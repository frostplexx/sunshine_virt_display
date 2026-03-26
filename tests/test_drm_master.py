"""Tests for src/drm/drm_master.py"""

import ctypes
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import src.drm.drm_master as drm_master_module
from src.drm.drm_master import (
    _find_compositor_pid_and_fd,
    _pidfd_getfd,
    _pidfd_open,
    with_drm_master,
)


class TestPidfdOpen:
    def test_success(self):
        with patch.object(drm_master_module._libc, "syscall", return_value=5) as mock_sc:
            result = _pidfd_open(1234)
        assert result == 5

    def test_raises_on_negative_return(self):
        with patch.object(drm_master_module._libc, "syscall", return_value=-1):
            with patch("ctypes.get_errno", return_value=1):
                with pytest.raises(OSError):
                    _pidfd_open(1234)

    def test_passes_flags(self):
        with patch.object(drm_master_module._libc, "syscall", return_value=7) as mock_sc:
            result = _pidfd_open(999, flags=1)
        assert result == 7
        args = mock_sc.call_args[0]
        assert args[0] == drm_master_module._SYS_PIDFD_OPEN


class TestPidfdGetfd:
    def test_success(self):
        with patch.object(drm_master_module._libc, "syscall", return_value=10):
            result = _pidfd_getfd(5, 3)
        assert result == 10

    def test_raises_on_negative_return(self):
        with patch.object(drm_master_module._libc, "syscall", return_value=-1):
            with patch("ctypes.get_errno", return_value=13):
                with pytest.raises(OSError):
                    _pidfd_getfd(5, 3)

    def test_passes_correct_syscall_number(self):
        with patch.object(drm_master_module._libc, "syscall", return_value=10) as mock_sc:
            _pidfd_getfd(5, 3)
        args = mock_sc.call_args[0]
        assert args[0] == drm_master_module._SYS_PIDFD_GETFD


