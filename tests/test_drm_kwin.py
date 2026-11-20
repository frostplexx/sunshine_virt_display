"""Tests for src/drm/de/kwin.py"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.drm.de.kwin import clear_kwin_output_config


class TestClearKwinOutputConfig:
    def test_no_sudo_user_returns_early(self):
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise, just return
            clear_kwin_output_config("DP-1")

    def test_unknown_sudo_user_returns_early(self):
        import pwd
        with patch.dict(os.environ, {"SUDO_USER": "nonexistent_user_xyz"}):
            with patch("pwd.getpwnam", side_effect=KeyError("not found")):
                clear_kwin_output_config("DP-1")  # should not raise

    def test_missing_config_file_returns_early(self, tmp_path):
        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                # No kwinoutputconfig.json in tmp_path
                clear_kwin_output_config("DP-1")  # should not raise

    def test_removes_port_from_list_format(self, tmp_path, capsys):
        config = [
            {"name": "DP-1", "res": "1920x1080"},
            {"name": "DP-2", "res": "2560x1440"},
        ]
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        remaining = json.loads(config_file.read_text())
        assert len(remaining) == 1
        assert remaining[0]["name"] == "DP-2"
        assert "Cleared" in capsys.readouterr().out

    def test_no_match_in_list_format(self, tmp_path, capsys):
        config = [{"name": "DP-2", "res": "2560x1440"}]
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        assert "No stale" in capsys.readouterr().out

    def test_removes_port_from_dict_format(self, tmp_path, capsys):
        config = {
            "outputs": [
                {"name": "DP-1", "res": "1920x1080"},
                {"name": "HDMI-1", "res": "1280x720"},
            ]
        }
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        result = json.loads(config_file.read_text())
        assert len(result["outputs"]) == 1
        assert result["outputs"][0]["name"] == "HDMI-1"
        assert "Cleared" in capsys.readouterr().out

    def test_no_match_in_dict_format(self, tmp_path, capsys):
        config = {"outputs": [{"name": "HDMI-1", "res": "1280x720"}]}
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        assert "No stale" in capsys.readouterr().out

    def test_handles_json_parse_error(self, tmp_path, capsys):
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text("not valid json{{{")

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        assert "Warning" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# kscreen-doctor backend (issue #31)
# ---------------------------------------------------------------------------

from subprocess import CompletedProcess  # noqa: E402

from src.drm.de import kwin  # noqa: E402

_KSCREEN_JSON = json.dumps({"outputs": [
    {"id": 1, "name": "HDMI-A-2", "enabled": True, "connected": True, "currentModeId": "3",
     "modes": [{"id": "1", "name": "3840x2160@60", "refreshRate": 60.0, "size": {"width": 3840, "height": 2160}},
               {"id": "3", "name": "3440x1440@100", "refreshRate": 99.98, "size": {"width": 3440, "height": 1440}},
               {"id": "4", "name": "3440x1440@50", "refreshRate": 49.99, "size": {"width": 3440, "height": 1440}}],
     "pos": {"x": 1920, "y": 0}, "scale": 1.25, "priority": 1, "rotation": 1},
    {"id": 2, "name": "DP-2", "enabled": False, "connected": True, "currentModeId": "1",
     "pos": {"x": 0, "y": 0}, "scale": 1, "priority": 0, "rotation": 1},
    {"id": 3, "name": "eDP-1", "enabled": True, "connected": True, "currentModeId": "7",
     "modes": [{"id": "7", "name": "2560x1600@120", "refreshRate": 120.0, "size": {"width": 2560, "height": 1600}}],
     "pos": {"x": 0, "y": 0}, "scale": 2, "priority": 2, "rotation": 2},
]})


def _cp(rc=0, out="", err=""):
    return CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


class TestKscreenDoctorBackend:
    def test_monitor_specs_captures_restore_state(self):
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(out=_KSCREEN_JSON)):
            specs = kwin.monitor_specs(["HDMI-A-2", "eDP-1"])
        assert specs["HDMI-A-2"] == {"output": "HDMI-A-2", "width": 3440, "height": 1440,
                                     "refresh": 99.98, "position": "1920,0",
                                     "scale": 1.25, "priority": 1, "rotation": "none"}
        assert specs["eDP-1"]["rotation"] == "left"
        assert specs["eDP-1"]["priority"] == 2

    def test_monitor_specs_skips_disabled_and_unrequested(self):
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(out=_KSCREEN_JSON)):
            assert kwin.monitor_specs(["DP-2"]) == {}

    def test_available_false_without_session(self):
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=None):
            assert kwin.available() is False

    def test_available_false_on_bad_json(self):
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(out="not json")):
            assert kwin.available() is False

    def test_available_true(self):
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(out=_KSCREEN_JSON)):
            assert kwin.available() is True

    def test_disable_outputs_is_one_atomic_call(self):
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp()) as kd:
            assert kwin.disable_outputs(["HDMI-A-2", "eDP-1"]) is True
        kd.assert_called_once_with(["output.HDMI-A-2.disable", "output.eDP-1.disable"])

    def test_disable_outputs_failure(self):
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(rc=1, err="boom")):
            assert kwin.disable_outputs(["HDMI-A-2"]) is False

    def test_restore_outputs_builds_full_command(self):
        spec = {"output": "HDMI-A-2", "width": 3440, "height": 1440, "refresh": 99.98,
                "position": "1920,0", "scale": 1.25, "priority": 1, "rotation": "none"}
        with patch("src.drm.de.kwin._outputs", return_value=json.loads(_KSCREEN_JSON)["outputs"]), \
             patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp()) as kd:
            assert kwin.restore_outputs({"HDMI-A-2": spec}) is True
        kd.assert_called_once_with([
            "output.HDMI-A-2.enable", "output.HDMI-A-2.mode.3",
            "output.HDMI-A-2.position.1920,0", "output.HDMI-A-2.scale.1.25",
            "output.HDMI-A-2.rotation.none", "output.HDMI-A-2.priority.1",
        ])

    def test_restore_resolves_renumbered_mode_ids(self):
        # Regression: KWin renumbered mode ids after the virtual output appeared,
        # so a saved id "6" (3440x1440@100) restored as 3840x2160@30.
        spec = {"output": "HDMI-A-1", "width": 3440, "height": 1440, "refresh": 100.0,
                "position": "0,0", "scale": 2}
        renumbered = [{"name": "HDMI-A-1", "modes": [
            {"id": "1", "refreshRate": 49.99, "size": {"width": 3440, "height": 1440}},
            {"id": "6", "refreshRate": 29.97, "size": {"width": 3840, "height": 2160}},
            {"id": "9", "refreshRate": 99.98, "size": {"width": 3440, "height": 1440}},
        ]}]
        with patch("src.drm.de.kwin._outputs", return_value=renumbered), \
             patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp()) as kd:
            kwin.restore_outputs({"HDMI-A-1": spec})
        assert "output.HDMI-A-1.mode.9" in kd.call_args[0][0]

    def test_restore_falls_back_to_mode_name(self):
        spec = {"output": "HDMI-A-1", "width": 3440, "height": 1440, "refresh": 99.98,
                "position": "0,0", "scale": 2}
        with patch("src.drm.de.kwin._outputs", return_value=None), \
             patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp()) as kd:
            kwin.restore_outputs({"HDMI-A-1": spec})
        assert "output.HDMI-A-1.mode.3440x1440@100" in kd.call_args[0][0]

    def test_restore_legacy_spec_with_mode_id(self):
        spec = {"output": "HDMI-A-1", "mode": "6", "position": "0,0", "scale": 2}
        with patch("src.drm.de.kwin._outputs", return_value=[]), \
             patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp()) as kd:
            kwin.restore_outputs({"HDMI-A-1": spec})
        assert "output.HDMI-A-1.mode.6" in kd.call_args[0][0]

    def test_restore_outputs_failure_when_no_session(self):
        spec = {"output": "HDMI-A-2", "width": 3440, "height": 1440, "refresh": 100.0,
                "position": "0,0", "scale": 1}
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=None):
            assert kwin.restore_outputs({"HDMI-A-2": spec}) is False

    def test_kscreen_doctor_runs_as_session_user_when_root(self):
        session = {"user": "alice", "XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-0"}
        with patch("shutil.which", return_value="/usr/bin/kscreen-doctor"), \
             patch("src.drm.de.kwin.find_session", return_value=session), \
             patch("os.geteuid", return_value=0), \
             patch("subprocess.run", return_value=_cp()) as run:
            kwin.kscreen_doctor(["-j"])
        cmd = run.call_args[0][0]
        assert cmd[:4] == ["runuser", "-u", "alice", "--"]
        assert "WAYLAND_DISPLAY=wayland-0" in cmd
        assert cmd[-2:] == ["kscreen-doctor", "-j"]

    def test_kscreen_doctor_missing_binary(self):
        with patch("shutil.which", return_value=None):
            assert kwin.kscreen_doctor(["-j"]) is None


class TestKwinSessionDiscovery:
    def test_empty_outputs_means_unavailable(self):
        # kscreen-doctor exits 0 with no outputs when it can't reach KWin
        empty = json.dumps({"outputs": [], "screen": {}})
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(out=empty)):
            assert kwin.available() is False

    def test_wayland_display_from_kwin_env_wins(self, tmp_path):
        assert kwin._find_wayland_display(1000, str(tmp_path), {"WAYLAND_DISPLAY": "wayland-3"}) == "wayland-3"

    def test_wayland_display_falls_back_to_runtime_socket(self, tmp_path):
        # kwin_wayland's own environ has no WAYLAND_DISPLAY (wrapper passes the fd);
        # with no session client found, use the real socket — not a guessed wayland-0
        import socket
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(tmp_path / "wayland-1"))
        (tmp_path / "wayland-1.lock").write_text("")
        try:
            with patch("pathlib.Path.iterdir", return_value=iter([])):
                assert kwin._find_wayland_display(1000, str(tmp_path), {}) == "wayland-1"
        finally:
            sock.close()

    def test_no_socket_returns_none(self, tmp_path):
        with patch("pathlib.Path.iterdir", return_value=iter([])):
            assert kwin._find_wayland_display(1000, str(tmp_path), {}) is None
