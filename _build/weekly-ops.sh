#!/bin/bash
# Weekly ops script - run every Sunday or whenever
# Usage: ./weekly-ops.sh

set -e

PRIVATE_DIR="$HOME/desktop/fortune0-private"
DATE=$(date +%Y-%m-%d)
WORKER_URL="https://fortune0-forms.mattmauersp.workers.dev"

# Check for admin key
if [ -z "$FORTUNE0_ADMIN_KEY" ]; then
  echo "❌ Set FORTUNE0_ADMIN_KEY first:"
  echo "   export FORTUNE0_ADMIN_KEY=your-key"
  exit 1
fi

echo "🔄 fortune0 weekly ops - $DATE"
echo "================================"

# 1. Sync Stripe subscribers
echo ""
echo "1️⃣ Syncing Stripe subscribers..."
./sync-subscribers.sh

# 2. Export email signups
echo ""
echo "2️⃣ Exporting email signups..."
curl -s "$WORKER_URL?key=$FORTUNE0_ADMIN_KEY" > "$PRIVATE_DIR/emails-$DATE.json"
echo "   Saved to $PRIVATE_DIR/emails-$DATE.json"

# 3. Export Stripe data
echo ""
echo "3️⃣ Exporting Stripe subscriptions..."
stripe subscriptions list --live > "$PRIVATE_DIR/subs-$DATE.json"
echo "   Saved to $PRIVATE_DIR/subs-$DATE.json"

echo ""
echo "4️⃣ Exporting Stripe customers..."
stripe customers list --live > "$PRIVATE_DIR/customers-$DATE.json"
echo "   Saved to $PRIVATE_DIR/customers-$DATE.json"

# 4. Show summary
echo ""
echo "================================"
echo "✅ Weekly ops complete!"
echo ""
echo "📊 Quick stats:"
curl -s -X POST "$WORKER_URL" \
  -H "Content-Type: application/json" \
  -d '{"action":"get-stats"}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"   Signups: {d['totalSignups']}\")
print(f\"   Subscribers: {d['totalSubscribers']}\")
print(f\"   Domains: {len(d['domainCounts'])}\")
"

echo ""
echo "📁 Exports saved to: $PRIVATE_DIR"
ls -la "$PRIVATE_DIR"/*.json 2>/dev/null | tail -5
