#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR=/opt/sunshine-vd
SERVICE_DEST=/etc/systemd/system/sunshineVD.service
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

CONFIGURE_SUNSHINE=true
SUNSHINE_CONFIG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --configure-sunshine)
            CONFIGURE_SUNSHINE=true
            shift
            ;;
        --no-sunshine-config)
            CONFIGURE_SUNSHINE=false
            shift
            ;;
        --sunshine-config)
            if [[ $# -lt 2 ]]; then
                echo "Error: --sunshine-config needs a path" >&2
                exit 2
            fi
            SUNSHINE_CONFIG="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: sudo ./install.sh [--no-sunshine-config] [--sunshine-config PATH]"
            exit 0
            ;;
        *)
            echo "Error: unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

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

if [[ "$CONFIGURE_SUNSHINE" == true ]]; then
    echo ""
    echo "==> Configuring Sunshine global_prep_cmd..."
    TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || true)}"
    HELPER=(python3 "$SCRIPT_DIR/scripts/sunshine_prep_cmd.py" install)
    if [[ -n "$TARGET_USER" ]]; then
        HELPER+=(--user "$TARGET_USER")
    fi
    if [[ -n "$SUNSHINE_CONFIG" ]]; then
        HELPER+=(--config "$SUNSHINE_CONFIG")
    fi
    if ! "${HELPER[@]}"; then
        echo "Warning: could not update the Sunshine config automatically."
        echo "Configure the Do/Undo commands manually as described in the README."
    fi
fi

echo ""
echo "Done. Status:"
systemctl status sunshineVD --no-pager || true
