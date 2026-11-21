"""
KWin-specific helpers for virtual display management.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def clear_kwin_output_config(port: str) -> None:
    """
    Remove any stale KWin saved output config for *port* so that KWin applies
    the EDID preferred mode instead of a previously-saved resolution/scale.

    KWin stores per-connector config keyed by connector name in
    ~/.config/kwinoutputconfig.json.  When a physical monitor was last seen on
    e.g. DP-2 at 2560x1440, that entry persists and overrides our custom EDID
    when the virtual connector appears on the same port name.

    Runs as root (via sudo), so we look up the real user from $SUDO_USER.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if not sudo_user:
        return

    try:
        home = Path(pwd.getpwnam(sudo_user).pw_dir)
    except KeyError:
        return

    config_path = home / ".config" / "kwinoutputconfig.json"
    if not config_path.exists():
        return

    try:
        data: Any = json.loads(config_path.read_text())
        # kwinoutputconfig.json may be {"outputs": [...]} or a bare [...]
        outputs: list[Any] = data if isinstance(data, list) else data.get("outputs", [])
        filtered = [o for o in outputs if o.get("name") != port]
        if len(filtered) == len(outputs):
            print(f"  ✓ No stale KWin config for {port}")
            return
        data = filtered if isinstance(data, list) else {**data, "outputs": filtered}
        _ = config_path.write_text(json.dumps(data, indent=2))
        print(f"  ✓ Cleared KWin saved config for {port} (was overriding EDID resolution)")
    except Exception as e:
        print(f"  Warning: Could not update kwinoutputconfig.json: {e}")


# ---------------------------------------------------------------------------
# Compositor-safe output toggling via kscreen-doctor (issue #31)
#
# Like Hyprland, KWin owns the atomic modeset state.  A CRTC forced onto a
# connector behind its back (drmModeSetCrtc with borrowed DRM master) is never
# picked up, leaving physical monitors dark after disconnect.  Instead we ask
# KWin itself to disable/re-enable outputs through kscreen-doctor, mirroring
# the Hyprland backend's interface: available / monitor_specs /
# disable_outputs / restore_outputs.
# ---------------------------------------------------------------------------

# libkscreen rotation enum -> kscreen-doctor rotation keyword
_ROTATIONS: dict[int, str] = {
    1: "none", 2: "left", 4: "inverted", 8: "right",
    16: "flipped", 32: "flipped90", 64: "flipped180", 128: "flipped270",
}


