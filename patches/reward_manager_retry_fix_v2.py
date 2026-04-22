"""
PATCH v2: reward_manager.py - Retry Queue ALPHA Payment Fix

Apply to: neurons/orchestrator/core/reward_manager.py

This patch fixes the retry queue to use ALPHA transfer_stake instead of 
legacy TAO transfer(). Key change: converts TAO to ALPHA at retry time
rather than changing all 10 callers.

Key changes:
1. process_payment_retry_queue() converts TAO->ALPHA before calling transfer_alpha_with_memo()
2. transfer_alpha_with_memo() handles bytes->str conversion for tx_hash fields
3. Adds async lock to prevent race conditions
4. Adds _safe_hex_str() helper for consistent hash formatting
"""

# ============================================================================
# CHANGE 1: Add async lock to RewardManager.__init__
# ============================================================================
# In __init__, add:
        self._retry_lock = asyncio.Lock()

# ============================================================================
# CHANGE 2: Replace entire process_payment_retry_queue() method
# ============================================================================
# BEFORE (lines ~477-670):
# - Calls subtensor.transfer() (legacy TAO)
# - No async lock
# - Extracts tx_hash from ExtrinsicResponse

# AFTER:
    async def process_payment_retry_queue(
        self, current_epoch: int, wallet, subtensor, hotkey: str, 
        db, subnet_core_client, netuid: int = 105, alpha_per_chunk: float = 0.5
    ):
        """Process queued payments when balance is available.
        
        Converts legacy TAO amounts to ALPHA and uses transfer_stake.
        """
        if not self._payment_retry_queue or not wallet or not subtensor:
            return

        # Prevent concurrent retry processing
        async with self._retry_lock:
            # Check ALPHA stake balance (not TAO free balance)
            try:
                stake_info = subtensor.get_stake_for_coldkey_and_hotkey(
                    coldkey_ss58=wallet.coldkey.ss58_address,
                    hotkey_ss58=wallet.hotkey.ss58_address,
                    netuid=netuid,
                )
                available_alpha = float(stake_info) if stake_info else 0.0
            except Exception as e:
                logger.warning(f"Could not check ALPHA stake for retry: {e}")
                try:
                    # Fallback: check TAO balance (for backward compat during transition)
                    balance = subtensor.get_balance(wallet.hotkey.ss58_address)
                    available_alpha = float(balance)
                    logger.info("Falling back to TAO balance check for retry queue")
                except Exception as e2:
                    logger.warning(f"Could not check balance for retry queue: {e2}")
                    return

            if available_alpha <= 0:
                logger.debug(
                    f"No ALPHA for payment retries ({len(self._payment_retry_queue)} queued)"
                )
                return

            logger.info(
                f"Processing payment retry queue: {len(self._payment_retry_queue)} items, "
                f"{available_alpha:.4f} ALPHA available"
            )

            completed = set()
            for i, item in enumerate(self._payment_retry_queue):
                if available_alpha <= 1e-9:
                    break

                task_id = item.get("task_id")
                proof = item.get("proof")
                
                # Skip zero-byte tasks
                if proof and getattr(proof, "bytes_relayed", 0) <= 0:
                    completed.add(i)
                    continue

                # Dedup: skip if already paid
                if task_id and task_id in self._paid_task_ids:
                    logger.info(f"DEDUP: retry task {task_id[:16]}... already paid")
                    completed.add(i)
                    continue

                # Resolve worker coldkey
                worker_coldkey = None
                if SUBNET_CORE_CLIENT_AVAILABLE and subnet_core_client and task_id:
                    try:
                        payment_info = await subnet_core_client.get_task_payment_address(task_id)
                        worker_coldkey = payment_info.get("address")
                    except Exception as e:
                        item["attempts"] += 1
                        logger.warning(f"Failed to resolve coldkey for retry {task_id[:16]}...: {e}")
                        continue
                
                if not worker_coldkey and proof and proof.worker_hotkey:
                    try:
                        worker_coldkey = await self._resolve_worker_coldkey(
                            proof.worker_hotkey, subtensor, netuid
                        )
                    except Exception as e:
                        item["attempts"] += 1
                        logger.warning(f"Could not resolve coldkey: {e}")
                        continue

                if not worker_coldkey:
                    item["attempts"] += 1
                    logger.warning(f"Empty coldkey for retry task {task_id[:16]}...")
                    continue

                # Convert stored TAO amount to ALPHA
                # The queue stores TAO amounts from old callers
                # We need to convert: 1 TAO ~= 1 ALPHA (approximate during dTAO transition)
                # Better: use alpha_per_chunk as the retry amount since that's the standard
                stored_tao = item.get("reward_tao", 0)
                
                # Use stored amount if reasonable, otherwise fall back to alpha_per_chunk
                if stored_tao > 0 and stored_tao < 10:  # Sanity check: must be less than 10 TAO
                    amount_alpha = stored_tao  # Direct 1:1 conversion (simplification)
                    logger.debug(f"Retry: converting {stored_tao} TAO to ALPHA for task {task_id[:16]}...")
                else:
                    amount_alpha = alpha_per_chunk  # Fallback to standard amount
                    logger.debug(f"Retry: using standard {alpha_per_chunk} ALPHA for task {task_id[:16]}...")

                # Sanity check against available
                if amount_alpha > available_alpha:
                    amount_alpha = available_alpha

                transfer_id = item.get("transfer_id", f"retry:{task_id}")

                # Call transfer_alpha_with_memo (ALPHA, not TAO)
                tx_hash = await self.transfer_alpha_with_memo(
                    worker_coldkey=worker_coldkey,
                    amount_alpha=amount_alpha,
                    transfer_id=transfer_id,
                    wallet=wallet,
                    subtensor=subtensor,
                    netuid=netuid,
                )

                if tx_hash:
                    available_alpha -= amount_alpha
                    if task_id:
                        self._paid_task_ids.add(task_id)
                    
                    # Record to BeamCore
                    amount_rao = int(amount_alpha * 1e9)
                    if SUBNET_CORE_CLIENT_AVAILABLE and subnet_core_client:
                        try:
                            await subnet_core_client.record_pob_payment(
                                task_id=task_id,
                                tx_hash=tx_hash,
                                amount_rao=amount_rao,
                            )
                            await subnet_core_client.record_worker_payment(
                                WorkerPaymentData(
                                    orchestrator_hotkey=hotkey or "",
                                    epoch=current_epoch,
                                    worker_id=item["worker_id"],
                                    worker_hotkey=item["worker_hotkey"],
                                    bytes_relayed=proof.bytes_relayed if proof else 0,
                                    tasks_completed=1,
                                    amount_earned=amount_rao,
                                    task_id=task_id,
                                    tx_hash=tx_hash,
                                )
                            )
                        except Exception as e:
                            logger.warning(f"Failed to record retry payment to BeamCore: {e}")

                    logger.info(
                        f"Retry payment SUCCESS: {amount_alpha} ALPHA to {worker_coldkey[:16]}... "
                        f"tx={tx_hash[:32]}..."
                    )
                    completed.add(i)
                    self.total_rewards_distributed += amount_alpha
                else:
                    item["attempts"] += 1
                    logger.warning(
                        f"Retry ALPHA transfer failed for task {task_id[:16]}... "
                        f"(attempt {item['attempts']}/{self._max_payment_retries})"
                    )

            # Clean up completed/expired items
            expired = [
                i for i, item in enumerate(self._payment_retry_queue)
                if i not in completed and item["attempts"] >= self._max_payment_retries
            ]
            for i in expired:
                item = self._payment_retry_queue[i]
                logger.error(
                    f"Payment retry EXHAUSTED for task {item.get('task_id', 'unknown')[:16]}... "
                    f"— {item['reward_tao']:.6f} TAO equivalent lost"
                )

            self._payment_retry_queue = [
                item for i, item in enumerate(self._payment_retry_queue)
                if i not in completed and i not in expired
            ]

            if completed:
                await self._report_epoch_summary(current_epoch, hotkey, subnet_core_client)

