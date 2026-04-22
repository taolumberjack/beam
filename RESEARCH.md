# BEAM Subnet (sn105) - Research & Analysis

## Overview

**BEAM** is a decentralized bandwidth coordination layer on Bittensor Subnet 105 (mainnet) / 304 (testnet). It creates an open market for bandwidth by coordinating distributed data transfers across a network of workers, orchestrators (miners), and validators.

**Repo:** https://github.com/Beam-Network/beam  
**Mainnet:** https://beamcore.b1m.ai  
**Testnet:** https://beamcore-dev.b1m.ai  
**Subnet UID:** 105 (mainnet), 304 (testnet)

---

## Architecture

```
Client → BeamCore → Orchestrator(s) → Workers → Destinations
              ↓                           ↓
         Validators ← Proof-of-Bandwidth ←┘
```

### Three Node Types

1. **Orchestrator (Miner)** - Coordinates bandwidth work
   - Polls BeamCore for chunk assignments
   - Assigns chunks to workers
   - Pays workers in ALPHA tokens (dTAO)
   - Submits Proof-of-Bandwidth (PoB) to BeamCore
   - Earns emissions based on validator weights

2. **Worker** - Executes actual data transfers
   - Connects to BeamCore via WebSocket
   - Receives task pushes via Buffer service
   - Fetches data from source URLs, delivers to destinations
   - Reports completion with bandwidth metrics
   - Gets paid by orchestrators

3. **Validator** - Verifies and scores
   - Fetches unverified proofs from BeamCore API
   - Verifies PoB (signatures, timing, bandwidth, canary)
   - Calculates SLA scores with multiplicative penalties
   - Verifies orchestrator payments to workers
   - Sets weights on-chain every ~100 blocks (~20 min)
   - Responds to weight audits from BeamCore

---

## Scoring Formula (exposure_v1)

```
raw_weight = exposure * quality * confidence * penalty

exposure   = 0.70 * bytes_share + 0.30 * proofs_share  (verified work)
quality    = 0.40*bw + 0.25*compliance + 0.20*verification + 0.15*spot_check
confidence = sqrt(verified_proofs/10)*0.70 + sqrt(verified_bytes/1GB)*0.30
penalty    = fraud * payment * sybil multipliers
```

**Critical thresholds:**
- `MIN_COMPLIANCE_FOR_EMISSIONS = 0.5` — below this = zero emissions
- `TRUST_THRESHOLD_COMPLIANCE = 0.5` — below = 0.5x penalty
- `TRUST_THRESHOLD_VERIFICATION = 0.5` — below = 0.5x penalty

---

## Key Issues from Chat Logs (Week of Apr 13-14)

### 1. Payment System Bugs (CRITICAL)
- **Missing on-chain tx_hash**: Many orchestrators creating "proof of payment" without actual on-chain transactions
- **worker_payments.tx_hash fields are NULL** for recent epochs
- **Wrong transfer function**: Using `SubtensorModule.transfer_stake` incorrectly — parameter confusion between coldkey/hotkey
- **Retry payment error**: `Subtensor.transfer() got unexpected keyword argument 'destination_ss58'`
- **502 Bad Gateway** on assignment posting: `beamcore.b1m.ai/orchestrators/assignments`

### 2. Compliance & Scoring Issues
- Same few UIDs (100, 101, 220, 221) consistently claiming all rewards
- Weights and on-chain weights are always different
- Orchestrators completing tasks but receiving no reward
- Unpaid tasks not reflected in dashboard

### 3. Worker Management
- ~1,200 registered workers but only ~130 actually live
- Worker slots capped at 100 (dynamic based on live ratio)
- Grace period for PoB payment extended to task.epoch + 1

### 4. System Resets
- SLA and compliance scores reset to neutral for all orchestrators
- System will be reset for all participants
- No need to reward workers during reset period

---

## Economic Model

### Emissions Distribution
```
Bittensor Emissions
        │
        ├──► Validators (18%)
        │      └── Based on stake & activity
        │
        └──► Orchestrators (82%)
               └── Based on validator weights
                    │
                    ├──► Operator Fee (orchestrator keeps %)
                    └──► Worker Pool (remainder)
```

### Orchestrator Revenue Factors
1. **Stake amount** — more stake = more chunk assignments
2. **SLA score** — multiplicative penalties for poor performance
3. **Worker count & quality** — more/better workers = more tasks
4. **Operator fee** — lower fee = more worker attraction
5. **Payment compliance** — must pay workers on time or get slashed

### Penalty Structure
- SLA < 0.70 → portion of rewards redirected to Orchestrator #1 (subnet treasury)
- Unpaid proofs → up to 50% penalty (5% per unpaid, max 50%)
- Invalid/missing tx_hash → 50% slash
- Fraud detected → severity-based multiplier (0.1 to 1.0)

