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
            self.send_json({"status": "ok", "service": "fortune0", "version": "1.0.0",
                            "uptime": "running", "db": "sqlite"})

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

        elif path == "/api/me":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE email=?", [sess["email"]]).fetchone()
            conn.close()
            if user:
                self.send_json(dict(user))
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
            # Redirect to signup with referral pre-filled
            if aff:
                self.send_response(302)
                self.send_header("Location", f"/join?ref={code}")
                self.end_headers()
            else:
                # Unknown code — still redirect to join, they can sign up fresh
                self.send_response(302)
                self.send_header("Location", "/join")
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
                d["returning"] = True
                self.send_json(d)
                return
            conn.execute("INSERT INTO affiliates (email, referral_code, commission_rate) VALUES (?, ?, 0.10)",
                         [email, code])
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
            d["clicks"] = 0
            d["returning"] = False
            self.send_json(d, 201)

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
