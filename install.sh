#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR=/opt/sunshine-vd
SERVICE_DEST=/etc/systemd/system/sunshineVD.service

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo ./install.sh"; exit 1; }

echo "==> Checking for jeepney..."
if ! python3 -c "import jeepney" 2>/dev/null; then
    echo ""
    echo "ERROR: jeepney is not installed."
    echo ""
    echo "Please install it using your package manager:"
    echo "  - Arch/CachyOS/Manjaro: sudo pacman -S python-jeepney"
    echo "  - Fedora:               sudo dnf install python3-jeepney"
    echo "  - Ubuntu/Debian:        sudo apt install python3-jeepney"
    echo ""
    echo "Or use pip in a virtual environment:"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install jeepney"
    echo ""
    exit 1
fi
echo "    jeepney found."

echo "==> Copying project to $INSTALL_DIR..."
install -d "$INSTALL_DIR"
rsync -a --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.coverage' \
    --exclude='custom_edid.bin' \
    --exclude='virt_display.state' \
    . "$INSTALL_DIR/"

echo "==> Installing systemd service..."
install -m 644 src/daemon/sunshineVD.service "$SERVICE_DEST"

systemctl daemon-reload
systemctl enable --now sunshineVD

echo ""
echo "==> Configuring Sunshine global_prep_cmd..."
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

if command -v nc >/dev/null 2>&1; then
    USE_CMD="nc"
elif command -v socat >/dev/null 2>&1; then
    USE_CMD="socat"
else
    USE_CMD=""
fi

if [ -z "$USE_CMD" ]; then
    echo "Neither 'nc' nor 'socat' found. Skipping Sunshine Do/Undo commands automation."
    echo "Please install one of them (e.g. openbsd-netcat or socat) and configure manually."
elif [ -z "$SUNSHINE_CONF" ]; then
    echo "Sunshine config not found in common locations, skipping automation."
    echo "Please configure Sunshine manually as described in the README."
else
    python3 -c "
import sys, json, os, re
CONF_PATH = sys.argv[1]
use_cmd = sys.argv[2]
nc_do = 'sh -c \"echo --connect,--width,\${SUNSHINE_CLIENT_WIDTH},--height,\${SUNSHINE_CLIENT_HEIGHT},--refresh-rate,\${SUNSHINE_CLIENT_FPS} | nc -U /tmp/sunshineVD.sock\"'
nc_undo = 'sh -c \"echo --disconnect | nc -U /tmp/sunshineVD.sock\"'
socat_do = 'sh -c \"echo --connect,--width,\${SUNSHINE_CLIENT_WIDTH},--height,\${SUNSHINE_CLIENT_HEIGHT},--refresh-rate,\${SUNSHINE_CLIENT_FPS} | socat - UNIX-CONNECT:/tmp/sunshineVD.sock\"'
socat_undo = 'sh -c \"echo --disconnect | socat - UNIX-CONNECT:/tmp/sunshineVD.sock\"'
if use_cmd == 'nc':
    our_cmd_obj = {'do': nc_do, 'undo': nc_undo}
else:
    our_cmd_obj = {'do': socat_do, 'undo': socat_undo}
with open(CONF_PATH, 'r') as f: lines = f.readlines()
new_lines = []
found = False
for line in lines:
    if line.startswith('global_prep_cmd'):
        found = True
        match = re.match(r'global_prep_cmd\s*=\s*(.*)', line)
        if match:
            try: cmds = json.loads(match.group(1).strip())
            except Exception: cmds = []
            if not isinstance(cmds, list): cmds = []
            cmds = [cmd for cmd in cmds if not ((cmd.get('do') == nc_do and cmd.get('undo') == nc_undo) or (cmd.get('do') == socat_do and cmd.get('undo') == socat_undo))]
            cmds.append(our_cmd_obj)
            if len(cmds) > 0: new_lines.append(f'global_prep_cmd = {json.dumps(cmds, separators=(\",\", \":\"))}\\n')
        else: new_lines.append(line)
    else: new_lines.append(line)
if not found:
    if len(new_lines) > 0 and not new_lines[-1].endswith('\n'): new_lines[-1] += '\n'
    new_lines.append(f'global_prep_cmd = {json.dumps([our_cmd_obj], separators=(\",\", \":\"))}\\n')
with open(CONF_PATH, 'w') as f: f.writelines(new_lines)
" "$SUNSHINE_CONF" "$USE_CMD"
    echo "Added Do/Undo commands ($USE_CMD variant) to $SUNSHINE_CONF"
fi

echo ""
echo "Done. Status:"
systemctl status sunshineVD --no-pager || true
