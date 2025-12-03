#!/usr/bin/env python3
"""
Virtual Display Manager for Linux
Manages virtual displays by creating custom EDIDs and toggling display ports

This script must be run with sudo privileges.
Usage: echo "password" | sudo python3 main.py --connect --width 1920 --height 1080
"""

import os
import sys
from pathlib import Path

# Get the directory where this script is located and add it to Python path
SCRIPT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

import argparse
import subprocess
from gen_edid import create_edid


def ensure_root():
    """Ensure the script is running as root"""
    if os.geteuid() != 0:
        print("Error: This script must be run as root (use sudo)")
        sys.exit(1)


def run_command(command):
    """Run a command (already running as root, no need for sudo)"""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result


def get_drm_devices():
    """Get list of DRM devices from /sys/kernel/debug/dri/"""
    debug_dri_path = "/sys/kernel/debug/dri"
    devices = []

    # List the directory (already running as root)
    cmd = f"ls -1 {debug_dri_path}"
    result = run_command(cmd)

    if result.returncode != 0:
        print(
            "Error: /sys/kernel/debug/dri not found or not accessible. Make sure debugfs is mounted."
        )
        return devices

    # Parse the output to get device names
    for line in result.stdout.strip().split("\n"):
        if line.startswith("0000:"):
            devices.append(Path(debug_dri_path) / line)

    return sorted(devices)


def get_display_ports(drm_device):
    """Get all display ports for a given DRM device"""
    ports = {"DP": [], "HDMI": []}

    # List the directory (already running as root)
    cmd = f"ls -1 {drm_device}"
    result = run_command(cmd)

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
                        # Extract just the port name (e.g., "DP-1" from "card1-DP-1")
                        port_name = display.name.replace(f"{card_name}-", "")
                        connected.append(port_name)
                except:
                    pass

    return connected


def find_empty_slot(drm_device, card_name):
    """Find the first empty display slot, preferring DP over HDMI"""
    ports = get_display_ports(drm_device)
    connected = get_connected_displays(card_name)

    # First try to find an empty DP slot
    for port in sorted(ports["DP"]):
        if port not in connected:
            return port, drm_device

    # Then try HDMI slots
    for port in sorted(ports["HDMI"]):
        if port not in connected:
            return port, drm_device

    return None, None


def get_card_name_from_device(drm_device_path):
    """Extract card name (e.g., 'card1') from DRM device path"""
    # Map the /sys/kernel/debug/dri device to /sys/class/drm card
    # This is a heuristic - typically card0 maps to 0000:00:02.0 (integrated)
    # and card1 to discrete GPU
    device_name = drm_device_path.name

    # Try to find the card by reading the device symlink
    drm_class_path = Path("/sys/class/drm")
    for card_dir in drm_class_path.iterdir():
        if card_dir.name.startswith("card") and not "-" in card_dir.name:
            device_link = card_dir / "device"
            if device_link.exists():
                try:
                    target = os.readlink(device_link)
                    if device_name in target:
                        return card_dir.name
                except:
                    pass

    # Fallback: assume card1 for discrete GPU (most common case)
    return "card1"


