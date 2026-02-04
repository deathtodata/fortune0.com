#!/bin/bash
# Sync Stripe subscribers to Cloudflare KV
# Run this after someone subscribes or cancels

WORKER_URL="https://fortune0-forms.mattmauersp.workers.dev"
ADMIN_KEY="${FORTUNE0_ADMIN_KEY}"

if [ -z "$ADMIN_KEY" ]; then
  echo "Set FORTUNE0_ADMIN_KEY environment variable first"
  echo "export FORTUNE0_ADMIN_KEY=your-key-here"
  exit 1
fi

echo "Fetching active Stripe subscriptions..."

# Get active subscribers from Stripe and sync each one
stripe subscriptions list --live --status=active --limit=100 | \
  jq -r '.data[] | .customer' | \
  while read customer_id; do
    # Get customer email
    email=$(stripe customers retrieve "$customer_id" --live | jq -r '.email')

    if [ "$email" != "null" ] && [ -n "$email" ]; then
      echo "Syncing: $email"
      curl -s -X POST "$WORKER_URL" \
        -H "Content-Type: application/json" \
        -d "{\"action\":\"sync-subscriber\",\"email\":\"$email\",\"tier\":\"d2d\",\"status\":\"active\",\"key\":\"$ADMIN_KEY\"}"
      echo ""
    fi
  done

echo "Done!"
