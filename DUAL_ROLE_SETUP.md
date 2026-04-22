# BEAM Subnet 105 — Dual Role Setup (Orchestrator + Validator)

## VPS Specs (VULTR)

**Recommended for dual-role:**
- **VPS**: High Frequency 8vCPU / 32GB RAM / 256GB NVMe
- **OS**: Ubuntu 22.04 LTS
- **Bandwidth**: Unmetered (critical for BEAM)
- **Cost**: ~$48/mo

**Minimum viable:**
- 6vCPU / 16GB RAM / 160GB SSD
- But dual-role will be tight on resources

## Wallet Setup

```bash
# Wallet 1: Orchestrator
btcli w create --wallet.name taolumberjackBeamOrch
btcli w create_hotkey --wallet.name taolumberjackBeamOrch --wallet.hotkey orch1

# Wallet 2: Validator
btcli w create --wallet.name taoLumberjackBeamVal
btcli w create_hotkey --wallet.name taoLumberjackBeamVal --wallet.hotkey val1
```

## Registration (needs TAO for fees)

```bash
# Check balance
btcli w balance --wallet.name taolumberjackBeamOrch
btcli w balance --wallet.name taoLumberjackBeamVal

# Register both on subnet 105
btcli s register --netuid 105 --wallet.name taolumberjackBeamOrch --wallet.hotkey orch1
btcli s register --netuid 105 --wallet.name taoLumberjackBeamVal --wallet.hotkey val1

# Check registration
btcli s list --netuid 105
```

## Funding Requirements

**Orchestrator:** Needs ALPHA (stake) to pay workers
- Transfer ALPHA to `taolumberjackBeamOrch` coldkey
- Stake: `btcli s stake --netuid 105 --wallet.name taolumberjackBeamOrch --wallet.hotkey orch1 --amount <amount>`

**Validator:** Needs TAO for registration fees
- Already registered above
- No ongoing funding needed (earns through weight-setting)

## Installation

```bash
# 1. SSH into your VULTR VPS
ssh root@<your-vps-ip>

# 2. Install dependencies
apt update && apt upgrade -y
apt install -y python3-pip python3-venv git curl build-essential

# 3. Clone repo (patched branch)
git clone https://github.com/taolumberjack/beam.git
cd beam-sn105
git checkout taolumberjack-patches

# 4. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 5. Install
pip install -e .

# 6. Copy .env template
cp .env.example .env
nano .env  # Edit with your settings
```

## Running Both Roles

### Option A: Systemd Services (Recommended for production)

Create two service files:

**`/etc/systemd/system/beam-orch.service`:**
```ini
[Unit]
Description=BEAM Orchestrator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/beam-sn105
Environment=PYTHONPATH=/root/beam-sn105
Environment=PATH=/root/beam-sn105/venv/bin
ExecStart=/root/beam-sn105/venv/bin/python neurons/orchestrator/orchestrator.py \
    --wallet.name taolumberjackBeamOrch \
    --wallet.hotkey orch1 \
    --netuid 105 \
    --subtensor.network finney \
    --logging.debug
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/beam-val.service`:**
```ini
[Unit]
Description=BEAM Validator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/beam-sn105
Environment=PYTHONPATH=/root/beam-sn105
Environment=PATH=/root/beam-sn105/venv/bin
ExecStart=/root/beam-sn105/venv/bin/python neurons/validator/core/validator.py \
    --wallet.name taoLumberjackBeamVal \
    --wallet.hotkey val1 \
    --netuid 105 \
    --subtensor.network finney \
    --logging.debug
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
systemctl daemon-reload
systemctl enable beam-orch beam-val
systemctl start beam-orch beam-val

# Check status
systemctl status beam-orch
systemctl status beam-val

# View logs
journalctl -u beam-orch -f
journalctl -u beam-val -f
```

### Option B: tmux/Screen (For testing)

```bash
# Terminal 1 - Orchestrator
tmux new -s orch
source beam-sn105/venv/bin/activate
cd beam-sn105
python neurons/orchestrator/orchestrator.py \
    --wallet.name taolumberjackBeamOrch \
    --wallet.hotkey orch1 \
    --netuid 105
# Ctrl+B, D to detach

# Terminal 2 - Validator
tmux new -s val
source beam-sn105/venv/bin/activate
cd beam-sn105
python neurons/validator/core/validator.py \
    --wallet.name taoLumberjackBeamVal \
    --wallet.hotkey val1 \
    --netuid 105
# Ctrl+B, D to detach

# Reattach
tmux attach -t orch
tmux attach -t val
```

## Monitoring

```bash
# Check both processes are running
ps aux | grep -E "orchestrator|validator"

# Check resource usage
htop

# Check logs
tail -f /var/log/syslog | grep -E "beam|orchestrator|validator"

# Check Bittensor status
btcli s metagraph --netuid 105
```

## Ports to Open (VULTR Firewall)

```
TCP 22     - SSH
TCP 80     - HTTP (optional, for web dashboard)
TCP 443    - HTTPS (optional)
TCP 9944   - Subtensor RPC (if running local node)
TCP 9945   - Subtensor WS (if running local node)
```

## .env Configuration (Key Settings)

```bash
# /root/beam-sn105/.env

# Subtensor
SUBTENSOR_NETWORK=finney
SUBTENSOR_CHAIN_ENDPOINT=wss://entrypoint-finney.opentensor.ai:443

# Netuid
NETUID=105

# SubnetCore API (if available)
SUBNET_CORE_URL=https://api.taolumberjack.com
SUBNET_CORE_API_KEY=your_api_key

# Orchestrator-specific
ALPHA_PER_CHUNK=0.5
MIN_PAYMENT_THRESHOLD=0.0005

# Validator-specific
VALIDATION_INTERVAL=300
WEIGHT_SET_INTERVAL=3600
```

## Quick Status Checks

```bash
# Is orchestrator accepting tasks?
curl -s http://localhost:8000/health  # If HTTP API enabled

# Is validator setting weights?
journalctl -u beam-val --since "1 hour ago" | grep "weights"

# Check if payments are working (orchestrator logs)
journalctl -u beam-orch --since "10 minutes ago" | grep -E "ALPHA|payment|transfer"

# Check validator is verifying payments
journalctl -u beam-val --since "10 minutes ago" | grep -E "verify|slash|penalty"
```

## Troubleshooting

**Orchestrator not paying?**
- Check ALPHA stake balance: `btcli s stake --netuid 105 --wallet.name taolumberjackBeamOrch`
- Check SubnetCore client connection in logs

**Validator not setting weights?**
- Check metagraph inclusion: `btcli s metagraph --netuid 105`
- Ensure sufficient stake for weight-setting privileges

**Both roles using too much RAM?**
- Orchestrator: Reduce `MAX_CONCURRENT_TASKS` in config
- Validator: Reduce `BATCH_SIZE` for proof verification

## Security Notes

1. **Never share coldkey mnemonic** — Store it offline
2. **Use separate hotkeys** — Already set up above
3. **Firewall everything except required ports**
4. **Regular backups**:
   ```bash
   tar czf ~/wallets-backup.tar.gz ~/.bittensor/wallets/
   # Copy to secure storage
   ```

## Next Steps After Setup

1. ⬜ Fund wallets with TAO for registration
2. ⬜ Register both on subnet 105
3. ⬜ Stake ALPHA on orchestrator wallet
4. ⬜ Start both services
5. ⬜ Monitor for 24h to ensure stable
6. ⬜ Set up alerts (disk, memory, service down)
