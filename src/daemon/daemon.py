#!/usr/bin/env python3
"""Sunshine Virtual Display Daemon — manages virtual displays via Unix socket."""

import argparse
import logging
import os
import select
import signal
import socket
import sys
import threading
import time
from pathlib import Path

from jeepney import DBusAddress, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection
from jeepney.low_level import HeaderFields

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import display
from src.drm.de import kwin

log = logging.getLogger(__name__)

SOCKET_FILE = "/tmp/sunshineVD.sock"
SUNSHINE_UNIT_PATH = "/org/freedesktop/systemd1/unit/sunshine_2eservice"

_lock = threading.Lock()
_watch_disconnect_lock = threading.Lock()
_op_active = threading.Event()   # set while connect/disconnect is changing outputs
_state: dict = {
    "connected": False,
    "connect_args": None,       # (width, height, refresh_rate, device)
    "sleep_was_connected": False,
}
_server: socket.socket | None = None
_inhibitor_fd: int | None = None
_running = True


# ---------------------------------------------------------------------------
# Sleep inhibitor (systemd logind delay lock)
# ---------------------------------------------------------------------------

def _acquire_inhibitor() -> int | None:
    try:
        conn = open_dbus_connection(bus="SYSTEM")
        addr = DBusAddress(
            "/org/freedesktop/login1",
            bus_name="org.freedesktop.login1",
            interface="org.freedesktop.login1.Manager",
        )
        msg = new_method_call(
            addr,
            "Inhibit",
            "ssss",
            ("sleep", "sunshineVD", "Disconnect virtual display before sleep", "delay"),
        )
        reply = conn.send_and_get_reply(msg)
        # reply.body[0] is a jeepney.wrappers.UnixFd; .fileno() gives the raw fd
        raw_fd = reply.body[0].fileno()
        # Duplicate so the jeepney connection closing doesn't steal the fd
        owned_fd = os.dup(raw_fd)
        conn.close()
        log.info("Acquired sleep inhibitor lock (fd=%d)", owned_fd)
        return owned_fd
    except ImportError:
        log.warning("jeepney not installed — sleep inhibitor disabled")
        return None
    except Exception as exc:
        log.warning("Could not acquire sleep inhibitor: %s", exc)
        return None


def _release_inhibitor() -> None:
    global _inhibitor_fd
    if _inhibitor_fd is not None:
        try:
            os.close(_inhibitor_fd)
            log.info("Released sleep inhibitor lock")
        except OSError:
            pass
        _inhibitor_fd = None


# ---------------------------------------------------------------------------
# Sleep / wake handlers
# ---------------------------------------------------------------------------

def _on_sleep(going_to_sleep: bool) -> None:
    global _inhibitor_fd

    if going_to_sleep:
        log.info("System going to sleep")
        with _lock:
            was_connected = _state["connected"]
            if was_connected:
                _state["sleep_was_connected"] = True
                saved_args = _state["connect_args"]
            else:
                _state["sleep_was_connected"] = False
                saved_args = None

        if was_connected:
            log.info("Disconnecting virtual display before sleep")
            ok = _display_disconnect()
            with _lock:
                if ok:
                    _state["connected"] = False
                    log.info("Disconnected before sleep")
                else:
                    log.warning("Disconnect before sleep failed")

        # Release the inhibitor so the system can actually suspend
        _release_inhibitor()

    else:
        log.info("System waking up")
        # Re-acquire inhibitor for the next sleep cycle
        _inhibitor_fd = _acquire_inhibitor()

        with _lock:
            should_reconnect = _state["sleep_was_connected"]
            args = _state["connect_args"]

        if should_reconnect and args:
            width, height, refresh_rate, device = args
            log.info(
                "Reconnecting virtual display after wake: %dx%d@%d", width, height, refresh_rate
            )
            ok = _display_connect(width, height, refresh_rate, device=device)
            with _lock:
                if ok:
                    _state["connected"] = True
                    _state["sleep_was_connected"] = False
                    log.info("Reconnected after wake")
                else:
                    log.error("Failed to reconnect after wake")


