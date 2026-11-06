import asyncio
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


helper = module("helper", ROOT / "system/net_helper.py")
patcher = module("patcher", ROOT / "scripts/patch_runtime.py")
backend = module("backend", ROOT / "main.py")
probe = module("probe", ROOT / "system/probe.py")


class NetworkBoundary(unittest.TestCase):
    def test_access_check_performs_no_network_operations(self):
        with patch.object(helper.os, "geteuid", return_value=0, create=True), patch.object(helper, "run") as run:
            self.assertEqual(helper.main(["check-access"]), 0)
        run.assert_not_called()

    def test_valid_calls(self):
        calls = [
            "modprobe tun", "ip link delete radminvpn0",
            "ip tuntap add dev radminvpn0 mode tap user deck",
            "ip link set radminvpn0 address 02:ab:cd:12:34:56",
            "ip link set radminvpn0 up",
            "ip link set radminvpn0 multicast on",
            "ip link set radminvpn0 allmulticast on",
            "ip addr add 26.12.34.56/8 dev radminvpn0",
            "ip -6 addr add fd00::123/128 dev radminvpn0",
            "ip addr flush dev radminvpn0",
            "ip route replace 26.0.0.0/8 dev radminvpn0",
            "ip route add 224.0.2.60/32 dev radminvpn0",
            "ip maddr add 224.0.2.60 dev radminvpn0",
            "ip route append 224.0.0.0/4 dev radminvpn0 metric 0",
            "ip route append 255.255.255.255/32 dev radminvpn0 metric 0",
            "nmcli device set radminvpn0 managed no",
            "sysctl -w net.ipv4.conf.radminvpn0.rp_filter=0",
            "sysctl -w net.ipv4.conf.radminvpn0.accept_local=1",
        ]
        for call in calls:
            with self.subTest(call=call):
                self.assertTrue(helper.allowed(call.split()))

    def test_reject_privilege_expansion(self):
        calls = [
            "bash -c id", "sh", "ip link delete wlan0", "ip netns exec root sh",
            "ip tuntap add dev radminvpn0 mode tap user root",
            "ip addr add 127.0.0.1/8 dev radminvpn0",
            "ip addr add 26.1.2.3/0 dev radminvpn0",
            "ip addr add 26.999.2.3/8 dev radminvpn0",
            "ip -6 addr add ::1/128 dev radminvpn0",
            "ip route replace default dev radminvpn0",
            "ip link set radminvpn0 netns 1",
            "sysctl -w kernel.core_pattern=/tmp/x",
            "nft flush ruleset", "iptables -F", "modprobe evil",
            "ip link delete radminvpn0 ; id",
            "ip link set radminvpn0 address 02:00:00:00:00:00;id",
        ]
        for call in calls:
            with self.subTest(call=call):
                self.assertFalse(helper.allowed(call.split()))


