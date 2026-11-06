"""Read bounded VPN diagnostics as deck; no configuration/registry/password reads."""
import datetime
import os
from pathlib import Path
import stat
import subprocess

DATA = Path("/home/deck/.local/share/radmin-vpn-linux")


def tail(path, encoding="utf-8", max_chars=5000):
    path = Path(path)
    try:
        if path.is_symlink():
            return "Skipped symbolic link"
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return "Skipped non-regular file"
            start = max(0, info.st_size - 32768)
            if encoding == "utf-16-le":
                start = start // 2 * 2
            stream.seek(start)
            body = stream.read(32768).decode(encoding, errors="replace")
        modified = datetime.datetime.fromtimestamp(info.st_mtime, datetime.timezone.utc).isoformat()
        return f"Updated UTC: {modified}\n" + "\n".join(body.splitlines()[-60:])[-max_chars:]
    except OSError as error:
        return f"Unavailable: {error.strerror or error}"


def command(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=4,
                                env={"PATH": "/usr/bin:/usr/sbin", "LANG": "C.UTF-8"})
        return (result.stdout or result.stderr).strip()[-4000:]
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)


def report():
    service = DATA / "wineprefix/drive_c/ProgramData/Famatech/Radmin VPN/service.log"
    sections = [
        ("RADMIN SERVICE LOG (connection state)", tail(service, "utf-16-le", 7000)),
        ("CURRENT LAUNCHER LOG", tail(DATA / "run.log", max_chars=3500)),
        ("WINE SERVICE OUTPUT", tail("/tmp/radmin_service.log", max_chars=2500)),
        ("RADMIN GUI OUTPUT", tail("/tmp/radmin_gui.log", max_chars=2000)),
        ("BRIDGE LOG", tail("/tmp/radmin_bridge.log", max_chars=1800)),
        ("SERVICE HOOK LOG", tail(DATA / "wineprefix/drive_c/radmin_hook_debug.log", max_chars=2000)),
        ("VPN ADAPTER", command("/usr/bin/ip", "-br", "addr", "show", "dev", "radminvpn0")),
        ("VPN ROUTES", command("/usr/bin/ip", "-4", "route", "show", "dev", "radminvpn0")),
    ]
    sockets = command("/usr/bin/ss", "-tnp")
    relevant = [line for line in sockets.splitlines() if any(s in line.lower() for s in ("wine", "rvcontrol", "rvpn"))]
    sections.append(("WINE TCP CONNECTIONS", "\n".join(relevant)[-2000:] or "No matching connections visible"))
    return "\n\n".join(f"=== {name} ===\n{body}" for name, body in sections)


if __name__ == "__main__":
    print(report())
