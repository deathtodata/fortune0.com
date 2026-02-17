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
import re as _re
import uuid
from html.parser import HTMLParser

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
SEARXNG_URL = os.environ.get("SEARXNG_URL", "")  # Your own SearXNG instance (e.g. https://d2d-search.onrender.com)
BRAVE_SEARCH_KEY = os.environ.get("BRAVE_SEARCH_KEY", "")  # Free: https://brave.com/search/api/ (2000 queries/mo)
ADMIN_EMAIL = os.environ.get("F0_ADMIN_EMAIL", "admin@example.com")  # Set F0_ADMIN_EMAIL env var in production
ADMIN_SECRET = os.environ.get("F0_ADMIN_SECRET", "")  # Admin login passphrase — set on Render
IS_PRODUCTION = bool(DATABASE_URL)  # True on Render (has PostgreSQL), False on localhost

# RFC 2606 reserved domains — safe for testing, blocked in production
RESERVED_DOMAINS = {'example.com', 'example.net', 'example.org'}

os.makedirs(DATA_DIR, exist_ok=True)

def validate_email_environment(email):
    """Block reserved test emails in production, warn about real emails in dev."""
    if not email or '@' not in email:
        return False, "Invalid email"
    domain = email.split('@')[-1].lower()
    if IS_PRODUCTION and domain in RESERVED_DOMAINS:
        return False, "Test emails not allowed in production"
    return True, "ok"

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
#  WEB SEARCH (DuckDuckGo — no API key needed)
# ═══════════════════════════════════════════

class _DDGParser(HTMLParser):
    """Parse DuckDuckGo HTML search results (html.duckduckgo.com).
    Results use: .result__a for title/link, .result__snippet for snippet."""
    def __init__(self):
        super().__init__()
        self.results = []
        self._in_link = False
        self._in_snippet = False
        self._current = {}
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        cls = attrs_d.get("class", "")
        # Title links have class "result__a"
        if tag == "a" and "result__a" in cls:
            self._in_link = True
            self._current = {"url": attrs_d.get("href", ""), "title": "", "snippet": ""}
            self._text = []
        # Snippets have class "result__snippet"
        if tag == "a" and "result__snippet" in cls:
            self._in_snippet = True
            self._text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            self._in_link = False
            self._current["title"] = " ".join(self._text).strip()
            self._text = []
        if tag == "a" and self._in_snippet:
            self._in_snippet = False
            self._current["snippet"] = " ".join(self._text).strip()
            if self._current.get("url") and self._current.get("title"):
                self.results.append(self._current)
            self._current = {}
            self._text = []

    def handle_data(self, data):
        if self._in_link or self._in_snippet:
            self._text.append(data.strip())

