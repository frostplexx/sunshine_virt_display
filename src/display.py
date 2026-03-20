"""
Connect and disconnect virtual displays by managing EDIDs and sysfs connector state.
"""

from pathlib import Path

from src.drm import (
    find_empty_slot,
    force_crtc_assignment,
    get_card_name_from_device,
    get_connected_displays,
    get_drm_devices,
    release_crtc,
    run_command,
    wait_for_output_ready,
)
from src.edid import create_edid, find_best_vic_resolution, get_pixel_clock_info

SCRIPT_DIR = Path(__file__).parent.parent.absolute()


def connect(width: int, height: int, refresh_rate: int) -> bool:
    """
    Connect a virtual display:
    1. Generate custom EDID
    2. Find empty display slot
    3. Override EDID
    4. Turn off connected displays
    5. Turn on virtual display
    6. Wait for output to be ready
    """
    print(f"Connecting virtual display: {width}x{height}@{refresh_rate}Hz")

    # Step 1: Generate custom EDID
    print("Step 1: Generating custom EDID...")
    print(f"  Requested: {width}x{height} @ {refresh_rate}Hz")

    pixel_clock_mhz, max_mhz, will_break = get_pixel_clock_info(
        width, height, refresh_rate
    )
    print(f"  Pixel clock: {pixel_clock_mhz:.2f} MHz (max: {max_mhz:.2f} MHz)")

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
        run_command(cmd)
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

    # Step 7: Force CRTC assignment via DRM ioctl, then wait for output
    print(f"\nStep 7: Forcing CRTC assignment...")
    force_crtc_assignment(card_name, empty_port)

    print(f"\nStep 8: Waiting for output to be ready...")
    ready, mode = wait_for_output_ready(card_name, empty_port, width, height)

    if ready:
        print(f"  ✓ Output ready ({mode})")
    else:
        print(f"  ⚠ Timed out waiting for output, proceeding anyway")

    # Save state for disconnect
    state_file = SCRIPT_DIR / "virt_display.state"
    state_file.write_text(f"{card_name}\n{empty_port}\n{','.join(connected_displays)}")

    print(f"\n✓ Virtual display successfully connected!")
    print(f"  Port: {card_name}-{empty_port}")
    print(f"  Resolution: {width}x{height}@{refresh_rate}Hz")

    return True


def disconnect() -> bool:
    """
    Disconnect virtual display:
    1. Turn off virtual display
    2. Turn on previously connected displays
    """
    print("Disconnecting virtual display...")

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

    # Step 1: Turn on physical displays FIRST — avoid a zero-output window
    # that can confuse the compositor (KWin crashes or stops rendering if
    # all outputs disappear at once).
    print("\nStep 1: Turning on previous displays...")
    for display in previous_displays:
        if display:
            status_path = f"/sys/class/drm/{card_name}-{display}/status"
            cmd = f"sh -c 'echo on > {status_path}'"
            run_command(cmd)
            print(f"  ✓ Turned on {display}")

    # Step 2: Force CRTC assignment for restored displays
    # On AMD, sysfs hotplug alone doesn't assign CRTCs
    print("\nStep 2: Forcing CRTC assignment for restored displays...")
    for display in previous_displays:
        if display:
            force_crtc_assignment(card_name, display)

    # Step 3: Release CRTC from virtual display and turn it off
    print(f"\nStep 3: Releasing CRTC from virtual display ({virtual_port})...")
    release_crtc(card_name, virtual_port)

    print(f"\nStep 4: Turning off virtual display ({virtual_port})...")
    status_path = f"/sys/class/drm/{card_name}-{virtual_port}/status"
    cmd = f"sh -c 'echo off > {status_path}'"
    result = run_command(cmd)

    if result.returncode != 0:
        print(f"  Warning: Could not turn off virtual display: {result.stderr}")
    else:
        print(f"  ✓ Virtual display turned off")

    state_file.unlink()

    print("\n✓ Virtual display disconnected!")
    return True
