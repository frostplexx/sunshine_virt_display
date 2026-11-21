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
        assert specs["HDMI-A-2"] == {"output": "HDMI-A-2", "enabled": True,
                                     "width": 3440, "height": 1440,
                                     "refresh": 99.98, "position": "1920,0",
                                     "scale": 1.25, "priority": 1, "rotation": "none"}
        assert specs["eDP-1"]["rotation"] == "left"
        assert specs["eDP-1"]["priority"] == 2
        assert specs["eDP-1"]["enabled"] is True

    def test_monitor_specs_records_disabled_outputs(self):
        # Regression: a connected output that the user disabled in KWin must
        # not abort the connect, and must stay disabled after disconnect.
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(out=_KSCREEN_JSON)):
            assert kwin.monitor_specs(["DP-2"]) == {"DP-2": {"output": "DP-2", "enabled": False}}

    def test_monitor_specs_skips_unrequested_outputs(self):
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(out=_KSCREEN_JSON)):
            assert kwin.monitor_specs(["HDMI-A-9"]) == {}

    @pytest.mark.parametrize("rotation,keyword", [
        (16, "flipped"), (32, "flipped90"), (64, "flipped180"), (128, "flipped270"),
    ])
    def test_monitor_specs_keeps_flipped_rotations(self, rotation, keyword):
        data = json.dumps({"outputs": [{
            "name": "DP-1", "enabled": True, "currentModeId": "1",
            "modes": [{"id": "1", "refreshRate": 60.0, "size": {"width": 1920, "height": 1080}}],
            "pos": {"x": 0, "y": 0}, "scale": 1, "priority": 1, "rotation": rotation,
        }]})
        with patch("src.drm.de.kwin.kscreen_doctor", return_value=_cp(out=data)):
            specs = kwin.monitor_specs(["DP-1"])
        assert specs["DP-1"]["rotation"] == keyword

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

    def test_restore_skips_disabled_outputs(self):
        disabled = {"DP-2": {"output": "DP-2", "enabled": False}}
        with patch("src.drm.de.kwin.kscreen_doctor") as kd:
            assert kwin.restore_outputs(disabled) is True
        kd.assert_not_called()

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


class TestTouchMapping:
    DEVICES = [
        {"sysname": "event8", "name": "libvirtualhid Keyboard", "touch": False, "tablet": False, "output": ""},
        {"sysname": "event11", "name": "libvirtualhid Mouse (Absolute)", "touch": False, "tablet": False, "output": ""},
        {"sysname": "event12", "name": "libvirtualhid Touchscreen", "touch": True, "tablet": False, "output": ""},
        {"sysname": "event13", "name": "libvirtualhid Pen Tablet", "touch": False, "tablet": True, "output": ""},
        {"sysname": "event14", "name": "ELAN Touchscreen", "touch": True, "tablet": False, "output": ""},
        {"sysname": "event15", "name": "Touch passthrough", "touch": True, "tablet": False, "output": ""},
    ]

    def test_only_sunshine_touch_and_pen_match(self):
        matched = [d["sysname"] for d in self.DEVICES if kwin._is_sunshine_pointer_device(d)]
        # a real built-in touchscreen (ELAN) and keyboards/mice are left alone
        assert matched == ["event12", "event13", "event15"]

    def test_map_virtual_input_maps_each_device_once(self):
        with patch("src.drm.de.kwin.input_devices", return_value=self.DEVICES), \
             patch("src.drm.de.kwin.set_device_output", return_value=True) as setter:
            n = kwin.map_virtual_input("DP-1", timeout=0.05, interval=0.01)
        assert n == 3
        assert sorted(c.args for c in setter.call_args_list) == [
            ("event12", "DP-1"), ("event13", "DP-1"), ("event15", "DP-1")]

    def test_map_virtual_input_picks_up_late_devices(self):
        calls = {"n": 0}
        def devices():
            calls["n"] += 1
            return self.DEVICES[:2] if calls["n"] < 3 else self.DEVICES[:3]
        with patch("src.drm.de.kwin.input_devices", side_effect=devices), \
             patch("src.drm.de.kwin.set_device_output", return_value=True) as setter:
            n = kwin.map_virtual_input("DP-1", timeout=0.2, interval=0.01)
        assert n == 1
        setter.assert_called_once_with("event12", "DP-1")

    def test_stop_input_mapping_resets_only_our_mapped_devices(self):
        devs = [dict(d, output="DP-1") for d in self.DEVICES]
        with patch("src.drm.de.kwin.input_devices", return_value=devs), \
             patch("src.drm.de.kwin.set_device_output", return_value=True) as setter:
            kwin.stop_input_mapping()
        assert sorted(c.args for c in setter.call_args_list) == [
            ("event12", ""), ("event13", ""), ("event15", "")]

    def test_set_device_output_uses_kwin_dbus(self):
        with patch("src.drm.de.kwin._run_in_session", return_value=_cp()) as run:
            assert kwin.set_device_output("event12", "DP-1") is True
        assert run.call_args[0][0] == ["busctl", "--user", "set-property", "org.kde.KWin",
                                       "/org/kde/KWin/InputDevice/event12", "org.kde.KWin.InputDevice",
                                       "outputName", "s", "DP-1"]

    def test_input_devices_parses_busctl_json(self):
        values = {
            "devicesSysNames": ["event12"], "name": "libvirtualhid Touchscreen",
            "touch": True, "tabletTool": False, "outputName": "",
        }
        def fake(cmd):
            return _cp(out=json.dumps({"type": "x", "data": values[cmd[-1]]}))
        with patch("src.drm.de.kwin._run_in_session", side_effect=fake):
            assert kwin.input_devices() == [{"sysname": "event12", "name": "libvirtualhid Touchscreen",
                                             "touch": True, "tablet": False, "output": ""}]


