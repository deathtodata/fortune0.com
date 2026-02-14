#!/usr/bin/env python3
"""
End-to-end test for fortune0 platform.
Starts the server, tests all endpoints, then shuts down.
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

PORT = 9999
BASE = f"http://localhost:{PORT}"
PASSED = 0
FAILED = 0

def api(method, path, body=None, token=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return 0, {"error": str(e)}

def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name} — {detail}")

def main():
    global PASSED, FAILED

    # Clean and start server
    os.makedirs("data", exist_ok=True)
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fortune0.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    env = os.environ.copy()
    env["F0_PORT"] = str(PORT)
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server
    for _ in range(20):
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        print("FATAL: Server did not start")
        proc.kill()
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  fortune0 E2E Tests — http://localhost:{PORT}")
    print(f"{'='*50}\n")

    try:
        # ── 1. Health ──
        print("[1] Health check")
        status, data = api("GET", "/health")
        test("GET /health returns 200", status == 200)
        test("Status is 'ok'", data.get("status") == "ok")
        test("Version is 1.0.0", data.get("version") == "1.0.0")

        # ── 2. Static files ──
        print("\n[2] Static file serving")
        status, _ = api("GET", "/")
        # The response won't be JSON for HTML, so let's use urllib directly
        try:
            resp = urllib.request.urlopen(f"{BASE}/")
            test("GET / serves index.html", resp.status == 200)
            ct = resp.headers.get("Content-Type", "")
            test("Content-Type is HTML", "text/html" in ct)
        except Exception as e:
            test("GET / serves index.html", False, str(e))

        try:
            resp = urllib.request.urlopen(f"{BASE}/app")
            test("GET /app serves app.html", resp.status == 200)
        except Exception as e:
            test("GET /app serves app.html", False, str(e))

        try:
            resp = urllib.request.urlopen(f"{BASE}/favicon.svg")
            test("GET /favicon.svg serves SVG", resp.status == 200)
        except Exception as e:
            test("GET /favicon.svg", False, str(e))

        # ── 3. Auth — unauthenticated ──
        print("\n[3] Auth boundaries (unauthenticated)")
        status, data = api("GET", "/api/contacts")
        test("GET /api/contacts returns 401", status == 401)

        status, data = api("GET", "/api/stats")
        test("GET /api/stats returns 401", status == 401)

        status, data = api("POST", "/api/contacts", {"name": "Nope"})
        test("POST /api/contacts returns 401", status == 401)

        # ── 4. Signup ──
        print("\n[4] Signup")
        status, data = api("POST", "/api/signup", {"email": "testuser@example.com"})
        test("POST /api/signup returns 200", status == 200)
        test("Returns token", "token" in data and len(data["token"]) > 10)
        test("Returns referral_code", "referral_code" in data and data["referral_code"].startswith("IK-"))
        test("Returns email", data.get("email") == "testuser@example.com")
        test("Is new user", data.get("new") is True)
        token = data.get("token", "")
        refCode = data.get("referral_code", "")

        # ── 5. Signup again (returning user) ──
        print("\n[5] Returning user login")
        status, data = api("POST", "/api/signup", {"email": "testuser@example.com"})
        test("Returns 200 for existing user", status == 200)
        test("Not flagged as new", data.get("new") is False)
        test("Same referral code", data.get("referral_code") == refCode)
        token = data.get("token", "")  # Use fresh token

        # ── 6. GET /api/me ──
        print("\n[6] User profile")
        status, data = api("GET", "/api/me", token=token)
        test("GET /api/me returns 200", status == 200)
        test("Email matches", data.get("email") == "testuser@example.com")
        test("Tier is free", data.get("tier") == "free")

        # ── 7. Contacts CRUD ──
        print("\n[7] Contacts CRUD")
        # Add
        status, data = api("POST", "/api/contacts", {"name": "Alice Smith", "email": "alice@example.com", "phone": "555-1234", "company": "Acme"}, token=token)
        test("POST /api/contacts returns 201", status == 201)
        test("Contact has name", data.get("name") == "Alice Smith")
        contact_id = data.get("id")

        status, data = api("POST", "/api/contacts", {"name": "Bob Jones", "email": "bob@example.com", "phone": "555-5678", "company": "Initech"}, token=token)
        test("Second contact added", status == 201)

        # List
        status, data = api("GET", "/api/contacts", token=token)
        test("GET /api/contacts returns list", status == 200 and isinstance(data, list))
        test("Two contacts in list", len(data) == 2)

        # Delete
        status, data = api("POST", "/api/contacts/delete", {"id": contact_id}, token=token)
        test("DELETE contact returns ok", status == 200 and data.get("deleted") is True)

        status, data = api("GET", "/api/contacts", token=token)
        test("One contact remaining", len(data) == 1)

        # Validation
        status, data = api("POST", "/api/contacts", {"name": ""}, token=token)
        test("Empty name rejected (400)", status == 400)

        # ── 8. Affiliates ──
        print("\n[8] Affiliates")
        status, data = api("POST", "/api/affiliates", {"email": "creator@influencer.com", "commission_rate": 0.12}, token=token)
        test("POST /api/affiliates returns 201", status == 201)
        test("Has referral_code", "referral_code" in data)
        test("Rate is 0.12", data.get("commission_rate") == 0.12)
        aff_code = data.get("referral_code", "")
        aff_email = data.get("email", "")

        # Duplicate
        status, data = api("POST", "/api/affiliates", {"email": "creator@influencer.com"}, token=token)
        test("Duplicate affiliate returns existing (200)", status == 200)
        test("Same code on re-register", data.get("referral_code") == aff_code)

        # List
        status, data = api("GET", "/api/affiliates", token=token)
        test("GET /api/affiliates returns list", isinstance(data, list) and len(data) >= 1)

        # ── 9. Webhook / Order attribution ──
        print("\n[9] Order attribution (webhooks)")
        # Invalid code
        status, data = api("POST", "/api/webhooks/order", {"discount_code": "FAKE-CODE", "order_total": 100})
        test("Invalid code returns 404", status == 404)
        test("attributed=False", data.get("attributed") is False)

        # Valid code
        status, data = api("POST", "/api/webhooks/order", {"discount_code": aff_code, "order_total": 500})
        test("Valid code returns 200", status == 200)
        test("attributed=True", data.get("attributed") is True)
        test("Affiliate matched", data.get("affiliate") == aff_email)
        commission = data.get("commission", 0)
        test(f"Commission is $60 (12% of $500)", commission == 60.0)
        test("Platform fee calculated", data.get("platform_fee", 0) > 0)
        platform_fee = data.get("platform_fee", 0)
        test(f"Platform fee is $25 (5% of $500)", platform_fee == 25.0)

        # Second order (different amount)
        status, data = api("POST", "/api/webhooks/order", {"discount_code": aff_code, "order_total": 1000})
        test("Second order attributed", data.get("attributed") is True)

        # ── 10. Commissions ──
        print("\n[10] Commission history")
        status, data = api("GET", "/api/commissions", token=token)
        test("GET /api/commissions returns list", isinstance(data, list))
        test("Two commissions recorded", len(data) == 2)

        # ── 11. Stats ──
        print("\n[11] Dashboard stats")
        status, data = api("GET", "/api/stats", token=token)
        test("GET /api/stats returns 200", status == 200)
        test("Contacts count = 1", data.get("contacts") == 1)
        test("Affiliates count >= 1", data.get("affiliates") >= 1)
        test("Commissions count = 2", data.get("commissions") == 2)
        test("Revenue = $1500", data.get("attributed_revenue") == 1500.0)
        test("Has activity feed", isinstance(data.get("activity"), list) and len(data["activity"]) > 0)

        # ── 12. Commission tiers ──
        print("\n[12] Commission tier calculation")
        # Register a whale affiliate
        status, data = api("POST", "/api/affiliates", {"email": "whale@volume.com", "commission_rate": 0.10}, token=token)
        whale_code = data.get("referral_code", "")

        # Stack up orders to cross tier boundaries
        running_total = 0
        for i, amt in enumerate([5000, 10000, 50000, 100000, 150000]):
            status, data = api("POST", "/api/webhooks/order", {
                "discount_code": whale_code,
                "order_total": amt,
                "order_id": f"WHALE-{i:03d}"
            })
            if status == 200:
                running_total += amt
                fee_pct = round(data["platform_fee"] / amt * 100, 1)

        # Check the whale's total
        status, affs = api("GET", "/api/affiliates", token=token)
        whale = next((a for a in affs if a["email"] == "whale@volume.com"), None)
        test("Whale affiliate exists", whale is not None)
        if whale:
            test(f"Whale total_earned = ${whale['total_earned']}", whale["total_earned"] == 31500.0)
            test(f"Whale total_referrals = 5", whale["total_referrals"] == 5)

        # Check that later orders had lower platform fees (tier degradation)
        status, comms = api("GET", "/api/commissions", token=token)
        whale_comms = [c for c in comms if c["affiliate_email"] == "whale@volume.com"]
        if len(whale_comms) >= 2:
            # Last order should have a lower fee rate than first
            first_rate = max(c["platform_fee_rate"] for c in whale_comms)
            last_rate = min(c["platform_fee_rate"] for c in whale_comms)
            test(f"Tier degraded: {first_rate*100}% → {last_rate*100}%", last_rate < first_rate, f"first={first_rate}, last={last_rate}")

        # ── 13. Signup validation ──
        print("\n[13] Input validation")
        status, data = api("POST", "/api/signup", {"email": ""})
        test("Empty email rejected", status == 400)
        status, data = api("POST", "/api/signup", {"email": "not-an-email"})
        test("Invalid email rejected", status == 400)

    finally:
        # Shutdown
        proc.terminate()
        proc.wait(timeout=5)

    # Summary
    print(f"\n{'='*50}")
    print(f"  Results: {PASSED} passed, {FAILED} failed")
    print(f"{'='*50}\n")
    sys.exit(1 if FAILED > 0 else 0)


if __name__ == "__main__":
    main()
