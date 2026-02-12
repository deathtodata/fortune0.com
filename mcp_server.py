#!/usr/bin/env python3
"""
fortune0 MCP Server
====================

Lets any AI app (Claude Desktop, VS Code, etc.) interact with fortune0.

Setup:
    pip install fastmcp

Add to Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
        "mcpServers": {
            "fortune0": {
                "command": "python3",
                "args": ["/path/to/fortune0-site/mcp_server.py"]
            }
        }
    }

Then just talk to Claude:
    "Sign me up for fortune0"
    "Show my dashboard stats"
    "Add a contact named John at john@example.com"
    "What's my referral code?"
    "How many people clicked my referral link?"
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import base64
from datetime import datetime, timezone, timedelta

try:
    from fastmcp import FastMCP
except ImportError:
    print("Install fastmcp first: pip install fastmcp")
    print("Then re-run this server.")
    raise SystemExit(1)

# ═══════════════════════════════════════════
#  CONFIG (same as server.py)
# ═══════════════════════════════════════════

SITE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SITE_DIR, "data")
LICENSE_SECRET = os.environ.get("F0_LICENSE_SECRET", "fortune0-dev-secret-2026")

os.makedirs(DATA_DIR, exist_ok=True)

COMMISSION_TIERS = [
    (250_000, 0.03),
    (50_000, 0.035),
    (10_000, 0.04),
    (0, 0.05),
]

# ═══════════════════════════════════════════
#  DATABASE (same schema as server.py)
# ═══════════════════════════════════════════

SCHEMA = """
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

