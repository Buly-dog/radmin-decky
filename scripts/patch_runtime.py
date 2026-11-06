"""Small fail-closed patch against radmin-vpn-linux v1.1.1 scripts."""
from pathlib import Path
import stat
import sys
import tempfile


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Unsupported upstream script: expected exactly one {old[:70]!r}")
    return text.replace(old, new, 1)


def patch(runtime):
    path = runtime / "usr/bin/run.sh"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "trap cleanup EXIT", "trap cleanup EXIT\ntrap 'exit 0' TERM INT")
    text = replace_once(text, 'pkill -f "RvControlSvc|RvRvpnGui|rvpn_launcher" 2>/dev/null || true', "# Decky: wineserver -k below is scoped to this prefix; never pkill other apps.")
    text = replace_once(text, "pkill -f tap_bridge 2>/dev/null || true", "# Decky: systemd owns the bridge lifetime.")
    text = replace_once(text, ") > /tmp/radmin_service.log 2>&1 &", ") > /tmp/radmin_service.log 2>&1 &\nSERVICE_PID=$!")
    text = replace_once(text, "    wait || true", '    wait "$SERVICE_PID" || { tail -n 40 /tmp/radmin_service.log >&2; exit 1; }\n    echo "Radmin service exited unexpectedly" >&2\n    exit 1')
    path.write_text(text, encoding="utf-8", newline="\n")
    lib = runtime / "usr/bin/lib.sh"
    text = lib.read_text(encoding="utf-8")
    start = text.index("_nft_input_chains() {")
    end = text.index("# True when $1 is strictly newer", start)
    if text[start:end].count("firewall_close() {") != 1:
        raise ValueError("Unsupported firewall functions")
    text = text[:start] + '''firewall_open() {
    sudo firewall open || die "Decky firewall setup failed"
    echo "Decky adapter rules"
}

firewall_close() {
    sudo firewall close
}

''' + text[end:]
    lib.write_text(text, encoding="utf-8", newline="\n")


def upgrade_gui(runtime):
    path = runtime / "usr/bin/run.sh"
    if path.is_symlink():
        raise ValueError("Refusing symlink at run.sh")
    text = path.read_text(encoding="utf-8")
    old = '    [ "$_gui_rc" -eq 0 ] && break          # user closed the window → normal exit'
    new = """    if [ "$_gui_rc" -eq 0 ]; then
        if [ "${RADMIN_DECKY_KEEP_RUNNING:-0}" = 1 ]; then
            say "Radmin GUI exited normally; VPN service remains active"
            GUI_PID=""
        fi
        break
    fi"""
    if text.count(new) == 1 and old not in text:
        return
    if 'wait "$SERVICE_PID"' not in text:
        raise ValueError("Expected the Decky runtime with service supervision")
    text = replace_once(text, old, new)
    text = replace_once(text, 'good "Radmin VPN running — close the GUI or press Ctrl+C to stop."', """if [ "${RADMIN_DECKY_KEEP_RUNNING:-0}" = 1 ]; then
    good "Radmin VPN running — stop it from Decky."
else
    good "Radmin VPN running — close the GUI or press Ctrl+C to stop."
fi""")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                     dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        temporary.chmod(stat.S_IMODE(path.stat().st_mode))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--upgrade-gui":
        upgrade_gui(Path(sys.argv[2]))
    else:
        patch(Path(sys.argv[1]))
