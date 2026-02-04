# Security & PII Handling for fortune0

## What's PII (don't leak this)
- Email addresses
- Customer IDs
- Payment info
- Stripe keys
- Admin keys

## What's public (okay to expose)
- Domain names
- Product names
- Pricing (public anyway)
- Access: true/false responses

## Endpoint Security Checklist

### /check-access (PUBLIC)
- Input: email
- Output: { access: true/false, tier: string }
- ✓ Safe: Only returns boolean, never lists other users
- ✓ Safe: No way to enumerate subscribers

### /sync-subscriber (ADMIN ONLY)
- Input: email, key, tier, status
- Output: { success: true }
- ✓ Protected: Requires ADMIN_KEY
- ⚠ Run locally only, don't expose key

### GET /?key=xxx (ADMIN ONLY)
- Output: All submissions
- ✓ Protected: Requires ADMIN_KEY
- ⚠ Don't share this URL

## Before Deploying Code, Ask:
1. What data does this endpoint return?
2. Can someone enumerate users by calling it repeatedly?
3. Is there an auth check if it returns PII?
4. Am I logging anything sensitive?

## Local vs Cloud

| Data | Where to Keep | Why |
|------|---------------|-----|
| Emails JSON export | ~/fortune0-private/ | Your backup, never commit |
| Stripe exports | ~/fortune0-private/ | Your backup, never commit |
| ADMIN_KEY | wrangler secret + your head | Never in code |
| Stripe secret key | stripe CLI login only | Never stored anywhere |

## What NOT to paste in chat/terminals
- API keys (sk_live_xxx, ADMIN_KEY)
- Customer emails in bulk
- Full JSON exports
- Stripe webhook secrets

## Rate Limiting (TODO)
- Could add: max 10 access checks per minute per IP
- Would prevent brute force email enumeration
