# fortune0

> 230 domains. Open incubator. You build, we launch.

fortune0 is an open framework for starting companies from scratch. We own the domains. You pitch what they should become. If selected, you build it.

## Status Key

| Symbol | Meaning |
|--------|---------|
| 🟢 | Open - accepting pitches |
| 🔒 | Claimed - builder selected |
| 🏗️ | Building - in development |
| ✅ | Launched - live product |
| 💀 | Abandoned - reopened |

## How It Works

1. **Browse** → [fortune0.com/ideas.html](https://fortune0.com/ideas.html)
2. **Pick a domain** → 230+ available, filtered by category
3. **Submit pitch** → What would you build?
4. **Get selected** → We review within 7 days
5. **Build it** → 30-90 day sprint
6. **Launch** → Ship under the domain

## File Structure

```
fortune0.com/
├── index.html          # Landing page
├── ideas.html          # Browse all 230 domains
├── domains.json        # Domain data (edit this to add/update)
├── config.json         # Site configuration
├── newsletter.html     # Newsletter archive
├── newsletters/        # Individual issues
├── CONTRIBUTING.md     # How to pitch/apply
├── PROJECT-TEMPLATE.md # Template for new projects
└── README.md           # This file
```

## For Builders

See [CONTRIBUTING.md](./CONTRIBUTING.md) for:
- How to apply
- Compensation models (hourly, revenue share, equity)
- The build process
- Rules and expectations

## For New Projects

Use [PROJECT-TEMPLATE.md](./PROJECT-TEMPLATE.md) to document:
- Project overview
- MVP scope
- Tech stack
- Progress tracking

## Local Development

```bash
python3 -m http.server 3000
# Then open http://localhost:3000
```

## Deployment

Currently on GitHub Pages:
- Repo: github.com/deathtodata/fortune0.com
- Live: fortune0.com

## Edit Domains

To add/remove/update domains, edit `domains.json`:

```json
{
  "domain": "example.com",
  "value": 1000,
  "expires": "2026-08-28",
  "status": "open"
}
```

Push changes → site updates automatically.

## Legal

fortune0 is a DBA of [Your Company Name].

All projects built under fortune0 operate under this umbrella. Specific terms negotiated per project.

---

**Questions?** matt@fortune0.com
