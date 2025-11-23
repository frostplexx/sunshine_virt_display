#!/bin/bash
# Virtual Display Manager Wrapper for Sunshine
# This script wraps the Python virtual display manager for easy integration with Sunshine
# Configure your sudo password here for Sunshine integration

# CONFIGURE YOUR SUDO PASSWORD HERE
SUDO_PASSWORD="your_password_here"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/main.py"

# Execute the Python script with sudo using the configured password
echo "$SUDO_PASSWORD" | sudo -S python3 "$PYTHON_SCRIPT" "$@"
