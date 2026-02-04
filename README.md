# fortune0

> 230 domains. Open incubator. $1 to participate.

## Structure

```
fortune0.com/
│
├── index.html              # Landing (Three.js)
├── ideas.html              # Browse 230 domains
├── domain-template.html    # Single domain page (?d=x.com)
├── pitch.html              # Animation builder
├── why.html                # Philosophy
├── projects.html           # Launched projects
├── newsletter.html         # Newsletter
├── thanks.html             # Post-signup
├── 404.html
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
├── projects/               # Project folders
│   └── death2data/
│
├── _build/                 # Build tools (not served)
│   ├── trailer_generator.py
│   └── kinetic_type.py
│
└── _archive/               # Deprecated (not served)
    ├── idea.html
    ├── ideas.json
    └── ...
```

## Launched

- **death2data.com** - $1 privacy notebooks

## Local Dev

```bash
python3 -m http.server 3000
```

## Deploy

GitHub Pages from `main` branch.

---

matt@fortune0.com
