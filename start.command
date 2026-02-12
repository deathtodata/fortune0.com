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

# Open browser after a short delay
(sleep 2 && open "http://localhost:$PORT") &

echo "  Server: http://localhost:$PORT"
echo "  Press Ctrl+C to stop"
echo ""

F0_PORT=$PORT $PY server.py
