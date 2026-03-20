"""
DRM/sysfs helpers for discovering GPU devices, display ports, and connector state.
Includes libdrm ctypes bindings for forcing CRTC assignment via ioctl.
"""

import ctypes
import ctypes.util
import fcntl
import os
import subprocess
import time
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


def wait_for_output_ready(card_name, port, width, height, timeout=4.0):
    """
    Poll sysfs until the DRM connector is fully configured.
    Returns (ready, mode_string).
    """
    expected_res = f"{width}x{height}"
    sysfs_base = Path(f"/sys/class/drm/{card_name}-{port}")
    poll_interval = 0.1
    max_polls = int(timeout / poll_interval)

    for _ in range(max_polls):
        try:
            status = (sysfs_base / "status").read_text().strip()
            enabled = (sysfs_base / "enabled").read_text().strip()
            modes_file = sysfs_base / "modes"
            mode = modes_file.read_text().strip().split("\n")[0] if modes_file.exists() else ""

            if status == "connected" and enabled == "enabled" and expected_res in mode:
                # Small grace period for compositor to finish
                time.sleep(0.5)
                return True, mode
        except (OSError, IOError):
            pass

        time.sleep(poll_interval)

    return False, ""


# ---------------------------------------------------------------------------
# libdrm ctypes bindings for CRTC assignment
# ---------------------------------------------------------------------------

DRM_DISPLAY_MODE_LEN = 32
DRM_IOCTL_SET_MASTER = 0x0000641E
DRM_IOCTL_DROP_MASTER = 0x0000641F

# ioctl numbers for dumb buffer creation/destruction and framebuffer add/remove
# _IOWR('d', 0xB2, struct drm_mode_create_dumb) — create dumb buffer
DRM_IOCTL_MODE_CREATE_DUMB = 0xC02064B2
# _IOWR('d', 0xAE, struct drm_mode_fb_cmd) — add framebuffer
DRM_IOCTL_MODE_ADDFB = 0xC01C64AE
# _IOWR('d', 0xAF, uint32_t) — remove framebuffer
DRM_IOCTL_MODE_RMFB = 0xC00464AF
# _IOWR('d', 0xB4, struct drm_mode_destroy_dumb) — destroy dumb buffer
DRM_IOCTL_MODE_DESTROY_DUMB = 0xC00464B4


