# BEAM SN105 Payment System — Critical Code Audit
**Auditor:** Senior Blockchain Engineer (Subagent)  
**Date:** 2026-04-22  
**Scope:** Orchestrator reward/epoch flow + Validator on-chain verification  
**Focus:** NULL `tx_hash`, silent payment failures, ALPHA vs TAO mismatches, dTAO `batch_all` + `transfer_stake` correctness.

---

## Executive Summary

The BEAM orchestrator payment system contains **multiple CRITICAL bugs** that explain the widespread NULL / invalid `tx_hash` failures and validator slashing. The root cause is a **fundamental mismatch** between what the orchestrator pays (ALPHA via `batch_all` + `transfer_stake`) and what the validator verifies (legacy TAO `Balances.transfer`). Additionally, the orchestrator’s retry queue is still emitting legacy TAO transfers, and several edge cases in hash formatting, amount validation, and memo parsing will cause 100 % of on-chain ALPHA payments to be rejected by validators.

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 5 | Immediate patch required |
| HIGH | 6 | Patch before next epoch |
| MEDIUM | 5 | Patch in upcoming release |

---

## 1. `neurons/orchestrator/core/reward_manager.py`

### CRITICAL-1 — Retry queue emits legacy TAO `subtensor.transfer()` instead of ALPHA `batch_all`
- **Line:** 557
- **Details:** `process_payment_retry_queue()` calls `subtensor.transfer(...)` (legacy TAO transfer). It never calls `transfer_alpha_with_memo()`. This means:
  1. Retried payments send the **wrong token** (TAO, not ALPHA).
  2. The resulting tx is a `Balances.transfer` extrinsic, not `Utility.batch_all`.
  3. Even if the validator later fixes its verifier, retry payments will be flagged as legacy / invalid because they lack the mandatory `remark_with_event` memo.
- **Silent failure:** Because the retry path still produces a tx_hash string, it is saved to the DB and sent to BeamCore, masking the fact that the worker was paid in the wrong token.

**Patch:**
```python
# BEFORE (line ~557)
response = subtensor.transfer(
    wallet=wallet,
    destination_ss58=payment_dest,
    amount=amount,
    wait_for_inclusion=True,
    wait_for_finalization=False,
)

# AFTER — unify retry queue to use ALPHA transfer_stake
# 1. Store transfer_id + worker_coldkey + alpha_amount when queuing.
# 2. In process_payment_retry_queue, call transfer_alpha_with_memo instead.
#    (See CRITICAL-2 for queue item shape.)
worker_coldkey = item.get("worker_coldkey") or await self._resolve_worker_coldkey(
    item["worker_hotkey"], subtensor, netuid
)
transfer_id = item.get("transfer_id")
if not transfer_id:
    # Re-validate with SubnetCore if missing
    validation = await subnet_core_client.validate_transfer_for_payment(item["task_id"])
    transfer_id = validation.get("transfer_id")

if worker_coldkey and transfer_id:
    tx_hash = await self.transfer_alpha_with_memo(
        worker_coldkey=worker_coldkey,
        amount_alpha=item["alpha_amount"],   # ALPHA, not TAO
        transfer_id=f"{transfer_id}:{item['task_id']}",
        wallet=wallet,
        subtensor=subtensor,
        netuid=netuid,
    )
else:
    logger.error(f"Retry skipped: missing coldkey or transfer_id for {item['task_id']}")
    continue
```

---

### CRITICAL-2 — Retry queue stores mixed units (ALPHA `alpha_per_chunk` vs TAO `reward`) in the same field
- **Lines:** 151, 214, 222, 226, 254, 270, 293, 331, 335, 345
- **Details:** `_queue_failed_payment(worker, proof, reward_tao: float)` is called with:
  - `alpha_per_chunk` (e.g. `0.5` ALPHA) when validation fails or pre-conditions missing.
  - `reward` (TAO, calculated from emission delta) when balance is insufficient.
  The retry processor treats `item["reward_tao"]` as TAO and passes it to `subtensor.transfer` (see CRITICAL-1). The result is that some retries send 0.5 TAO instead of 0.5 ALPHA, while others send a TAO amount that has nothing to do with the intended ALPHA payment.
