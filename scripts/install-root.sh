#!/bin/bash
set -euo pipefail
[[ $EUID == 0 && ( $# == 2 || ( $# == 3 && $3 == --system-only ) ) ]] || exit 1
SOURCE=$(realpath -e -- "$1")
RUNTIME=$(realpath -e -- "$2")
[[ -f "$SOURCE/main.py" && -x "$RUNTIME/wine/bin/wine" ]] || exit 1
CFG=/etc/radmin-decky
PLUGIN='/home/deck/homebrew/plugins/Radmin VPN'
ASSETS=/home/deck/homebrew/data/radmin-decky-runtime
# Privileged Python files and their parent must never be writable by deck.
[[ ! -L "$CFG" ]] || { echo 'Refusing symlink at /etc/radmin-decky'; exit 1; }
install -d -o root -g root -m 755 "$CFG" "$CFG/shim"
chown root:root "$CFG" "$CFG/shim"
chmod 755 "$CFG" "$CFG/shim"
if [[ $(systemctl show radmin-decky.service --property=LoadState --value 2>/dev/null) == loaded ]]; then
    systemctl stop radmin-decky.service
fi
for name in net_helper.py runner.py probe.py; do
    [[ ! -L "$CFG/$name" ]] || { echo "Refusing symlink: $name"; exit 1; }
    install -o root -g root -m 644 "$SOURCE/system/$name" "$CFG/$name"
done
install -o root -g root -m 755 "$SOURCE/system/sudo" "$CFG/shim/sudo"
install -o root -g root -m 755 "$SOURCE/system/configure.sh" "$CFG/configure.sh"
# Reinstall only this app's runtime, without ever removing the Wine prefix.
[[ ! -L "$ASSETS" && ! -L "$PLUGIN" ]] || { echo 'Refusing symlink at plugin/runtime destination'; exit 1; }
install -d -o root -g root -m 755 "$ASSETS" "$PLUGIN" "$PLUGIN/dist"
if [[ $(realpath -e -- "$RUNTIME") != $(realpath -e -- "$ASSETS") ]]; then
    cp -a -- "$RUNTIME/." "$ASSETS/"
fi
chown -R root:root "$ASSETS"
# cp -a preserves private AppImage modes. After chown, mode 0700/0600 would
# lock deck out. Grant read/traverse while keeping the runtime non-writable.
chmod -R u=rwX,go=rX "$ASSETS"
RUNUSER=$(command -v runuser)
"$RUNUSER" -u deck -- /usr/bin/python3 -I "$SOURCE/scripts/runtime_access.py" "$ASSETS"
if [[ ${3:-} != --system-only ]]; then
    for name in main.py plugin.json package.json LICENSE; do
        install -o root -g root -m 644 "$SOURCE/$name" "$PLUGIN/$name"
    done
    install -o root -g root -m 644 "$SOURCE/dist/index.js" "$PLUGIN/dist/index.js"
    install -o root -g root -m 644 "$SOURCE/dist/index.js.map" "$PLUGIN/dist/index.js.map"
fi
install -o root -g root -m 644 "$SOURCE/system/radmin-decky.service" /etc/systemd/system/radmin-decky.service
SUDO_TEMP=$(mktemp /etc/sudoers.d/.radmin-decky.XXXXXX)
trap 'rm -f -- "$SUDO_TEMP"' EXIT
printf '%s\n' 'deck ALL=(root) NOPASSWD: /usr/bin/python3 -I /etc/radmin-decky/net_helper.py *' > "$SUDO_TEMP"
chmod 440 "$SUDO_TEMP"
visudo -cf "$SUDO_TEMP"
mv -f -- "$SUDO_TEMP" /etc/sudoers.d/radmin-decky
install -o root -g root -m 644 "$SOURCE/scripts/sudo_policy.py" "$CFG/sudo_policy.py"
install -o root -g root -m 644 "$SOURCE/scripts/uninstall-root.sh" "$CFG/uninstall.sh"
# Later matching PASSWD entries override NOPASSWD. Include the exact narrow
# helper rule again at the end of the main policy, after all distro includes.
/usr/bin/python3 -I "$CFG/sudo_policy.py" --install
visudo -c
# -k ignores a cached password: this must really work without authentication.
# This helper operation performs no network changes.
"$RUNUSER" -u deck -- /usr/bin/sudo -k -n /usr/bin/python3 -I "$CFG/net_helper.py" check-access
echo 'Passwordless helper access verified as deck.'
install -d -o deck -g deck -m 755 /home/deck/Desktop
cat > /home/deck/Desktop/Radmin-VPN-Setup.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Configure Radmin VPN
Name[ru]=Настроить Radmin VPN
Comment=Turn off the Decky VPN switch first. Join networks and enable Radmin here.
Exec=/bin/bash /etc/radmin-decky/configure.sh
Terminal=true
Icon=network-vpn
Categories=Network;
DESKTOP
chown deck:deck /home/deck/Desktop/Radmin-VPN-Setup.desktop
chmod 755 /home/deck/Desktop/Radmin-VPN-Setup.desktop
systemctl daemon-reload
printf '%s\n' '{"version":"0.1.6","upstream":"v1.1.1"}' > "$CFG/installed.json.new"
chmod 644 "$CFG/installed.json.new"
mv -f -- "$CFG/installed.json.new" "$CFG/installed.json"
# Explicit switch only. Do not enable boot autostart in the first test build.
echo 'System component installed; VPN is stopped.'
