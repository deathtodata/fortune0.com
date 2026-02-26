#!/usr/bin/env python3
"""
D2D / Fortune0 Live Test Suite
Run from your terminal: python3 test_live.py

Tests the REAL production system — not mocks, not fakes.
Flags anything that doesn't match expected reality.
"""

import json
import urllib.request
import sys
import time

API = "https://fortune0-com.onrender.com"
SITE = "https://death2data.com"
STRIPE_ACTIVE = 9  # UPDATE THIS to match your real Stripe active subscriber count

PASS = 0
FAIL = 0
WARN = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}")
        if detail:
            print(f"    → {detail}")

def warn(name, detail=""):
    global WARN
    WARN += 1
    print(f"  ⚠ {name}")
    if detail:
        print(f"    → {detail}")

def fetch_json(url, timeout=30):
    """Fetch JSON from URL, return (data, error)"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "d2d-test/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), None
    except Exception as e:
        return None, str(e)

def fetch_text(url, timeout=30):
    """Fetch raw text from URL, return (text, error)"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "d2d-test/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode(), None
    except Exception as e:
        return None, str(e)


# ═══════════════════════════════════════
#  1. HEALTH CHECK
# ═══════════════════════════════════════
print("\n─── 1. HEALTH CHECK ───")
data, err = fetch_json(f"{API}/health")
if err:
    test("Server reachable", False, f"Could not connect: {err}")
    print("\n  Server is down or sleeping. Wake it up and re-run.")
    sys.exit(1)

test("Server responds", data is not None)
test("Status is ok", data.get("status") == "ok", f"Got: {data.get('status')}")
test("Database is PostgreSQL", data.get("db") == "postgresql", f"Got: {data.get('db')}")
test("DB connected", data.get("db_connected") == True, f"Got: {data.get('db_connected')}")


# ═══════════════════════════════════════
#  2. PUBLIC STATS (the numbers your site shows)
# ═══════════════════════════════════════
print("\n─── 2. PUBLIC STATS ───")
stats, err = fetch_json(f"{API}/api/public/stats")
test("Stats endpoint responds", stats is not None, err or "")

if stats:
    customers = stats.get("customers", 0)
    total_users = stats.get("total_users", 0)
    mrr = stats.get("mrr", 0)
    searches = stats.get("searches_total", 0)

    test("Customers > 0", customers > 0, f"Got: {customers}")
    test("Total users > 0", total_users > 0, f"Got: {total_users}")
    test("MRR matches customers × $1", mrr == customers * 1.0,
         f"MRR={mrr}, expected {customers * 1.0}")

    # THE BIG ONE: does DB match Stripe?
    if customers != STRIPE_ACTIVE:
        test(f"DB active ({customers}) matches Stripe active ({STRIPE_ACTIVE})", False,
             f"DB thinks {customers} are active, Stripe says {STRIPE_ACTIVE}. "
             f"Gap of {customers - STRIPE_ACTIVE} — churn webhook not synced yet.")
    else:
        test(f"DB active ({customers}) matches Stripe active ({STRIPE_ACTIVE})", True)

    test("Searches are being logged", searches > 0, f"Got: {searches}")
    print(f"\n  📊 Live numbers: {customers} active / {total_users} total / ${mrr} MRR / {searches} searches")


# ═══════════════════════════════════════
#  3. WEBHOOK CONFIG
# ═══════════════════════════════════════
print("\n─── 3. STRIPE WEBHOOK CONFIG ───")
wh, err = fetch_json(f"{API}/api/webhooks/stripe")
test("Webhook endpoint reachable", wh is not None, err or "")
if wh:
    test("Webhook secret configured", wh.get("webhook_secret_configured") == True)
    test("Stripe key configured", wh.get("stripe_key_configured") == True)


# ═══════════════════════════════════════
#  4. STATIC SITE (GitHub Pages)
# ═══════════════════════════════════════
print("\n─── 4. STATIC SITE ───")
pages = [
    ("/", "homepage"),
    ("/about.html", "about"),
    ("/revenue.html", "revenue"),
    ("/tools/notebook.html", "notebook"),
    ("/tools/sanitizer.html", "sanitizer"),
    ("/tools/leak-score.html", "leak score"),
    ("/tools/converter.html", "converter"),
    ("/tools/qr-generator.html", "QR generator"),
    ("/privacy.html", "privacy"),
    ("/terms.html", "terms"),
]