- **Impact:** Workers are either underpaid (wrong token) or the orchestrator overpays in TAO.

**Patch:**
```python
def _queue_failed_payment(
    self, worker, proof, alpha_amount: float, transfer_id: Optional[str] = None
):
    self._payment_retry_queue.append({
        "worker_hotkey": proof.worker_hotkey,
        "worker_id": proof.worker_id,
        "task_id": proof.task_id,
        "proof": proof,
        "alpha_amount": alpha_amount,     # Always ALPHA
        "transfer_id": transfer_id,       # Needed for memo
        "attempts": 0,
        "queued_at": time.time(),
    })
```

---

### CRITICAL-3 — `transfer_alpha_with_memo` produces malformed `tx_hash` when `receipt.*_hash` is `bytes`
- **Line:** 744
- **Details:** Substrate `receipt.extrinsic_hash` and `receipt.block_hash` are often `bytes` objects, not hex strings.
  ```python
  tx_hash = f"{receipt.extrinsic_hash}:{receipt.block_hash}"
  ```
  If these are bytes, Python formats them as `b'0xabc...':b'0xdef...'`, which is unparseable by validators and will always fail verification.

**Patch:**
```python
# Inside transfer_alpha_with_memo, after receipt.is_success check
ext_hash = receipt.extrinsic_hash
block_hash = receipt.block_hash

if isinstance(ext_hash, bytes):
    ext_hash = "0x" + ext_hash.hex()
if isinstance(block_hash, bytes):
    block_hash = "0x" + block_hash.hex()

tx_hash = f"{ext_hash}:{block_hash}"
```

---

### HIGH-1 — Retry queue checks TAO balance, not ALPHA stake
- **Line:** 482
- **Details:** `subtensor.get_balance(wallet.hotkey.ss58_address)` returns free TAO balance. ALPHA payments require staked ALPHA. An orchestrator with sufficient ALPHA stake but low free TAO will incorrectly skip retries, while one with high free TAO but low ALPHA stake will attempt retries and fail on-chain.

**Patch:**
```python
# Replace TAO balance check with ALPHA stake check (pseudocode — depends on SDK)
alpha_stake = subtensor.get_stake_for_coldkey_and_hotkey(
    coldkey_ss58=wallet.coldkey.ss58_address,
    hotkey_ss58=wallet.hotkey.ss58_address,
    netuid=netuid,
)
available_alpha = float(alpha_stake) - fee_buffer
```

---

### HIGH-2 — `transfer_alpha_with_memo` does not validate that `receipt.extrinsic_hash` and `receipt.block_hash` are present before formatting
- **Line:** 744
- **Details:** If either field is `None`, `tx_hash` becomes `"None:None"`. The `if tx_hash:` check passes (truthy string), `transfer_success` is set to `True`, and a fake hash is recorded in BeamCore / DB.

**Patch:**
```python
if receipt.is_success:
    ext_hash = receipt.extrinsic_hash
    block_hash = receipt.block_hash
    if not ext_hash or not block_hash:
        logger.error("ALPHA transfer succeeded but missing hash fields")
        return None
    # ... (bytes handling) ...
    tx_hash = f"{ext_hash}:{block_hash}"
```

---

### MEDIUM-1 — `payment_memo` format is fragile if `transfer_id` contains colons
- **Line:** 289
- **Details:** `payment_memo = f"{transfer_id}:{proof.task_id}"`. If `transfer_id` ever contains a colon, validators performing a simple split on `:` will parse the memo incorrectly. Use a delimiter that is guaranteed unique, or encode the pair as JSON.

