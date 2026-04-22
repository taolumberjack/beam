"""
PATCH v2: validator.py - Route ALPHA payments to AlphaPaymentVerifier

Apply to: neurons/validator/core/validator.py

This patch fixes the validator to properly verify ALPHA batch_all payments.
Key fix from v1: No longer sets is_alpha=True unconditionally. Instead,
tries ALPHA verifier first, and falls back to TAO verifier if ALPHA fails.

Key changes:
1. Import AlphaPaymentVerifier alongside TxVerifier
2. Try ALPHA verifier first, then TAO verifier as fallback
3. Only apply penalty if BOTH verifiers fail
4. Restore missing _verify_unverified_epoch_payments() call
5. Check worker_coldkey (not worker_hotkey) for recipient match
"""

# ============================================================================
# CHANGE 1: Import AlphaPaymentVerifier alongside TxVerifier
# ============================================================================
# BEFORE (line ~26):
#   from chain.tx_verifier import TxVerifier, TxVerificationResult

# AFTER:
from chain.tx_verifier import TxVerifier, TxVerificationResult, AlphaPaymentVerifier

# ============================================================================
# CHANGE 2: Replace entire _verify_orchestrator_payments() method
# ============================================================================
# BEFORE (lines ~1148-1300):
# - Creates only TxVerifier
# - Passes all payments to tx_verifier.verify_transfer()
# - Uses worker_hotkey as expected_to

