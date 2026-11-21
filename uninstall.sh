#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR=/opt/sunshine-vd
SERVICE_DEST=/etc/systemd/system/sunshineVD.service
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

REMOVE_SUNSHINE_CONFIG=true
SUNSHINE_CONFIG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep-sunshine-config)
            REMOVE_SUNSHINE_CONFIG=false
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
            echo "Usage: sudo ./uninstall.sh [--keep-sunshine-config] [--sunshine-config PATH]"
            exit 0
            ;;
        *)
            echo "Error: unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo ./uninstall.sh"; exit 1; }

echo "==> Stopping and disabling systemd service..."
systemctl stop sunshineVD || true
systemctl disable sunshineVD || true

if [[ "$REMOVE_SUNSHINE_CONFIG" == true ]]; then
    echo "==> Removing Sunshine global_prep_cmd..."
    TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || true)}"
    HELPER=(python3 "$SCRIPT_DIR/scripts/sunshine_prep_cmd.py" uninstall)
    if [[ -n "$TARGET_USER" ]]; then
        HELPER+=(--user "$TARGET_USER")
    fi
    if [[ -n "$SUNSHINE_CONFIG" ]]; then
        HELPER+=(--config "$SUNSHINE_CONFIG")
    fi
    if ! "${HELPER[@]}"; then
        echo "Warning: could not remove the Sunshine Do/Undo command automatically."
        echo "Remove it manually from your Sunshine configuration."
    fi
fi

echo "==> Removing systemd service file..."
rm -f "$SERVICE_DEST"
systemctl daemon-reload

echo "==> Removing project files..."
rm -rf "$INSTALL_DIR"

echo ""
echo "Done. Uninstall complete."
