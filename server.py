#!/usr/bin/env python3
"""
fortune0 Platform Server
========================

ONE command to launch everything:

    python3 server.py

Then open http://localhost:8080

This serves:
- The marketing site (index.html)
- The platform app (app.html)
- The storyboard (storyboard.html)
- All static assets (favicon, icons, CSS)
- The full REST API (/api/*)
- Real SQLite persistence

Zero dependencies. Pure Python stdlib.
"""

import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
import sys
import base64
import csv
import io
import urllib.request
import urllib.error
import urllib.parse
import math

# Optional: PostgreSQL support (for Render/production)
try:
    import psycopg2
    import psycopg2.extras
    HAS_PG = True
except ImportError:
    HAS_PG = False
import threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# ═══════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════

PORT = int(os.environ.get("PORT", os.environ.get("F0_PORT", 8080)))
SITE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SITE_DIR, "data")
LICENSE_SECRET = os.environ.get("F0_LICENSE_SECRET", "fortune0-dev-secret-2026")
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # Set for PostgreSQL (Render, etc.)
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")  # whsec_... from Stripe dashboard
STRIPE_PAYMENT_LINK = os.environ.get("STRIPE_PAYMENT_LINK", "")  # https://buy.stripe.com/xxxxx
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")  # sk_live_... or sk_test_... for API calls
ADMIN_EMAIL = os.environ.get("F0_ADMIN_EMAIL", "lolztex@gmail.com")  # Admin operations

os.makedirs(DATA_DIR, exist_ok=True)

# Commission tiers (platform fee on attributed revenue)
COMMISSION_TIERS = [
    (250_000, 0.03),
    (50_000, 0.035),
    (10_000, 0.04),
    (0, 0.05),
]

# In-memory sessions {token: {email, expires}}
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()

# ═══════════════════════════════════════════
#  CRYPTO
# ═══════════════════════════════════════════

def generate_referral_code(email):
    return f"IK-{hashlib.sha256(email.lower().encode()).hexdigest()[:8].upper()}"

def generate_license_key(email, days=28):
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
    payload = {"email": email.lower(), "expires": expires}
    payload_str = json.dumps(payload, sort_keys=True)
    sig = hmac.new(LICENSE_SECRET.encode(), payload_str.encode(), hashlib.sha256).hexdigest()[:16]
    payload["sig"] = sig
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"IK-{encoded}"

