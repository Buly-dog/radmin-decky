"""Decky root backend. Accepts only fixed service actions; never shell strings."""
import asyncio
import json
from pathlib import Path

UNIT = "radmin-decky.service"
SYSTEMCTL = "/usr/bin/systemctl"
CONFIG = Path("/etc/radmin-decky")
INSTALL_UNIT = "radmin-decky-install.service"
SYSTEM_VERSION = "0.1.6"


def gui_mode():
    try:
        return json.loads((CONFIG / "launch.json").read_text(encoding="utf-8")).get("gui") is True
    except (OSError, ValueError, AttributeError):
        return False


def system_current():
    try:
        return json.loads((CONFIG / "installed.json").read_text(encoding="utf-8")).get("version") == SYSTEM_VERSION
    except (OSError, ValueError, AttributeError):
        return False


async def command(*args, timeout=12):
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={"PATH": "/usr/bin:/usr/sbin", "LANG": "C.UTF-8"})
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError("Команда не ответила вовремя. Откройте журнал VPN.")
    return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


class Plugin:
    async def set_gui_mode(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Expected boolean")
        status = await self.get_status()
        if not status["installed"]:
            raise RuntimeError("Сначала установите компоненты VPN")
        if status["enabled"] or status["state"] == "deactivating":
            raise RuntimeError("Сначала выключите VPN, затем измените режим запуска")
        temporary = CONFIG / "launch.json.new"
        temporary.write_text(json.dumps({"gui": enabled}), encoding="utf-8")
        temporary.chmod(0o644)
        temporary.replace(CONFIG / "launch.json")
        return await self.get_status()

    async def installation_status(self):
        _, output, _ = await command(SYSTEMCTL, "show", INSTALL_UNIT, "--property=ActiveState,Result", "--no-pager")
        props = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        return {"installing": props.get("ActiveState") in ("active", "activating", "deactivating"),
                "install_failed": props.get("ActiveState") == "failed"}

    async def install_system(self):
        if not hasattr(self, "_install_lock"):
            self._install_lock = asyncio.Lock()
        async with self._install_lock:
            return await self._install_system()

    async def _install_system(self):
        state = await self.installation_status()
        if state["installing"]:
            return await self.get_status()
        if system_current() and (await self.get_status())["installed"]:
            return await self.get_status()
        script = Path(__file__).resolve().parent / "scripts/install_game.py"
        if not script.is_file():
            raise RuntimeError("Нужен полный ZIP версии 0.1.1 или новее")
        await command(SYSTEMCTL, "reset-failed", INSTALL_UNIT)
        rc, _, error = await command("/usr/bin/systemd-run", "--unit=radmin-decky-install",
                                      "--property=Type=exec", "--property=RuntimeMaxSec=20min",
                                      "--", "/usr/bin/python3", "-I", str(script))
        if rc:
            raise RuntimeError(error.strip() or "Не удалось запустить установку")
        return await self.get_status()

    async def get_status(self):
        base = {"installed": False, "configured": False, "state": "missing",
                "ready": False, "ip": "", "enabled": False, "gui_mode": gui_mode(),
                "message": "Нажмите «Установить компоненты VPN». Потребуется загрузить около 178 МБ."}
        base.update(await self.installation_status())
        if base["installing"]:
            base["message"] = "Устанавливаются компоненты VPN. Это может занять несколько минут; ход установки — в журнале."
            return base
        if base["install_failed"]:
            base["message"] = "Установка не удалась. Откройте журнал, затем можно повторить установку."
        if not system_current():
            return base
        rc, output, error = await command(SYSTEMCTL, "show", UNIT, "--no-pager",
                                          "--property=ActiveState,SubState,Result,LoadState")
        if rc:
            raise RuntimeError(error.strip() or "Не удалось проверить службу")
        props = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if props.get("LoadState") != "loaded":
            return base
        runuser = "/usr/bin/runuser" if Path("/usr/bin/runuser").exists() else "/usr/sbin/runuser"
        rc, output, error = await command(runuser, "-u", "deck", "--", "/usr/bin/python3", "-I", str(CONFIG / "probe.py"))
        if rc:
            raise RuntimeError(error.strip() or "Не удалось прочитать состояние VPN")
        probe = json.loads(output)
        state = props.get("ActiveState", "unknown")
        enabled = state in ("active", "activating", "reloading")
        ready = enabled and probe["ready"]
        if not probe["configured"]:
            message = "Сначала настройте сети Radmin: откройте «Настроить Radmin VPN» на рабочем столе."
        elif ready:
            message = "Адаптер и маршрут готовы. Подключение Radmin к участникам сети пока не проверено."
        elif state == "failed":
            message = "Ошибка запуска. Откройте журнал VPN."
        elif enabled:
            message = "Запускается / ожидает подключения. Если статус не меняется, откройте журнал."
        elif state == "deactivating":
            message = "Останавливается…"
        else:
            message = "VPN выключен."
        return {**base, "installed": True, "configured": probe["configured"],
                "state": state, "enabled": enabled, "ready": ready,
                "ip": probe["ip"] if ready else "", "message": message}

    async def _action(self, action):
        if action not in ("start", "stop", "restart"):
            raise ValueError("Unknown action")
        if not (CONFIG / "installed.json").is_file():
            raise RuntimeError("Сначала нажмите «Установить компоненты VPN»")
        rc, _, error = await command(SYSTEMCTL, "--no-block", action, UNIT)
        if rc:
            raise RuntimeError(error.strip() or "Не удалось управлять службой")
        await asyncio.sleep(0.25)
        return await self.get_status()

    async def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Expected boolean")
        if enabled and not (await self.get_status())["configured"]:
            raise RuntimeError("Сначала настройте Radmin на рабочем столе")
        return await self._action("start" if enabled else "stop")

    async def restart(self):
        return await self._action("restart")

    async def get_logs(self):
        rc, out, err = await command("/usr/bin/journalctl", "-u", UNIT, "-u", INSTALL_UNIT, "-n", "100", "--no-pager", "-o", "short-iso")
        journal = out[-12000:] if not rc else err.strip() or "Журнал запуска недоступен"
        runuser = "/usr/bin/runuser" if Path("/usr/bin/runuser").exists() else "/usr/sbin/runuser"
        script = Path(__file__).resolve().parent / "scripts/diagnostics.py"
        rc, diagnostics, error = await command(runuser, "-u", "deck", "--", "/usr/bin/python3", "-I", str(script), timeout=20)
        if rc:
            diagnostics = error.strip() or "Диагностика Radmin недоступна"
        import re
        return re.sub(r"\x1b\[[0-9;]*m", "", diagnostics[:20000] + "\n\n=== SYSTEM JOURNAL ===\n" + journal)

    async def _main(self):
        pass

    async def _unload(self):
        # A Decky restart must not interrupt a running game/VPN.
        pass

    async def _uninstall(self):
        # Decky gives unload hooks only a few seconds. Queue both stops without
        # waiting; systemd owns their completion and kills installer children.
        await command(SYSTEMCTL, "--no-block", "stop", INSTALL_UNIT, UNIT, timeout=3)