---

## Technical Stack

| Component | Technology |
|-----------|-----------|
| Runtime | Python 3.10+ |
| Blockchain | Bittensor 8.0+ |
| API | FastAPI + uvicorn |
| Database | SQLAlchemy + asyncpg (optional) |
| Cache | Redis 7+ |
| WebSocket | websockets 12+ |
| HTTP | httpx 0.25+ |
| Crypto | pynacl, cryptography |
| Chain Ops | Fiber (weight setting) |
| Monitoring | Prometheus + Grafana |

---

## Key Files

### Orchestrator (Miner)
- `neurons/orchestrator/main.py` — Entry point, FastAPI app, WebSocket registration
- `neurons/orchestrator/core/orchestrator.py` — Main facade, delegates to managers
- `neurons/orchestrator/core/reward_manager.py` — Worker payments, retry queue, ALPHA transfers
- `neurons/orchestrator/core/epoch_manager.py` — Epoch lifecycle, payment proof generation
- `neurons/orchestrator/core/task_scheduler.py` — Task assignment, broadcast offers
- `neurons/orchestrator/core/proof_aggregator.py` — Proof collection, merkle trees
- `neurons/orchestrator/core/worker_manager.py` — Worker registration, health checks

### Validator
- `neurons/validator/main.py` — Entry point, FastAPI app
- `neurons/validator/core/validator.py` — Main loop, scoring, weight setting
- `neurons/validator/services/weight_calculator.py` — exposure_v1 formula implementation
- `neurons/validator/chain/fiber_chain.py` — On-chain weight setting via Fiber
- `neurons/validator/chain/tx_verifier.py` — On-chain transaction verification

### Worker
- `neurons/worker/worker.py` — Standalone worker, connects to BeamCore via WebSocket

### Shared
- `neurons/shared/merkle.py` — Merkle tree operations

---

## BeamCore API Endpoints (Key)

| Endpoint | Purpose |
|----------|---------|
| `POST /auth/challenge` | Get auth challenge |
| `POST /auth/verify` | Verify signature, get API key |
| `POST /workers/register` | Register worker |
| `POST /workers/heartbeat` | Worker heartbeat |
| `GET /workers/tasks/pending` | Poll for tasks |
| `POST /workers/tasks/accept` | Accept task |
| `POST /workers/tasks/complete` | Report completion |
| `POST /orchestrators/register` | Register orchestrator |
| `GET /orchestrators/assignments` | Get transfer assignments |
| `POST /orchestrators/assignments` | Post chunk assignments |
| `GET /pob/unverified` | Get unverified proofs |
| `POST /pob/verify` | Submit verification result |
| `GET /validators/audits` | Get pending weight audits |
| `POST /validators/audits` | Submit audit response |

---

## On-Chain Operations

### ALPHA Payment (Mandatory)
```python
# Batch call: system.remark_with_event + SubtensorModule.transfer_stake
batch_call = substrate.compose_call(
    call_module='Utility',
    call_function='batch_all',
    call_params={'calls': [
        # Memo for validator verification
        substrate.compose_call('System', 'remark_with_event', {'remark': f"{transfer_id}:{task_id}"}),
        # Actual ALPHA transfer
        substrate.compose_call('SubtensorModule', 'transfer_stake', {
            'destination_coldkey': worker_coldkey,
            'hotkey': wallet.hotkey.ss58_address,  # Orchestrator's hotkey
            'origin_netuid': netuid,
            'destination_netuid': netuid,
            'alpha_amount': amount_rao,
        }),
    ]}
)
```

### Weight Setting
```python
# Via Fiber (preferred)
fiber_chain.set_weights(wallet, validator_uid, uids, weights)

# Via Bittensor (fallback)
subtensor.set_weights(wallet, netuid, uids, weights)
```

---

## Current State (Apr 21, 2026)

- System undergoing backend upgrades
- SLA/compliance scores recently reset
- Worker slot cap: 100 (dynamic to 150 if all live for 24h)
- Payment system has critical bugs (tx_hash null, wrong API calls)
- Many orchestrators not actually submitting on-chain payments
- Validators verifying payments and applying penalties

---

## Opportunities

1. **Fix payment bugs** — Most orchestrators failing at this; fixing it = massive competitive advantage
2. **Optimize worker pool** — Better worker management = higher SLA scores
3. **Robust retry logic** — Handle BeamCore 502s, transient failures
4. **Validator accuracy** — Better PoB verification = more trustworthy weights
5. **Monitor compliance** — Real-time compliance tracking to avoid penalties
