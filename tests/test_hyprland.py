"""Tests for Hyprland-specific display helpers."""

import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from src.drm.de import hyprland


def _hyprctl_result(payload: object) -> CompletedProcess:
    return CompletedProcess(args="hyprctl", returncode=0, stdout=json.dumps(payload), stderr="")


def test_monitor_specs_uses_hyprctl_json_and_preserves_10_bit():
    monitors = [
        {
            "name": "DP-1",
            "width": 3440,
            "height": 1440,
            "refreshRate": 144.0,
            "x": 0,
            "y": 0,
            "scale": 1.0,
            "currentFormat": "XBGR2101010",
            "vrr": False,
        }
    ]

    with patch("src.drm.de.hyprland.hyprctl", return_value=_hyprctl_result(monitors)):
        assert hyprland.monitor_specs(["DP-1"]) == {
            "DP-1": {
                "output": "DP-1",
                "mode": "3440x1440@144.0",
                "position": "0x0",
                "scale": 1.0,
                "bitdepth": 10,
            }
        }


def test_monitor_specs_handles_8_bit_outputs():
    monitors = [
        {
            "name": "DP-2",
            "width": 1920,
            "height": 1200,
            "refreshRate": 59.95,
            "x": 3440,
            "y": 0,
            "scale": 1.0,
            "currentFormat": "XRGB8888",
            "vrr": False,
        }
    ]

    with patch("src.drm.de.hyprland.hyprctl", return_value=_hyprctl_result(monitors)):
        assert hyprland.monitor_specs(["DP-2"])["DP-2"]["bitdepth"] == 8


def test_monitor_specs_preserves_active_vrr_when_config_has_no_policy():
    monitors = [
        {
            "name": "DP-1",
            "width": 3440,
            "height": 1440,
            "refreshRate": 144.0,
            "x": 0,
            "y": 0,
            "scale": 1.0,
            "currentFormat": "XBGR2101010",
            "vrr": True,
        }
    ]

    with patch("src.drm.de.hyprland.hyprctl", return_value=_hyprctl_result(monitors)):
        assert hyprland.monitor_specs(["DP-1"])["DP-1"]["vrr"] == 1



def test_restore_outputs_includes_disabled_false_and_monitor_options():
    mock_eval = MagicMock(return_value=True)
    specs = {
        "DP-1": {
            "output": "DP-1",
            "mode": "3440x1440@144.0",
            "position": "0x0",
            "scale": 1.0,
            "bitdepth": 10,
            "vrr": 1,
        }
    }

    with patch("src.drm.de.hyprland.eval_monitor", mock_eval):
        assert hyprland.restore_outputs(specs) is True

    mock_eval.assert_called_once_with(
        {
            "output": "DP-1",
            "mode": "3440x1440@144.0",
            "position": "0x0",
            "scale": 1.0,
            "bitdepth": 10,
            "vrr": 1,
            "disabled": False,
        }
    )
