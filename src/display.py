"""
Connect and disconnect virtual displays by managing EDIDs and sysfs connector state.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.drm import (
    find_empty_slot,
    force_crtc_assignment,
    get_card_name_from_device,
    get_connected_displays,
    get_drm_devices,
    notify_hotplug,
    release_crtc,
    run_command,
    wait_for_output_ready,
)
from src.drm.de import hyprland
from src.drm.de import kwin
from src.drm.de.kwin import clear_kwin_output_config
from src.edid import create_edid, find_best_vic_resolution, get_pixel_clock_info

SCRIPT_DIR = Path(__file__).parent.parent.absolute()
DRM_SYSFS = Path("/sys/class/drm")


def _use_hyprland_safe_path() -> bool:
    """
    On Hyprland, direct DRM CRTC stealing/reassignment bypasses the
    compositor's own atomic modeset state: Hyprland never picks up a CRTC we
    set behind its back, so physical outputs stay dark after disconnect.
    This is independent of the GPU driver (seen on both NVIDIA and amdgpu,
    issue #31), so always prefer compositor monitor commands under Hyprland
    and keep the direct DRM path for other compositors.
    """
    return hyprland.available()


def _use_kwin_safe_path() -> bool:
    """
    KWin has the same problem as Hyprland: it never adopts a CRTC forced
    behind its back, so physical outputs stay dark after disconnect
    (issue #31).  Use kscreen-doctor when a KWin Wayland session is reachable.
    """
    return kwin.available()


# Compositor backends that can hide/restore outputs without direct DRM
# CRTC manipulation.  Each module provides monitor_specs(), disable_outputs()
# and restore_outputs().
_SAFE_BACKENDS = {"hyprland": hyprland, "kwin": kwin}


def _select_safe_backend() -> str | None:
    if _use_hyprland_safe_path():
        return "hyprland"
    if _use_kwin_safe_path():
        return "kwin"
    return None


def connect(width: int, height: int, refresh_rate: int, device: str | None = None) -> bool:
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

    # If a previous session didn't clean up properly, the old virtual port still
    # has its EDID override set and sysfs status "connected". Clear it now so it
    # doesn't appear in connected_displays and end up in previous_displays.
    state_file = SCRIPT_DIR / "virt_display.state"
    if state_file.exists():
        stale = state_file.read_text().strip().split("\n")
        stale_card = stale[0] if len(stale) > 0 else ""
        stale_port = stale[1] if len(stale) > 1 else ""
        stale_edid = stale[3] if len(stale) > 3 else ""
        if stale_card and stale_port:
            print(f"  Stale session detected ({stale_card}-{stale_port}) — cleaning up...")
            if stale_edid:
                _ = run_command(f"sh -c 'cat /dev/null > {stale_edid}'")
            _ = run_command(f"sh -c 'echo off > /sys/class/drm/{stale_card}-{stale_port}/status'")
            _ = notify_hotplug(stale_card)
            time.sleep(0.5)  # let DRM process the hotplug before scanning
        state_file.unlink()

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
    _ = edid_file.write_bytes(edid_data)
    print(f"  ✓ Created EDID file: {edid_file}")
    print(f"  ✓ Final resolution: {width}x{height} @ {refresh_rate}Hz")
    print(f"  ✓ EDID size: {len(edid_data)} bytes")

    # Step 2: Find DRM devices and list connected displays
    print("\nStep 2: Scanning displays...")
    drm_devices = get_drm_devices()

    if not drm_devices:
        print("Error: No DRM devices found")
        return False

    if device:
        # User explicitly specified a card — find it or fail clearly.
        matched = [d for d in drm_devices if get_card_name_from_device(d) == device]
        if not matched:
            available = [get_card_name_from_device(d) for d in drm_devices]
            print(f"Error: device '{device}' not found. Available: {available}")
            return False
        drm_device = matched[0]
    else:
        # Pick the device that has the most connected displays — on multi-GPU
        # systems this ensures we land on the card with physical monitors rather
        # than an idle iGPU that happens to sort first by PCI address.
        best_device = drm_devices[0]
        best_count = -1
        for dev in drm_devices:
            c = get_card_name_from_device(dev)
            n = len(get_connected_displays(c))
            if n > best_count:
                best_count = n
                best_device = dev
        drm_device = best_device
    card_name = get_card_name_from_device(drm_device)
    print(f"  Using device: {drm_device.name} ({card_name})")

    connected_displays = get_connected_displays(card_name)
    print(
        f"  Connected displays: {connected_displays if connected_displays else 'None'}"
    )

    # Step 3: Find empty slot
    print("\nStep 3: Finding empty display slot...")
    empty_port, slot_device = find_empty_slot(drm_device, card_name)

    if not empty_port:
        print("Error: No empty display slots available")
        return False

    print(f"  ✓ Selected slot: {empty_port}")

    # Step 4: Override EDID
    print(f"\nStep 4: Overriding EDID for {empty_port}...")
    edid_override_path = slot_device / empty_port / "edid_override"

    cmd = f"sh -c 'cat {edid_file.absolute()} > {edid_override_path}'"
    result = run_command(cmd)

    if result.returncode != 0:
        print(f"  Error overriding EDID: {result.stderr}")
        return False

    print(f"  ✓ EDID override applied")

    backend_name = _select_safe_backend()
    backend = _SAFE_BACKENDS[backend_name] if backend_name else None
    safe_path = backend is not None
    restore_specs: dict[str, dict[str, object]] = {}
    hide_outputs: list[str] = []

    if backend is not None:
        print(f"\nStep 5: {backend_name} detected — using compositor-safe monitor toggles")
        restore_specs = backend.monitor_specs(connected_displays)
        missing_specs = sorted(set(connected_displays) - set(restore_specs))
        if missing_specs:
            print(f"  Error: Could not capture {backend_name} restore state for: {', '.join(missing_specs)}")
            print("  Refusing to hide physical outputs without a known-good restore plan")
            _ = run_command(f"sh -c 'cat /dev/null > {edid_override_path}'")
            return False
        # Outputs that are connected but disabled in the compositor stay
        # disabled: the user turned them off on purpose.
        hide_outputs = [o for o, spec in restore_specs.items() if spec.get("enabled", True)]
        print(f"  Physical outputs will be hidden via {backend_name}, not by stealing DRM CRTCs")
    else:
        # Turn off all connected displays and explicitly release their CRTCs.
        # On AMD, echo off > status marks the connector disconnected in sysfs but
        # the compositor keeps the CRTC active.  Without an explicit CRTC release
        # the compositor continues rendering to the old displays, Sunshine sees
        # multiple monitors, and uses the wrong one.
        print("\nStep 5: Turning off connected displays...")
        for display in connected_displays:
            _ = release_crtc(card_name, display)
            status_path = f"/sys/class/drm/{card_name}-{display}/status"
            cmd = f"sh -c 'echo off > {status_path}'"
            _ = run_command(cmd)
            print(f"  ✓ Turned off {display}")
        if connected_displays:
            _ = notify_hotplug(card_name)

    # Step 6: Clear any stale KWin output config, then turn on virtual display
    print(f"\nStep 6: Preparing virtual display ({empty_port})...")
    clear_kwin_output_config(empty_port)
    print(f"  Turning on virtual display ({empty_port})...")
    status_path = f"/sys/class/drm/{card_name}-{empty_port}/status"
    cmd = f"sh -c 'echo on > {status_path}'"
    result = run_command(cmd)

    if result.returncode != 0:
        print(f"  Error turning on display: {result.stderr}")
        return False

    # The sysfs write doesn't emit a hotplug uevent; without one KWin never
    # sees the new output and Step 7 times out.
    _ = notify_hotplug(card_name)
    print(f"  ✓ Virtual display enabled on {empty_port}")

    # Step 7: Wait for compositor to assign CRTC naturally, then fall back to forcing.
    # Do not force with direct DRM under Hyprland/KWin; that is the path that can
    # leave physical monitors stuck at 0x0 after disconnect.
    print(f"\nStep 7: Waiting for output to be ready...")
    ready, mode = wait_for_output_ready(card_name, empty_port, width, height, timeout=5.0)

    if ready:
        print(f"  ✓ Output ready ({mode})")
    elif safe_path:
        print("  ✗ Timed out waiting for virtual output; refusing to hide physical outputs")
        _ = run_command(f"sh -c 'echo off > /sys/class/drm/{card_name}-{empty_port}/status'")
        _ = run_command(f"sh -c 'cat /dev/null > {edid_override_path}'")
        _ = notify_hotplug(card_name)
        return False
    else:
        print(f"  ⚠ Compositor did not assign CRTC — forcing assignment...")
        _ = force_crtc_assignment(card_name, empty_port)
        ready, mode = wait_for_output_ready(card_name, empty_port, width, height, timeout=5.0)
        if ready:
            print(f"  ✓ Output ready ({mode})")
        else:
            print(f"  ⚠ Timed out waiting for output, proceeding anyway")

    if backend is not None and hide_outputs:
        print(f"\nStep 8: Hiding physical outputs via {backend_name}...")
        if backend.disable_outputs(hide_outputs):
            print(f"  ✓ Hidden: {', '.join(hide_outputs)}")
        else:
            print("  ✗ Could not hide one or more physical outputs — cleaning up virtual display")
            _ = run_command(f"sh -c 'echo off > /sys/class/drm/{card_name}-{empty_port}/status'")
            _ = run_command(f"sh -c 'cat /dev/null > {edid_override_path}'")
            _ = notify_hotplug(card_name)
            return False

    # Save state for disconnect (line 4 = edid_override_path for cleanup,
    # line 5 = compositor restore JSON when compositor-safe path was used,
    # line 6 = which compositor backend produced it,
    # line 7 = PID of the KWin session that owns the virtual display)
    kwin_pid = kwin.find_kwin_pid() if backend_name == "kwin" else None
    state_file = SCRIPT_DIR / "virt_display.state"
    _write_state_file(state_file, [
        card_name,
        empty_port,
        ",".join(connected_displays),
        str(edid_override_path),
        json.dumps(restore_specs),
        backend_name or "",
        "" if kwin_pid is None else str(kwin_pid),
    ])

    if backend_name == "kwin":
        # Sunshine's virtual touchscreen/pen appear right after this; map them
        # to the virtual output instead of the now-hidden physical one.
        _ = kwin.start_input_mapping(empty_port)
        # maliit keeps the physical monitor's size until it is restarted.
        _ = kwin.restart_virtual_keyboard_later(kwin_pid=kwin_pid)

    print(f"\n✓ Virtual display successfully connected!")
    print(f"  Port: {card_name}-{empty_port}")
    print(f"  Resolution: {width}x{height}@{refresh_rate}Hz")

    return True


def _output_connected(card_name: str, output: str) -> bool:
    try:
        return (DRM_SYSFS / f"{card_name}-{output}" / "status").read_text().strip() == "connected"
    except OSError:
        return False


def virtual_connector() -> str | None:
    """sysfs name (e.g. 'card1-DP-1') of the active virtual display, if any."""
    try:
        lines = (SCRIPT_DIR / "virt_display.state").read_text().strip().split("\n")
    except OSError:
        return None
    return f"{lines[0]}-{lines[1]}" if len(lines) > 1 and lines[0] and lines[1] else None


def physical_connectors() -> frozenset[str]:
    """Connected physical connectors across all cards, excluding the virtual display."""
    virtual = virtual_connector()
    connected: set[str] = set()
    for status in DRM_SYSFS.glob("card*-*/status"):
        name = status.parent.name
        if name == virtual or "Writeback" in name or "Virtual" in name:
            continue
        try:
            if status.read_text().strip() == "connected":
                connected.add(name)
        except OSError:
            continue
    return frozenset(connected)


def active_backend() -> str | None:
    """Compositor backend of the active virtual display session, if any."""
    state_file = SCRIPT_DIR / "virt_display.state"
    try:
        lines = state_file.read_text().strip().split("\n")
    except OSError:
        return None
    if len(lines) > 5 and lines[5]:
        return lines[5]
    if len(lines) > 4 and lines[4] not in ("", "{}"):
        return "hyprland"  # state files from before the KWin backend
    return None


def kwin_session_pid() -> int | None:
    """PID of the compositor that created the active virtual display, if known."""
    state_file = SCRIPT_DIR / "virt_display.state"
    try:
        lines = state_file.read_text().strip().split("\n")
    except OSError:
        return None
    if len(lines) > 6 and lines[6].isdigit():
        return int(lines[6])
    return None


def _write_state_file(state_file: Path, lines: list[str]) -> None:
    """Write the state file atomically; the daemon reads it from other threads."""
    temporary = state_file.with_name(state_file.name + ".tmp")
    _ = temporary.write_text("\n".join(lines))
    _ = temporary.replace(state_file)


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
    if len(state_data) < 2:
        print("Error: Invalid state file")
        return False

    card_name = state_data[0]
    virtual_port = state_data[1]
    previous_displays = state_data[2].split(",") if len(state_data) > 2 and state_data[2] else []
    try:
        restore_specs = json.loads(state_data[4]) if len(state_data) > 4 and state_data[4] else {}
    except json.JSONDecodeError:
        restore_specs = {}
    # Resolve the backend from the state file, not from the restore specs: a
    # session with no physical outputs still has a compositor backend that we
    # must use for touch mapping and the keyboard restart.
    backend_name = active_backend()
    backend = _SAFE_BACKENDS.get(backend_name) if backend_name else None
    kwin_pid = kwin_session_pid()

    print(f"  Virtual display: {card_name}-{virtual_port}")
    print(f"  Previous displays: {previous_displays if previous_displays else 'None'}")

    if backend_name == "kwin":
        kwin.stop_input_mapping()

    if backend is not None:
        print(f"\nStep 1: Restoring physical outputs via {backend_name}...")
        # A monitor unplugged during the stream can't be restored; trying would
        # fail the whole disconnect and leave the virtual display stuck on.
        unplugged = sorted(o for o in restore_specs if not _output_connected(card_name, o))
        if unplugged:
            print(f"  ⚠ No longer connected (unplugged?): {', '.join(unplugged)} — skipping")
            restore_specs = {o: s for o, s in restore_specs.items() if o not in unplugged}
        if not restore_specs:
            print("  ⚠ No physical outputs left to restore")
        elif backend.restore_outputs(restore_specs):
            print(f"  ✓ Restored: {', '.join(restore_specs.keys())}")
        elif backend_name == "kwin" and not kwin.session_alive(kwin_pid):
            # Logged out: there is no compositor left to restore into.  The
            # physical outputs were only disabled inside KWin, never at the
            # kernel level, so once the virtual output is gone the login
            # screen and the next session start on the physical monitor.
            print("  ⚠ KWin session has ended (logout) — skipping compositor restore,")
            print("    removing the virtual display so the next session uses the physical monitor")
        else:
            print(f"\n✗ {backend_name} restore failed — state file preserved so disconnect can be retried")
            return False
    else:
        # Turn on physical displays FIRST — avoid a zero-output window
        # that can confuse the compositor (KWin crashes or stops rendering if
        # all outputs disappear at once).
        print("\nStep 1: Turning on previous displays...")
        for disp in previous_displays:
            if disp:
                status_path = f"/sys/class/drm/{card_name}-{disp}/status"
                _ = run_command(f"sh -c 'echo on > {status_path}'")
                print(f"  ✓ Turned on {disp}")
        if any(previous_displays):
            _ = notify_hotplug(card_name)

        # Force CRTC assignment and verify each display is actually up.
        # On AMD, sysfs hotplug alone doesn't assign CRTCs. Retry up to 3 times
        # with a short delay; only proceed past this step when all displays are
        # confirmed active so the state file is never deleted on a partial restore.
        print("\nStep 2: Restoring physical displays...")
        all_restored = True
        for disp in previous_displays:
            if not disp:
                continue

            restored = False
            for attempt in range(1, 4):
                if attempt > 1:
                    print(f"  Retrying {disp} (attempt {attempt}/3)...")
                    time.sleep(2.0)

                ok = force_crtc_assignment(card_name, disp)
                if ok:
                    ready, mode = wait_for_output_ready(card_name, disp, 0, 0, timeout=5.0)
                    if ready:
                        print(f"  ✓ {disp} restored ({mode})")
                        restored = True
                        break
                    print(f"  ⚠ {disp}: CRTC assigned but compositor has not picked it up yet")
                else:
                    print(f"  ⚠ {disp}: CRTC assignment failed")

            if not restored:
                print(f"  ✗ {disp}: failed to restore after 3 attempts")
                all_restored = False

        if not all_restored:
            print("\n✗ Not all displays restored — state file preserved so disconnect can be retried")
            return False

        print(f"\nStep 3: Releasing CRTC from virtual display ({virtual_port})...")
        _ = release_crtc(card_name, virtual_port)

    print(f"\nStep 4: Turning off virtual display ({virtual_port})...")
    status_path = f"/sys/class/drm/{card_name}-{virtual_port}/status"
    result = run_command(f"sh -c 'echo off > {status_path}'")

    if result.returncode != 0:
        print(f"  Warning: Could not turn off virtual display: {result.stderr}")
    else:
        print(f"  ✓ Virtual display turned off")

    # Clear the EDID override so the port shows as disconnected on the next connect.
    # Without this, a future connect() sees the port as connected and stores it in
    # previous_displays, causing disconnect to try to restore a virtual port as if
    # it were a physical display.
    edid_override_path = state_data[3] if len(state_data) > 3 else ""
    if edid_override_path:
        _ = run_command(f"sh -c 'cat /dev/null > {edid_override_path}'")
        print(f"  ✓ EDID override cleared")

    # Without a hotplug uevent the compositor keeps the (now disconnected)
    # virtual output around as an invisible extra screen.
    _ = notify_hotplug(card_name)

    if backend_name == "kwin":
        # ...and maliit keeps the phone's size until it is restarted.
        _ = kwin.restart_virtual_keyboard_later(kwin_pid=kwin_pid)

    state_file.unlink()

    print("\n✓ Virtual display disconnected!")
    return True