class TestFindCompositorPidAndFd:
    def test_returns_none_none_on_stat_failure(self):
        with patch("os.stat", side_effect=OSError("no device")):
            pid, fd = _find_compositor_pid_and_fd("/dev/dri/card1")
        assert pid is None
        assert fd is None

    def test_returns_none_none_when_no_candidates(self, capsys):
        with patch("os.stat") as mock_stat, \
             patch.object(Path, "iterdir", return_value=[]):
            mock_stat.return_value.st_rdev = 12345
            pid, fd = _find_compositor_pid_and_fd("/dev/dri/card1")
        assert pid is None
        assert fd is None

    def test_skips_own_pid(self, capsys):
        own_pid = os.getpid()
        proc_entry = MagicMock()
        proc_entry.name = str(own_pid)

        with patch("os.stat") as mock_stat, \
             patch.object(Path, "iterdir", return_value=[proc_entry]) as mock_iter:
            mock_stat.return_value.st_rdev = 12345
            pid, fd = _find_compositor_pid_and_fd("/dev/dri/card1")

        assert pid is None

    def test_skips_non_numeric_proc_entries(self, capsys):
        entry = MagicMock()
        entry.name = "self"

        with patch("os.stat") as mock_stat, \
             patch.object(Path, "iterdir", return_value=[entry]):
            mock_stat.return_value.st_rdev = 12345
            pid, fd = _find_compositor_pid_and_fd("/dev/dri/card1")

        assert pid is None

    def test_finds_compositor_when_drop_master_succeeds(self, capsys):
        card_rdev = 12345
        comp_pid = 9999
        comp_fd = 7

        # Fake /proc entry for compositor
        fd_entry = MagicMock()
        fd_entry.name = str(comp_fd)

        proc_entry = MagicMock()
        proc_entry.name = str(comp_pid)
        fd_dir = MagicMock()
        fd_dir.iterdir.return_value = [fd_entry]
        proc_entry.__truediv__ = lambda self, other: fd_dir

        with patch("os.stat") as mock_stat, \
             patch("os.getpid", return_value=1), \
             patch.object(Path, "iterdir", return_value=[proc_entry]), \
             patch("src.drm.drm_master._pidfd_open", return_value=50) as mock_open, \
             patch("src.drm.drm_master._pidfd_getfd", return_value=51) as mock_getfd, \
             patch("os.close") as mock_close, \
             patch("fcntl.ioctl", return_value=0), \
             patch.object(Path, "read_text", return_value="kwin_wayland"):

            def stat_side(path, **kw):
                s = MagicMock()
                s.st_rdev = card_rdev
                return s

            mock_stat.side_effect = stat_side

            result_pid, result_fd = _find_compositor_pid_and_fd("/dev/dri/card1")

        assert result_pid == comp_pid
        assert result_fd == comp_fd

    def test_skips_candidate_when_pidfd_open_fails(self, capsys):
        fd_entry = MagicMock()
        fd_entry.name = "5"

        proc_entry = MagicMock()
        proc_entry.name = "8888"
        fd_dir = MagicMock()
        fd_dir.iterdir.return_value = [fd_entry]
        proc_entry.__truediv__ = lambda self, other: fd_dir

        with patch("os.stat") as mock_stat, \
             patch("os.getpid", return_value=1), \
             patch.object(Path, "iterdir", return_value=[proc_entry]), \
             patch("src.drm.drm_master._pidfd_open", side_effect=OSError("denied")):

            mock_stat.return_value.st_rdev = 12345

            result_pid, result_fd = _find_compositor_pid_and_fd("/dev/dri/card1")

        assert result_pid is None

    def test_skips_candidate_when_ioctl_drop_fails(self, capsys):
        fd_entry = MagicMock()
        fd_entry.name = "5"

        proc_entry = MagicMock()
        proc_entry.name = "8888"
        fd_dir = MagicMock()
        fd_dir.iterdir.return_value = [fd_entry]
        proc_entry.__truediv__ = lambda self, other: fd_dir

        with patch("os.stat") as mock_stat, \
             patch("os.getpid", return_value=1), \
             patch.object(Path, "iterdir", return_value=[proc_entry]), \
             patch("src.drm.drm_master._pidfd_open", return_value=50), \
             patch("src.drm.drm_master._pidfd_getfd", return_value=51), \
             patch("os.close"), \
             patch("fcntl.ioctl", side_effect=OSError("not master")), \
             patch.object(Path, "read_text", return_value="kwin"):

            mock_stat.return_value.st_rdev = 12345

            result_pid, result_fd = _find_compositor_pid_and_fd("/dev/dri/card1")

        assert result_pid is None

    def test_handles_permission_error_in_fd_dir(self, capsys):
        proc_entry = MagicMock()
        proc_entry.name = "7777"
        fd_dir = MagicMock()
        fd_dir.iterdir.side_effect = PermissionError("denied")
        proc_entry.__truediv__ = lambda self, other: fd_dir

        with patch("os.stat") as mock_stat, \
             patch("os.getpid", return_value=1), \
             patch.object(Path, "iterdir", return_value=[proc_entry]):
            mock_stat.return_value.st_rdev = 12345
            result_pid, result_fd = _find_compositor_pid_and_fd("/dev/dri/card1")

        assert result_pid is None

    def test_handles_comm_read_failure(self, capsys):
        """When /proc/pid/comm can't be read, comm defaults to '?'"""
        fd_entry = MagicMock()
        fd_entry.name = "5"

        proc_entry = MagicMock()
        proc_entry.name = "8888"
        fd_dir = MagicMock()
        fd_dir.iterdir.return_value = [fd_entry]
        proc_entry.__truediv__ = lambda self, other: fd_dir

        with patch("os.stat") as mock_stat, \
             patch("os.getpid", return_value=1), \
             patch.object(Path, "iterdir", return_value=[proc_entry]), \
             patch("src.drm.drm_master._pidfd_open", return_value=50), \
             patch("src.drm.drm_master._pidfd_getfd", return_value=51), \
             patch("os.close"), \
             patch("fcntl.ioctl", return_value=0), \
             patch.object(Path, "read_text", side_effect=OSError("no comm")):

            mock_stat.return_value.st_rdev = 12345
            result_pid, result_fd = _find_compositor_pid_and_fd("/dev/dri/card1")

        # comm fallback is "?" — function should still work
        assert result_pid == 8888


