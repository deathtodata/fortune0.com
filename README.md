# fortune0

> 230 domains. Open incubator. $1 to participate.

## Structure

```
fortune0.com/
│
├── index.html              # Landing (Three.js) — served by GitHub Pages
├── ideas.html              # Browse 230 domains
├── domain-template.html    # Single domain page (?d=x.com)
├── pitch.html              # Animation builder
├── why.html                # Philosophy
├── projects.html           # Launched projects
├── newsletter.html         # Newsletter
├── thanks.html             # Post-signup
├── 404.html
│
├── server.py               # Platform backend (zero dependencies)
├── app.html                # Platform console (CRM, affiliates, commissions)
├── join.html               # Affiliate onboarding + QR generator
├── storyboard.html         # Dev planning board
├── blueprint.html          # Architecture blueprint
│
├── domains.json            # All domain data
├── config.json             # Site config
├── favicon.svg
│
├── assets/                 # Brand assets
│   ├── fortune0-trailer.mp4
│   ├── death2data-trailer.mp4
│   └── ...
│
├── newsletters/            # Newsletter archive
├── _build/                 # Build tools (not served)
├── _archive/               # Deprecated (not served)
├── run_tests.py            # E2E test suite (58 assertions)
├── test_referral.py        # Referral flow tests (30 assertions)
├── Dockerfile              # Container build (optional)
├── docker-compose.yml      # One-command local dev
└── start.command           # macOS double-click launcher
```

## Launched

- **death2data.com** - $1 privacy notebooks

## Local Dev

Static pages (GitHub Pages):
```bash
python3 -m http.server 3000
```

Full platform with API:
```bash
python3 server.py
```

Then open http://localhost:8080

## API endpoints

All API routes return JSON. Auth via `Authorization: Bearer <token>` header.

**Public:**
- `GET /health` — server status
- `POST /api/signup` — create account `{email}`
- `POST /api/join` — self-service affiliate signup `{email}`
- `GET /r/<code>` — referral redirect + click tracking

**Authenticated:**
- `GET /api/me` — current user profile
- `GET /api/stats` — dashboard statistics
- `GET /api/contacts` — list contacts
- `POST /api/contacts` — add contact
- `GET /api/affiliates` — list affiliates
- `POST /api/affiliates` — register affiliate
- `GET /api/commissions` — commission history

## Tests

```bash
python3 run_tests.py       # 58 assertions
python3 test_referral.py   # 30 assertions
```

Tests run automatically on every push via GitHub Actions.

## Deploy

Static site: GitHub Pages from `main` branch.

Platform API: Deploy `server.py` anywhere Python 3.8+ runs. Set `F0_LICENSE_SECRET` env var.

---

fortune0.com