def connect_virtual_display(width, height, refresh_rate):
    """
    Connect a virtual display:
    1. Generate custom EDID
    2. Find empty display slot
    3. Override EDID
    4. Turn off connected displays
    5. Turn on virtual display
    """
    print(f"Connecting virtual display: {width}x{height}@{refresh_rate}Hz")

    # Step 1: Generate custom EDID
    print("Step 1: Generating custom EDID...")
    print(f"  Requested: {width}x{height} @ {refresh_rate}Hz")

    # Import the necessary functions from gen_edid
    from gen_edid import (
        check_if_calculation_breaks,
        find_best_vic_resolution,
        get_pixel_clock_info,
    )

    # Get pixel clock info for diagnostics
    pixel_clock_mhz, max_mhz, will_break = get_pixel_clock_info(
        width, height, refresh_rate
    )
    print(f"  Pixel clock: {pixel_clock_mhz:.2f} MHz (max: {max_mhz:.2f} MHz)")

    # Check if the resolution would break
    if will_break:
        print(
            f"  ⚠️  WARNING: Pixel clock exceeds limit by {pixel_clock_mhz - max_mhz:.2f} MHz!"
        )
        print(f"  Finding best VIC standard resolution...")

        vic_result = find_best_vic_resolution(width, height, refresh_rate)
        if vic_result:
            vic_width, vic_height, vic_refresh, vic_code, vic_name = vic_result
            print(
                f"  → Falling back to VIC {vic_code}: {vic_width}x{vic_height} @ {vic_refresh}Hz ({vic_name})"
            )

            # Show new pixel clock
            new_clock_mhz, _, _ = get_pixel_clock_info(
                vic_width, vic_height, vic_refresh
            )
            print(f"  → New pixel clock: {new_clock_mhz:.2f} MHz")

            width, height, refresh_rate = vic_width, vic_height, vic_refresh
        else:
            print(f"  ⚠️  No suitable VIC found, attempting custom resolution anyway...")
    else:
        print(f"  ✓ Pixel clock within limits")
        print(f"  ✓ Using custom resolution: {width}x{height} @ {refresh_rate}Hz")

    edid_data = create_edid(
        width=width,
        height=height,
        refresh_rate=refresh_rate,
        enable_hdr=True,
        display_name="Virtual Display",
    )

    edid_file = SCRIPT_DIR / "custom_edid.bin"
    edid_file.write_bytes(edid_data)
    print(f"  ✓ Created EDID file: {edid_file}")
    print(f"  ✓ Final resolution: {width}x{height} @ {refresh_rate}Hz")
    print(f"  ✓ EDID size: {len(edid_data)} bytes")

    # Step 2: Find DRM devices and list connected displays
    print("\nStep 2: Scanning displays...")
    drm_devices = get_drm_devices()

    if not drm_devices:
        print("Error: No DRM devices found")
        return False

    # Use the first device (usually the main GPU)
    drm_device = drm_devices[0]
    card_name = get_card_name_from_device(drm_device)
    print(f"  Using device: {drm_device.name} ({card_name})")

    connected_displays = get_connected_displays(card_name)
    print(
        f"  Connected displays: {connected_displays if connected_displays else 'None'}"
    )

    # Step 3: Find empty slot
    print("\nStep 3: Finding empty display slot...")
    empty_port, device = find_empty_slot(drm_device, card_name)

    if not empty_port:
        print("Error: No empty display slots available")
        return False

    print(f"  ✓ Selected slot: {empty_port}")

    # Step 4: Override EDID
    print(f"\nStep 4: Overriding EDID for {empty_port}...")
    edid_override_path = device / empty_port / "edid_override"

    # Write the EDID file
    cmd = f"sh -c 'cat {edid_file.absolute()} > {edid_override_path}'"
    result = run_command(cmd)

    if result.returncode != 0:
        print(f"  Error overriding EDID: {result.stderr}")
        return False

    print(f"  ✓ EDID override applied")

    # Step 5: Turn off all connected displays
    print("\nStep 5: Turning off connected displays...")
    for display in connected_displays:
        status_path = f"/sys/class/drm/{card_name}-{display}/status"
        cmd = f"sh -c 'echo off > {status_path}'"
        result = run_command(cmd)
        print(f"  ✓ Turned off {display}")

    # Step 6: Turn on virtual display
    print(f"\nStep 6: Turning on virtual display ({empty_port})...")
    status_path = f"/sys/class/drm/{card_name}-{empty_port}/status"
    cmd = f"sh -c 'echo on > {status_path}'"
    result = run_command(cmd)

    if result.returncode != 0:
        print(f"  Error turning on display: {result.stderr}")
        return False

    print(f"  ✓ Virtual display enabled on {empty_port}")

    # Save state for disconnect
    state_file = SCRIPT_DIR / "virt_display.state"
    state_file.write_text(f"{card_name}\n{empty_port}\n{','.join(connected_displays)}")

    print(f"\n✓ Virtual display successfully connected!")
    print(f"  Port: {card_name}-{empty_port}")
    print(f"  Resolution: {width}x{height}@{refresh_rate}Hz")

    return True


def disconnect_virtual_display():
    """
    Disconnect virtual display:
    1. Turn off virtual display
    2. Turn on previously connected displays
    """
    print("Disconnecting virtual display...")

    # Read state file
    state_file = SCRIPT_DIR / "virt_display.state"
    if not state_file.exists():
        print("Error: No state file found. Was a virtual display connected?")
        return False

    state_data = state_file.read_text().strip().split("\n")
    if len(state_data) < 3:
        print("Error: Invalid state file")
        return False

    card_name = state_data[0]
    virtual_port = state_data[1]
    previous_displays = state_data[2].split(",") if state_data[2] else []

    print(f"  Virtual display: {card_name}-{virtual_port}")
    print(f"  Previous displays: {previous_displays if previous_displays else 'None'}")

    # Step 1: Turn off virtual display
    print(f"\nStep 1: Turning off virtual display ({virtual_port})...")
    status_path = f"/sys/class/drm/{card_name}-{virtual_port}/status"
    cmd = f"sh -c 'echo off > {status_path}'"
    result = run_command(cmd)

    if result.returncode != 0:
        print(f"  Warning: Could not turn off virtual display: {result.stderr}")
    else:
        print(f"  ✓ Virtual display turned off")

    # Step 2: Turn on previously connected displays
    print("\nStep 2: Turning on previous displays...")
    for display in previous_displays:
        if display:  # Skip empty strings
            status_path = f"/sys/class/drm/{card_name}-{display}/status"
            cmd = f"sh -c 'echo on > {status_path}'"
            result = run_command(cmd)
            print(f"  ✓ Turned on {display}")

    # Clean up state file
    state_file.unlink()

    print("\n✓ Virtual display disconnected!")
    return True


def main():
    """Main entry point"""
    try:
        # Ensure running as root
        ensure_root()

        parser = argparse.ArgumentParser(
            description="Virtual Display Manager for Linux",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Connect with resolution from Sunshine
  sudo %(prog)s --connect --width 1920 --height 1080 --refresh-rate 60
  
  # Disconnect virtual display
  sudo %(prog)s --disconnect
        """,
        )

        parser.add_argument(
            "--connect", action="store_true", help="Connect virtual display"
        )
        parser.add_argument(
            "--disconnect", action="store_true", help="Disconnect virtual display"
        )
        parser.add_argument("--width", type=int, help="Display width in pixels")
        parser.add_argument("--height", type=int, help="Display height in pixels")
        parser.add_argument(
            "--refresh-rate",
            type=int,
            default=60,
            help="Refresh rate in Hz (default: 60)",
        )

        args = parser.parse_args()

        if args.connect:
            if not args.width or not args.height:
                print(
                    "Error: --width and --height are required for --connect",
                    file=sys.stderr,
                )
                sys.exit(1)

            success = connect_virtual_display(
                args.width, args.height, args.refresh_rate
            )
            sys.exit(0 if success else 1)

        elif args.disconnect:
            success = disconnect_virtual_display()
            sys.exit(0 if success else 1)

        else:
            parser.print_help()
            sys.exit(1)

    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
