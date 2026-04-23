#!/bin/bash
# BEAM Subnet 105 - Worker (Miner) Setup
# Run as itlumberjack user

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

USER="$(whoami)"
USER_HOME="$HOME"
VENV_DIR="$USER_HOME/beam-venv"
BEAM_DIR="$USER_HOME/beam"

# ── Prerequisites ──────────────────────────────────────────────────────────
if [ "$USER" = "root" ]; then
    echo -e "${RED}ERROR: Run as itlumberjack user, NOT root${NC}"
    exit 1
fi

echo -e "${GREEN}=== BEAM Worker (Miner) Setup ===${NC}"
echo "User: $USER"
echo ""

# ── Config ─────────────────────────────────────────────────────────────────
read -p "Subnet UID [105]: " NETUID
NETUID=${NETUID:-"105"}
read -p "Wallet name [taolumberjackBeamWork]: " WALLET_NAME
WALLET_NAME=${WALLET_NAME:-"taolumberjackBeamWork"}
read -p "Hotkey name [work1]: " HOTKEY
HOTKEY=${HOTKEY:-"work1"}

# ── Install deps ───────────────────────────────────────────────────────────
echo -e "${YELLOW}Installing dependencies...${NC}"
sudo apt-get update -qq && sudo apt-get install -y -qq python3-pip python3-venv git curl build-essential htop tmux jq python3-full 2>/dev/null

# ── Create venv ────────────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating venv at $VENV_DIR${NC}"
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
export PATH="$VENV_DIR/bin:$PATH"

# ── Install bittensor ──────────────────────────────────────────────────────
echo -e "${YELLOW}Installing bittensor...${NC}"
pip install --upgrade pip -q
pip install bittensor bittensor-cli -q

# ── Clone/update BEAM repo ─────────────────────────────────────────────────
if [ ! -d "$BEAM_DIR/.git" ]; then
    echo -e "${YELLOW}Cloning BEAM repo...${NC}"
    git clone https://github.com/taolumberjack/beam.git "$BEAM_DIR"
    cd "$BEAM_DIR"
    git checkout taolumberjack-patches 2>/dev/null || true
else
    cd "$BEAM_DIR"
    echo -e "${YELLOW}Pulling latest taolumberjack-patches...${NC}"
    git fetch origin
    git checkout taolumberjack-patches
    git pull origin taolumberjack-patches
fi

pip install -e . -q

# ── Create wallet ──────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=== Wallet Setup ===${NC}"
echo -e "${YELLOW}Creating wallet: $WALLET_NAME${NC}"
$VENV_DIR/bin/btcli w create --wallet.name "$WALLET_NAME" --no_prompt 2>/dev/null || true
$VENV_DIR/bin/btcli w create_hotkey --wallet.name "$WALLET_NAME" --wallet.hotkey "$HOTKEY" --no_prompt 2>/dev/null || true

# ── Install systemd service ────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Installing systemd service...${NC}"
sudo tee /etc/systemd/system/beam-work.service > /dev/null << EOF
[Unit]
Description=BEAM Subnet 105 Worker
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BEAM_DIR
Environment=PYTHONPATH=$BEAM_DIR
Environment=PATH=$VENV_DIR/bin
Environment=SUBNET_CORE_URL=https://beamcore.b1m.ai
ExecStart=$VENV_DIR/bin/python neurons/worker/worker.py \\
    --wallet.name $WALLET_NAME \\
    --wallet.hotkey $HOTKEY \\
    --netuid $NETUID \\
    --subtensor.network finney \\
    --logging.debug
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable beam-work

# ── Finish ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=== Worker Setup Complete ===${NC}"
echo ""
echo "Wallet: $WALLET_NAME / $HOTKEY"
echo "Subnet: $NETUID"
echo ""
echo "NEXT STEPS:"
echo "  1. Fund coldkey (~0.057 TAO for registration fee)"
echo "  2. Register on subnet $NETUID:"
echo "       btcli s register --netuid $NETUID --wallet.name $WALLET_NAME --wallet.hotkey $HOTKEY"
echo "  3. Start worker:"
echo "       sudo systemctl start beam-work"
echo "  4. Watch logs:"
echo "       sudo journalctl -u beam-work -f"
