"""Tests for src/display.py"""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, call, patch

import pytest

from src.display import connect, disconnect


def _ok_run(cmd: str = "") -> CompletedProcess:
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


def _fail_run(cmd: str = "") -> CompletedProcess:
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="error")


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
             patch("src.display.release_crtc", return_value=True):
            result = disconnect()
        assert result is True

    def test_state_file_deleted_after_disconnect(self, tmp_path):
        self._write_state(tmp_path, "card1", "DP-2", ["HDMI-1"])
        with patch("src.display.SCRIPT_DIR", tmp_path), \
             patch("src.display.run_command", return_value=_ok_run()), \
             patch("src.display.force_crtc_assignment", return_value=True), \
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
             patch("src.display.release_crtc", return_value=True):
            disconnect()
        assert mock_force.call_count == 2
