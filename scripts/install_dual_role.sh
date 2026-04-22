#!/bin/bash
# BEAM Subnet 105 - Dual Role Auto-Install Script
# Run as itlumberjack user (will prompt for sudo password when needed)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
USER="$(whoami)"
USER_HOME="$HOME"
VENV_DIR="$USER_HOME/beam-venv"
BEAM_DIR="$USER_HOME/beam"

echo -e "${GREEN}=== BEAM Subnet 105 Dual Role Setup ===${NC}"
echo "Installing as user: $USER"
echo "Home directory: $USER_HOME"
echo ""

# Get user input
read -p "Subnet UID [105]: " NETUID
NETUID=${NETUID:-"105"}

echo ""
echo -e "${YELLOW}Installing system dependencies (may prompt for sudo password)...${NC}"
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git curl build-essential htop tmux jq python3-full

# Create virtual environment
echo -e "${YELLOW}Creating Python virtual environment...${NC}"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Install Bittensor CLI into venv
echo -e "${YELLOW}Installing Bittensor CLI...${NC}"
pip install --upgrade pip
pip install bittensor

# Install BEAM dependencies
echo -e "${YELLOW}Installing BEAM dependencies...${NC}"
cd "$BEAM_DIR"
pip install -e .

# Create wallets
echo ""
echo -e "${GREEN}=== Wallet Setup ===${NC}"
echo -e "${YELLOW}Creating orchestrator wallet: taolumberjackBeamOrch${NC}"
btcli w create --wallet.name taolumberjackBeamOrch --no_prompt || true
btcli w create_hotkey --wallet.name taolumberjackBeamOrch --wallet.hotkey orch1 --no_prompt || true

echo -e "${YELLOW}Creating validator wallet: taoLumberjackBeamVal${NC}"
btcli w create --wallet.name taoLumberjackBeamVal --no_prompt || true
btcli w create_hotkey --wallet.name taoLumberjackBeamVal --wallet.hotkey val1 --no_prompt || true

# Install systemd services
echo ""
echo -e "${YELLOW}Installing systemd services (may prompt for sudo password)...${NC}"

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
ExecStart=$VENV_DIR/bin/python neurons/orchestrator/orchestrator.py \
    --wallet.name taolumberjackBeamOrch \
    --wallet.hotkey orch1 \
    --netuid $NETUID \
    --subtensor.network finney \
    --logging.debug
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/beam-val.service > /dev/null << EOF
[Unit]
Description=BEAM Subnet 105 Validator
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BEAM_DIR
Environment=PYTHONPATH=$BEAM_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/python neurons/validator/core/validator.py \
    --wallet.name taoLumberjackBeamVal \
    --wallet.hotkey val1 \
    --netuid $NETUID \
    --subtensor.network finney \
    --logging.debug
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

# Create .env file
cat > "$BEAM_DIR/.env" << EOF
# BEAM Subnet $NETUID Configuration
SUBTENSOR_NETWORK=finney
SUBTENSOR_CHAIN_ENDPOINT=wss://entrypoint-finney.opentensor.ai:443
NETUID=$NETUID

# Orchestrator
ALPHA_PER_CHUNK=0.5
MIN_PAYMENT_THRESHOLD=0.0005

# Validator
VALIDATION_INTERVAL=300
WEIGHT_SET_INTERVAL=3600
EOF

# Set ownership
sudo chown -R $USER:$USER "$BEAM_DIR"

echo ""
echo -e "${GREEN}=== Installation Complete ===${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Fund your wallets with TAO for registration fees"
echo "   btcli w balance --wallet.name taolumberjackBeamOrch"
echo "   btcli w balance --wallet.name taoLumberjackBeamVal"
echo ""
echo "2. Register on subnet $NETUID:"
echo "   btcli s register --netuid $NETUID --wallet.name taolumberjackBeamOrch --wallet.hotkey orch1"
echo "   btcli s register --netuid $NETUID --wallet.name taoLumberjackBeamVal --wallet.hotkey val1"
echo ""
echo "3. Stake ALPHA on orchestrator:"
echo "   btcli s stake --netuid $NETUID --wallet.name taolumberjackBeamOrch --wallet.hotkey orch1 --amount 10"
echo ""
echo "4. Start services:"
echo "   sudo systemctl start beam-orch beam-val"
echo "   sudo systemctl enable beam-orch beam-val"
echo ""
echo -e "${GREEN}Wallet addresses:${NC}"
btcli w list

echo ""
echo -e "${YELLOW}Log locations:${NC}"
echo "   Orchestrator: sudo journalctl -u beam-orch -f"
echo "   Validator:    sudo journalctl -u beam-val -f"
echo ""
echo -e "${GREEN}Done!${NC}"
