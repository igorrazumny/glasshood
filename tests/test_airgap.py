# File: tests/test_airgap.py
# Purpose: Tests for air-gap encrypted file export

import json
import tempfile
import unittest

from agent.airgap import (
    encrypt_payload, decrypt_payload, AirgapExporter, _derive_key,
)


class TestKeyDerivation(unittest.TestCase):

    def test_same_inputs_same_key(self):
        salt = b"salt" * 8
        k1 = _derive_key("passphrase", salt)
        k2 = _derive_key("passphrase", salt)
        self.assertEqual(k1, k2)

    def test_different_passphrase_different_key(self):
        salt = b"salt" * 8
        k1 = _derive_key("pass1", salt)
        k2 = _derive_key("pass2", salt)
        self.assertNotEqual(k1, k2)

    def test_key_length(self):
        salt = b"s" * 32
        k = _derive_key("test", salt)
        self.assertEqual(len(k), 32)


class TestEncryptDecrypt(unittest.TestCase):

    def test_roundtrip(self):
        data = b"hello world"
        encrypted = encrypt_payload(data, "secret123")
        decrypted = decrypt_payload(encrypted, "secret123")
        self.assertEqual(decrypted, data)

    def test_wrong_passphrase_fails(self):
        data = b"sensitive data"
        encrypted = encrypt_payload(data, "correct")
        with self.assertRaises(Exception):
            decrypt_payload(encrypted, "wrong")

    def test_encrypted_differs_from_plaintext(self):
        data = b"plaintext content"
        encrypted = encrypt_payload(data, "key")
        self.assertNotEqual(encrypted, data)
        self.assertNotIn(data, encrypted)

    def test_different_encryptions_differ(self):
        data = b"same data"
        e1 = encrypt_payload(data, "key")
        e2 = encrypt_payload(data, "key")
        self.assertNotEqual(e1, e2)  # random salt/nonce

    def test_large_payload(self):
        data = b"x" * 100_000
        encrypted = encrypt_payload(data, "key")
        decrypted = decrypt_payload(encrypted, "key")
        self.assertEqual(decrypted, data)


class TestAirgapExporter(unittest.TestCase):

    def test_export_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            exporter = AirgapExporter(d, "passphrase", "agent-01")
            filename = exporter.export_batch([{"msg": "test"}])
            self.assertTrue(filename.startswith("glasshood-agent-01-"))
            self.assertTrue(filename.endswith(".enc"))

    def test_export_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            exporter = AirgapExporter(d, "passphrase", "agent-01")
            events = [{"source_id": "sap", "message": "batch 42"}]
            filename = exporter.export_batch(events)
            filepath = f"{d}/{filename}"
            result = exporter.import_file(filepath)
            self.assertEqual(result["agent_id"], "agent-01")
            self.assertEqual(result["event_count"], 1)
            self.assertEqual(result["events"], events)

    def test_export_multiple_batches(self):
        with tempfile.TemporaryDirectory() as d:
            exporter = AirgapExporter(d, "passphrase", "agent-01")
            f1 = exporter.export_batch([{"msg": "batch1"}])
            f2 = exporter.export_batch([{"msg": "batch2"}])
            self.assertNotEqual(f1, f2)

    def test_creates_export_dir(self):
        with tempfile.TemporaryDirectory() as d:
            export_path = f"{d}/subdir/export"
            exporter = AirgapExporter(export_path, "pass", "a1")
            exporter.export_batch([{"msg": "test"}])
            import os
            self.assertTrue(os.path.isdir(export_path))
