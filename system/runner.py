#!/usr/bin/python3
"""Unprivileged supervisor for the pinned, adapted upstream runtime."""
import fcntl
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys
import uuid
import json

BASE = Path("/etc/radmin-decky")
RUNTIME = Path("/home/deck/homebrew/data/radmin-decky-runtime")
DATA = Path("/home/deck/.local/share/radmin-vpn-linux")


def session_environment(env):
    keys = {"DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"}
    # Steam's actual process environment follows Desktop/Gaming Mode changes.
    for proc in Path("/proc").iterdir():
        try:
            if not proc.name.isdigit() or proc.stat().st_uid != os.getuid():
                continue
            if (proc / "comm").read_text().strip() != "steam":
                continue
            values = dict(part.split("=", 1) for part in (proc / "environ").read_bytes().decode(errors="replace").split("\0") if "=" in part)
            if values.get("DISPLAY"):
                env.update({k: v for k, v in values.items() if k in keys})
                return
        except (OSError, ValueError):
            continue
    try:
        result = subprocess.run(["/usr/bin/systemctl", "--user", "show-environment"],
                                capture_output=True, text=True, timeout=5, env=env)
        session = result.stdout
    except (OSError, subprocess.TimeoutExpired):
        session = ""
    for line in session.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in keys:
            env[key] = value
    env.setdefault("DISPLAY", ":0")
    authority = Path("/home/deck/.Xauthority")
    if authority.is_file():
        env.setdefault("XAUTHORITY", str(authority))


def main():
    if os.getuid() != pwd.getpwnam("deck").pw_uid:
        raise RuntimeError("Run as deck, never as root")
    if sys.argv[1:] not in ([], ["--configure"]):
        raise RuntimeError("Usage: runner.py [--configure]")
    configure = sys.argv[1:] == ["--configure"]
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Radmin already running. Turn off the Decky switch or close the desktop AppImage first.")
        exe = DATA / "wineprefix/drive_c/Program Files (x86)/Radmin VPN/RvControlSvc.exe"
        if not configure and not exe.is_file():
            raise RuntimeError("First open 'Configure Radmin VPN' on the Desktop and join your networks.")
        env = os.environ.copy()
        env.update({
            "HOME": "/home/deck", "USER": "deck", "LOGNAME": "deck",
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
            "PATH": f"{BASE}/shim:{RUNTIME}/wine/bin:/usr/bin:/usr/sbin",
            "WINEPREFIX": str(DATA / "wineprefix"),
            "WINELOADER": str(RUNTIME / "wine/bin/wine"),
            "WINESERVER": str(RUNTIME / "wine/bin/wineserver"),
            "BUILD_DIR": str(RUNTIME / "usr/lib/radmin-vpn"),
            "RADMIN_DATA_DIR": str(DATA), "RADMIN_SUDO_PRIMED": "1",
            "APPIMAGE": str(RUNTIME / "AppRun"),
            "PYTHONUNBUFFERED": "1", "RVPN_DEBUG": "0",
        })
        # No optional host injection into the dedicated Wine runtime.
        for key in ("LD_PRELOAD", "LD_LIBRARY_PATH", "WINEARCH", "WINEDLLOVERRIDES",
                    "RADMIN_INSTALLER_URL", "RADMIN_VERSION", "RADMIN_SHA256"):
            env.pop(key, None)
        if not configure:
            session_environment(env)
        token = env.get("INVOCATION_ID") or uuid.uuid4().hex
        helper = str(BASE / "shim/sudo")
        subprocess.run([helper, "session-begin", token], env=env, check=True)
        try:
            return supervise(env, configure)
        finally:
            # The token prevents a failed launch from cleaning up another VPN.
            subprocess.run([helper, "session-end", token], env=env, check=False)


def launch_arguments(configure):
    window = configure
    if not window:
        try:
            window = json.loads((BASE / "launch.json").read_text(encoding="utf-8")).get("gui") is True
        except (OSError, ValueError, AttributeError):
            window = False
    args = ["/bin/bash", str(RUNTIME / "usr/bin/run.sh")]
    if not window:
        args.append("--no-ui")
    return args


def supervise(env, configure):
    log = DATA / "run.log"
    if log.exists():
        log.replace(DATA / "run.previous.log")
    args = launch_arguments(configure)
    mode = "configuration" if configure else "with Radmin GUI" if "--no-ui" not in args else "headless"
    print(f"Radmin Decky: {mode} launch, DISPLAY={env.get('DISPLAY', '(unset)')}", flush=True)
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(args, env=env, cwd=DATA, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        def stop(signum, frame):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        for line in process.stdout:
            output.write(line)
            output.flush()
            print(line, end="", flush=True)
        return process.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"Radmin Decky: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
