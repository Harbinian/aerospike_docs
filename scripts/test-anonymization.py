"""Isolated checks for private policies and the complete staged snapshot."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("check-anonymization.py")
SPEC = importlib.util.spec_from_file_location("anonymization_check", SCRIPT)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class AnonymizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.write(".gitignore", "/ANONYMIZATION.local.json\n")
        self.write(CHECK.POLICY_NAME, json.dumps({
            "version": 1,
            "rules": [{"id": "R001", "pattern": "PrivateExample"}],
        }))

    def write(self, name, content):
        (self.root / name).write_text(content, encoding="utf-8")

    def stage(self):
        subprocess.run(["git", "add", "--all"], cwd=self.root, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_safe_content_and_private_policy_are_separate(self):
        self.write("public.txt", "Example company")
        self.stage()
        self.assertTrue(CHECK.run(self.root, staged=True)["valid"])
        self.assertNotIn(CHECK.POLICY_NAME, dict(CHECK.index_files(self.root)))

    def test_staged_secret_cannot_be_hidden_by_clean_working_copy(self):
        self.write("sample.txt", "PrivateExample")
        self.stage()
        self.write("sample.txt", "Example company")
        self.assertTrue(CHECK.run(self.root)["valid"])
        result = CHECK.run(self.root, staged=True)
        self.assertFalse(result["valid"])
        self.assertNotIn("PrivateExample", json.dumps(result))

    def test_unstaged_leak_does_not_change_clean_index(self):
        self.write("sample.txt", "Example company")
        self.stage()
        self.write("sample.txt", "PrivateExample")
        self.assertFalse(CHECK.run(self.root)["valid"])
        self.assertTrue(CHECK.run(self.root, staged=True)["valid"])

    def test_json_escapes_and_utf16_are_checked(self):
        self.write("escaped.json", '"\\u0050rivateExample"')
        (self.root / "wide.txt").write_bytes("PrivateExample".encode("utf-16"))
        self.assertEqual(len(CHECK.run(self.root)["violations"]), 2)

    def test_missing_policy_blocks_check(self):
        (self.root / CHECK.POLICY_NAME).unlink()
        with self.assertRaises(ValueError):
            CHECK.run(self.root)

    def test_invalid_json_fixture_is_scanned_without_becoming_a_format_gate(self):
        self.write("invalid.json", "{deliberately invalid fixture")
        self.assertTrue(CHECK.run(self.root)["valid"])
        self.write("invalid.json", r"{\\u0050rivateExample")
        self.assertFalse(CHECK.run(self.root)["valid"])

    def test_tracked_policy_blocks_check(self):
        subprocess.run(["git", "add", "-f", CHECK.POLICY_NAME], cwd=self.root, check=True)
        with self.assertRaises(ValueError):
            CHECK.run(self.root, staged=True)

    def test_binary_requires_review_and_sensitive_paths_are_redacted(self):
        (self.root / "opaque.bin").write_bytes(b"\xff\x00\x12")
        self.write("PrivateExample.txt", "safe")
        result = CHECK.run(self.root)
        self.assertFalse(result["valid"])
        self.assertNotIn("PrivateExample", json.dumps(result))
        self.assertIn("BINARY_REVIEW_REQUIRED", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
