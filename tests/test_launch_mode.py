import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

with patch.dict(sys.modules, {"fcntl": SimpleNamespace(), "pwd": SimpleNamespace()}):
    spec = importlib.util.spec_from_file_location("runner_mode_test", Path(__file__).resolve().parents[1] / "system/runner.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)


class LaunchMode(unittest.TestCase):
    def test_default_headless(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, "BASE", Path(temp)):
            self.assertIn("--no-ui", runner.launch_arguments(False))

    def test_saved_gui_mode_uses_normal_upstream_launch(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, "BASE", Path(temp)):
            (Path(temp) / "launch.json").write_text('{"gui":true}')
            args = runner.launch_arguments(False)
        self.assertNotIn("--no-ui", args)
        self.assertEqual(args, ["/bin/bash", str(runner.RUNTIME / "usr/bin/run.sh")])

    def test_configuration_always_uses_gui(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, "BASE", Path(temp)):
            self.assertNotIn("--no-ui", runner.launch_arguments(True))

    def test_invalid_settings_fall_back_to_headless(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, "BASE", Path(temp)):
            (Path(temp) / "launch.json").write_text("broken")
            self.assertIn("--no-ui", runner.launch_arguments(False))
