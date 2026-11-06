"""Run as deck: verify the installed runtime is readable and native binaries load."""
import os
from pathlib import Path
import subprocess
import sys


def verify(root):
    root = Path(root)
    def walk_error(error):
        raise RuntimeError(f"Runtime directory is inaccessible: {error.filename}") from error
    for directory, _, files in os.walk(root, onerror=walk_error, followlinks=False):
        if not os.access(directory, os.R_OK | os.X_OK):
            raise RuntimeError(f"Runtime directory cannot be traversed: {directory}")
        for name in files:
            file = Path(directory) / name
            if not file.is_symlink() and not os.access(file, os.R_OK):
                raise RuntimeError(f"Runtime file cannot be read by deck: {file}")
    for relative in ("usr/bin/run.sh", "usr/bin/lib.sh", "usr/bin/patch_qwindows_font.py"):
        with (root / relative).open("rb") as stream:
            stream.read(1)
    for relative in ("wine/bin/wine", "wine/bin/wineserver", "usr/lib/radmin-vpn/tap_bridge"):
        file = root / relative
        if not file.is_file() or not os.access(file, os.R_OK | os.X_OK):
            raise RuntimeError(f"Runtime binary cannot be executed by deck: {file}")
    env = {"PATH": "/usr/bin:/usr/sbin", "HOME": "/home/deck", "LANG": "C.UTF-8"}
    subprocess.run(["/bin/bash", "-n", str(root / "usr/bin/run.sh")], env=env, check=True, timeout=15)
    for binary in ("wine", "wineserver"):
        result = subprocess.run([str(root / "wine/bin" / binary), "--version"], env=env,
                                capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError(f"{binary} cannot load as deck: {result.stderr.strip()}")
        print(result.stdout.strip() or result.stderr.strip(), flush=True)
    print("Runtime readability and Wine execution verified as deck.", flush=True)


if __name__ == "__main__":
    verify(sys.argv[1])
