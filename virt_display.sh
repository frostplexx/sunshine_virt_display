#!/bin/bash
# Virtual Display Manager Wrapper for Sunshine
# This script wraps the Python virtual display manager for easy integration with Sunshine
# NOTE: Requires passwordless sudo configuration (see README.md for setup instructions)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/main.py"

# Execute the Python script with sudo (requires sudoers configuration)
sudo python3 "$PYTHON_SCRIPT" "$@"