def search_ddg(query, count=10):
    """Search DuckDuckGo HTML — no API key, no dependencies."""
    try:
        url = "https://html.duckduckgo.com/html/"
        data = urllib.parse.urlencode({"q": query}).encode()
        req = urllib.request.Request(url, data=data, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        parser = _DDGParser()
        parser.feed(html)
        results = []
        for r in parser.results[:count]:
            # DDG prefixes URLs with a redirect — extract the actual URL
            actual_url = r["url"]
            if "uddg=" in actual_url:
                try:
                    actual_url = urllib.parse.unquote(
                        urllib.parse.parse_qs(urllib.parse.urlparse(actual_url).query).get("uddg", [actual_url])[0]
                    )
                except Exception:
                    pass
            results.append({
                "title": r["title"],
                "url": actual_url,
                "snippet": r["snippet"],
                "engine": "duckduckgo",
            })
        return results
    except Exception as e:
        sys.stderr.write(f"  DDG search failed: {e}\n")
        return []

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
CREATE TABLE IF NOT EXISTS domain_interest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    domain TEXT NOT NULL,
    source TEXT DEFAULT 'landing',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(email, domain)
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    visibility TEXT DEFAULT 'private',
    tier_required TEXT DEFAULT 'free',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS domain_interest (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    domain TEXT NOT NULL,
    source TEXT DEFAULT 'landing',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(email, domain)
);
CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    user_email TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    visibility TEXT DEFAULT 'private',
    tier_required TEXT DEFAULT 'free',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires TEXT NOT NULL
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
    # Store in database so sessions survive deploys
    try:
        conn = get_db()
        if USE_PG:
            conn.execute(
                "INSERT INTO sessions (token, email, expires) VALUES (?, ?, ?) "
                "ON CONFLICT (token) DO UPDATE SET email=EXCLUDED.email, expires=EXCLUDED.expires",
                [token, email.lower(), expires.isoformat()])
        else:
            conn.execute("INSERT OR REPLACE INTO sessions (token, email, expires) VALUES (?, ?, ?)",
                         [token, email.lower(), expires.isoformat()])
        conn.commit()
        conn.close()
        sys.stderr.write(f"  [Session] Saved to DB: {email.lower()} (expires {expires.isoformat()})\n")
    except Exception as e:
        sys.stderr.write(f"  [Session] DB save failed: {e}\n")
    with SESSIONS_LOCK:
        SESSIONS[token] = {"email": email.lower(), "expires": expires}
    return token

def get_session(token):
    if not token:
        return None
    with SESSIONS_LOCK:
        sess = SESSIONS.get(token)
    if sess:
        if sess["expires"] < datetime.now(timezone.utc):
            with SESSIONS_LOCK:
                SESSIONS.pop(token, None)
            return None
        return sess
    # Not in memory — check database (survives deploys)
    try:
        conn = get_db()
        row = conn.execute("SELECT email, expires FROM sessions WHERE token=?", [token]).fetchone()
        conn.close()
        if row:
            # dict key access works for both sqlite3.Row and PG RealDictCursor
            expires_str = row["expires"]
            expires = datetime.fromisoformat(expires_str)
            if expires < datetime.now(timezone.utc):
                sys.stderr.write(f"  [Session] DB token expired for {row['email']}\n")
                return None
            email = row["email"]
            sess = {"email": email, "expires": expires}
            with SESSIONS_LOCK:
                SESSIONS[token] = sess  # cache in memory
            sys.stderr.write(f"  [Session] Restored from DB: {email}\n")
            return sess
        else:
            sys.stderr.write(f"  [Session] Token not found in DB (token prefix: {token[:8]}...)\n")
    except Exception as e:
        sys.stderr.write(f"  [Session] DB lookup failed: {e}\n")
    return None

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
        self.send_header("Access-Control-Allow-Origin", "*")
        # No caching in dev so edits show up instantly
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(content)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._raw_body = b""
            return {}
        raw = self.rfile.read(length)
        self._raw_body = raw  # preserve original bytes for webhook signature verification
        return json.loads(raw)

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
            # Public health check — only status info, no business data
            db_type = "postgresql" if USE_PG else "sqlite"
            db_ok = True
            try:
                conn = get_db()
                conn.execute("SELECT 1").fetchone()
                conn.close()
            except Exception:
                db_ok = False
            self.send_json({
                "status": "ok" if db_ok else "degraded",
                "service": "fortune0",
                "version": "1.6.0",
                "db": db_type,
                "db_connected": db_ok,
            })

        # ── Public stats (no auth, no PII — safe for about page) ──
        elif path == "/api/public/stats":
            conn = get_db()
            active = conn.execute("SELECT COUNT(*) as c FROM users WHERE tier='active'").fetchone()["c"]
            total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            if USE_PG:
                searches_today = conn.execute(
                    "SELECT COUNT(*) as c FROM activity WHERE action='search' AND created_at > NOW() - INTERVAL '1 day'"
                ).fetchone()["c"]
            else:
                searches_today = conn.execute(
                    "SELECT COUNT(*) as c FROM activity WHERE action='search' AND created_at > datetime('now', '-1 day')"
                ).fetchone()["c"]
            searches_total = conn.execute(
                "SELECT COUNT(*) as c FROM activity WHERE action='search'"
            ).fetchone()["c"]
            conn.close()
            self.send_json({
                "customers": active,
                "mrr": active * 1.0,  # $1/mo per active sub
                "total_users": total,
                "searches_today": searches_today,
                "searches_total": searches_total,
            })

        # ── Stripe webhook ping (GET = verify endpoint is reachable) ──
        elif path == "/api/webhooks/stripe":
            self.send_json({
                "status": "ok",
                "endpoint": "/api/webhooks/stripe",
                "method_required": "POST",
                "webhook_secret_configured": bool(STRIPE_WEBHOOK_SECRET),
                "stripe_key_configured": bool(STRIPE_SECRET_KEY),
            })

        # ── Admin health: full stats (requires admin auth) ──
        elif path == "/api/admin/health":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            if sess["email"] != ADMIN_EMAIL:
                self.send_json({"error": "Admin only"}, 403); return
            db_type = "postgresql" if USE_PG else "sqlite"
            stripe_configured = bool(STRIPE_WEBHOOK_SECRET)
            payment_link_set = bool(STRIPE_PAYMENT_LINK)
            stripe_api_set = bool(STRIPE_SECRET_KEY)
            searxng_set = bool(SEARXNG_URL)
            conn = get_db()
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
                "status": "ok", "service": "fortune0", "version": "1.6.0",
                "db": db_type,
                "stripe_webhook": "configured" if stripe_configured else "not set",
                "stripe_payment_link": "configured" if payment_link_set else "not set",
                "stripe_api": "configured" if stripe_api_set else "not set",
                "searxng": "configured" if searxng_set else "not set",
                "users": user_count,
                "active_users": active_users,
                "affiliates": affiliate_count,
                "real_revenue": active_users,
                "commission_volume": round(total_revenue, 2),
                "total_credits_issued": round(total_credits, 2),
                "total_credits_spent": round(credits_spent, 2),
                "credits_from_stripe": credits_imported,
            })

        # ── Search (domain registry public, web results paid-only) ──
        elif path == "/api/search":
            q = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
            if not q:
                self.send_json({"error": "Query required"}, 400); return

            # Check auth (optional — domain search works without it)
            sess = self.get_user()
            user_tier = "anonymous"
            if sess:
                conn_tier = get_db()
                user = conn_tier.execute("SELECT tier FROM users WHERE email=?", [sess["email"]]).fetchone()
                user_tier = user["tier"] if user else "free"
                conn_tier.close()

            # ── 1. Domain registry (always available, no auth) ──
            results = []
            search_source = "none"
            try:
                domains_path = os.path.join(SITE_DIR, "domains.json")
                if os.path.exists(domains_path):
                    with open(domains_path) as f:
                        domains = json.load(f)
                    q_lower = q.lower()
                    q_words = q_lower.split()
                    for d in domains:
                        name = d["domain"].replace(".com", "").replace(".io", "").replace(".ai", "").replace(".net", "").replace(".org", "").replace(".xyz", "")
                        domain_words = _re.sub(r'([a-z])([A-Z])', r'\1 \2', name).lower()
                        domain_words = domain_words.replace("-", " ").replace(".", " ")
                        score = 0
                        for w in q_words:
                            if len(w) >= 2 and w in domain_words:
                                score += 10
                            elif len(w) >= 3 and w in name.lower():
                                score += 5
                        if score > 0:
                            results.append({
                                "title": d["domain"],
                                "url": f"https://{d['domain']}",
                                "snippet": f"Value: {d.get('value', 0)} | Status: {d.get('status', 'open')} | Expires: {d.get('expires', '?')}",
                                "engine": "registry",
                                "score": score + d.get("value", 0),
                            })
                    results.sort(key=lambda r: r.get("score", 0), reverse=True)
                    results = results[:10]
                    if results:
                        search_source = "registry"
            except Exception as e:
                sys.stderr.write(f"  Domain registry search failed: {e}\n")

            # ── 2. Web search (paid tier only) ──
            # Priority: Brave API (if key set) → SearXNG (if URL set) → DuckDuckGo (always available)
            web_results = []
            web_locked = False

            if sess and (user_tier == "active" or sess.get("email") == ADMIN_EMAIL):
                # Try Brave Search API first (if configured)
                if BRAVE_SEARCH_KEY and not web_results:
                    try:
                        brave_url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(q)}&count=10"
                        req = urllib.request.Request(brave_url, headers={
                            "Accept": "application/json",
                            "X-Subscription-Token": BRAVE_SEARCH_KEY,
                        })
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            data = json.loads(resp.read().decode())
                            for r in data.get("web", {}).get("results", [])[:10]:
                                web_results.append({
                                    "title": r.get("title", ""),
                                    "url": r.get("url", ""),
                                    "snippet": r.get("description", ""),
                                    "engine": "brave",
                                })
                        if web_results:
                            search_source = "brave" if search_source == "none" else search_source + "+brave"
                    except Exception as e:
                        sys.stderr.write(f"  Brave Search failed: {e}\n")

                # Try SearXNG if configured and nothing yet
                if SEARXNG_URL and not web_results:
                    try:
                        search_url = f"{SEARXNG_URL.rstrip('/')}/search?q={urllib.parse.quote(q)}&format=json&categories=general"
                        req = urllib.request.Request(search_url, headers={
                            "User-Agent": "death2data/1.0 (privacy search)",
                            "Accept": "application/json",
                        })
                        with urllib.request.urlopen(req, timeout=12) as resp:
                            data = json.loads(resp.read().decode())
                            for r in data.get("results", [])[:10]:
                                web_results.append({
                                    "title": r.get("title", ""),
                                    "url": r.get("url", ""),
                                    "snippet": r.get("content", ""),
                                    "engine": r.get("engine", ""),
                                })
                        if web_results:
                            search_source = "searxng" if search_source == "none" else search_source + "+searxng"
                    except Exception as e:
                        sys.stderr.write(f"  SearXNG ({SEARXNG_URL}) failed: {e}\n")

                # DuckDuckGo fallback — always available, no config needed
                if not web_results:
                    web_results = search_ddg(q, count=10)
                    if web_results:
                        search_source = "duckduckgo" if search_source == "none" else search_source + "+duckduckgo"
            else:
                web_locked = True  # Web search available but user not authed/paid

            # Remove score field, merge
            for r in results:
                r.pop("score", None)
            all_results = results + web_results

            # Log search if authenticated
            if sess:
                conn_log = get_db()
                log_activity(conn_log, sess["email"], "search", q[:100])
                conn_log.commit(); conn_log.close()

            self.send_json({
                "query": q,
                "results": all_results,
                "count": len(all_results),
                "source": search_source,
                "registry_matches": len(results),
                "web_results": len(web_results),
                "web_locked": web_locked,
                "authed": bool(sess),
                "tier": user_tier,
            })

        elif path == "/api/stats":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            email = sess["email"]
            contacts = conn.execute("SELECT COUNT(*) c FROM contacts WHERE user_email=?", [email]).fetchone()["c"]
            recent = conn.execute("SELECT * FROM activity WHERE user_email=? ORDER BY created_at DESC LIMIT 20", [email]).fetchall()
            if email == ADMIN_EMAIL:
                # Admin sees platform-wide stats
                affiliates = conn.execute("SELECT COUNT(*) c FROM affiliates").fetchone()["c"]
                comms = conn.execute("SELECT COUNT(*) c FROM commissions").fetchone()["c"]
                revenue = conn.execute("SELECT COALESCE(SUM(order_total),0) s FROM commissions").fetchone()["s"]
                aff_pay = conn.execute("SELECT COALESCE(SUM(commission_amount),0) s FROM commissions").fetchone()["s"]
                plat_rev = conn.execute("SELECT COALESCE(SUM(platform_fee),0) s FROM commissions").fetchone()["s"]
            else:
                # Regular users see only their own stats
                affiliates = conn.execute("SELECT COUNT(*) c FROM affiliates WHERE email=?", [email]).fetchone()["c"]
                comms = conn.execute("SELECT COUNT(*) c FROM commissions WHERE affiliate_email=?", [email]).fetchone()["c"]
                revenue = conn.execute("SELECT COALESCE(SUM(order_total),0) s FROM commissions WHERE affiliate_email=?", [email]).fetchone()["s"]
                aff_pay = conn.execute("SELECT COALESCE(SUM(commission_amount),0) s FROM commissions WHERE affiliate_email=?", [email]).fetchone()["s"]
                plat_rev = conn.execute("SELECT COALESCE(SUM(platform_fee),0) s FROM commissions WHERE affiliate_email=?", [email]).fetchone()["s"]
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
            if sess["email"] == ADMIN_EMAIL:
                # Admin sees all affiliates
                rows = conn.execute("SELECT * FROM affiliates ORDER BY total_earned DESC").fetchall()
            else:
                # Regular users only see their own affiliate record
                rows = conn.execute("SELECT * FROM affiliates WHERE email=? ORDER BY total_earned DESC", [sess["email"]]).fetchall()
            conn.close()
            self.send_json([dict(r) for r in rows])

        elif path == "/api/commissions":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            conn = get_db()
            if sess["email"] == ADMIN_EMAIL:
                # Admin sees all commissions
                rows = conn.execute("SELECT * FROM commissions ORDER BY created_at DESC LIMIT 100").fetchall()
            else:
                # Regular users only see their own commissions
                rows = conn.execute("SELECT * FROM commissions WHERE affiliate_email=? ORDER BY created_at DESC LIMIT 100", [sess["email"]]).fetchall()
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
                  AND a.email NOT LIKE '%example.net'
                  AND a.email NOT LIKE '%example.org'
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
            total_users = conn.execute("SELECT COUNT(*) c FROM users WHERE email NOT LIKE '%@example.com' AND email NOT LIKE '%@example.net' AND email NOT LIKE '%@example.org'").fetchone()["c"]
            active_users = conn.execute("SELECT COUNT(*) c FROM users WHERE tier='active' AND email NOT LIKE '%@example.com' AND email NOT LIKE '%@example.net' AND email NOT LIKE '%@example.org'").fetchone()["c"]
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
                ud["is_admin"] = (sess["email"] == ADMIN_EMAIL)
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
            # Never expose email publicly — hash it
            email_hash = hashlib.sha256(aff["email"].encode()).hexdigest()[:8]
            self.send_json({
                "code": code,
                "email_hash": email_hash,
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

        # ── Analytics: time-series platform data (admin only) ──
        elif path == "/api/analytics":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            if sess["email"] != ADMIN_EMAIL:
                self.send_json({"error": "Admin only"}, 403); return
            conn = get_db()
            try:
                # Signups per day (last 30 days)
                if USE_PG:
                    signups = conn.execute("""
                        SELECT DATE(created_at) as day, COUNT(*) as count
                        FROM users WHERE created_at > NOW() - INTERVAL '30 days'
                        GROUP BY DATE(created_at) ORDER BY day
                    """).fetchall()
                    activations = conn.execute("""
                        SELECT DATE(created_at) as day, COUNT(*) as count
                        FROM activity WHERE action='payment' AND created_at > NOW() - INTERVAL '30 days'
                        GROUP BY DATE(created_at) ORDER BY day
                    """).fetchall()
                    searches = conn.execute("""
                        SELECT DATE(created_at) as day, COUNT(*) as count
                        FROM activity WHERE action='search' AND created_at > NOW() - INTERVAL '30 days'
                        GROUP BY DATE(created_at) ORDER BY day
                    """).fetchall()
                    all_activity = conn.execute("""
                        SELECT DATE(created_at) as day, action, COUNT(*) as count
                        FROM activity WHERE created_at > NOW() - INTERVAL '30 days'
                        GROUP BY DATE(created_at), action ORDER BY day
                    """).fetchall()
                else:
                    signups = conn.execute("""
                        SELECT DATE(created_at) as day, COUNT(*) as count
                        FROM users WHERE created_at > datetime('now', '-30 days')
                        GROUP BY DATE(created_at) ORDER BY day
                    """).fetchall()
                    activations = conn.execute("""
                        SELECT DATE(created_at) as day, COUNT(*) as count
                        FROM activity WHERE action='payment' AND created_at > datetime('now', '-30 days')
                        GROUP BY DATE(created_at) ORDER BY day
                    """).fetchall()
                    searches = conn.execute("""
                        SELECT DATE(created_at) as day, COUNT(*) as count
                        FROM activity WHERE action='search' AND created_at > datetime('now', '-30 days')
                        GROUP BY DATE(created_at) ORDER BY day
                    """).fetchall()
                    all_activity = conn.execute("""
                        SELECT DATE(created_at) as day, action, COUNT(*) as count
                        FROM activity WHERE created_at > datetime('now', '-30 days')
                        GROUP BY DATE(created_at), action ORDER BY day
                    """).fetchall()

                # Current totals
                total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
                active_users = conn.execute("SELECT COUNT(*) c FROM users WHERE tier='active'").fetchone()["c"]
                total_searches = conn.execute("SELECT COUNT(*) c FROM activity WHERE action='search'").fetchone()["c"]
                total_signups_ever = conn.execute("SELECT COUNT(*) c FROM activity WHERE action='signup'").fetchone()["c"]
                total_payments = conn.execute("SELECT COUNT(*) c FROM activity WHERE action='payment'").fetchone()["c"]

                # Credits from actual Stripe payments
                stripe_credits = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM credits WHERE source='stripe_import'").fetchone()

                # Domain interest stats
                try:
                    domain_interest_total = conn.execute("SELECT COUNT(*) c FROM domain_interest").fetchone()["c"]
                    top_domains = conn.execute("""
                        SELECT domain, COUNT(*) as signups
                        FROM domain_interest
                        GROUP BY domain
                        ORDER BY signups DESC
                        LIMIT 10
                    """).fetchall()
                except Exception:
                    domain_interest_total = 0
                    top_domains = []

            except Exception as e:
                conn.close()
                self.send_json({"error": f"Analytics query failed: {e}"}, 500)
                return

            conn.close()
            self.send_json({
                "signups_by_day": [dict(r) for r in signups],
                "activations_by_day": [dict(r) for r in activations],
                "searches_by_day": [dict(r) for r in searches],
                "activity_by_day": [dict(r) for r in all_activity],
                "domain_interest": {
                    "total": domain_interest_total,
                    "top_domains": [dict(r) for r in top_domains],
                },
                "totals": {
                    "users": total_users,
                    "active_users": active_users,
                    "real_revenue": active_users,  # $1/mo × active
                    "total_searches": total_searches,
                    "total_signups": total_signups_ever,
                    "total_payments": total_payments,
                    "stripe_charges": stripe_credits["c"],
                    "stripe_credits_total": round(stripe_credits["s"], 2),
                    "domain_interest": domain_interest_total,
                },
            })

        # ── Charts redirect (charts render client-side now) ──
        elif path.startswith("/api/chart"):
            self.send_json({
                "message": "Charts render client-side now. Go to /charts for the analytics dashboard.",
                "dashboard": "/charts",
                "data_endpoints": ["/health", "/api/analytics", "/domains.json"],
            })

        # ── Notes: list public notes or user's own notes ──
        elif path == "/api/notes":
            sess = self.get_user()
            visibility = qs.get("visibility", ["public"])[0]

            conn = get_db()
            if visibility == "public":
                # Anyone can see public notes
                rows = conn.execute(
                    "SELECT n.id, n.title, n.body, n.visibility, n.tier_required, n.created_at, n.updated_at, "
                    "u.referral_code FROM notes n LEFT JOIN users u ON u.email = n.user_email "
                    "WHERE n.visibility='public' ORDER BY n.created_at DESC LIMIT 50"
                ).fetchall()
                conn.close()
                self.send_json([dict(r) for r in rows])
            elif sess:
                # Authed user sees their own notes
                rows = conn.execute(
                    "SELECT * FROM notes WHERE user_email=? ORDER BY created_at DESC",
                    [sess["email"]]
                ).fetchall()
                conn.close()
                self.send_json([dict(r) for r in rows])
            else:
                conn.close()
                self.send_json({"error": "Auth required for private notes"}, 401)

        # ── Domain info API: /api/domain-info/<domain> ──
        elif path.startswith("/api/domain-info/"):
            domain_slug = path[len("/api/domain-info/"):].strip().lower()
            # Load domains.json
            domains_path = os.path.join(SITE_DIR, "domains.json")
            if not os.path.exists(domains_path):
                self.send_json({"error": "No domain registry"}, 404); return
            with open(domains_path) as f:
                domains = json.load(f)
            # Find matching domain (support slug with or without TLD)
            match = None
            for d in domains:
                dname = d["domain"].lower()
                slug_only = dname.split(".")[0]
                if dname == domain_slug or slug_only == domain_slug:
                    match = d
                    break
            if not match:
                self.send_json({"error": "Domain not found", "slug": domain_slug}, 404); return
            # Get interest count
            conn = get_db()
            try:
                interest_count = conn.execute(
                    "SELECT COUNT(*) c FROM domain_interest WHERE domain=?",
                    [match["domain"]]
                ).fetchone()["c"]
            except Exception:
                interest_count = 0
            conn.close()
            match["interest_count"] = interest_count
            self.send_json(match)

        # ── Domain interest stats (public) ──
        elif path == "/api/domain-interest":
            conn = get_db()
            try:
                rows = conn.execute("""
                    SELECT domain, COUNT(*) as signups
                    FROM domain_interest
                    GROUP BY domain
                    ORDER BY signups DESC
                    LIMIT 50
                """).fetchall()
            except Exception:
                rows = []
            conn.close()
            self.send_json([dict(r) for r in rows])

        # ── QR code generator page: /qr/<domain> ──
        elif path.startswith("/qr/"):
            self.send_file(os.path.join(SITE_DIR, "qr.html"))

        # ── Domain landing pages: /d/<domain-name> (portfolio only) ──
        elif path.startswith("/d/"):
            slug = path[3:].strip().lower().rstrip("/")
            # Only serve landing pages for domains in our portfolio
            domains_path = os.path.join(SITE_DIR, "domains.json")
            found = False
            if os.path.exists(domains_path):
                with open(domains_path) as f:
                    domains = json.load(f)
                for d in domains:
                    dname = d["domain"].lower()
                    slug_only = dname.split(".")[0]
                    if dname == slug or slug_only == slug:
                        found = True
                        break
            if found:
                self.send_file(os.path.join(SITE_DIR, "domain-template.html"))
            else:
                # Unknown domain → redirect to ideas browser
                self.send_response(302)
                self.send_header("Location", "/ideas")
                self.end_headers()

        # ── Admin: list all users with license keys (GET) ──
        elif path == "/api/admin/users":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            if sess["email"] != ADMIN_EMAIL:
                self.send_json({"error": "Admin only"}, 403); return

            conn = get_db()
            users = conn.execute("""
                SELECT u.email, u.tier, u.referral_code, u.license_key,
                       u.created_at,
                       COALESCE(SUM(CASE WHEN c.amount > 0 THEN c.amount ELSE 0 END), 0) as credits
                FROM users u
                LEFT JOIN credits c ON c.user_email = u.email
                GROUP BY u.email
                ORDER BY u.created_at DESC
            """).fetchall()
            conn.close()

            user_list = []
            for u in users:
                key_status = "none"
                if u["license_key"]:
                    _, msg = validate_license_key(u["license_key"])
                    key_status = msg.lower()
                user_list.append({
                    "email": u["email"],
                    "tier": u["tier"],
                    "referral_code": u["referral_code"],
                    "license_key": u["license_key"] or "",
                    "key_status": key_status,
                    "credits": round(u["credits"], 2),
                    "created_at": u["created_at"],
                })

            self.send_json({"users": user_list, "count": len(user_list)})

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

        # ── Signup (create NEW accounts only — existing users must use /api/login) ──
        if path == "/api/signup":
            email = body.get("email", "").strip().lower()
            if not email or "@" not in email:
                self.send_json({"error": "Valid email required"}, 400); return
            ok, reason = validate_email_environment(email)
            if not ok:
                self.send_json({"error": reason}, 400); return

            conn = get_db()
            existing = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
            if existing:
                user_data = dict(existing)
                # Active tier (paid via Stripe) — auto-login, no key needed
                if user_data.get("tier") == "active":
                    token = create_session(user_data["email"])
                    log_activity(conn, user_data["email"], "auto_login", "Active tier auto-login")
                    conn.commit(); conn.close()
                    self.send_json({
                        "token": token, "email": user_data["email"],
                        "tier": "active", "referral_code": user_data.get("referral_code", ""),
                    })
                    return
                # Free tier — require license key
                conn.close()
                self.send_json({
                    "error": "Account already exists. Sign in with your license key.",
                    "exists": True,
                }, 409)
                return

            ref_code = generate_referral_code(email)
            license_key = generate_license_key(email)
            conn.execute("INSERT INTO users (email, referral_code, license_key, tier) VALUES (?, ?, ?, 'free')",
                         [email, ref_code, license_key])
            source_domain = body.get("source_domain", body.get("domain", "direct"))
            log_activity(conn, email, "signup", f"New account: {ref_code} (via {source_domain})")
            # Track domain interest if they came from a domain landing page
            if source_domain and source_domain != "direct":
                try:
                    conn.execute(
                        "INSERT INTO domain_interest (email, domain, source) VALUES (?, ?, 'signup')",
                        [email, source_domain]
                    )
                except Exception:
                    pass
            conn.commit(); conn.close()

            token = create_session(email)
            self.send_json({
                "token": token, "email": email,
                "referral_code": ref_code, "license_key": license_key,
                "tier": "free", "new": True,
            })

        # ── Login (license key OR admin secret) ──
        elif path == "/api/login":
            email = body.get("email", "").strip().lower()
            key = body.get("key", "").strip()
            if not email:
                self.send_json({"error": "Email required"}, 400); return

            # Admin can log in with F0_ADMIN_SECRET instead of license key
            authed = False
            if email == ADMIN_EMAIL and ADMIN_SECRET and key == ADMIN_SECRET:
                authed = True
                auth_method = "Admin secret"
            elif key:
                payload, msg = validate_license_key(key)
                if not payload or msg != "Valid":
                    self.send_json({"error": msg}, 401); return
                if payload.get("email", "").lower() != email:
                    self.send_json({"error": "Key doesn't match email"}, 401); return
                authed = True
                auth_method = "License key"
            else:
                self.send_json({"error": "Key required"}, 400); return

            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
            if not user:
                # Admin auto-creates their account if it doesn't exist yet
                if email == ADMIN_EMAIL and authed:
                    ref_code = generate_referral_code(email)
                    lk = generate_license_key(email, days=365)
                    conn.execute("INSERT INTO users (email, referral_code, license_key, tier) VALUES (?, ?, ?, 'active')",
                                 [email, ref_code, lk])
                    log_activity(conn, email, "signup", f"Admin account auto-created: {ref_code}")
                    conn.commit()
                    user = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
                else:
                    conn.close()
                    self.send_json({"error": "Account not found"}, 404); return
            log_activity(conn, email, "login", auth_method)
            conn.commit(); conn.close()
            token = create_session(email)
            self.send_json({
                "token": token, "email": email,
                "referral_code": user["referral_code"],
                "tier": user["tier"],
                "is_admin": (email == ADMIN_EMAIL),
            })

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
                conn.close()
                # Don't return full data — just confirm they exist and point them to login
                self.send_json({
                    "returning": True,
                    "message": "You already have an affiliate account. Sign in with your license key to see your stats.",
                    "profile_url": f"/u/{existing['referral_code']}",
                })
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
            # Verify signature using original raw bytes (NOT re-serialized JSON)
            raw_body = getattr(self, '_raw_body', b'')
            sig_header = self.headers.get("Stripe-Signature", "")
            event_type = body.get("type", "unknown")
            sys.stderr.write(f"  [Stripe Webhook] Received event: {event_type}, body size: {len(raw_body)} bytes, sig present: {bool(sig_header)}\n")

            if STRIPE_WEBHOOK_SECRET and sig_header:
                # Verify Stripe webhook signature
                # Stripe signs: {timestamp}.{raw_body} using HMAC-SHA256
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
                        sys.stderr.write(f"  [Stripe Webhook] Signature mismatch! Check STRIPE_WEBHOOK_SECRET env var.\n")
                        self.send_json({"error": "Invalid signature"}, 401)
                        return
                    sys.stderr.write(f"  [Stripe Webhook] Signature verified OK.\n")
                except Exception as e:
                    sys.stderr.write(f"  [Stripe Webhook] Signature parse error: {e} — processing anyway (dev mode).\n")
            elif not STRIPE_WEBHOOK_SECRET:
                sys.stderr.write(f"  [Stripe Webhook] No STRIPE_WEBHOOK_SECRET set — skipping signature verification.\n")

            # Handle the event (event_type already extracted above for logging)
            if event_type == "checkout.session.completed":
                session_data = body.get("data", {}).get("object", {})
                ref_code = session_data.get("client_reference_id", "")
                customer_email = session_data.get("customer_email", "") or session_data.get("customer_details", {}).get("email", "")
                amount = session_data.get("amount_total", 0) / 100  # cents to dollars
                sys.stderr.write(f"  [Stripe Webhook] checkout.session.completed: email={customer_email}, ref={ref_code}, ${amount}\n")

                if not ref_code and not customer_email:
                    sys.stderr.write(f"  [Stripe Webhook] ERROR: No reference ID or email in event.\n")
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
                    sys.stderr.write(f"  [Stripe Webhook] Activated existing user: {email} → tier=active\n")
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
                            sys.stderr.write(f"  [Stripe Webhook] Created new active account: {customer_email}\n")
                        except Exception as e:
                            sys.stderr.write(f"  [Stripe Webhook] Error creating account for {customer_email}: {e}\n")
                    conn.close()
                    self.send_json({"activated": True, "new_account": True, "email": customer_email})
            else:
                # Other event types — acknowledge but ignore
                sys.stderr.write(f"  [Stripe Webhook] Ignoring event type: {event_type}\n")
                self.send_json({"received": True})

        # ── Account recovery (email lookup) ──
        elif path == "/api/recover":
            # Recovery disabled — no email sending service configured
            # Don't reveal whether any email exists in the system
            self.send_json({
                "message": "If this email has an account, your license key was shown at signup. Check your Stripe receipt email or contact support.",
                "support": "matt@death2data.com",
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
            test_patterns = ['%@example.com', '%@example.net', '%@example.org']
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

        # ── Admin: renew a user's license key ──
        elif path == "/api/admin/renew-key":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            if sess["email"] != ADMIN_EMAIL:
                self.send_json({"error": "Admin only"}, 403); return

            target_email = body.get("email", "").strip().lower()
            days = int(body.get("days", 90))
            if not target_email:
                self.send_json({"error": "Email required"}, 400); return

            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE email=?", [target_email]).fetchone()
            if not user:
                conn.close()
                self.send_json({"error": "User not found"}, 404); return

            new_key = generate_license_key(target_email, days=days)
            conn.execute("UPDATE users SET license_key=? WHERE email=?", [new_key, target_email])
            log_activity(conn, sess["email"], "admin_renew_key", f"Renewed key for {target_email} ({days} days)")
            conn.commit()
            conn.close()

            self.send_json({"renewed": True, "email": target_email, "new_key": new_key, "days": days})

        # ── Create note ──

        elif path == "/api/admin/set-tier":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            if sess["email"] != ADMIN_EMAIL:
                self.send_json({"error": "Admin only"}, 403); return
            target = body.get("email", "").strip().lower()
            new_tier = body.get("tier", "").strip().lower()
            if not target or new_tier not in ("free", "active", "premium"):
                self.send_json({"error": "Need email and tier (free/active/premium)"}, 400); return
            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE email=?", [target]).fetchone()
            if not user:
                conn.close()
                self.send_json({"error": "User not found"}, 404); return
            conn.execute("UPDATE users SET tier=? WHERE email=?", [new_tier, target])
            conn.commit(); conn.close()
            self.send_json({"ok": True, "email": target, "tier": new_tier})

        elif path == "/api/notes":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return

            title = body.get("title", "").strip()
            note_body = body.get("body", "").strip()
            visibility = body.get("visibility", "private")  # private or public
            tier_required = body.get("tier_required", "free")  # free or active

            if not title or not note_body:
                self.send_json({"error": "Title and body required"}, 400); return
            if visibility not in ("private", "public"):
                self.send_json({"error": "Visibility must be 'private' or 'public'"}, 400); return

            conn = get_db()

            # Check tier — only active users can create public notes
            if visibility == "public":
                user = conn.execute("SELECT tier FROM users WHERE email=?", [sess["email"]]).fetchone()
                user_tier = user["tier"] if user else "free"
                if user_tier != "active":
                    conn.close()
                    self.send_json({"error": "Active tier required to publish public notes"}, 403); return

            conn.execute(
                "INSERT INTO notes (user_email, title, body, visibility, tier_required) VALUES (?, ?, ?, ?, ?)",
                [sess["email"], title, note_body, visibility, tier_required]
            )
            log_activity(conn, sess["email"], "note_created", f"{visibility}: {title[:50]}")
            conn.commit()
            row = conn.execute("SELECT * FROM notes WHERE user_email=? ORDER BY id DESC LIMIT 1", [sess["email"]]).fetchone()
            conn.close()
            self.send_json(dict(row), 201)

        # ── Update note ──
        elif path == "/api/notes/update":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            nid = body.get("id")
            if not nid:
                self.send_json({"error": "ID required"}, 400); return
            conn = get_db()
            updates = []
            vals = []
            for field in ["title", "body", "visibility", "tier_required"]:
                if field in body:
                    updates.append(f"{field}=?")
                    vals.append(body[field])
            if not updates:
                conn.close()
                self.send_json({"error": "No fields to update"}, 400); return
            updates.append("updated_at=CURRENT_TIMESTAMP" if not USE_PG else "updated_at=NOW()")
            vals.extend([nid, sess["email"]])
            conn.execute(f"UPDATE notes SET {','.join(updates)} WHERE id=? AND user_email=?", vals)
            log_activity(conn, sess["email"], "note_updated", f"Note #{nid}")
            conn.commit()
            row = conn.execute("SELECT * FROM notes WHERE id=?", [nid]).fetchone()
            conn.close()
            self.send_json(dict(row) if row else {"error": "Not found"}, 200 if row else 404)

        # ── Delete note ──
        elif path == "/api/notes/delete":
            sess = self.get_user()
            if not sess:
                self.send_json({"error": "Auth required"}, 401); return
            nid = body.get("id")
            if not nid:
                self.send_json({"error": "ID required"}, 400); return
            conn = get_db()
            conn.execute("DELETE FROM notes WHERE id=? AND user_email=?", [nid, sess["email"]])
            log_activity(conn, sess["email"], "note_deleted", f"Note #{nid}")
            conn.commit(); conn.close()
            self.send_json({"deleted": True})

        # ── Domain interest signup (no auth required) ──
        elif path == "/api/domain-interest":
            email = body.get("email", "").strip().lower()
            domain = body.get("domain", "").strip().lower()
            source = body.get("source", "landing")
            ref = body.get("ref", "").strip()  # referral code from QR / shared link

            if not email or "@" not in email:
                self.send_json({"error": "Valid email required"}, 400); return
            ok, reason = validate_email_environment(email)
            if not ok:
                self.send_json({"error": reason}, 400); return
            if not domain:
                self.send_json({"error": "Domain required"}, 400); return

            conn = get_db()

            # Record domain interest
            try:
                conn.execute(
                    "INSERT INTO domain_interest (email, domain, source) VALUES (?, ?, ?)",
                    [email, domain, source]
                )
            except Exception:
                pass  # UNIQUE constraint — already interested

            # Also create a user account if they don't have one
            existing = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
            if not existing:
                ref_code = generate_referral_code(email)
                license_key = generate_license_key(email)
                try:
                    conn.execute(
                        "INSERT INTO users (email, referral_code, license_key, tier) VALUES (?, ?, ?, 'free')",
                        [email, ref_code, license_key]
                    )
                    log_activity(conn, email, "signup", f"Via domain landing: {domain} (ref: {ref or 'none'})")
                except Exception:
                    pass
            else:
                ref_code = existing["referral_code"]

            # ── Referral attribution: if they came via a QR code / shared link ──
            referred_by = None
            if ref:
                referrer = conn.execute("SELECT email FROM users WHERE referral_code=?", [ref]).fetchone()
                if referrer:
                    referred_by = referrer["email"]
                    # Log the referral attribution
                    log_activity(conn, referred_by, "referral_scan", f"{email} signed up for {domain} via QR/link")
                    log_activity(conn, email, "referred_by", f"Referred by {ref} for {domain}")
                    # Record commission if referrer is an affiliate
                    affiliate = conn.execute("SELECT * FROM affiliates WHERE email=?", [referred_by]).fetchone()
                    if affiliate:
                        try:
                            order_id = f"ref-{uuid.uuid4().hex[:12]}"
                            conn.execute("""INSERT INTO commissions
                                (affiliate_email, order_id, order_total, commission_amount, commission_rate,
                                 platform_fee, platform_fee_rate, status, discount_code)
                                VALUES (?, ?, 1.00, 0.30, 0.30, 0.05, 0.05, 'pending', ?)""",
                                [referred_by, order_id, f"ref:{ref}"]
                            )
                        except Exception:
                            pass

            log_activity(conn, email, "domain_interest", f"Interested in {domain} ({source}){' ref:' + ref if ref else ''}")
            conn.commit()

            # Get interest count for this domain
            count = conn.execute(
                "SELECT COUNT(*) c FROM domain_interest WHERE domain=?", [domain]
            ).fetchone()["c"]
            conn.close()

            # Do NOT create a session — interest signup is not authentication
            self.send_json({
                "registered": True,
                "domain": domain,
                "interest_count": count,
            })

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
    print(f"  Charts:     {Y}http://localhost:{PORT}/charts{R}")
    print(f"  Domain:     {Y}http://localhost:{PORT}/d/civicresume{R}")
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
