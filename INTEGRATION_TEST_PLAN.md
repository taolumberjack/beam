# BEAM SN105 Payment System Patches — Integration Test Plan

**Prepared by:** Integration Tester Subagent  
**Date:** 2026-04-22  
**Scope:** reward_manager_retry_fix.py, validator_alpha_verifier.py, tx_verifier_empty_sender_fix.py  
**Target Networks:** SN304 (testnet), SN105 (mainnet)

---

## 1. EXECUTIVE SUMMARY

Three critical patches fix BEAM SN105 payment system bugs:
1. **Retry queue** was using legacy TAO `subtensor.transfer()` instead of ALPHA `transfer_stake`
2. **Validator** was routing all payments through legacy `TxVerifier`, rejecting ALPHA `batch_all`
3. **tx_hash** had bytes vs string formatting issues

This plan identifies integration risks and provides a structured path from testnet validation to mainnet deployment.

---

## 2. PRE-DEPLOYMENT CHECKLIST

### 2.1 Environment & Dependencies
| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1 | Bittensor SDK >= 8.x installed | ☐ | Current `pyproject.toml` pins `bittensor>=7.0.0`. **Must upgrade to >=8.x** before patches. `transfer_stake` API may differ between v7 and v8. |
| 2 | Substrate interface available (`subtensor.substrate`) | ☐ | Required by both `transfer_alpha_with_memo()` and `AlphaPaymentVerifier`. Verify `substrate` is not `None`. |
| 3 | SubnetCore API client operational | ☐ | Patches depend on `subnet_core_client.get_task_payment_address()`, `record_pob_payment()`, `record_worker_payment()`. |
| 4 | Wallet coldkey funded with ALPHA stake | ☐ | Retry logic now checks `ALPHA stake` balance, not TAO free balance. |
| 5 | Validator wallet has subtensor connection | ☐ | `AlphaPaymentVerifier` and `TxVerifier` both require `self.subtensor` to be initialized. |

### 2.2 Code Compatibility
| # | Check | Status | Notes |
|---|-------|--------|-------|
| 6 | `AlphaPaymentVerifier` class exists in `chain/tx_verifier.py` | ☐ | Verify the class is imported in `validator.py`: `from chain.tx_verifier import TxVerifier, TxVerificationResult, AlphaPaymentVerifier`. |
| 7 | `_format_tx_hash()` helper added to `RewardManager` | ☐ | Must exist before patch application to avoid `AttributeError`. |
| 8 | `_queue_failed_payment()` signature updated everywhere | ☐ | Callers at lines ~299, ~338, ~350 must pass `amount_alpha` and `transfer_id`. |
| 9 | `_resolve_worker_coldkey()` exists and is async | ☐ | Used by retry queue for coldkey resolution fallback. |
| 10 | `TxVerificationResult` supports `from_address`, `to_address`, `amount_tao` fields | ☐ | Patched error paths assign these fields. |

### 2.3 Configuration & Secrets
| # | Check | Status | Notes |
|---|-------|--------|-------|
| 11 | `NETUID` env var set correctly (304 for testnet, 105 for mainnet) | ☐ | Hard-coded default `105` in some calls; must be overridden via config. |
| 12 | `SUBNET_CORE_URL` points to correct environment | ☐ | `beamcore-dev.b1m.ai` (testnet) vs `beamcore.b1m.ai` (mainnet). |
| 13 | `BEAM_VALIDATOR_SUBNET_CORE_URL` set (validator) | ☐ | Validator uses prefixed env var. |
| 14 | `REGISTRY_URL` matches `SUBNET_CORE_URL` (orchestrator) | ☐ | Orchestrator uses unprefixed `REGISTRY_URL`. |

---

## 3. DETAILED INTEGRATION ISSUES FOUND

### 3.1 Database Schema — NO MIGRATIONS REQUIRED
- **Finding:** No DB schema changes needed.
- **Rationale:**
  - Retry queue is an in-memory Python list (`self._payment_retry_queue`), not a DB table.
  - Payment records sent to SubnetCore API use existing `WorkerPaymentData` dataclass fields.
  - `reward_tao` was never persisted to DB; it was only a runtime dict key.
- **Action:** None. Existing DB tables remain compatible.

