"""
KWin-specific helpers for virtual display management.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import stat
import subprocess
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
        if isinstance(data, list):
            outputs: list[Any] = data
            filtered: list[Any] = [o for o in outputs if o.get("name") != port]
            if len(filtered) < len(outputs):
                _ = config_path.write_text(json.dumps(filtered, indent=2))
                print(f"  ✓ Cleared KWin saved config for {port} (was overriding EDID resolution)")
            else:
                print(f"  ✓ No stale KWin config for {port}")
        else:
            outputs = data.get("outputs", [])
            original_count: int = len(outputs)
            data["outputs"] = [o for o in outputs if o.get("name") != port]
            if len(data["outputs"]) < original_count:
                _ = config_path.write_text(json.dumps(data, indent=2))
                print(f"  ✓ Cleared KWin saved config for {port} (was overriding EDID resolution)")
            else:
                print(f"  ✓ No stale KWin config for {port}")
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
_ROTATIONS: dict[int, str] = {1: "none", 2: "left", 4: "inverted", 8: "right"}


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
        candidates = sorted(Path(runtime_dir).glob("wayland-[0-9]*"))
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


def kscreen_doctor(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run kscreen-doctor as the KWin session's user."""
    if not shutil.which("kscreen-doctor"):
        return None
    session = find_session()
    if not session:
        return None

    env_args = [f"{k}={v}" for k, v in session.items() if k != "user"]
    cmd = ["kscreen-doctor", *args]
    if os.geteuid() == 0:
        cmd = ["runuser", "-u", session["user"], "--", "env", *env_args, *cmd]
    else:
        cmd = ["env", *env_args, *cmd]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"    kscreen-doctor failed: {e}")
        return None


def _outputs() -> list[dict[str, Any]] | None:
    result = kscreen_doctor(["-j"])
    if not result or result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    outputs = data.get("outputs") if isinstance(data, dict) else None
    # kscreen-doctor exits 0 with an empty list when it couldn't reach the
    # compositor (e.g. wrong WAYLAND_DISPLAY) — treat that as unavailable.
    return outputs if isinstance(outputs, list) and outputs else None


def available() -> bool:
    """Return True when a KWin Wayland session can be controlled via kscreen-doctor."""
    return _outputs() is not None


def monitor_specs(outputs: list[str]) -> dict[str, dict[str, object]]:
    """Capture enough KWin output state to restore *outputs* later."""
    wanted = set(outputs)
    specs: dict[str, dict[str, object]] = {}
    for out in _outputs() or []:
        name = out.get("name")
        if name not in wanted or not out.get("enabled"):
            continue
        mode_id = out.get("currentModeId")
        if mode_id in (None, ""):
            continue
        pos = out.get("pos") or {}
        spec: dict[str, object] = {
            "output": name,
            "mode": str(mode_id),
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


def restore_outputs(specs: dict[str, dict[str, object]]) -> bool:
    """Re-enable physical outputs through KWin with their saved configuration."""
    if not specs:
        return True
    args: list[str] = []
    for spec in specs.values():
        o = spec["output"]
        args.append(f"output.{o}.enable")
        args.append(f"output.{o}.mode.{spec['mode']}")
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
