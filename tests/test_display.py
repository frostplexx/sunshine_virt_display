"""Tests for src/display.py"""

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, call, patch

import pytest

from src.display import connect, disconnect, kwin_session_pid
from src.display import _use_hyprland_safe_path as _real_use_hyprland_safe_path
from src.display import _use_kwin_safe_path as _real_use_kwin_safe_path


def _ok_run(cmd: str = "") -> CompletedProcess:
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


def _fail_run(cmd: str = "") -> CompletedProcess:
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="error")


@pytest.fixture(autouse=True)
def _default_to_legacy_drm_path():
    """Keep existing tests deterministic on Hyprland dev machines."""
    with patch("src.display._use_hyprland_safe_path", return_value=False), \
         patch("src.display._use_kwin_safe_path", return_value=False), \
         patch("src.display.notify_hotplug", return_value=True), \
         patch("src.display.kwin.start_input_mapping"), \
         patch("src.display.kwin.stop_input_mapping"), \
         patch("src.display.kwin.restart_virtual_keyboard_later"), \
         patch("src.display._output_connected", return_value=True):
        yield


class TestHyprlandSafePathGate:
    """Regression for issue #31: AMD + Hyprland must not use direct DRM CRTC stealing."""

    def test_hyprland_on_amdgpu_uses_safe_path(self):
        with patch("src.display.hyprland.available", return_value=True):
            assert _real_use_hyprland_safe_path() is True

    def test_hyprland_on_nvidia_uses_safe_path(self):
        with patch("src.display.hyprland.available", return_value=True):
            assert _real_use_hyprland_safe_path() is True

    def test_non_hyprland_uses_legacy_drm_path(self):
        with patch("src.display.hyprland.available", return_value=False):
            assert _real_use_hyprland_safe_path() is False

    def test_kwin_gate_follows_kwin_availability(self):
        with patch("src.display.kwin.available", return_value=True):
            assert _real_use_kwin_safe_path() is True
        with patch("src.display.kwin.available", return_value=False):
            assert _real_use_kwin_safe_path() is False