**Patch:**
```python
import json
payment_memo = json.dumps({"xfer": transfer_id, "task": proof.task_id}, separators=(',', ':'))
```

---

## 2. `neurons/orchestrator/core/epoch_manager.py`

### HIGH-3 — `create_payment_merkle_tree` is never imported; placeholder root is submitted to BeamCore
- **Line:** 22
- **Details:** The module sets `create_payment_merkle_tree = None` and never imports the real implementation from `neurons/shared/merkle.py`. Consequently `generate_payment_proofs()` always skips merkle tree creation and submits `merkle_root = "0x" + "0" * 64` (placeholder) to BeamCore.
- **Impact:** Validators cannot verify payment inclusion because the real merkle root is never published.

**Patch:**
```python
# BEFORE (line 22)
create_payment_merkle_tree = None

# AFTER
from neurons.shared.merkle import create_payment_merkle_tree
```

---

### MEDIUM-2 — `generate_payment_proofs` submits placeholder root to BeamCore before attempting real tree generation
- **Line:** 164
- **Details:** Even with the import fixed, the function sends `merkle_root = "0x" + "0" * 64` to BeamCore at line 180 **before** trying to build the real tree. If the tree build crashes, BeamCore already has a fake root.

**Patch:**
```python
# Build tree FIRST, then submit to BeamCore
tree, payments_with_proofs = create_payment_merkle_tree(payments)
merkle_root = tree.root

# NOW update BeamCore with the real root
if subnet_core:
    ...
```

---

### MEDIUM-3 — Missing grace period logic (`task.epoch + 1`)
- **Details:** The audit requirement asked to verify that grace period equals `task.epoch + 1`. No such logic exists in `epoch_manager.py`. The only grace period found is `NEW_ORCHESTRATOR_GRACE_PERIOD_HOURS = 24` (orchestrator registration), which is unrelated to task payment deadlines. If a grace period was intended to allow payment one epoch late, it is absent.

**Recommendation:** Implement explicit grace period check in `generate_payment_proofs`:
```python
eligible_epochs = [epoch, epoch - 1]  # current + 1 grace epoch
payments = []
for e in eligible_epochs:
    ... fetch / accumulate payments for epoch e ...
```

---

## 3. `neurons/validator/chain/tx_verifier.py`

### CRITICAL-4 — `AlphaPaymentVerifier` is dead code; validator only uses legacy `TxVerifier`
- **Lines:** 26 (validator.py), 1156 (validator.py), 272 (tx_verifier.py)
- **Details:** `validator.py` imports only `TxVerifier` and `TxVerificationResult`. It instantiates `tx_verifier = TxVerifier(self.subtensor)` and uses it for **all** payments. `AlphaPaymentVerifier` is fully implemented but never imported or called. Therefore:
  - Validators never parse `Utility.batch_all`.
  - Validators never extract `remark_with_event` memos.
  - Validators never validate `SubtensorModule.transfer_stake` amounts.
- **Impact:** 100 % of valid ALPHA payments are invisible to the validator’s verification logic.

**Patch (validator.py):**
```python
# Add to imports (line 26)
from chain.tx_verifier import TxVerifier, TxVerificationResult, AlphaPaymentVerifier

# In _verify_orchestrator_payments (line ~1156)
tx_verifier = TxVerifier(self.subtensor) if self.subtensor else None
alpha_verifier = AlphaPaymentVerifier(self.subtensor) if self.subtensor else None

# Inside the payment verification loop (line ~1183)
if tx_hash.startswith("0x"):
    # ALPHA payments always contain ':' separating extrinsic_hash:block_hash
    if ":" in tx_hash and alpha_verifier:
        # Resolve worker coldkey from metagraph (same logic as orchestrator)
        worker_coldkey = await self._resolve_worker_coldkey(worker_hotkey, self.subtensor, self.config.netuid)
        expected_memo = payment.get("expected_memo") or f"{payment.get('transfer_id')}:{task_id}"
        verification = alpha_verifier.verify_alpha_payment(
            tx_hash=tx_hash,
            expected_transfer_id=expected_memo,
            expected_worker_coldkey=worker_coldkey,
            min_amount_alpha=0.0005,  # match orchestrator MIN_TRANSFER_RAO in ALPHA
        )
    else:
        # Legacy TAO path
        verification = tx_verifier.verify_transfer(
            tx_hash=tx_hash,
            expected_from=orchestrator_coldkey,  # never empty string
            expected_to=worker_payment_addr,
            expected_amount=amount_tao,
            tolerance=0.05,
        )
```

