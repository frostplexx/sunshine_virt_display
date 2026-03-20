#!/usr/bin/env python3
"""
debug_virt_display.py - Snapshot the display/capture state relevant to
sunshine_virt_display.

Run as root (sudo python3 debug_virt_display.py) for full DRM access.
Run without sudo for the sysfs-only view.

Usage:
    sudo python3 scripts/debug_virt_display.py
"""

import ctypes
import ctypes.util
import os
import subprocess
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers  (plain text only — no ANSI escapes, safe for GitHub issues)
# ---------------------------------------------------------------------------

def hdr(title):
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")


def ok(msg):   print(f"  [OK]   {msg}")
def warn(msg): print(f"  [WARN] {msg}")
def err(msg):  print(f"  [ERR]  {msg}")
def info(msg): print(f"         {msg}")


def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return "", str(e)


# ---------------------------------------------------------------------------
# Section 1 — sysfs connector status
# ---------------------------------------------------------------------------

def section_sysfs_connectors():
    hdr("1. sysfs DRM connector status  (/sys/class/drm/)")

    drm = Path("/sys/class/drm")
    if not drm.exists():
        err("/sys/class/drm not found")
        return

    for entry in sorted(drm.iterdir()):
        if "-" not in entry.name:
            continue
        status_f = entry / "status"
        enabled_f = entry / "enabled"
        if not status_f.exists():
            continue

        status = status_f.read_text().strip()
        enabled = enabled_f.read_text().strip() if enabled_f.exists() else "?"

        marker = " *" if status == "connected" else "  "
        print(f"  {marker} {entry.name:<30}  status={status:<14} enabled={enabled}")


# ---------------------------------------------------------------------------
# Section 2 — KMS connector / encoder / CRTC state (libdrm)
# ---------------------------------------------------------------------------

class _DrmModeRes(ctypes.Structure):
    _fields_ = [
        ("count_fbs",        ctypes.c_int),
        ("fbs",              ctypes.POINTER(ctypes.c_uint32)),
        ("count_crtcs",      ctypes.c_int),
        ("crtcs",            ctypes.POINTER(ctypes.c_uint32)),
        ("count_connectors", ctypes.c_int),
        ("connectors",       ctypes.POINTER(ctypes.c_uint32)),
        ("count_encoders",   ctypes.c_int),
        ("encoders",         ctypes.POINTER(ctypes.c_uint32)),
        ("min_width",        ctypes.c_uint32),
        ("max_width",        ctypes.c_uint32),
        ("min_height",       ctypes.c_uint32),
        ("max_height",       ctypes.c_uint32),
    ]

