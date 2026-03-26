"""
libdrm ctypes bindings: structs, ioctl constants, library loader,
and low-level connector/CRTC helpers.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import Any, Literal, Protocol, cast, final

# ---------------------------------------------------------------------------
# ioctl constants
# ---------------------------------------------------------------------------

DRM_DISPLAY_MODE_LEN: int = 32
DRM_IOCTL_SET_MASTER: int = 0x0000641E
DRM_IOCTL_DROP_MASTER: int = 0x0000641F

# _IOWR('d', 0xB2, struct drm_mode_create_dumb)
DRM_IOCTL_MODE_CREATE_DUMB: int = 0xC02064B2
# _IOWR('d', 0xAE, struct drm_mode_fb_cmd)
DRM_IOCTL_MODE_ADDFB: int = 0xC01C64AE
# _IOWR('d', 0xAF, uint32_t)
DRM_IOCTL_MODE_RMFB: int = 0xC00464AF
# _IOWR('d', 0xB4, struct drm_mode_destroy_dumb)
DRM_IOCTL_MODE_DESTROY_DUMB: int = 0xC00464B4

# ---------------------------------------------------------------------------
# Connector type lookup tables (internal)
# ---------------------------------------------------------------------------

_CONNECTOR_TYPE_NAMES: dict[int, str] = {
    0: "Unknown", 1: "VGA", 2: "DVII", 3: "DVID", 4: "DVIA",
    5: "Composite", 6: "SVIDEO", 7: "LVDS", 8: "Component",
    9: "9PinDIN", 10: "DisplayPort", 11: "HDMIA", 12: "HDMIB",
    13: "TV", 14: "eDP", 15: "VIRTUAL", 16: "DSI", 17: "DPI",
    18: "WRITEBACK", 19: "SPI", 20: "USB",
}

_SYSFS_TO_DRM_TYPE: dict[str, str] = {
    "DP": "DisplayPort",
    "HDMI-A": "HDMIA",
    "HDMI": "HDMIA",
}

# ---------------------------------------------------------------------------
# ctypes structs (internal)
# ---------------------------------------------------------------------------


@final
class DrmModeModeInfo(ctypes.Structure):
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


@final
class DrmModeCreateDumb(ctypes.Structure):
    _fields_ = [
        ("height", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("bpp", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("handle", ctypes.c_uint32),  # output
        ("pitch", ctypes.c_uint32),   # output
        ("size", ctypes.c_uint64),    # output
    ]


@final
class DrmModeFbCmd(ctypes.Structure):
    _fields_ = [
        ("fb_id", ctypes.c_uint32),   # output
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pitch", ctypes.c_uint32),
        ("bpp", ctypes.c_uint32),
        ("depth", ctypes.c_uint32),
        ("handle", ctypes.c_uint32),
    ]


@final
class DrmModeDestroyDumb(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint32),
    ]


@final
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


@final
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
        ("modes", ctypes.POINTER(DrmModeModeInfo)),
        ("count_props", ctypes.c_int),
        ("props", ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values", ctypes.POINTER(ctypes.c_uint64)),
        ("count_encoders", ctypes.c_int),
        ("encoders", ctypes.POINTER(ctypes.c_uint32)),
    ]


@final
class _DrmModeEncoder(ctypes.Structure):
    _fields_ = [
        ("encoder_id", ctypes.c_uint32),
        ("encoder_type", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("possible_clones", ctypes.c_uint32),
    ]


@final
class _DrmModeCrtc(ctypes.Structure):
    _fields_ = [
        ("crtc_id", ctypes.c_uint32),
        ("buffer_id", ctypes.c_uint32),
        ("x", ctypes.c_uint32),
        ("y", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("mode_valid", ctypes.c_int),
        ("mode", DrmModeModeInfo),
        ("gamma_size", ctypes.c_int),
    ]


# ---------------------------------------------------------------------------
# LibDRM Protocol — typed interface for the loaded libdrm shared library
# ---------------------------------------------------------------------------


class LibDRM(Protocol):
    def drmModeGetResources(self, fd: int) -> Any: ...
    def drmModeFreeResources(self, resources: Any) -> None: ...
    def drmModeGetConnector(self, fd: int, connector_id: int) -> Any: ...
    def drmModeFreeConnector(self, connector: Any) -> None: ...
    def drmModeGetEncoder(self, fd: int, encoder_id: int) -> Any: ...
    def drmModeFreeEncoder(self, encoder: Any) -> None: ...
    def drmModeGetCrtc(self, fd: int, crtc_id: int) -> Any: ...
    def drmModeFreeCrtc(self, crtc: Any) -> None: ...
    def drmModeSetCrtc(
        self,
        fd: int,
        crtc_id: int,
        fb_id: int,
        x: int,
        y: int,
        connectors: Any,
        count: int,
        mode: Any,
    ) -> int: ...


# ---------------------------------------------------------------------------
# Library loader
# ---------------------------------------------------------------------------


def load_libdrm() -> LibDRM | None:
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
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_int,
            ctypes.POINTER(DrmModeModeInfo),
        ]
        return cast(LibDRM, cast(object, lib))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Connector/CRTC helpers
# ---------------------------------------------------------------------------


def sysfs_port_to_drm_name(port: str) -> tuple[str | None, int | None]:
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


def find_connector(
    libdrm: LibDRM,
    fd: int,
    res: Any,
    target_type_name: str,
    target_type_id: int,
) -> Any | None:
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


def _find_free_crtc(
    libdrm: LibDRM,
    fd: int,
    res: Any,
    connector_p: Any,
) -> int:
    """
    Find a CRTC that can drive the given connector.
    Prefers an inactive CRTC. Returns crtc_id or 0.
    """
    r = res.contents
    conn = connector_p.contents

    # Build set of CRTCs currently in use by other connectors
    used_crtcs: set[int] = set()
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
        possible: int = enc_p.contents.possible_crtcs
        libdrm.drmModeFreeEncoder(enc_p)

        # possible_crtcs is a bitmask over the CRTC array index
        for ci in range(r.count_crtcs):
            if not (possible & (1 << ci)):
                continue
            crtc_id: int = r.crtcs[ci]
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


def probe_connector(
    libdrm: LibDRM,
    fd: int,
    res: Any,
    drm_type: str,
    type_id: int,
    port: str,
    silent: bool = False,
) -> Literal[True] | None | tuple[int, int, DrmModeModeInfo]:
    """
    Check connector state. Returns:
      True      — already has a CRTC, nothing to do
      None      — error (not found, not connected, no modes)
      (crtc_id, connector_id, mode_copy) — needs SetCrtc

    Pass silent=True to suppress transient "not connected" messages during
    retry loops.
    """
    conn_p = find_connector(libdrm, fd, res, drm_type, type_id)
    if not conn_p:
        print(f"    Connector {drm_type}-{type_id} not found in DRM")
        return None

    try:
        conn = conn_p.contents

        if conn.connection != 1:
            if not silent:
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
        mode_copy = DrmModeModeInfo()
        ctypes.memmove(
            ctypes.byref(mode_copy),
            ctypes.byref(conn.modes[0]),
            ctypes.sizeof(DrmModeModeInfo),
        )

        crtc_id = _find_free_crtc(libdrm, fd, res, conn_p)
        if not crtc_id:
            print(f"    No compatible CRTC found for {port}")
            return None

        return (crtc_id, conn.connector_id, mode_copy)
    finally:
        libdrm.drmModeFreeConnector(conn_p)
