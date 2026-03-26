"""Tests for src/drm/bindings.py"""

import ctypes
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.drm.bindings import (
    DRM_DISPLAY_MODE_LEN,
    DRM_IOCTL_DROP_MASTER,
    DRM_IOCTL_MODE_ADDFB,
    DRM_IOCTL_MODE_CREATE_DUMB,
    DRM_IOCTL_MODE_DESTROY_DUMB,
    DRM_IOCTL_MODE_RMFB,
    DRM_IOCTL_SET_MASTER,
    DrmModeCreateDumb,
    DrmModeFbCmd,
    DrmModeDestroyDumb,
    DrmModeModeInfo,
    _find_free_crtc,
    find_connector,
    load_libdrm,
    probe_connector,
    sysfs_port_to_drm_name,
)


class TestConstants:
    def test_display_mode_len(self):
        assert DRM_DISPLAY_MODE_LEN == 32

    def test_set_master(self):
        assert DRM_IOCTL_SET_MASTER == 0x0000641E

    def test_drop_master(self):
        assert DRM_IOCTL_DROP_MASTER == 0x0000641F

    def test_create_dumb(self):
        assert DRM_IOCTL_MODE_CREATE_DUMB == 0xC02064B2

    def test_addfb(self):
        assert DRM_IOCTL_MODE_ADDFB == 0xC01C64AE

    def test_rmfb(self):
        assert DRM_IOCTL_MODE_RMFB == 0xC00464AF

    def test_destroy_dumb(self):
        assert DRM_IOCTL_MODE_DESTROY_DUMB == 0xC00464B4


class TestStructs:
    def test_drm_mode_mode_info_fields(self):
        m = DrmModeModeInfo()
        m.clock = 148500
        m.hdisplay = 1920
        m.vdisplay = 1080
        m.vrefresh = 60
        assert m.clock == 148500
        assert m.hdisplay == 1920
        assert m.vdisplay == 1080
        assert m.vrefresh == 60

    def test_drm_mode_create_dumb_fields(self):
        d = DrmModeCreateDumb()
        d.width = 1920
        d.height = 1080
        d.bpp = 32
        d.flags = 0
        assert d.width == 1920
        assert d.height == 1080
        assert d.bpp == 32

    def test_drm_mode_fb_cmd_fields(self):
        fb = DrmModeFbCmd()
        fb.width = 1920
        fb.height = 1080
        fb.pitch = 7680
        fb.bpp = 32
        fb.depth = 24
        assert fb.width == 1920
        assert fb.bpp == 32

    def test_drm_mode_destroy_dumb_fields(self):
        d = DrmModeDestroyDumb()
        d.handle = 42
        assert d.handle == 42

    def test_mode_info_name_field(self):
        m = DrmModeModeInfo()
        m.name = b"1920x1080"
        assert b"1920x1080" in m.name


class TestSysfsPortToDrmName:
    def test_dp1(self):
        drm_type, type_id = sysfs_port_to_drm_name("DP-1")
        assert drm_type == "DisplayPort"
        assert type_id == 1

    def test_dp2(self):
        drm_type, type_id = sysfs_port_to_drm_name("DP-2")
        assert drm_type == "DisplayPort"
        assert type_id == 2

    def test_hdmi_a_1(self):
        drm_type, type_id = sysfs_port_to_drm_name("HDMI-A-1")
        assert drm_type == "HDMIA"
        assert type_id == 1

    def test_hdmi_no_suffix_A(self):
        drm_type, type_id = sysfs_port_to_drm_name("HDMI-1")
        assert drm_type == "HDMIA"
        assert type_id == 1

    def test_unknown_port(self):
        drm_type, type_id = sysfs_port_to_drm_name("VGA-1")
        assert drm_type is None
        assert type_id is None

    def test_malformed_suffix(self):
        # prefix matches but suffix is not an int
        drm_type, type_id = sysfs_port_to_drm_name("DP-abc")
        assert drm_type is None
        assert type_id is None

    def test_empty_string(self):
        drm_type, type_id = sysfs_port_to_drm_name("")
        assert drm_type is None
        assert type_id is None


