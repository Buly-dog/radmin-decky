"""Runs as deck, never root. Local readiness, not peer connectivity."""
import json
from pathlib import Path
import subprocess

DATA = Path("/home/deck/.local/share/radmin-vpn-linux")
PREFIX = DATA / "wineprefix"


def json_command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=4)
    return json.loads(result.stdout) if result.returncode == 0 else []


def probe():
    configured = (PREFIX / "drive_c/Program Files (x86)/Radmin VPN/RvControlSvc.exe").is_file()
    ip = ""
    for interface in json_command("/usr/bin/ip", "-j", "-4", "addr", "show", "dev", "radminvpn0"):
        for addr in interface.get("addr_info", []):
            if addr.get("local", "").startswith("26."):
                ip = addr["local"]
    routes = json_command("/usr/bin/ip", "-j", "-4", "route", "show", "26.0.0.0/8")
    routed = any(r.get("dev") == "radminvpn0" and r.get("dst") == "26.0.0.0/8" for r in routes)
    log = PREFIX / "drive_c/ProgramData/Famatech/Radmin VPN/service.log"
    ready_log = False
    try:
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 32768) // 2 * 2)
            ready_log = "adapter ready" in stream.read(32768).decode("utf-16-le", errors="replace")
    except OSError:
        pass  # A fresh launch truncates/recreates the service log.
    return {"configured": configured, "ready": bool(ip and routed and ready_log), "ip": ip}


if __name__ == "__main__":
    print(json.dumps(probe()))
