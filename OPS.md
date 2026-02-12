# fortune0 Operations Guide

Every command you need, in order, for every situation.

---

## MCP: Let AI Apps Use fortune0 (No Hosting Needed)

This is the easiest way to demo fortune0. No website, no server, no hosting. People just talk to Claude and Claude talks to fortune0.

```bash
# One-time install
pip install fastmcp

# Test it works
python3 ~/code/fortune0-site/mcp_server.py
```

Then add to Claude Desktop config (`~/.claude/claude_desktop_config.json`):

```json
{
    "mcpServers": {
        "fortune0": {
            "command": "python3",
            "args": ["/Users/matthewmauer/code/fortune0-site/mcp_server.py"]
        }
    }
}
```

Restart Claude Desktop. Now you (or anyone) can say:
- "Sign me up for fortune0 with my email"
- "Show my dashboard stats"
- "Add a contact named John at john@example.com"
- "What's my referral code?"
- "Join the affiliate program"

The database is the same one server.py uses. Everything stays local.

---

## Daily: Push Changes to GitHub

```bash
cd ~/code/fortune0-site
rm -f .git/index.lock
git add -A
git commit -m "describe what changed"
git push
```

If it says "index.lock exists", that first `rm` line fixes it. If it says "nothing to commit", you're already up to date.

---

## First Time: Deploy to Render (Make the Site Actually Work)

Right now fortune0.com is on GitHub Pages which can't run the API. This moves everything to Render so it all works.

1. Go to https://render.com
2. Click "Get Started" → sign in with GitHub (use Soulfra account)
3. Click "New" → "Web Service"
4. Find `deathtodata/fortune0.com` and click "Connect"
5. It reads `render.yaml` automatically — just click "Create Web Service"
6. Wait 2-3 minutes for it to build
7. Render gives you a URL like `fortune0-xxxx.onrender.com`
8. Test it: go to that URL — you should see the landing page
9. Test the API: go to that URL + `/app` — sign in should work

Then point your real domain at it:

10. Go to Cloudflare dashboard → DNS for fortune0.com
11. Find the CNAME record that points to `deathtodata.github.io`
12. Change it to point to your Render URL instead
13. In Render dashboard → Settings → Custom Domains → add `fortune0.com`
14. Wait 5-10 minutes for DNS to propagate

After this, fortune0.com runs everything — landing page, app, API, database. GitHub Pages is no longer needed.

---

## First Time: Cloudflare Tunnel (Run from Your Mac Instead)

If you'd rather run it from your own Mac instead of Render:

```bash
cd ~/code/fortune0-site
./tunnel-setup.command
```

This walks you through everything. After setup:

```bash
./start.command
```

Platform is live at `platform.fortune0.com` while your Mac is on.

---

## Check if the Site is Working

```bash
# Local
curl http://localhost:8080/health

# Live (after deploying)
curl https://fortune0.com/health
```

Should return: `{"status": "ok", ...}`

If it returns HTML or an error, the API server isn't running.

---

## Look at the Database

```bash
cd ~/code/fortune0-site
sqlite3 data/fortune0.db

# See all users
SELECT * FROM users;

# See all affiliates
SELECT * FROM affiliates;

# See commissions
SELECT * FROM commissions;

# See recent activity
SELECT * FROM activity ORDER BY created_at DESC LIMIT 10;

# Exit
.quit
```

---

## Kill a Stuck Server

```bash
# Find what's on port 8080
lsof -i :8080

# Kill it (replace PID with the number from above)
kill <PID>

# Or kill all Python servers
pkill -f server.py
```

---

## Run Tests

```bash
cd ~/code/fortune0-site
python3 run_tests.py       # 58 checks
python3 test_referral.py   # 30 checks
```

All 88 should pass. If they fail because of an existing database:

```bash
rm data/fortune0.db
python3 run_tests.py
```

---

## Clean Up Corrupted Files on Mac

```bash
# Delete the pileup of corrupted claude.json files
cd ~
rm -f .claude.json.corrupted.*

# Delete git lock files
rm -f ~/code/fortune0-site/.git/index.lock
```

---

## Affiliate Onboarding: How It Works

1. Someone goes to `fortune0.com/join`
2. They enter their email
3. They get a referral code (like `IK-A1B2C3D4`) and a QR code
4. They share the QR code or link (`fortune0.com/r/IK-A1B2C3D4`)
5. Anyone who clicks that link and signs up is tracked to them
6. When a tracked user makes a purchase, the affiliate earns 3-5%
7. The affiliate can see their stats in the dashboard at `/app`

Commission tiers:
- Under $10K revenue: 5% commission
- $10K - $50K: 4%
- $50K - $250K: 3.5%
- Over $250K: 3%

---

## What Each File Does

| File | Purpose | Do you edit it? |
|---|---|---|
| `server.py` | The entire backend — API, database, serves all pages | Only if adding features |
| `app.html` | Dashboard users see after signing in | For UI changes |
| `join.html` | Affiliate signup page with QR codes | For UI changes |
| `index.html` | Landing page with Three.js animation | For marketing changes |
| `ideas.html` | Browse the 230 domains | For domain list changes |
| `domains.json` | The actual list of 230 domains | To add/remove domains |
| `render.yaml` | Tells Render how to deploy | Don't touch |
| `Dockerfile` | Tells Docker how to build | Don't touch |
| `start.command` | Double-click to launch locally | Don't touch |
| `run_tests.py` | Automated tests | Only if adding test cases |
| `OPS.md` | This file | Update as needed |

---

## What the Environment Variables Mean

| Variable | What it does | When to set it |
|---|---|---|
| `PORT` | Which port the server listens on | Render sets this automatically. Locally defaults to 8080. |
| `F0_LICENSE_SECRET` | A password that signs license keys so nobody can fake them | Render generates this automatically via render.yaml. Locally uses a dev default. |

---

## Emergency: Site is Down

1. Check if the server is running: `curl https://fortune0.com/health`
2. If no response: log into Render dashboard, check the service status
3. If Render shows an error: click "Manual Deploy" → "Deploy latest commit"
4. If using Cloudflare Tunnel: make sure your Mac is on and `start.command` is running
5. If all else fails: run locally with `python3 server.py` and test at localhost:8080

---

fortune0.com
