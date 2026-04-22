# BEAM Subnet 105 — Orchestrator (Miner) Setup Plan (taoLumberjack)

## Your Context
- **Current**: Validating SN67 on Vultr VPS (216.128.153.39)
- **Naming**: taoLumberjack theme
- **Existing wallet**: `lumberjackVal1` / `lumberjackVal1hot`
- **Target**: SN105 (mainnet) or SN304 (testnet)
- **Note**: Orchestrator = "miner" in Bittensor terminology

---

## Phase 1: Infrastructure

### Step 1.1 — Server Requirements (Orchestrator)

Orchestrators need MORE resources than validators because they coordinate workers and handle data transfers.

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 8 cores | 16+ cores |
| RAM | 32 GB | 64 GB |
| Storage | 200 GB SSD | 500 GB NVMe |
| Network | 1 Gbps | 10 Gbps |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| Public IP | Required | Static IP preferred |

**Recommendation**: Separate server from validator. Orchestrator is bandwidth-heavy.

### Step 1.2 — Server Naming

```bash
# On your orchestrator server
sudo hostnamectl set-hostname beamLumberjack-orch

echo "127.0.1.1 beamLumberjack-orch" | sudo tee -a /etc/hosts
```

### Step 1.3 — System Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3-pip python3-venv python3-dev git curl wget \
    build-essential libssl-dev pkg-config tmux htop net-tools nginx

# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# Create workspace
mkdir -p ~/beam-orch && cd ~/beam-orch
```

---

## Phase 2: Wallet Setup

### Step 2.1 — Create Orchestrator Wallet

Use a SEPARATE wallet from your validator for security.

```bash
# Create orchestrator wallet
btcli wallet create --wallet.name lumberjackOrch1 --wallet.hotkey lumberjackOrch1hot

# Get wallet address
btcli wallet overview --wallet.name lumberjackOrch1
```

### Step 2.2 — Fund the Wallet

```bash
# Check balance
btcli wallet balance --wallet.name lumberjackOrch1

# Transfer TAO from another wallet if needed
btcli wallet transfer \
    --wallet.name your_source_wallet \
    --destination <lumberjackOrch1_coldkey_ss58> \
    --amount 50
```

### Step 2.3 — Register on Subnet

```bash
# Check registration cost
btcli subnet list --network finney  # Look at SN105 Recycle column

# Register on mainnet SN105
btcli subnet register \
    --wallet.name lumberjackOrch1 \
    --wallet.hotkey lumberjackOrch1hot \
    --netuid 105 \
    --network finney

# OR testnet first
btcli subnet register \
    --wallet.name lumberjackOrch1 \
    --wallet.hotkey lumberjackOrch1hot \
    --netuid 304 \
    --network test
```

### Step 2.4 — Add Stake

```bash
# Stake TAO to your hotkey
btcli stake add \
    --wallet.name lumberjackOrch1 \
    --wallet.hotkey lumberjackOrch1hot \
    --netuid 105 \
    --amount 200 \
    --network finney
```

### Step 2.5 — Verify Registration

```bash
# Get your UID
btcli subnet metagraph --netuid 105 --network finney | grep lumberjackOrch1hot

# Note your UID - you'll need it
```

---

## Phase 3: Install BEAM Orchestrator

### Step 3.1 — Clone and Setup

```bash
cd ~/beam-orch
git clone https://github.com/Beam-Network/beam.git
cd beam

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
```

### Step 3.2 — Install Dependencies

```bash
# Install bittensor
pip install bittensor>=8.0.0

# Install orchestrator dependencies
pip install fastapi uvicorn sqlalchemy asyncpg alembic aiohttp websockets \
    redis pynacl cryptography pydantic pydantic-settings pyyaml httpx \
    python-multipart torch numpy substrate-interface

# OR if requirements.txt exists
pip install -r requirements.txt
```

---

## Phase 4: Orchestrator Configuration

### Step 4.1 — Create Environment File

```bash
cd ~/beam-orch/beam/neurons/orchestrator
nano .env
```

```env
# ========================================
# BEAM Orchestrator Config (taoLumberjack)
# ========================================

