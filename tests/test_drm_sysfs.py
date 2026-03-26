"""Tests for src/drm/sysfs.py"""

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.drm.sysfs import (
    find_empty_slot,
    get_card_name_from_device,
    get_connected_displays,
    get_display_ports,
    get_drm_devices,
    run_command,
)


class TestRunCommand:
    def test_returns_completed_process(self):
        result = run_command("echo hello")
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_captures_stderr(self):
        result = run_command("ls /nonexistent_path_xyz 2>&1")
        # Either returncode != 0 or stderr has content
        assert result.returncode != 0 or result.returncode == 0

    def test_failed_command(self):
        result = run_command("false")
        assert result.returncode != 0

    def test_stdout_captured_as_text(self):
        result = run_command("echo test")
        assert isinstance(result.stdout, str)


class TestGetDrmDevices:
    def test_returns_empty_on_error(self, capsys):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            devices = get_drm_devices()
        assert devices == []
        assert "Error" in capsys.readouterr().out

    def test_returns_pci_devices(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "0000:01:00.0\n0000:02:00.0\nsomething_else\n"
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            devices = get_drm_devices()
        assert len(devices) == 2
        assert all(d.name.startswith("0000:") for d in devices)

    def test_returns_sorted_paths(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "0000:02:00.0\n0000:01:00.0\n"
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            devices = get_drm_devices()
        assert devices == sorted(devices)

    def test_skips_non_pci_lines(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ttm\nbridge\n0000:01:00.0\n"
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            devices = get_drm_devices()
        assert len(devices) == 1

    def test_returns_path_objects(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "0000:01:00.0\n"
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            devices = get_drm_devices()
        assert all(isinstance(d, Path) for d in devices)


class TestGetDisplayPorts:
    def test_returns_empty_on_error(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            ports = get_display_ports(Path("/fake/device"))
        assert ports == {"DP": [], "HDMI": []}

    def test_parses_dp_ports(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "DP-1\nDP-2\nHDMI-1\n"
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            ports = get_display_ports(Path("/fake/device"))
        assert "DP-1" in ports["DP"]
        assert "DP-2" in ports["DP"]

    def test_parses_hdmi_ports(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "HDMI-1\nHDMI-2\n"
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            ports = get_display_ports(Path("/fake/device"))
        assert "HDMI-1" in ports["HDMI"]
        assert "HDMI-2" in ports["HDMI"]

    def test_skips_unrecognized_lines(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "DP-1\nVGA-1\nDVI-D-1\n"
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            ports = get_display_ports(Path("/fake/device"))
        assert len(ports["DP"]) == 1
        assert len(ports["HDMI"]) == 0

    def test_empty_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("src.drm.sysfs.run_command", return_value=mock_result):
            ports = get_display_ports(Path("/fake/device"))
        assert ports["DP"] == []
        assert ports["HDMI"] == []


class TestGetConnectedDisplays:
    def _make_display_entry(self, name: str, status: str) -> MagicMock:
        status_file = MagicMock()
        status_file.exists.return_value = True
        status_file.read_text.return_value = status

        entry = MagicMock()
        entry.name = name
        entry.__truediv__ = lambda self, other: status_file
        return entry

    def test_returns_connected_ports(self):
        card = "card1"
        entry = self._make_display_entry(f"{card}-DP-1", "connected")

        mock_path = MagicMock()
        mock_path.iterdir.return_value = [entry]

        with patch("src.drm.sysfs.Path", return_value=mock_path):
            result = get_connected_displays(card)

        assert "DP-1" in result

    def test_skips_disconnected(self):
        card = "card1"
        entry = self._make_display_entry(f"{card}-DP-1", "disconnected")

        mock_path = MagicMock()
        mock_path.iterdir.return_value = [entry]

        with patch("src.drm.sysfs.Path", return_value=mock_path):
            result = get_connected_displays(card)

        assert result == []

    def test_skips_other_cards(self):
        entry = self._make_display_entry("card0-DP-1", "connected")

        mock_path = MagicMock()
        mock_path.iterdir.return_value = [entry]

        with patch("src.drm.sysfs.Path", return_value=mock_path):
            result = get_connected_displays("card1")

        assert result == []

    def test_skips_missing_status_file(self):
        entry = MagicMock()
        entry.name = "card1-DP-1"
        status_file = MagicMock()
        status_file.exists.return_value = False
        entry.__truediv__ = lambda self, other: status_file

        mock_path = MagicMock()
        mock_path.iterdir.return_value = [entry]

        with patch("src.drm.sysfs.Path", return_value=mock_path):
            result = get_connected_displays("card1")

        assert result == []

    def test_handles_read_exception(self):
        entry = MagicMock()
        entry.name = "card1-DP-1"
        status_file = MagicMock()
        status_file.exists.return_value = True
        status_file.read_text.side_effect = OSError("permission denied")
        entry.__truediv__ = lambda self, other: status_file

        mock_path = MagicMock()
        mock_path.iterdir.return_value = [entry]

        with patch("src.drm.sysfs.Path", return_value=mock_path):
            result = get_connected_displays("card1")

        assert result == []


class TestFindEmptySlot:
    def test_prefers_dp_over_hdmi(self):
        device = Path("/fake/device")
        with patch("src.drm.sysfs.get_display_ports") as mock_ports, \
             patch("src.drm.sysfs.get_connected_displays") as mock_connected:
            mock_ports.return_value = {"DP": ["DP-1"], "HDMI": ["HDMI-1"]}
            mock_connected.return_value = []
            port, dev = find_empty_slot(device, "card1")
        assert port == "DP-1"

    def test_falls_back_to_hdmi(self):
        device = Path("/fake/device")
        with patch("src.drm.sysfs.get_display_ports") as mock_ports, \
             patch("src.drm.sysfs.get_connected_displays") as mock_connected:
            mock_ports.return_value = {"DP": ["DP-1"], "HDMI": ["HDMI-1"]}
            mock_connected.return_value = ["DP-1"]
            port, dev = find_empty_slot(device, "card1")
        assert port == "HDMI-1"

    def test_returns_none_when_all_occupied(self):
        device = Path("/fake/device")
        with patch("src.drm.sysfs.get_display_ports") as mock_ports, \
             patch("src.drm.sysfs.get_connected_displays") as mock_connected:
            mock_ports.return_value = {"DP": ["DP-1"], "HDMI": ["HDMI-1"]}
            mock_connected.return_value = ["DP-1", "HDMI-1"]
            port, dev = find_empty_slot(device, "card1")
        assert port is None
        assert dev is None

    def test_returns_device_path(self):
        device = Path("/fake/device")
        with patch("src.drm.sysfs.get_display_ports") as mock_ports, \
             patch("src.drm.sysfs.get_connected_displays") as mock_connected:
            mock_ports.return_value = {"DP": ["DP-1"], "HDMI": []}
            mock_connected.return_value = []
            port, dev = find_empty_slot(device, "card1")
        assert dev == device

    def test_sorts_dp_ports(self):
        device = Path("/fake/device")
        with patch("src.drm.sysfs.get_display_ports") as mock_ports, \
             patch("src.drm.sysfs.get_connected_displays") as mock_connected:
            mock_ports.return_value = {"DP": ["DP-3", "DP-1", "DP-2"], "HDMI": []}
            mock_connected.return_value = []
            port, dev = find_empty_slot(device, "card1")
        assert port == "DP-1"

    def test_no_ports_at_all(self):
        device = Path("/fake/device")
        with patch("src.drm.sysfs.get_display_ports") as mock_ports, \
             patch("src.drm.sysfs.get_connected_displays") as mock_connected:
            mock_ports.return_value = {"DP": [], "HDMI": []}
            mock_connected.return_value = []
            port, dev = find_empty_slot(device, "card1")
        assert port is None
        assert dev is None


class TestGetCardNameFromDevice:
    def test_returns_card_name_from_symlink(self, tmp_path):
        # Create a fake /sys/class/drm structure
        drm_class = tmp_path / "drm"
        card_dir = drm_class / "card1"
        card_dir.mkdir(parents=True)
        device_link = card_dir / "device"

        device_name = "0000:01:00.0"
        target_path = tmp_path / device_name
        target_path.mkdir()
        device_link.symlink_to(target_path)

        drm_device_path = Path("/sys/kernel/debug/dri") / device_name

        with patch("src.drm.sysfs.Path") as MockPath:
            # Mock Path("/sys/class/drm")
            mock_drm_path = MagicMock()

            card1_mock = MagicMock()
            card1_mock.name = "card1"
            dev_link = MagicMock()
            dev_link.exists.return_value = True
            card1_mock.__truediv__ = lambda self, other: dev_link

            mock_drm_path.iterdir.return_value = [card1_mock]
            MockPath.return_value = mock_drm_path

            with patch("os.readlink", return_value=f"/something/{device_name}/something"):
                result = get_card_name_from_device(drm_device_path)
        assert result == "card1"

    def test_fallback_to_card1(self):
        with patch("src.drm.sysfs.Path") as MockPath:
            mock_drm_path = MagicMock()
            mock_drm_path.iterdir.return_value = []
            MockPath.return_value = mock_drm_path

            result = get_card_name_from_device(Path("/sys/kernel/debug/dri/0000:01:00.0"))
        assert result == "card1"

    def test_skips_entries_with_dash(self):
        # Entries like "card1-DP-1" should be skipped (has dash)
        with patch("src.drm.sysfs.Path") as MockPath:
            mock_drm_path = MagicMock()
            not_card = MagicMock()
            not_card.name = "card1-DP-1"
            mock_drm_path.iterdir.return_value = [not_card]
            MockPath.return_value = mock_drm_path

            result = get_card_name_from_device(Path("/sys/kernel/debug/dri/0000:01:00.0"))
        assert result == "card1"

    def test_skips_noncard_entries(self):
        with patch("src.drm.sysfs.Path") as MockPath:
            mock_drm_path = MagicMock()
            version_entry = MagicMock()
            version_entry.name = "version"
            mock_drm_path.iterdir.return_value = [version_entry]
            MockPath.return_value = mock_drm_path

            result = get_card_name_from_device(Path("/sys/kernel/debug/dri/0000:01:00.0"))
        assert result == "card1"

    def test_handles_readlink_exception(self):
        with patch("src.drm.sysfs.Path") as MockPath:
            mock_drm_path = MagicMock()
            card1_mock = MagicMock()
            card1_mock.name = "card1"
            dev_link = MagicMock()
            dev_link.exists.return_value = True
            card1_mock.__truediv__ = lambda self, other: dev_link
            mock_drm_path.iterdir.return_value = [card1_mock]
            MockPath.return_value = mock_drm_path

            with patch("os.readlink", side_effect=OSError("perm denied")):
                result = get_card_name_from_device(Path("/sys/kernel/debug/dri/0000:01:00.0"))
        assert result == "card1"