# ============================================================================
# CHANGE 3: Add _safe_hex_str() and _format_tx_hash() helpers
# ============================================================================
# Add these methods to RewardManager class:

    def _safe_hex_str(self, value) -> str:
        """Convert bytes or mixed types to hex string safely."""
        if isinstance(value, bytes):
            return "0x" + value.hex()
        elif isinstance(value, str):
            # Handle Python repr of bytes: "b'0xabc...'" 
            if value.startswith("b'") and value.endswith("'"):
                inner = value[2:-1]  # strip b'...'
                if inner.startswith("0x"):
                    return inner
                else:
                    return "0x" + inner
            if not value.startswith("0x"):
                return "0x" + value
            return value
        else:
            return str(value)

    def _format_tx_hash(self, extrinsic_hash, block_hash) -> str:
        """Format tx_hash as 'extrinsic_hash:block_hash' with proper hex encoding."""
        return f"{self._safe_hex_str(extrinsic_hash)}:{self._safe_hex_str(block_hash)}"

# ============================================================================
# CHANGE 4: In transfer_alpha_with_memo() — use _format_tx_hash()
# ============================================================================
# Replace (around line ~744):
#   tx_hash = f"{receipt.extrinsic_hash}:{receipt.block_hash}"
# With:
#   tx_hash = self._format_tx_hash(receipt.extrinsic_hash, receipt.block_hash)

# Also in process_payment_retry_queue fallback tx_hash generation:
# Replace:
#   tx_hash = f"retry:{hotkey[:8]}:{payment_dest[:8]}:{int(time.time())}"
# With: remove this fallback entirely — if transfer_alpha_with_memo returns None, that's a real failure