class TestLoadLibdrm:
    def test_returns_none_when_library_not_found(self):
        with patch("ctypes.util.find_library", return_value=None):
            result = load_libdrm()
        assert result is None

    def test_returns_none_on_cdll_exception(self):
        with patch("ctypes.util.find_library", return_value="libdrm.so"):
            with patch("ctypes.CDLL", side_effect=OSError("not found")):
                result = load_libdrm()
        assert result is None

    def test_returns_libdrm_when_found(self):
        mock_lib = MagicMock()
        with patch("ctypes.util.find_library", return_value="libdrm.so"):
            with patch("ctypes.CDLL", return_value=mock_lib):
                result = load_libdrm()
        assert result is not None


def _make_mock_libdrm():
    """Build a minimal mock LibDRM object."""
    lib = MagicMock()
    return lib


def _make_res(connector_ids: list[int], crtc_ids: list[int]) -> MagicMock:
    res_contents = MagicMock()
    res_contents.count_connectors = len(connector_ids)
    res_contents.connectors = connector_ids
    res_contents.count_crtcs = len(crtc_ids)
    res_contents.crtcs = crtc_ids
    res = MagicMock()
    res.contents = res_contents
    return res


def _make_connector(
    connector_id: int,
    connector_type: int,
    connector_type_id: int,
    connection: int = 1,
    encoder_id: int = 0,
    count_modes: int = 1,
    count_encoders: int = 1,
    encoder_ids: list[int] | None = None,
) -> MagicMock:
    mode = DrmModeModeInfo()
    mode.hdisplay = 1920
    mode.vdisplay = 1080
    mode.vrefresh = 60

    modes_array = (DrmModeModeInfo * 1)(mode)

    conn = MagicMock()
    conn.connector_id = connector_id
    conn.connector_type = connector_type
    conn.connector_type_id = connector_type_id
    conn.connection = connection
    conn.encoder_id = encoder_id
    conn.count_modes = count_modes
    conn.modes = modes_array
    conn.count_encoders = count_encoders
    conn.encoders = encoder_ids or [0]

    conn_p = MagicMock()
    conn_p.contents = conn
    return conn_p


class TestFindConnector:
    def test_finds_matching_connector(self):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        conn_p = _make_connector(1, 10, 1)  # type 10 = DisplayPort
        lib.drmModeGetConnector.return_value = conn_p

        # type 10 maps to "DisplayPort" in _CONNECTOR_TYPE_NAMES
        result = find_connector(lib, 5, res, "DisplayPort", 1)
        assert result is conn_p

    def test_returns_none_when_not_found(self):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        conn_p = _make_connector(1, 10, 2)  # type_id=2, not 1
        lib.drmModeGetConnector.return_value = conn_p

        result = find_connector(lib, 5, res, "DisplayPort", 1)
        assert result is None

    def test_skips_null_connector_pointer(self):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        lib.drmModeGetConnector.return_value = None

        result = find_connector(lib, 5, res, "DisplayPort", 1)
        assert result is None

    def test_frees_non_matching_connector(self):
        lib = _make_mock_libdrm()
        res = _make_res([1, 2], [])
        # First connector: type_id=2 (no match), second: null
        conn_p1 = _make_connector(1, 10, 2)
        lib.drmModeGetConnector.side_effect = [conn_p1, None]

        find_connector(lib, 5, res, "DisplayPort", 1)
        lib.drmModeFreeConnector.assert_called_once_with(conn_p1)


