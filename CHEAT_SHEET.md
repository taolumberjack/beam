# BEAM Subnet 105 — Error Cheat Sheet & Knowledge Base

*Compiled from Discord chat logs (Apr 13-21, 2026) and source code analysis*

---

## Table of Contents
1. [Payment System Errors](#1-payment-system-errors)
2. [BeamCore API Errors](#2-beamcore-api-errors)
3. [Compliance & Scoring Issues](#3-compliance--scoring-issues)
4. [Worker Connection Errors](#4-worker-connection-errors)
5. [Weight & Validation Errors](#5-weight--validation-errors)
6. [Bittensor Chain Errors](#6-bittensor-chain-errors)
7. [Configuration Errors](#7-configuration-errors)
8. [Quick Diagnosis Flowchart](#8-quick-diagnosis-flowchart)

---

## 1. Payment System Errors

### 1.1 `worker_payments.tx_hash is NULL`
**Error:** All worker_payments.tx_hash fields for recent epochs are NULL
**Reporter:** N_Beam (team)
**Root Cause:** Orchestrator creates PoB (Proof-of-Bandwidth) records but NEVER actually submits the on-chain `batch_all` extrinsic. The code path skips the blockchain transaction and goes straight to recording the payment in BeamCore.
**Affected File:** `neurons/orchestrator/core/reward_manager.py`
**Code Location:** `pay_worker_immediately()` method — the `transfer_alpha_with_memo()` call fails silently or is bypassed
**Fix:**
```python
# BEFORE (broken):
# tx_hash = "placeholder"  # or skipped entirely
# await subnet_core_client.record_worker_payment(...)

# AFTER (fixed):
receipt = substrate.submit_extrinsic(batch_call, wait_for_inclusion=True)
tx_hash = f"{receipt.extrinsic_hash}:{receipt.block_hash}"
await subnet_core_client.record_pob_payment(task_id=proof.task_id, tx_hash=tx_hash, amount_rao=amount_rao)
```
**Prevention:** Log every payment attempt. Alert if `tx_hash` is empty or doesn't contain `:` separator.
**Severity:** 🔴 CRITICAL — zero compliance without valid tx_hash

---

### 1.2 `Subtensor.transfer() got an unexpected keyword argument 'destination_ss58'`
**Error:** Retry payment error — old bittensor API call fails
**Reporter:** Eliaquim (UID unknown)
**Root Cause:** `process_payment_retry_queue()` uses legacy `subtensor.transfer(destination_ss58=...)` API which was removed in bittensor 8.x. The retry queue path is separate from the main payment path and wasn't updated.
**Affected File:** `neurons/orchestrator/core/reward_manager.py` (~line 581+)
**Code Location:** `process_payment_retry_queue()` method
**Fix:**
```python
# BEFORE (broken):
response = subtensor.transfer(
    wallet=wallet,
    destination_ss58=payment_dest,  # ❌ invalid param in v8+
    amount=amount,
)

# AFTER (fixed):
# Use SubtensorModule.transfer_stake in batch_all (same as immediate payment)
batch_call = substrate.compose_call(
    call_module='Utility',
    call_function='batch_all',
    call_params={'calls': [
        substrate.compose_call('System', 'remark_with_event', {'remark': f"retry:{task_id}"}),
        substrate.compose_call('SubtensorModule', 'transfer_stake', {
            'destination_coldkey': payment_dest,
            'hotkey': wallet.hotkey.ss58_address,
            'origin_netuid': netuid,
            'destination_netuid': netuid,
            'alpha_amount': int(reward * 1e9),
        }),
    ]}
)
receipt = substrate.submit_extrinsic(batch_call, wait_for_inclusion=True)
```
**Prevention:** Remove all legacy `subtensor.transfer()` calls. Standardize on `batch_all` + `transfer_stake` everywhere.
**Severity:** 🔴 CRITICAL — retry queue is completely broken

---

### 1.3 Manual Payment Not Recorded — `has_pob=False`
**Error:** "I already paid these manually. The poller is picking them up again because they still show has_pob=False on BeamCore."
**Reporter:** ROCK [SNTY] (UID 69)
**Root Cause:** Manual on-chain payments were made but the orchestrator never POSTed the `tx_hash` to BeamCore's `/pob/{task_id}/payment` endpoint. BeamCore doesn't watch the chain directly — it relies on the orchestrator to report the tx_hash.
**Affected File:** `neurons/orchestrator/core/reward_manager.py`
**Fix:** After ANY manual payment, call:
```bash
curl -X POST "https://beamcore.b1m.ai/pob/{task_id}/payment" \
  -H "Content-Type: application/json" \
  -d '{"tx_hash": "0xEXTRINSIC_HASH:0xBLOCK_HASH", "amount_rao": 1000000000}'
```
**Prevention:** Build an automatic payment loop that retries until `has_pob=True` is confirmed.
**Severity:** 🟡 MEDIUM — compliance drops, but recoverable

---

### 1.4 `transfer_stake` Parameter Confusion
**Error:** "Which should I use among coldkey address and hotkey address for 'hotkey' parameter?"
**Reporter:** Eliaquim
**Root Cause:** Confusion about `transfer_stake` call parameters in the `batch_all` extrinsic.
**Correct Parameters:**
```python
substrate.compose_call('SubtensorModule', 'transfer_stake', {
    'destination_coldkey': worker_coldkey,      # ← Worker's coldkey (receives ALPHA)
    'hotkey': wallet.hotkey.ss58_address,       # ← YOUR hotkey (signing/staking key)
    'origin_netuid': netuid,                     # ← Subnet ID (105 or 304)
    'destination_netuid': netuid,                # ← Same subnet
    'alpha_amount': amount_rao,                  # ← Amount in RAO (1e-9 ALPHA)
})
```
**Key Rule:** `destination_coldkey` = who gets paid. `hotkey` = your orchestrator's hotkey (same as wallet.hotkey).
**Affected File:** `neurons/orchestrator/core/reward_manager.py` — `transfer_alpha_with_memo()`
**Severity:** 🟡 MEDIUM — wrong params = failed payments

---

### 1.5 Epoch Boundary Payment Race Condition
**Error:** Transfer happens 2 seconds before epoch ends → payment rejected with 410
**Reporter:** N_Beam (explaining the issue)
**Root Cause:** Old grace period was too short. Payment submitted in epoch N but validator checks in epoch N+1 → rejected.
**Fix Applied by Team:** Grace period extended to `task.epoch + 1` (~72 minutes total)
**Your Code:** Ensure `epoch_manager.py` respects grace period:
```python
# In payment validation logic
grace_period_epoch = task.epoch + 1
if current_epoch <= grace_period_epoch:
    accept_payment()
else:
    reject_with_410()
```
**Prevention:** Don't wait until end of epoch to batch payments. Pay immediately per task.
**Severity:** 🟢 LOW — fixed by team, but understand the boundary

---

## 2. BeamCore API Errors

### 2.1 `502 Bad Gateway` on `/orchestrators/assignments`
**Error:** `Failed to post assignments for transfer xfer-...: Server error '502 Bad Gateway' for url 'https://beamcore.b1m.ai/orchestrators/assignments'`
**Reporter:** Mnilko, Eliaquim (multiple orchestrators)
**Root Cause:** BeamCore backend overloaded during high transfer volume. Not an orchestrator bug.
**Affected File:** `neurons/orchestrator/core/orchestrator.py` — `post_assignments()`
**Fix (Orchestrator-side):** Add exponential backoff retry:
```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((aiohttp.ClientError, aiohttp.ServerDisconnectedError))
)
async def post_assignments_with_retry(self, transfer_id, assignments):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{self.beamcore_url}/orchestrators/assignments",
            json={"transfer_id": transfer_id, "assignments": assignments},
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status == 502:
                raise aiohttp.ServerDisconnectedError("BeamCore 502")
            resp.raise_for_status()
            return await resp.json()
```
**Prevention:** Always wrap BeamCore calls in retry logic. Cache assignments locally until confirmed.
**Severity:** 🟡 MEDIUM — transient, but breaks task flow

---

### 2.2 `Failed to fetch payments from BeamCore for epoch N`
**Error:** `Error getting epoch payments` / `Failed to fetch payments from BeamCore for epoch 22122`
**Reporter:** Eliaquim
**Root Cause:** BeamCore API timeout or epoch data not yet generated. `epoch_manager.py` tries to fetch payment summary before BeamCore has processed the epoch.
**Affected File:** `neurons/orchestrator/core/epoch_manager.py` — `generate_payment_proofs()`
**Fix:**
```python
# Add fallback when BeamCore fetch fails
async def generate_payment_proofs(self, epoch, ...):
    payments = []
    
    # Try BeamCore first
    if subnet_core:
        try:
            beamcore_payments = await subnet_core.get_epoch_payments(epoch)
            payments = beamcore_payments.get("payments", [])
        except Exception as e:
            logger.warning(f"BeamCore fetch failed for epoch {epoch}: {e}")
    
    # Fallback: use local accumulator
    if not payments:
        logger.info(f"Using local payment accumulator for epoch {epoch}")
        payments = self._get_local_epoch_payments(epoch)
    
    # Continue with merkle root generation...
```
**Prevention:** Maintain local payment ledger as backup. Don't depend solely on BeamCore for epoch summaries.
**Severity:** 🟡 MEDIUM — epoch proof generation fails

---

## 3. Compliance & Scoring Issues

### 3.1 Compliance Score Drops to 0 (Zero Emissions)
**Error:** "Orchestrator completed 9 tasks but received no reward" / "compliance drops below 30%, zero emissions"
**Reporter:** Andre (UID 59), brownbo
**Root Cause:**
1. Workers not paid on time → `compliance_score` drops
2. `MIN_COMPLIANCE_FOR_EMISSIONS = 0.5` — below this = zero weight
3. `effective_comp = comp if comp >= 0.5 else 0.0` in weight calculator
**Affected File:** `neurons/validator/services/weight_calculator.py`
**Code:**
```python
# From compute_weights():
effective_comp = comp if comp >= MIN_COMPLIANCE_FOR_EMISSIONS else 0.0
raw = exposure_val * quality_final * confidence_val * penalty * effective_comp
```
**Fix:** Pay workers IMMEDIATELY after task completion. Don't batch. Don't delay.
**Recovery:**
- Unpaid jobs scroll out of 7-day window
- No automatic retry — worker never gets paid
- You recover after ~7 days but lose that worker's trust
**Prevention:**
```python
# In orchestrator.py - pay synchronously on task completion
async def on_task_completed(task_id, proof):
    await self.reward_manager.pay_worker_immediately(worker, proof, current_epoch, ...)
    await self.acknowledge_task_to_beamcore(task_id)
```
**Severity:** 🔴 CRITICAL — zero emissions = wasted stake

---

### 3.2 Same UIDs Claiming All Rewards (100, 101, 220, 221)
**Error:** "Why are the same few UIDs consistently claiming all the rewards?"
**Reporter:** brownbo
**Root Cause:** These UIDs were the ONLY ones with valid payment proofs + high compliance. Everyone else had NULL tx_hash or failed payments. The weight formula correctly concentrated weight on the few valid orchestrators.
**Explanation:**
```
raw_weight = exposure * quality * confidence * penalty * effective_comp
# Most orchestrators: effective_comp = 0 (compliance < 0.5)
# Valid orchestrators: effective_comp = 1.0 → they get ALL the weight
```
**Fix:** Fix your payment system. Don't complain about the formula.
**N_Beam's Response:** "No they are random UID we pick to test our changes."
**Severity:** 🟡 MEDIUM — perception issue, actually working as designed

---

### 3.3 SLA Reset Announced
**Error:** "System will be reset for all participants including SLA scores"
**Reporter:** N_Beam (team announcement)
**What Happened:** Team reset SLA and compliance scores to neutral for all orchestrators on Apr 14.
**Action Required:** None — this was a one-time reset during backend upgrades.
**Future:** Scores now accumulate normally. Don't expect another reset.
**Severity:** 🟢 INFO — historical event

---

## 4. Worker Connection Errors

### 4.1 `HTTP 403` on Worker WebSocket
**Error:** `[Worker] [WS] Connection error: InvalidStatus: server rejected WebSocket connection: HTTP 403`
**Reporter:** 🌟 (Discord user)
**Root Cause:**
1. Stale/invalid API key after system reset
2. Worker not registered on subnet 304 (testnet)
3. API key doesn't match worker_id in URL path
**Affected File:** `neurons/worker/worker.py`
**Fix:**
```bash
# 1. Clear cached credentials
rm -f ~/.beam_worker_*.json

# 2. Verify wallet is registered on correct subnet
btcli subnet metagraph --netuid 304 --network test | grep your_hotkey

# 3. Re-run worker (will re-register and get fresh API key)
python3 worker.py --wallet.name your_wallet --wallet.hotkey your_hotkey --subtensor.network test
```
**Prevention:** Auto-retry registration on 403. Don't cache API keys indefinitely.
**Severity:** 🟡 MEDIUM — worker can't connect = no work done

---

### 4.2 Worker Slots Capped at 100
**Error:** "We will begin with 100 active worker slots"
**Reporter:** N_Beam (team announcement)
**Rule:**
- 1,200 registered workers but only ~130 live
- Cap starts at 100
- If all 100 stay live for 24h → cap increases to 150
- If average drops → cap reduces automatically
**Action:** Ensure your workers are stable. Don't spam registrations.
**Severity:** 🟢 INFO — design constraint

---

## 5. Weight & Validation Errors

### 5.1 `weights and on-chain weights always different`
**Error:** "Why beam weights and on-chain weights always different?"
**Reporter:** helven
**Root Cause:**
1. Validator computes weights using local formula
2. `params_hash` mismatch between validator and BeamCore → validator refuses to use local computation
3. Validator falls back to relaying BeamCore's weights, but there may be a lag
4. `commit-reveal` scheme on Bittensor adds delay
**Affected File:** `neurons/validator/core/validator.py` — `_respond_to_weight_audits()`
**Code:**
```python
bc_hash = breakdowns.get("params_hash")
if bc_hash and not verify_params_hash(bc_hash):
    # Hash mismatch — fall back to relaying BeamCore weights
    logger.warning("params_hash mismatch, relaying BeamCore weights")
    uids = breakdowns.get("uids", [])
    weights = breakdowns.get("weights", [])
```
**Fix:** Keep validator code updated. `git pull` when BeamCore updates.
**Prevention:** Monitor `params_hash` in logs. Alert on mismatch.
**Severity:** 🟡 MEDIUM — weights are set, just source is different

---

### 5.2 `/validators/proof-ids` Endpoint Hit
**Error:** "Someone is sending requests to my orchestrator through /validators/proof-ids. What is this?"
**Reporter:** Andre
**Answer from N_Beam:** "Test transfers i picked random orchestrators. you wont get impacted."
**Explanation:** The Beam team runs spot-checks by randomly requesting proof IDs from orchestrators to verify they're actually doing work.
**Action:** None needed. Respond normally.
**Severity:** 🟢 INFO — expected behavior

---

## 6. Bittensor Chain Errors

### 6.1 `transfer_stake` vs `transfer` Confusion
**Problem:** Multiple orchestrators using wrong chain call
**Correct Flow:**
```python
# ✅ CORRECT: batch_all with remark + transfer_stake
batch_call = substrate.compose_call(
    'Utility', 'batch_all',
    {'calls': [
        substrate.compose_call('System', 'remark_with_event', {'remark': memo}),
        substrate.compose_call('SubtensorModule', 'transfer_stake', {
            'destination_coldkey': worker_coldkey,
            'hotkey': wallet.hotkey.ss58_address,
            'origin_netuid': netuid,
            'destination_netuid': netuid,
            'alpha_amount': amount_rao,
        }),
    ]}
)

# ❌ WRONG: Direct transfer (legacy, doesn't work in dTAO)
subtensor.transfer(wallet=wallet, destination_ss58=addr, amount=amt)

# ❌ WRONG: Missing remark_with_event
# Validators need the memo to verify the payment
```
**Severity:** 🔴 CRITICAL

---

### 6.2 `tx_hash` Format
**Format:** `"{extrinsic_hash}:{block_hash}"`
**Example:** `"0xabc123...def:0x987fed...cba"`
**Validation:**
- Must contain exactly one `:`
- Both parts must start with `0x`
- `extrinsic_hash` = 66 chars (including 0x)
- `block_hash` = 66 chars (including 0x)
**Code:**
```python
def validate_tx_hash(tx_hash: str) -> bool:
    if ":" not in tx_hash or tx_hash.count(":") != 1:
        return False
    parts = tx_hash.split(":")
    return (
        len(parts) == 2 and
        parts[0].startswith("0x") and len(parts[0]) == 66 and
        parts[1].startswith("0x") and len(parts[1]) == 66
    )
```
**Severity:** 🟡 MEDIUM — invalid format = verification fails

---

## 7. Configuration Errors

### 7.1 `READY=false` Default
**Problem:** New orchestrators don't receive transfers
**Cause:** Default `READY=false` in config. Orchestrator must explicitly opt-in.
**Fix:**
```bash
# Option 1: Environment variable
export READY=true

# Option 2: API call at runtime
curl -X PATCH http://localhost:8000/orchestrators/ready \
  -H "Content-Type: application/json" \
  -d '{"ready": true}'
```
**Severity:** 🟡 MEDIUM — orchestrator runs but gets no work

---

### 7.2 Testnet vs Mainnet Confusion
| Parameter | Testnet | Mainnet |
|-----------|---------|---------|
| NETUID | 304 | 105 |
| Subtensor | test | finney |
| BeamCore | beamcore-dev.b1m.ai | beamcore.b1m.ai |
| Subtensor URL | wss://test.finney.opentensor.ai | wss://entrypoint-finney.opentensor.ai |

**Common Mistake:** Using mainnet wallet on testnet or vice versa.
**Fix:** Use separate wallets or be explicit with `--network` flag.
**Severity:** 🟡 MEDIUM — wrong network = wrong subnet

---

## 8. Quick Diagnosis Flowchart

```
Orchestrator getting zero emissions?
├── Check compliance score
│   ├── < 0.5 → PAYMENT ISSUE → Check tx_hash in worker_payments
│   │   ├── tx_hash is NULL → Fix payment pipeline (Section 1.1)
│   │   ├── tx_hash invalid format → Fix tx_hash generation (Section 6.2)
│   │   └── tx_hash valid but rejected → Check transfer_stake params (Section 1.4)
│   └── >= 0.5 → Check SLA score
│       ├── < 0.7 → Worker quality issue
│       └── >= 0.7 → Check weight calculator / validator bugs
├── Check BeamCore connection
│   ├── 502 errors → Add retry logic (Section 2.1)
│   └── Connection OK → Check assignment posting
└── Check worker count
    ├── 0 workers → Worker connection/auth issue (Section 4.1)
    └── > 0 workers → Check task acceptance rate

Validator weights not matching?
├── Check params_hash in logs
│   └── Mismatch → git pull latest code (Section 5.1)
└── Check blocks_since_last_update
    └── < 100 → Wait for weight rate limit
```

---

## Error Severity Legend

| Symbol | Severity | Action |
|--------|----------|--------|
| 🔴 | CRITICAL | Fix immediately — zero emissions or broken core function |
| 🟡 | MEDIUM | Fix soon — degraded performance or intermittent failures |
| 🟢 | INFO | Monitor — expected behavior or informational |

---

## Patch Checklist

Before going live, verify:
- [ ] All `subtensor.transfer()` calls removed
- [ ] All payments use `batch_all` + `transfer_stake`
- [ ] `tx_hash` format is `{extrinsic_hash}:{block_hash}`
- [ ] `remark_with_event` memo included in every payment batch
- [ ] Retry queue uses same payment logic as immediate payments
- [ ] BeamCore API calls wrapped in exponential backoff retry
- [ ] Local payment accumulator maintained as fallback
- [ ] `READY=true` set before expecting transfers
- [ ] `NETUID` and `SUBTENSOR_NETWORK` match your target
- [ ] Worker WebSocket auth handles 403 by re-registering
- [ ] `params_hash` matches between validator and BeamCore

---

*Cheat sheet version: 2026-04-22 | Sources: Discord logs + beam repo source*
