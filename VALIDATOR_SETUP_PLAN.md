# BEAM Subnet 105 — Validator Setup Plan (taoLumberjack)

## Your Context
- **Current**: Validating SN67 on Vultr VPS (216.128.153.39)
- **Naming**: taoLumberjack theme
- **Existing wallet**: `lumberjackVal1` / `lumberjackVal1hot`
- **Target**: SN105 (mainnet) or SN304 (testnet)

---

## Phase 1: Infrastructure & Wallet Prep

### Step 1.1 — Server Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 16 GB | 32 GB |
| Storage | 100 GB SSD | 200 GB NVMe |
| Network | 100 Mbps | 1 Gbps |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |

**Recommendation**: Use your existing Vultr VPS if it meets specs, or spin up a second instance. Validator needs to be online 24/7.

### Step 1.2 — Server Naming (taoLumberjack Theme)

```bash
# On your VPS
sudo hostnamectl set-hostname beamLumberjack-val

# Add to /etc/hosts
echo "127.0.1.1 beamLumberjack-val" | sudo tee -a /etc/hosts
```

### Step 1.3 — System Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3-pip python3-venv python3-dev git curl wget \
    build-essential libssl-dev pkg-config tmux htop net-tools

# Install Rust (required by some bittensor deps)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# Verify Python 3.10+
python3 --version  # Should be >= 3.10

# Create workspace directory
mkdir -p ~/beam-sn105 && cd ~/beam-sn105
```

### Step 1.4 — Bittensor Wallet Setup

You already have `lumberjackVal1` — we'll reuse it. If you want a fresh validator wallet:

```bash
# Option A: Reuse existing wallet
btcli wallet list
# Should show lumberjackVal1 with lumberjackVal1hot

# Option B: Create new validator wallet (if preferred)
btcli wallet create --wallet.name lumberjackVal1 --wallet.hotkey lumberjackVal105hot
```

**Get your wallet address:**
```bash
btcli wallet overview --wallet.name lumberjackVal1
# Note the SS58 address of lumberjackVal1hot
```

### Step 1.5 — Check Registration Status

```bash
# Check if you're already registered on SN105
btcli subnet metagraph --netuid 105 --network finney | grep lumberjackVal1hot

# Check if registered on testnet (SN304)
btcli subnet metagraph --netuid 304 --network test | grep lumberjackVal1hot
```

If **NOT registered**, proceed to Phase 2.

---

## Phase 2: Subnet Registration

### Step 2.1 — Get TAO for Registration

Validators need **minimum 100 TAO** stake (recommended: 500+ for competitive position).

```bash
# Check your balance
btcli wallet balance --wallet.name lumberjackVal1

# If you need to transfer TAO to this wallet
btcli wallet transfer --wallet.name your_source_wallet --destination <lumberjackVal1_coldkey_ss58>
```

### Step 2.2 — Register on Subnet

```bash
# Register on mainnet SN105
btcli subnet register \
    --wallet.name lumberjackVal1 \
    --wallet.hotkey lumberjackVal1hot \
    --netuid 105 \
    --network finney

# OR register on testnet SN304 first (RECOMMENDED for testing)
btcli subnet register \
    --wallet.name lumberjackVal1 \
    --wallet.hotkey lumberjackVal1hot \
    --netuid 304 \
    --network test
```

**Registration cost**: Varies based on network demand. Check current cost:
```bash
btcli subnet list --network finney  # Look at SN105 Recycle column
```

### Step 2.3 — Add Stake

```bash
# Stake TAO to your hotkey on SN105
btcli stake add \
    --wallet.name lumberjackVal1 \
    --wallet.hotkey lumberjackVal1hot \
    --netuid 105 \
    --amount 500 \
    --network finney
```

**Why stake matters**: Higher stake = higher trust in the network = your weights have more influence.

### Step 2.4 — Verify Registration

```bash
# Get your UID
btcli subnet metagraph --netuid 105 --network finney | grep lumberjackVal1hot

# Should output something like:
# | 42 | lumberjackVal1hot... | 500.0 | ... |
# Your UID is 42
```

**Write down your UID** — you'll need it in config.

---

## Phase 3: Install BEAM Validator Software

### Step 3.1 — Clone the Repo

```bash
cd ~/beam-sn105
git clone https://github.com/Beam-Network/beam.git
cd beam
```

### Step 3.2 — Create Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel
```

### Step 3.3 — Install Dependencies

```bash
# Install bittensor first
pip install bittensor>=8.0.0

# Install remaining dependencies
pip install fastapi uvicorn sqlalchemy asyncpg alembic aiohttp websockets \
    redis pynacl cryptography pydantic pydantic-settings pyyaml httpx \
    python-multipart torch numpy

# OR use requirements if provided
pip install -r requirements.txt  # If repo has one
```

### Step 3.4 — Verify Installation

