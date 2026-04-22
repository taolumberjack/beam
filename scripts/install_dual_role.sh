#!/bin/bash
# BEAM Subnet 105 - Dual Role Auto-Install Script
# Run as root on fresh Ubuntu 22.04 VPS

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== BEAM Subnet 105 Dual Role Setup ===${NC}"
echo "This will install both Orchestrator and Validator"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root${NC}"
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
apt update && apt upgrade -y
apt install -y python3-pip python3-venv git curl build-essential htop tmux jq

# Install Bittensor CLI
echo -e "${YELLOW}Installing Bittensor CLI...${NC}"
pip install bittensor

# Clone repo
echo -e "${YELLOW}Cloning repository...${NC}"
cd /root
if [ -d "beam" ]; then
    echo -e "${YELLOW}Directory exists, pulling latest...${NC}"
    cd beam
    git pull
else
    git clone "$REPO_URL"
    cd beam
fi

# Checkout patched branch
echo -e "${YELLOW}Checking out taolumberjack-patches branch...${NC}"
git checkout taolumberjack-patches || git checkout -b taolumberjack-patches

# Create virtual environment
echo -e "${YELLOW}Setting up Python environment...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
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
cp scripts/beam-orch.service /etc/systemd/system/
cp scripts/beam-val.service /etc/systemd/system/

# Update service files with wallet names
sed -i "s/taolumberjackBeamOrch/$ORCH_WALLET/g" /etc/systemd/system/beam-orch.service
sed -i "s/taoLumberjackBeamVal/$VAL_WALLET/g" /etc/systemd/system/beam-val.service
sed -i "s/--netuid 105/--netuid $NETUID/g" /etc/systemd/system/beam-*.service

systemctl daemon-reload

# Create .env file
cat > /root/beam/.env << EOF
# BEAM Subnet 105 Configuration
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
echo "   systemctl start beam-orch beam-val"
echo "   systemctl enable beam-orch beam-val"
echo ""
echo -e "${GREEN}Wallet addresses:${NC}"
btcli w list

echo ""
echo -e "${YELLOW}Log locations:${NC}"
echo "   Orchestrator: journalctl -u beam-orch -f"
echo "   Validator:    journalctl -u beam-val -f"
echo ""
echo -e "${GREEN}Done!${NC}"
