#!/bin/bash
# ═══════════════════════════════════════════════════
#  fortune0 — Cloudflare Tunnel Setup
#  Double-click this file on your Mac to set up
#  a permanent tunnel so your platform API is live
# ═══════════════════════════════════════════════════

cd "$(dirname "$0")"

echo ""
echo "  fortune0 tunnel setup"
echo "  ─────────────────────"
echo ""

# ── Step 1: Check cloudflared ──
if ! command -v cloudflared &> /dev/null; then
    echo "  cloudflared not found. Installing via Homebrew..."
    if command -v brew &> /dev/null; then
        brew install cloudflare/cloudflare/cloudflared
    else
        echo ""
        echo "  ERROR: Homebrew not found either."
        echo "  Install cloudflared manually:"
        echo "    brew install cloudflare/cloudflare/cloudflared"
        echo "  Or: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
        echo ""
        read -p "  Press Enter to close..."
        exit 1
    fi
fi

echo "  cloudflared version: $(cloudflared --version 2>&1 | head -1)"
echo ""

# ── Step 2: Login (if needed) ──
if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
    echo "  You need to login to Cloudflare first."
    echo "  A browser window will open — select the fortune0.com zone."
    echo ""
    cloudflared tunnel login
    echo ""
fi

# ── Step 3: Create named tunnel ──
TUNNEL_NAME="fortune0-platform"

# Check if tunnel already exists
if cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
    echo "  Tunnel '$TUNNEL_NAME' already exists."
    TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}')
else
    echo "  Creating tunnel '$TUNNEL_NAME'..."
    cloudflared tunnel create "$TUNNEL_NAME"
    TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}')
fi

echo "  Tunnel ID: $TUNNEL_ID"
echo ""

# ── Step 4: Create config ──
TUNNEL_CONFIG="$HOME/.cloudflared/config.yml"

if [ -f "$TUNNEL_CONFIG" ]; then
    echo "  Config already exists at $TUNNEL_CONFIG"
    echo "  Backing up to config.yml.bak..."
    cp "$TUNNEL_CONFIG" "$TUNNEL_CONFIG.bak"
fi

cat > "$TUNNEL_CONFIG" << EOF
tunnel: $TUNNEL_ID
credentials-file: $HOME/.cloudflared/${TUNNEL_ID}.json

ingress:
  - hostname: platform.fortune0.com
    service: http://localhost:8080
  - service: http_status:404
EOF

echo "  Config written to $TUNNEL_CONFIG"
echo ""

# ── Step 5: Set up DNS ──
echo "  Setting up DNS: platform.fortune0.com -> tunnel..."
cloudflared tunnel route dns "$TUNNEL_NAME" platform.fortune0.com 2>/dev/null || true
echo ""

# ── Step 6: Install as service (auto-start on boot) ──
echo ""
echo "  ─────────────────────────────────────────"
echo "  Setup complete!"
echo ""
echo "  Your platform will be live at:"
echo "    https://platform.fortune0.com"
echo ""
echo "  To start the tunnel manually:"
echo "    cloudflared tunnel run fortune0-platform"
echo ""
echo "  To install as a system service (starts on boot):"
echo "    sudo cloudflared service install"
echo ""
echo "  To start everything (server + tunnel) at once:"
echo "    Double-click start.command"
echo "  ─────────────────────────────────────────"
echo ""
read -p "  Press Enter to close..."
