"""
CRTC assignment and release operations.

Provides high-level functions to force CRTC assignment onto connectors
and release CRTCs, working around compositors that don't handle hotplug.
"""

import ctypes
import fcntl
import os
import time
from pathlib import Path

from src.drm.bindings import (
    DRM_IOCTL_MODE_ADDFB,
    DRM_IOCTL_MODE_CREATE_DUMB,
    DRM_IOCTL_MODE_DESTROY_DUMB,
    DRM_IOCTL_MODE_RMFB,
    _DrmModeFbCmd,
    _DrmModeCreateDumb,
    _DrmModeDestroyDumb,
    _DrmModeModeInfo,
    _find_connector,
    _find_free_crtc,
    _load_libdrm,
    _probe_connector,
    _sysfs_port_to_drm_name,
)
from src.drm.drm_master import _with_drm_master


def _check_crtc_active(libdrm, card_path, drm_type, type_id):
    """
    Return True if the connector has an active CRTC via the encoder chain.
    This is the ground-truth check that the compositor has finished modesetting.
    """
    try:
        fd = os.open(card_path, os.O_RDWR | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        res = libdrm.drmModeGetResources(fd)
        if not res:
            return False
        try:
            conn_p = _find_connector(libdrm, fd, res, drm_type, type_id)
            if not conn_p:
                return False
            try:
                conn = conn_p.contents
                if not conn.encoder_id:
                    return False
                enc_p = libdrm.drmModeGetEncoder(fd, conn.encoder_id)
                if not enc_p:
                    return False
                crtc_id = enc_p.contents.crtc_id
                libdrm.drmModeFreeEncoder(enc_p)
                return crtc_id != 0
            finally:
                libdrm.drmModeFreeConnector(conn_p)
        finally:
            libdrm.drmModeFreeResources(res)
    finally:
        os.close(fd)


def wait_for_output_ready(card_name, port, width, height, timeout=10.0):
    """
    Poll until the DRM connector is sysfs-connected AND has an active CRTC
    assigned by the compositor (verified via libdrm encoder chain).
    Returns (ready, mode_string).
    """
    sysfs_base = Path(f"/sys/class/drm/{card_name}-{port}")
    drm_type, type_id = _sysfs_port_to_drm_name(port)
    card_path = f"/dev/dri/{card_name}"
    libdrm = _load_libdrm()
    poll_interval = 0.2
    max_polls = int(timeout / poll_interval)

    for _ in range(max_polls):
        try:
            status = (sysfs_base / "status").read_text().strip()
            if status == "connected":
                if libdrm and drm_type and _check_crtc_active(libdrm, card_path, drm_type, type_id):
                    modes_file = sysfs_base / "modes"
                    mode = modes_file.read_text().strip().split("\n")[0] if modes_file.exists() else ""
                    # Short grace period for compositor to finish rendering setup
                    time.sleep(0.3)
                    return True, mode
        except (OSError, IOError):
            pass

        time.sleep(poll_interval)

    return False, ""


def release_crtc(card_name, port):
    """
    Release the CRTC from a connector by disabling its display pipeline.
    This is needed on disconnect so the CRTC becomes available for other connectors.
    Returns True if CRTC was released (or wasn't assigned).
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
            conn_p = _find_connector(libdrm, probe_fd, res, drm_type, type_id)
            if not conn_p:
                print(f"    Connector {drm_type}-{type_id} not found")
                return False

            try:
                conn = conn_p.contents
                if not conn.encoder_id:
                    print(f"    Connector {port} has no encoder, nothing to release")
                    return True

                enc_p = libdrm.drmModeGetEncoder(probe_fd, conn.encoder_id)
                if not enc_p:
                    print(f"    Could not get encoder {conn.encoder_id}")
                    return False

                crtc_id = enc_p.contents.crtc_id
                libdrm.drmModeFreeEncoder(enc_p)

                if not crtc_id:
                    print(f"    Connector {port} has no CRTC, nothing to release")
                    return True
            finally:
                libdrm.drmModeFreeConnector(conn_p)
        finally:
            libdrm.drmModeFreeResources(res)
    finally:
        os.close(probe_fd)

    print(f"    Releasing CRTC {crtc_id} from {port}")

    def do_release(master_fd):
        ret = libdrm.drmModeSetCrtc(
            master_fd,
            crtc_id,
            0,       # fb_id = 0 (no framebuffer)
            0, 0,    # x, y
            None,    # no connectors
            0,       # connector count = 0
            None,    # no mode
        )
        if ret == 0:
            print(f"    CRTC {crtc_id} released successfully")
            return True
        else:
            errno_val = ctypes.get_errno()
            print(f"    drmModeSetCrtc(release) failed (ret={ret}, errno={errno_val}: "
                  f"{os.strerror(errno_val) if errno_val else 'unknown'})")
            return False

    try:
        return _with_drm_master(card_path, do_release)
    except Exception as e:
        print(f"    Failed to release CRTC: {e}")
        return False


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

    # Probe connector state, retrying until the connector becomes DRM-connected.
    # After sysfs hotplug (`echo on > status`) there is a window where the kernel
    # has marked the connector connected in sysfs but the DRM subsystem has not
    # yet updated conn.connection — typically resolves within a few hundred ms.
    probe_deadline = time.monotonic() + 5.0
    probe_interval = 0.3
    result = None
    while True:
        is_last = time.monotonic() >= probe_deadline
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
                result = _probe_connector(
                    libdrm, probe_fd, res, drm_type, type_id, port,
                    silent=not is_last,
                )
            finally:
                libdrm.drmModeFreeResources(res)
        finally:
            os.close(probe_fd)

        if result is not None or is_last:
            break
        time.sleep(probe_interval)

    if result is None:
        return False  # error already printed on last attempt
    if result is True:
        return True  # already has CRTC

    # result is (crtc_id, connector_id, mode) — need to do the SetCrtc
    crtc_id, connector_id, mode_copy = result

    print(f"    Assigning CRTC {crtc_id} to {port} ({mode_copy.hdisplay}x{mode_copy.vdisplay})")

    def do_set_crtc(master_fd):
        # Create a dumb framebuffer — amdgpu requires a real fb_id
        create = _DrmModeCreateDumb()
        create.width = mode_copy.hdisplay
        create.height = mode_copy.vdisplay
        create.bpp = 32
        create.flags = 0

        print(f"    Creating dumb buffer: {create.width}x{create.height} bpp=32")
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
            destroy = _DrmModeDestroyDumb()
            destroy.handle = create.handle
            try:
                fcntl.ioctl(master_fd, DRM_IOCTL_MODE_DESTROY_DUMB, destroy)
            except OSError:
                pass
            return False
        print(f"    Framebuffer added: fb_id={fb.fb_id}")

        # Set CRTC with the real framebuffer
        conn_ids = (ctypes.c_uint32 * 1)(connector_id)
        print(f"    Calling drmModeSetCrtc(crtc={crtc_id}, fb={fb.fb_id}, "
              f"conn={connector_id}, mode={mode_copy.hdisplay}x{mode_copy.vdisplay})")
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
            errno_val = ctypes.get_errno()
            print(f"    drmModeSetCrtc failed (ret={ret}, errno={errno_val}: "
                  f"{os.strerror(errno_val) if errno_val else 'unknown'})")
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
