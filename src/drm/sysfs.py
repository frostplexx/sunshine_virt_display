"""
Sysfs and debugfs helpers for discovering GPU devices, display ports,
and connector state.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run_command(command: str) -> subprocess.CompletedProcess[str]:
    """Run a shell command and return the CompletedProcess."""
    # To run robustly on NixOS, execute simple file writes/clears and directory listings
    # natively using Python APIs, avoiding shell or external binary execution errors.
    cmd_stripped = command.strip()
    if cmd_stripped.startswith("sh -c '") and cmd_stripped.endswith("'"):
        cmd_stripped = cmd_stripped[7:-1]
    elif cmd_stripped.startswith('sh -c "') and cmd_stripped.endswith('"'):
        cmd_stripped = cmd_stripped[7:-1]

    cmd_parts = cmd_stripped.split()

    if ">" in cmd_parts:
        if not any(char in cmd_stripped for char in ";&|*?$()"):
            idx = cmd_parts.index(">")
            if cmd_parts.count(">") == 1:
                target_path_str = " ".join(cmd_parts[idx+1:]).strip()
                action_parts = cmd_parts[:idx]
                if len(action_parts) >= 2:
                    if action_parts[0] == "cat":
                        src_path_str = " ".join(action_parts[1:]).strip()
                        if src_path_str == "/dev/null":
                            try:
                                Path(target_path_str).write_bytes(b"")
                                return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                            except Exception as e:
                                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr=str(e))
                        else:
                            try:
                                src_bytes = Path(src_path_str).read_bytes()
                                Path(target_path_str).write_bytes(src_bytes)
                                return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                            except Exception as e:
                                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr=str(e))
                    elif action_parts[0] == "echo":
                        content = " ".join(action_parts[1:]).strip()
                        if content.startswith("'") and content.endswith("'"):
                            content = content[1:-1]
                        elif content.startswith('"') and content.endswith('"'):
                            content = content[1:-1]
                        try:
                            Path(target_path_str).write_text(content + "\n")
                            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                        except Exception as e:
                            return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr=str(e))

    # Handle "ls -1 /some/path" or "ls /some/path"
    if (len(cmd_parts) == 2 or len(cmd_parts) == 3) and cmd_parts[0] == "ls":
        if not any(char in cmd_stripped for char in ";&|*?$()<>"):
            path_idx = 2 if cmd_parts[1] == "-1" else 1
            if path_idx < len(cmd_parts):
                dir_path_str = cmd_parts[path_idx]
                try:
                    entries = os.listdir(dir_path_str)
                    stdout = "".join(f"{entry}\n" for entry in entries)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout=stdout, stderr="")
                except Exception as e:
                    return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr=str(e))
    
    return subprocess.run(command, shell=True, capture_output=True, text=True)


def get_drm_devices() -> list[Path]:
    """Get list of DRM devices from /sys/kernel/debug/dri/"""
    debug_dri_path = "/sys/kernel/debug/dri"
    devices: list[Path] = []

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


def get_display_ports(drm_device: Path) -> dict[str, list[str]]:
    """Get all display ports for a given DRM device."""
    ports: dict[str, list[str]] = {"DP": [], "HDMI": []}

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


def get_connected_displays(card_name: str) -> list[str]:
    """Get list of currently connected displays from /sys/class/drm/"""
    drm_path = Path("/sys/class/drm")
    connected: list[str] = []

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


def find_empty_slot(drm_device: Path, card_name: str) -> tuple[str | None, Path | None]:
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


def get_card_name_from_device(drm_device_path: Path) -> str:
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
