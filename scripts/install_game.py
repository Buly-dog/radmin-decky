"""Runs in a dedicated root systemd unit. Runtime preparation runs as deck."""
import fcntl
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tempfile
import signal

SOURCE = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(args, check=True, env={"PATH": "/usr/bin:/usr/sbin", "HOME": "/home/deck", "LANG": "C.UTF-8"})


def main():
    if os.geteuid() != 0 or os.uname().machine != "x86_64":
        raise RuntimeError("Steam Deck x86_64 and root Decky backend required")
    user = pwd.getpwnam("deck")
    def interrupted(signum, frame):
        raise SystemExit("Installation cancelled")
    signal.signal(signal.SIGTERM, interrupted)
    runuser = "/usr/bin/runuser" if Path("/usr/bin/runuser").exists() else "/usr/sbin/runuser"
    for name in ("curl", "sha256sum", "flock", "visudo", "ip"):
        if not shutil.which(name, path="/usr/bin:/usr/sbin"):
            raise RuntimeError(f"Missing required command: {name}")
    # Updating components is an explicit action; stop our existing service first.
    loaded = subprocess.run(["/usr/bin/systemctl", "show", "radmin-decky.service", "--property=LoadState", "--value"], capture_output=True, text=True, timeout=10)
    if loaded.stdout.strip() == "loaded":
        run("/usr/bin/systemctl", "stop", "radmin-decky.service")
    assets = Path("/home/deck/homebrew/data/radmin-decky-runtime")
    if Path("/etc/radmin-decky/installed.json").is_file() and (assets / "wine/bin/wine").is_file():
        print("Updating system component using the existing Wine runtime...", flush=True)
        run("/bin/bash", str(SOURCE / "scripts/install-root.sh"), str(SOURCE), str(assets), "--system-only")
        return
    cache = Path("/home/deck/.cache")
    run(runuser, "-u", "deck", "--", "/usr/bin/mkdir", "-p", str(cache))
    if shutil.disk_usage(cache).free < 3 * 1024**3:
        raise RuntimeError("At least 3 GiB free space is required for runtime preparation and backup")
    work = Path(tempfile.mkdtemp(prefix="radmin-decky-install.", dir=cache))
    os.chown(work, user.pw_uid, user.pw_gid)
    try:
        run(runuser, "-u", "deck", "--", "/bin/bash", str(SOURCE / "scripts/prepare-runtime.sh"), str(SOURCE), str(work))
        # Do not let another launcher modify the prefix during the system install.
        fd = os.open("/home/deck/.local/share/radmin-vpn-linux/.lock", os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, "r+") as lock:
            info = os.fstat(lock.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != user.pw_uid:
                raise RuntimeError("Unexpected owner/type of the Radmin lock")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run("/bin/bash", str(SOURCE / "scripts/install-root.sh"), str(SOURCE), str(work / "squashfs-root"), "--system-only")
        print("System component installed. Return to the plugin and refresh status.", flush=True)
    finally:
        shutil.rmtree(work)


if __name__ == "__main__":
    main()
