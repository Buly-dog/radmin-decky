"""Check the final Decky ZIP using the loader's top-level plugin.json convention."""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
file = ROOT / "release" / f"Radmin-VPN-{version}-Decky.zip"
with zipfile.ZipFile(file) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert len(names) == len(set(names)), "Duplicate ZIP paths"
    manifests = [n for n in names if n.endswith("/plugin.json") and n.count("/") == 1]
    assert manifests == ["Radmin VPN/plugin.json"], manifests
    for name in names:
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert path.parts[0] == "Radmin VPN"
        assert not any(p in path.parts for p in (".tools", ".test-data", "node_modules", "__pycache__"))
        if name.endswith(".sh") or name.endswith("/system/sudo"):
            assert b"\r\n" not in archive.read(name), f"Windows newlines: {name}"
            assert (archive.getinfo(name).external_attr >> 16) & 0o111, f"Missing executable mode: {name}"
    manifest = json.loads(archive.read(manifests[0]))
    assert manifest["name"] == "Radmin VPN" and manifest["flags"] == ["root"] and manifest["api_version"] == 1
    assert json.loads(archive.read("Radmin VPN/package.json"))["version"] == version
    required = ["main.py", "dist/index.js", "dist/index.js.map", "CHECK_REPORT.md",
                "system/net_helper.py", "system/runner.py", "system/probe.py", "system/sudo",
                "system/configure.sh", "system/radmin-decky.service", "scripts/install_game.py",
                "scripts/prepare-runtime.sh", "scripts/patch_runtime.py", "scripts/install-root.sh",
                "scripts/uninstall-root.sh", "scripts/sudo_policy.py", "scripts/runtime_access.py", "scripts/diagnostics.py"]
    for name in required:
        assert f"Radmin VPN/{name}" in names, f"Missing {name}"
    assert b"cleanup-if-idle" in archive.read("Radmin VPN/system/radmin-decky.service")
    system_version = re.search(rb'SYSTEM_VERSION = "([0-9.]+)"', archive.read("Radmin VPN/main.py")).group(1).decode()
    assert f'"version":"{system_version}"'.encode() in archive.read("Radmin VPN/scripts/install-root.sh")
    assert b"sudo -k -n" in archive.read("Radmin VPN/scripts/install-root.sh")
    assert b"chmod -R u=rwX,go=rX" in archive.read("Radmin VPN/scripts/install-root.sh")
digest = hashlib.sha256(file.read_bytes()).hexdigest()
assert f"{digest}  {file.name}" in (ROOT / "release/SHA256SUMS.txt").read_text()
print(f"Decky ZIP OK: version {version}, {len(names)} files, {file.stat().st_size} bytes")
print(f"SHA-256: {digest}")
