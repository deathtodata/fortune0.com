# fortune0 Operations Calendar

## Daily (5 min)
- [ ] Check Stripe dashboard for new subscribers
- [ ] Glance at worker logs: `wrangler tail` (optional)

## Weekly (Sunday, 15 min)
- [ ] Sync Stripe subscribers to KV:
  ```bash
  cd ~/desktop/fortune0.com/_build
  export FORTUNE0_ADMIN_KEY=your-key
  ./sync-subscribers.sh
  ```
- [ ] Export emails locally:
  ```bash
  curl "https://fortune0-forms.mattmauersp.workers.dev?key=$FORTUNE0_ADMIN_KEY" \
    > ~/desktop/fortune0-private/emails-$(date +%Y-%m-%d).json
  ```
- [ ] Export Stripe data:
  ```bash
  stripe subscriptions list --live > ~/desktop/fortune0-private/subs-$(date +%Y-%m-%d).json
  stripe customers list --live > ~/desktop/fortune0-private/customers-$(date +%Y-%m-%d).json
  ```
- [ ] Git commit any changes:
  ```bash
  cd ~/desktop/fortune0.com && git add -A && git status
  ```

## Monthly (1st of month, 30 min)
- [ ] Review subscriber count vs last month
- [ ] Check domain expiration dates in domains.json
- [ ] Renew any domains expiring in next 60 days
- [ ] Review which domains have most signups (from exports)
- [ ] Write newsletter update (optional)
- [ ] Backup fortune0-private folder to external drive

## Quarterly
- [ ] Review Stripe fees vs revenue
- [ ] Consider which domains to let expire vs keep
- [ ] Update PRODUCT-FLOW.md if strategy changed

---

## Automation Ideas (Future)

### Cron job for weekly sync
```bash
# Add to crontab: crontab -e
0 9 * * 0 cd ~/desktop/fortune0.com/_build && ./sync-subscribers.sh
```

### Launchd for Mac (runs even when terminal closed)
```xml
<!-- ~/Library/LaunchAgents/com.fortune0.sync.plist -->
<!-- Runs every Sunday at 9am -->
```

### Make it one command
```bash
# ~/desktop/fortune0.com/_build/weekly-ops.sh
#!/bin/bash
export FORTUNE0_ADMIN_KEY="your-key"
./sync-subscribers.sh
curl "https://fortune0-forms.mattmauersp.workers.dev?key=$FORTUNE0_ADMIN_KEY" \
  > ~/desktop/fortune0-private/emails-$(date +%Y-%m-%d).json
stripe subscriptions list --live > ~/desktop/fortune0-private/subs-$(date +%Y-%m-%d).json
echo "Weekly ops complete: $(date)"
```

---

## Emergency Procedures

### Someone's access not working
1. Check if they're in Stripe (active subscription?)
2. Run sync script
3. Test: `curl -X POST ... '{"action":"check-access","email":"their@email.com"}'`

### Key leaked
1. Rotate immediately:
   ```bash
   wrangler secret delete ADMIN_KEY
   wrangler secret put ADMIN_KEY
   ```
2. Update your local export scripts with new key
3. Stripe key: Dashboard → API Keys → Roll key

### Site down
1. Check GitHub Pages status
2. Check Cloudflare status
3. Worker: `wrangler tail` for errors

---

## Trust Nobody Mode

All customer data stays in:
- Stripe (they need it for payments)
- Your KV (encrypted, you control)
- Your laptop exports (~/fortune0-private/)

Nobody else has access. No employees, no contractors, no shared dashboards.
To share stats without sharing data → use the get-stats endpoint (counts only).
