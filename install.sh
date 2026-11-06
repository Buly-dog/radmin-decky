#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ $(id -un) == deck && $HOME == /home/deck ]] || { echo 'Run this as deck on Steam Deck, without sudo.'; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'Only x86_64 Steam Deck is supported.'; exit 1; }
for cmd in curl sha256sum python3 sudo visudo systemctl ip flock; do
    command -v "$cmd" >/dev/null || { echo "Missing command: $cmd"; exit 1; }
done
[[ -f "$ROOT/dist/index.js" ]] || { echo 'Incomplete bundle: dist/index.js missing.'; exit 1; }
[[ -d /home/deck/homebrew/plugins ]] || { echo 'Install Decky Loader first, then run this installer again.'; exit 1; }
if pgrep -u "$(id -u)" -f 'RvControlSvc.exe|RvRvpnGui.exe|rvpn_launcher.exe' >/dev/null; then
    echo 'Close Radmin / turn off its Decky switch first, then run the installer again.'
    exit 1
fi
DATA="$HOME/.local/share/radmin-vpn-linux"
mkdir -p "$DATA"
# Share the upstream lock so no AppImage or configuration launch races installation.
exec 9>"$DATA/.lock"
flock -n 9 || { echo 'Radmin is already running. Close it before installing.'; exit 1; }
mkdir -p "$HOME/.cache"
WORK=$(mktemp -d "$HOME/.cache/radmin-decky-install.XXXXXX")
trap 'rm -rf -- "$WORK"' EXIT
echo 'Downloading pinned Radmin Linux v1.1.1 runtime (about 178 MiB)…'
curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
  'https://github.com/baptisterajaut/radmin-vpn-linux/releases/download/v1.1.1/RadminVPN-Linux-x86_64.AppImage' \
  -o "$WORK/Radmin.AppImage"
echo '14601f601c171ac4ad855e9a9e69473ae5ebf62503ce5271c6a38d3ac475f2f3  '"$WORK/Radmin.AppImage" | sha256sum --check --status || { echo 'SHA-256 mismatch. Installation stopped.'; exit 1; }
chmod +x "$WORK/Radmin.AppImage"
(cd "$WORK" && ./Radmin.AppImage --appimage-extract >/dev/null)
[[ -x "$WORK/squashfs-root/wine/bin/wine" ]] || { echo 'Unexpected AppImage layout.'; exit 1; }
python3 "$ROOT/scripts/patch_runtime.py" "$WORK/squashfs-root"
# Preserve the user's existing ID and networks before the first adapted launch.
BACKUP="$HOME/.local/share/radmin-decky-backups"
if [[ -d "$DATA/wineprefix" && ! -f "$BACKUP/.initial-prefix-saved" ]]; then
    mkdir -p "$BACKUP"
    echo 'Backing up your existing Radmin prefix…'
    cp -a -- "$DATA/wineprefix" "$BACKUP/wineprefix-$(date +%Y%m%d-%H%M%S)"
    touch "$BACKUP/.initial-prefix-saved"
fi
echo 'Installing the Decky plugin and system service. Enter the deck password once if prompted.'
sudo /bin/bash "$ROOT/scripts/install-root.sh" "$ROOT" "$WORK/squashfs-root"
echo
echo 'Installed. Restart Steam Deck to load the plugin.'
echo 'To configure or join networks, open "Configure Radmin VPN" on the Desktop.'
echo 'For normal use: Gaming Mode → … → Decky → Radmin VPN → On.'
