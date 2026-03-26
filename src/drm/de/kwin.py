"""
KWin-specific fixes for virtual display management.
"""

from __future__ import annotations

import json
import os
import pwd
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