class TestFindFreeCrtc:
    def _make_encoder(self, possible_crtcs: int, crtc_id: int = 0) -> MagicMock:
        enc = MagicMock()
        enc.possible_crtcs = possible_crtcs
        enc.crtc_id = crtc_id
        enc_p = MagicMock()
        enc_p.contents = enc
        return enc_p

    def test_returns_free_crtc(self):
        lib = _make_mock_libdrm()
        res = _make_res([1], [100])
        # connector has one encoder that can drive CRTC index 0
        conn_p = _make_connector(1, 10, 1, encoder_ids=[10])
        enc_p = self._make_encoder(possible_crtcs=0b1, crtc_id=0)

        # No other connectors
        lib.drmModeGetConnector.return_value = MagicMock(
            contents=MagicMock(connector_id=999, encoder_id=0)
        )
        lib.drmModeGetEncoder.return_value = enc_p

        result = _find_free_crtc(lib, 5, res, conn_p)
        assert result == 100  # crtc_id from res.crtcs[0]

    def test_returns_zero_when_no_crtc(self):
        lib = _make_mock_libdrm()
        res = _make_res([1], [100])
        conn_p = _make_connector(1, 10, 1, count_encoders=0, encoder_ids=[])
        conn_p.contents.count_encoders = 0

        lib.drmModeGetConnector.return_value = MagicMock(
            contents=MagicMock(connector_id=999, encoder_id=0)
        )

        result = _find_free_crtc(lib, 5, res, conn_p)
        assert result == 0

    def test_falls_back_to_used_crtc(self):
        lib = _make_mock_libdrm()
        res = _make_res([1, 2], [100])

        main_conn = MagicMock()
        main_conn.connector_id = 1
        main_conn.count_encoders = 1
        main_conn.encoders = [10]
        conn_p = MagicMock()
        conn_p.contents = main_conn

        # other connector is using crtc 100
        other_conn = MagicMock()
        other_conn.connector_id = 2
        other_conn.encoder_id = 20
        other_conn_p = MagicMock()
        other_conn_p.contents = other_conn

        other_enc = MagicMock()
        other_enc.crtc_id = 100
        other_enc_p = MagicMock()
        other_enc_p.contents = other_enc

        enc_p = self._make_encoder(possible_crtcs=0b1, crtc_id=0)

        def get_connector(fd, conn_id):
            if conn_id == 1:
                return conn_p
            return other_conn_p

        def get_encoder(fd, enc_id):
            if enc_id == 20:
                return other_enc_p
            return enc_p

        lib.drmModeGetConnector.side_effect = get_connector
        lib.drmModeGetEncoder.side_effect = get_encoder

        result = _find_free_crtc(lib, 5, res, conn_p)
        # fallback: returns crtc_id=100 anyway
        assert result == 100