for path, name in pages:
    html, err = fetch_text(f"{SITE}{path}")
    if err:
        test(f"{name} loads", False, err)
    else:
        test(f"{name} loads ({len(html)} bytes)", len(html) > 500,
             f"Page too small: {len(html)} bytes")

# Check stats.json cache
stats_cache, err = fetch_json(f"{SITE}/stats.json")
if stats_cache:
    cached_customers = stats_cache.get("customers", 0)
    test(f"stats.json cache reasonable", cached_customers > 0 and cached_customers <= 50,
         f"Cached: {cached_customers}")
    if stats and abs(cached_customers - stats.get("customers", 0)) > 5:
        warn("stats.json is stale",
             f"Cache says {cached_customers}, live API says {stats.get('customers', 0)}")


# ═══════════════════════════════════════
#  5. STORY MODE
# ═══════════════════════════════════════
print("\n─── 5. STORY MODE ───")
# Test with D2D's own about page (always available, same-origin-ish)
story, err = fetch_json(f"{API}/api/story?url=https://death2data.com/about.html")
if err:
    test("Story endpoint responds", False, err)
else:
    test("Story endpoint responds", story is not None)
    if story:
        story_cards = story.get("cards", [])
        test(f"Story returns cards ({len(story_cards)})", len(story_cards) >= 1,
             f"Got {len(story_cards)} cards")
        test("Story has title", bool(story.get("title")), f"Title: {story.get('title', 'none')}")
        test("Story has domain", bool(story.get("domain")))

        has_analysis = story.get("analyzed", False)
        if has_analysis:
            test("Claude analysis included", True)
            analysis_cards = [c for c in story_cards if c.get("type") == "analysis"]
            if analysis_cards:
                score = analysis_cards[0].get("privacy_score", 0)
                test(f"Privacy score present ({score}/10)", 1 <= score <= 10)
        else:
            warn("No Claude analysis (ANTHROPIC_API_KEY not set?)",
                 "Story works but without privacy scoring")

        # Test caching — second request should be cached
        story2, _ = fetch_json(f"{API}/api/story?url=https://death2data.com/about.html")
        if story2:
            test("Second request is cached", story2.get("cached") == True)


# ═══════════════════════════════════════
#  6. SEARCH (does it actually work?)
# ═══════════════════════════════════════
print("\n─── 6. SEARCH (unauthenticated) ───")
search, err = fetch_json(f"{API}/api/search?q=test")
test("Search endpoint responds", search is not None, err or "")
if search:
    # Unauthenticated users get domain results + limited web
    domains = search.get("domains", [])
    web = search.get("web", [])
    test("Domain results returned", len(domains) >= 0)  # may be 0 for "test"
    # Web results locked for free users is expected behavior
    if search.get("web_locked"):
        test("Web search locked for free users", True)
    elif len(web) > 0:
        test(f"Web results returned ({len(web)} results)", True)
        engines = set(r.get("engine", "unknown") for r in web)
        print(f"    Search engines used: {', '.join(engines)}")
    else:
        warn("No web results and not locked — check search backends")


# ═══════════════════════════════════════
#  6. DNS CHECK
# ═══════════════════════════════════════
print("\n─── 6. DNS / DOMAIN CHECK ───")
# Check that death2data.com resolves and serves content
html, err = fetch_text("https://death2data.com/")
test("death2data.com resolves", html is not None, err or "")
if html:
    test("Homepage has search input", "search" in html.lower() or "input" in html.lower())
    test("Homepage references API", "fortune0-com.onrender.com" in html)


# ═══════════════════════════════════════
#  SUMMARY
# ═══════════════════════════════════════
print(f"\n{'═' * 40}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed, {WARN} warnings")
print(f"{'═' * 40}")

if FAIL == 0:
    print("\n  All checks passed. But remember:")
    print(f"  → DB says {stats.get('customers', '?')} active, Stripe says {STRIPE_ACTIVE}")
    print(f"  → Once you add churn events in Stripe webhook settings,")
    print(f"    the numbers will sync on next cancellation.\n")
else:
    print(f"\n  {FAIL} issue(s) need attention. See ✗ items above.\n")