# --- API Settings ---
ORCHESTRATOR_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO

# --- Wallet ---
WALLET_NAME=lumberjackOrch1
WALLET_HOTKEY=lumberjackOrch1hot
WALLET_PATH=~/.bittensor/wallets

# --- Subnet ---
NETUID=105
SUBTENSOR_NETWORK=finney
# SUBTENSOR_ADDRESS=wss://entrypoint-finney.opentensor.ai:443

# --- Orchestrator Identity ---
# Get your UID from metagraph
ORCHESTRATOR_UID=<your_uid_here>

# --- Fee Settings ---
# % of emission you share with workers (0-100)
# Lower = you keep more, but fewer workers join
# Higher = more workers, but less profit
FEE_PERCENTAGE=15

# --- ALPHA Payment Settings ---
# Amount of ALPHA to pay per completed task/chunk
ALPHA_PER_CHUNK=0.5

# --- Readiness ---
# Set to true when ready to receive transfers
READY=false

# --- Worker Management ---
MAX_WORKERS=10000
WORKER_TIMEOUT=300
MIN_WORKER_BANDWIDTH=10.0
WORKER_HEARTBEAT_INTERVAL=30

# --- Task Settings ---
MAX_CONCURRENT_TASKS=1000
TASK_TIMEOUT=120
CHUNK_SIZE=1048576

# --- Proof Aggregation ---
PROOF_BATCH_SIZE=100
PROOF_AGGREGATION_INTERVAL=60
MIN_PROOFS_FOR_EPOCH=10

# --- Validator Communication ---
VALIDATOR_REPORT_INTERVAL=300
MIN_VALIDATOR_STAKE=10.0

# --- BeamCore API ---
SUBNET_CORE_URL=https://beamcore.b1m.ai
# For testnet: https://beamcore-dev.b1m.ai

# --- Database (optional) ---
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost/beam

# --- Redis (recommended) ---
REDIS_URL=redis://localhost:6379/0

# --- Storage ---
STORAGE_GATEWAY_URL=https://storage.beam.network
STORAGE_REPLICATION_FACTOR=3

# --- Registry ---
REGISTRY_URL=https://beamcore.b1m.ai
REGISTRY_ENABLED=true
REGISTRY_HEARTBEAT_INTERVAL=30

# --- Client Auth ---
CLIENT_AUTH_ENABLED=true
CLIENT_STAKE_GATED_ENABLED=true

# --- Subnet Auth ---
SUBNET_AUTH_ENABLED=true
SUBNET_AUTH_REQUIRE_METAGRAPH=true
SUBNET_AUTH_MIN_VALIDATOR_STAKE=100.0
SUBNET_AUTH_MIN_WORKER_STAKE=0.0

