#!/bin/bash
# BEAM Subnet 105 - Dual Role Auto-Install Script
# Run as regular user (itlumberjack) with sudo privileges

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
USER="itlumberjack"
USER_HOME="/home/$USER"
VENV_DIR="$USER_HOME/beam-venv"
BEAM_DIR="$USER_HOME/beam"

echo -e "${GREEN}=== BEAM Subnet 105 Dual Role Setup ===${NC}"
echo "Installing as user: $USER"
echo "Home directory: $USER_HOME"
echo ""

# Check we're running as the correct user
if [ "$USER" != "$(whoami)" ]; then
    echo -e "${RED}Please run this script as user '$USER'${NC}"
    echo "Usage: sudo -u $USER bash install_dual_role.sh"
    exit 1
fi

# Check sudo access
if ! sudo -n true 2>/dev/null; then
    echo -e "${RED}User $USER needs passwordless sudo or interactive sudo${NC}"
    exit 1
fi

# Get user input
read -p "GitHub repo URL [https://github.com/taolumberjack/beam.git]: " REPO_URL
REPO_URL=${REPO_URL:-"https://github.com/taolumberjack/beam.git"}

read -p "Wallet name for Orchestrator [taolumberjackBeamOrch]: " ORCH_WALLET
ORCH_WALLET=${ORCH_WALLET:-"taolumberjackBeamOrch"}

read -p "Wallet name for Validator [taoLumberjackBeamVal]: " VAL_WALLET
VAL_WALLET=${VAL_WALLET:-"taoLumberjackBeamVal"}

read -p "Subnet UID [105]: " NETUID
NETUID=${NETUID:-"105"}

echo ""
echo -e "${YELLOW}Installing system dependencies...${NC}"
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

# Clone repo
echo -e "${YELLOW}Cloning repository...${NC}"
cd "$USER_HOME"
if [ -d "beam" ]; then
    echo -e "${YELLOW}Directory exists, pulling latest...${NC}"
    cd beam
    git pull
else
    git clone "$REPO_URL" "$BEAM_DIR"
    cd "$BEAM_DIR"
fi

# Checkout patched branch
echo -e "${YELLOW}Checking out taolumberjack-patches branch...${NC}"
git checkout taolumberjack-patches || git checkout -b taolumberjack-patches

# Install BEAM into the venv
echo -e "${YELLOW}Installing BEAM dependencies...${NC}"
pip install -e .

# Create wallets
echo ""
echo -e "${GREEN}=== Wallet Setup ===${NC}"
echo -e "${YELLOW}Creating orchestrator wallet: $ORCH_WALLET${NC}"
btcli w create --wallet.name "$ORCH_WALLET" --no_prompt || true
btcli w create_hotkey --wallet.name "$ORCH_WALLET" --wallet.hotkey orch1 --no_prompt || true

echo -e "${YELLOW}Creating validator wallet: $VAL_WALLET${NC}"
btcli w create --wallet.name "$VAL_WALLET" --no_prompt || true
btcli w create_hotkey --wallet.name "$VAL_WALLET" --wallet.hotkey val1 --no_prompt || true

# Install systemd services
echo ""
echo -e "${YELLOW}Installing systemd services...${NC}"

# Create service files with correct user
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
    --wallet.name $ORCH_WALLET \
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
    --wallet.name $VAL_WALLET \
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
echo "   - Orchestrator: btcli w balance --wallet.name $ORCH_WALLET"
echo "   - Validator: btcli w balance --wallet.name $VAL_WALLET"
echo ""
echo "2. Register on subnet $NETUID:"
echo "   btcli s register --netuid $NETUID --wallet.name $ORCH_WALLET --wallet.hotkey orch1"
echo "   btcli s register --netuid $NETUID --wallet.name $VAL_WALLET --wallet.hotkey val1"
echo ""
echo "3. Stake ALPHA on orchestrator:"
echo "   btcli s stake --netuid $NETUID --wallet.name $ORCH_WALLET --wallet.hotkey orch1 --amount 10"
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