class Firewall(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = patch.object(helper, "STATE", Path(self.temp.name))
        self.state.start()

    def tearDown(self):
        self.state.stop()
        self.temp.cleanup()

    def test_preserves_existing_trusted_zone(self):
        def run(argv, check=True):
            text = "trusted\n" if "--get-zone-of-interface=radminvpn0" in argv else ""
            return subprocess.CompletedProcess(argv, 0, text, "")
        with patch.object(helper, "run", side_effect=run) as calls, patch.object(helper, "nft_rules", return_value=[]):
            helper.firewall_open()
            helper.firewall_close()
        self.assertFalse(any("--remove-interface=radminvpn0" in c.args[0] for c in calls.call_args_list))

    def test_restores_previous_zone(self):
        def run(argv, check=True):
            text = "public\n" if "--get-zone-of-interface=radminvpn0" in argv else ""
            return subprocess.CompletedProcess(argv, 0, text, "")
        with patch.object(helper, "run", side_effect=run) as calls, patch.object(helper, "nft_rules", return_value=[]):
            helper.firewall_open()
            helper.firewall_close()
        self.assertIn(["firewall-cmd", "--zone=public", "--change-interface=radminvpn0"], [c.args[0] for c in calls.call_args_list])

    def test_only_own_tagged_nft_rules_removed(self):
        rules = [{"rule": {"family": "inet", "table": "filter", "chain": "input", "handle": i, "comment": tag}} for i, tag in [(1, helper.TAG), (2, "other")]]
        with patch.object(helper, "nft_rules", return_value=rules), patch.object(helper, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as calls:
            helper.firewall_close()
        self.assertEqual(len(calls.call_args_list), 1)
        self.assertEqual(calls.call_args.args[0][-1], "1")


class UpstreamPatch(unittest.TestCase):
    def test_pinned_scripts_patch_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            scripts = runtime / "usr/bin"
            scripts.mkdir(parents=True)
            for name in ("run.sh", "lib.sh"):
                shutil.copyfile(ROOT / "tests/upstream" / name, scripts / name)
            patcher.patch(runtime)
            run = (scripts / "run.sh").read_text(encoding="utf-8")
            lib = (scripts / "lib.sh").read_text(encoding="utf-8")
            self.assertIn("trap 'exit 0' TERM INT", run)
            self.assertIn('wait "$SERVICE_PID"', run)
            self.assertNotIn("pkill -f", run)
            self.assertIn("sudo firewall open", lib)
            self.assertNotIn("sudo nft", lib)
            with self.assertRaises(ValueError):
                patcher.patch(runtime)


class Backend(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        status = patch.object(backend.Plugin, "installation_status", new=AsyncMock(return_value={"installing": False, "install_failed": False}))
        status.start()
        self.addCleanup(status.stop)

    async def test_missing_installation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(backend, "CONFIG", Path(temp)):
            status = await backend.Plugin().get_status()
        self.assertFalse(status["installed"])
        self.assertFalse(status["ready"])

    async def status(self, state, ready, configured=True):
        with tempfile.TemporaryDirectory() as temp:
            cfg = Path(temp)
            (cfg / "installed.json").write_text(json.dumps({"version": backend.SYSTEM_VERSION}))
            responses = [(0, f"LoadState=loaded\nActiveState={state}\n", ""), (0, json.dumps({"configured": configured, "ready": ready, "ip": "26.1.2.3"}), "")]
            with patch.object(backend, "CONFIG", cfg), patch.object(backend, "command", new=AsyncMock(side_effect=responses)):
                return await backend.Plugin().get_status()

    async def test_active_process_is_not_ready(self):
        result = await self.status("active", False)
        self.assertTrue(result["enabled"])
        self.assertFalse(result["ready"])

    async def test_stale_adapter_does_not_override_stopped_service(self):
        result = await self.status("inactive", True)
        self.assertFalse(result["ready"])
        self.assertEqual(result["ip"], "")

    async def test_ready(self):
        result = await self.status("active", True)
        self.assertTrue(result["ready"])
        self.assertEqual(result["ip"], "26.1.2.3")

    async def test_failed_has_error_message(self):
        result = await self.status("failed", False)
        self.assertIn("Ошибка", result["message"])

    async def test_rejects_non_boolean(self):
        with self.assertRaises(ValueError):
            await backend.Plugin().set_enabled("true")

    async def test_gui_mode_cannot_change_while_vpn_runs(self):
        with patch.object(backend.Plugin, "get_status", new=AsyncMock(return_value={"installed": True, "enabled": True, "state": "active"})):
            with self.assertRaisesRegex(RuntimeError, "Сначала выключите VPN"):
                await backend.Plugin().set_gui_mode(True)

    async def test_gui_mode_is_saved_without_changing_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = Path(temp)
            with patch.object(backend, "CONFIG", cfg), patch.object(backend.Plugin, "get_status", new=AsyncMock(side_effect=[{"installed": True, "enabled": False, "state": "inactive"}, {"gui_mode": True}])):
                result = await backend.Plugin().set_gui_mode(True)
            self.assertEqual(json.loads((cfg / "launch.json").read_text()), {"gui": True})
            self.assertTrue(result["gui_mode"])
            self.assertEqual([p.name for p in cfg.iterdir()], ["launch.json"])

    async def test_installation_progress_disables_vpn(self):
        with patch.object(backend.Plugin, "installation_status", new=AsyncMock(return_value={"installing": True, "install_failed": False})):
            status = await backend.Plugin().get_status()
        self.assertTrue(status["installing"])
        self.assertFalse(status["enabled"])
        self.assertFalse(status["ready"])

    async def test_repeated_install_click_does_not_start_second_job(self):
        with patch.object(backend.Plugin, "installation_status", new=AsyncMock(return_value={"installing": True, "install_failed": False})), patch.object(backend, "command", new=AsyncMock()) as command:
            result = await backend.Plugin().install_system()
        self.assertTrue(result["installing"])
        command.assert_not_awaited()

    async def test_only_fixed_actions(self):
        with self.assertRaises(ValueError):
            await backend.Plugin()._action("start; id")

    async def test_service_stop_uses_no_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = Path(temp)
            (cfg / "installed.json").write_text("{}")
            with patch.object(backend, "CONFIG", cfg), patch.object(backend, "command", new=AsyncMock(return_value=(0, "", ""))) as command, patch.object(backend.Plugin, "get_status", new=AsyncMock(return_value={})), patch.object(backend.asyncio, "sleep", new=AsyncMock()):
                await backend.Plugin().set_enabled(False)
                command.assert_awaited_once_with("/usr/bin/systemctl", "--no-block", "stop", backend.UNIT)

    async def test_uninstall_stops_installer_and_vpn(self):
        with patch.object(backend, "command", new=AsyncMock(return_value=(0, "", ""))) as command:
            await backend.Plugin()._uninstall()
        command.assert_awaited_once_with(backend.SYSTEMCTL, "--no-block", "stop", backend.INSTALL_UNIT, backend.UNIT, timeout=3)

    async def test_logs_include_service_diagnostics_before_system_journal(self):
        with patch.object(backend, "command", new=AsyncMock(side_effect=[(0, "journal text", ""), (0, "service diagnostic text", "")])) as command:
            result = await backend.Plugin().get_logs()
        self.assertLess(result.index("service diagnostic text"), result.index("journal text"))
        self.assertIn("deck", command.call_args_list[1].args)

    async def test_log_reader_failure_keeps_system_journal(self):
        with patch.object(backend, "command", new=AsyncMock(side_effect=[(0, "journal text", ""), (1, "", "diagnostic error")])):
            result = await backend.Plugin().get_logs()
        self.assertIn("journal text", result)
        self.assertIn("diagnostic error", result)

    async def test_concurrent_install_requests_start_one_job(self):
        started = False
        async def installation_status():
            return {"installing": started, "install_failed": False}
        async def command(*args, **kwargs):
            nonlocal started
            if args[0] == "/usr/bin/systemd-run":
                await asyncio.sleep(0)
                started = True
            return 0, "", ""
        with tempfile.TemporaryDirectory() as temp, patch.object(backend, "CONFIG", Path(temp)), patch.object(backend.Plugin, "installation_status", side_effect=installation_status), patch.object(backend, "command", new=AsyncMock(side_effect=command)) as calls:
            plugin = backend.Plugin()
            await asyncio.gather(plugin.install_system(), plugin.install_system())
        self.assertEqual(sum(c.args[0] == "/usr/bin/systemd-run" for c in calls.call_args_list), 1)

    async def test_broken_marker_is_repairable(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = Path(temp)
            (cfg / "installed.json").write_text("broken json")
            with patch.object(backend, "CONFIG", cfg):
                result = await backend.Plugin().get_status()
        self.assertFalse(result["installed"])


class SafeCleanup(unittest.TestCase):
    def call_cleanup(self, lockfile, blocked=False, firewall_error=False):
        fcntl = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=Mock(side_effect=BlockingIOError() if blocked else None))
        pwd = SimpleNamespace(getpwnam=lambda name: SimpleNamespace(pw_uid=lockfile.stat().st_uid))
        with patch.dict(sys.modules, {"fcntl": fcntl, "pwd": pwd}), patch.object(helper.os, "O_NOFOLLOW", getattr(helper.os, "O_NOFOLLOW", 0), create=True), patch.object(helper, "DATA_LOCK", lockfile), patch.object(helper, "STATE", lockfile.parent), patch.object(helper, "session_owned", return_value=True), patch.object(helper, "firewall_close", side_effect=RuntimeError("firewall error") if firewall_error else None) as close, patch.object(helper, "run") as run:
            if firewall_error:
                with self.assertRaises(RuntimeError):
                    helper.cleanup_if_idle()
            else:
                helper.cleanup_if_idle()
            return close, run

    def test_other_launcher_is_never_disconnected(self):
        with tempfile.TemporaryDirectory() as temp:
            lockfile = Path(temp) / ".lock"
            lockfile.touch()
            close, run = self.call_cleanup(lockfile, blocked=True)
        close.assert_not_called()
        run.assert_not_called()

    def test_idle_cleanup_removes_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            lockfile = Path(temp) / ".lock"
            lockfile.touch()
            close, run = self.call_cleanup(lockfile)
        close.assert_called_once()
        run.assert_called_once_with(["ip", "link", "delete", "radminvpn0"], check=False)

    def test_firewall_error_still_removes_idle_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            lockfile = Path(temp) / ".lock"
            lockfile.touch()
            _, run = self.call_cleanup(lockfile, firewall_error=True)
        run.assert_called_once_with(["ip", "link", "delete", "radminvpn0"], check=False)


class ProbeReadiness(unittest.TestCase):
    def test_adapter_without_route_is_not_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp)
            log = prefix / "drive_c/ProgramData/Famatech/Radmin VPN/service.log"
            log.parent.mkdir(parents=True)
            log.write_text("adapter ready", encoding="utf-16-le")
            addresses = [{"addr_info": [{"local": "26.1.2.3"}]}]
            with patch.object(probe, "PREFIX", prefix), patch.object(probe, "json_command", side_effect=[addresses, []]):
                result = probe.probe()
        self.assertFalse(result["ready"])

    def test_missing_service_log_during_launch_is_not_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(probe, "PREFIX", Path(temp)), patch.object(probe, "json_command", side_effect=[[{"addr_info": [{"local": "26.1.2.3"}]}], [{"dst": "26.0.0.0/8", "dev": "radminvpn0"}]]):
                result = probe.probe()
        self.assertFalse(result["ready"])


class FirewallRecovery(unittest.TestCase):
    def test_already_flushed_iptables_rule_does_not_block_next_start(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(helper, "STATE", Path(temp)), patch.object(helper, "nft_rules", return_value=[]):
            helper.save_state({"iptables": ["iptables"]})
            with patch.object(helper, "run", return_value=subprocess.CompletedProcess([], 1, "", "missing")) as run:
                helper.firewall_close()
            self.assertFalse((Path(temp) / "firewall.json").exists())
            self.assertEqual(run.call_args.args[0][1], "-C")

    def test_nft_inspection_error_is_reported(self):
        with patch.object(helper, "run", return_value=subprocess.CompletedProcess([], 1, "", "nft error")):
            with self.assertRaisesRegex(RuntimeError, "nft error"):
                helper.nft_rules()


class SessionOwnership(unittest.TestCase):
    def test_existing_adapter_is_not_claimed_or_deleted(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(helper, "STATE", Path(temp)), patch.object(helper, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                helper.session_begin("a" * 32)
            self.assertFalse((Path(temp) / "session").exists())
        self.assertEqual(run.call_args.args[0], ["ip", "link", "show", "dev", "radminvpn0"])

    def test_failed_new_session_cannot_clean_up_previous_owner(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(helper, "STATE", Path(temp)), patch.object(helper, "firewall_close") as close, patch.object(helper, "run") as run:
            (Path(temp) / "session").write_text("a" * 32, encoding="ascii")
            helper.session_end("b" * 32)
            close.assert_not_called()
            run.assert_not_called()
            self.assertEqual((Path(temp) / "session").read_text(), "a" * 32)

    def test_claim_and_release_own_session(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(helper, "STATE", Path(temp)), patch.object(helper, "firewall_close") as close, patch.object(helper, "run", return_value=subprocess.CompletedProcess([], 1, "", "")) as run:
            helper.session_begin("a" * 32)
            self.assertTrue(helper.session_owned("a" * 32))
            helper.session_end("a" * 32)
            self.assertFalse((Path(temp) / "session").exists())
            close.assert_called_once()
            self.assertEqual(run.call_args.args[0], ["ip", "link", "delete", "radminvpn0"])


if __name__ == "__main__":
    unittest.main()