def get_db():
    db_path = os.path.join(DATA_DIR, "fortune0.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn

def log_activity(conn, email, action, detail=""):
    conn.execute("INSERT INTO activity (user_email, action, detail) VALUES (?, ?, ?)",
                 [email, action, detail])

# ═══════════════════════════════════════════
#  CRYPTO (same as server.py)
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

# ═══════════════════════════════════════════
#  MCP SERVER
# ═══════════════════════════════════════════

mcp = FastMCP(
    "fortune0",
    description="fortune0 open incubator — sign up, manage contacts, earn referral commissions, track everything locally"
)

@mcp.tool()
def signup(email: str) -> dict:
    """Create a fortune0 account. Returns license key and referral code. If account exists, returns existing info."""
    email = email.strip().lower()
    if not email or "@" not in email:
        return {"error": "Valid email required"}

    conn = get_db()
    existing = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
    if existing:
        conn.close()
        return {
            "status": "existing_account",
            "email": existing["email"],
            "referral_code": existing["referral_code"],
            "license_key": existing["license_key"],
            "tier": existing["tier"],
            "created_at": existing["created_at"]
        }

    ref_code = generate_referral_code(email)
    lic_key = generate_license_key(email)
    conn.execute("INSERT INTO users (email, referral_code, license_key) VALUES (?, ?, ?)",
                 [email, ref_code, lic_key])
    log_activity(conn, email, "signup", "Account created via MCP")
    conn.commit()
    conn.close()

    return {
        "status": "created",
        "email": email,
        "referral_code": ref_code,
        "license_key": lic_key,
        "tier": "free",
        "referral_link": f"fortune0.com/r/{ref_code}"
    }


@mcp.tool()
def get_stats(email: str) -> dict:
    """Get dashboard stats for a fortune0 user — contacts, affiliates, commissions, revenue."""
    email = email.strip().lower()
    conn = get_db()

    user = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
    if not user:
        conn.close()
        return {"error": f"No account found for {email}. Use the signup tool first."}

    contacts = conn.execute("SELECT COUNT(*) c FROM contacts WHERE user_email=?", [email]).fetchone()["c"]
    affiliates = conn.execute("SELECT COUNT(*) c FROM affiliates").fetchone()["c"]
    comms = conn.execute("SELECT COUNT(*) c FROM commissions").fetchone()["c"]
    revenue = conn.execute("SELECT COALESCE(SUM(order_total),0) s FROM commissions").fetchone()["s"]
    aff_pay = conn.execute("SELECT COALESCE(SUM(commission_amount),0) s FROM commissions").fetchone()["s"]
    recent = conn.execute("SELECT action, detail, created_at FROM activity WHERE user_email=? ORDER BY created_at DESC LIMIT 10", [email]).fetchall()

    conn.close()
    return {
        "email": email,
        "referral_code": user["referral_code"],
        "tier": user["tier"],
        "contacts": contacts,
        "affiliates": affiliates,
        "commissions": comms,
        "total_revenue": round(revenue, 2),
        "affiliate_payouts": round(aff_pay, 2),
        "recent_activity": [{"action": r["action"], "detail": r["detail"], "when": r["created_at"]} for r in recent]
    }


@mcp.tool()
def add_contact(email: str, contact_name: str, contact_email: str = "", phone: str = "", company: str = "", notes: str = "") -> dict:
    """Add a contact to a fortune0 user's CRM."""
    email = email.strip().lower()
    conn = get_db()

    user = conn.execute("SELECT * FROM users WHERE email=?", [email]).fetchone()
    if not user:
        conn.close()
        return {"error": f"No account found for {email}. Use the signup tool first."}

    conn.execute("INSERT INTO contacts (user_email, name, email, phone, company, notes) VALUES (?, ?, ?, ?, ?, ?)",
                 [email, contact_name, contact_email, phone, company, notes])
    log_activity(conn, email, "contact_added", f"Added {contact_name}")
    conn.commit()
    conn.close()
    return {"status": "added", "contact": contact_name}


@mcp.tool()
def list_contacts(email: str, search: str = "") -> dict:
    """List contacts for a fortune0 user. Optionally search by name, email, or company."""
    email = email.strip().lower()
    conn = get_db()

    if search:
        q = f"%{search}%"
        rows = conn.execute(
            "SELECT name, email, phone, company, notes, created_at FROM contacts WHERE user_email=? AND (name LIKE ? OR email LIKE ? OR company LIKE ?) ORDER BY created_at DESC",
            [email, q, q, q]).fetchall()
    else:
        rows = conn.execute(
            "SELECT name, email, phone, company, notes, created_at FROM contacts WHERE user_email=? ORDER BY created_at DESC",
            [email]).fetchall()

    conn.close()
    return {
        "count": len(rows),
        "contacts": [dict(r) for r in rows]
    }


@mcp.tool()
def join_affiliate(email: str) -> dict:
    """Sign up as a fortune0 affiliate to earn commissions on referrals."""
    email = email.strip().lower()
    conn = get_db()

    existing = conn.execute("SELECT * FROM affiliates WHERE email=?", [email]).fetchone()
    if existing:
        conn.close()
        return {
            "status": "already_affiliate",
            "referral_code": existing["referral_code"],
            "commission_rate": f"{existing['commission_rate']*100:.0f}%",
            "total_earned": existing["total_earned"],
            "total_referrals": existing["total_referrals"],
            "referral_link": f"fortune0.com/r/{existing['referral_code']}"
        }

    ref_code = generate_referral_code(email)
    conn.execute("INSERT OR IGNORE INTO affiliates (email, referral_code) VALUES (?, ?)",
                 [email, ref_code])
    log_activity(conn, email, "affiliate_joined", "Joined affiliate program via MCP")
    conn.commit()
    conn.close()

    return {
        "status": "joined",
        "email": email,
        "referral_code": ref_code,
        "commission_rate": "10%",
        "referral_link": f"fortune0.com/r/{ref_code}"
    }


@mcp.tool()
def referral_stats(email: str) -> dict:
    """Check referral click stats and commission history for an affiliate."""
    email = email.strip().lower()
    conn = get_db()

    aff = conn.execute("SELECT * FROM affiliates WHERE email=?", [email]).fetchone()
    if not aff:
        conn.close()
        return {"error": f"Not an affiliate. Use join_affiliate tool first."}

    clicks = conn.execute("SELECT COUNT(*) c FROM referral_clicks WHERE referral_code=?", [aff["referral_code"]]).fetchone()["c"]
    conversions = conn.execute("SELECT COUNT(*) c FROM referral_clicks WHERE referral_code=? AND converted=1", [aff["referral_code"]]).fetchone()["c"]
    commissions = conn.execute("SELECT order_id, order_total, commission_amount, status, created_at FROM commissions WHERE affiliate_email=? ORDER BY created_at DESC LIMIT 20", [email]).fetchall()

    conn.close()
    return {
        "referral_code": aff["referral_code"],
        "total_clicks": clicks,
        "conversions": conversions,
        "total_earned": aff["total_earned"],
        "total_referrals": aff["total_referrals"],
        "commission_history": [dict(c) for c in commissions]
    }


@mcp.tool()
def platform_health() -> dict:
    """Check if the fortune0 platform is running and see basic stats."""
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    affiliates = conn.execute("SELECT COUNT(*) c FROM affiliates").fetchone()["c"]
    contacts = conn.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"]
    conn.close()
    return {
        "status": "ok",
        "service": "fortune0",
        "version": "1.0.0",
        "database": "sqlite",
        "total_users": users,
        "total_affiliates": affiliates,
        "total_contacts": contacts
    }


# ═══════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════

if __name__ == "__main__":
    mcp.run()
