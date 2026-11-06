import importlib.util
from pathlib import Path
import unittest
import tempfile
import subprocess
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("sudo_policy", Path(__file__).resolve().parents[1] / "scripts/sudo_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class SudoPolicy(unittest.TestCase):
    def test_specific_include_after_later_password_rule(self):
        original = "@includedir /etc/sudoers.d\n%wheel ALL=(ALL:ALL) ALL\n"
        result = policy.update_text(original, True)
        self.assertGreater(result.index(policy.INCLUDE), result.index("%wheel"))
        self.assertTrue(result.startswith(original))

    def test_repeated_install_does_not_duplicate_include(self):
        original = "root ALL=(ALL:ALL) ALL\n"
        first = policy.update_text(original, True)
        self.assertEqual(policy.update_text(first, True), first)
        self.assertEqual(first.count(policy.BEGIN), 1)

    def test_update_keeps_include_after_newly_appended_rules(self):
        first = policy.update_text("root ALL=(ALL:ALL) ALL\n", True)
        result = policy.update_text(first + "%wheel ALL=(ALL:ALL) ALL\n", True)
        self.assertGreater(result.index(policy.INCLUDE), result.index("%wheel"))

    def test_uninstall_preserves_unrelated_rules(self):
        original = "root ALL=(ALL:ALL) ALL\n"
        updated = policy.update_text(original, True) + "%wheel ALL=(ALL:ALL) ALL\n"
        removed = policy.update_text(updated, False)
        self.assertIn(original, removed)
        self.assertIn("%wheel ALL=(ALL:ALL) ALL\n", removed)
        self.assertNotIn(policy.BEGIN, removed)
        self.assertNotIn(policy.INCLUDE, removed)

    def test_malformed_block_is_rejected(self):
        with self.assertRaises(ValueError):
            policy.update_text("root ALL=(ALL) ALL\n" + policy.BEGIN, True)

    def test_invalid_candidate_never_replaces_original(self):
        with tempfile.TemporaryDirectory() as temp:
            main = Path(temp) / "sudoers"
            backup = Path(temp) / "backup"
            original = "root ALL=(ALL) ALL\n"
            main.write_text(original)
            with patch.object(policy.shutil, "which", return_value="/usr/sbin/visudo"), patch.object(policy.os, "chown", create=True), patch.object(policy.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "visudo")):
                with self.assertRaises(subprocess.CalledProcessError):
                    policy.apply(True, main, backup)
            self.assertEqual(main.read_text(), original)
            self.assertEqual(backup.read_text(), original)
            self.assertFalse(list(Path(temp).glob(".sudoers-radmin-*")))

    def test_valid_candidate_replaces_only_after_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            main = Path(temp) / "sudoers"
            backup = Path(temp) / "backup"
            original = "%wheel ALL=(ALL) ALL\n"
            main.write_text(original)
            def validate(args, check):
                self.assertEqual(main.read_text(), original)
                self.assertIn(policy.INCLUDE, Path(args[-1]).read_text())
            with patch.object(policy.shutil, "which", return_value="/usr/sbin/visudo"), patch.object(policy.os, "chown", create=True), patch.object(policy.subprocess, "run", side_effect=validate):
                policy.apply(True, main, backup)
            self.assertEqual(main.read_text(), policy.update_text(original, True))
            self.assertEqual(backup.read_text(), original)


if __name__ == "__main__":
    unittest.main()