class TestWithDrmMaster:
    def test_direct_acquisition_success(self):
        callback = MagicMock(return_value=42)

        with patch("os.open", return_value=10) as mock_open, \
             patch("os.close") as mock_close, \
             patch("fcntl.ioctl", return_value=0) as mock_ioctl:
            result = with_drm_master("/dev/dri/card1", callback)

        assert result == 42
        callback.assert_called_once_with(10)

    def test_direct_acquisition_drop_master_error_ignored(self):
        callback = MagicMock(return_value=99)
        ioctl_calls = [0]  # first call SET_MASTER succeeds

        def ioctl_side(fd, req, arg=0):
            if req == drm_master_module.DRM_IOCTL_DROP_MASTER:
                raise OSError("can't drop")
            return 0

        with patch("os.open", return_value=10), \
             patch("os.close"), \
             patch("fcntl.ioctl", side_effect=ioctl_side):
            result = with_drm_master("/dev/dri/card1", callback)

        assert result == 99

    def test_falls_back_to_pidfd_when_set_master_fails(self, capsys):
        callback = MagicMock(return_value=77)

        set_master_count = [0]

        def ioctl_side(fd, req, arg=0):
            if req == drm_master_module.DRM_IOCTL_SET_MASTER:
                set_master_count[0] += 1
                if set_master_count[0] == 1:
                    raise OSError("compositor holds master")
                return 0  # second SET_MASTER (our own fd) succeeds
            return 0  # DROP_MASTER always succeeds

        open_count = [0]

        def open_side(path, flags):
            open_count[0] += 1
            return 10 + open_count[0]

        with patch("os.open", side_effect=open_side), \
             patch("os.close"), \
             patch("fcntl.ioctl", side_effect=ioctl_side), \
             patch("src.drm.drm_master._find_compositor_pid_and_fd", return_value=(1234, 5)), \
             patch("src.drm.drm_master._pidfd_open", return_value=20), \
             patch("src.drm.drm_master._pidfd_getfd", return_value=30):
            result = with_drm_master("/dev/dri/card1", callback)

        assert result == 77

    def test_raises_when_no_compositor_found(self):
        def ioctl_side(fd, req, arg=0):
            if req == drm_master_module.DRM_IOCTL_SET_MASTER:
                raise OSError("compositor holds master")
            return 0

        with patch("os.open", return_value=10), \
             patch("os.close"), \
             patch("fcntl.ioctl", side_effect=ioctl_side), \
             patch("src.drm.drm_master._find_compositor_pid_and_fd", return_value=(None, None)):
            with pytest.raises(RuntimeError, match="Could not find"):
                with_drm_master("/dev/dri/card1", lambda fd: None)

    def test_restores_compositor_master_after_callback(self, capsys):
        callback = MagicMock(return_value=1)
        set_master_count = [0]
        ioctl_log = []

        def ioctl_side(fd, req, arg=0):
            ioctl_log.append((fd, req))
            if req == drm_master_module.DRM_IOCTL_SET_MASTER:
                set_master_count[0] += 1
                if set_master_count[0] == 1:
                    raise OSError("compositor holds master")
            return 0

        open_count = [0]

        def open_side(path, flags):
            open_count[0] += 1
            return open_count[0]

        with patch("os.open", side_effect=open_side), \
             patch("os.close"), \
             patch("fcntl.ioctl", side_effect=ioctl_side), \
             patch("src.drm.drm_master._find_compositor_pid_and_fd", return_value=(1234, 5)), \
             patch("src.drm.drm_master._pidfd_open", return_value=20), \
             patch("src.drm.drm_master._pidfd_getfd", return_value=30):
            with_drm_master("/dev/dri/card1", callback)

        # Verify SET_MASTER was called on stolen_fd (fd=30) to restore compositor
        restore_calls = [(fd, req) for fd, req in ioctl_log if fd == 30 and req == drm_master_module.DRM_IOCTL_SET_MASTER]
        assert len(restore_calls) >= 1

    def test_restore_failure_is_warned_not_raised(self, capsys):
        callback = MagicMock(return_value=5)
        set_master_count = [0]

        def ioctl_side(fd, req, arg=0):
            if req == drm_master_module.DRM_IOCTL_SET_MASTER:
                set_master_count[0] += 1
                if set_master_count[0] == 1:
                    raise OSError("compositor holds master")
                if fd == 30:  # restoring compositor — fail
                    raise OSError("restore failed")
            return 0

        open_count = [0]

        def open_side(path, flags):
            open_count[0] += 1
            return open_count[0]

        with patch("os.open", side_effect=open_side), \
             patch("os.close"), \
             patch("fcntl.ioctl", side_effect=ioctl_side), \
             patch("src.drm.drm_master._find_compositor_pid_and_fd", return_value=(1234, 5)), \
             patch("src.drm.drm_master._pidfd_open", return_value=20), \
             patch("src.drm.drm_master._pidfd_getfd", return_value=30):
            result = with_drm_master("/dev/dri/card1", callback)

        assert result == 5
        assert "Warning" in capsys.readouterr().out

    def test_open_exception_propagates(self):
        with patch("os.open", side_effect=OSError("no such file")):
            with pytest.raises(OSError):
                with_drm_master("/dev/dri/card99", lambda fd: None)
