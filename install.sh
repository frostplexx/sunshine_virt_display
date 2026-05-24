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
echo "Done. Status:"
systemctl status sunshineVD --no-pager || true
