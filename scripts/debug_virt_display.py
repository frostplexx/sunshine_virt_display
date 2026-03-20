#!/usr/bin/env python3
"""
debug_virt_display.py - Snapshot the full display/capture state relevant to
sunshine_virt_display, with emphasis on what Sunshine's KMS monitor list sees.

Run as root (sudo python3 debug_virt_display.py) for full DRM access.
Run without sudo for the Wayland-side view only.

Usage:
    sudo python3 debug_virt_display.py            # full snapshot
    sudo python3 debug_virt_display.py --watch     # re-print every 2s (useful while connecting)
"""

import argparse
import ctypes
import ctypes.util
import os
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"

def hdr(title):
    width = 72
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def err(msg):  print(f"  {RED}✗{RESET}  {msg}")
def info(msg): print(f"     {msg}")

def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return "", str(e)


# ---------------------------------------------------------------------------
# Section 1 – sysfs connector status
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

        status  = status_f.read_text().strip()
        enabled = enabled_f.read_text().strip() if enabled_f.exists() else "?"

        color = GREEN if status == "connected" else ""
        print(f"  {color}{entry.name:<30}{RESET}  status={status:<14} enabled={enabled}")


# ---------------------------------------------------------------------------
# Section 2 – libdrm connector + CRTC + plane view  (mirrors Sunshine's KMS scan)
# ---------------------------------------------------------------------------