def validate_license_key(key):
    if not key or not key.startswith("IK-"):
        return None, "Invalid format"
    token = key[3:]
    padding = 4 - len(token) % 4
    if padding != 4:
        token += "=" * padding
    try:
        raw = base64.urlsafe_b64decode(token).decode()
        payload = json.loads(raw)
    except Exception:
        return None, "Cannot decode"
    sig = payload.pop("sig", "")
    payload_str = json.dumps(payload, sort_keys=True)
    expected = hmac.new(LICENSE_SECRET.encode(), payload_str.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None, "Invalid signature"
    try:
        exp = datetime.strptime(payload["expires"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            return payload, "Expired"
    except Exception:
        return None, "Bad expiry"
    return payload, "Valid"

# ═══════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    referral_code TEXT UNIQUE NOT NULL,
    license_key TEXT,
    tier TEXT DEFAULT 'free',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS affiliates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    referral_code TEXT UNIQUE NOT NULL,
    commission_rate REAL DEFAULT 0.10,
    total_earned REAL DEFAULT 0.0,
    total_referrals INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS commissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    affiliate_email TEXT NOT NULL,
    order_id TEXT NOT NULL UNIQUE,
    order_total REAL NOT NULL,
    commission_amount REAL NOT NULL,
    commission_rate REAL NOT NULL,
    platform_fee REAL NOT NULL DEFAULT 0,
    platform_fee_rate REAL NOT NULL DEFAULT 0.05,
    status TEXT DEFAULT 'pending',
    discount_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS referral_clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referral_code TEXT NOT NULL,
    source_domain TEXT,
    visitor_hash TEXT,
    converted INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL,
    source TEXT DEFAULT 'system',
    description TEXT,
    stripe_charge_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    referral_code TEXT UNIQUE NOT NULL,
    license_key TEXT,
    tier TEXT DEFAULT 'free',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS affiliates (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    referral_code TEXT UNIQUE NOT NULL,
    commission_rate REAL DEFAULT 0.10,
    total_earned REAL DEFAULT 0.0,
    total_referrals INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS commissions (
    id SERIAL PRIMARY KEY,
    affiliate_email TEXT NOT NULL,
    order_id TEXT NOT NULL UNIQUE,
    order_total REAL NOT NULL,
    commission_amount REAL NOT NULL,
    commission_rate REAL NOT NULL,
    platform_fee REAL NOT NULL DEFAULT 0,
    platform_fee_rate REAL NOT NULL DEFAULT 0.05,
    status TEXT DEFAULT 'pending',
    discount_code TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    user_email TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS activity (
    id SERIAL PRIMARY KEY,
    user_email TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS referral_clicks (
    id SERIAL PRIMARY KEY,
    referral_code TEXT NOT NULL,
    source_domain TEXT,
    visitor_hash TEXT,
    converted INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS credits (
    id SERIAL PRIMARY KEY,
    user_email TEXT NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL,
    source TEXT DEFAULT 'system',
    description TEXT,
    stripe_charge_id TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

USE_PG = bool(DATABASE_URL and HAS_PG)

class PGWrapper:
    """Wraps a psycopg2 connection to act like sqlite3 (? placeholders, dict rows, .execute on conn)."""
    def __init__(self, dsn):
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False
        # Create tables
        cur = self._conn.cursor()
        for stmt in SCHEMA_PG.split(';'):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        self._conn.commit()
        cur.close()

    def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params or [])
        return cur

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        self._conn.commit()
        cur.close()

    def commit(self):
        self._conn.commit()

    def close(self):
        try:
            self._conn.commit()
        except Exception:
            pass
        self._conn.close()

def get_db():
    if USE_PG:
        return PGWrapper(DATABASE_URL)
    else:
        db_path = os.path.join(DATA_DIR, "fortune0.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA_SQLITE)
        return conn

def log_activity(conn, user_email, action, detail=""):
    conn.execute("INSERT INTO activity (user_email, action, detail) VALUES (?, ?, ?)",
                 [user_email, action, detail])

# ═══════════════════════════════════════════
#  STRIPE API (stdlib only — no pip install)
# ═══════════════════════════════════════════

def stripe_get(endpoint, params=None):
    """Call Stripe API using urllib. Returns parsed JSON or None on error."""
    if not STRIPE_SECRET_KEY:
        return None
    url = f"https://api.stripe.com/v1/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    auth = base64.b64encode(f"{STRIPE_SECRET_KEY}:".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        sys.stderr.write(f"  Stripe API error: {e}\n")
        return None

def calculate_credits(amount_cents, payment_timestamp):
    """Calculate credits from a Stripe payment.
    Base: $1 = 100 credits.
    Loyalty bonus: +10 credits per month since payment (retroactive).
    """
    amount_dollars = amount_cents / 100
    base_credits = amount_dollars * 100  # $1 = 100 credits

    # Months since payment
    now = datetime.now(timezone.utc)
    try:
        paid_at = datetime.fromtimestamp(payment_timestamp, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        paid_at = now
    months_elapsed = max(0, (now - paid_at).days / 30)
    loyalty_bonus = math.floor(months_elapsed) * 10  # 10 credits per month

    total = round(base_credits + loyalty_bonus, 2)
    return total, base_credits, loyalty_bonus, paid_at

# ═══════════════════════════════════════════
#  AUTH / SESSIONS
# ═══════════════════════════════════════════

def create_session(email):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    with SESSIONS_LOCK:
        SESSIONS[token] = {"email": email.lower(), "expires": expires}
    return token

def get_session(token):
    if not token:
        return None
    with SESSIONS_LOCK:
        sess = SESSIONS.get(token)
        if not sess:
            return None
        if sess["expires"] < datetime.now(timezone.utc):
            del SESSIONS[token]
            return None
        return sess

# ═══════════════════════════════════════════
#  COMMISSION LOGIC
# ═══════════════════════════════════════════

def get_platform_fee_rate(monthly):
    for threshold, rate in COMMISSION_TIERS:
        if monthly >= threshold:
            return rate
    return 0.05

# ═══════════════════════════════════════════
#  HTTP HANDLER
# ═══════════════════════════════════════════

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0]) or "POST" in str(args[0]):
            sys.stderr.write(f"  {args[0]}\n")

    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_csv(self, filename, rows, fieldnames):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        body = output.getvalue().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, filepath):
        if not os.path.isfile(filepath):
            self.send_json({"error": "Not found"}, 404)
            return
        mime, _ = mimetypes.guess_type(filepath)
        if mime is None:
            mime = "application/octet-stream"
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(content))
        # No caching in dev so edits show up instantly
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(content)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def get_user(self):
        auth = self.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
        return get_session(token)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    # ─── GET ───
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        # ── API routes ──
        if path == "/health":
            db_type = "postgresql" if USE_PG else "sqlite"
            stripe_configured = bool(STRIPE_WEBHOOK_SECRET)
            payment_link_set = bool(STRIPE_PAYMENT_LINK)
            conn = get_db()
            stripe_api_set = bool(STRIPE_SECRET_KEY)
            try:
                user_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
                affiliate_count = conn.execute("SELECT COUNT(*) c FROM affiliates").fetchone()["c"]
                active_users = conn.execute("SELECT COUNT(*) c FROM users WHERE tier='active'").fetchone()["c"]
                total_revenue = conn.execute("SELECT COALESCE(SUM(order_total),0) s FROM commissions").fetchone()["s"]
                total_credits = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM credits WHERE amount > 0").fetchone()["s"]
                credits_spent = conn.execute("SELECT COALESCE(SUM(ABS(amount)),0) s FROM credits WHERE amount < 0").fetchone()["s"]
                credits_imported = conn.execute("SELECT COUNT(*) c FROM credits WHERE source='stripe_import'").fetchone()["c"]
            except Exception:
                user_count = affiliate_count = active_users = 0
                total_revenue = total_credits = credits_spent = credits_imported = 0
            conn.close()
            self.send_json({
                "status": "ok", "service": "fortune0", "version": "1.2.0",
                "db": db_type,
                "stripe_webhook": "configured" if stripe_configured else "not set",
                "stripe_payment_link": "configured" if payment_link_set else "not set",
                "stripe_api": "configured" if stripe_api_set else "not set",
                "users": user_count,
                "active_users": active_users,
                "affiliates": affiliate_count,
                "total_revenue": round(total_revenue, 2),
                "total_credits_issued": round(total_credits, 2),
                "total_credits_spent": round(credits_spent, 2),
                "credits_from_stripe": credits_imported,
            })

        elif path == "/api/stats":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            email = sess["email"]
            contacts = conn.execute("SELECT COUNT(*) c FROM contacts WHERE user_email=?", [email]).fetchone()["c"]
            affiliates = conn.execute("SELECT COUNT(*) c FROM affiliates").fetchone()["c"]
            comms = conn.execute("SELECT COUNT(*) c FROM commissions").fetchone()["c"]
            revenue = conn.execute("SELECT COALESCE(SUM(order_total),0) s FROM commissions").fetchone()["s"]
            aff_pay = conn.execute("SELECT COALESCE(SUM(commission_amount),0) s FROM commissions").fetchone()["s"]
            plat_rev = conn.execute("SELECT COALESCE(SUM(platform_fee),0) s FROM commissions").fetchone()["s"]
            recent = conn.execute("SELECT * FROM activity WHERE user_email=? ORDER BY created_at DESC LIMIT 20", [email]).fetchall()
            conn.close()
            self.send_json({
                "contacts": contacts, "affiliates": affiliates, "commissions": comms,
                "attributed_revenue": round(revenue, 2),
                "affiliate_payouts": round(aff_pay, 2),
                "platform_revenue": round(plat_rev, 2),
                "activity": [dict(r) for r in recent],
            })

        elif path == "/api/contacts":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            q = qs.get("q", [""])[0]
            if q:
                rows = conn.execute("SELECT * FROM contacts WHERE user_email=? AND (name LIKE ? OR email LIKE ? OR company LIKE ?) ORDER BY created_at DESC",
                                    [sess["email"], f"%{q}%", f"%{q}%", f"%{q}%"]).fetchall()
            else:
                rows = conn.execute("SELECT * FROM contacts WHERE user_email=? ORDER BY created_at DESC", [sess["email"]]).fetchall()
            conn.close()
            self.send_json([dict(r) for r in rows])

        elif path == "/api/affiliates":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            rows = conn.execute("SELECT * FROM affiliates ORDER BY total_earned DESC").fetchall()
            conn.close()
            self.send_json([dict(r) for r in rows])

        elif path == "/api/commissions":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            rows = conn.execute("SELECT * FROM commissions ORDER BY created_at DESC LIMIT 100").fetchall()
            conn.close()
            self.send_json([dict(r) for r in rows])

        # ── Leaderboard (public, anonymized) ──
        elif path == "/api/leaderboard":
            conn = get_db()
            affs_raw = conn.execute("""
                SELECT a.referral_code, a.commission_rate, a.total_referrals, a.total_earned,
                       COALESCE(cr.balance, 0) as credit_balance,
                       u.tier
                FROM affiliates a
                LEFT JOIN users u ON u.email = a.email
                LEFT JOIN (
                    SELECT user_email, SUM(amount) as balance FROM credits GROUP BY user_email
                ) cr ON cr.user_email = a.email
                WHERE a.email NOT LIKE '%@example.com'
                  AND a.email NOT LIKE '%@fortune0.com'
                ORDER BY a.total_earned DESC
                LIMIT 25
            """).fetchall()

            # Anonymize: hash the referral code, only show prefix + hash
            affs = []
            for r in affs_raw:
                d = dict(r)
                code = d.get("referral_code", "")
                anon = hashlib.sha256(code.encode()).hexdigest()[:6].upper()
                d["referral_code"] = f"F0-{anon}"
                d["credit_balance"] = round(d.get("credit_balance", 0), 0)
                affs.append(d)

            # Platform totals
            total_users = conn.execute("SELECT COUNT(*) c FROM users WHERE email NOT LIKE '%@example.com' AND email NOT LIKE '%@fortune0.com'").fetchone()["c"]
            active_users = conn.execute("SELECT COUNT(*) c FROM users WHERE tier='active' AND email NOT LIKE '%@example.com' AND email NOT LIKE '%@fortune0.com'").fetchone()["c"]
            total_revenue = conn.execute("SELECT COALESCE(SUM(order_total),0) s FROM commissions WHERE affiliate_email NOT LIKE '%@example.com'").fetchone()["s"]
            total_credits = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM credits WHERE amount > 0 AND user_email NOT LIKE '%@example.com'").fetchone()["s"]

            conn.close()
            self.send_json({
                "leaderboard": affs,
                "platform": {
                    "total_users": total_users,
                    "active_users": active_users,
                    "total_revenue": round(total_revenue, 2),
                    "total_credits": round(total_credits, 2),
                },
            })

        # ── Data export (CSV) ──
        elif path == "/api/export/contacts":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            rows = conn.execute("SELECT name, email, phone, company, notes, created_at FROM contacts WHERE user_email=? ORDER BY created_at DESC",
                                [sess["email"]]).fetchall()
            conn.close()
            self.send_csv("contacts.csv", [dict(r) for r in rows],
                         ["name", "email", "phone", "company", "notes", "created_at"])

        elif path == "/api/export/commissions":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            rows = conn.execute("SELECT order_id, order_total, commission_amount, commission_rate, platform_fee, status, discount_code, created_at FROM commissions WHERE affiliate_email=? ORDER BY created_at DESC",
                                [sess["email"]]).fetchall()
            conn.close()
            self.send_csv("commissions.csv", [dict(r) for r in rows],
                         ["order_id", "order_total", "commission_amount", "commission_rate", "platform_fee", "status", "discount_code", "created_at"])

        elif path == "/api/export/activity":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            rows = conn.execute("SELECT action, detail, created_at FROM activity WHERE user_email=? ORDER BY created_at DESC",
                                [sess["email"]]).fetchall()
            conn.close()
            self.send_csv("activity.csv", [dict(r) for r in rows],
                         ["action", "detail", "created_at"])

        elif path == "/api/export/all":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            email = sess["email"]
            user = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
            contacts = conn.execute("SELECT name, email, phone, company, notes, created_at FROM contacts WHERE user_email=?", [email]).fetchall()
            comms = conn.execute("SELECT * FROM commissions WHERE affiliate_email=?", [email]).fetchall()
            activity = conn.execute("SELECT action, detail, created_at FROM activity WHERE user_email=?", [email]).fetchall()
            aff = conn.execute("SELECT * FROM affiliates WHERE email=?", [email]).fetchone()
            conn.close()
            ud = dict(user) if user else {}
            ad = dict(aff) if aff else {}
            self.send_json({
                "user": {k: str(v) for k, v in ud.items() if k != "license_key"},
                "affiliate": {k: str(v) for k, v in ad.items()},
                "contacts": [dict(r) for r in contacts],
                "commissions": [dict(r) for r in comms],
                "activity": [dict(r) for r in activity],
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "format_version": "1.0",
            })

        # ── Credit balance + history ──
        elif path == "/api/credits":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            email = sess["email"]
            balance_row = conn.execute("SELECT COALESCE(SUM(amount),0) bal FROM credits WHERE user_email=?", [email]).fetchone()
            balance = round(balance_row["bal"], 2)
            history = conn.execute("SELECT id, amount, type, source, description, created_at FROM credits WHERE user_email=? ORDER BY created_at DESC LIMIT 50", [email]).fetchall()
            # Count by type
            granted = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM credits WHERE user_email=? AND type='granted'", [email]).fetchone()["s"]
            purchased = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM credits WHERE user_email=? AND type='purchased'", [email]).fetchone()["s"]
            spent = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM credits WHERE user_email=? AND type='spent'", [email]).fetchone()["s"]
            conn.close()
            self.send_json({
                "balance": balance,
                "total_granted": round(granted, 2),
                "total_purchased": round(purchased, 2),
                "total_spent": round(abs(spent), 2),
                "history": [dict(r) for r in history],
            })

        elif path == "/api/me":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE email=?", [sess["email"]]).fetchone()
            # Include credit balance
            balance_row = conn.execute("SELECT COALESCE(SUM(amount),0) bal FROM credits WHERE user_email=?", [sess["email"]]).fetchone()
            conn.close()
            if user:
                ud = dict(user)
                ud["credit_balance"] = round(balance_row["bal"], 2)
                self.send_json(ud)
            else:
                self.send_json({"error": "User not found"}, 404)

        # ── Affiliate click stats ──
        elif path == "/api/affiliate/stats":
            code = qs.get("code", [""])[0]
            if not code:
                self.send_json({"error": "Code required"}, 400); return
            conn = get_db()
            aff = conn.execute("SELECT * FROM affiliates WHERE referral_code=?", [code]).fetchone()
            if not aff:
                conn.close()
                self.send_json({"error": "Not found"}, 404); return
            clicks = conn.execute("SELECT COUNT(*) c FROM referral_clicks WHERE referral_code=?", [code]).fetchone()["c"]
            conversions = conn.execute("SELECT COUNT(*) c FROM referral_clicks WHERE referral_code=? AND converted=1", [code]).fetchone()["c"]
            conn.close()
            self.send_json({
                "code": code,
                "email": aff["email"],
                "clicks": clicks,
                "conversions": conversions,
                "conversion_rate": round(conversions / clicks * 100, 1) if clicks > 0 else 0,
                "total_earned": aff["total_earned"],
                "total_referrals": aff["total_referrals"],
                "commission_rate": aff["commission_rate"],
            })

        # ── Profile page: /u/IK-XXXXXXXX ──
        elif path.startswith("/u/"):
            # Serve the profile page template — JS fetches /api/profile/CODE
            self.send_file(os.path.join(SITE_DIR, "profile.html"))

        # ── Profile API: /api/profile/IK-XXXXXXXX ──
        elif path.startswith("/api/profile/"):
            code = path[len("/api/profile/"):]
            if not code:
                self.send_json({"error": "Code required"}, 400); return
            conn = get_db()
            # Look up user by referral code
            user = conn.execute("SELECT * FROM users WHERE referral_code=?", [code]).fetchone()
            if not user:
                conn.close()
                self.send_json({"error": "Not found"}, 404); return
            # Get affiliate stats if they have them
            aff = conn.execute("SELECT * FROM affiliates WHERE referral_code=?", [code]).fetchone()
            clicks = conn.execute("SELECT COUNT(*) c FROM referral_clicks WHERE referral_code=?", [code]).fetchone()["c"]
            conn.close()
            ud = dict(user)
            ad = dict(aff) if aff else {}
            profile = {
                "code": code,
                "email_hash": hashlib.sha256(ud["email"].encode()).hexdigest()[:8],  # anonymous
                "tier": ud.get("tier", "free"),
                "member_since": str(ud.get("created_at", "")),
                "clicks": clicks,
                "referrals": ad.get("total_referrals", 0),
                "commission_rate": ad.get("commission_rate", 0.10),
                "earned": round(ad.get("total_earned", 0), 2),
            }
            self.send_json(profile)

        # ── Referral redirect: /r/IK-XXXXXXXX ──
        elif path.startswith("/r/"):
            code = path[3:]  # strip "/r/"
            if not code:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers(); return
            conn = get_db()
            aff = conn.execute("SELECT * FROM affiliates WHERE referral_code=?", [code]).fetchone()
            # Log the click (anonymize visitor via hash of IP + UA)
            visitor_raw = (self.client_address[0] + self.headers.get("User-Agent", "")).encode()
            visitor_hash = hashlib.sha256(visitor_raw).hexdigest()[:16]
            source_domain = self.headers.get("Host", "direct")
            conn.execute("INSERT INTO referral_clicks (referral_code, source_domain, visitor_hash) VALUES (?, ?, ?)",
                         [code, source_domain, visitor_hash])
            conn.commit()
            conn.close()
            # Redirect to profile page (which has the join CTA)
            self.send_response(302)
            self.send_header("Location", f"/u/{code}")
            self.end_headers()

        # ── Static files ──
        elif path == "/":
            self.send_file(os.path.join(SITE_DIR, "index.html"))
        else:
            # Try serving: exact file, then clean URL (.html), then 404
            safe_path = path.lstrip("/")
            filepath = os.path.join(SITE_DIR, safe_path)
            html_path = os.path.join(SITE_DIR, safe_path + ".html")

            # Prevent directory traversal
            if os.path.commonpath([filepath, SITE_DIR]) != SITE_DIR:
                self.send_json({"error": "Not found", "path": path}, 404)
            elif os.path.isfile(filepath):
                self.send_file(filepath)
            elif os.path.isfile(html_path):
                self.send_file(html_path)
            else:
                # Serve custom 404 page if it exists
                page_404 = os.path.join(SITE_DIR, "404.html")
                if os.path.isfile(page_404):
                    self.send_file(page_404)
                else:
                    self.send_json({"error": "Not found", "path": path}, 404)

    # ─── POST ───
    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        body = self.read_body()

        # ── Signup (create free account) ──
        if path == "/api/signup":
            email = body.get("email", "").strip().lower()
            if not email or "@" not in email:
                self.send_json({"error": "Valid email required"}, 400); return

            conn = get_db()
            existing = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
            if existing:
                # Already exists — just log them in
                token = create_session(email)
                log_activity(conn, email, "login", "Returning user")
                conn.commit(); conn.close()
                self.send_json({
                    "token": token, "email": email,
                    "referral_code": existing["referral_code"],
                    "tier": existing["tier"], "new": False,
                })
                return

            ref_code = generate_referral_code(email)
            license_key = generate_license_key(email)
            conn.execute("INSERT INTO users (email, referral_code, license_key, tier) VALUES (?, ?, ?, 'free')",
                         [email, ref_code, license_key])
            log_activity(conn, email, "signup", f"New account: {ref_code}")
            conn.commit(); conn.close()

            token = create_session(email)
            self.send_json({
                "token": token, "email": email,
                "referral_code": ref_code, "license_key": license_key,
                "tier": "free", "new": True,
            })

        # ── Login (with license key) ──
        elif path == "/api/login":
            email = body.get("email", "").strip().lower()
            key = body.get("key", "").strip()
            if not email or not key:
                self.send_json({"error": "Email and key required"}, 400); return
            payload, msg = validate_license_key(key)
            if not payload or msg != "Valid":
                self.send_json({"error": msg}, 401); return
            if payload.get("email", "").lower() != email:
                self.send_json({"error": "Key doesn't match email"}, 401); return
            conn = get_db()
            log_activity(conn, email, "login", "License key auth")
            conn.commit(); conn.close()
            token = create_session(email)
            self.send_json({"token": token, "email": email})

        # ── Add contact ──
        elif path == "/api/contacts":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            name = body.get("name", "").strip()
            if not name:
                self.send_json({"error": "Name required"}, 400); return
            conn = get_db()
            conn.execute("INSERT INTO contacts (user_email, name, email, phone, company, notes) VALUES (?, ?, ?, ?, ?, ?)",
                         [sess["email"], name, body.get("email",""), body.get("phone",""), body.get("company",""), body.get("notes","")])
            log_activity(conn, sess["email"], "contact_added", f"Added: {name}")
            conn.commit()
            row = conn.execute("SELECT * FROM contacts WHERE user_email=? AND name=? ORDER BY id DESC LIMIT 1", [sess["email"], name]).fetchone()
            conn.close()
            self.send_json(dict(row), 201)

        # ── Register affiliate ──
        elif path == "/api/affiliates":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            email = body.get("email", "").strip().lower()
            rate = float(body.get("commission_rate", 0.10))
            if not email:
                self.send_json({"error": "Email required"}, 400); return
            code = generate_referral_code(email)
            conn = get_db()
            existing = conn.execute("SELECT * FROM affiliates WHERE email=?", [email]).fetchone()
            if existing:
                conn.close()
                self.send_json(dict(existing))
                return
            conn.execute("INSERT INTO affiliates (email, referral_code, commission_rate) VALUES (?, ?, ?)",
                         [email, code, rate])
            log_activity(conn, sess["email"], "affiliate_registered", f"{email} → {code}")
            conn.commit()
            row = conn.execute("SELECT * FROM affiliates WHERE email=?", [email]).fetchone()
            conn.close()
            self.send_json(dict(row), 201)

        # ── Shopify order webhook (attribution) ──
        elif path == "/api/webhooks/order":
            code = body.get("discount_code", "").strip()
            total = float(body.get("order_total", 0))
            order_id = body.get("order_id", f"ORD-{secrets.token_hex(4).upper()}")
            if not code:
                self.send_json({"error": "Discount code required"}, 400); return

            conn = get_db()
            aff = conn.execute("SELECT * FROM affiliates WHERE referral_code=?", [code]).fetchone()
            if not aff:
                conn.close()
                self.send_json({"error": f"No affiliate for code '{code}'", "attributed": False}, 404)
                return

            rate = aff["commission_rate"]
            commission = round(total * rate, 2)
            monthly = aff["total_earned"] + commission
            fee_rate = get_platform_fee_rate(monthly)
            fee = round(total * fee_rate, 2)

            try:
                conn.execute("""INSERT INTO commissions
                    (affiliate_email, order_id, order_total, commission_amount, commission_rate,
                     platform_fee, platform_fee_rate, status, discount_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                    [aff["email"], order_id, total, commission, rate, fee, fee_rate, code])
                conn.execute("UPDATE affiliates SET total_earned=total_earned+?, total_referrals=total_referrals+1 WHERE email=?",
                             [commission, aff["email"]])
                log_activity(conn, aff["email"], "commission", f"${commission} from order {order_id}")
                conn.commit()
            except (sqlite3.IntegrityError, Exception) as e:
                if "UNIQUE" in str(e).upper() or "duplicate" in str(e).lower() or isinstance(e, sqlite3.IntegrityError):
                    conn.close()
                    self.send_json({"error": "Duplicate order ID", "attributed": False}, 409)
                    return
                raise

            conn.close()
            self.send_json({
                "attributed": True, "affiliate": aff["email"],
                "commission": commission, "platform_fee": fee,
                "order_id": order_id,
            })

        # ── Update contact ──
        elif path == "/api/contacts/update":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            cid = body.get("id")
            if not cid:
                self.send_json({"error": "ID required"}, 400); return
            conn = get_db()
            # Only update fields that were sent
            updates = []
            vals = []
            for field in ["name", "email", "phone", "company", "notes"]:
                if field in body:
                    updates.append(f"{field}=?")
                    vals.append(body[field])
            if not updates:
                conn.close()
                self.send_json({"error": "No fields to update"}, 400); return
            vals.extend([cid, sess["email"]])
            conn.execute(f"UPDATE contacts SET {','.join(updates)} WHERE id=? AND user_email=?", vals)
            log_activity(conn, sess["email"], "contact_updated", f"Updated contact #{cid}")
            conn.commit()
            row = conn.execute("SELECT * FROM contacts WHERE id=?", [cid]).fetchone()
            conn.close()
            self.send_json(dict(row) if row else {"error": "Not found"}, 200 if row else 404)

        # ── Delete contact ──
        elif path == "/api/contacts/delete":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            cid = body.get("id")
            if not cid:
                self.send_json({"error": "ID required"}, 400); return
            conn = get_db()
            conn.execute("DELETE FROM contacts WHERE id=? AND user_email=?", [cid, sess["email"]])
            log_activity(conn, sess["email"], "contact_deleted", f"Deleted contact #{cid}")
            conn.commit(); conn.close()
            self.send_json({"deleted": True})

        # ── Self-service affiliate join (no auth required) ──
        elif path == "/api/join":
            email = body.get("email", "").strip().lower()
            referred_by = body.get("referred_by", "").strip()  # referral code of who sent them
            if not email or "@" not in email:
                self.send_json({"error": "Valid email required"}, 400); return
            code = generate_referral_code(email)
            conn = get_db()
            existing = conn.execute("SELECT * FROM affiliates WHERE email=?", [email]).fetchone()
            if existing:
                clicks = conn.execute("SELECT COUNT(*) c FROM referral_clicks WHERE referral_code=?", [existing["referral_code"]]).fetchone()["c"]
                conn.close()
                d = dict(existing)
                d["clicks"] = clicks
                d["short_url"] = f"/r/{existing['referral_code']}"
                d["profile_url"] = f"/u/{existing['referral_code']}"
                d["returning"] = True
                self.send_json(d)
                return
            conn.execute("INSERT INTO affiliates (email, referral_code, commission_rate) VALUES (?, ?, 0.10)",
                         [email, code])
            # Track who referred this person
            if referred_by:
                referrer = conn.execute("SELECT * FROM affiliates WHERE referral_code=?", [referred_by]).fetchone()
                if referrer:
                    conn.execute("UPDATE affiliates SET total_referrals=total_referrals+1 WHERE referral_code=?", [referred_by])
                    log_activity(conn, referrer["email"], "referral_signup", f"{email} joined through {referred_by}")
                    # Mark the most recent referral click as converted
                    if USE_PG:
                        conn.execute("UPDATE referral_clicks SET converted=1 WHERE id=(SELECT id FROM referral_clicks WHERE referral_code=? AND converted=0 ORDER BY created_at DESC LIMIT 1)", [referred_by])
                    else:
                        conn.execute("UPDATE referral_clicks SET converted=1 WHERE referral_code=? AND converted=0 ORDER BY created_at DESC LIMIT 1", [referred_by])
            # Also create a user account
            license_key = generate_license_key(email)
            try:
                conn.execute("INSERT INTO users (email, referral_code, license_key, tier) VALUES (?, ?, ?, 'free')",
                             [email, code, license_key])
            except Exception:
                pass  # user already exists
            log_activity(conn, email, "affiliate_joined", f"Self-service: {code}")
            conn.commit()
            row = conn.execute("SELECT * FROM affiliates WHERE email=?", [email]).fetchone()
            conn.close()
            token = create_session(email)
            d = dict(row)
            d["token"] = token
            d["license_key"] = license_key
            d["short_url"] = f"/r/{code}"
            d["profile_url"] = f"/u/{code}"
            d["clicks"] = 0
            d["returning"] = False
            self.send_json(d, 201)

        # ── Stripe webhook (payment confirmation) ──
        elif path == "/api/webhooks/stripe":
            # Stripe sends checkout.session.completed with client_reference_id = referral code
            # Verify signature if webhook secret is set
            raw_body = json.dumps(body).encode()
            sig_header = self.headers.get("Stripe-Signature", "")

            if STRIPE_WEBHOOK_SECRET and sig_header:
                # Verify Stripe webhook signature
                # Stripe signs: timestamp.payload
                # For now we do a simple HMAC check on the payload
                # In production, use stripe library's verify method
                try:
                    parts = dict(item.split("=", 1) for item in sig_header.split(","))
                    timestamp = parts.get("t", "")
                    expected_sig = parts.get("v1", "")
                    signed_payload = f"{timestamp}.{raw_body.decode()}"
                    computed = hmac.new(
                        STRIPE_WEBHOOK_SECRET.encode(),
                        signed_payload.encode(),
                        hashlib.sha256
                    ).hexdigest()
                    if not hmac.compare_digest(computed, expected_sig):
                        self.send_json({"error": "Invalid signature"}, 401)
                        return
                except Exception:
                    pass  # If parsing fails, still process (dev mode)

            # Handle the event
            event_type = body.get("type", "")
            if event_type == "checkout.session.completed":
                session_data = body.get("data", {}).get("object", {})
                ref_code = session_data.get("client_reference_id", "")
                customer_email = session_data.get("customer_email", "") or session_data.get("customer_details", {}).get("email", "")
                amount = session_data.get("amount_total", 0) / 100  # cents to dollars

                if not ref_code and not customer_email:
                    self.send_json({"error": "No reference ID or email"}, 400)
                    return

                conn = get_db()

                # Find the user by referral code or email
                user = None
                if ref_code:
                    user = conn.execute("SELECT * FROM users WHERE referral_code=?", [ref_code]).fetchone()
                if not user and customer_email:
                    user = conn.execute("SELECT * FROM users WHERE email=?", [customer_email.lower()]).fetchone()

                if user:
                    ud = dict(user)
                    email = ud["email"]
                    code = ud["referral_code"]

                    # Activate: free -> active
                    conn.execute("UPDATE users SET tier='active' WHERE email=?", [email])
                    log_activity(conn, email, "payment", f"${amount} via Stripe — tier activated")

                    # Generate a fresh license key (28 days from now)
                    new_key = generate_license_key(email, days=28)
                    conn.execute("UPDATE users SET license_key=? WHERE email=?", [new_key, email])

                    conn.commit()
                    conn.close()
                    self.send_json({"activated": True, "email": email, "code": code, "tier": "active"})
                else:
                    # Payment came in but no matching account — create one
                    if customer_email:
                        code = generate_referral_code(customer_email)
                        key = generate_license_key(customer_email, days=28)
                        try:
                            conn.execute("INSERT INTO users (email, referral_code, license_key, tier) VALUES (?, ?, ?, 'active')",
                                         [customer_email.lower(), code, key])
                            conn.execute("INSERT INTO affiliates (email, referral_code, commission_rate) VALUES (?, ?, 0.10)",
                                         [customer_email.lower(), code])
                            log_activity(conn, customer_email, "payment_signup", f"${amount} via Stripe — new active account")
                            conn.commit()
                        except Exception:
                            pass
                    conn.close()
                    self.send_json({"activated": True, "new_account": True, "email": customer_email})
            else:
                # Other event types — acknowledge but ignore
                self.send_json({"received": True})

        # ── Account recovery (email lookup) ──
        elif path == "/api/recover":
            email = body.get("email", "").strip().lower()
            if not email or "@" not in email:
                self.send_json({"error": "Valid email required"}, 400); return

            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
            if not user:
                conn.close()
                # Don't reveal whether email exists — just say "check your email"
                self.send_json({"sent": True})
                return

            ud = dict(user)
            token = create_session(email)
            log_activity(conn, email, "recovery", "Account recovered via email")
            conn.commit()
            conn.close()

            self.send_json({
                "token": token,
                "email": email,
                "referral_code": ud["referral_code"],
                "tier": ud.get("tier", "free"),
                "profile_url": f"/u/{ud['referral_code']}",
            })

        # ── Get activation link (returns Stripe payment URL with code attached) ──
        elif path == "/api/activate":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return

            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE email=?", [sess["email"]]).fetchone()
            conn.close()

            if not user:
                self.send_json({"error": "User not found"}, 404); return

            ud = dict(user)
            if ud.get("tier") == "active":
                self.send_json({"already_active": True, "tier": "active"})
                return

            if STRIPE_PAYMENT_LINK:
                payment_url = f"{STRIPE_PAYMENT_LINK}?client_reference_id={ud['referral_code']}"
            else:
                payment_url = None

            self.send_json({
                "tier": "free",
                "payment_url": payment_url,
                "referral_code": ud["referral_code"],
            })

        # ── Sync Stripe payment history → credits ──
        elif path == "/api/admin/sync-stripe":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            if sess["email"] != ADMIN_EMAIL:
                self.send_json({"error": "Admin only"}, 403); return
            if not STRIPE_SECRET_KEY:
                self.send_json({"error": "STRIPE_SECRET_KEY not configured"}, 400); return

            # Pull all successful charges from Stripe (paginate)
            all_charges = []
            has_more = True
            starting_after = None
            while has_more:
                params = {"limit": 100, "status": "succeeded"}
                if starting_after:
                    params["starting_after"] = starting_after
                data = stripe_get("charges", params)
                if not data or "data" not in data:
                    break
                charges = data["data"]
                all_charges.extend(charges)
                has_more = data.get("has_more", False)
                if charges:
                    starting_after = charges[-1]["id"]

            # Also pull customers for email mapping
            all_customers = []
            has_more = True
            starting_after = None
            while has_more:
                params = {"limit": 100}
                if starting_after:
                    params["starting_after"] = starting_after
                data = stripe_get("customers", params)
                if not data or "data" not in data:
                    break
                customers = data["data"]
                all_customers.extend(customers)
                has_more = data.get("has_more", False)
                if customers:
                    starting_after = customers[-1]["id"]

            # Build customer ID → email map
            cust_emails = {}
            for c in all_customers:
                if c.get("email"):
                    cust_emails[c["id"]] = c["email"].lower()

            conn = get_db()
            imported = 0
            skipped = 0
            created_accounts = 0

            for charge in all_charges:
                charge_id = charge["id"]
                amount_cents = charge.get("amount", 0)
                created_ts = charge.get("created", 0)
                customer_id = charge.get("customer", "")

                # Get email from charge or customer
                email = ""
                if charge.get("billing_details", {}).get("email"):
                    email = charge["billing_details"]["email"].lower()
                elif charge.get("receipt_email"):
                    email = charge["receipt_email"].lower()
                elif customer_id and customer_id in cust_emails:
                    email = cust_emails[customer_id]

                if not email or amount_cents <= 0:
                    skipped += 1
                    continue

                # Check if already imported
                existing = conn.execute("SELECT id FROM credits WHERE stripe_charge_id=?", [charge_id]).fetchone()
                if existing:
                    skipped += 1
                    continue

                # Calculate credits
                total_credits, base, loyalty, paid_at = calculate_credits(amount_cents, created_ts)

                # Ensure user exists
                user = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
                if not user:
                    code = generate_referral_code(email)
                    key = generate_license_key(email, days=28)
                    try:
                        conn.execute("INSERT INTO users (email, referral_code, license_key, tier) VALUES (?, ?, ?, 'active')",
                                     [email, code, key])
                        conn.execute("INSERT INTO affiliates (email, referral_code, commission_rate) VALUES (?, ?, 0.10)",
                                     [email, code])
                        created_accounts += 1
                    except Exception:
                        pass

                # Always activate since they paid
                conn.execute("UPDATE users SET tier='active' WHERE email=?", [email])

                # Insert credit entry
                desc = f"${amount_cents/100:.2f} payment on {paid_at.strftime('%Y-%m-%d')} ({int(base)} base + {int(loyalty)} loyalty)"
                conn.execute(
                    "INSERT INTO credits (user_email, amount, type, source, description, stripe_charge_id) VALUES (?, ?, 'granted', 'stripe_import', ?, ?)",
                    [email, total_credits, desc, charge_id]
                )
                log_activity(conn, email, "credits_granted", f"{total_credits} credits from Stripe import")
                imported += 1

            conn.commit()

            # Summary stats
            total_credits_issued = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM credits WHERE source='stripe_import'").fetchone()["s"]
            conn.close()

            self.send_json({
                "synced": True,
                "charges_found": len(all_charges),
                "customers_found": len(all_customers),
                "credits_imported": imported,
                "skipped_duplicate": skipped,
                "accounts_created": created_accounts,
                "total_credits_issued": round(total_credits_issued, 2),
            })

        # ── Manual credit grant (admin) ──
        elif path == "/api/admin/grant-credits":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            if sess["email"] != ADMIN_EMAIL:
                self.send_json({"error": "Admin only"}, 403); return

            target_email = body.get("email", "").strip().lower()
            amount = float(body.get("amount", 0))
            reason = body.get("reason", "Manual grant")

            if not target_email or amount <= 0:
                self.send_json({"error": "Email and positive amount required"}, 400); return

            conn = get_db()
            conn.execute(
                "INSERT INTO credits (user_email, amount, type, source, description) VALUES (?, ?, 'granted', 'admin', ?)",
                [target_email, amount, reason]
            )
            log_activity(conn, target_email, "credits_granted", f"{amount} credits: {reason}")
            conn.commit()
            balance = conn.execute("SELECT COALESCE(SUM(amount),0) bal FROM credits WHERE user_email=?", [target_email]).fetchone()["bal"]
            conn.close()
            self.send_json({"granted": True, "email": target_email, "amount": amount, "new_balance": round(balance, 2)})

        # ── Admin: purge test data ──
        elif path == "/api/admin/purge-test-data":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            if sess["email"] != ADMIN_EMAIL:
                self.send_json({"error": "Admin only"}, 403); return

            conn = get_db()
            # Test patterns to clean
            test_patterns = ['%@example.com', '%@fortune0.com']
            purged = {"users": 0, "affiliates": 0, "contacts": 0, "commissions": 0, "credits": 0, "activity": 0}

            for pattern in test_patterns:
                purged["users"] += conn.execute("DELETE FROM users WHERE email LIKE ?", [pattern]).rowcount
                purged["affiliates"] += conn.execute("DELETE FROM affiliates WHERE email LIKE ?", [pattern]).rowcount
                purged["contacts"] += conn.execute("DELETE FROM contacts WHERE user_email LIKE ?", [pattern]).rowcount
                purged["commissions"] += conn.execute("DELETE FROM commissions WHERE affiliate_email LIKE ?", [pattern]).rowcount
                purged["credits"] += conn.execute("DELETE FROM credits WHERE user_email LIKE ?", [pattern]).rowcount
                purged["activity"] += conn.execute("DELETE FROM activity WHERE user_email LIKE ?", [pattern]).rowcount

            conn.commit()
            total = sum(purged.values())
            log_activity(conn, sess["email"], "admin_purge", f"Purged {total} test records")
            conn.commit()
            conn.close()

            self.send_json({"purged": True, "records_removed": purged, "total": total})

        # ── Spend credits ──
        elif path == "/api/credits/spend":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return

            amount = float(body.get("amount", 0))
            reason = body.get("reason", "")
            if amount <= 0:
                self.send_json({"error": "Amount must be positive"}, 400); return

            conn = get_db()
            email = sess["email"]
            balance = conn.execute("SELECT COALESCE(SUM(amount),0) bal FROM credits WHERE user_email=?", [email]).fetchone()["bal"]
            if balance < amount:
                conn.close()
                self.send_json({"error": "Insufficient credits", "balance": round(balance, 2), "requested": amount}, 400)
                return

            conn.execute(
                "INSERT INTO credits (user_email, amount, type, source, description) VALUES (?, ?, 'spent', 'user', ?)",
                [email, -amount, reason]
            )
            log_activity(conn, email, "credits_spent", f"{amount} credits: {reason}")
            conn.commit()
            new_balance = conn.execute("SELECT COALESCE(SUM(amount),0) bal FROM credits WHERE user_email=?", [email]).fetchone()["bal"]
            conn.close()
            self.send_json({"spent": True, "amount": amount, "new_balance": round(new_balance, 2)})

        else:
            self.send_json({"error": "Not found"}, 404)

# ═══════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════

if __name__ == "__main__":
    # Init database
    conn = get_db()
    conn.close()

    G = "\033[38;2;0;255;170m"  # green
    Y = "\033[33m"              # yellow
    D = "\033[90m"              # dim
    R = "\033[0m"               # reset
    print()
    print(f"  {G}fortune0 platform v1.0{R}")
    print()
    print(f"  Landing:    {Y}http://localhost:{PORT}{R}")
    print(f"  App:        {Y}http://localhost:{PORT}/app{R}")
    print(f"  Storyboard: {Y}http://localhost:{PORT}/storyboard{R}")
    print(f"  Join:       {Y}http://localhost:{PORT}/join{R}")
    print(f"  Health:     {Y}http://localhost:{PORT}/health{R}")
    print()
    print(f"  {D}Data: {DATA_DIR}{R}")
    print(f"  {D}Ctrl+C to stop{R}")
    print()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.server_close()
