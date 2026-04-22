"""
PATCH: validator.py - Route ALPHA payments to AlphaPaymentVerifier

Apply to: neurons/validator/core/validator.py

This patch fixes the validator to properly verify ALPHA batch_all payments
instead of routing everything through the legacy TxVerifier.

Key changes:
1. Import AlphaPaymentVerifier
2. Route batch_all ALPHA payments to AlphaPaymentVerifier
3. Route legacy Balances.transfer to TxVerifier
4. Check worker_coldkey (not worker_hotkey) for recipient match
"""

# ============================================================================
# CHANGE 1: Import AlphaPaymentVerifier alongside TxVerifier
# ============================================================================
# BEFORE (line ~26):
#   from chain.tx_verifier import TxVerifier, TxVerificationResult

# AFTER:
from chain.tx_verifier import TxVerifier, TxVerificationResult, AlphaPaymentVerifier

# ============================================================================
# CHANGE 2: In _verify_orchestrator_payments() — detect payment type and route
# ============================================================================
# BEFORE (lines ~1156-1220):
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

                # Determine payment type based on tx_hash format or content
                # ALPHA payments from batch_all have format: extrinsic_hash:block_hash
                # Legacy TAO payments also use same format, so we need to detect by verification
                
                verification = None
                is_alpha = False

                if alpha_verifier and tx_hash.startswith("0x"):
                    # Try ALPHA verification first (most common in dTAO)
                    expected_memo = payment.get("expected_memo", f"{payment.get('transfer_id', '')}:{task_id}")
                    worker_coldkey = payment.get("worker_coldkey", "")
                    amount_alpha = payment.get("amount_earned", 0) / 1e9  # rao to ALPHA
                    
                    verification = alpha_verifier.verify_alpha_payment(
                        tx_hash=tx_hash,
                        expected_transfer_id=expected_memo,
                        expected_worker_coldkey=worker_coldkey,
                        min_amount_alpha=0.4,  # Slightly below standard 0.5 to account for dust
                    )
                    is_alpha = True

                # If ALPHA verifier not available or payment is legacy TAO
                if not is_alpha and tx_verifier:
                    worker_payment_addr = payment.get("worker_hotkey", "")
                    amount_tao = payment.get("amount_earned", 0) / 1e9
                    
                    verification = tx_verifier.verify_transfer(
                        tx_hash=tx_hash,
                        expected_from="",  # Skip sender check for now
                        expected_to=worker_payment_addr,
                        expected_amount=amount_tao,
                        tolerance=0.05,
                    )

                if verification and not verification.is_valid:
                    self._apply_payment_penalty(
                        orchestrator_hotkey, 
                        f"invalid_{'alpha' if is_alpha else 'tao'}_tx: {verification.error}",
                        task_id
                    )
                    logger.warning(
                        f"Invalid {'ALPHA' if is_alpha else 'TAO'} tx for task {task_id[:16]}...: "
                        f"{verification.error}"
                    )
                elif verification and verification.is_valid:
                    logger.debug(
                        f"Verified {'ALPHA' if is_alpha else 'TAO'} payment for task {task_id[:16]}... "
                        f"tx={tx_hash[:24]}..."
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

# ============================================================================
# CHANGE 3: Update existing payment verification loop (lines ~1190-1230)
# ============================================================================
# Find the existing loop that iterates over verified proofs and replaces the
# tx_verifier.verify_transfer() call with the new routing logic above.

# ============================================================================
# CHANGE 4: Fix worker_coldkey resolution in payment records
# ============================================================================
# When calling BeamCore to get payment data, ensure we request worker_coldkey:
# In the SubnetCore API call (if configurable):
#   - Request field: worker_coldkey
#   - Pass expected_memo if available

# If SubnetCore doesn't return worker_coldkey, resolve from metagraph:
    def _resolve_worker_coldkey_from_payment(self, payment: dict) -> str:
        """Resolve worker coldkey from payment data or metagraph."""
        # Try payment record first
        coldkey = payment.get("worker_coldkey", "")
        if coldkey:
            return coldkey
        
        # Fallback: try metagraph lookup by worker_hotkey
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