### 3.2 SubnetCore API — POTENTIAL BREAKING CHANGES
| Endpoint / Method | Risk | Details |
|-------------------|------|---------|
| `get_task_payment_address(task_id)` | **Low** | Already exists in `subnet_core_client.py`. Returns `{"address": ...}` |
| `record_pob_payment(task_id, tx_hash, amount_rao)` | **Low** | Already exists. Patches call it with `amount_rao` (int). |
| `record_worker_payment(WorkerPaymentData)` | **Medium** | Dataclass includes `amount_earned` (int, nano). Patch changes semantic meaning from TAO-nano to ALPHA-nano. **Ensure SubnetCore backend handles ALPHA units.** |
| `get_verified_proofs_for_payment_verification(limit=500)` | **Medium** | **NEW API METHOD** in validator patch. Must be implemented on SubnetCore backend before validator patch works. Returns `{"proofs": [...], "payments": [...]}`. |

**Action:** Coordinate with SubnetCore team to deploy `get_verified_proofs_for_payment_verification()` endpoint BEFORE validator patch goes live.

### 3.3 Bittensor SDK Compatibility — REQUIRES UPGRADE
| SDK Version | `transfer_stake` | `batch_all` | `remark_with_event` | Verdict |
|-------------|------------------|-------------|---------------------|---------|
| 7.x | May not exist | May not exist | May not exist | **UNSUPPORTED** |
| 8.x | Available | Available | Available | **REQUIRED** |

**Finding:** `pyproject.toml` pins `bittensor>=7.0.0`. Patches use:
- `subtensor.get_stake_for_coldkey_and_hotkey()` — added in SDK 8.x
- `substrate.compose_call(module='SubtensorModule', call_function='transfer_stake', ...)` — chain-level call, but SDK 8.x exposes better helpers
- `substrate.compose_call(module='Utility', call_function='batch_all', ...)` — chain-level, should work if substrate interface is available

**Risk:** If SDK 7.x is used, `get_stake_for_coldkey_and_hotkey` may raise `AttributeError`, causing retry queue to fall back to `get_balance()` (TAO), which is wrong for ALPHA payments.

**Action:**
1. Update `pyproject.toml`: `bittensor>=8.0.0`
2. Pin a specific tested version: `bittensor==8.x.y`
3. Run `pip install --upgrade bittensor` in testnet environment first.

### 3.4 Worker Compatibility — NO CHANGES REQUIRED
- **Finding:** Workers are unaffected.
- **Rationale:** Workers submit proofs and receive payments via SubnetCore. They don't interact with retry queue or validator payment verification directly.
- **Action:** None. Workers will continue to connect as before.

### 3.5 Config Changes — MINOR ADDITIONS
| Config Key | File | Required? | Default | Notes |
|------------|------|-----------|---------|-------|
| `netuid` | `config/*.yaml` | Yes | `105` | Must be `304` for testnet. Already configurable via env. |
| `alpha_per_chunk` | `reward_manager.py` | No | `0.5` | Hard-coded in function signature. Consider adding to config. |
| `min_amount_alpha` | `validator.py` | No | `0.4` | Hard-coded in `alpha_verifier.verify_alpha_payment()`. Consider adding to config. |

**Recommendation:** Make `alpha_per_chunk` and `min_amount_alpha` configurable via `OrchestratorSettings` and `Settings` rather than hard-coding.

### 3.6 Environment Variables — NO NEW VARS REQUIRED
- **Finding:** No new environment variables are introduced by the patches.
- **Existing vars used:**
  - `NETUID`, `BEAM_NETUID`
  - `SUBNET_CORE_URL`, `BEAM_VALIDATOR_SUBNET_CORE_URL`
  - `WALLET_NAME`, `WALLET_HOTKEY`
- **Action:** Verify existing `.env` files are correct for target network.

### 3.7 Rollback Safety — PARTIAL ROLLBACK POSSIBLE
| Component | Rollback Difficulty | Notes |
|-----------|---------------------|-------|
| `reward_manager.py` retry fix | **Medium** | Retry queue items in memory are lost on restart. If rolled back, in-flight ALPHA retries would revert to TAO logic, but queue contents (ALPHA amounts) would mismatch old TAO logic. **Drain retry queue before rollback.** |
| `validator.py` alpha verifier | **Easy** | Reverting import and routing logic is straightforward. No persistent state changed. |
| `tx_verifier.py` bytes fix | **Easy** | Pure logic change, no state. Safe to revert. |

**Action:**
1. Before deploying, ensure retry queue is empty (`len(_payment_retry_queue) == 0`).
2. Take Git tag/branch snapshot: `git tag pre-alpha-payment-patches-$(date +%s)`
3. Keep old branch alive for 48h post-deployment.