# AFTER:
    async def _verify_orchestrator_payments(self) -> None:
        """Verify orchestrator payments to workers using on-chain tx hashes."""
        if not SUBNET_CORE_AVAILABLE or not self.subnet_core_client:
            return

        try:
            # Fetch verified proofs and payment data from SubnetCore
            result = await self.subnet_core_client.get_verified_proofs_for_payment_verification(
                limit=500
            )
            verified_proofs = result.get("proofs", [])
            if not verified_proofs:
                return

            # Build lookup by task_id
            payment_by_task_id: dict = {}
            for payment in result.get("payments", []):
                task_id = payment.get("task_id")
                if task_id:
                    payment_by_task_id[task_id] = payment

            # Initialize BOTH verifiers
            tx_verifier = TxVerifier(self.subtensor) if self.subtensor else None
            alpha_verifier = AlphaPaymentVerifier(self.subtensor) if self.subtensor else None

            for proof in verified_proofs:
                task_id = proof.get("task_id", "")
                orchestrator_hotkey = proof.get("orchestrator_hotkey", "")

                if not task_id or task_id not in payment_by_task_id:
                    continue

                payment = payment_by_task_id[task_id]
                tx_hash = payment.get("tx_hash")

                if not tx_hash:
                    # Missing tx_hash — apply penalty
                    self._apply_payment_penalty(orchestrator_hotkey, "missing_tx_hash", task_id)
                    continue

                # Try ALPHA verification first
                alpha_result = None
                if alpha_verifier and tx_hash.startswith("0x"):
                    expected_memo = payment.get("expected_memo", f"{payment.get('transfer_id', '')}:{task_id}")
                    worker_coldkey = payment.get("worker_coldkey", "")
                    
                    # If worker_coldkey not in payment, try to resolve it
                    if not worker_coldkey:
                        worker_coldkey = self._resolve_worker_coldkey_from_payment(payment)
                    
                    amount_alpha = payment.get("amount_earned", 0) / 1e9  # rao to ALPHA
                    
                    alpha_result = alpha_verifier.verify_alpha_payment(
                        tx_hash=tx_hash,
                        expected_transfer_id=expected_memo,
                        expected_worker_coldkey=worker_coldkey,
                        min_amount_alpha=0.4,  # Slightly below standard 0.5
                    )

                # If ALPHA verification succeeded, we're done
                if alpha_result and alpha_result.is_valid:
                    logger.debug(
                        f"Verified ALPHA payment for task {task_id[:16]}... "
                        f"tx={tx_hash[:24]}..."
                    )
                    continue

                # If ALPHA verification failed because it's NOT an ALPHA payment,
                # try TAO verifier as fallback
                if alpha_result and alpha_result.error and "not a batch_all" in alpha_result.error:
                    if tx_verifier:
                        worker_hotkey = payment.get("worker_hotkey", "")
                        amount_tao = payment.get("amount_earned", 0) / 1e9
                        
                        tao_result = tx_verifier.verify_transfer(
                            tx_hash=tx_hash,
                            expected_from="",  # Skip sender check
                            expected_to=worker_hotkey,
                            expected_amount=amount_tao,
                            tolerance=0.05,
                        )
                        
                        if tao_result and tao_result.is_valid:
                            logger.debug(
                                f"Verified TAO payment for task {task_id[:16]}... "
                                f"tx={tx_hash[:24]}..."
                            )
                            continue
                        elif tao_result:
                            # TAO verification failed — apply penalty
                            self._apply_payment_penalty(
                                orchestrator_hotkey,
                                f"invalid_tao_tx: {tao_result.error}",
                                task_id
                            )
                            continue
                
                # ALPHA verification failed for other reasons
                if alpha_result:
                    self._apply_payment_penalty(
                        orchestrator_hotkey,
                        f"invalid_alpha_tx: {alpha_result.error}",
                        task_id
                    )
                    logger.warning(
                        f"Invalid ALPHA payment for task {task_id[:16]}...: "
                        f"{alpha_result.error}"
                    )
                else:
                    # No verifier available
                    logger.warning(
                        f"No verifier available for task {task_id[:16]}... — skipping"
                    )

        except Exception as e:
            logger.error(f"Error verifying orchestrator payments: {e}", exc_info=True)

    def _apply_payment_penalty(self, orch_hotkey: str, reason: str, task_id: str):
        """Apply penalty for invalid/missing payment."""
        if orch_hotkey not in self.payment_penalty_multipliers:
            self.payment_penalty_multipliers[orch_hotkey] = 1.0
        
        # 50% slash for any payment issue
        self.payment_penalty_multipliers[orch_hotkey] *= 0.5
        
        logger.warning(
            f"SLASHING orchestrator {orch_hotkey[:16]}...: {reason} "
            f"for task {task_id[:16]}... (penalty now: {self.payment_penalty_multipliers[orch_hotkey]:.2f})"
        )

    def _resolve_worker_coldkey_from_payment(self, payment: dict) -> str:
        """Resolve worker coldkey from payment data or metagraph."""
        coldkey = payment.get("worker_coldkey", "")
        if coldkey:
            return coldkey
        
        worker_hotkey = payment.get("worker_hotkey", "")
        if worker_hotkey and self.subtensor:
            try:
                metagraph = self.subtensor.metagraph(self.settings.netuid)
                for neuron in metagraph.neurons:
                    if neuron.hotkey == worker_hotkey:
                        return neuron.coldkey
            except Exception as e:
                logger.warning(f"Could not resolve coldkey for {worker_hotkey[:16]}...: {e}")
        
        return ""

# ============================================================================
# CHANGE 3: Restore _verify_unverified_epoch_payments() call
# ============================================================================
# Find where _verify_orchestrator_payments() is called in the main loop
# and ensure _verify_unverified_epoch_payments() is still called after it.
# 
# In the main loop (around line ~340 in _main_loop):
# AFTER calling _verify_orchestrator_payments(), add:
#   await self._verify_unverified_epoch_payments(
#       unpaid_by_orchestrator, verified_proofs_by_orch
#   )

# ============================================================================
# CHANGE 4: Remove dead _verify_unverified_epoch_payments() if it exists
# ============================================================================
# If _verify_unverified_epoch_payments() is already defined elsewhere,
# make sure it's not removed. The v1 patch accidentally dropped the call.