# ---------------------------------------------------------------------------
# DBus sleep signal listener (runs in a background thread)
# ---------------------------------------------------------------------------

def _dbus_query_property(obj_path: str, bus_name: str, interface: str, prop: str):
    """Open a fresh system-bus connection, read one property, close."""
    conn = open_dbus_connection(bus="SYSTEM")
    try:
        addr = DBusAddress(obj_path, bus_name=bus_name,
                           interface="org.freedesktop.DBus.Properties")
        reply = conn.send_and_get_reply(new_method_call(addr, "Get", "ss", (interface, prop)))
        return reply.body[0][1]  # unwrap DBus variant → (sig, value)
    finally:
        conn.close()


def _get_sunshine_pid() -> int | None:
    """Find the Sunshine process PID by scanning /proc/*/comm."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() == "sunshine":
                return int(entry.name)
        except OSError:
            continue
    log.warning("Could not find a running 'sunshine' process")
    return None


def _watch_sunshine_pid(pid: int) -> None:
    """Block on a pidfd until Sunshine exits, then disconnect."""
    _watch_pid(pid, "Sunshine")


def _watch_kwin_pid(pid: int) -> None:
    """Block until KWin exits (the user logged out), then disconnect."""
    _watch_pid(pid, "KWin")


def _watch_pid(pid: int, label: str) -> None:
    """Block on a pidfd until *pid* exits, then disconnect if still connected."""
    try:
        pidfd = os.pidfd_open(pid)
    except OSError as exc:
        log.warning("pidfd_open(%d) failed: %s", pid, exc)
        return

    log.info("Watching %s PID %d", label, pid)
    try:
        while _running:
            ready, _, _ = select.select([pidfd], [], [], 1.0)
            if ready:
                break
    finally:
        os.close(pidfd)

    if not _running:
        return

    # On logout Sunshine and KWin exit together; serialize their disconnects
    # so the second one sees the first one's result instead of racing it.
    with _watch_disconnect_lock:
        with _lock:
            connected = _state["connected"]
        if not connected:
            return
        log.warning("%s PID %d exited — disconnecting virtual display", label, pid)
        ok = _display_disconnect()
        with _lock:
            if ok:
                _state["connected"] = False
                _state["connect_args"] = None


def _on_shutdown_signal(shutting_down: bool) -> None:
    if not shutting_down:
        return
    log.info("System shutting down — disconnecting virtual display")
    with _lock:
        connected = _state["connected"]
    if connected:
        ok = _display_disconnect()
        with _lock:
            if ok:
                _state["connected"] = False


def _on_sunshine_unit_changed(body) -> None:
    try:
        iface, changed, invalidated = body
    except (ValueError, TypeError):
        return

    if iface != "org.freedesktop.systemd1.Unit":
        return

    if "ActiveState" in changed:
        state = changed["ActiveState"][1]
    elif "ActiveState" in invalidated:
        try:
            state = _dbus_query_property(
                SUNSHINE_UNIT_PATH,
                "org.freedesktop.systemd1",
                "org.freedesktop.systemd1.Unit",
                "ActiveState",
            )
        except Exception as exc:
            log.debug("Could not query Sunshine ActiveState: %s", exc)
            return
    else:
        return

    if state in ("failed", "inactive"):
        with _lock:
            connected = _state["connected"]
        if connected:
            log.warning("Sunshine became %s — disconnecting virtual display", state)
            ok = _display_disconnect()
            with _lock:
                if ok:
                    _state["connected"] = False
                    _state["connect_args"] = None


def _dbus_listener() -> None:
    try:
        conn = open_dbus_connection(bus="SYSTEM")

        match_rules = [
            "type='signal',interface='org.freedesktop.login1.Manager',"
            "member='PrepareForSleep',path='/org/freedesktop/login1'",
            "type='signal',interface='org.freedesktop.login1.Manager',"
            "member='PrepareForShutdown',path='/org/freedesktop/login1'",
            f"type='signal',interface='org.freedesktop.DBus.Properties',"
            f"member='PropertiesChanged',path='{SUNSHINE_UNIT_PATH}'",
        ]
        for rule in match_rules:
            conn.send_and_get_reply(new_method_call(message_bus, "AddMatch", "s", (rule,)))

        # Tell systemd to emit unit property signals
        systemd_mgr = DBusAddress(
            "/org/freedesktop/systemd1",
            bus_name="org.freedesktop.systemd1",
            interface="org.freedesktop.systemd1.Manager",
        )
        try:
            conn.send_and_get_reply(new_method_call(systemd_mgr, "Subscribe", "", ()))
        except Exception as exc:
            log.warning("Could not subscribe to systemd signals: %s", exc)

        # Acquire the inhibitor here, after the connection is proven to work,
        # rather than racing at daemon startup before the bus is fully ready.
        _inhibitor_fd = _acquire_inhibitor()

        log.info("DBus listener ready (sleep, shutdown, Sunshine unit)")

        while _running:
            try:
                msg = conn.receive()
            except Exception:
                if not _running:
                    break
                raise

            member = msg.header.fields.get(HeaderFields.member)
            path = msg.header.fields.get(HeaderFields.path)

            if member == "PrepareForSleep":
                _on_sleep(bool(msg.body[0]))
            elif member == "PrepareForShutdown":
                _on_shutdown_signal(bool(msg.body[0]))
            elif member == "PropertiesChanged" and path == SUNSHINE_UNIT_PATH:
                _on_sunshine_unit_changed(msg.body)

    except Exception as exc:
        log.error("DBus listener failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sunshineVD")
    p.add_argument("--connect", action="store_true")
    p.add_argument("--disconnect", action="store_true")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--refresh-rate", type=int, default=60)
    p.add_argument("-d", "--device", type=str, default=None)
    return p


def _display_connect(*args, **kwargs) -> bool:
    _op_active.set()
    try:
        return display.connect(*args, **kwargs)
    finally:
        _op_active.clear()


def _display_disconnect() -> bool:
    _op_active.set()
    try:
        return display.disconnect()
    finally:
        _op_active.clear()


# ---------------------------------------------------------------------------
# Monitor hotplug -> restart the on-screen keyboard
# ---------------------------------------------------------------------------

_NETLINK_KOBJECT_UEVENT = 15


def _is_drm_hotplug(msg: bytes) -> bool:
    fields = msg.split(b"\0")
    return b"SUBSYSTEM=drm" in fields and b"HOTPLUG=1" in fields


def _hotplug_listener() -> None:
    """
    Restart maliit when a physical monitor is plugged in or unplugged: like
    after connect/disconnect, the keyboard keeps the old layout's size.
    Our own synthetic uevents (virtual display on/off) are ignored because the
    virtual connector is excluded and events during an operation only
    re-baseline the connector set.
    """
    try:
        sock = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, _NETLINK_KOBJECT_UEVENT)
        sock.bind((0, 1))
    except OSError as exc:
        log.warning("Hotplug listener unavailable: %s", exc)
        return

    last = display.physical_connectors()
    try:
        while _running:
            ready, _, _ = select.select([sock], [], [], 1.0)
            if not ready:
                continue
            if not _is_drm_hotplug(sock.recv(65536)):
                continue
            # Let the kernel/compositor settle, then drain the burst of events.
            time.sleep(1.0)
            sock.setblocking(False)
            try:
                while True:
                    sock.recv(65536)
            except (BlockingIOError, OSError):
                pass
            sock.setblocking(True)

            now = display.physical_connectors()
            if _op_active.is_set():
                last = now
                continue
            if now != last:
                added, removed = sorted(now - last), sorted(last - now)
                log.info("Monitor hotplug: connected %s, disconnected %s — restarting on-screen keyboard",
                         added or "-", removed or "-")
                last = now
                kwin.restart_virtual_keyboard_later(delay=1.5,
                                                   kwin_pid=display.kwin_session_pid())
    finally:
        sock.close()


def _handle_command(args: list[str]) -> None:
    try:
        parsed = _make_parser().parse_args(args)
    except SystemExit:
        log.warning("Could not parse command: %s", args)
        return

    if parsed.connect:
        if not parsed.width or not parsed.height:
            log.error("--connect requires --width and --height")
            return
        log.info(
            "Connecting virtual display: %dx%d@%d", parsed.width, parsed.height, parsed.refresh_rate
        )
        ok = _display_connect(
            parsed.width, parsed.height, parsed.refresh_rate, device=parsed.device
        )
        with _lock:
            if ok:
                _state["connected"] = True
                _state["connect_args"] = (
                    parsed.width,
                    parsed.height,
                    parsed.refresh_rate,
                    parsed.device,
                )
            else:
                log.error("connect() failed")

        if ok:
            pid = _get_sunshine_pid()
            if pid:
                threading.Thread(
                    target=_watch_sunshine_pid,
                    args=(pid,),
                    daemon=True,
                    name="sunshine-pid-watch",
                ).start()

            # Logging out of KDE ends KWin: restore the physical monitor then too.
            if display.active_backend() == "kwin":
                kwin_pid = display.kwin_session_pid() or kwin.find_kwin_pid()
                if kwin_pid:
                    threading.Thread(
                        target=_watch_kwin_pid,
                        args=(kwin_pid,),
                        daemon=True,
                        name="kwin-pid-watch",
                    ).start()

    elif parsed.disconnect:
        log.info("Disconnecting virtual display")
        ok = _display_disconnect()
        with _lock:
            if ok:
                _state["connected"] = False
                _state["connect_args"] = None
            else:
                log.error("disconnect() failed")

    else:
        log.warning("Received command with neither --connect nor --disconnect: %s", args)


# ---------------------------------------------------------------------------
# Cleanup and shutdown
# ---------------------------------------------------------------------------

def _cleanup() -> None:
    _release_inhibitor()
    if _server is not None:
        try:
            _server.close()
        except OSError:
            pass
    try:
        os.remove(SOCKET_FILE)
    except OSError:
        pass


def _shutdown(signum, frame) -> None:
    global _running
    log.info("Received signal %d — shutting down", signum)
    _running = False

    with _lock:
        connected = _state["connected"]

    if connected:
        log.info("Disconnecting virtual display before exit")
        ok = _display_disconnect()
        with _lock:
            if ok:
                _state["connected"] = False

    _cleanup()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _server

    # display.py and the drm modules report progress via print(). Under systemd
    # stdout is a pipe and therefore block-buffered, so those diagnostics would
    # never reach the journal before a failure/kill (issue #25).
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    sys.stderr.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )

    if os.geteuid() != 0:
        log.error("Daemon must be run as root")
        sys.exit(1)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    sleep_thread = threading.Thread(target=_dbus_listener, daemon=True, name="dbus-listener")
    sleep_thread.start()
    threading.Thread(target=_hotplug_listener, daemon=True, name="hotplug-listener").start()

    try:
        os.remove(SOCKET_FILE)
    except FileNotFoundError:
        pass

    _server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    _server.bind(SOCKET_FILE)
    os.chmod(SOCKET_FILE, 0o666)
    _server.listen(1)
    _server.settimeout(1.0)

    log.info("Daemon listening on %s", SOCKET_FILE)

    while _running:
        try:
            conn, _ = _server.accept()
        except socket.timeout:
            continue
        except OSError:
            if not _running:
                break
            raise

        try:
            data = conn.recv(256)
            if data:
                args = data.decode("utf-8").strip().split(",")
                log.info("Received command: %s", args)
                _handle_command(args)
        except Exception as exc:
            log.error("Error handling connection: %s", exc, exc_info=True)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