---

## 4. HARDENING ISSUES & RECOMMENDATIONS

### 4.1 Hardcoded Values That Should Be Configurable
| Location | Value | Recommended Config Key |
|----------|-------|------------------------|
| `validator_alpha_verifier.py` | `min_amount_alpha=0.4` | `validator.min_alpha_payment` |
| `reward_manager_retry_fix.py` | `alpha_per_chunk=0.5` | `orchestrator.alpha_per_chunk` |
| `reward_manager_retry_fix.py` | `MIN_CHAIN_TRANSFER = 5e-7` | `orchestrator.min_chain_transfer_tao` (legacy fallback only) |
| `reward_manager_retry_fix.py` | `MIN_TRANSFER_RAO = 500_000` | `orchestrator.min_alpha_transfer_rao` |
| `reward_manager_retry_fix.py` | `_max_payment_retries = 5` | Already exists as class attr, but could be config-driven |

### 4.2 TODO / FIXME Comments in Patches
- **Finding:** No `TODO`, `FIXME`, `HACK`, or `XXX` comments found in patch files.
- **However:** In `validator.py` (original source, line ~1190), there is a pre-existing TODO:  
  `# TODO: Get orchestrator coldkey from metagraph or payment record`  
  This is addressed by the patch's `_resolve_worker_coldkey_from_payment()` helper.
- **Action:** Remove the pre-existing TODO comment after patch application.

### 4.3 Error Message Descriptiveness
| Patch | Error Message Quality | Recommendation |
|-------|----------------------|----------------|
| `reward_manager_retry_fix.py` | Good | Includes amounts, addresses (truncated), attempt counts. ✅ |
| `validator_alpha_verifier.py` | Good | Distinguishes ALPHA vs TAO verification paths. Includes `verification.error`. ✅ |
| `tx_verifier_empty_sender_fix.py` | Good | `_safe_hex_str()` prevents cryptic bytes errors. ✅ |

### 4.4 Race Conditions in New Retry Logic
| Scenario | Risk | Mitigation |
|----------|------|------------|
| **Double payment via retry + immediate pay** | **Medium** | `_paid_task_ids` dedup set guards against this. Both paths check `task_id in self._paid_task_ids` before paying. ✅ |
| **Concurrent retry queue processing** | **Low** | `process_payment_retry_queue()` is async but not explicitly locked. If called from multiple tasks, concurrent modification of `_payment_retry_queue` and `_paid_task_ids` could occur. | **Recommendation:** Add an `asyncio.Lock` around queue mutation in `process_payment_retry_queue()`. |
| **Balance check vs actual transfer race** | **Low** | ALPHA stake balance is checked once at queue start. Another process could consume stake before transfer completes. | **Recommendation:** Re-check balance immediately before `transfer_alpha_with_memo()` call, or catch insufficient balance errors gracefully. |
| **Bytes tx_hash race in multiple validators** | **Very Low** | `_safe_hex_str()` normalizes hash format. Independent of timing. ✅ |

---

## 5. TESTNET TESTING STEPS (SN304)

### 5.1 Environment Setup
```bash
# 1. Verify testnet config
export NETUID=304
export BEAM_NETUID=304
export SUBTENSOR_NETWORK=test
export SUBNET_CORE_URL=https://beamcore-dev.b1m.ai
export BEAM_VALIDATOR_SUBNET_CORE_URL=https://beamcore-dev.b1m.ai

# 2. Upgrade bittensor
pip install --upgrade "bittensor>=8.0.0"
python -c "import bittensor as bt; print(bt.__version__)"  # Should be 8.x

# 3. Verify SDK has required methods
python -c "
import bittensor as bt
st = bt.Subtensor(network='test')
assert hasattr(st, 'get_stake_for_coldkey_and_hotkey'), 'Missing get_stake_for_coldkey_and_hotkey'
print('SDK OK')
"
```

### 5.2 Orchestrator Patch Tests
```bash
# 4. Apply reward_manager_retry_fix.py patch
cd neurons/orchestrator/core
# (Apply patch via git apply or manual edit)

# 5. Run orchestrator in testnet mode with test wallet
python main.py
```