class TestProbeConnector:
    def test_returns_none_when_connector_not_found(self, capsys):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        lib.drmModeGetConnector.return_value = None

        result = probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1")
        assert result is None
        assert "not found" in capsys.readouterr().out

    def test_returns_none_when_not_connected(self, capsys):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        conn_p = _make_connector(1, 10, 1, connection=2)  # disconnected
        lib.drmModeGetConnector.return_value = conn_p

        result = probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1")
        assert result is None

    def test_silent_suppresses_not_connected_message(self, capsys):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        conn_p = _make_connector(1, 10, 1, connection=2)
        lib.drmModeGetConnector.return_value = conn_p

        probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1", silent=True)
        assert capsys.readouterr().out == ""

    def test_returns_true_when_crtc_already_assigned(self, capsys):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        conn_p = _make_connector(1, 10, 1, connection=1, encoder_id=5)

        enc = MagicMock()
        enc.crtc_id = 100
        enc_p = MagicMock()
        enc_p.contents = enc
        lib.drmModeGetConnector.return_value = conn_p
        lib.drmModeGetEncoder.return_value = enc_p

        result = probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1")
        assert result is True

    def test_returns_none_when_no_modes(self, capsys):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        conn_p = _make_connector(1, 10, 1, connection=1, encoder_id=0, count_modes=0)
        lib.drmModeGetConnector.return_value = conn_p

        result = probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1")
        assert result is None
        assert "no modes" in capsys.readouterr().out

    def test_returns_none_when_no_crtc_available(self, capsys):
        lib = _make_mock_libdrm()
        res = _make_res([1], [])
        conn_p = _make_connector(1, 10, 1, connection=1, encoder_id=0, count_modes=1, count_encoders=0)
        conn_p.contents.count_encoders = 0
        lib.drmModeGetConnector.return_value = conn_p

        # _find_free_crtc will scan other connectors — return None
        lib.drmModeGetConnector.side_effect = [conn_p, None]

        result = probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1")
        assert result is None

    def test_returns_tuple_when_crtc_needed(self):
        lib = _make_mock_libdrm()
        res = _make_res([1], [100])
        conn_p = _make_connector(1, 10, 1, connection=1, encoder_id=0, count_modes=1, count_encoders=1, encoder_ids=[10])

        enc_for_crtc = MagicMock()
        enc_for_crtc.possible_crtcs = 0b1
        enc_for_crtc.crtc_id = 0
        enc_p_for_crtc = MagicMock()
        enc_p_for_crtc.contents = enc_for_crtc

        # drmModeGetConnector: first call returns conn_p (for find_connector),
        # subsequent calls (from _find_free_crtc scanning other connectors) return null
        call_count = [0]

        def get_connector(fd, cid):
            call_count[0] += 1
            if call_count[0] == 1:
                return conn_p
            return None

        lib.drmModeGetConnector.side_effect = get_connector
        lib.drmModeGetEncoder.return_value = enc_p_for_crtc

        result = probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1")
        assert isinstance(result, tuple)
        crtc_id, connector_id, mode = result
        assert crtc_id == 100
        assert connector_id == 1
        assert isinstance(mode, DrmModeModeInfo)

    def test_encoder_without_crtc_continues(self):
        """encoder_id set but encoder has no crtc_id → continues to check modes"""
        lib = _make_mock_libdrm()
        res = _make_res([1], [100])
        conn_p = _make_connector(1, 10, 1, connection=1, encoder_id=5, count_modes=1, count_encoders=1, encoder_ids=[10])

        enc_no_crtc = MagicMock()
        enc_no_crtc.crtc_id = 0  # no crtc
        enc_p_no_crtc = MagicMock()
        enc_p_no_crtc.contents = enc_no_crtc

        enc_for_free = MagicMock()
        enc_for_free.possible_crtcs = 0b1
        enc_for_free.crtc_id = 0
        enc_p_for_free = MagicMock()
        enc_p_for_free.contents = enc_for_free

        call_count = [0]

        def get_connector(fd, cid):
            call_count[0] += 1
            if call_count[0] == 1:
                return conn_p
            return None

        def get_encoder(fd, enc_id):
            if enc_id == 5:
                return enc_p_no_crtc
            return enc_p_for_free

        lib.drmModeGetConnector.side_effect = get_connector
        lib.drmModeGetEncoder.side_effect = get_encoder

        result = probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1")
        # Should proceed to get modes and return a tuple (crtc needed)
        assert result is not None

    def test_null_encoder_pointer_when_checking_existing_crtc(self):
        """encoder_id set but drmModeGetEncoder returns None → continues"""
        lib = _make_mock_libdrm()
        res = _make_res([1], [100])
        conn_p = _make_connector(1, 10, 1, connection=1, encoder_id=5, count_modes=1, count_encoders=1, encoder_ids=[10])

        enc_for_free = MagicMock()
        enc_for_free.possible_crtcs = 0b1
        enc_for_free.crtc_id = 0
        enc_p_for_free = MagicMock()
        enc_p_for_free.contents = enc_for_free

        call_count = [0]

        def get_connector(fd, cid):
            call_count[0] += 1
            if call_count[0] == 1:
                return conn_p
            return None

        def get_encoder(fd, enc_id):
            if enc_id == 5:
                return None  # no encoder pointer
            return enc_p_for_free

        lib.drmModeGetConnector.side_effect = get_connector
        lib.drmModeGetEncoder.side_effect = get_encoder

        result = probe_connector(lib, 5, res, "DisplayPort", 1, "DP-1")
        assert result is not None