def _read_environ(proc: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        raw = (proc / "environ").read_bytes()
    except OSError:
        return env
    for item in raw.split(b"\0"):
        key, sep, value = item.partition(b"=")
        if sep:
            env[key.decode(errors="replace")] = value.decode(errors="replace")
    return env


def _wayland_socket_number(path: Path) -> int:
    """Numeric suffix of a wayland-N socket, for a stable sort order."""
    try:
        return int(path.name.partition("-")[2])
    except ValueError:
        return -1


def _find_wayland_display(uid: int, runtime_dir: str, kwin_env: dict[str, str]) -> str | None:
    """
    kwin_wayland is handed its listening socket by kwin_wayland_wrapper, so its
    own environment usually has no WAYLAND_DISPLAY.  Take it from a client in
    the same session (plasmashell) instead, falling back to the first
    wayland-N socket in the runtime dir.
    """
    if kwin_env.get("WAYLAND_DISPLAY"):
        return kwin_env["WAYLAND_DISPLAY"]

    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            if (proc / "comm").read_text().strip() not in ("plasmashell", "ksmserver", "kded6"):
                continue
        except OSError:
            continue
        display = _read_environ(proc).get("WAYLAND_DISPLAY")
        if display:
            return display

    try:
        candidates = sorted(Path(runtime_dir).glob("wayland-[0-9]*"), key=_wayland_socket_number)
    except OSError:
        candidates = []
    for cand in candidates:
        try:
            if stat.S_ISSOCK(cand.stat().st_mode):
                return cand.name
        except OSError:
            continue
    return None


def find_session() -> dict[str, str] | None:
    """
    Locate a running kwin_wayland and return the environment needed to talk
    to it: user, XDG_RUNTIME_DIR, WAYLAND_DISPLAY, DBUS_SESSION_BUS_ADDRESS.
    The daemon runs as root under systemd, so nothing is inherited.
    """
    for proc in sorted(Path("/proc").iterdir(), key=lambda p: p.name):
        if not proc.name.isdigit():
            continue
        try:
            if (proc / "comm").read_text().strip() != "kwin_wayland":
                continue
            uid = proc.stat().st_uid
        except OSError:
            continue
        env = _read_environ(proc)
        if not env:
            continue

        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            continue

        runtime_dir = env.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        display = _find_wayland_display(uid, runtime_dir, env)
        if not display:
            continue

        session = {
            "user": user,
            "XDG_RUNTIME_DIR": runtime_dir,
            "WAYLAND_DISPLAY": display,
        }
        if "DBUS_SESSION_BUS_ADDRESS" in env:
            session["DBUS_SESSION_BUS_ADDRESS"] = env["DBUS_SESSION_BUS_ADDRESS"]
        return session
    return None


def _run_in_session(cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run *cmd* as the KWin session's user with its Wayland/DBus environment."""
    session = find_session()
    if not session:
        return None

    env_args = [f"{k}={v}" for k, v in session.items() if k != "user"]
    if os.geteuid() == 0:
        cmd = ["runuser", "-u", session["user"], "--", "env", *env_args, *cmd]
    else:
        cmd = ["env", *env_args, *cmd]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"    {cmd[-1] if cmd else 'command'} failed: {e}")
        return None


def find_kwin_pid() -> int | None:
    """PID of the running kwin_wayland, or None when no KWin session exists."""
    for pid, comm, _, _ in _processes():
        if comm == "kwin_wayland":
            return pid
    return None


def session_alive(kwin_pid: int | None = None) -> bool:
    """False once KWin has exited, e.g. after the user logged out.

    With *kwin_pid* only that compositor counts, so another user's session
    cannot keep the check alive after a logout.
    """
    if kwin_pid is None:
        return find_kwin_pid() is not None
    return any(pid == kwin_pid and comm == "kwin_wayland"
               for pid, comm, _, _ in _processes())


def kscreen_doctor(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run kscreen-doctor as the KWin session's user."""
    if not shutil.which("kscreen-doctor"):
        return None
    return _run_in_session(["kscreen-doctor", *args])


def _outputs() -> list[dict[str, Any]] | None:
    result = kscreen_doctor(["-j"])
    if not result or result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    outputs = data.get("outputs") if isinstance(data, dict) else None
    # No outputs means there is nothing to hide or restore.  An unreachable
    # session produces no config at all and hits the timeout in
    # _run_in_session, so it is already handled above.
    return outputs if isinstance(outputs, list) and outputs else None


def available() -> bool:
    """Return True when a KWin Wayland session can be controlled via kscreen-doctor."""
    return _outputs() is not None


def monitor_specs(outputs: list[str]) -> dict[str, dict[str, object]]:
    """
    Capture enough KWin output state to restore *outputs* later.

    A connected output that is disabled in KWin is recorded with
    ``enabled: False``.  It is already hidden and must stay hidden, so the
    display manager must not try to hide or restore it (for example the
    internal panel in an "external monitor only" profile).  Specs written by
    older versions have no ``enabled`` key and are treated as enabled.
    """
    wanted = set(outputs)
    specs: dict[str, dict[str, object]] = {}
    for out in _outputs() or []:
        name = out.get("name")
        if name not in wanted:
            continue
        if not out.get("enabled"):
            specs[name] = {"output": name, "enabled": False}
            continue
        mode_id = out.get("currentModeId")
        current = next((m for m in out.get("modes") or [] if str(m.get("id")) == str(mode_id)), None)
        size = (current or {}).get("size") or {}
        if not current or not size.get("width") or not size.get("height"):
            continue
        pos = out.get("pos") or {}
        # KWin renumbers mode ids whenever the set of outputs changes (e.g.
        # when the virtual display appears), so store the mode itself and
        # resolve it to an id again at restore time.
        spec: dict[str, object] = {
            "output": name,
            "enabled": True,
            "width": int(size["width"]),
            "height": int(size["height"]),
            "refresh": float(current.get("refreshRate", 0)),
            "position": f"{int(pos.get('x', 0))},{int(pos.get('y', 0))}",
            "scale": out.get("scale", 1),
        }
        if isinstance(out.get("priority"), int) and out["priority"] > 0:
            spec["priority"] = out["priority"]
        rotation = _ROTATIONS.get(out.get("rotation", 1))
        if rotation:
            spec["rotation"] = rotation
        specs[name] = spec
    return specs


def disable_outputs(outputs: list[str]) -> bool:
    """Disable physical outputs through KWin, atomically in one config change."""
    if not outputs:
        return True
    result = kscreen_doctor([f"output.{o}.disable" for o in outputs])
    if result and result.returncode != 0:
        print(f"    kscreen-doctor: {result.stderr.strip()}")
    return bool(result and result.returncode == 0)


def _resolve_mode(spec: dict[str, object], outputs: list[dict[str, Any]]) -> str | None:
    """Map a saved WxH@refresh to the output's *current* KWin mode id."""
    if "width" not in spec:
        # Legacy spec that stored a raw mode id
        mode = spec.get("mode")
        return str(mode) if mode not in (None, "") else None

    w, h = spec["width"], spec["height"]
    refresh = float(spec.get("refresh", 0))  # type: ignore[arg-type]
    out = next((o for o in outputs if o.get("name") == spec["output"]), None)
    candidates = [
        m for m in (out or {}).get("modes") or []
        if (m.get("size") or {}).get("width") == w and (m.get("size") or {}).get("height") == h
    ]
    if candidates:
        best = min(candidates, key=lambda m: abs(float(m.get("refreshRate", 0)) - refresh))
        return str(best["id"])
    # Fall back to kscreen-doctor's name matching
    return f"{w}x{h}@{round(refresh)}"


def restore_outputs(specs: dict[str, dict[str, object]]) -> bool:
    """Re-enable physical outputs through KWin with their saved configuration."""
    enabled_specs = {name: spec for name, spec in specs.items() if spec.get("enabled", True)}
    if not enabled_specs:
        return True
    outputs = _outputs() or []
    args: list[str] = []
    for spec in enabled_specs.values():
        o = spec["output"]
        args.append(f"output.{o}.enable")
        mode = _resolve_mode(spec, outputs)
        if mode:
            args.append(f"output.{o}.mode.{mode}")
        args.append(f"output.{o}.position.{spec['position']}")
        args.append(f"output.{o}.scale.{spec['scale']}")
        if "rotation" in spec:
            args.append(f"output.{o}.rotation.{spec['rotation']}")
        if "priority" in spec:
            args.append(f"output.{o}.priority.{spec['priority']}")
    result = kscreen_doctor(args)
    if result and result.returncode != 0:
        print(f"    kscreen-doctor: {result.stderr.strip()}")
    return bool(result and result.returncode == 0)


# ---------------------------------------------------------------------------
# Touch / pen mapping for Sunshine's virtual input devices
#
# Sunshine creates its virtual touchscreen and pen when the stream starts.
# KWin maps touch devices to a physical output, which at that point is the
# one we just disabled, so every touch is dropped ("Could not find logical
# output for DrmOutput").  Point those devices at the virtual output via
# KWin's per-device `outputName` DBus property instead.
# ---------------------------------------------------------------------------

_KWIN_INPUT = ("org.kde.KWin", "/org/kde/KWin/InputDevice")
_mapping_stop = threading.Event()
_mapping_lock = threading.Lock()


def _busctl_get(path: str, iface: str, prop: str) -> Any:
    result = _run_in_session(["busctl", "--user", "--json=short", "get-property",
                              _KWIN_INPUT[0], path, iface, prop])
    if not result or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout).get("data")
    except (json.JSONDecodeError, AttributeError):
        return None


def input_device_sysnames() -> list[str]:
    """sysnames of the input devices KWin currently knows about."""
    names = _busctl_get(_KWIN_INPUT[1], "org.kde.KWin.InputDeviceManager", "devicesSysNames")
    return [str(name) for name in names or []]


def input_device(sysname: str) -> dict[str, Any]:
    """One KWin input device with its name, touch/tablet flags and mapped output."""
    path = f"{_KWIN_INPUT[1]}/{sysname}"
    return {
        "sysname": sysname,
        "name": _busctl_get(path, "org.kde.KWin.InputDevice", "name") or "",
        "touch": bool(_busctl_get(path, "org.kde.KWin.InputDevice", "touch")),
        "tablet": bool(_busctl_get(path, "org.kde.KWin.InputDevice", "tabletTool")),
        "output": _busctl_get(path, "org.kde.KWin.InputDevice", "outputName") or "",
    }


def _is_sunshine_pointer_device(dev: dict[str, Any]) -> bool:
    """Sunshine's virtual touchscreen / pen (libvirtualhid, or inputtino's passthrough devices)."""
    name = dev.get("name", "")
    ours = name.startswith("libvirtualhid") or "passthrough" in name.lower()
    return ours and (dev.get("touch") or dev.get("tablet") or "Touch" in name or "Pen" in name)


def set_device_output(sysname: str, output: str) -> bool:
    result = _run_in_session(["busctl", "--user", "set-property", _KWIN_INPUT[0],
                              f"{_KWIN_INPUT[1]}/{sysname}", "org.kde.KWin.InputDevice",
                              "outputName", "s", output])
    if not result or result.returncode != 0:
        return False
    # KWin's setOutputName() silently ignores a name it does not know (for
    # example the virtual output is not registered yet).  Confirm the value.
    return _busctl_get(f"{_KWIN_INPUT[1]}/{sysname}", "org.kde.KWin.InputDevice",
                       "outputName") == output


def map_virtual_input(
    output: str,
    timeout: float = 30.0,
    interval: float = 0.5,
    stop_event: threading.Event | None = None,
) -> int:
    """
    Wait for Sunshine's virtual touch/pen devices to appear and map them to
    *output*.  Returns the number of devices mapped.  Stops early when the
    watcher's stop event is set (see start_input_mapping/stop_input_mapping).

    Only the device name list is polled.  Each device's properties are read
    once, so a desktop with many input devices does not spawn four busctl
    calls per device per poll.
    """
    stop = _mapping_stop if stop_event is None else stop_event
    mapped: set[str] = set()
    names: dict[str, str | None] = {}
    deadline = time.monotonic() + timeout
    while not stop.is_set():
        for sysname in input_device_sysnames():
            if sysname in mapped:
                continue
            if sysname not in names:
                dev = input_device(sysname)
                if not dev["name"]:
                    continue  # KWin has not finished registering it yet
                names[sysname] = dev["name"] if _is_sunshine_pointer_device(dev) else None
            name = names[sysname]
            if name is None:
                continue
            if set_device_output(sysname, output):
                print(f"  ✓ Mapped {name} to {output}")
                mapped.add(sysname)
        if time.monotonic() >= deadline:
            break
        stop.wait(interval)
    return len(mapped)


def start_input_mapping(output: str) -> threading.Thread:
    global _mapping_stop
    with _mapping_lock:
        previous = _mapping_stop
        stop = threading.Event()
        _mapping_stop = stop
    # A watcher from an earlier session must not clear a stop request that
    # belongs to the new watcher.
    previous.set()
    thread = threading.Thread(target=map_virtual_input, args=(output,),
                              kwargs={"stop_event": stop}, daemon=True,
                              name="kwin-touch-mapping")
    thread.start()
    return thread


def stop_input_mapping() -> None:
    """Stop the watcher and drop our mapping so KWin uses its default again."""
    with _mapping_lock:
        stop = _mapping_stop
    stop.set()
    for sysname in input_device_sysnames():
        dev = input_device(sysname)
        if _is_sunshine_pointer_device(dev) and dev["output"]:
            _ = set_device_output(sysname, "")


# ---------------------------------------------------------------------------
# On-screen keyboard restart
#
# maliit-keyboard (and plasma-keyboard) size themselves to the output they
# start on and don't resize when outputs come and go: after a connect the
# keyboard keeps the physical monitor's size on the virtual display, and after
# a disconnect it keeps the phone's size.  KWin launches the keyboard itself
# and starts it again when it exits, so terminating it once the new layout has
# settled makes it come back at the right size.
# ---------------------------------------------------------------------------

_KEYBOARD_NAMES = ("maliit-keyboard", "plasma-keyboard")

# KWin restarts the input method only on CrashExit and gives up after the
# fifth crash within 20 s (src/inputmethod.cpp).  Keep one restart in reserve.
_KEYBOARD_RESTART_WINDOW = 20.0
_KEYBOARD_RESTART_BUDGET = 4
_keyboard_restarts: list[float] = []
_keyboard_restart_lock = threading.Lock()


def _reserve_keyboard_restart(now: float | None = None) -> bool:
    """Take one slot from the restart budget KWin tolerates."""
    timestamp = time.monotonic() if now is None else now
    with _keyboard_restart_lock:
        cutoff = timestamp - _KEYBOARD_RESTART_WINDOW
        while _keyboard_restarts and _keyboard_restarts[0] <= cutoff:
            _keyboard_restarts.pop(0)
        if len(_keyboard_restarts) >= _KEYBOARD_RESTART_BUDGET:
            return False
        _keyboard_restarts.append(timestamp)
        return True


def _session_uid() -> int | None:
    """UID of the user that owns the KWin session, when one is reachable."""
    session = find_session()
    if not session:
        return None
    try:
        return pwd.getpwnam(session["user"]).pw_uid
    except KeyError:
        return None


def _processes() -> list[tuple[int, str, int, int]]:
    """Return (pid, comm, ppid, uid) for every process."""
    procs: list[tuple[int, str, int, int]] = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            uid = proc.stat().st_uid
            comm = (proc / "comm").read_text().strip()
            ppid = 0
            for line in (proc / "status").read_text().splitlines():
                if line.startswith("PPid:"):
                    ppid = int(line.split()[1])
                    break
        except (OSError, ValueError):
            continue
        procs.append((int(proc.name), comm, ppid, uid))
    return procs


def restart_virtual_keyboard(kwin_pid: int | None = None) -> list[int]:
    """
    Terminate KWin-managed on-screen keyboards so KWin restarts them at the
    current output size.  Keyboards not started by KWin are left alone, since
    nothing would bring them back.  Returns the PIDs that were signalled.

    Only keyboards of *kwin_pid* are touched.  Without a PID (old state files)
    only keyboards of the session user are touched, so a global hotplug does
    not kill another user's keyboard.
    """
    procs = _processes()
    if kwin_pid is not None:
        kwin_pids = {kwin_pid}
    else:
        uid = _session_uid()
        if uid is None:
            return []
        kwin_pids = {pid for pid, comm, _, puid in procs
                     if comm == "kwin_wayland" and puid == uid}
    targets = [(pid, comm) for pid, comm, ppid, _ in procs
               if comm in _KEYBOARD_NAMES and ppid in kwin_pids]
    if not targets:
        return []
    if not _reserve_keyboard_restart():
        print("  ⚠ Skipped on-screen keyboard restart: KWin's restart budget is exhausted")
        return []
    restarted: list[int] = []
    for pid, comm in targets:
        try:
            os.kill(pid, signal.SIGTERM)
            restarted.append(pid)
            print(f"  ✓ Restarted {comm} (pid {pid}) so it resizes to the new layout")
        except OSError as e:
            print(f"  Warning: could not restart {comm} (pid {pid}): {e}")
    return restarted


def restart_virtual_keyboard_later(delay: float = 1.0,
                                   kwin_pid: int | None = None) -> threading.Thread:
    """Restart the on-screen keyboard after *delay* seconds, in the background."""
    def run() -> None:
        time.sleep(delay)
        _ = restart_virtual_keyboard(kwin_pid)

    thread = threading.Thread(target=run, daemon=True, name="kwin-keyboard-restart")
    thread.start()
    return thread