---

### CRITICAL-5 — `TxVerifier` rejects `Utility.batch_all`, causing 50 % slash on every valid ALPHA payment
- **Line:** 190–200 (`_query_extrinsic`)
- **Details:** The legacy verifier explicitly rejects any extrinsic that is not `Balances.transfer`:
  ```python
  if call_module != "Balances" or "transfer" not in call_function.lower():
      return TxVerificationResult(is_valid=False, error=f"not a transfer: {call_module}.{call_function}")
  ```
  Because ALPHA payments are `Utility.batch_all`, this returns `"not a transfer: Utility.batch_all"`. The validator interprets this as fraud and applies a 50 % slash (`existing * 0.5`).

**Patch:** See CRITICAL-4 — route ALPHA payments to `AlphaPaymentVerifier` and never run them through `TxVerifier`.

---

### HIGH-4 — `TxVerifier.verify_transfer` fails sender check when `expected_from=""`
- **Line:** 88
- **Details:** `validator.py` passes `expected_from=""` with the comment *"Skip sender check for now"*. However, `TxVerifier` does not skip the check:
  ```python
  if result.from_address != expected_from:   # real_address != ""  → ALWAYS True
      return TxVerificationResult(is_valid=False, error="sender mismatch ...")
  ```
  This means **even legacy TAO retry payments are marked invalid** because the sender check fails against the empty string.

**Patch:**
```python
# In TxVerifier.verify_transfer (line ~88)
if expected_from and result.from_address != expected_from:
    return TxVerificationResult(is_valid=False, error="sender mismatch ...")
```

---

### HIGH-5 — `AlphaPaymentVerifier` default `min_amount_alpha=1.0` rejects standard 0.5 ALPHA payments
- **Line:** 304
- **Details:** Orchestrator `transfer_alpha_with_memo` pays `alpha_per_chunk` (default `0.5` ALPHA) and tops up dust to `500_000` RAO (`0.0005` ALPHA). The verifier’s default minimum of `1.0` ALPHA means **all standard payments fail amount validation**.

**Patch:**
```python
# In AlphaPaymentVerifier.verify_alpha_payment signature
def verify_alpha_payment(
    self,
    tx_hash: str,
    expected_transfer_id: str,
    expected_worker_coldkey: str,
    min_amount_alpha: float = 0.0005,  # was 1.0
) -> AlphaPaymentVerificationResult:
```

---

### HIGH-6 — `AlphaPaymentVerifier` does not handle hex-encoded remark strings from Substrate
- **Line:** 485
- **Details:** Some Substrate clients return `remark_with_event` data as a hex string (`"0x1234..."`) rather than raw bytes or a list of ints. The current parser only handles `bytes`, `str`, and `list`. A hex string would be treated as the literal memo, causing a mismatch.

**Patch:**
```python
if isinstance(remark_value, str):
    if remark_value.startswith("0x"):
        try:
            memo = bytes.fromhex(remark_value[2:]).decode("utf-8", errors="ignore")
        except Exception:
            memo = remark_value
    else:
        memo = remark_value
```

---

