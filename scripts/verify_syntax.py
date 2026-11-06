"""Python AST and real bash -n checks. Set BASH_CHECK for portable Bash on Windows."""
import ast
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("BASH_CHECK") or shutil.which("bash")
if not BASH:
    raise RuntimeError("Bash required for syntax verification")
checked = []
for folder in (ROOT, ROOT / "scripts", ROOT / "system", ROOT / "tests"):
    for file in folder.glob("*.py"):
        ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        checked.append(file.name)


def bash(file):
    result = subprocess.run([BASH, "--noprofile", "--norc", "-n", str(file)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"Bash syntax error in {file}: {result.stderr}")
    checked.append(file.name)


for file in [ROOT / "install.sh", ROOT / "system/sudo", *ROOT.glob("scripts/*.sh"), *ROOT.glob("system/*.sh")]:
    bash(file)
spec = importlib.util.spec_from_file_location("patcher", ROOT / "scripts/patch_runtime.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)
with tempfile.TemporaryDirectory() as temp:
    runtime = Path(temp)
    scripts = runtime / "usr/bin"
    scripts.mkdir(parents=True)
    for name in ("run.sh", "lib.sh"):
        shutil.copyfile(ROOT / "tests/upstream" / name, scripts / name)
    patcher.patch(runtime)
    for file in scripts.iterdir():
        bash(file)
print(f"Syntax OK: {len(checked)} Python/Bash files, including patched upstream scripts")
