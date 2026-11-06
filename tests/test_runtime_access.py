import importlib.util
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("runtime_access", Path(__file__).resolve().parents[1] / "scripts/runtime_access.py")
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


class RuntimeAccess(unittest.TestCase):
    def fixture(self, root):
        for relative in ("usr/bin/run.sh", "usr/bin/lib.sh", "usr/bin/patch_qwindows_font.py",
                         "wine/bin/wine", "wine/bin/wineserver", "usr/lib/radmin-vpn/tap_bridge"):
            file = root / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("fixture")

    def test_private_script_is_rejected_before_executing_wine(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            def allowed(path, mode):
                return Path(path) != root / "usr/bin/run.sh"
            with patch.object(access.os, "access", side_effect=allowed), patch.object(access.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "cannot be read"):
                    access.verify(root)
                run.assert_not_called()

    def test_readable_runtime_checks_bash_and_both_native_binaries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with patch.object(access.os, "access", return_value=True), patch.object(access.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "wine test", "")) as run:
                access.verify(root)
            self.assertEqual(len(run.call_args_list), 3)
            self.assertEqual(run.call_args_list[0].args[0][:2], ["/bin/bash", "-n"])

    def test_native_loader_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with patch.object(access.os, "access", return_value=True), patch.object(access.subprocess, "run", side_effect=[subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 127, "", "missing shared library")]):
                with self.assertRaisesRegex(RuntimeError, "missing shared library"):
                    access.verify(root)
