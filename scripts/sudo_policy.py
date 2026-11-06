"""Place our narrow include after distro rules; validate and replace atomically."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BEGIN = "# BEGIN RADMIN_DECKY MANAGED INCLUDE"
END = "# END RADMIN_DECKY MANAGED INCLUDE"
INCLUDE = "@include /etc/sudoers.d/radmin-decky"


def update_text(text, install):
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError("Malformed Radmin managed block; refusing to change sudoers")
    if BEGIN in text:
        start = text.index(BEGIN)
        end = text.index(END) + len(END)
        if end < start:
            raise ValueError("Malformed Radmin block")
        if end < len(text) and text[end] == "\n":
            end += 1
        text = text[:start] + text[end:]
    if install:
        text = text.rstrip("\n") + "\n\n" + BEGIN + "\n" + INCLUDE + "\n" + END + "\n"
    return text


def apply(install, path=Path("/etc/sudoers"), backup=Path("/etc/radmin-decky/sudoers.before-radmin-decky")):
    if path.is_symlink():
        raise RuntimeError("Refusing symlink at /etc/sudoers")
    original = path.read_bytes()
    updated = update_text(original.decode("utf-8"), install).encode("utf-8")
    if updated == original:
        return
    metadata = path.stat()
    visudo = shutil.which("visudo", path="/usr/bin:/usr/sbin")
    if not visudo:
        raise RuntimeError("visudo is required")
    if install and not backup.exists():
        backup.write_bytes(original)
        backup.chmod(0o600)
    descriptor, name = tempfile.mkstemp(prefix=".sudoers-radmin-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        temporary.chmod(metadata.st_mode & 0o777)
        subprocess.run([visudo, "-cf", str(temporary)], check=True)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    if os.geteuid() != 0 or sys.argv[1:] not in (["--install"], ["--remove"]):
        raise SystemExit("Usage as root: sudo_policy.py --install|--remove")
    apply(sys.argv[1] == "--install")
