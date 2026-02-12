#!/bin/bash
# ═══════════════════════════════════════════
#  fortune0 — double-click this to launch
# ═══════════════════════════════════════════

cd "$(dirname "$0")"

echo ""
echo "  Starting fortune0..."
echo ""

# Check for Python
if command -v python3 &> /dev/null; then
    PY=python3
elif command -v python &> /dev/null; then
    PY=python
else
    echo "  ERROR: Python not found."
    echo "  Install it from https://python.org"
    echo ""
    read -p "  Press Enter to close..."
    exit 1
fi

# Pick a port
PORT=${F0_PORT:-8080}

# Start Cloudflare Tunnel in background (if configured)
TUNNEL_PID=""
if command -v cloudflared &> /dev/null && [ -f "$HOME/.cloudflared/config.yml" ]; then
    echo "  Starting Cloudflare Tunnel..."
    cloudflared tunnel run fortune0-platform &>/dev/null &
    TUNNEL_PID=$!
    echo "  Tunnel: https://platform.fortune0.com"
else
    echo "  No tunnel configured (local only)"
    echo "  Run tunnel-setup.command to make it public"
fi

# Open browser after a short delay
(sleep 2 && open "http://localhost:$PORT") &

echo "  Server: http://localhost:$PORT"
echo "  Press Ctrl+C to stop"
echo ""

# Cleanup tunnel on exit
cleanup() {
    if [ -n "$TUNNEL_PID" ]; then
        kill $TUNNEL_PID 2>/dev/null
    fi
    exit 0
}
trap cleanup INT TERM

F0_PORT=$PORT $PY server.py
