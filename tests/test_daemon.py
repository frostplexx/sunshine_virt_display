"""Tests for src/daemon/daemon.py process watchers (logout / Sunshine exit)."""

import subprocess
import threading
from unittest.mock import patch

import pytest

from src.daemon import daemon


@pytest.fixture
def connected_state():
    with daemon._lock:
        saved = dict(daemon._state)
        daemon._state.update(connected=True, connect_args=(2868, 1320, 120, None))
    yield
    with daemon._lock:
        daemon._state.clear()
        daemon._state.update(saved)


def _exited_child() -> subprocess.Popen:
    proc = subprocess.Popen(["sleep", "30"])
    return proc


class TestWatchPid:
    def test_disconnects_when_watched_process_exits(self, connected_state):
        proc = _exited_child()
        with patch.object(daemon.display, "disconnect", return_value=True) as disc:
            t = threading.Thread(target=daemon._watch_pid, args=(proc.pid, "KWin"))
            t.start()
            proc.kill(); proc.wait()
            t.join(timeout=5)
        assert not t.is_alive()
        disc.assert_called_once()
        assert daemon._state["connected"] is False

    def test_no_disconnect_when_not_connected(self, connected_state):
        daemon._state["connected"] = False
        proc = _exited_child()
        with patch.object(daemon.display, "disconnect") as disc:
            t = threading.Thread(target=daemon._watch_pid, args=(proc.pid, "KWin"))
            t.start()
            proc.kill(); proc.wait()
            t.join(timeout=5)
        disc.assert_not_called()

    def test_logout_kwin_and_sunshine_exit_together_disconnects_once(self, connected_state):
        kwin_proc, sunshine_proc = _exited_child(), _exited_child()
        with patch.object(daemon.display, "disconnect", return_value=True) as disc:
            threads = [
                threading.Thread(target=daemon._watch_pid, args=(kwin_proc.pid, "KWin")),
                threading.Thread(target=daemon._watch_pid, args=(sunshine_proc.pid, "Sunshine")),
            ]
            for t in threads:
                t.start()
            for p in (kwin_proc, sunshine_proc):
                p.kill(); p.wait()
            for t in threads:
                t.join(timeout=5)
        disc.assert_called_once()

    def test_failed_disconnect_keeps_connected_for_retry(self, connected_state):
        # e.g. Sunshine died first while KWin was still tearing down: the
        # KWin watcher must still be able to finish the job afterwards.
        proc = _exited_child()
        with patch.object(daemon.display, "disconnect", return_value=False):
            t = threading.Thread(target=daemon._watch_pid, args=(proc.pid, "Sunshine"))
            t.start()
            proc.kill(); proc.wait()
            t.join(timeout=5)
        assert daemon._state["connected"] is True

    def test_unwatchable_pid_is_ignored(self, connected_state):
        with patch.object(daemon.display, "disconnect") as disc:
            daemon._watch_pid(2**22 + 12345, "KWin")
        disc.assert_not_called()


class TestHotplug:
    def test_recognises_drm_hotplug_uevent(self):
        msg = b"change@/devices/pci0000:00/0000:03:00.0/drm/card1\0ACTION=change\0SUBSYSTEM=drm\0HOTPLUG=1\0DEVNAME=dri/card1\0"
        assert daemon._is_drm_hotplug(msg)

    def test_ignores_other_uevents(self):
        assert not daemon._is_drm_hotplug(b"add@/devices/x\0ACTION=add\0SUBSYSTEM=input\0")
        assert not daemon._is_drm_hotplug(b"change@/x\0ACTION=change\0SUBSYSTEM=drm\0")

    def test_operations_mark_outputs_as_changing(self):
        seen = []
        with patch.object(daemon.display, "connect", side_effect=lambda *a, **k: seen.append(daemon._op_active.is_set()) or True), \
             patch.object(daemon.display, "disconnect", side_effect=lambda: seen.append(daemon._op_active.is_set()) or True):
            assert daemon._display_connect(1920, 1080, 60, device=None) is True
            assert daemon._display_disconnect() is True
        assert seen == [True, True]
        assert not daemon._op_active.is_set()

    def test_op_flag_cleared_even_if_operation_raises(self):
        with patch.object(daemon.display, "disconnect", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                daemon._display_disconnect()
        assert not daemon._op_active.is_set()