class TestVirtualKeyboardRestart:
    PROCS = [
        (1359, "kwin_wayland", 1346),
        (44326, "maliit-keyboard", 1359),    # started by KWin -> restart
        (50000, "maliit-keyboard", 2000),    # started by something else -> leave alone
        (50001, "plasma-keyboard", 1359),    # Plasma's newer keyboard, KWin-managed
        (50002, "plasmashell", 1),
    ]

    def test_only_kwin_managed_keyboards_are_restarted(self):
        with patch("src.drm.de.kwin._processes", return_value=self.PROCS), \
             patch("os.kill") as kill:
            assert kwin.restart_virtual_keyboard() == [44326, 50001]
        import signal
        assert sorted(c.args for c in kill.call_args_list) == [(44326, signal.SIGTERM), (50001, signal.SIGTERM)]

    def test_no_kwin_means_nothing_killed(self):
        procs = [p for p in self.PROCS if p[1] != "kwin_wayland"]
        with patch("src.drm.de.kwin._processes", return_value=procs), patch("os.kill") as kill:
            assert kwin.restart_virtual_keyboard() == []
        kill.assert_not_called()

    def test_kill_failure_is_non_fatal(self):
        with patch("src.drm.de.kwin._processes", return_value=self.PROCS[:2]), \
             patch("os.kill", side_effect=PermissionError("nope")):
            assert kwin.restart_virtual_keyboard() == []

    def test_restart_later_waits_then_restarts(self):
        with patch("src.drm.de.kwin.restart_virtual_keyboard") as restart, \
             patch("src.drm.de.kwin.time.sleep") as sleep:
            kwin.restart_virtual_keyboard_later(delay=1.5).join(timeout=2)
        sleep.assert_called_once_with(1.5)
        restart.assert_called_once()

    def test_processes_reads_proc(self):
        procs = kwin._processes()
        me = [p for p in procs if p[0] == os.getpid()]
        assert me and me[0][2] == os.getppid()


class TestKwinSessionAlive:
    def test_find_kwin_pid(self):
        with patch("src.drm.de.kwin._processes", return_value=[(10, "bash", 1), (1359, "kwin_wayland", 1346)]):
            assert kwin.find_kwin_pid() == 1359
            assert kwin.session_alive() is True

    def test_no_kwin_after_logout(self):
        with patch("src.drm.de.kwin._processes", return_value=[(10, "bash", 1), (11, "sddm", 1)]):
            assert kwin.find_kwin_pid() is None
            assert kwin.session_alive() is False
