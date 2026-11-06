"""Small fail-closed patch against radmin-vpn-linux v1.1.1 scripts."""
from pathlib import Path
import sys


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


if __name__ == "__main__":
    patch(Path(sys.argv[1]))
