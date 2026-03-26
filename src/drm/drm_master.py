"""
DRM master acquisition and release via Linux pidfd syscalls.

Allows temporarily borrowing DRM master from a running compositor,
performing an operation, then restoring it.
"""

import ctypes
import ctypes.util
import fcntl
import os
from pathlib import Path

from src.drm.bindings import DRM_IOCTL_DROP_MASTER, DRM_IOCTL_SET_MASTER

# ---------------------------------------------------------------------------
# Syscall wrappers (x86_64)
# ---------------------------------------------------------------------------

_SYS_PIDFD_OPEN = 434
_SYS_PIDFD_GETFD = 438

_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.syscall.restype = ctypes.c_long


def _pidfd_open(pid, flags=0):
    rc = _libc.syscall(_SYS_PIDFD_OPEN, ctypes.c_int(pid), ctypes.c_uint(flags))
    if rc < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"pidfd_open({pid}): {os.strerror(errno)}")
    return rc


def _pidfd_getfd(pidfd, targetfd, flags=0):
    rc = _libc.syscall(
        _SYS_PIDFD_GETFD,
        ctypes.c_int(pidfd),
        ctypes.c_int(targetfd),
        ctypes.c_uint(flags),
    )
    if rc < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"pidfd_getfd({targetfd}): {os.strerror(errno)}")
    return rc


# ---------------------------------------------------------------------------
# Compositor detection
# ---------------------------------------------------------------------------


def _find_compositor_pid_and_fd(card_path):
    """
    Find the process that holds DRM master for the given card device.
    Scans /proc for processes with the card open, then tests each by
    attempting DROP_MASTER via pidfd_getfd to confirm it's the real master.
    Returns (pid, fd_number) or (None, None).
    """
    try:
        card_rdev = os.stat(card_path).st_rdev
    except OSError:
        return None, None

    # Collect all (pid, fd_num) candidates
    candidates = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if pid == os.getpid():
            continue
        fd_dir = proc / "fd"
        try:
            for entry in fd_dir.iterdir():
                try:
                    st = os.stat(str(entry))
                    if st.st_rdev == card_rdev:
                        candidates.append((pid, int(entry.name)))
                except (OSError, ValueError):
                    continue
        except (OSError, PermissionError):
            continue

    print(f"    Scanning for DRM master holder ({len(candidates)} candidate fds)")

    # Test each candidate — the real DRM master holder is the one where
    # DROP_MASTER succeeds on their duplicated fd.
    for pid, fd_num in candidates:
        try:
            try:
                comm = Path(f"/proc/{pid}/comm").read_text().strip()
            except OSError:
                comm = "?"

            pidfd = _pidfd_open(pid)
            try:
                dup_fd = _pidfd_getfd(pidfd, fd_num)
            finally:
                os.close(pidfd)
            try:
                fcntl.ioctl(dup_fd, DRM_IOCTL_DROP_MASTER, 0)
                # It worked — restore master and return this candidate
                fcntl.ioctl(dup_fd, DRM_IOCTL_SET_MASTER, 0)
                os.close(dup_fd)
                print(f"    Found DRM master: PID {pid} ({comm}) fd {fd_num}")
                return pid, fd_num
            except OSError:
                os.close(dup_fd)
        except OSError:
            continue

    print("    No DRM master holder found")
    return None, None


# ---------------------------------------------------------------------------
# Master borrowing context
# ---------------------------------------------------------------------------


def _with_drm_master(card_path, callback):
    """
    Temporarily acquire DRM master, run callback(fd), then restore master
    to the original holder (compositor).

    Uses pidfd_getfd to duplicate the compositor's DRM fd so we can
    drop/restore their master status.
    """
    # First try the simple path — maybe no compositor is running
    print(f"    Attempting direct DRM master acquisition on {card_path}")
    our_fd = os.open(card_path, os.O_RDWR | os.O_CLOEXEC)
    try:
        try:
            fcntl.ioctl(our_fd, DRM_IOCTL_SET_MASTER, 0)
            print("    Direct SET_MASTER succeeded (no compositor holding master)")
            try:
                return callback(our_fd)
            finally:
                try:
                    fcntl.ioctl(our_fd, DRM_IOCTL_DROP_MASTER, 0)
                except OSError:
                    pass
        except OSError as e:
            print(f"    Direct SET_MASTER failed: {e} -- using pidfd path")
    except Exception:
        os.close(our_fd)
        raise

    os.close(our_fd)

    # Find the compositor's DRM fd
    comp_pid, comp_fd_num = _find_compositor_pid_and_fd(card_path)
    if comp_pid is None:
        raise RuntimeError("Could not find process holding DRM master")

    print(f"    Borrowing DRM master from PID {comp_pid} (fd {comp_fd_num})")

    # Duplicate the compositor's fd via pidfd_getfd (shares the same drm_file)
    pidfd = _pidfd_open(comp_pid)
    try:
        stolen_fd = _pidfd_getfd(pidfd, comp_fd_num)
    finally:
        os.close(pidfd)

    try:
        # Drop master on the compositor's drm_file
        print("    Dropping compositor's DRM master...")
        fcntl.ioctl(stolen_fd, DRM_IOCTL_DROP_MASTER, 0)
        print("    Compositor master dropped, acquiring our own...")

        # Now open our own fd and acquire master
        our_fd = os.open(card_path, os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.ioctl(our_fd, DRM_IOCTL_SET_MASTER, 0)
            print("    DRM master acquired successfully")
            try:
                return callback(our_fd)
            finally:
                # Drop our master
                try:
                    fcntl.ioctl(our_fd, DRM_IOCTL_DROP_MASTER, 0)
                except OSError:
                    pass
        finally:
            os.close(our_fd)
    finally:
        # Restore master to compositor
        print("    Restoring DRM master to compositor...")
        try:
            fcntl.ioctl(stolen_fd, DRM_IOCTL_SET_MASTER, 0)
            print("    Compositor master restored")
        except OSError as e:
            print(f"    Warning: could not restore compositor master: {e}")
        os.close(stolen_fd)
