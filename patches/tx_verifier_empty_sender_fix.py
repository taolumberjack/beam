"""
PATCH: tx_verifier.py - Fix Empty Sender Check

Apply to: neurons/validator/chain/tx_verifier.py

This patch fixes TxVerifier to properly skip sender validation when
expected_from is empty string (used by validator.py when orchestrator
coldkey is not immediately available).

Key changes:
1. Skip sender check when expected_from is ""
2. Add helper to safely handle bytes vs str hash fields
"""

# ============================================================================
# CHANGE 1: In TxVerifier.verify_transfer() — skip empty sender check
# ============================================================================
# BEFORE (lines ~85-95):
#        # Validate sender
#        if result.from_address != expected_from:
#            result = TxVerificationResult(
#                is_valid=False,
#                error=f"sender mismatch: expected {expected_from[:16]}..., got ...",
#            )

# AFTER:
        # Validate sender (skip if expected_from is empty)
        if expected_from and result.from_address != expected_from:
            result = TxVerificationResult(
                is_valid=False,
                error=f"sender mismatch: expected {expected_from[:16]}..., got {result.from_address[:16] if result.from_address else 'None'}...",
                from_address=result.from_address,
                to_address=result.to_address,
                amount_tao=result.amount_tao,
            )
            self._cache[tx_hash] = result
            return result

# ============================================================================
# CHANGE 2: Add _safe_hex_str() helper for bytes handling
# ============================================================================
# Add to TxVerifier class:

    def _safe_hex_str(self, value) -> str:
        """Convert bytes or string to hex string safely."""
        if isinstance(value, bytes):
            return "0x" + value.hex()
        elif isinstance(value, str):
            # Already a string — ensure it starts with 0x
            if not value.startswith("0x"):
                return "0x" + value
            return value
        else:
            return str(value)

    def _extract_tx_hash(self, response_or_receipt) -> str:
        """Extract extrinsic_hash:block_hash from various response types."""
        extrinsic_hash = None
        block_hash = None
        
        # Handle ExtrinsicResponse (SDK v10+)
        if hasattr(response_or_receipt, 'extrinsic_receipt'):
            receipt = response_or_receipt.extrinsic_receipt
            if receipt:
                extrinsic_hash = getattr(receipt, 'extrinsic_hash', None)
                block_hash = getattr(receipt, 'block_hash', None)
        
        # Handle receipt directly
        elif hasattr(response_or_receipt, 'extrinsic_hash'):
            extrinsic_hash = response_or_receipt.extrinsic_hash
            block_hash = getattr(response_or_receipt, 'block_hash', None)
        
        # Format to hex strings
        if extrinsic_hash and block_hash:
            return f"{self._safe_hex_str(extrinsic_hash)}:{self._safe_hex_str(block_hash)}"
        elif extrinsic_hash:
            return self._safe_hex_str(extrinsic_hash)
        else:
            return ""

# ============================================================================
# CHANGE 3: In _query_extrinsic() — use _safe_hex_str for hash comparison
# ============================================================================
# Find the section where extrinsic_hash is compared:
# ext_hash_str = "0x" + ext_hash_raw.hex() if isinstance(ext_hash_raw, bytes) else str(ext_hash_raw)

# Replace with:
            ext_hash_str = self._safe_hex_str(ext_hash_raw)
            if ext_hash_str.lower() == extrinsic_hash.lower():

# ============================================================================
# CHANGE 4: In AlphaPaymentVerifier — add same _safe_hex_str helper
# ============================================================================
# Add to AlphaPaymentVerifier class:

    def _safe_hex_str(self, value) -> str:
        """Convert bytes or string to hex string safely."""
        if isinstance(value, bytes):
            return "0x" + value.hex()
        elif isinstance(value, str):
            if not value.startswith("0x"):
                return "0x" + value
            return value
        else:
            return str(value)

# ============================================================================
# CHANGE 5: In AlphaPaymentVerifier._query_batch_extrinsic() — use helper
# ============================================================================
# Find:
# ext_hash_str = "0x" + ext_hash_raw.hex() if isinstance(ext_hash_raw, bytes) else str(ext_hash_raw)

# Replace with:
            ext_hash_str = self._safe_hex_str(ext_hash_raw)
            if ext_hash_str.lower() == extrinsic_hash.lower():

# Also find:
# extrinsic_hash = parts[0]
# block_hash = parts[1]

# Ensure validation:
            if not (parts[0].startswith("0x") and parts[1].startswith("0x")):
                # Try to fix missing 0x prefix
                extrinsic_hash = self._safe_hex_str(parts[0])
                block_hash = self._safe_hex_str(parts[1])
            else:
                extrinsic_hash = parts[0]
                block_hash = parts[1]