### MEDIUM-4 — Validator verifies recipient `worker_hotkey` against tx `to_address`, but ALPHA tx pays to `worker_coldkey`
- **Line:** 1180 (validator.py)
- **Details:**
  ```python
  worker_payment_addr = payment.get("worker_hotkey", "")
  ```
  For ALPHA `transfer_stake`, the on-chain recipient is the worker’s **coldkey**. The validator compares the hotkey from the payment record against the coldkey in the extrinsic. This fails recipient verification even when the payment is legitimate.

**Patch:**
```python
# Resolve coldkey from metagraph (same helper as orchestrator)
worker_coldkey = await self._resolve_worker_coldkey(worker_hotkey, self.subtensor, self.config.netuid)
# Pass worker_coldkey as expected_to (or expected_worker_coldkey for AlphaPaymentVerifier)
```

---

### MEDIUM-5 — `TxVerifier` cache key collisions across different expected parameters
- **Line:** 75
- **Details:** `TxVerifier` caches by `tx_hash` alone. If the same tx_hash is checked with different `expected_to` or `expected_amount`, the cached result from the first check is returned. `AlphaPaymentVerifier` correctly uses a composite key (`f"{tx_hash}:{expected_transfer_id}:{expected_worker_coldkey}"`).

**Patch:**
```python
# In TxVerifier.verify_transfer
cache_key = f"{tx_hash}:{expected_from}:{expected_to}:{expected_amount}"
if cache_key in self._cache:
    return self._cache[cache_key]
# ... at the end ...
self._cache[cache_key] = result
```

---

## Unit Tests That Would Catch These Bugs

| # | Test | Target File | Bugs Caught |
|---|------|-------------|-------------|
| 1 | `test_retry_queue_calls_transfer_alpha_with_memo` | `reward_manager.py` | CRITICAL-1, CRITICAL-2 |
| 2 | `test_transfer_alpha_with_memo_bytes_hash` | `reward_manager.py` | CRITICAL-3 |
| 3 | `test_transfer_alpha_with_memo_none_hash_returns_none` | `reward_manager.py` | HIGH-2 |
| 4 | `test_retry_queue_alpha_balance_check` | `reward_manager.py` | HIGH-1 |
| 5 | `test_txverifier_rejects_batch_all` | `tx_verifier.py` | CRITICAL-5 |
| 6 | `test_validator_routes_alpha_to_alpha_verifier` | `validator.py` | CRITICAL-4 |
| 7 | `test_txverifier_empty_expected_from_skips_sender_check` | `tx_verifier.py` | HIGH-4 |
| 8 | `test_alpha_verifier_0_5_alpha_passes` | `tx_verifier.py` | HIGH-5 |
| 9 | `test_alpha_verifier_hex_remark` | `tx_verifier.py` | HIGH-6 |
| 10 | `test_epoch_manager_uses_real_merkle_tree` | `epoch_manager.py` | HIGH-3 |
| 11 | `test_merkle_root_empty_leaves` | `shared/merkle.py` | (regression) |
| 12 | `test_validator_expected_to_is_coldkey_for_alpha` | `validator.py` | MEDIUM-4 |
| 13 | `test_txverifier_cache_is_parameterized` | `tx_verifier.py` | MEDIUM-5 |

### Example test skeletons

