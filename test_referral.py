#!/usr/bin/env python3
"""Test the referral/QR/join flow."""
import json, os, subprocess, sys, time, urllib.request, urllib.error

PORT = 9998
BASE = f"http://localhost:{PORT}"
PASSED = FAILED = 0

def api(method, path, body=None, token=None, follow=False):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        if not follow:
            # Don't follow redirects
            import http.client
            conn = http.client.HTTPConnection("localhost", PORT)
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            body_text = resp.read().decode()
            try:
                return resp.status, json.loads(body_text), dict(resp.getheaders())
            except:
                return resp.status, {"raw": body_text}, dict(resp.getheaders())
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read()), {}
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), {}
    except Exception as e:
        return 0, {"error": str(e)}, {}

def test(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1; print(f"  ✓ {name}")
    else:
        FAILED += 1; print(f"  ✗ {name} — {detail}")

def main():
    # Run from the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))

    db_path = os.path.join(script_dir, "data", "fortune0.db")
    os.makedirs(os.path.join(script_dir, "data"), exist_ok=True)
    if os.path.exists(db_path): os.remove(db_path)

    env = os.environ.copy()
    env["F0_PORT"] = str(PORT)
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=script_dir, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    for _ in range(20):
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=1); break
        except: time.sleep(0.3)
    else:
        print("FATAL: Server did not start"); proc.kill(); sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  Referral Flow Tests — {BASE}")
    print(f"{'='*50}\n")

    try:
        # 1. Join page serves
        print("[1] Join page")
        status, _, _ = api("GET", "/join", follow=False)
        test("GET /join returns 200", status == 200)

        # 2. Self-service join
        print("\n[2] Self-service affiliate join")
        status, data, _ = api("POST", "/api/join", {"email": "creator@example.com"}, follow=True)
        test("POST /api/join returns 201", status == 201, f"got {status}")
        test("Returns referral_code", "referral_code" in data and data["referral_code"].startswith("IK-"))
        test("Returns short_url", "/r/" in data.get("short_url", ""))
        test("Returns token", len(data.get("token", "")) > 10)
        test("Returns license_key", data.get("license_key", "").startswith("IK-"))
        test("clicks = 0", data.get("clicks") == 0)
        test("returning = False", data.get("returning") is False)
        code = data.get("referral_code", "")
        token = data.get("token", "")

        # 3. Re-join (returning user)
        print("\n[3] Returning affiliate")
        status, data, _ = api("POST", "/api/join", {"email": "creator@example.com"}, follow=True)
        test("Returns 200 for existing", status == 200)
        test("returning = True", data.get("returning") is True)
        test("Same code", data.get("referral_code") == code)

        # 4. Referral redirect
        print("\n[4] Referral redirect (/r/<code>)")
        status, _, headers = api("GET", f"/r/{code}", follow=False)
        test("GET /r/<code> returns 302", status == 302, f"got {status}")
        location = headers.get("Location", "")
        test("Redirects to /join?ref=<code>", f"/join?ref={code}" in location, f"got {location}")

        # 5. Unknown code still redirects
        print("\n[5] Unknown referral code")
        status, _, headers = api("GET", "/r/FAKE-CODE-123", follow=False)
        test("Unknown code returns 302", status == 302)
        test("Redirects to /join", headers.get("Location", "") == "/join")

        # 6. Click tracking
        print("\n[6] Click tracking")
        # Make a few more clicks
        api("GET", f"/r/{code}", follow=False)
        api("GET", f"/r/{code}", follow=False)

        # Check stats
        status, data, _ = api("GET", f"/api/affiliate/stats?code={code}", follow=True)
        test("GET /api/affiliate/stats returns 200", status == 200, f"got {status}")
        test("Clicks >= 3", data.get("clicks", 0) >= 3, f"got {data.get('clicks')}")
        test("Has email", data.get("email") == "creator@example.com")
        test("Has commission_rate", data.get("commission_rate") == 0.10)

        # 7. Affiliate shows up in main API
        print("\n[7] Integration with main system")
        status, data, _ = api("GET", "/api/affiliates", token=token, follow=True)
        test("Affiliate visible in /api/affiliates", status == 200 and any(a.get("referral_code") == code for a in data))

        # The user account was also created
        status, data, _ = api("GET", "/api/me", token=token, follow=True)
        test("User account exists via /api/me", status == 200 and data.get("email") == "creator@example.com")

        # 8. Full loop: join → get code → simulate order → check earnings
        print("\n[8] Full affiliate earning loop")
        # Register second affiliate
        status, data2, _ = api("POST", "/api/join", {"email": "hustler@example.com"}, follow=True)
        code2 = data2.get("referral_code", "")
        test("Second affiliate joined", status == 201)

        # Simulate order with their code
        status, order, _ = api("POST", "/api/webhooks/order", {
            "discount_code": code2, "order_total": 250
        }, follow=True)
        test("Order attributed", order.get("attributed") is True)
        test("Commission = $25 (10%)", order.get("commission") == 25.0)

        # Check their stats
        status, stats, _ = api("GET", f"/api/affiliate/stats?code={code2}", follow=True)
        test("Earnings updated", stats.get("total_earned") == 25.0)
        test("Referrals = 1", stats.get("total_referrals") == 1)

        # 9. Validation
        print("\n[9] Input validation")
        status, _, _ = api("POST", "/api/join", {"email": ""}, follow=True)
        test("Empty email rejected", status == 400)
        status, _, _ = api("POST", "/api/join", {"email": "nope"}, follow=True)
        test("Invalid email rejected", status == 400)
        status, _, _ = api("GET", "/api/affiliate/stats?code=", follow=True)
        test("Empty code rejected", status == 400)
        status, _, _ = api("GET", "/api/affiliate/stats?code=FAKE", follow=True)
        test("Unknown code returns 404", status == 404)

    finally:
        proc.terminate()
        proc.wait(timeout=5)

    print(f"\n{'='*50}")
    print(f"  Results: {PASSED} passed, {FAILED} failed")
    print(f"{'='*50}\n")
    sys.exit(1 if FAILED else 0)

if __name__ == "__main__":
    main()
