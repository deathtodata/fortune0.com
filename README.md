# fortune0

> 230 domains. Open incubator. $1 to participate.

fortune0 is a platform where people sign up, pick domains, earn commissions by referring others, and launch micro-businesses. The platform handles operations (hosting, payments, tracking). You handle distribution.

Everything runs from one Python file with zero dependencies.

## Quick Start

```bash
python3 server.py
```

Open http://localhost:8080. That's it — landing page, dashboard, API, database, everything.

## How It Works

`server.py` is the entire backend. It serves the website, runs the API, and stores data in SQLite. No frameworks, no npm install, no config files. One file, one command.

When someone signs up at `/app`, they get:
- A license key (like `IK-xxxxx`) that expires in 28 days
- A referral code for tracking who they bring in
- A CRM dashboard for contacts, affiliates, and commissions

When someone joins as an affiliate at `/join`, they get a QR code and referral link they can share. Every referred sale earns them a commission (3-5% based on volume).

## Deploy (Make It Live)

Right now fortune0.com is on GitHub Pages, which can only serve static HTML — no Python, no API, no database. That's why `/app` doesn't work on the live site.

To make everything work, deploy `server.py` to any host that runs Python:

### Option 1: Render.com (free, easiest)

1. Go to [render.com](https://render.com) and sign in with GitHub
2. Click "New" → "Web Service" → connect the `deathtodata/fortune0.com` repo
3. It auto-detects `render.yaml` and configures everything
4. In Cloudflare DNS, point `fortune0.com` to your Render URL (or use Render's custom domain settings)

### Option 2: Docker (any server)

```bash
docker compose up -d
```

### Option 3: Run from your Mac + Cloudflare Tunnel

```bash
# One-time setup (creates permanent tunnel)
./tunnel-setup.command

# Then whenever you want it live:
./start.command
```

This makes your Mac the server. Platform lives at `platform.fortune0.com` as long as your Mac is running.

### Option 4: Any VPS ($5/month)

```bash
scp -r . you@yourserver:/app/fortune0
ssh you@yourserver "cd /app/fortune0 && python3 server.py &"
```

## Environment Variables

| Variable | What it does | Default |
|---|---|---|
| `PORT` | Server port | `8080` |
| `F0_LICENSE_SECRET` | Signs license keys so they can't be faked. Set to any random string in production. Locally it doesn't matter. | `fortune0-dev-secret-2026` |

That's it. Two env vars. `PORT` is set automatically by most hosts. `F0_LICENSE_SECRET` has a default that works for dev. In production, your host (Render, etc.) auto-generates one.

## Pages

| URL | What it is |
|---|---|
| `/` | Landing page (Three.js particles, Stripe link) |
| `/app` | Platform console — sign in, CRM, affiliates, commissions |
| `/join` | Affiliate onboarding — get QR code + referral link |
| `/ideas` | Browse the 230 domains |
| `/pitch` | Pitch animation |
| `/why` | Philosophy page |
| `/projects` | Launched projects |
| `/storyboard` | Dev planning board |
| `/blueprint` | Architecture overview |

## API

All routes return JSON. Auth via `Authorization: Bearer <token>` header.

**Public:** `GET /health`, `POST /api/signup`, `POST /api/join`, `GET /r/<code>`

**Authenticated:** `GET /api/me`, `GET /api/stats`, `GET /api/contacts`, `POST /api/contacts`, `GET /api/affiliates`, `POST /api/affiliates`, `GET /api/commissions`

## Tests

```bash
python3 run_tests.py       # 58 assertions
python3 test_referral.py   # 30 assertions
```

Tests run automatically on every push via GitHub Actions.

## Structure

```
fortune0.com/
├── server.py              ← the whole backend (API + static files + SQLite)
├── app.html               ← platform console
├── join.html              ← affiliate onboarding
├── index.html             ← landing page
├── ideas.html, pitch.html, why.html, projects.html, etc.
├── assets/                ← trailers, logos, GIFs
├── _build/                ← build tools, Cloudflare worker
├── _archive/              ← deprecated files
├── data/fortune0.db       ← SQLite database (auto-created)
├── render.yaml            ← one-click Render.com deploy
├── Dockerfile             ← container build
├── docker-compose.yml     ← one-command Docker dev
├── start.command          ← macOS double-click launcher
├── tunnel-setup.command   ← Cloudflare Tunnel setup
└── run_tests.py, test_referral.py ← test suites
```

## Launched

- **death2data.com** — $1 privacy notebooks

---

fortune0.com