| Step | Test | Expected Result |
|------|------|---------------|
| 5.2.1 | Submit a task, let immediate ALPHA payment succeed | `ALPHA payment SUCCESS` log. `tx_hash` format: `0x...:0x...`. `_paid_task_ids` contains task_id. |
| 5.2.2 | Submit a task with insufficient ALPHA stake | `Insufficient balance` log. Item queued in `_payment_retry_queue` with `amount_alpha` (not `reward_tao`). |
| 5.2.3 | Verify `_format_tx_hash()` handles bytes | If SDK returns bytes for `extrinsic_hash`, log shows `0x...` hex string, not `<bytes object>`. |
| 5.2.4 | Verify retry queue processes when stake available | Fund wallet with ALPHA. Retry queue processes. `Retry payment SUCCESS` log. SubnetCore `record_pob_payment` called with correct `amount_rao`. |
| 5.2.5 | Verify retry dedup | After retry succeeds, same task_id queued again is skipped with `DEDUP` log. |
| 5.2.6 | Verify queue expiration | After 5 failed attempts, item removed with `Payment retry EXHAUSTED` log. |

### 5.3 Validator Patch Tests
```bash
# 6. Apply validator_alpha_verifier.py and tx_verifier_empty_sender_fix.py patches
cd neurons/validator/core
# (Apply patches)

# 7. Run validator in testnet mode
python main.py
```

| Step | Test | Expected Result |
|------|------|---------------|
| 5.3.1 | Verify `AlphaPaymentVerifier` is imported | No `ImportError` on startup. |
| 5.3.2 | Validator fetches verified proofs from SubnetCore | `_verify_orchestrator_payments()` runs. Calls `get_verified_proofs_for_payment_verification()`. |
| 5.3.3 | ALPHA payment verification path | For `batch_all` tx_hash, `alpha_verifier.verify_alpha_payment()` called. Memo and recipient checked. |
| 5.3.4 | Legacy TAO payment verification path | For non-ALPHA payments, `tx_verifier.verify_transfer()` called with `expected_from=""`. No sender mismatch error. |
| 5.3.5 | Invalid ALPHA tx_hash triggers penalty | `SLASHING orchestrator ... by 50%` log. `payment_penalty_multipliers[orch_hotkey]` = 0.5. |
| 5.3.6 | Valid ALPHA tx_hash passes | No penalty applied. `Verified ALPHA payment` debug log. |
| 5.3.7 | Bytes tx_hash handling | Submit tx_hash where SDK returns bytes. `_safe_hex_str()` normalizes to hex string. Verification proceeds without `TypeError`. |

### 5.4 End-to-End Payment Flow Test
| Step | Action | Check |
|------|--------|-------|
| 5.4.1 | Worker completes task | Proof submitted to SubnetCore. |
| 5.4.2 | Orchestrator pays worker ALPHA | `transfer_alpha_with_memo()` succeeds. On-chain tx visible in block explorer. |
| 5.4.3 | Validator verifies payment | Validator calls `AlphaPaymentVerifier.verify_alpha_payment()`. Memo matches `expected_memo`. Recipient matches `worker_coldkey`. |
| 5.4.4 | Validator sets weights | Weights reflect payment verification. Orchestrator with invalid payments has penalty multiplier < 1.0. |

---

## 6. MAINNET DEPLOYMENT STEPS (SN105)

### 6.1 Pre-Flight (Do NOT Skip)
```bash
# 1. Confirm testnet validation complete
# All 5.2.x and 5.3.x tests must pass.

# 2. Switch to mainnet env
export NETUID=105
export BEAM_NETUID=105
export SUBTENSOR_NETWORK=finney
export SUBNET_CORE_URL=https://beamcore.b1m.ai
export BEAM_VALIDATOR_SUBNET_CORE_URL=https://beamcore.b1m.ai

# 3. Verify mainnet wallet has sufficient ALPHA stake
python -c "
import bittensor as bt
w = bt.Wallet(name='orchestrator', hotkey='default')
st = bt.Subtensor(network='finney')
stake = st.get_stake_for_coldkey_and_hotkey(w.coldkey.ss58_address, w.hotkey.ss58_address, 105)
print(f'ALPHA stake: {float(stake)}')
"

# 4. Git tag the release
git tag -a v0.x.x-alpha-patches -m "ALPHA payment patches for SN105"
git push origin v0.x.x-alpha-patches
```

### 6.2 Deployment Order
1. **SubnetCore Backend** — Deploy `get_verified_proofs_for_payment_verification()` endpoint to mainnet BeamCore.
2. **Orchestrators** — Deploy `reward_manager_retry_fix.py`. Restart orchestrators during low-traffic window.
3. **Validators** — Wait 1 epoch (~360 blocks) after orchestrator deployment. Deploy `validator_alpha_verifier.py` + `tx_verifier_empty_sender_fix.py`.
4. **Monitor** — Watch logs for 2 epochs (see Section 7).

