#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR=/opt/sunshine-vd
SERVICE_DEST=/etc/systemd/system/sunshineVD.service

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo ./uninstall.sh"; exit 1; }

echo "==> Stopping and disabling systemd service..."
systemctl stop sunshineVD || true
systemctl disable sunshineVD || true

echo "==> Removing systemd service file..."
rm -f "$SERVICE_DEST"
systemctl daemon-reload

echo "==> Removing project files..."
rm -rf "$INSTALL_DIR"

echo "==> Removing Sunshine global_prep_cmd..."
TARGET_USER=${SUDO_USER:-$(logname 2>/dev/null || true)}
if [ -z "$TARGET_USER" ]; then
    TARGET_HOME="/root"
else
    TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
fi

SUNSHINE_CONF=""
POSSIBLE_LOCATIONS=(
    "$TARGET_HOME/.config/sunshine/sunshine.conf"
    "/root/.config/sunshine/sunshine.conf"
    "/etc/sunshine/sunshine.conf"
)

for loc in "${POSSIBLE_LOCATIONS[@]}"; do
    if [ -f "$loc" ]; then
        SUNSHINE_CONF="$loc"
        break
    fi
done

if [ -z "$SUNSHINE_CONF" ]; then
    echo "Sunshine config not found in common locations, skipping automation."
else
    python3 -c "
import sys, json, os, re
CONF_PATH = sys.argv[1]
nc_do = 'sh -c \"echo --connect,--width,\${SUNSHINE_CLIENT_WIDTH},--height,\${SUNSHINE_CLIENT_HEIGHT},--refresh-rate,\${SUNSHINE_CLIENT_FPS} | nc -U /tmp/sunshineVD.sock\"'
nc_undo = 'sh -c \"echo --disconnect | nc -U /tmp/sunshineVD.sock\"'
socat_do = 'sh -c \"echo --connect,--width,\${SUNSHINE_CLIENT_WIDTH},--height,\${SUNSHINE_CLIENT_HEIGHT},--refresh-rate,\${SUNSHINE_CLIENT_FPS} | socat - UNIX-CONNECT:/tmp/sunshineVD.sock\"'
socat_undo = 'sh -c \"echo --disconnect | socat - UNIX-CONNECT:/tmp/sunshineVD.sock\"'

with open(CONF_PATH, 'r') as f: lines = f.readlines()
new_lines = []
for line in lines:
    if line.startswith('global_prep_cmd'):
        match = re.match(r'global_prep_cmd\s*=\s*(.*)', line)
        if match:
            try: cmds = json.loads(match.group(1).strip())
            except Exception: cmds = []
            if not isinstance(cmds, list): cmds = []
            cmds = [cmd for cmd in cmds if not ((cmd.get('do') == nc_do and cmd.get('undo') == nc_undo) or (cmd.get('do') == socat_do and cmd.get('undo') == socat_undo))]
            if len(cmds) > 0: new_lines.append(f'global_prep_cmd = {json.dumps(cmds, separators=(\",\", \":\"))}\\n')
        else: new_lines.append(line)
    else: new_lines.append(line)

with open(CONF_PATH, 'w') as f: f.writelines(new_lines)
" "$SUNSHINE_CONF"
    echo "Removed Do/Undo commands from $SUNSHINE_CONF"
fi

echo ""
echo "Done. Uninstall complete."
