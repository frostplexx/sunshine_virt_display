"""
Sysfs and debugfs helpers for discovering GPU devices, display ports,
and connector state.
"""

import os
import subprocess
from pathlib import Path


def run_command(command):
    """Run a shell command and return the CompletedProcess."""
    return subprocess.run(command, shell=True, capture_output=True, text=True)


def get_drm_devices():
    """Get list of DRM devices from /sys/kernel/debug/dri/"""
    debug_dri_path = "/sys/kernel/debug/dri"
    devices = []

    result = run_command(f"ls -1 {debug_dri_path}")
    if result.returncode != 0:
        print(
            "Error: /sys/kernel/debug/dri not found or not accessible. Make sure debugfs is mounted."
        )
        return devices

    for line in result.stdout.strip().split("\n"):
        if line.startswith("0000:"):
            devices.append(Path(debug_dri_path) / line)

    return sorted(devices)


def get_display_ports(drm_device):
    """Get all display ports for a given DRM device."""
    ports = {"DP": [], "HDMI": []}

    result = run_command(f"ls -1 {drm_device}")
    if result.returncode != 0:
        return ports

    for line in result.stdout.strip().split("\n"):
        port_name = line.strip()
        if port_name.startswith("DP-"):
            ports["DP"].append(port_name)
        elif port_name.startswith("HDMI-"):
            ports["HDMI"].append(port_name)

    return ports


def get_connected_displays(card_name):
    """Get list of currently connected displays from /sys/class/drm/"""
    drm_path = Path("/sys/class/drm")
    connected = []

    for display in drm_path.iterdir():
        if display.name.startswith(f"{card_name}-"):
            status_file = display / "status"
            if status_file.exists():
                try:
                    status = status_file.read_text().strip()
                    if status == "connected":
                        port_name = display.name.replace(f"{card_name}-", "")
                        connected.append(port_name)
                except Exception:
                    pass

    return connected


def find_empty_slot(drm_device, card_name):
    """Find the first empty display slot, preferring DP over HDMI."""
    ports = get_display_ports(drm_device)
    connected = get_connected_displays(card_name)

    for port in sorted(ports["DP"]):
        if port not in connected:
            return port, drm_device

    for port in sorted(ports["HDMI"]):
        if port not in connected:
            return port, drm_device

    return None, None


def get_card_name_from_device(drm_device_path):
    """Extract card name (e.g., 'card1') from DRM device path."""
    device_name = drm_device_path.name

    drm_class_path = Path("/sys/class/drm")
    for card_dir in drm_class_path.iterdir():
        if card_dir.name.startswith("card") and "-" not in card_dir.name:
            device_link = card_dir / "device"
            if device_link.exists():
                try:
                    target = os.readlink(device_link)
                    if device_name in target:
                        return card_dir.name
                except Exception:
                    pass

    # Fallback: assume card1 for discrete GPU (most common case)
    return "card1"
