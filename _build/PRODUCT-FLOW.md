# fortune0 Product Flow

## The Loop

```
┌─────────────────────────────────────────────────────────┐
│                    fortune0.com                          │
│                                                          │
│  Featured Domain of the Day: wrongtab.com               │
│  "47 tabs open. Can't find anything."                   │
│                                                          │
│  [Submit Your Idea] [Vote] [Use Credits to Research]   │
└─────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
      FREE USER      $1 SUBSCRIBER    POWER USER
      - Browse        - Everything     - Everything
      - Submit idea   - Vote on ideas  - AI research credits
      - See results   - Earn credits   - Priority features
                      - Access tools
```

## How Credits Work

### Earning Credits
- Submit idea that gets 10+ votes = 5 credits
- Refer someone who subscribes = 10 credits
- Daily login streak = 1 credit/day

### Spending Credits
- AI search (Ollama powered) = 1 credit
- Deep research on a domain = 5 credits
- Generate pitch deck = 10 credits

## Daily Domain Feature

Each day, domains.json rotates which domain is "featured":

```javascript
// Simple rotation based on day of year
const domains = await fetch('/domains.json').then(r => r.json());
const dayOfYear = Math.floor((Date.now() - new Date(2026,0,1)) / 86400000);
const featured = domains[dayOfYear % domains.length];
```

## Data Flow

```
User visits fortune0.com
    │
    ▼
Not logged in ──────────────────────┐
    │                               │
    ▼                               ▼
[Enter email to participate]    [Browse only]
    │
    ▼
Worker: check-access
    │
    ├── access: false ──► Show $1 subscribe link
    │
    └── access: true ──► Unlock:
                          - Voting
                          - Idea submission
                          - Credit balance
                          - AI tools (if credits > 0)
```

## What Each Domain Page Shows

### Public (everyone)
- Domain name
- Current tagline/description
- Top 3 ideas (titles only)
- "Subscribe to vote and submit"

### Subscribers ($1)
- All ideas with full details
- Vote buttons
- Submit idea form
- Your credit balance
- Access to research tools

## Credit Balance Storage

```javascript
// In KV, store per-user:
subscriber:matt@example.com = {
  email: "matt@example.com",
  tier: "d2d",
  credits: 50,
  lastLogin: "2026-02-04",
  streak: 7
}
```

## Implementation Priority

1. ✅ Access check (DONE)
2. [ ] Add credits field to subscriber sync
3. [ ] Featured domain rotation on homepage
4. [ ] Idea submission form (stores in KV)
5. [ ] Voting system (increment vote count)
6. [ ] Credit spending (AI search integration)
