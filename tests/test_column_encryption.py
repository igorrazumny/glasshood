# File: tests/test_column_encryption.py
# Purpose: Tests for AEAD column encryption (AES-256-GCM)

import os
import unittest
from unittest.mock import patch

from src.storage.encryption import (
    encrypt_value, decrypt_value, encrypt_row, decrypt_row, is_enabled,
)

# Valid 32-byte key for testing
TEST_KEY_HEX = os.urandom(32).hex()


class TestIsEnabled(unittest.TestCase):
    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", "")
    def test_disabled_when_no_key(self):
        self.assertFalse(is_enabled())

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_enabled_with_valid_key(self):
        self.assertTrue(is_enabled())

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", "not-hex")
    def test_disabled_with_invalid_hex(self):
        self.assertFalse(is_enabled())

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", "aabb")
    def test_disabled_with_wrong_length(self):
        self.assertFalse(is_enabled())


class TestEncryptDecrypt(unittest.TestCase):
    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_round_trip(self):
        plaintext = "Batch 42 deviation: pH out of range"
        ct = encrypt_value(plaintext)
        self.assertNotEqual(ct, plaintext)
        pt = decrypt_value(ct)
        self.assertEqual(pt, plaintext)

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_round_trip_with_aad(self):
        plaintext = "Critical alert"
        aad = "event-id-123"
        ct = encrypt_value(plaintext, associated_data=aad)
        pt = decrypt_value(ct, associated_data=aad)
        self.assertEqual(pt, plaintext)

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_wrong_aad_fails_gracefully(self):
        plaintext = "secret data"
        ct = encrypt_value(plaintext, associated_data="correct-id")
        result = decrypt_value(ct, associated_data="wrong-id")
        # Should return ciphertext unchanged on AEAD failure
        self.assertEqual(result, ct)

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_different_encryptions_differ(self):
        plaintext = "same message"
        ct1 = encrypt_value(plaintext)
        ct2 = encrypt_value(plaintext)
        self.assertNotEqual(ct1, ct2)  # random nonce

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", "")
    def test_passthrough_when_disabled(self):
        plaintext = "unencrypted"
        self.assertEqual(encrypt_value(plaintext), plaintext)
        self.assertEqual(decrypt_value(plaintext), plaintext)

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_empty_string(self):
        ct = encrypt_value("")
        pt = decrypt_value(ct)
        self.assertEqual(pt, "")

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_unicode(self):
        plaintext = "Abweichung: Temperatur zu hoch"
        ct = encrypt_value(plaintext)
        pt = decrypt_value(ct)
        self.assertEqual(pt, plaintext)


class TestRowEncryption(unittest.TestCase):
    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_encrypt_row_encrypts_message(self):
        row = {"event_id": "e1", "message": "secret", "source_id": "mw-01"}
        result = encrypt_row(row)
        self.assertNotEqual(result["message"], "secret")
        self.assertEqual(result["source_id"], "mw-01")

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_decrypt_row_decrypts_message(self):
        row = {"event_id": "e1", "message": "secret", "source_id": "mw-01"}
        encrypted = encrypt_row(dict(row))
        decrypted = decrypt_row(encrypted)
        self.assertEqual(decrypted["message"], "secret")

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_aad_bound_to_event_id(self):
        row = {"event_id": "e1", "message": "secret"}
        encrypted = encrypt_row(dict(row))
        # Tamper with event_id
        encrypted["event_id"] = "e2"
        decrypted = decrypt_row(encrypted)
        # AEAD fails — message stays encrypted
        self.assertNotEqual(decrypted["message"], "secret")

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", "")
    def test_noop_when_disabled(self):
        row = {"event_id": "e1", "message": "plain"}
        self.assertEqual(encrypt_row(dict(row))["message"], "plain")
        self.assertEqual(decrypt_row(dict(row))["message"], "plain")

    @patch("src.storage.encryption.STORAGE_ENCRYPTION_KEY", TEST_KEY_HEX)
    def test_empty_message_not_encrypted(self):
        row = {"event_id": "e1", "message": ""}
        result = encrypt_row(dict(row))
        self.assertEqual(result["message"], "")
