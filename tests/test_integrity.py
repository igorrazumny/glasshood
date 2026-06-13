# File: tests/test_integrity.py
# Purpose: Tests for agent binary/code integrity verification

import os
import tempfile
import unittest

from agent.integrity import (
    compute_file_hash, compute_directory_hash, generate_manifest, verify_integrity,
)


class TestComputeFileHash(unittest.TestCase):
    """SHA-256 hash of individual files."""

    def test_known_content(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("hello world\n")
            f.flush()
            h = compute_file_hash(f.name)
        os.unlink(f.name)
        # SHA-256 of "hello world\n"
        self.assertEqual(len(h), 64)
        self.assertTrue(h.isalnum())

    def test_same_content_same_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f1:
            f1.write("test content")
            f1.flush()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f2:
            f2.write("test content")
            f2.flush()
        h1 = compute_file_hash(f1.name)
        h2 = compute_file_hash(f2.name)
        os.unlink(f1.name)
        os.unlink(f2.name)
        self.assertEqual(h1, h2)

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f1:
            f1.write("content a")
            f1.flush()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f2:
            f2.write("content b")
            f2.flush()
        h1 = compute_file_hash(f1.name)
        h2 = compute_file_hash(f2.name)
        os.unlink(f1.name)
        os.unlink(f2.name)
        self.assertNotEqual(h1, h2)


class TestComputeDirectoryHash(unittest.TestCase):
    """Directory-level hashing."""

    def test_hashes_py_files_only(self):
        with tempfile.TemporaryDirectory() as d:
            (open(os.path.join(d, "a.py"), "w")).write("code")
            (open(os.path.join(d, "b.txt"), "w")).write("text")
            hashes = compute_directory_hash(d)
            self.assertIn("a.py", hashes)
            self.assertNotIn("b.txt", hashes)

    def test_includes_subdirectories(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "sub")
            os.makedirs(sub)
            (open(os.path.join(sub, "mod.py"), "w")).write("module")
            hashes = compute_directory_hash(d)
            self.assertIn(os.path.join("sub", "mod.py"), hashes)

    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            hashes = compute_directory_hash(d)
            self.assertEqual(hashes, {})


class TestGenerateManifest(unittest.TestCase):
    """Manifest generation."""

    def test_manifest_structure(self):
        with tempfile.TemporaryDirectory() as d:
            (open(os.path.join(d, "main.py"), "w")).write("print('hi')")
            manifest = generate_manifest(d)
            self.assertEqual(manifest["algorithm"], "sha256")
            self.assertIn("digest", manifest)
            self.assertIn("files", manifest)
            self.assertEqual(len(manifest["digest"]), 64)

    def test_manifest_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            (open(os.path.join(d, "a.py"), "w")).write("aaa")
            (open(os.path.join(d, "b.py"), "w")).write("bbb")
            m1 = generate_manifest(d)
            m2 = generate_manifest(d)
            self.assertEqual(m1["digest"], m2["digest"])

    def test_manifest_changes_on_modification(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "code.py")
            with open(path, "w") as f:
                f.write("original")
            m1 = generate_manifest(d)
            with open(path, "w") as f:
                f.write("modified")
            m2 = generate_manifest(d)
            self.assertNotEqual(m1["digest"], m2["digest"])


class TestVerifyIntegrity(unittest.TestCase):
    """End-to-end integrity verification."""

    def test_empty_digest_skips_check(self):
        passed, msg = verify_integrity("/nonexistent", "")
        self.assertTrue(passed)
        self.assertIn("No integrity check", msg)

    def test_matching_digest_passes(self):
        with tempfile.TemporaryDirectory() as d:
            (open(os.path.join(d, "agent.py"), "w")).write("code here")
            manifest = generate_manifest(d)
            passed, msg = verify_integrity(d, manifest["digest"])
            self.assertTrue(passed)
            self.assertIn("OK", msg)

    def test_mismatched_digest_fails(self):
        with tempfile.TemporaryDirectory() as d:
            (open(os.path.join(d, "agent.py"), "w")).write("code here")
            passed, msg = verify_integrity(d, "0" * 64)
            self.assertFalse(passed)
            self.assertIn("MISMATCH", msg)

    def test_tampered_file_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "agent.py")
            with open(path, "w") as f:
                f.write("original code")
            manifest = generate_manifest(d)
            digest = manifest["digest"]
            # Tamper
            with open(path, "w") as f:
                f.write("tampered code")
            passed, msg = verify_integrity(d, digest)
            self.assertFalse(passed)