class TestConnect:
    def _base_patches(self):
        """Return a dict of patch targets with sensible defaults."""
        return {
            "src.display.get_pixel_clock_info": (100.0, 655.35, False),
            "src.display.get_drm_devices": [Path("/sys/kernel/debug/dri/0000:01:00.0")],
            "src.display.get_card_name_from_device": "card1",
            "src.display.get_connected_displays": [],
            "src.display.find_empty_slot": ("DP-1", Path("/sys/kernel/debug/dri/0000:01:00.0")),
            "src.display.run_command": _ok_run(),
            "src.display.release_crtc": True,
            "src.display.force_crtc_assignment": True,
            "src.display.wait_for_output_ready": (True, "1920x1080"),
            "src.display.clear_kwin_output_config": None,
            "src.display.create_edid": b"\x00" * 256,
            "src.display.find_best_vic_resolution": None,
        }

    def test_returns_true_on_success(self, tmp_path):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60)
        assert result is True

    def test_returns_false_when_no_drm_devices(self, tmp_path, capsys):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[]), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60)
        assert result is False
        assert "No DRM devices" in capsys.readouterr().out

    def test_returns_false_when_device_not_found(self, tmp_path, capsys):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card0"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60, device="card1")
        assert result is False
        assert "not found" in capsys.readouterr().out

    def test_explicit_device_selected(self, tmp_path):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60, device="card1")
        assert result is True

    def test_returns_false_when_no_empty_slot(self, tmp_path, capsys):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=(None, None)), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60)
        assert result is False
        assert "No empty" in capsys.readouterr().out

    def test_returns_false_when_edid_override_fails(self, tmp_path, capsys):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_fail_run()), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60)
        assert result is False

    def test_returns_false_when_enable_display_fails(self, tmp_path, capsys):
        call_count = [0]

        def run_side(cmd):
            call_count[0] += 1
            # First call (EDID override) succeeds; second (turn off display n/a here);
            # third (turn on virtual) fails
            if call_count[0] == 1:
                return _ok_run()
            return _fail_run()

        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", side_effect=run_side), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60)
        assert result is False

    def test_pixel_clock_fallback_to_vic(self, tmp_path, capsys):
        vic_result = (1920, 1080, 60, 16, "1080p")
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(700.0, 655.35, True)), \
             patch("src.display.find_best_vic_resolution", return_value=vic_result), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 120)
        assert result is True
        out = capsys.readouterr().out
        assert "Falling back to VIC" in out

    def test_pixel_clock_no_vic_found(self, tmp_path, capsys):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(700.0, 655.35, True)), \
             patch("src.display.find_best_vic_resolution", return_value=None), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 120)
        assert result is True
        out = capsys.readouterr().out
        assert "No suitable VIC" in out

    def test_connected_displays_released(self, tmp_path):
        mock_release = MagicMock(return_value=True)
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["HDMI-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", mock_release), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            connect(1920, 1080, 60)
        mock_release.assert_called_with("card1", "HDMI-1")

    def test_force_crtc_when_not_ready(self, tmp_path, capsys):
        ready_seq = [(False, ""), (True, "1920x1080")]
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.force_crtc_assignment", return_value=True) as mock_force, \
             patch("src.display.wait_for_output_ready", side_effect=ready_seq), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60)
        assert result is True
        mock_force.assert_called_once()

    def test_timeout_warning_when_still_not_ready(self, tmp_path, capsys):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(False, "")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60)
        assert result is True
        assert "Timed out" in capsys.readouterr().out

    def test_selects_gpu_with_most_displays(self, tmp_path):
        dev1 = Path("/sys/kernel/debug/dri/0000:01:00.0")
        dev2 = Path("/sys/kernel/debug/dri/0000:02:00.0")

        def card_name(dev):
            return "card0" if dev == dev1 else "card1"

        def connected(card):
            return [] if card == "card0" else ["HDMI-1", "DP-1"]

        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[dev1, dev2]), \
             patch("src.display.get_card_name_from_device", side_effect=card_name), \
             patch("src.display.get_connected_displays", side_effect=connected), \
             patch("src.display.find_empty_slot", return_value=("DP-2", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1920, 1080, 60)
        assert result is True

    def test_state_file_written(self, tmp_path):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["HDMI-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", return_value=True), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            connect(1920, 1080, 60)

        state_file = tmp_path / "virt_display.state"
        assert state_file.exists()
        content = state_file.read_text()
        assert "card1" in content
        assert "DP-1" in content
        assert "HDMI-1" in content

    def test_nvidia_hyprland_safe_path_preserves_monitor_options(self, tmp_path):
        restore_specs = {
            "DP-1": {
                "output": "DP-1",
                "mode": "3440x1440@144.0",
                "position": "0x0",
                "scale": 1.0,
                "bitdepth": 10,
                "vrr": 1,
            }
        }
        mock_release = MagicMock(return_value=True)
        mock_force = MagicMock(return_value=True)

        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._use_hyprland_safe_path", return_value=True), \
             patch("src.display.hyprland.monitor_specs", return_value=restore_specs), \
             patch("src.display.hyprland.disable_outputs", return_value=True) as mock_disable, \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["DP-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-3", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.release_crtc", mock_release), \
             patch("src.display.force_crtc_assignment", mock_force), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1280x800")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1280, 800, 60)

        assert result is True
        mock_release.assert_not_called()
        mock_force.assert_not_called()
        mock_disable.assert_called_once_with(["DP-1"])
        content = (tmp_path / "virt_display.state").read_text()
        assert '"bitdepth": 10' in content
        assert '"vrr": 1' in content

    def test_nvidia_hyprland_safe_path_refuses_without_restore_specs(self, tmp_path):
        mock_run = MagicMock(return_value=_ok_run())
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._use_hyprland_safe_path", return_value=True), \
             patch("src.display.hyprland.monitor_specs", return_value={}), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["DP-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-3", tmp_path)), \
             patch("src.display.run_command", mock_run), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(1280, 800, 60)

        assert result is False
        cmds = [call_args[0][0] for call_args in mock_run.call_args_list]
        assert not any("echo off > /sys/class/drm/card1-DP-1/status" in c for c in cmds)


    def test_kwin_safe_path_hides_outputs_without_drm_stealing(self, tmp_path):
        restore_specs = {"HDMI-A-2": {"output": "HDMI-A-2", "mode": "3", "position": "0,0", "scale": 1}}
        mock_release = MagicMock(return_value=True)
        mock_force = MagicMock(return_value=True)
        mock_run = MagicMock(return_value=_ok_run())

        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._use_kwin_safe_path", return_value=True), \
             patch("src.display.kwin.monitor_specs", return_value=restore_specs), \
             patch("src.display.kwin.disable_outputs", return_value=True) as mock_disable, \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:01:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["HDMI-A-2"]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", mock_run), \
             patch("src.display.release_crtc", mock_release), \
             patch("src.display.force_crtc_assignment", mock_force), \
             patch("src.display.wait_for_output_ready", return_value=(True, "854x480")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            result = connect(854, 480, 60)

        assert result is True
        mock_release.assert_not_called()
        mock_force.assert_not_called()
        mock_disable.assert_called_once_with(["HDMI-A-2"])
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert not any("card1-HDMI-A-2/status" in c for c in cmds)
        lines = (tmp_path / "virt_display.state").read_text().split("\n")
        assert lines[5] == "kwin"

    def test_kwin_connect_maps_touch_to_virtual_output(self, tmp_path):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._use_kwin_safe_path", return_value=True), \
             patch("src.display.kwin.monitor_specs", return_value={"HDMI-A-1": {"output": "HDMI-A-1"}}), \
             patch("src.display.kwin.disable_outputs", return_value=True), \
             patch("src.display.kwin.start_input_mapping") as start_map, \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:03:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["HDMI-A-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.wait_for_output_ready", return_value=(True, "2868x1320")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            assert connect(2868, 1320, 120) is True
        start_map.assert_called_once_with("DP-1")

    def test_kwin_disabled_connected_output_does_not_abort(self, tmp_path):
        specs = {
            "HDMI-A-1": {"output": "HDMI-A-1", "enabled": True},
            "eDP-1": {"output": "eDP-1", "enabled": False},
        }
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._use_kwin_safe_path", return_value=True), \
             patch("src.display.kwin.monitor_specs", return_value=specs), \
             patch("src.display.kwin.disable_outputs", return_value=True) as disable, \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:03:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["HDMI-A-1", "eDP-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.wait_for_output_ready", return_value=(True, "2868x1320")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            assert connect(2868, 1320, 120) is True
        disable.assert_called_once_with(["HDMI-A-1"])
        saved = json.loads((tmp_path / "virt_display.state").read_text().split("\n")[4])
        assert saved["HDMI-A-1"]["enabled"] is True
        assert saved["eDP-1"]["enabled"] is False

    def test_kwin_missing_restore_state_clears_edid_override(self, tmp_path):
        mock_run = MagicMock(return_value=_ok_run())
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._use_kwin_safe_path", return_value=True), \
             patch("src.display.kwin.monitor_specs", return_value={}), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:03:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["HDMI-A-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", mock_run), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            assert connect(854, 480, 60) is False
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("/dev/null >" in c and "edid_override" in c for c in cmds)

    def test_kwin_connect_restarts_keyboard(self, tmp_path):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._use_kwin_safe_path", return_value=True), \
             patch("src.display.kwin.monitor_specs", return_value={"HDMI-A-1": {"output": "HDMI-A-1"}}), \
             patch("src.display.kwin.disable_outputs", return_value=True), \
             patch("src.display.kwin.restart_virtual_keyboard_later") as restart_kb, \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:03:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["HDMI-A-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.wait_for_output_ready", return_value=(True, "2868x1320")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            assert connect(2868, 1320, 120) is True
        restart_kb.assert_called_once()

    def test_kwin_connect_records_the_compositor_pid(self, tmp_path):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._use_kwin_safe_path", return_value=True), \
             patch("src.display.kwin.monitor_specs", return_value={"HDMI-A-1": {"output": "HDMI-A-1"}}), \
             patch("src.display.kwin.disable_outputs", return_value=True), \
             patch("src.display.kwin.find_kwin_pid", return_value=1359), \
             patch("src.display.kwin.start_input_mapping"), \
             patch("src.display.kwin.restart_virtual_keyboard_later") as restart_kb, \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:03:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=["HDMI-A-1"]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.wait_for_output_ready", return_value=(True, "2868x1320")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            assert connect(2868, 1320, 120) is True
        lines = (tmp_path / "virt_display.state").read_text().split("\n")
        assert lines[6] == "1359"
        restart_kb.assert_called_once_with(kwin_pid=1359)

    def test_kwin_logout_checks_the_recorded_pid(self, tmp_path):
        (tmp_path / "virt_display.state").write_text(
            "card1\nDP-1\nHDMI-A-1\n/x/edid_override\n"
            '{"HDMI-A-1":{"output":"HDMI-A-1","width":3440,"height":1440,'
            '"refresh":100,"position":"0,0","scale":2}}\nkwin\n1359')
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.kwin.restore_outputs", return_value=False), \
             patch("src.display.kwin.session_alive", return_value=False) as alive, \
             patch("src.display.kwin.restart_virtual_keyboard_later") as restart_kb, \
             patch("src.display.run_command", return_value=_ok_run()):
            assert disconnect() is True
        alive.assert_called_once_with(1359)
        restart_kb.assert_called_once_with(kwin_pid=1359)

    def test_kwin_session_pid(self, tmp_path):
        state = tmp_path / "virt_display.state"
        state.write_text("card1\nDP-1\n\n\n{}\nkwin\n1359")
        with patch("src.display.SCRIPT_DIR", tmp_path):
            assert kwin_session_pid() == 1359
        state.write_text("card1\nDP-1\n\n\n{}\nkwin")
        with patch("src.display.SCRIPT_DIR", tmp_path):
            assert kwin_session_pid() is None

    def test_legacy_connect_does_not_restart_keyboard(self, tmp_path):
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.kwin.restart_virtual_keyboard_later") as restart_kb, \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:03:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            assert connect(1920, 1080, 60) is True
        restart_kb.assert_not_called()

    def test_hotplug_sent_after_enabling_virtual_output(self, tmp_path):
        # Regression: sysfs status writes emit no uevent, so KWin never saw the
        # virtual output and Step 7 timed out.
        order: list[str] = []
        def run(cmd):
            if "echo on" in cmd:
                order.append("on")
            return _ok_run()
        def ready(*a, **k):
            order.append("wait")
            return (True, "1920x1080")
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.notify_hotplug", side_effect=lambda c: order.append(f"hotplug:{c}")), \
             patch("src.display.get_pixel_clock_info", return_value=(100.0, 655.35, False)), \
             patch("src.display.get_drm_devices", return_value=[Path("/sys/kernel/debug/dri/0000:03:00.0")]), \
             patch("src.display.get_card_name_from_device", return_value="card1"), \
             patch("src.display.get_connected_displays", return_value=[]), \
             patch("src.display.find_empty_slot", return_value=("DP-1", tmp_path)), \
             patch("src.display.run_command", side_effect=run), \
             patch("src.display.wait_for_output_ready", side_effect=ready), \
             patch("src.display.clear_kwin_output_config"), \
             patch("src.display.create_edid", return_value=b"\x00" * 256):
            assert connect(1920, 1080, 60) is True
        assert order.index("on") < order.index("hotplug:card1") < order.index("wait")


class TestDisconnect:
    def _write_state(self, path: Path, card: str, port: str, displays: list[str]) -> None:
        (path / "virt_display.state").write_text(
            f"{card}\n{port}\n{','.join(displays)}"
        )

    def test_returns_false_when_no_state_file(self, tmp_path, capsys):
        with patch("src.display.SCRIPT_DIR", tmp_path):
            result = disconnect()
        assert result is False
        assert "No state file" in capsys.readouterr().out

    def test_returns_false_when_state_file_invalid(self, tmp_path, capsys):
        (tmp_path / "virt_display.state").write_text("only_one_line")
        with patch("src.display.SCRIPT_DIR", tmp_path):
            result = disconnect()
        assert result is False
        assert "Invalid state" in capsys.readouterr().out

    def test_returns_true_on_success(self, tmp_path):
        self._write_state(tmp_path, "card1", "DP-2", ["HDMI-1"])
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.release_crtc", return_value=True):
            result = disconnect()
        assert result is True

    def test_state_file_deleted_after_disconnect(self, tmp_path):
        self._write_state(tmp_path, "card1", "DP-2", ["HDMI-1"])
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.release_crtc", return_value=True):
            disconnect()
        assert not (tmp_path / "virt_display.state").exists()

    def test_turns_on_previous_displays(self, tmp_path):
        self._write_state(tmp_path, "card1", "DP-2", ["HDMI-1", "DP-1"])
        mock_run = MagicMock(return_value=_ok_run())
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.run_command", mock_run), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.release_crtc", return_value=True):
            disconnect()
        # Should have called run_command with 'echo on' for previous displays
        cmds = [call_args[0][0] for call_args in mock_run.call_args_list]
        on_cmds = [c for c in cmds if "echo on" in c]
        assert len(on_cmds) >= 2

    def test_skips_empty_display_names(self, tmp_path):
        self._write_state(tmp_path, "card1", "DP-2", [""])
        mock_run = MagicMock(return_value=_ok_run())
        mock_force = MagicMock(return_value=True)
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.run_command", mock_run), \
             patch("src.display.force_crtc_assignment", mock_force), \
             patch("src.display.release_crtc", return_value=True):
            result = disconnect()
        assert result is True
        mock_force.assert_not_called()

    def test_no_previous_displays(self, tmp_path):
        self._write_state(tmp_path, "card1", "DP-2", [])
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.release_crtc", return_value=True):
            result = disconnect()
        assert result is True

    def test_warns_when_turn_off_virtual_fails(self, tmp_path, capsys):
        self._write_state(tmp_path, "card1", "DP-2", [])
        run_calls = [0]

        def run_side(cmd):
            run_calls[0] += 1
            # Last call (echo off for virtual display) fails
            if "echo off" in cmd:
                return _fail_run()
            return _ok_run()

        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.run_command", side_effect=run_side), \
             patch("src.display.force_crtc_assignment", return_value=True), \
             patch("src.display.release_crtc", return_value=True):
            result = disconnect()

        assert result is True
        assert "Warning" in capsys.readouterr().out

    def test_forces_crtc_for_all_restored_displays(self, tmp_path):
        self._write_state(tmp_path, "card1", "DP-2", ["HDMI-1", "DP-1"])
        mock_force = MagicMock(return_value=True)
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.force_crtc_assignment", mock_force), \
             patch("src.display.wait_for_output_ready", return_value=(True, "1920x1080")), \
             patch("src.display.release_crtc", return_value=True):
            disconnect()
        assert mock_force.call_count == 2

    def test_hyprland_restore_path_skips_crtc_forcing(self, tmp_path):
        restore_json = '{"DP-1":{"output":"DP-1","mode":"3440x1440@144.0","position":"0x0","scale":1.0,"bitdepth":10,"vrr":1}}'
        (tmp_path / "virt_display.state").write_text(
            f"card1\nDP-3\nDP-1\n{tmp_path / 'DP-3' / 'edid_override'}\n{restore_json}"
        )
        mock_restore = MagicMock(return_value=True)
        mock_force = MagicMock(return_value=True)
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.hyprland.restore_outputs", mock_restore), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.force_crtc_assignment", mock_force), \
             patch("src.display.release_crtc", return_value=True):
            result = disconnect()

        assert result is True
        mock_restore.assert_called_once()
        mock_force.assert_not_called()

    def test_kwin_restore_path_skips_crtc_forcing(self, tmp_path):
        restore_json = '{"HDMI-A-2":{"output":"HDMI-A-2","mode":"3","position":"0,0","scale":1}}'
        (tmp_path / "virt_display.state").write_text(
            f"card1\nDP-1\nHDMI-A-2\n{tmp_path / 'DP-1' / 'edid_override'}\n{restore_json}\nkwin"
        )
        mock_kwin = MagicMock(return_value=True)
        mock_hypr = MagicMock(return_value=True)
        mock_force = MagicMock(return_value=True)
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.kwin.restore_outputs", mock_kwin), \
             patch("src.display.hyprland.restore_outputs", mock_hypr), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.force_crtc_assignment", mock_force), \
             patch("src.display.release_crtc", return_value=True):
            result = disconnect()

        assert result is True
        mock_kwin.assert_called_once()
        mock_hypr.assert_not_called()
        mock_force.assert_not_called()

    def test_kwin_disconnect_without_restore_specs_uses_safe_path(self, tmp_path):
        state = tmp_path / "virt_display.state"
        state.write_text("card1\nDP-1\n\n\n{}\nkwin")
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.kwin.stop_input_mapping") as stop_map, \
             patch("src.display.kwin.restart_virtual_keyboard_later") as restart_kb, \
             patch("src.display.release_crtc") as release, \
             patch("src.display.force_crtc_assignment") as force, \
             patch("src.display.run_command", return_value=_ok_run()):
            assert disconnect() is True
        stop_map.assert_called_once()
        restart_kb.assert_called_once()
        release.assert_not_called()
        force.assert_not_called()

    def test_kwin_disconnect_stops_touch_mapping(self, tmp_path):
        (tmp_path / "virt_display.state").write_text(
            'card1\nDP-1\nHDMI-A-1\n\n{"HDMI-A-1":{"output":"HDMI-A-1","width":3440,"height":1440,"refresh":100,"position":"0,0","scale":2}}\nkwin'
        )
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.kwin.restore_outputs", return_value=True), \
             patch("src.display.kwin.stop_input_mapping") as stop_map, \
             patch("src.display.kwin.restart_virtual_keyboard_later") as restart_kb, \
             patch("src.display.run_command", return_value=_ok_run()):
            assert disconnect() is True
        stop_map.assert_called_once()
        restart_kb.assert_called_once()

    def test_hotplug_sent_after_virtual_output_removed(self, tmp_path):
        # Regression: without a uevent KWin kept the disconnected virtual
        # output as an invisible extra screen.
        (tmp_path / "virt_display.state").write_text(
            'card1\nDP-1\nHDMI-A-1\n/x/edid_override\n{"HDMI-A-1":{"output":"HDMI-A-1","width":3440,"height":1440,"refresh":100,"position":"0,0","scale":2}}\nkwin'
        )
        order: list[str] = []
        def run(cmd):
            order.append("edid-clear" if "/dev/null" in cmd else "off" if "echo off" in cmd else cmd)
            return _ok_run()
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.kwin.restore_outputs", return_value=True), \
             patch("src.display.notify_hotplug", side_effect=lambda c: order.append(f"hotplug:{c}")), \
             patch("src.display.run_command", side_effect=run):
            assert disconnect() is True
        assert order[-1] == "hotplug:card1"
        assert order.index("off") < order.index("edid-clear") < order.index("hotplug:card1")

    def test_kwin_restore_failure_preserves_state(self, tmp_path):
        state = tmp_path / "virt_display.state"
        state.write_text('card1\nDP-1\nHDMI-A-2\n\n{"HDMI-A-2":{"output":"HDMI-A-2","mode":"3","position":"0,0","scale":1}}\nkwin')
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.kwin.restore_outputs", return_value=False), \
             patch("src.display.kwin.session_alive", return_value=True), \
             patch("src.display.run_command", return_value=_ok_run()):
            assert disconnect() is False
        assert state.exists()

    def test_kwin_logout_still_removes_virtual_display(self, tmp_path):
        # Logged out: KWin is gone, so the restore can't succeed. The virtual
        # output must still be switched off, or the next login comes up on the
        # phone-sized phantom display with the monitor disabled.
        state = tmp_path / "virt_display.state"
        state.write_text('card1\nDP-1\nHDMI-A-1\n/x/edid_override\n{"HDMI-A-1":{"output":"HDMI-A-1","width":3440,"height":1440,"refresh":100,"position":"0,0","scale":2}}\nkwin')
        mock_run = MagicMock(return_value=_ok_run())
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.kwin.restore_outputs", return_value=False), \
             patch("src.display.kwin.session_alive", return_value=False), \
             patch("src.display.run_command", mock_run):
            assert disconnect() is True
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("echo off > /sys/class/drm/card1-DP-1/status" in c for c in cmds)
        assert any("/dev/null > /x/edid_override" in c for c in cmds)
        assert not state.exists()

    def test_unplugged_monitor_is_skipped_on_restore(self, tmp_path):
        state = tmp_path / "virt_display.state"
        specs = '{"HDMI-A-1":{"output":"HDMI-A-1"},"DP-2":{"output":"DP-2"}}'
        state.write_text(f"card1\nDP-1\nHDMI-A-1,DP-2\n\n{specs}\nkwin")
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._output_connected", side_effect=lambda c, o: o == "HDMI-A-1"), \
             patch("src.display.kwin.restore_outputs", return_value=True) as restore, \
             patch("src.display.run_command", return_value=_ok_run()):
            assert disconnect() is True
        assert list(restore.call_args[0][0]) == ["HDMI-A-1"]

    def test_all_monitors_unplugged_still_removes_virtual_display(self, tmp_path):
        # Monitor unplugged mid-stream: restoring it would fail and leave the
        # virtual display stuck on, like after a logout.
        state = tmp_path / "virt_display.state"
        state.write_text('card1\nDP-1\nHDMI-A-1\n/x/edid_override\n{"HDMI-A-1":{"output":"HDMI-A-1"}}\nkwin')
        mock_run = MagicMock(return_value=_ok_run())
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display._output_connected", return_value=False), \
             patch("src.display.kwin.restore_outputs") as restore, \
             patch("src.display.run_command", mock_run):
            assert disconnect() is True
        restore.assert_not_called()
        assert any("echo off > /sys/class/drm/card1-DP-1/status" in c[0][0] for c in mock_run.call_args_list)
        assert not state.exists()

    def test_physical_connectors_excludes_virtual_and_writeback(self, tmp_path):
        from src.display import physical_connectors
        sysfs = tmp_path / "drm"
        for name, status in [("card1-HDMI-A-1", "connected"), ("card1-DP-1", "connected"),
                             ("card1-DP-2", "disconnected"), ("card1-Writeback-1", "connected")]:
            (sysfs / name).mkdir(parents=True)
            (sysfs / name / "status").write_text(status + "\n")
        (tmp_path / "virt_display.state").write_text("card1\nDP-1\nHDMI-A-1\n\n{}\nkwin")
        with patch("src.display.DRM_SYSFS", sysfs), patch("src.display.SCRIPT_DIR", tmp_path):
            assert physical_connectors() == {"card1-HDMI-A-1"}
        (tmp_path / "virt_display.state").unlink()
        with patch("src.display.DRM_SYSFS", sysfs), patch("src.display.SCRIPT_DIR", tmp_path):
            assert physical_connectors() == {"card1-HDMI-A-1", "card1-DP-1"}

    @pytest.mark.parametrize("content,expected", [
        ('card1\nDP-1\nHDMI-A-1\n/x\n{"HDMI-A-1":{}}\nkwin', "kwin"),
        ('card1\nDP-1\nHDMI-A-1\n/x\n{"HDMI-A-1":{}}', "hyprland"),
        ("card1\nDP-1\nHDMI-A-1\n/x\n{}\n", None),
    ])
    def test_active_backend(self, tmp_path, content, expected):
        from src.display import active_backend
        (tmp_path / "virt_display.state").write_text(content)
        with patch("src.display.SCRIPT_DIR", tmp_path):
            assert active_backend() == expected

    def test_active_backend_without_session(self, tmp_path):
        from src.display import active_backend
        with patch("src.display.SCRIPT_DIR", tmp_path):
            assert active_backend() is None