class _DrmModeCreateDumb(ctypes.Structure):
    _fields_ = [
        ("height", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("bpp", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("handle", ctypes.c_uint32),  # output
        ("pitch", ctypes.c_uint32),   # output
        ("size", ctypes.c_uint64),    # output
    ]


class _DrmModeFbCmd(ctypes.Structure):
    _fields_ = [
        ("fb_id", ctypes.c_uint32),   # output
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pitch", ctypes.c_uint32),
        ("bpp", ctypes.c_uint32),
        ("depth", ctypes.c_uint32),
        ("handle", ctypes.c_uint32),
    ]


class _DrmModeDestroyDumb(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint32),
    ]

# Connector type names (DRM_MODE_CONNECTOR_*)
_CONNECTOR_TYPE_NAMES = {
    0: "Unknown", 1: "VGA", 2: "DVII", 3: "DVID", 4: "DVIA",
    5: "Composite", 6: "SVIDEO", 7: "LVDS", 8: "Component",
    9: "9PinDIN", 10: "DisplayPort", 11: "HDMIA", 12: "HDMIB",
    13: "TV", 14: "eDP", 15: "VIRTUAL", 16: "DSI", 17: "DPI",
    18: "WRITEBACK", 19: "SPI", 20: "USB",
}

# Port name prefix in sysfs -> DRM connector type names
_SYSFS_TO_DRM_TYPE = {
    "DP": "DisplayPort",
    "HDMI-A": "HDMIA",
    "HDMI": "HDMIA",
}


class _DrmModeModeInfo(ctypes.Structure):
    _fields_ = [
        ("clock", ctypes.c_uint32),
        ("hdisplay", ctypes.c_uint16),
        ("hsync_start", ctypes.c_uint16),
        ("hsync_end", ctypes.c_uint16),
        ("htotal", ctypes.c_uint16),
        ("hskew", ctypes.c_uint16),
        ("vdisplay", ctypes.c_uint16),
        ("vsync_start", ctypes.c_uint16),
        ("vsync_end", ctypes.c_uint16),
        ("vtotal", ctypes.c_uint16),
        ("vscan", ctypes.c_uint16),
        ("vrefresh", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("name", ctypes.c_char * DRM_DISPLAY_MODE_LEN),
    ]


class _DrmModeRes(ctypes.Structure):
    _fields_ = [
        ("count_fbs", ctypes.c_int),
        ("fbs", ctypes.POINTER(ctypes.c_uint32)),
        ("count_crtcs", ctypes.c_int),
        ("crtcs", ctypes.POINTER(ctypes.c_uint32)),
        ("count_connectors", ctypes.c_int),
        ("connectors", ctypes.POINTER(ctypes.c_uint32)),
        ("count_encoders", ctypes.c_int),
        ("encoders", ctypes.POINTER(ctypes.c_uint32)),
        ("min_width", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
    ]


class _DrmModeConnector(ctypes.Structure):
    _fields_ = [
        ("connector_id", ctypes.c_uint32),
        ("encoder_id", ctypes.c_uint32),
        ("connector_type", ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection", ctypes.c_uint32),  # 1=connected 2=disconnected 3=unknown
        ("mmWidth", ctypes.c_uint32),
        ("mmHeight", ctypes.c_uint32),
        ("subpixel", ctypes.c_uint32),
        ("count_modes", ctypes.c_int),
        ("modes", ctypes.POINTER(_DrmModeModeInfo)),
        ("count_props", ctypes.c_int),
        ("props", ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values", ctypes.POINTER(ctypes.c_uint64)),
        ("count_encoders", ctypes.c_int),
        ("encoders", ctypes.POINTER(ctypes.c_uint32)),
    ]


class _DrmModeEncoder(ctypes.Structure):
    _fields_ = [
        ("encoder_id", ctypes.c_uint32),
        ("encoder_type", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("possible_clones", ctypes.c_uint32),
    ]


class _DrmModeCrtc(ctypes.Structure):
    _fields_ = [
        ("crtc_id", ctypes.c_uint32),
        ("buffer_id", ctypes.c_uint32),
        ("x", ctypes.c_uint32),
        ("y", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("mode_valid", ctypes.c_int),
        ("mode", _DrmModeModeInfo),
        ("gamma_size", ctypes.c_int),
    ]


def _load_libdrm():
    """Load libdrm and set up function signatures."""
    name = ctypes.util.find_library("drm")
    if not name:
        return None
    try:
        lib = ctypes.CDLL(name)
        lib.drmModeGetResources.restype = ctypes.POINTER(_DrmModeRes)
        lib.drmModeFreeResources.restype = None
        lib.drmModeGetConnector.restype = ctypes.POINTER(_DrmModeConnector)
        lib.drmModeFreeConnector.restype = None
        lib.drmModeGetEncoder.restype = ctypes.POINTER(_DrmModeEncoder)
        lib.drmModeFreeEncoder.restype = None
        lib.drmModeGetCrtc.restype = ctypes.POINTER(_DrmModeCrtc)
        lib.drmModeFreeCrtc.restype = None
        lib.drmModeSetCrtc.restype = ctypes.c_int
        lib.drmModeSetCrtc.argtypes = [
            ctypes.c_int,                          # fd
            ctypes.c_uint32,                       # crtc_id
            ctypes.c_uint32,                       # fb_id
            ctypes.c_uint32,                       # x
            ctypes.c_uint32,                       # y
            ctypes.POINTER(ctypes.c_uint32),       # connectors
            ctypes.c_int,                          # count
            ctypes.POINTER(_DrmModeModeInfo),      # mode
        ]
        return lib
    except Exception:
        return None


def _sysfs_port_to_drm_name(port):
    """
    Convert sysfs port name (e.g. 'DP-2', 'HDMI-A-1') to the DRM connector
    type name + type_id tuple (e.g. ('DisplayPort', 2), ('HDMIA', 1)).
    """
    for prefix, drm_type in _SYSFS_TO_DRM_TYPE.items():
        if port.startswith(prefix + "-"):
            suffix = port[len(prefix) + 1:]
            try:
                return drm_type, int(suffix)
            except ValueError:
                pass
    return None, None


def _find_connector(libdrm, fd, res, target_type_name, target_type_id):
    """Find a connector by DRM type name and type_id. Returns pointer or None."""
    r = res.contents
    for i in range(r.count_connectors):
        conn_p = libdrm.drmModeGetConnector(fd, r.connectors[i])
        if not conn_p:
            continue
        c = conn_p.contents
        type_name = _CONNECTOR_TYPE_NAMES.get(c.connector_type, "")
        if type_name == target_type_name and c.connector_type_id == target_type_id:
            return conn_p
        libdrm.drmModeFreeConnector(conn_p)
    return None


def _find_free_crtc(libdrm, fd, res, connector_p):
    """
    Find a CRTC that can drive the given connector.
    Prefers an inactive CRTC. Returns crtc_id or 0.
    """
    r = res.contents
    conn = connector_p.contents

    # Build set of CRTCs currently in use by other connectors
    used_crtcs = set()
    for i in range(r.count_connectors):
        other_p = libdrm.drmModeGetConnector(fd, r.connectors[i])
        if not other_p:
            continue
        o = other_p.contents
        if o.connector_id != conn.connector_id and o.encoder_id:
            enc_p = libdrm.drmModeGetEncoder(fd, o.encoder_id)
            if enc_p:
                if enc_p.contents.crtc_id:
                    used_crtcs.add(enc_p.contents.crtc_id)
                libdrm.drmModeFreeEncoder(enc_p)
        libdrm.drmModeFreeConnector(other_p)

    # Try each encoder the connector supports
    for ei in range(conn.count_encoders):
        enc_p = libdrm.drmModeGetEncoder(fd, conn.encoders[ei])
        if not enc_p:
            continue
        possible = enc_p.contents.possible_crtcs
        libdrm.drmModeFreeEncoder(enc_p)

        # possible_crtcs is a bitmask over the CRTC array index
        for ci in range(r.count_crtcs):
            if not (possible & (1 << ci)):
                continue
            crtc_id = r.crtcs[ci]
            if crtc_id not in used_crtcs:
                return crtc_id

    # Fallback: steal any compatible CRTC (even if in use)
    for ei in range(conn.count_encoders):
        enc_p = libdrm.drmModeGetEncoder(fd, conn.encoders[ei])
        if not enc_p:
            continue
        possible = enc_p.contents.possible_crtcs
        libdrm.drmModeFreeEncoder(enc_p)

        for ci in range(r.count_crtcs):
            if possible & (1 << ci):
                return r.crtcs[ci]

    return 0


def _find_compositor_pid_and_fd(card_path):
    """
    Find the process that holds DRM master for the given card device.
    Scans /proc for processes with the card open, then tests each by
    attempting DROP_MASTER via pidfd_getfd to confirm it's the real master.
    Returns (pid, fd_number) or (None, None).
    """
    try:
        card_rdev = os.stat(card_path).st_rdev
    except OSError:
        return None, None

    # Collect all (pid, fd_num) candidates
    candidates = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if pid == os.getpid():
            continue
        fd_dir = proc / "fd"
        try:
            for entry in fd_dir.iterdir():
                try:
                    st = os.stat(str(entry))
                    if st.st_rdev == card_rdev:
                        candidates.append((pid, int(entry.name)))
                except (OSError, ValueError):
                    continue
        except (OSError, PermissionError):
            continue

    # Test each candidate — the real DRM master holder is the one where
    # DROP_MASTER succeeds on their duplicated fd.
    for pid, fd_num in candidates:
        try:
            pidfd = _pidfd_open(pid)
            try:
                dup_fd = _pidfd_getfd(pidfd, fd_num)
            finally:
                os.close(pidfd)
            try:
                fcntl.ioctl(dup_fd, DRM_IOCTL_DROP_MASTER, 0)
                # It worked — restore master and return this candidate
                fcntl.ioctl(dup_fd, DRM_IOCTL_SET_MASTER, 0)
                os.close(dup_fd)
                return pid, fd_num
            except OSError:
                os.close(dup_fd)
        except OSError:
            continue

    return None, None


# Syscall numbers (x86_64)
_SYS_PIDFD_OPEN = 434
_SYS_PIDFD_GETFD = 438

_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.syscall.restype = ctypes.c_long


def _pidfd_open(pid, flags=0):
    rc = _libc.syscall(_SYS_PIDFD_OPEN, ctypes.c_int(pid), ctypes.c_uint(flags))
    if rc < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"pidfd_open({pid}): {os.strerror(errno)}")
    return rc


def _pidfd_getfd(pidfd, targetfd, flags=0):
    rc = _libc.syscall(
        _SYS_PIDFD_GETFD,
        ctypes.c_int(pidfd),
        ctypes.c_int(targetfd),
        ctypes.c_uint(flags),
    )
    if rc < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"pidfd_getfd({targetfd}): {os.strerror(errno)}")
    return rc


def _with_drm_master(card_path, callback):
    """
    Temporarily acquire DRM master, run callback(fd), then restore master
    to the original holder (compositor).

    Uses pidfd_getfd to duplicate the compositor's DRM fd so we can
    drop/restore their master status.
    """
    # First try the simple path — maybe no compositor is running
    our_fd = os.open(card_path, os.O_RDWR | os.O_CLOEXEC)
    try:
        try:
            fcntl.ioctl(our_fd, DRM_IOCTL_SET_MASTER, 0)
            # Simple path worked — no compositor holding master
            try:
                return callback(our_fd)
            finally:
                try:
                    fcntl.ioctl(our_fd, DRM_IOCTL_DROP_MASTER, 0)
                except OSError:
                    pass
        except OSError:
            pass  # EBUSY — compositor holds master, use pidfd path
    except Exception:
        os.close(our_fd)
        raise

    os.close(our_fd)

    # Find the compositor's DRM fd
    comp_pid, comp_fd_num = _find_compositor_pid_and_fd(card_path)
    if comp_pid is None:
        raise RuntimeError("Could not find process holding DRM master")

    print(f"    Borrowing DRM master from PID {comp_pid} (fd {comp_fd_num})")

    # Duplicate the compositor's fd via pidfd_getfd (shares the same drm_file)
    pidfd = _pidfd_open(comp_pid)
    try:
        stolen_fd = _pidfd_getfd(pidfd, comp_fd_num)
    finally:
        os.close(pidfd)

    try:
        # Drop master on the compositor's drm_file
        fcntl.ioctl(stolen_fd, DRM_IOCTL_DROP_MASTER, 0)
        print(f"    Compositor master dropped, acquiring our own...")

        # Now open our own fd and acquire master
        our_fd = os.open(card_path, os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.ioctl(our_fd, DRM_IOCTL_SET_MASTER, 0)
            try:
                return callback(our_fd)
            finally:
                # Drop our master
                try:
                    fcntl.ioctl(our_fd, DRM_IOCTL_DROP_MASTER, 0)
                except OSError:
                    pass
        finally:
            os.close(our_fd)
    finally:
        # Restore master to compositor
        try:
            fcntl.ioctl(stolen_fd, DRM_IOCTL_SET_MASTER, 0)
        except OSError:
            pass
        os.close(stolen_fd)


def force_crtc_assignment(card_name, port):
    """
    Force a CRTC onto a connected connector that has no CRTC assigned.
    Temporarily borrows DRM master from the compositor via pidfd_getfd,
    calls drmModeSetCrtc, then restores master.

    Returns True if CRTC was successfully assigned (or was already assigned).
    """
    libdrm = _load_libdrm()
    if not libdrm:
        print("    Could not load libdrm")
        return False

    drm_type, type_id = _sysfs_port_to_drm_name(port)
    if not drm_type:
        print(f"    Could not parse port name: {port}")
        return False

    card_path = f"/dev/dri/{card_name}"

    # First check state without needing master (read-only)
    try:
        probe_fd = os.open(card_path, os.O_RDWR | os.O_CLOEXEC)
    except OSError as e:
        print(f"    Could not open {card_path}: {e}")
        return False

    try:
        res = libdrm.drmModeGetResources(probe_fd)
        if not res:
            print("    drmModeGetResources failed")
            return False

        try:
            result = _probe_connector(libdrm, probe_fd, res, drm_type, type_id, port)
        finally:
            libdrm.drmModeFreeResources(res)

        if result is None:
            return False  # error already printed
        if result is True:
            return True  # already has CRTC

        # result is (crtc_id, connector_id, mode) — need to do the SetCrtc
        crtc_id, connector_id, mode_copy = result
    finally:
        os.close(probe_fd)

    print(f"    Assigning CRTC {crtc_id} to {port} ({mode_copy.hdisplay}x{mode_copy.vdisplay})")

    def do_set_crtc(master_fd):
        # Create a dumb framebuffer — amdgpu requires a real fb_id
        create = _DrmModeCreateDumb()
        create.width = mode_copy.hdisplay
        create.height = mode_copy.vdisplay
        create.bpp = 32
        create.flags = 0

        try:
            fcntl.ioctl(master_fd, DRM_IOCTL_MODE_CREATE_DUMB, create)
        except OSError as e:
            print(f"    Failed to create dumb buffer: {e}")
            return False
        print(f"    Dumb buffer created: handle={create.handle} pitch={create.pitch} size={create.size}")

        # Add framebuffer
        fb = _DrmModeFbCmd()
        fb.width = mode_copy.hdisplay
        fb.height = mode_copy.vdisplay
        fb.pitch = create.pitch
        fb.bpp = 32
        fb.depth = 24
        fb.handle = create.handle

        try:
            fcntl.ioctl(master_fd, DRM_IOCTL_MODE_ADDFB, fb)
        except OSError as e:
            print(f"    Failed to add framebuffer: {e}")
            # Clean up dumb buffer
            destroy = _DrmModeDestroyDumb()
            destroy.handle = create.handle
            try:
                fcntl.ioctl(master_fd, DRM_IOCTL_MODE_DESTROY_DUMB, destroy)
            except OSError:
                pass
            return False

        # Set CRTC with the real framebuffer
        conn_ids = (ctypes.c_uint32 * 1)(connector_id)
        ret = libdrm.drmModeSetCrtc(
            master_fd,
            crtc_id,
            fb.fb_id,
            0, 0,  # x, y
            conn_ids,
            1,
            ctypes.byref(mode_copy),
        )

        if ret == 0:
            print(f"    CRTC {crtc_id} assigned successfully (fb={fb.fb_id})")
            return True
        else:
            print(f"    drmModeSetCrtc failed (ret={ret})")
            # Clean up on failure
            try:
                fcntl.ioctl(master_fd, DRM_IOCTL_MODE_RMFB, ctypes.c_uint32(fb.fb_id))
            except OSError:
                pass
            destroy = _DrmModeDestroyDumb()
            destroy.handle = create.handle
            try:
                fcntl.ioctl(master_fd, DRM_IOCTL_MODE_DESTROY_DUMB, destroy)
            except OSError:
                pass
            return False

    try:
        return _with_drm_master(card_path, do_set_crtc)
    except Exception as e:
        print(f"    Failed to force CRTC assignment: {e}")
        return False


def _probe_connector(libdrm, fd, res, drm_type, type_id, port):
    """
    Check connector state. Returns:
      True      — already has a CRTC, nothing to do
      None      — error (not found, not connected, no modes)
      (crtc_id, connector_id, mode_copy) — needs SetCrtc
    """
    conn_p = _find_connector(libdrm, fd, res, drm_type, type_id)
    if not conn_p:
        print(f"    Connector {drm_type}-{type_id} not found in DRM")
        return None

    try:
        conn = conn_p.contents

        if conn.connection != 1:
            print(f"    Connector {port} is not DRM-connected (status={conn.connection})")
            return None

        # Check if it already has a CRTC
        if conn.encoder_id:
            enc_p = libdrm.drmModeGetEncoder(fd, conn.encoder_id)
            if enc_p:
                if enc_p.contents.crtc_id:
                    print(f"    Connector {port} already has CRTC {enc_p.contents.crtc_id}")
                    libdrm.drmModeFreeEncoder(enc_p)
                    return True
                libdrm.drmModeFreeEncoder(enc_p)

        if conn.count_modes < 1:
            print(f"    Connector {port} has no modes available")
            return None

        # Copy the mode so it outlives the connector pointer
        mode_copy = _DrmModeModeInfo()
        ctypes.memmove(ctypes.byref(mode_copy), ctypes.byref(conn.modes[0]),
                       ctypes.sizeof(_DrmModeModeInfo))

        crtc_id = _find_free_crtc(libdrm, fd, res, conn_p)
        if not crtc_id:
            print(f"    No compatible CRTC found for {port}")
            return None

        return (crtc_id, conn.connector_id, mode_copy)
    finally:
        libdrm.drmModeFreeConnector(conn_p)
