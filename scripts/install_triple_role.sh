#!/bin/bash
# BEAM Subnet 105 - Triple Role Setup (Worker + Orchestrator + Validator)
# Run as itlumberjack user

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

USER="$(whoami)"
USER_HOME="$HOME"
VENV_DIR="$USER_HOME/beam-venv"
BEAM_DIR="$USER_HOME/beam"

echo -e "${GREEN}=== BEAM Subnet 105 Triple Role Setup ===${NC}"
echo "User: $USER"
echo ""

read -p "Subnet UID [105]: " NETUID
NETUID=${NETUID:-"105"}

# Install deps
echo -e "${YELLOW}Installing dependencies...${NC}"
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git curl build-essential htop tmux jq python3-full

# Create venv
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
export PATH="$VENV_DIR/bin:$PATH"

# Install packages
pip install --upgrade pip
pip install bittensor bittensor-cli

# Install BEAM
cd "$BEAM_DIR"
pip install -e .

# Create all wallets + hotkeys
echo ""
echo -e "${GREEN}=== Creating Wallets ===${NC}"

for wallet in taolumberjackBeamWork taolumberjackBeamOrch taoLumberjackBeamVal; do
    echo -e "${YELLOW}Creating $wallet${NC}"
    $VENV_DIR/bin/btcli w create --wallet.name "$wallet" --no_prompt || true
    
    # Determine hotkey name
    if [ "$wallet" = "taolumberjackBeamWork" ]; then
        hotkey="work1"
    elif [ "$wallet" = "taolumberjackBeamOrch" ]; then
        hotkey="orch1"
    else
        hotkey="val1"
    fi
    
    $VENV_DIR/bin/btcli w create_hotkey --wallet.name "$wallet" --wallet.hotkey "$hotkey" --no_prompt || true
done

# Install all 3 systemd services
echo ""
echo -e "${YELLOW}Installing systemd services...${NC}"

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
ExecStart=$VENV_DIR/bin/python neurons/worker/worker.py \
    --wallet.name taolumberjackBeamWork \
    --wallet.hotkey work1 \
    --netuid $NETUID \
    --subtensor.network finney
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

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
    --subtensor.network finney
Restart=always
RestartSec=10

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
    --wallet.hotkey va1 \
    --netuid $NETUID \
    --subtensor.network finney
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

# Create .env
cat > "$BEAM_DIR/.env" << EOF
NETUID=$NETUID
SUBTENSOR_NETWORK=finney
SUBTENSOR_CHAIN_ENDPOINT=wss://entrypoint-finney.opentensor.ai:443
ALPHA_PER_CHUNK=0.5
MIN_PAYMENT_THRESHOLD=0.0005
EOF

sudo chown -R $USER:$USER "$BEAM_DIR"

echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "Wallets:"
$VENV_DIR/bin/btcli w list
echo ""
echo "Next:"
echo "1. Fund wallets (~0.17 TAO total)"
echo "2. Register all 3 on subnet $NETUID"
echo "3. Stake ALPHA on orchestrator"
echo "4. Start: sudo systemctl start beam-work beam-orch beam-val"
