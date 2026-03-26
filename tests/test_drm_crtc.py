"""Tests for src/drm/crtc.py"""

import ctypes
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from src.drm.bindings import DrmModeModeInfo
from src.drm.crtc import (
    _check_crtc_active,
    force_crtc_assignment,
    release_crtc,
    wait_for_output_ready,
)


def _make_libdrm():
    lib = MagicMock()
    return lib


def _make_res(count_crtcs: int = 1) -> MagicMock:
    res_contents = MagicMock()
    res_contents.count_crtcs = count_crtcs
    res_contents.crtcs = [100]
    res_contents.count_connectors = 0
    res = MagicMock()
    res.contents = res_contents
    return res


class TestCheckCrtcActive:
    def test_returns_false_on_open_error(self):
        lib = _make_libdrm()
        with patch("os.open", side_effect=OSError("no device")):
            result = _check_crtc_active(lib, "/dev/dri/card1", "DisplayPort", 1)
        assert result is False

    def test_returns_false_when_resources_null(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = None
        with patch("os.open", return_value=5), patch("os.close"):
            result = _check_crtc_active(lib, "/dev/dri/card1", "DisplayPort", 1)
        assert result is False

    def test_returns_false_when_connector_not_found(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        with patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=None):
            result = _check_crtc_active(lib, "/dev/dri/card1", "DisplayPort", 1)
        assert result is False

    def test_returns_false_when_no_encoder(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        conn = MagicMock()
        conn.encoder_id = 0
        conn_p = MagicMock()
        conn_p.contents = conn
        with patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p):
            result = _check_crtc_active(lib, "/dev/dri/card1", "DisplayPort", 1)
        assert result is False

    def test_returns_false_when_encoder_pointer_null(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        lib.drmModeGetEncoder.return_value = None
        conn = MagicMock()
        conn.encoder_id = 5
        conn_p = MagicMock()
        conn_p.contents = conn
        with patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p):
            result = _check_crtc_active(lib, "/dev/dri/card1", "DisplayPort", 1)
        assert result is False

    def test_returns_false_when_crtc_id_zero(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        enc = MagicMock()
        enc.crtc_id = 0
        enc_p = MagicMock()
        enc_p.contents = enc
        lib.drmModeGetEncoder.return_value = enc_p
        conn = MagicMock()
        conn.encoder_id = 5
        conn_p = MagicMock()
        conn_p.contents = conn
        with patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p):
            result = _check_crtc_active(lib, "/dev/dri/card1", "DisplayPort", 1)
        assert result is False

    def test_returns_true_when_crtc_id_nonzero(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        enc = MagicMock()
        enc.crtc_id = 100
        enc_p = MagicMock()
        enc_p.contents = enc
        lib.drmModeGetEncoder.return_value = enc_p
        conn = MagicMock()
        conn.encoder_id = 5
        conn_p = MagicMock()
        conn_p.contents = conn
        with patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p):
            result = _check_crtc_active(lib, "/dev/dri/card1", "DisplayPort", 1)
        assert result is True


class TestWaitForOutputReady:
    def _sysfs_path(self, card: str, port: str) -> str:
        return f"/sys/class/drm/{card}-{port}"

    def test_returns_false_on_timeout(self):
        with patch("src.drm.crtc.load_libdrm", return_value=None), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.sleep"), \
             patch("pathlib.Path.read_text", return_value="disconnected"):
            ready, mode = wait_for_output_ready("card1", "DP-1", 1920, 1080, timeout=0.01)
        assert ready is False
        assert mode == ""

    def test_returns_true_when_connected_and_crtc_active(self):
        lib = _make_libdrm()
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("src.drm.crtc._check_crtc_active", return_value=True), \
             patch("time.sleep"), \
             patch("pathlib.Path.read_text", return_value="connected"), \
             patch("pathlib.Path.exists", return_value=True):
            ready, mode = wait_for_output_ready("card1", "DP-1", 1920, 1080, timeout=1.0)
        assert ready is True

    def test_skips_crtc_check_when_no_libdrm(self):
        with patch("src.drm.crtc.load_libdrm", return_value=None), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.sleep"), \
             patch("pathlib.Path.read_text", return_value="connected"):
            # libdrm is None → no CRTC check → never returns True → timeout
            ready, _ = wait_for_output_ready("card1", "DP-1", 1920, 1080, timeout=0.01)
        assert ready is False

    def test_handles_oserror_in_read(self):
        with patch("src.drm.crtc.load_libdrm", return_value=None), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.sleep"), \
             patch("pathlib.Path.read_text", side_effect=OSError("perm")):
            ready, _ = wait_for_output_ready("card1", "DP-1", 1920, 1080, timeout=0.01)
        assert ready is False

    def test_mode_string_extracted_from_sysfs(self):
        lib = _make_libdrm()
        read_calls = [0]

        def read_text():
            read_calls[0] += 1
            if read_calls[0] == 1:
                return "connected"
            return "1920x1080\n1280x720\n"

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("src.drm.crtc._check_crtc_active", return_value=True), \
             patch("time.sleep"), \
             patch("pathlib.Path.read_text", side_effect=read_text), \
             patch("pathlib.Path.exists", return_value=True):
            ready, mode = wait_for_output_ready("card1", "DP-1", 1920, 1080, timeout=1.0)
        assert ready is True
        assert mode == "1920x1080"


class TestReleaseCrtc:
    def test_returns_false_when_no_libdrm(self, capsys):
        with patch("src.drm.crtc.load_libdrm", return_value=None):
            result = release_crtc("card1", "DP-1")
        assert result is False

    def test_returns_false_when_port_parse_fails(self, capsys):
        lib = _make_libdrm()
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=(None, None)):
            result = release_crtc("card1", "DP-1")
        assert result is False

    def test_returns_false_when_open_fails(self, capsys):
        lib = _make_libdrm()
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", side_effect=OSError("no device")):
            result = release_crtc("card1", "DP-1")
        assert result is False

    def test_returns_false_when_resources_null(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = None
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", return_value=5), patch("os.close"):
            result = release_crtc("card1", "DP-1")
        assert result is False

    def test_returns_false_when_connector_not_found(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=None):
            result = release_crtc("card1", "DP-1")
        assert result is False

    def test_returns_true_when_no_encoder(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        conn = MagicMock()
        conn.encoder_id = 0
        conn_p = MagicMock()
        conn_p.contents = conn
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p):
            result = release_crtc("card1", "DP-1")
        assert result is True

    def test_returns_false_when_encoder_pointer_null(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        lib.drmModeGetEncoder.return_value = None
        conn = MagicMock()
        conn.encoder_id = 5
        conn_p = MagicMock()
        conn_p.contents = conn
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p):
            result = release_crtc("card1", "DP-1")
        assert result is False

    def test_returns_true_when_no_crtc_on_encoder(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        enc = MagicMock()
        enc.crtc_id = 0
        enc_p = MagicMock()
        enc_p.contents = enc
        lib.drmModeGetEncoder.return_value = enc_p
        conn = MagicMock()
        conn.encoder_id = 5
        conn_p = MagicMock()
        conn_p.contents = conn
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p):
            result = release_crtc("card1", "DP-1")
        assert result is True

    def test_releases_crtc_successfully(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        enc = MagicMock()
        enc.crtc_id = 100
        enc_p = MagicMock()
        enc_p.contents = enc
        lib.drmModeGetEncoder.return_value = enc_p
        conn = MagicMock()
        conn.encoder_id = 5
        conn_p = MagicMock()
        conn_p.contents = conn
        lib.drmModeSetCrtc.return_value = 0

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p), \
             patch("src.drm.crtc.with_drm_master", lambda path, cb: cb(5)):
            result = release_crtc("card1", "DP-1")
        assert result is True

    def test_release_fails_when_set_crtc_returns_nonzero(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        enc = MagicMock()
        enc.crtc_id = 100
        enc_p = MagicMock()
        enc_p.contents = enc
        lib.drmModeGetEncoder.return_value = enc_p
        conn = MagicMock()
        conn.encoder_id = 5
        conn_p = MagicMock()
        conn_p.contents = conn
        lib.drmModeSetCrtc.return_value = -1

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p), \
             patch("src.drm.crtc.with_drm_master", lambda path, cb: cb(5)), \
             patch("ctypes.get_errno", return_value=1):
            result = release_crtc("card1", "DP-1")
        assert result is False

    def test_returns_false_on_drm_master_exception(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        enc = MagicMock()
        enc.crtc_id = 100
        enc_p = MagicMock()
        enc_p.contents = enc
        lib.drmModeGetEncoder.return_value = enc_p
        conn = MagicMock()
        conn.encoder_id = 5
        conn_p = MagicMock()
        conn_p.contents = conn

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.find_connector", return_value=conn_p), \
             patch("src.drm.crtc.with_drm_master", side_effect=RuntimeError("no master")):
            result = release_crtc("card1", "DP-1")
        assert result is False


class TestForceCrtcAssignment:
    def _make_probe_tuple(self) -> tuple:
        mode = DrmModeModeInfo()
        mode.hdisplay = 1920
        mode.vdisplay = 1080
        return (100, 1, mode)

    def test_returns_false_when_no_libdrm(self):
        with patch("src.drm.crtc.load_libdrm", return_value=None):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False

    def test_returns_false_when_port_parse_fails(self):
        lib = _make_libdrm()
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=(None, None)):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False

    def test_returns_false_when_open_fails(self):
        lib = _make_libdrm()
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 0.0, 10.0]), \
             patch("os.open", side_effect=OSError("no device")):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False

    def test_returns_false_when_resources_null(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = None
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 0.0, 10.0]), \
             patch("os.open", return_value=5), patch("os.close"):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False

    def test_returns_false_when_probe_returns_none(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 10.0]), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.probe_connector", return_value=None):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False

    def test_returns_true_when_already_has_crtc(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 10.0]), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.probe_connector", return_value=True):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is True

    def test_retries_until_probe_succeeds(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        probe_results = [None, None, True]
        probe_iter = iter(probe_results)

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 0.1, 0.2, 10.0]), \
             patch("time.sleep"), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.probe_connector", side_effect=probe_results):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is True

    def test_sets_crtc_successfully(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        lib.drmModeSetCrtc.return_value = 0

        mode = DrmModeModeInfo()
        mode.hdisplay = 1920
        mode.vdisplay = 1080

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 10.0]), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.probe_connector", return_value=(100, 1, mode)), \
             patch("src.drm.crtc.with_drm_master", lambda path, cb: cb(5)), \
             patch("fcntl.ioctl", return_value=0):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is True

    def test_returns_false_when_create_dumb_fails(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()

        mode = DrmModeModeInfo()
        mode.hdisplay = 1920
        mode.vdisplay = 1080

        import fcntl as fcntl_mod

        def ioctl_side(fd, req, struct):
            from src.drm.bindings import DRM_IOCTL_MODE_CREATE_DUMB
            if req == DRM_IOCTL_MODE_CREATE_DUMB:
                raise OSError("failed")
            return 0

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 10.0]), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.probe_connector", return_value=(100, 1, mode)), \
             patch("src.drm.crtc.with_drm_master", lambda path, cb: cb(5)), \
             patch("fcntl.ioctl", side_effect=ioctl_side):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False

    def test_returns_false_when_addfb_fails(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()

        mode = DrmModeModeInfo()
        mode.hdisplay = 1920
        mode.vdisplay = 1080

        from src.drm.bindings import DRM_IOCTL_MODE_ADDFB, DRM_IOCTL_MODE_CREATE_DUMB

        def ioctl_side(fd, req, struct):
            if req == DRM_IOCTL_MODE_CREATE_DUMB:
                return 0
            if req == DRM_IOCTL_MODE_ADDFB:
                raise OSError("addfb failed")
            return 0

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 10.0]), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.probe_connector", return_value=(100, 1, mode)), \
             patch("src.drm.crtc.with_drm_master", lambda path, cb: cb(5)), \
             patch("fcntl.ioctl", side_effect=ioctl_side):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False

    def test_returns_false_when_set_crtc_fails(self, capsys):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()
        lib.drmModeSetCrtc.return_value = -1

        mode = DrmModeModeInfo()
        mode.hdisplay = 1920
        mode.vdisplay = 1080

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 10.0]), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.probe_connector", return_value=(100, 1, mode)), \
             patch("src.drm.crtc.with_drm_master", lambda path, cb: cb(5)), \
             patch("fcntl.ioctl", return_value=0), \
             patch("ctypes.get_errno", return_value=1):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False

    def test_returns_false_on_drm_master_exception(self):
        lib = _make_libdrm()
        lib.drmModeGetResources.return_value = _make_res()

        mode = DrmModeModeInfo()
        mode.hdisplay = 1920
        mode.vdisplay = 1080

        with patch("src.drm.crtc.load_libdrm", return_value=lib), \
             patch("src.drm.crtc.sysfs_port_to_drm_name", return_value=("DisplayPort", 1)), \
             patch("time.monotonic", side_effect=[0.0, 10.0]), \
             patch("os.open", return_value=5), patch("os.close"), \
             patch("src.drm.crtc.probe_connector", return_value=(100, 1, mode)), \
             patch("src.drm.crtc.with_drm_master", side_effect=RuntimeError("no master")):
            result = force_crtc_assignment("card1", "DP-1")
        assert result is False
