#!/usr/bin/python3
"""Device-scoped privileged operations. Never executes caller-supplied shell code."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

DEV = "radminvpn0"
TAG = "radmin-decky"
STATE = Path("/run/radmin-decky")
DATA_LOCK = Path("/home/deck/.local/share/radmin-vpn-linux/.lock")


def allowed(argv):
    fixed = [
        ["modprobe", "tun"],
        ["nmcli", "device", "set", DEV, "managed", "no"],
        ["ip", "link", "delete", DEV],
        ["ip", "tuntap", "add", "dev", DEV, "mode", "tap", "user", "deck"],
        ["ip", "link", "set", DEV, "up"],
        ["ip", "link", "set", DEV, "multicast", "on"],
        ["ip", "link", "set", DEV, "allmulticast", "on"],
        ["ip", "addr", "flush", "dev", DEV],
        ["ip", "maddr", "add", "224.0.2.60", "dev", DEV],
        ["ip", "route", "add", "224.0.2.60/32", "dev", DEV],
        ["ip", "route", "replace", "26.0.0.0/8", "dev", DEV],
        ["ip", "route", "append", "255.255.255.255/32", "dev", DEV, "metric", "0"],
        ["ip", "route", "append", "224.0.0.0/4", "dev", DEV, "metric", "0"],
        ["sysctl", "-w", f"net.ipv4.conf.{DEV}.rp_filter=0"],
        ["sysctl", "-w", f"net.ipv4.conf.{DEV}.accept_local=1"],
    ]
    if argv in fixed:
        return True
    if len(argv) == 6 and argv[:5] == ["ip", "link", "set", DEV, "address"]:
        return bool(re.fullmatch(r"02(?::[0-9a-fA-F]{2}){5}", argv[5]))
    if len(argv) == 6 and argv[:3] == ["ip", "addr", "add"] and argv[4:] == ["dev", DEV]:
        try:
            addr = ipaddress.IPv4Interface(argv[3])
            return str(addr.ip).startswith("26.") and 8 <= addr.network.prefixlen <= 32
        except ValueError:
            return False
    if len(argv) == 7 and argv[:4] == ["ip", "-6", "addr", "add"] and argv[5:] == ["dev", DEV]:
        try:
            addr = ipaddress.IPv6Interface(argv[4])
            return addr.ip in ipaddress.IPv6Network("fc00::/7") and addr.network.prefixlen == 128
        except ValueError:
            return False
    return False


def run(argv, check=True):
    executable = next((str(Path(p) / argv[0]) for p in ("/usr/bin", "/usr/sbin")
                       if (Path(p) / argv[0]).is_file()), None)
    if not executable:
        if check:
            raise RuntimeError(f"Missing system command: {argv[0]}")
        return subprocess.CompletedProcess(argv, 127, "", "Not installed")
    result = subprocess.run([executable, *argv[1:]], capture_output=True, text=True,
                            timeout=20, env={"PATH": "/usr/bin:/usr/sbin", "LANG": "C"})
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{argv[0]} failed ({result.returncode})")
    return result


def save_state(state):
    temporary = STATE / "firewall.new"
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(STATE / "firewall.json")


def nft_rules():
    result = run(["nft", "-j", "-a", "list", "ruleset"], check=False)
    if result.returncode not in (0, 127):
        raise RuntimeError(result.stderr.strip() or "Could not inspect nftables rules")
    return json.loads(result.stdout).get("nftables", []) if result.returncode == 0 else []


def firewall_close():
    statefile = STATE / "firewall.json"
    state = json.loads(statefile.read_text()) if statefile.exists() else {}
    errors = []
    if state.get("firewalld"):
        previous = state.get("previous_zone")
        args = ["firewall-cmd", f"--zone={previous}", f"--change-interface={DEV}"] if previous else ["firewall-cmd", "--zone=trusted", f"--remove-interface={DEV}"]
        result = run(args, check=False)
        if result.returncode:
            errors.append(result.stderr.strip())
    for item in nft_rules():
        rule = item.get("rule", {})
        if rule.get("comment") != TAG:
            continue
        result = run(["nft", "delete", "rule", rule["family"], rule["table"], rule["chain"], "handle", str(rule["handle"])], check=False)
        if result.returncode:
            errors.append(result.stderr.strip())
    for tool in state.get("iptables", []):
        exists = run([tool, "-C", "INPUT", "-i", DEV, "-m", "comment", "--comment", TAG, "-j", "ACCEPT"], check=False)
        if exists.returncode == 1:
            continue  # The firewall may already have flushed our rule.
        if exists.returncode:
            errors.append(exists.stderr.strip())
            continue
        result = run([tool, "-D", "INPUT", "-i", DEV, "-m", "comment", "--comment", TAG, "-j", "ACCEPT"], check=False)
        if result.returncode:
            errors.append(result.stderr.strip())
    if errors:
        raise RuntimeError("Firewall cleanup incomplete: " + "; ".join(errors))
    statefile.unlink(missing_ok=True)


def firewall_open():
    firewall_close()
    if run(["firewall-cmd", "--state"], check=False).returncode == 0:
        previous = run(["firewall-cmd", f"--get-zone-of-interface={DEV}"], check=False).stdout.strip()
        if previous == "trusted":
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]+", previous):
            previous = ""
        save_state({"firewalld": True, "previous_zone": previous})
        run(["firewall-cmd", "--zone=trusted", f"--change-interface={DEV}"])
        return
    rules = nft_rules()
    for item in rules:
        chain = item.get("chain", {})
        if chain.get("hook") != "input" or chain.get("type") != "filter" or chain.get("family") not in ("ip", "ip6", "inet"):
            continue
        if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", chain.get(k, "")) for k in ("table", "name")):
            raise RuntimeError("Unsupported nftables chain name")
        run(["nft", "insert", "rule", chain["family"], chain["table"], chain["name"],
             "iifname", f'"{DEV}"', "accept", "comment", f'"{TAG}"'])
    state = {"iptables": []}
    save_state(state)
    for tool in ("iptables", "ip6tables"):
        version = run([tool, "--version"], check=False)
        if version.returncode or (rules and "legacy" not in version.stdout):
            continue
        run([tool, "-I", "INPUT", "-i", DEV, "-m", "comment", "--comment", TAG, "-j", "ACCEPT"])
        state["iptables"].append(tool)
        save_state(state)


def cleanup_if_idle():
    """ExecStopPost also runs after a failed start: never touch another launcher's VPN."""
    import fcntl
    import pwd
    import stat
    token = os.environ.get("INVOCATION_ID", "")
    if not session_owned(token):
        return
    try:
        fd = os.open(DATA_LOCK, os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return
    with os.fdopen(fd, "r+") as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != pwd.getpwnam("deck").pw_uid:
            raise RuntimeError("Unexpected owner/type of Radmin lock; cleanup refused")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another Radmin launcher owns the adapter; cleanup skipped")
            return
        session_end(token)


def session_owned(token):
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        return False
    try:
        return (STATE / "session").read_text(encoding="ascii") == token
    except FileNotFoundError:
        return False


def session_begin(token):
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise RuntimeError("Invalid session token")
    present = run(["ip", "link", "show", "dev", DEV], check=False)
    if present.returncode == 0:
        raise RuntimeError("Radmin adapter already exists. Close the other Radmin launcher first.")
    if present.returncode != 1:
        raise RuntimeError("Could not check whether another Radmin adapter exists")
    (STATE / "session").write_text(token, encoding="ascii")


def session_end(token):
    if not session_owned(token):
        return
    try:
        firewall_close()
    finally:
        run(["ip", "link", "delete", DEV], check=False)
    (STATE / "session").unlink(missing_ok=True)


def main(argv):
    if os.geteuid() != 0:
        raise RuntimeError("Root required")
    if argv == ["check-access"]:
        print("Radmin Decky: passwordless helper access OK")
        return 0
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    import fcntl
    with (STATE / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if argv == ["firewall", "open"]:
            firewall_open()
        elif argv == ["firewall", "close"]:
            firewall_close()
        elif argv == ["cleanup-if-idle"]:
            cleanup_if_idle()
        elif len(argv) == 2 and argv[0] == "session-begin":
            session_begin(argv[1])
        elif len(argv) == 2 and argv[0] == "session-end":
            session_end(argv[1])
        elif argv == ["cleanup"]:
            try:
                firewall_close()
            finally:
                run(["ip", "link", "delete", DEV], check=False)
        elif allowed(argv):
            result = run(argv, check=False)
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode
        else:
            raise RuntimeError("Rejected network command")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as error:
        print(f"radmin-decky: {error}", file=sys.stderr)
        sys.exit(1)
