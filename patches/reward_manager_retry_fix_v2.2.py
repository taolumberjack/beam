"""
PATCH v2.2: reward_manager.py - Final fixes for asyncio import and TAO→ALPHA conversion

Apply to: neurons/orchestrator/core/reward_manager.py

Fixes from v2 review:
1. Added note: ensure `import asyncio` is in the file (usually already there)
2. Removed hardcoded 1:1 TAO→ALPHA conversion — now uses alpha_per_chunk as base
3. Added TODO comment for future dTAO rate oracle
4. Documented caller signature changes needed in orchestrator.py
"""

# ============================================================================
# PREREQUISITE: Ensure `import asyncio` is at top of file
# ============================================================================
# Check that these imports exist at the top of reward_manager.py:
#   import asyncio
#   import logging
#   import time
# If asyncio is missing, add it.

# ============================================================================
# CHANGE 1: Add async lock to RewardManager.__init__
# ============================================================================
# In __init__, add after existing initializations:
        self._retry_lock = asyncio.Lock()

# ============================================================================
# CHANGE 2: Replace entire process_payment_retry_queue() method (v2.2)
# ============================================================================
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

                # Determine retry amount:
                # The queue stores legacy TAO amounts from old callers.
                # We use alpha_per_chunk as the standard retry amount since
                # that's the actual ALPHA payment standard. The stored TAO
                # amount is only used as a sanity check upper bound.
                #
                # TODO: During dTAO transition, 1 TAO != 1 ALPHA.
                #       Add a rate oracle or exchange rate lookup here
                #       once the rate API is available.
                #       For now, use the configured alpha_per_chunk.
                
                stored_tao = item.get("reward_tao", 0)
                
                # Use alpha_per_chunk as the standard amount
                # Clamp to available balance and stored amount upper bound
                amount_alpha = min(alpha_per_chunk, available_alpha)
                
                # Sanity: don't exceed what was originally queued (TAO ~= ALPHA approximation)
                # During dTAO this is approximate; add rate oracle TODO above
                if stored_tao > 0:
                    amount_alpha = min(amount_alpha, stored_tao * 1.0)  # 1:1 approx
                
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
# CHANGE 3: Update caller in orchestrator.py
# ============================================================================
# Find where process_payment_retry_queue() is called in orchestrator.py
# and update the call to pass netuid and alpha_per_chunk:
#
# BEFORE:
#   await self.reward_manager.process_payment_retry_queue(
#       current_epoch, wallet, subtensor, hotkey, db, subnet_core_client
#   )
#
# AFTER:
#   await self.reward_manager.process_payment_retry_queue(
#       current_epoch, wallet, subtensor, hotkey, db, subnet_core_client,
#       netuid=self.settings.netuid,
#       alpha_per_chunk=self.settings.alpha_per_chunk,
#   )