# --- CORS ---
CORS_ALLOWED_ORIGINS="*"
CORS_ALLOW_CREDENTIALS=false
```

### Step 4.2 — Configure Nginx (Reverse Proxy)

```bash
sudo nano /etc/nginx/sites-available/beam-orch
```

```nginx
server {
    listen 80;
    server_name beam-orch.yourdomain.com;  # Optional
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts for long-lived connections
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/beam-orch /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Step 4.3 — Firewall

```bash
sudo ufw allow 8000/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

## Phase 5: Worker Setup

Workers are SEPARATE processes that connect to your orchestrator. You can run them on the same server or different servers.

### Step 5.1 — Worker Wallet Setup

Each worker needs its own wallet:

```bash
# Create worker wallet
btcli wallet create --wallet.name lumberjackWorker1 --wallet.hotkey lumberjackWorker1hot

# Fund it with a small amount for registration
btcli wallet transfer \
    --wallet.name lumberjackOrch1 \
    --destination <lumberjackWorker1_coldkey_ss58> \
    --amount 1
```

### Step 5.2 — Run Worker

```bash
cd ~/beam-orch/beam/neurons/worker

# Edit worker config if needed
nano worker.py
# Change SUBNET_CORE_URL to testnet if testing

# Run worker
python3 worker.py \
    --wallet.name lumberjackWorker1 \
    --wallet.hotkey lumberjackWorker1hot \
    --subtensor.network finney
```

### Step 5.3 — Scale Workers

For production, run multiple workers on different servers:

```bash
# Worker 1 (on server A)
python3 worker.py --wallet.name lumberjackWorker1 --wallet.hotkey lumberjackWorker1hot

# Worker 2 (on server B)
python3 worker.py --wallet.name lumberjackWorker2 --wallet.hotkey lumberjackWorker2hot

# Worker 3 (on server C)
python3 worker.py --wallet.name lumberjackWorker3 --wallet.hotkey lumberjackWorker3hot
```

**Target**: 20-50 workers for competitive performance.

---

## Phase 6: Start Orchestrator

### Step 6.1 — First Run (Manual)

```bash
cd ~/beam-orch/beam/neurons/orchestrator
source ../../venv/bin/activate

# Start orchestrator
python3 main.py
```

**Watch for:**
- `Orchestrator initialized`
- `Connected to subtensor: finney`
- `Registered on subnet 105 with UID <your_uid>`
- `API server running on 0.0.0.0:8000`
- Workers connecting via WebSocket

### Step 6.2 — Enable Readiness

Once everything is working:

```bash
# Send readiness signal
curl -X PATCH http://localhost:8000/orchestrators/ready \
    -H "Content-Type: application/json" \
    -d '{"ready": true}'
```

Or set `READY=true` in `.env` and restart.

### Step 6.3 — Create Systemd Service

```bash
sudo nano /etc/systemd/system/beam-orch.service
```

```ini
[Unit]
Description=BEAM SN105 Orchestrator (taoLumberjack)
After=network.target redis-server.service

[Service]
Type=simple
User=itLumberjack
WorkingDirectory=/home/itLumberjack/beam-orch/beam/neurons/orchestrator
Environment="PATH=/home/itLumberjack/beam-orch/beam/venv/bin"
Environment="PYTHONPATH=/home/itLumberjack/beam-orch/beam"
ExecStart=/home/itLumberjack/beam-orch/beam/venv/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=beam-orch

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable beam-orch
sudo systemctl start beam-orch
sudo journalctl -u beam-orch -f
```

---

## Phase 7: Critical Payment Setup

### Step 7.1 — Verify Payment Configuration

The chat logs show most orchestrators FAIL because they don't properly submit on-chain payments.

**Your orchestrator MUST:**
1. Submit `batch_all` extrinsic with:
   - `System.remark_with_event("{transfer_id}:{task_id}")`
   - `SubtensorModule.transfer_stake(...)`
2. Get `tx_hash = "{extrinsic_hash}:{block_hash}"`
3. POST tx_hash to BeamCore

### Step 7.2 — Verify Payment Code

Check that your `reward_manager.py` has the correct flow:

```python
# In reward_manager.py, ensure this sequence:

# 1. Validate transfer before payment
validation = await subnet_core_client.validate_transfer_for_payment(task_id)
if not validation.get("valid"):
    logger.warning("Transfer validation failed")
    return None

# 2. Submit on-chain payment
batch_call = substrate.compose_call(
    call_module='Utility',
    call_function='batch_all',
    call_params={'calls': [
        substrate.compose_call('System', 'remark_with_event', 
            {'remark': f"{transfer_id}:{task_id}"}),
        substrate.compose_call('SubtensorModule', 'transfer_stake', {
            'destination_coldkey': worker_coldkey,
            'hotkey': wallet.hotkey.ss58_address,
            'origin_netuid': netuid,
            'destination_netuid': netuid,
            'alpha_amount': amount_rao,
        }),
    ]}
)

receipt = substrate.submit_extrinsic(batch_call, wait_for_inclusion=True)
tx_hash = f"{receipt.extrinsic_hash}:{receipt.block_hash}"

# 3. Record payment
await subnet_core_client.record_pob_payment(
    task_id=task_id,
    tx_hash=tx_hash,
    amount_rao=amount_rao,
)

# 4. Record worker payment
await subnet_core_client.record_worker_payment(
    WorkerPaymentData(
        orchestrator_hotkey=hotkey,
        epoch=current_epoch,
        worker_id=worker_id,
        worker_hotkey=worker_hotkey,
        bytes_relayed=bytes_relayed,
        amount_earned=amount_rao,
        task_id=task_id,
        tx_hash=tx_hash,
    )
)
```

### Step 7.3 — Monitor Payments

```bash
# Watch for payment errors in logs
sudo journalctl -u beam-orch -f | grep -E "(payment|PAYMENT|FAILED|tx_hash)"
```

**Red flags:**
- `tx_hash is NULL`
- `Subtensor.transfer() got unexpected keyword argument`
- `Failed to record PoB payment`
- `ALPHA payment FAILED`

---

## Phase 8: Monitoring & Optimization

### Step 8.1 — Monitor Dashboard

Check the BeamCore dashboard (if available) for:
- Your UID's compliance score
- Worker payment status
- Task completion rate
- SLA score

### Step 8.2 — Key Metrics to Watch

```bash
# Worker connections
curl http://localhost:8000/metrics | grep workers_connected

# Task completion rate
curl http://localhost:8000/metrics | grep tasks_completed

# Payment success rate
curl http://localhost:8000/metrics | grep payments_successful
```

### Step 8.3 — Optimize Performance

| Metric | Target | Action if Low |
|--------|--------|---------------|
| Compliance | > 0.5 | Pay workers faster |
| SLA | > 0.7 | Improve worker quality |
| Worker count | 20-100 | Lower fee percentage |
| Task acceptance | > 90% | Add more workers |
| Payment speed | < 5 min | Optimize payment pipeline |

### Step 8.4 — Avoid Common Pitfalls

1. **Don't set READY=true until tested**
2. **Don't skip on-chain payments** — compliance drops = zero emissions
3. **Don't use too high fee percentage** — workers won't join
4. **Don't let workers go offline** — SLA drops
5. **Monitor epoch boundaries** — grace period is task.epoch + 1

---

## Phase 9: Maintenance

### Update Code

```bash
cd ~/beam-orch/beam
git fetch origin
git pull origin main
sudo systemctl restart beam-orch
```

### Restart After Issues

```bash
# If payment system fails
sudo systemctl stop beam-orch
# Fix code
sudo systemctl start beam-orch

# Clear retry queue if needed
# Edit: remove stale entries from payment_retry_queue
```

---

## Quick Reference

```bash
# Start orchestrator
sudo systemctl start beam-orch

# Stop
sudo systemctl stop beam-orch

# Logs
sudo journalctl -u beam-orch -f

# Status
sudo systemctl status beam-orch

# Restart
sudo systemctl restart beam-orch

# Metagraph
btcli subnet metagraph --netuid 105 --network finney

# Balance
btcli wallet balance --wallet.name lumberjackOrch1
```

---

## Cost Breakdown

| Item | Cost Estimate |
|------|---------------|
| VPS (16 vCPU, 64GB, 10Gbps) | ~$200/month |
| Worker servers (x5) | ~$100/month each |
| TAO Registration | ~1-5 TAO |
| Minimum Stake | 100+ TAO |
| ALPHA for worker payments | Varies (earned from emissions) |
| Total Initial | ~105-600 TAO + server costs |

---

## Critical Success Factors

1. **Workers must be paid ON TIME** — compliance < 0.5 = zero emissions
2. **On-chain tx_hash must be submitted** — NULL tx_hash = 50% penalty
3. **Workers must stay online** — SLA < 0.7 = reduced rewards
4. **Monitor epoch boundaries** — payments need task.epoch + 1 grace period
5. **Keep code updated** — Beam team pushes fixes frequently

---

*Plan version: 2026-04-21 | For BEAM SN105 | taoLumberjack*
