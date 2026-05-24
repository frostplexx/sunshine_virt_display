"""
Hyprland-specific display helpers.

Hyprland exposes monitor state and configuration through `hyprctl`.  On
NVIDIA/Hyprland, direct DRM CRTC manipulation can leave physical outputs stuck
at 0x0 after disconnect, so the display manager uses these helpers to hide and
restore physical outputs through the compositor instead.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def find_instance() -> tuple[int, str] | None:
    """Return (uid, instance_signature) for a running Hyprland session."""
    run_user = Path("/run/user")
    if not run_user.exists():
        return None

    for user_dir in sorted(run_user.iterdir()):
        if not user_dir.name.isdigit():
            continue
        hypr_dir = user_dir / "hypr"
        if not hypr_dir.exists():
            continue
        for inst in sorted(hypr_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if (inst / ".socket.sock").exists():
                return int(user_dir.name), inst.name
    return None


def hyprctl(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run hyprctl against the newest visible Hyprland instance."""
    instance = find_instance()
    if not instance:
        return None
    uid, sig = instance
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    return subprocess.run(
        ["hyprctl", "-i", sig, *args],
        capture_output=True,
        text=True,
        env=env,
    )


def available() -> bool:
    """Return True when a Hyprland session can be controlled with hyprctl."""
    result = hyprctl(["status"])
    return bool(result and result.returncode == 0 and "backend:" in result.stdout)


def _bitdepth_from_format(fmt: Any) -> int | None:
    """Infer Hyprland monitor bitdepth from the active DRM format string."""
    fmt_text = str(fmt)
    if "2101010" in fmt_text:
        return 10
    if "8888" in fmt_text:
        return 8
    return None


def monitor_specs(outputs: list[str]) -> dict[str, dict[str, object]]:
    """Capture enough Hyprland monitor state to restore outputs later."""
    result = hyprctl(["-j", "monitors", "all"])
    if not result or result.returncode != 0:
        return {}

    try:
        monitors = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    wanted = set(outputs)
    specs: dict[str, dict[str, object]] = {}
    for mon in monitors:
        name = mon.get("name")
        if name not in wanted:
            continue
        width = mon.get("width")
        height = mon.get("height")
        refresh = mon.get("refreshRate")
        x = mon.get("x", 0)
        y = mon.get("y", 0)
        scale = mon.get("scale", 1.0)
        if not width or not height or not refresh:
            continue

        spec: dict[str, object] = {
            "output": name,
            "mode": f"{width}x{height}@{refresh}",
            "position": f"{x}x{y}",
            "scale": scale,
        }

        bitdepth = _bitdepth_from_format(mon.get("currentFormat"))
        if bitdepth is not None:
            spec["bitdepth"] = bitdepth

        if mon.get("vrr") is True:
            spec["vrr"] = 1

        specs[name] = spec
    return specs


def eval_monitor(spec: dict[str, object]) -> bool:
    """Apply a Hyprland monitor spec through the Lua-capable hyprctl eval API."""
    items = []
    for key, value in spec.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = json.dumps(value)
        items.append(f"{key} = {rendered}")
    code = "hl.monitor({ " + ", ".join(items) + " })"
    result = hyprctl(["eval", code])
    return bool(result and result.returncode == 0)


def disable_outputs(outputs: list[str]) -> bool:
    """Disable physical outputs through Hyprland."""
    ok = True
    for output in outputs:
        ok = eval_monitor({"output": output, "disabled": True}) and ok
    return ok


def restore_outputs(specs: dict[str, dict[str, object]]) -> bool:
    """Restore physical outputs through Hyprland."""
    ok = True
    for spec in specs.values():
        restore_spec = dict(spec)
        restore_spec["disabled"] = False
        ok = eval_monitor(restore_spec) and ok
    return ok
