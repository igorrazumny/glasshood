# File: src/storage/encryption.py
# Purpose: AEAD column encryption (AES-256-GCM) for sensitive BigQuery fields

import base64
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config.settings import STORAGE_ENCRYPTION_KEY

logger = logging.getLogger(__name__)

_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # GCM standard


def _get_key() -> bytes | None:
    """Parse hex-encoded encryption key from settings."""
    if not STORAGE_ENCRYPTION_KEY:
        return None
    try:
        key = bytes.fromhex(STORAGE_ENCRYPTION_KEY)
        if len(key) != _KEY_BYTES:
            logger.error(f"STORAGE_ENCRYPTION_KEY must be {_KEY_BYTES} bytes, got {len(key)}")
            return None
        return key
    except ValueError:
        logger.error("STORAGE_ENCRYPTION_KEY is not valid hex")
        return None


def is_enabled() -> bool:
    """Return True if column encryption is configured."""
    return _get_key() is not None


def encrypt_value(plaintext: str, associated_data: str = "") -> str:
    """Encrypt a string value using AES-256-GCM.

    Returns base64-encoded ciphertext (nonce || ciphertext || tag).
    associated_data (e.g. event_id) binds the ciphertext to its row.
    Returns plaintext unchanged if encryption is not configured.
    """
    key = _get_key()
    if key is None:
        return plaintext
    nonce = os.urandom(_NONCE_BYTES)
    aad = associated_data.encode("utf-8") if associated_data else None
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)
    # Format: base64(nonce + ciphertext_with_tag)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_value(ciphertext_b64: str, associated_data: str = "") -> str:
    """Decrypt a base64-encoded AES-256-GCM value.

    Returns plaintext string.
    Returns ciphertext_b64 unchanged if decryption fails or not configured.
    """
    key = _get_key()
    if key is None:
        return ciphertext_b64
    try:
        raw = base64.b64decode(ciphertext_b64)
        if len(raw) < _NONCE_BYTES + 16:  # nonce + minimum tag
            return ciphertext_b64
        nonce = raw[:_NONCE_BYTES]
        ct = raw[_NONCE_BYTES:]
        aad = associated_data.encode("utf-8") if associated_data else None
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, aad).decode("utf-8")
    except Exception:
        # Not encrypted or wrong key — return as-is
        return ciphertext_b64


def encrypt_row(row: dict) -> dict:
    """Encrypt the 'message' field of a row in-place. Returns the row."""
    if not is_enabled():
        return row
    event_id = row.get("event_id", "")
    msg = row.get("message", "")
    if msg:
        row["message"] = encrypt_value(msg, associated_data=event_id)
    return row


def decrypt_row(row: dict) -> dict:
    """Decrypt the 'message' field of a row. Returns a new dict."""
    if not is_enabled():
        return row
    result = dict(row)
    event_id = result.get("event_id", "")
    msg = result.get("message", "")
    if msg:
        result["message"] = decrypt_value(msg, associated_data=event_id)
    return result
