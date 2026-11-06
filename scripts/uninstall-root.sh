#!/bin/bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run: sudo bash /etc/radmin-decky/uninstall.sh'; exit 1; }
systemctl disable --now radmin-decky.service 2>/dev/null || true
# Remove the mandatory include before removing the included file.
/usr/bin/python3 -I /etc/radmin-decky/sudo_policy.py --remove
visudo -c
rm -f -- /etc/systemd/system/radmin-decky.service /etc/sudoers.d/radmin-decky
rm -f -- /home/deck/Desktop/Radmin-VPN-Setup.desktop
# Fixed absolute destinations only. Keep all user data and backups.
for target in '/home/deck/homebrew/plugins/Radmin VPN' /home/deck/homebrew/data/radmin-decky-runtime /etc/radmin-decky; do
    [[ ! -L "$target" ]] || { echo "Refusing symlink: $target"; exit 1; }
    rm -rf -- "$target"
done
systemctl daemon-reload
echo 'Removed plugin and service. Radmin prefix, networks and backups were kept.'
echo 'Restart Steam Deck to refresh Decky.'