class _DrmModeConnector(ctypes.Structure):
    _fields_ = [
        ("connector_id",      ctypes.c_uint32),
        ("encoder_id",        ctypes.c_uint32),
        ("connector_type",    ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection",        ctypes.c_uint32),
        ("mmWidth",           ctypes.c_uint32),
        ("mmHeight",          ctypes.c_uint32),
        ("subpixel",          ctypes.c_uint32),
        ("count_modes",       ctypes.c_int),
        ("modes",             ctypes.c_void_p),
        ("count_props",       ctypes.c_int),
        ("props",             ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values",       ctypes.POINTER(ctypes.c_uint64)),
        ("count_encoders",    ctypes.c_int),
        ("encoders",          ctypes.POINTER(ctypes.c_uint32)),
    ]

class _DrmModeEncoder(ctypes.Structure):
    _fields_ = [
        ("encoder_id",      ctypes.c_uint32),
        ("encoder_type",    ctypes.c_uint32),
        ("crtc_id",         ctypes.c_uint32),
        ("possible_crtcs",  ctypes.c_uint32),
        ("possible_clones", ctypes.c_uint32),
    ]

class _DrmModeCrtc(ctypes.Structure):
    _fields_ = [
        ("crtc_id",    ctypes.c_uint32),
        ("buffer_id",  ctypes.c_uint32),
        ("x",          ctypes.c_uint32),
        ("y",          ctypes.c_uint32),
        ("width",      ctypes.c_uint32),
        ("height",     ctypes.c_uint32),
        ("mode_valid", ctypes.c_int),
        ("_mode_info", ctypes.c_uint8 * 292),
        ("gamma_size", ctypes.c_int),
    ]

CONNECTOR_TYPE_NAMES = {
    0: "Unknown", 1: "VGA", 2: "DVII", 3: "DVID", 4: "DVIA",
    5: "Composite", 6: "SVIDEO", 7: "LVDS", 8: "Component",
    9: "9PinDIN", 10: "DisplayPort", 11: "HDMIA", 12: "HDMIB",
    13: "TV", 14: "eDP", 15: "VIRTUAL", 16: "DSI", 17: "DPI",
    18: "WRITEBACK", 19: "SPI", 20: "USB",
}
CONN_STATUS = {1: "connected", 2: "disconnected", 3: "unknown"}


def _load_libdrm():
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
        return lib
    except Exception:
        return None


def section_kms_connectors():
    hdr("2. KMS connector / encoder / CRTC state  (libdrm)")

    libdrm = _load_libdrm()
    if not libdrm:
        warn("libdrm not found -- skipping KMS section")
        return

    dri = Path("/dev/dri")
    if not dri.exists():
        err("/dev/dri not found")
        return

    cards = sorted(dri.glob("card[0-9]*"))
    if not cards:
        err("No /dev/dri/card* devices found")
        return

    for card_path in cards:
        print(f"\n  {card_path}")

        try:
            fd = os.open(str(card_path), os.O_RDWR | os.O_CLOEXEC)
        except PermissionError:
            warn("  Permission denied -- run as root for full KMS view")
            continue
        except Exception as e:
            err(f"  Could not open: {e}")
            continue

        # Driver name
        out, _ = run(f"cat /sys/class/drm/{card_path.name}/device/uevent 2>/dev/null | grep DRIVER")
        driver = out.split("=")[-1] if "=" in out else "?"
        print(f"    driver: {driver}")

        res = libdrm.drmModeGetResources(fd)
        if not res:
            warn("    drmModeGetResources returned NULL")
            os.close(fd)
            continue

        r = res.contents

        # CRTCs
        print(f"\n    CRTCs ({r.count_crtcs}):")
        for i in range(r.count_crtcs):
            cid = r.crtcs[i]
            crtc_p = libdrm.drmModeGetCrtc(fd, cid)
            if crtc_p:
                c = crtc_p.contents
                active = c.buffer_id != 0
                if active:
                    status_str = f"ACTIVE  fb={c.buffer_id} {c.width}x{c.height}"
                else:
                    status_str = "inactive fb=0"
                print(f"      [{i}] CRTC {cid}: {status_str}")
                libdrm.drmModeFreeCrtc(crtc_p)
            else:
                print(f"      [{i}] CRTC {cid}: (could not query)")

        # Connectors
        print(f"\n    Connectors ({r.count_connectors}):")
        for i in range(r.count_connectors):
            conn_id = r.connectors[i]
            conn_p = libdrm.drmModeGetConnector(fd, conn_id)
            if not conn_p:
                continue
            c = conn_p.contents

            type_name = CONNECTOR_TYPE_NAMES.get(c.connector_type, str(c.connector_type))
            conn_name = f"{type_name}-{c.connector_type_id}"
            status_str = CONN_STATUS.get(c.connection, "unknown")

            # Encoder -> CRTC chain
            crtc_id = 0
            enc_id = c.encoder_id
            if enc_id:
                enc_p = libdrm.drmModeGetEncoder(fd, enc_id)
                if enc_p:
                    crtc_id = enc_p.contents.crtc_id
                    libdrm.drmModeFreeEncoder(enc_p)

            # Gather possible_crtcs from all encoders
            all_possible = 0
            for ei in range(c.count_encoders):
                enc_p = libdrm.drmModeGetEncoder(fd, c.encoders[ei])
                if enc_p:
                    all_possible |= enc_p.contents.possible_crtcs
                    libdrm.drmModeFreeEncoder(enc_p)

            possible_list = [str(idx) for idx in range(r.count_crtcs) if all_possible & (1 << idx)]
            possible_str = f"[{','.join(possible_list)}]" if possible_list else "[]"

            phys = f"{c.mmWidth}x{c.mmHeight}mm" if (c.mmWidth or c.mmHeight) else "0x0mm"

            marker = "*" if c.connection == 1 else " "

            print(f"\n      {marker} [{conn_id}] {conn_name:<18}  "
                  f"drm_status={status_str:<14} encoder={enc_id}  crtc={crtc_id}  "
                  f"modes={c.count_modes}  physical={phys}")
            print(f"               possible_crtcs={possible_str}")

            libdrm.drmModeFreeConnector(conn_p)

        libdrm.drmModeFreeResources(res)
        os.close(fd)


# ---------------------------------------------------------------------------
# Section 3 — Sunshine log tail
# ---------------------------------------------------------------------------

def section_sunshine_log():
    hdr("3. Sunshine recent log  (last 40 relevant lines)")

    out, _ = run("journalctl --user -u sunshine -n 200 --no-pager 2>/dev/null")
    if not out:
        warn("Could not read Sunshine journal -- trying /tmp/virt_display.log only")
    else:
        keywords = ("resolution", "logical", "kms monitor", "found monitor",
                    "screencasting", "found interface", "missing wayland",
                    "client connected", "client disconnected", "executing",
                    "error", "warning", "fatal")
        lines = [l for l in out.splitlines()
                 if any(k in l.lower() for k in keywords)]
        for l in lines[-40:]:
            print(f"  {l}")

    vd_log = Path("/tmp/virt_display.log")
    if vd_log.exists():
        print(f"\n  virt_display.log (last 20 lines):")
        lines = vd_log.read_text().splitlines()
        for l in lines[-20:]:
            print(f"  {l}")


# ---------------------------------------------------------------------------
# Section 4 — State file + config
# ---------------------------------------------------------------------------

def section_config():
    hdr("4. Configuration snapshot")

    script_dir = Path(__file__).parent.parent

    state = script_dir / "virt_display.state"
    if state.exists():
        ok("virt_display.state exists:")
        for l in state.read_text().splitlines():
            info(l)
    else:
        warn("virt_display.state not present (no virtual display currently connected)")

    sunshine_conf = Path.home() / ".config/sunshine/sunshine.conf"
    if sunshine_conf.exists():
        print(f"\n  sunshine.conf:")
        for l in sunshine_conf.read_text().splitlines():
            info(l)


# ---------------------------------------------------------------------------
# Section 5 — System info
# ---------------------------------------------------------------------------

def section_system_info():
    hdr("5. System info")

    kernel, _ = run("uname -r")
    print(f"  Kernel: {kernel}")

    gpu_out, _ = run("lspci -nn 2>/dev/null | grep -iE 'vga|3d|display'")
    if gpu_out:
        for line in gpu_out.splitlines():
            print(f"  GPU: {line.strip()}")
    else:
        warn("Could not detect GPU via lspci")

    for mod in ("amdgpu", "nvidia", "i915", "xe", "nouveau"):
        ver, _ = run(f"modinfo {mod} 2>/dev/null | head -4")
        if ver:
            version_line = ""
            for l in ver.splitlines():
                if l.startswith("version:") or l.startswith("vermagic:"):
                    version_line = l.split(":", 1)[1].strip()
                    break
            if version_line:
                print(f"  {mod}: {version_line}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def snapshot():
    print(f"\nsunshine_virt_display debug snapshot  --  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Running as: {'root' if os.geteuid() == 0 else 'user (run with sudo for full KMS detail)'}")

    section_sysfs_connectors()
    section_kms_connectors()
    section_sunshine_log()
    section_config()
    section_system_info()
    print()
    print("<!-- Paste this entire output into a GitHub issue for debugging -->")


if __name__ == "__main__":
    snapshot()
