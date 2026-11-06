"""Create a desktop installer bundle and a complete Decky-installable ZIP."""
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"
VERSION = "0.1.6"


def add(archive, file, name):
    info = zipfile.ZipInfo(name, (2026, 11, 4, 12, 0, 0))
    info.create_system = 3
    mode = 0o755 if file.suffix == ".sh" or file.name == "sudo" else 0o644
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, file.read_bytes())


def main():
    if not (ROOT / "dist/index.js").is_file():
        raise RuntimeError("Build frontend first")
    RELEASE.mkdir(exist_ok=True)
    files = ["main.py", "plugin.json", "package.json", "pnpm-lock.yaml", "rollup.config.js",
             "tsconfig.json", "LICENSE", "THIRD_PARTY.md", "README.md", "CHECK_REPORT.md", "install.sh", "dist/index.js", "dist/index.js.map"]
    paths = [ROOT / f for f in files]
    for folder in ("src", "system", "scripts", "tests"):
        paths += [p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    with zipfile.ZipFile(RELEASE / f"Radmin-Decky-{VERSION}-SteamDeck.zip", "w") as archive:
        for file in sorted(paths):
            add(archive, file, f"Radmin-Decky-{VERSION}/{file.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(RELEASE / f"Radmin-VPN-{VERSION}-Decky.zip", "w") as archive:
        for file in sorted(paths):
            if "tests" not in file.relative_to(ROOT).parts:
                add(archive, file, f"Radmin VPN/{file.relative_to(ROOT).as_posix()}")
    sums = []
    for file in sorted(RELEASE.glob("*.zip")):
        sums.append(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}")
        print(f"{file.name}: {file.stat().st_size} bytes")
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