### 6.3 Deployment Window
- **Preferred:** During epoch boundary (just after weights set) to minimize in-flight payment disruption.
- **Avoid:** Mid-epoch when retry queue may have items.

---

## 7. ROLLBACK PROCEDURE

### 7.1 Trigger Conditions
- Payment success rate drops > 20% for 2 consecutive epochs
- Validators log repeated `ALPHA payment FAILED` or `Invalid ALPHA tx` at > 10% rate
- SubnetCore API returns 500s for `get_verified_proofs_for_payment_verification()`
- Any orchestrator reports `reward_tao` KeyError (patch not fully applied)

### 7.2 Rollback Steps
```bash
# 1. Stop affected services
systemctl stop beam-orchestrator  # or docker stop / kill process
systemctl stop beam-validator

# 2. Revert to pre-patch tag
git checkout v0.x.x-pre-alpha-patches  # or pre-patch branch

# 3. IMPORTANT: Clear retry queues before restart
# (Queue is in-memory; restart clears it automatically. Lost payments must be manually reconciled.)

# 4. Restart services
systemctl start beam-orchestrator
systemctl start beam-validator

# 5. Verify TAO payments resume
# Check logs for "Retry payment SUCCESS: ... TAO" (legacy path)
```

### 7.3 Post-Rollback Reconciliation
- Any tasks paid during patch window with ALPHA tx_hashes will have those tx_hashes stored in SubnetCore.
- Post-rollback, validators will attempt TAO verification on ALPHA tx_hashes → will fail.
- **Action:** Manually mark those epoch payments as verified in SubnetCore DB, or accept temporary penalty noise.

---

## 8. MONITORING CHECKLIST POST-DEPLOYMENT

### 8.1 Orchestrator Metrics (Check every 15 min for 2 hours)
| Metric | Command / Log Pattern | Healthy Threshold |
|--------|----------------------|-------------------|
| Retry queue size | `grep "queue size"` | < 10 items |
| Immediate payment success rate | `grep "ALPHA payment SUCCESS"` / total tasks | > 95% |
| Retry payment success rate | `grep "Retry payment SUCCESS"` / total retries | > 90% |
| Balance check failures | `grep "Could not check ALPHA stake"` | 0 |
| tx_hash format errors | `grep "bytes" | grep "tx_hash"` | 0 |

### 8.2 Validator Metrics (Check every 15 min for 2 hours)
| Metric | Command / Log Pattern | Healthy Threshold |
|--------|----------------------|-------------------|
| ALPHA verification pass rate | `grep "Verified ALPHA payment"` / total verifications | > 95% |
| TAO verification pass rate | `grep "Verified TAO payment"` / total verifications | > 95% (legacy) |
| Penalty slashes | `grep "SLASHING orchestrator"` | < 5% of orchestrators |
| Import errors | `grep "ImportError" | grep "AlphaPaymentVerifier"` | 0 |
| Bytes handling errors | `grep "_safe_hex_str" | grep "error"` | 0 |

### 8.3 On-Chain Metrics
| Metric | How to Check | Healthy Threshold |
|--------|-------------|-------------------|
| `batch_all` extrinsics visible | Block explorer / subscan | > 0 per epoch |
| `transfer_stake` in batch | Decode extrinsics | Present in all payment batches |
| `remark_with_event` memo | Decode extrinsics | Matches `{transfer_id}:{task_id}` format |

### 8.4 SubnetCore API Metrics
| Metric | Endpoint | Healthy Threshold |
|--------|----------|-------------------|
| `get_verified_proofs_for_payment_verification` latency | `GET /validators/payments/verified` | < 2s |
| `record_pob_payment` success rate | `POST /orchestrators/payments/pob` | > 99% |
| `record_worker_payment` success rate | `POST /orchestrators/payments/worker` | > 99% |

---

## 9. KNOWN RISKS AND MITIGATIONS

