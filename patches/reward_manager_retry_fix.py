"""
PATCH: reward_manager.py - Retry Queue ALPHA Payment Fix

Apply to: neurons/orchestrator/core/reward_manager.py

This patch replaces the legacy `subtensor.transfer()` retry path with
proper ALPHA `transfer_stake` via `transfer_alpha_with_memo()`.

Key changes:
1. _queue_failed_payment() stores amount_alpha instead of reward_tao
2. process_payment_retry_queue() calls transfer_alpha_with_memo()
3. transfer_alpha_with_memo() handles bytes-to-str conversion for tx_hash
4. Removes all legacy TAO transfer calls from retry path
"""

# ============================================================================
# CHANGE 1: In _queue_failed_payment() — store alpha amount, not TAO
# ============================================================================
# BEFORE (lines ~460-470):
    def _queue_failed_payment(self, worker, proof, reward_tao: float):
        self._payment_retry_queue.append({
            "worker_hotkey": proof.worker_hotkey,
            "worker_id": proof.worker_id,
            "task_id": proof.task_id,
            "proof": proof,
            "reward_tao": reward_tao,
            "attempts": 0,
            "queued_at": time.time(),
        })

# AFTER:
    def _queue_failed_payment(self, worker, proof, amount_alpha: float, transfer_id: str = ""):
        """Queue a failed/partial payment for retry when balance is available.
        
        Stores ALPHA amount (not TAO) since all payments use transfer_stake.
        """
        self._payment_retry_queue.append({
            "worker_hotkey": proof.worker_hotkey,
            "worker_id": proof.worker_id,
            "task_id": proof.task_id,
            "proof": proof,
            "amount_alpha": amount_alpha,  # Changed from reward_tao
            "transfer_id": transfer_id,  # Added: needed for memo
            "attempts": 0,
            "queued_at": time.time(),
        })
        logger.info(
            f"Queued payment retry: {amount_alpha} ALPHA for task {proof.task_id[:16]}... "
            f"(queue size: {len(self._payment_retry_queue)})"
        )

# ============================================================================
# CHANGE 2: In process_payment_retry_queue() — use transfer_alpha_with_memo()
# ============================================================================
# BEFORE (lines ~477-550):
# - Calls subtensor.transfer(wallet, destination_ss58, amount) 
# - Extracts tx_hash from ExtrinsicResponse
# - Logs "TAO" in success message

# AFTER:
    async def process_payment_retry_queue(self, current_epoch: int, wallet, subtensor, hotkey: str, db, subnet_core_client, netuid: int = 105):
        """Process queued payments when balance is available."""
        if not self._payment_retry_queue or not wallet or not subtensor:
            return

        # Check ALPHA stake balance (not TAO free balance)
        try:
            # For dTAO, we need to check ALPHA stake, not TAO balance
            # Try to get stake info
            stake_info = subtensor.get_stake_for_coldkey_and_hotkey(
                coldkey_ss58=wallet.coldkey.ss58_address,
                hotkey_ss58=wallet.hotkey.ss58_address,
                netuid=netuid,
            )
            available_alpha = float(stake_info) if stake_info else 0.0
        except Exception as e:
            logger.warning(f"Could not check ALPHA stake for retry queue: {e}")
            # Fallback: try TAO balance
            try:
                balance = subtensor.get_balance(wallet.hotkey.ss58_address)
                available_alpha = float(balance)
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
                logger.info(f"DEDUP: retry task {task_id[:16]}... already paid — removing from queue")
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
            
            # Fallback: resolve from metagraph
            if not worker_coldkey:
                try:
                    worker_coldkey = await self._resolve_worker_coldkey(
                        item["worker_hotkey"], subtensor, netuid
                    )
                except Exception as e:
                    item["attempts"] += 1
                    logger.warning(f"Could not resolve coldkey: {e}")
                    continue

            if not worker_coldkey:
                item["attempts"] += 1
                logger.warning(f"Empty coldkey for retry task {task_id[:16]}...")
                continue

            amount_alpha = min(item["amount_alpha"], available_alpha)
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
                f"— {item['amount_alpha']:.6f} ALPHA lost"
            )

        self._payment_retry_queue = [
            item for i, item in enumerate(self._payment_retry_queue)
            if i not in completed and i not in expired
        ]

        if completed:
            await self._report_epoch_summary(current_epoch, hotkey, subnet_core_client)

# ============================================================================
# CHANGE 3: In transfer_alpha_with_memo() — handle bytes tx_hash fields
# ============================================================================
# BEFORE (line ~744):
#   tx_hash = f"{receipt.extrinsic_hash}:{receipt.block_hash}"

# AFTER:
    def _format_tx_hash(self, extrinsic_hash, block_hash) -> str:
        """Ensure tx_hash fields are hex strings, not bytes objects."""
        # Handle bytes
        if isinstance(extrinsic_hash, bytes):
            extrinsic_hash = "0x" + extrinsic_hash.hex()
        else:
            extrinsic_hash = str(extrinsic_hash)
        
        if isinstance(block_hash, bytes):
            block_hash = "0x" + block_hash.hex()
        else:
            block_hash = str(block_hash)
        
        return f"{extrinsic_hash}:{block_hash}"

    # Then in transfer_alpha_with_memo(), replace:
    # tx_hash = f"{receipt.extrinsic_hash}:{receipt.block_hash}"
    # with:
    # tx_hash = self._format_tx_hash(receipt.extrinsic_hash, receipt.block_hash)

# ============================================================================
# CHANGE 4: Update callers of _queue_failed_payment to pass amount_alpha
# ============================================================================
# In pay_worker_immediately() — line ~299:
# BEFORE:
#   self._queue_failed_payment(worker, proof, reward)
# AFTER:
#   self._queue_failed_payment(worker, proof, alpha_per_chunk, transfer_id)

# Also line ~338 (after transfer_alpha_with_memo fails):
# BEFORE:
#   self._queue_failed_payment(worker, proof, reward)
# AFTER:
#   self._queue_failed_payment(worker, proof, alpha_per_chunk, payment_memo)

# And line ~350 (else block when transfer_id missing):
# BEFORE:
#   self._queue_failed_payment(worker, proof, alpha_per_chunk)
# AFTER:
#   self._queue_failed_payment(worker, proof, alpha_per_chunk, f"retry:{proof.task_id}")