```bash
python3 -c "import bittensor; print(bittensor.__version__)"
python3 -c "import torch; print(torch.__version__)"
```

---

## Phase 4: Validator Configuration

### Step 4.1 — Create Environment File

```bash
cd ~/beam-sn105/beam
nano .env
```

Paste this config (adjust values):

```env
# ========================================
# BEAM Validator Config (taoLumberjack)
# ========================================

# --- Bittensor ---
BEAM_NETUID=105
BEAM_SUBTENSOR_NETWORK=finney
# BEAM_SUBTENSOR_ADDRESS=wss://entrypoint-finney.opentensor.ai:443

# --- Wallet ---
BEAM_VALIDATOR_WALLET_NAME=lumberjackVal1
BEAM_VALIDATOR_WALLET_HOTKEY=lumberjackVal1hot

# --- Network ---
BEAM_VALIDATOR_EXTERNAL_IP=216.128.153.39
BEAM_VALIDATOR_EXTERNAL_URL=https://beamLumberjack-val.yourdomain.com  # Optional
BEAM_VALIDATOR_PORT=8093

# --- Validation ---
BEAM_VALIDATOR_TASK_INTERVAL_SECONDS=12
BEAM_VALIDATOR_TASKS_PER_EPOCH=10
BEAM_VALIDATOR_CHUNK_SIZE_BYTES=10485760

# --- PoB Verification ---
BEAM_VALIDATOR_MAX_CLOCK_DRIFT_US=5000000
BEAM_VALIDATOR_MIN_TRANSFER_TIME_US=50000
BEAM_VALIDATOR_MIN_BANDWIDTH_MBPS=50.0
BEAM_VALIDATOR_MAX_BANDWIDTH_MBPS=10000.0

# --- Weight Setting ---
BEAM_VALIDATOR_BLOCKS_BETWEEN_WEIGHTS=100
BEAM_VALIDATOR_WEIGHT_ALPHA=0.3
BEAM_VALIDATOR_MIN_CONNECTION_STAKE=10.0

# --- Scoring Weights ---
BEAM_VALIDATOR_SCORE_WEIGHT_BANDWIDTH=0.50
BEAM_VALIDATOR_SCORE_WEIGHT_UPTIME=0.20
BEAM_VALIDATOR_SCORE_WEIGHT_LOSS=0.15
BEAM_VALIDATOR_SCORE_WEIGHT_TIER=0.15

# --- BeamCore API ---
BEAM_VALIDATOR_SUBNET_CORE_URL=https://beamcore.b1m.ai
# For testnet: https://beamcore-dev.b1m.ai

# --- Payment Proof Verification ---
BEAM_VALIDATOR_MISSING_PROOF_PENALTY=0.5
BEAM_VALIDATOR_INVALID_PROOF_PENALTY=0.3
BEAM_VALIDATOR_PROOF_LOOKBACK_EPOCHS=10

# --- Redis (optional, for caching) ---
BEAM_VALIDATOR_REDIS_HOST=localhost
BEAM_VALIDATOR_REDIS_PORT=6379
BEAM_VALIDATOR_REDIS_DB=1

# --- Sync & Timing ---
BEAM_VALIDATOR_SYNC_INTERVAL=12
BEAM_VALIDATOR_JOB_TIMEOUT_SECONDS=60

# --- Logging ---
BEAM_VALIDATOR_LOG_LEVEL=INFO
BEAM_VALIDATOR_DEBUG=false
```

### Step 4.2 — Configure Firewall

```bash
# Allow validator API port
sudo ufw allow 8093/tcp

# Allow SSH (don't lock yourself out!)
sudo ufw allow 22/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

### Step 4.3 — Set Up Redis (Optional but Recommended)

```bash
# Install Redis
sudo apt install -y redis-server

# Configure Redis
sudo nano /etc/redis/redis.conf
# Set: maxmemory 256mb
# Set: maxmemory-policy allkeys-lru

# Start Redis
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Verify
redis-cli ping  # Should return PONG
```

---

## Phase 5: Run the Validator

### Step 5.1 — First Run (Manual, in tmux)

```bash
cd ~/beam-sn105/beam
source venv/bin/activate

cd neurons/validator

# Run main validator
python3 main.py
```

**What to watch for:**
- `Initializing Validator node...`
- `Connected to subtensor: finney`
- `Registered on subnet 105 with UID <your_uid>`
- `Fiber chain initialized with X nodes`
- `Validator node started`

If you see errors, check:
1. Wallet exists and is registered
2. Subtensor connection is working
3. Dependencies are installed

### Step 5.2 — Create Systemd Service (Production)

```bash
sudo nano /etc/systemd/system/beam-validator.service
```

```ini
[Unit]
Description=BEAM SN105 Validator (taoLumberjack)
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=itLumberjack
WorkingDirectory=/home/itLumberjack/beam-sn105/beam/neurons/validator
Environment="PATH=/home/itLumberjack/beam-sn105/beam/venv/bin"
Environment="PYTHONPATH=/home/itLumberjack/beam-sn105/beam"
Environment="BEAM_NETUID=105"
Environment="BEAM_SUBTENSOR_NETWORK=finney"
ExecStart=/home/itLumberjack/beam-sn105/beam/venv/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=beam-validator

