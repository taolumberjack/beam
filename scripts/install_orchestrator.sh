#!/bin/bash
# BEAM Subnet 105 - Orchestrator Setup
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

echo -e "${GREEN}=== BEAM Orchestrator Setup ===${NC}"
echo "User: $USER"
echo ""

# ── Config ─────────────────────────────────────────────────────────────────
read -p "Subnet UID [105]: " NETUID
NETUID=${NETUID:-"105"}
read -p "Wallet name [taolumberjackBeamOrch]: " WALLET_NAME
WALLET_NAME=${WALLET_NAME:-"taolumberjackBeamOrch"}
read -p "Hotkey name [orch1]: " HOTKEY
HOTKEY=${HOTKEY:-"orch1"}

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

# ── Create .env for orchestrator ──────────────────────────────────────────
echo -e "${YELLOW}Creating orchestrator .env...${NC}"
cat > "$BEAM_DIR/.env.orch" << EOF
NETUID=$NETUID
SUBTENSOR_NETWORK=finney
SUBTENSOR_CHAIN_ENDPOINT=wss://entrypoint-finney.opentensor.ai:443
SUBNET_CORE_URL=https://beamcore.b1m.ai
ALPHA_PER_CHUNK=0.5
MIN_PAYMENT_THRESHOLD=0.0005
EOF

# ── Install systemd service ────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Installing systemd service...${NC}"
sudo tee /etc/systemd/system/beam-orch.service > /dev/null << EOF
[Unit]
Description=BEAM Subnet 105 Orchestrator
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BEAM_DIR
Environment=PYTHONPATH=$BEAM_DIR
Environment=PATH=$VENV_DIR/bin
Environment=SUBNET_CORE_URL=https://beamcore.b1m.ai
Environment=WALLET_NAME=$WALLET_NAME
Environment=WALLET_HOTKEY=$HOTKEY
ExecStart=$VENV_DIR/bin/python neurons/orchestrator/main.py \\
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
sudo systemctl enable beam-orch

# ── Finish ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=== Orchestrator Setup Complete ===${NC}"
echo ""
echo "Wallet: $WALLET_NAME / $HOTKEY"
echo "Subnet: $NETUID"
echo "SubnetCore: https://beamcore.b1m.ai"
echo ""
echo "NEXT STEPS:"
echo "  1. Fund coldkey (~0.057 TAO for registration fee)"
echo "  2. Register on subnet $NETUID:"
echo "       btcli s register --netuid $NETUID --wallet.name $WALLET_NAME --wallet.hotkey $HOTKEY"
echo "  3. Stake ALPHA on hotkey so orchestrator can pay workers:"
echo "       btcli stake add --wallet.name $WALLET_NAME --wallet.hotkey $HOTKEY --amount 10"
echo "  4. Start orchestrator:"
echo "       sudo systemctl start beam-orch"
echo "  5. Watch logs:"
echo "       sudo journalctl -u beam-orch -f"
echo ""
echo "IMPORTANT:"
echo "  - Orchestrator reads wallet from WALLET_NAME/WALLET_HOTKEY env vars"
echo "  - Must have ALPHA staked to pay workers"
echo "  - Connects to SubnetCore at https://beamcore.b1m.ai"
