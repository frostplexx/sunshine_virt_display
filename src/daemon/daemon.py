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
from pathlib import Path

from jeepney import DBusAddress, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection
from jeepney.low_level import HeaderFields

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import display

log = logging.getLogger(__name__)

SOCKET_FILE = "/tmp/sunshineVD.sock"
SUNSHINE_UNIT_PATH = "/org/freedesktop/systemd1/unit/sunshine_2eservice"

_lock = threading.Lock()
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
            ok = display.disconnect()
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
            ok = display.connect(width, height, refresh_rate, device=device)
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
    try:
        pidfd = os.pidfd_open(pid)
    except OSError as exc:
        log.warning("pidfd_open(%d) failed: %s", pid, exc)
        return

    log.info("Watching Sunshine PID %d", pid)
    try:
        while _running:
            ready, _, _ = select.select([pidfd], [], [], 1.0)
            if ready:
                break
    finally:
        os.close(pidfd)

    if not _running:
        return

    with _lock:
        connected = _state["connected"]
    if connected:
        log.warning("Sunshine PID %d exited — disconnecting virtual display", pid)
        ok = display.disconnect()
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
        ok = display.disconnect()
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
            ok = display.disconnect()
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
        ok = display.connect(
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

    elif parsed.disconnect:
        log.info("Disconnecting virtual display")
        ok = display.disconnect()
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
        ok = display.disconnect()
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
