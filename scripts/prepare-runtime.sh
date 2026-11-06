#!/bin/bash
# Called by the Decky system installer as deck. Downloads never execute as root.
set -euo pipefail
[[ $(id -un) == deck && $# == 2 ]] || exit 1
SOURCE=$(realpath -e -- "$1")
WORK=$(realpath -e -- "$2")
DATA=/home/deck/.local/share/radmin-vpn-linux
mkdir -p "$DATA"
exec 9>"$DATA/.lock"
flock -n 9 || { echo 'Close the existing Radmin window before installing.'; exit 1; }
echo 'Downloading Radmin Linux v1.1.1 runtime (178 MiB)...'
curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
  'https://github.com/baptisterajaut/radmin-vpn-linux/releases/download/v1.1.1/RadminVPN-Linux-x86_64.AppImage' \
  -o "$WORK/Radmin.AppImage"
echo '14601f601c171ac4ad855e9a9e69473ae5ebf62503ce5271c6a38d3ac475f2f3  '"$WORK/Radmin.AppImage" | sha256sum --check --status
chmod +x "$WORK/Radmin.AppImage"
echo 'Extracting and adapting the runtime...'
(cd "$WORK" && ./Radmin.AppImage --appimage-extract >/dev/null)
[[ -x "$WORK/squashfs-root/wine/bin/wine" ]]
python3 "$SOURCE/scripts/patch_runtime.py" "$WORK/squashfs-root"
BACKUP=/home/deck/.local/share/radmin-decky-backups
if [[ -d "$DATA/wineprefix" && ! -f "$BACKUP/.initial-prefix-saved" ]]; then
    mkdir -p "$BACKUP"
    echo 'Backing up existing Radmin ID and settings...'
    cp -a -- "$DATA/wineprefix" "$BACKUP/wineprefix-$(date +%Y%m%d-%H%M%S)"
    touch "$BACKUP/.initial-prefix-saved"
fi
