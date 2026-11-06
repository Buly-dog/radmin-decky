import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("diagnostics", Path(__file__).resolve().parents[1] / "scripts/diagnostics.py")
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


class DiagnosticLogs(unittest.TestCase):
    def test_utf16_log_with_unaligned_tail_is_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "service.log"
            file.write_bytes(("old line\n" * 5000 + "Service was powered off before shutdown\n").encode("utf-16-le"))
            result = diagnostics.tail(file, "utf-16-le")
        self.assertIn("Service was powered off before shutdown", result)
        self.assertLess(len(result), 5200)

    def test_missing_logs_do_not_break_report(self):
        with tempfile.TemporaryDirectory() as temp:
            result = diagnostics.tail(Path(temp) / "missing.log")
        self.assertIn("Unavailable", result)

    def test_recent_lines_are_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "bridge.log"
            file.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
            result = diagnostics.tail(file)
        self.assertIn("line 99", result)
        self.assertNotIn("\nline 10\n", result)