# Minimal libdrm bindings via ctypes
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
        ("connector_id",   ctypes.c_uint32),
        ("encoder_id",     ctypes.c_uint32),
        ("connector_type", ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection",     ctypes.c_uint32),   # 1=connected 2=disconnected 3=unknown
        ("mmWidth",        ctypes.c_uint32),
        ("mmHeight",       ctypes.c_uint32),
        ("subpixel",       ctypes.c_uint32),
        ("count_modes",    ctypes.c_int),
        ("modes",          ctypes.c_void_p),
        ("count_props",    ctypes.c_int),
        ("props",          ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values",    ctypes.POINTER(ctypes.c_uint64)),
        ("count_encoders", ctypes.c_int),
        ("encoders",       ctypes.POINTER(ctypes.c_uint32)),
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
        ("crtc_id",      ctypes.c_uint32),
        ("buffer_id",    ctypes.c_uint32),
        ("x",            ctypes.c_uint32),
        ("y",            ctypes.c_uint32),
        ("width",        ctypes.c_uint32),
        ("height",       ctypes.c_uint32),
        ("mode_valid",   ctypes.c_int),
        # mode_info is 292 bytes – we don't need to parse it, just pad
        ("_mode_info",   ctypes.c_uint8 * 292),
        ("gamma_size",   ctypes.c_int),
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
        lib.drmOpen.restype = ctypes.c_int
        lib.drmClose.restype = ctypes.c_int
        lib.drmModeGetResources.restype = ctypes.POINTER(_DrmModeRes)
        lib.drmModeFreeResources.restype = None
        lib.drmModeGetConnector.restype = ctypes.POINTER(_DrmModeConnector)
        lib.drmModeFreeConnector.restype = None
        lib.drmModeGetEncoder.restype = ctypes.POINTER(_DrmModeEncoder)
        lib.drmModeFreeEncoder.restype = None
        lib.drmModeGetCrtc.restype = ctypes.POINTER(_DrmModeCrtc)
        lib.drmModeFreeCrtc.restype = None
        lib.drmGetVersion.restype = ctypes.c_void_p
        return lib
    except Exception:
        return None


def section_kms_connectors():
    hdr("2. KMS connector/encoder/CRTC state  (libdrm)")

    libdrm = _load_libdrm()
    if not libdrm:
        warn("libdrm not found – skipping KMS section")
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
        print(f"\n  {BOLD}{card_path}{RESET}")

        try:
            fd = os.open(str(card_path), os.O_RDWR | os.O_CLOEXEC)
        except PermissionError:
            warn(f"    Permission denied – run as root for full KMS view")
            continue
        except Exception as e:
            err(f"    Could not open: {e}")
            continue

        # Driver name
        out, _ = run(f"cat /sys/class/drm/{card_path.name}/device/uevent 2>/dev/null | grep DRIVER")
        driver = out.split("=")[-1] if "=" in out else "?"
        print(f"    driver: {driver}")

        res = libdrm.drmModeGetResources(fd)
        if not res:
            warn("    drmModeGetResources returned NULL (no KMS support or no permission)")
            os.close(fd)
            continue

        r = res.contents

        # CRTCs
        print(f"\n    CRTCs ({r.count_crtcs}):")
        crtc_ids = set()
        for i in range(r.count_crtcs):
            cid = r.crtcs[i]
            crtc_ids.add(cid)
            crtc_p = libdrm.drmModeGetCrtc(fd, cid)
            if crtc_p:
                c = crtc_p.contents
                active = c.buffer_id != 0
                status_str = f"{GREEN}ACTIVE  fb={c.buffer_id} {c.width}x{c.height}{RESET}" if active else f"{YELLOW}inactive fb=0{RESET}"
                print(f"      CRTC {cid}: {status_str}")
                libdrm.drmModeFreeCrtc(crtc_p)
            else:
                print(f"      CRTC {cid}: (could not query)")

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

            # Encoder → CRTC chain
            crtc_id = 0
            enc_id = c.encoder_id
            if enc_id:
                enc_p = libdrm.drmModeGetEncoder(fd, enc_id)
                if enc_p:
                    crtc_id = enc_p.contents.crtc_id
                    libdrm.drmModeFreeEncoder(enc_p)

            phys = f"{c.mmWidth}x{c.mmHeight}mm" if (c.mmWidth or c.mmHeight) else "0x0mm"


            print(f"\n      [{conn_id}] {BOLD}{conn_name:<18}{RESET}  "
                  f"drm_status={status_str:<14} encoder={enc_id}  crtc={crtc_id}  "
                  f"modes={c.count_modes}  physical={phys}")

            libdrm.drmModeFreeConnector(conn_p)

        libdrm.drmModeFreeResources(res)
        os.close(fd)


# ---------------------------------------------------------------------------
# Section 4 – Sunshine log tail
# ---------------------------------------------------------------------------

def section_sunshine_log():
    hdr("4. Sunshine recent log  (last 40 relevant lines)")

    out, _ = run("journalctl --user -u sunshine -n 200 --no-pager 2>/dev/null")
    if not out:
        warn("Could not read Sunshine journal – trying /tmp/virt_display.log only")
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
        print(f"\n  {BOLD}virt_display.log (last 20 lines):{RESET}")
        lines = vd_log.read_text().splitlines()
        for l in lines[-20:]:
            print(f"  {l}")


# ---------------------------------------------------------------------------
# Section 5 – State file + config
# ---------------------------------------------------------------------------

def section_config():
    hdr("5. Configuration snapshot")

    script_dir = Path(__file__).parent.parent

    state = script_dir / "virt_display.state"
    if state.exists():
        ok(f"virt_display.state exists:")
        for l in state.read_text().splitlines():
            info(l)
    else:
        warn("virt_display.state not present (no virtual display currently connected)")

    sunshine_conf = Path.home() / ".config/sunshine/sunshine.conf"
    if sunshine_conf.exists():
        print(f"\n  {BOLD}sunshine.conf:{RESET}")
        for l in sunshine_conf.read_text().splitlines():
            info(l)

    kwin_conf = Path.home() / ".config/kwinoutputconfig.json"
    if kwin_conf.exists():
        import json
        try:
            data = json.loads(kwin_conf.read_text())
            outputs_section = next((s for s in data if s.get("name") == "outputs"), None)
            if outputs_section:
                print(f"\n  {BOLD}kwinoutputconfig.json — saved display scales:{RESET}")
                for entry in outputs_section.get("data", []):
                    conn  = entry.get("connectorName", "?")
                    scale = entry.get("scale", "?")
                    mode  = entry.get("mode", {})
                    res   = f"{mode.get('width','?')}x{mode.get('height','?')}"
                    eid   = entry.get("edidHash", "")[:8]
                    color = GREEN if float(scale) == 1.0 else RED
                    print(f"    {conn}  {res}  {color}scale={scale}{RESET}  edid={eid}…")
        except Exception as e:
            warn(f"Could not parse kwinoutputconfig.json: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def snapshot():
    print(f"\n{BOLD}sunshine_virt_display debug snapshot{RESET}  —  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Running as: {'root' if os.geteuid() == 0 else 'user (run with sudo for full KMS detail)'}")

    section_sysfs_connectors()
    section_kms_connectors()
    section_sunshine_log()
    section_config()
    print()


def main():
    parser = argparse.ArgumentParser(description="Debug sunshine_virt_display display/KMS state")
    parser.add_argument("--watch", action="store_true",
                        help="Repeat snapshot every 2 seconds (useful while connecting a client)")
    args = parser.parse_args()

    if args.watch:
        try:
            while True:
                os.system("clear")
                snapshot()
                print(f"  {YELLOW}[ --watch mode: refreshing every 2s, Ctrl-C to stop ]{RESET}\n")
                time.sleep(2)
        except KeyboardInterrupt:
            pass
    else:
        snapshot()


if __name__ == "__main__":
    main()