[Install]
WantedBy=multi-user.target
```

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable beam-validator

# Start service
sudo systemctl start beam-validator

# Check logs
sudo journalctl -u beam-validator -f
```

---

## Phase 6: Validator Operations

### Step 6.1 — Monitor Health

```bash
# Watch validator logs
sudo journalctl -u beam-validator -f

# Check validator status
curl http://localhost:8093/health  # If health endpoint exists

# Check metagraph position
btcli subnet metagraph --netuid 105 --network finney | grep lumberjackVal1hot
```

### Step 6.2 — Verify Weight Setting

```bash
# Check when weights were last set
btcli subnet metagraph --netuid 105 --network finney
# Look at the "last_update" column for your UID

# Check your validator's weights on-chain
btcli weights show --netuid 105 --network finney --uid <your_uid>
```

### Step 6.3 — Monitor Earnings

```bash
# Check validator emission
btcli wallet inspect --wallet.name lumberjackVal1 --wallet.hotkey lumberjackVal1hot --netuid 105

# Check total stake over time
btcli stake show --wallet.name lumberjackVal1 --netuid 105
```

---

## Phase 7: Maintenance & Troubleshooting

### Common Issues from Chat Logs

| Issue | Cause | Fix |
|-------|-------|-----|
| `HTTP 403` on WebSocket | Invalid/expired API key | Re-register worker, clear cache |
| `502 Bad Gateway` | BeamCore overloaded | Add retry with exponential backoff |
| `tx_hash is NULL` | Payment not submitted on-chain | Fix payment flow in orchestrator |
| `Compliance < 0.5` | Unpaid workers | Ensure all workers paid within epoch |
| `Weights mismatch` | Formula params_hash mismatch | Update to latest validator code |

### Update Procedure

```bash
cd ~/beam-sn105/beam
git fetch origin
git pull origin main

# Restart service
sudo systemctl restart beam-validator

# Verify it's running
sudo systemctl status beam-validator
```

### Backup Your Wallets

```bash
# Backup wallet directory
mkdir -p ~/backups
tar -czf ~/backups/wallets-$(date +%Y%m%d).tar.gz ~/.bittensor/wallets

# Store backup securely (off-server)
```

---

## Phase 8: Testnet First (Recommended)

Before going live on mainnet, test everything on SN304:

```bash
# Change .env to testnet
sed -i 's/BEAM_NETUID=105/BEAM_NETUID=304/' .env
sed -i 's/BEAM_SUBTENSOR_NETWORK=finney/BEAM_SUBTENSOR_NETWORK=test/' .env
sed -i 's|BEAM_VALIDATOR_SUBNET_CORE_URL=https://beamcore.b1m.ai|BEAM_VALIDATOR_SUBNET_CORE_URL=https://beamcore-dev.b1m.ai|' .env

# Restart
sudo systemctl restart beam-validator

# Watch logs
sudo journalctl -u beam-validator -f
```

Run on testnet for **48-72 hours** to verify:
- ✅ Validator starts without errors
- ✅ Connects to BeamCore
- ✅ Fetches and verifies proofs
- ✅ Sets weights on-chain
- ✅ No memory leaks or crashes

Then switch to mainnet.

---

## Cost Breakdown

| Item | Cost Estimate |
|------|---------------|
| Vultr VPS (8 vCPU, 32GB) | ~$96/month |
| TAO Registration (SN105) | ~1-5 TAO (varies) |
| Minimum Stake | 100+ TAO |
| Competitive Stake | 500+ TAO |
| Total Initial Investment | ~105-600 TAO + server |

---

## Quick Reference Commands

```bash
# Start validator
sudo systemctl start beam-validator

# Stop validator
sudo systemctl stop beam-validator

# View logs
sudo journalctl -u beam-validator -f

# Check status
sudo systemctl status beam-validator

# Restart
sudo systemctl restart beam-validator

# Update code
cd ~/beam-sn105/beam && git pull && sudo systemctl restart beam-validator

# Check metagraph
btcli subnet metagraph --netuid 105 --network finney

# Check balance
btcli wallet balance --wallet.name lumberjackVal1

# Check validator emissions
btcli wallet inspect --wallet.name lumberjackVal1 --wallet.hotkey lumberjackVal1hot --netuid 105
```

---

*Plan version: 2026-04-21 | For BEAM SN105 | taoLumberjack*