| Risk ID | Risk | Likelihood | Impact | Mitigation |
|---------|------|------------|--------|------------|
| R1 | Bittensor SDK 8.x `get_stake_for_coldkey_and_hotkey` unavailable or behavior differs | Medium | High | Test on testnet first. Fallback to `get_balance()` exists but is wrong for ALPHA. If SDK method fails, retry queue stalls. **Mitigation:** Pin exact SDK version after testnet validation. |
| R2 | SubnetCore backend does not implement `get_verified_proofs_for_payment_verification()` | Medium | High | Validator patch will crash or skip all payment verification. **Mitigation:** Deploy backend endpoint BEFORE validator patch. |
| R3 | `transfer_stake` call parameters differ on mainnet vs testnet | Low | High | `origin_netuid` and `destination_netuid` parameters may have chain-specific behavior. **Mitigation:** Verify exact call parameters against mainnet metadata. |
| R4 | Retry queue contains old TAO-amount items after patch | Low | Medium | If orchestrator is patched with non-empty queue, old items have `reward_tao` key, but new code reads `amount_alpha`. **Mitigation:** Drain queue before patching, or add backward-compat code to read both keys. |
| R5 | Race condition: concurrent retry queue processing | Low | Medium | Multiple async tasks could process the same queue item. **Mitigation:** Add `asyncio.Lock` around `process_payment_retry_queue()`. |
| R6 | `alpha_per_chunk` hard-coded at 0.5 ALPHA — if ALPHA price spikes, payments become expensive | Low | Medium | Orchestrator may exhaust ALPHA stake faster than expected. **Mitigation:** Make `alpha_per_chunk` configurable and expose via SubnetCore network config. |
| R7 | Validator `min_amount_alpha=0.4` hard-coded — if `alpha_per_chunk` is reduced, validator may reject valid payments | Low | Medium | Mismatch between orchestrator payment amount and validator minimum. **Mitigation:** Sync `min_amount_alpha` with `alpha_per_chunk` via SubnetCore config API. |
| R8 | `worker_coldkey` resolution fails for new workers not yet in metagraph | Medium | Medium | `transfer_alpha_with_memo()` requires coldkey. If not in metagraph, payment fails. **Mitigation:** SubnetCore `get_task_payment_address()` already resolves coldkey. Ensure this is reliable. |
| R9 | `batch_all` extrinsic fails but `remark_with_event` succeeds, leaving orphan memo | Low | Low | If `transfer_stake` fails in batch, entire batch is reverted (atomic). No orphan memos. ✅ |
| R10 | Rollback leaves ALPHA tx_hashes in SubnetCore that legacy TAO verifier cannot validate | Low | Medium | Temporary penalty noise for 1-2 epochs. **Mitigation:** Document and accept, or manually verify affected payments. |

---

## 10. APPENDIX

### A. Patch Application Commands
```bash
# From repo root
# 1. Orchestrator patch
git apply patches/reward_manager_retry_fix.py --check  # dry-run first
git apply patches/reward_manager_retry_fix.py

# 2. Validator patches
git apply patches/validator_alpha_verifier.py --check
git apply patches/validator_alpha_verifier.py
git apply patches/tx_verifier_empty_sender_fix.py --check
git apply patches/tx_verifier_empty_sender_fix.py
```

### B. Quick Verification Script
```python
#!/usr/bin/env python3
"""Quick post-patch sanity check."""
import sys

def check():
    errors = []

    # 1. Check SDK version
    import bittensor as bt
    major = int(bt.__version__.split('.')[0])
    if major < 8:
        errors.append(f"Bittensor SDK {bt.__version__} < 8.x required")

    # 2. Check AlphaPaymentVerifier importable
    try:
        from neurons.validator.chain.tx_verifier import AlphaPaymentVerifier
    except ImportError as e:
        errors.append(f"AlphaPaymentVerifier import failed: {e}")

    # 3. Check _format_tx_hash exists
    from neurons.orchestrator.core.reward_manager import RewardManager
    if not hasattr(RewardManager, '_format_tx_hash'):
        errors.append("RewardManager missing _format_tx_hash")

    # 4. Check _queue_failed_payment signature
    import inspect
    sig = inspect.signature(RewardManager._queue_failed_payment)
    params = list(sig.parameters.keys())
    if 'amount_alpha' not in params or 'transfer_id' not in params:
        errors.append(f"_queue_failed_payment signature wrong: {params}")

    if errors:
        print("FAILURES:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("All checks passed ✅")

if __name__ == "__main__":
    check()
```

### C. Contact / Escalation
- **SubnetCore API issues:** Backend team — verify `get_verified_proofs_for_payment_verification()` endpoint.
- **Bittensor SDK issues:** Verify SDK 8.x compatibility with `transfer_stake` and `get_stake_for_coldkey_and_hotkey`.
- **On-chain verification issues:** Check `SubtensorModule.transfer_stake` call parameter names against chain metadata.

---

*End of Integration Test Plan*