```python
# test_reward_manager.py
@pytest.mark.asyncio
async def test_retry_queue_calls_transfer_alpha_with_memo(mock_reward_mgr):
    mock_reward_mgr._payment_retry_queue.append({
        "worker_hotkey": "5Hotkey...",
        "worker_id": "w1",
        "task_id": "t1",
        "proof": MagicMock(task_id="t1", worker_hotkey="5Hotkey...", bytes_relayed=100),
        "alpha_amount": 0.5,
        "transfer_id": "xfer-123",
        "attempts": 0,
        "queued_at": time.time(),
    })
    with patch.object(mock_reward_mgr, 'transfer_alpha_with_memo', new_callable=AsyncMock) as mock_alpha:
        mock_alpha.return_value = "0xabc:0xdef"
        await mock_reward_mgr.process_payment_retry_queue(
            current_epoch=1, wallet=MagicMock(), subtensor=MagicMock(),
            hotkey="5Orc...", db=None, subnet_core_client=MagicMock()
        )
    mock_alpha.assert_awaited_once()
    # Ensure subtensor.transfer was NEVER called
    mock_reward_mgr.subtensor.transfer.assert_not_called()

# test_tx_verifier.py
def test_alpha_verifier_hex_remark():
    verifier = AlphaPaymentVerifier(mock_subtensor)
    # Simulate substrate returning remark as hex string
    mock_extrinsic = {
        "call": {
            "call_module": "Utility",
            "call_function": "batch_all",
            "call_args": [{"name": "calls", "value": [
                {"call_module": "System", "call_function": "remark_with_event",
                 "call_args": [{"name": "remark", "value": "0x786665722d3132333a7431"}]},
                {"call_module": "SubtensorModule", "call_function": "transfer_stake",
                 "call_args": [
                     {"name": "destination_coldkey", "value": "5Cold..."},
                     {"name": "alpha_amount", "value": 500_000_000},
                     {"name": "hotkey", "value": "5Hot..."},
                 ]}
            ]}]
        }
    }
    with patch.object(verifier, '_query_batch_extrinsic', return_value=AlphaPaymentVerificationResult(
        is_valid=True, memo="xfer-123:t1", amount_alpha=0.5, recipient_coldkey="5Cold..."
    )):
        result = verifier.verify_alpha_payment(
            tx_hash="0xabc:0xdef",
            expected_transfer_id="xfer-123:t1",
            expected_worker_coldkey="5Cold...",
            min_amount_alpha=0.0005,
        )
    assert result.is_valid
```

---

## Root Cause of NULL `tx_hash`

1. **Immediate path:** `transfer_alpha_with_memo` returns `None` on any exception (line ~748). When this happens, `pay_worker_immediately` queues the payment but does **not** write to the DB or BeamCore. The retry queue is the only record.
2. **Retry path:** The retry queue is broken (CRITICAL-1 / CRITICAL-2). It either:
   - Never runs because the TAO balance check is wrong (HIGH-1).
   - Runs but emits a legacy TAO transfer with a synthetic fallback `tx_hash` (line 575) when hash extraction fails.
3. **Synthetic hashes:** The fallback string `f"retry:{hotkey[:8]}:{payment_dest[:8]}:{int(time.time())}"` is **not** a real blockchain hash. Validators skip it (does not start with `0x`), but BeamCore may store it as a placeholder. If the orchestrator crashes before the retry succeeds, the payment record in BeamCore has no valid on-chain evidence.
4. **Validator slashes:** Even when a valid ALPHA `tx_hash` is produced, the validator rejects it (CRITICAL-4 / CRITICAL-5), so orchestrators learn that payments “fail verification” and may stop submitting real hashes, leaving the field NULL.

---

## Recommended Priority Order

1. **CRITICAL-4 + CRITICAL-5** — Fix validator to use `AlphaPaymentVerifier` for ALPHA payments. Without this, every orchestrator paying correctly will be slashed.
2. **CRITICAL-1 + CRITICAL-2** — Rewrite retry queue to use `transfer_alpha_with_memo` with consistent ALPHA units.
3. **CRITICAL-3** — Add bytes-to-hex conversion in `transfer_alpha_with_memo`.
4. **HIGH-4** — Fix `TxVerifier` sender check to skip when `expected_from` is empty.
5. **HIGH-3** — Import real merkle tree in `epoch_manager.py`.
6. **HIGH-5 + HIGH-6** — Fix verifier defaults and hex remark parsing.
7. **MEDIUM-4** — Resolve `worker_coldkey` in validator for recipient checks.

---

*End of Audit.*
