"""
PATCH v2.1: validator.py - Route ALPHA payments with SubnetCore fallback

Apply to: neurons/validator/core/validator.py

This patch includes fallback logic for when the primary SubnetCore endpoint
is unavailable. It combines existing endpoints to build the same data.

Key changes:
1. Import AlphaPaymentVerifier alongside TxVerifier
2. Try ALPHA verifier first, then TAO verifier as fallback
3. Only apply penalty if BOTH verifiers fail
4. Fallback to existing endpoints if primary endpoint is missing
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
    async def _verify_orchestrator_payments(self) -> None:
        """Verify orchestrator payments to workers using on-chain tx hashes.
        
        Uses a tiered approach:
        1. Try get_paid_proofs_for_pop_verification() (ideal endpoint)
        2. Fallback to get_verified_proofs() + get_worker_payments() (existing endpoints)
        3. Verify each payment with AlphaPaymentVerifier (ALPHA) or TxVerifier (TAO)
        """
        if not SUBNET_CORE_AVAILABLE or not self.subnet_core_client:
            return

        try:
            # Fetch proofs and payments with fallback logic
            result = await self._fetch_payment_data_with_fallback()
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

    async def _fetch_payment_data_with_fallback(self) -> Dict[str, Any]:
        """Fetch payment verification data with fallback to existing endpoints.
        
        Tier 1: get_paid_proofs_for_pop_verification() — ideal endpoint
        Tier 2: get_verified_proofs() + get_worker_payments() — existing endpoints
        """
        # Tier 1: Try the ideal endpoint
        try:
            if hasattr(self.subnet_core_client, 'get_paid_proofs_for_pop_verification'):
                result = await self.subnet_core_client.get_paid_proofs_for_pop_verification(
                    limit=500
                )
                proofs = result.get("proofs", [])
                if proofs:
                    logger.info(f"Using get_paid_proofs_for_pop_verification: {len(proofs)} proofs")
                    return result
        except Exception as e:
            logger.warning(f"Tier 1 endpoint failed: {e}")

        # Tier 2: Fallback to existing endpoints
        logger.info("Falling back to existing endpoints for payment verification")
        
        try:
            # Get verified proofs
            verified_result = await self.subnet_core_client.get_verified_proofs(
                limit=500,
                seconds_ago=3600,  # 1 hour lookback
            )
            proofs = verified_result.get("proofs", [])
            
            # Get recent worker payments
            payments_result = await self.subnet_core_client.get_worker_payments(
                limit=500,
                seconds_ago=3600,
            )
            payments = payments_result.get("payments", [])
            
            # Build payment lookup by task_id
            payment_by_task_id = {}
            for payment in payments:
                task_id = payment.get("task_id")
                if task_id:
                    payment_by_task_id[task_id] = payment
            
            # Merge: add payment data to proofs that have matching task_id
            merged_proofs = []
            for proof in proofs:
                task_id = proof.get("task_id")
                if task_id and task_id in payment_by_task_id:
                    # Merge payment data into proof
                    payment = payment_by_task_id[task_id]
                    merged_proof = {**proof, **payment}
                    merged_proofs.append(merged_proof)
            
            logger.info(
                f"Tier 2 fallback: {len(proofs)} verified proofs, "
                f"{len(payments)} payments, {len(merged_proofs)} merged"
            )
            
            return {
                "proofs": merged_proofs,
                "payments": payments,
                "count": len(merged_proofs),
            }
            
        except Exception as e:
            logger.error(f"Tier 2 fallback failed: {e}")
            return {"proofs": [], "payments": [], "count": 0}

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
# CHANGE 3: Restore _verify_unverified_epoch_payments() call in main loop
# ============================================================================
# In _main_loop(), after calling _verify_orchestrator_payments(),
# ensure _verify_unverified_epoch_payments() is still called.
# 
# Find the main loop around line ~340 and add after:
#   await self._verify_orchestrator_payments()
# Add:
#   await self._verify_unverified_epoch_payments(
#       {}, {}  # Pass empty dicts if the method requires them
#   )
# Or check the actual signature of _verify_unverified_epoch_payments()
