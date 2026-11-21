#!/usr/bin/env python3
"""Add or remove this project's Sunshine global_prep_cmd entry."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOCKET_PATH = "/tmp/sunshineVD.sock"
CONFIG_KEY = "global_prep_cmd"
BACKUP_SUFFIX = ".bak"
DEFAULT_CONFIG = Path(".config/sunshine/sunshine.conf")


class ConfigError(Exception):
    """The Sunshine config cannot be read or changed safely."""


@dataclass(frozen=True)
class Assignment:
    prefix: str
    commands: list[dict[str, Any]]
    trailing: str
    ending: str


def _commands(executable: str) -> dict[str, str]:
    if Path(executable).name == "socat":
        transport = f"{shlex.quote(executable)} - UNIX-CONNECT:{SOCKET_PATH}"
    else:
        transport = f"{shlex.quote(executable)} -U {SOCKET_PATH}"
    return {
        "do": (
            'sh -c "echo --connect,--width,${SUNSHINE_CLIENT_WIDTH},'
            '--height,${SUNSHINE_CLIENT_HEIGHT},--refresh-rate,${SUNSHINE_CLIENT_FPS}'
            f' | {transport}"'
        ),
        "undo": f'sh -c "echo --disconnect | {transport}"',
    }


def _is_ours(command: dict[str, Any]) -> bool:
    do = str(command.get("do", ""))
    undo = str(command.get("undo", ""))
    return SOCKET_PATH in do and "--connect" in do and SOCKET_PATH in undo and "--disconnect" in undo


def _supports_unix_socket(executable: str, *, explicit: bool = False) -> bool:
    name = Path(executable).name
    if name == "socat":
        return True
    if not explicit and name != "nc" and not name.startswith("nc."):
        return False
    try:
        result = subprocess.run(
            [executable, "-h"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "-U" in (result.stdout + result.stderr)


def _find_executable(explicit: str | None) -> str:
    if explicit:
        path = shutil.which(explicit)
        if path is None and Path(explicit).is_file():
            path = str(Path(explicit))
        if path is None or not _supports_unix_socket(path, explicit=True):
            raise ConfigError(f"{explicit} cannot connect to a Unix domain socket")
        if not re.fullmatch(r"[A-Za-z0-9_./+-]+", path):
            raise ConfigError(f"unsupported characters in command path: {path}")
        return path
    # socat has a stable UNIX-CONNECT transport.  nc needs -U support.
    for name in ("socat", "nc"):
        path = shutil.which(name)
        if path and _supports_unix_socket(path):
            return path
    raise ConfigError(
        "neither socat nor an nc with -U support was found; "
        "install one of them or pass --command PATH"
    )


def _home_for_user(user: str | None) -> Path:
    if not user:
        return Path.home()
    try:
        return Path(pwd.getpwnam(user).pw_dir)
    except KeyError as exc:
        raise ConfigError(f"unknown user: {user}") from exc


def _in_sandbox(entry: Path) -> bool:
    try:
        sandbox = os.stat(entry / "root")
        host = os.stat("/")
    except OSError:
        return False
    return (sandbox.st_dev, sandbox.st_ino) != (host.st_dev, host.st_ino)


def _uid_for_user(user: str | None) -> int:
    if not user:
        return os.getuid()
    try:
        return pwd.getpwnam(user).pw_uid
    except KeyError as exc:
        raise ConfigError(f"unknown user: {user}") from exc


def _config_from_running_sunshine(user: str | None) -> Path | None:
    target_uid = _uid_for_user(user)
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != target_uid:
                continue
            if (entry / "comm").read_text().strip() != "sunshine":
                continue
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if _in_sandbox(entry):
            raise ConfigError(
                "Sunshine runs in a sandbox (Flatpak?); nc and socat are not "
                "available inside it. Configure the Do/Undo command manually."
            )
        for raw in argv[1:]:
            argument = raw.decode(errors="replace")
            if not argument or argument.startswith("-"):
                continue
            candidate = Path(argument)
            if not candidate.is_absolute():
                try:
                    candidate = Path(os.readlink(entry / "cwd")) / candidate
                except OSError:
                    continue
            if candidate.is_file():
                return candidate
    return None


def _find_config(user: str | None, explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"Sunshine config not found: {path}")
        return path
    env_path = os.environ.get("SUNSHINE_CONF")
    if env_path:
        path = Path(env_path).expanduser()
        if not path.is_file():
            raise ConfigError(f"SUNSHINE_CONF points to a missing file: {path}")
        return path
    running = _config_from_running_sunshine(user)
    if running is not None:
        return running
    home = _home_for_user(user)
    candidates = [home / DEFAULT_CONFIG]
    root_default = Path("/root") / DEFAULT_CONFIG
    if root_default not in candidates:
        candidates.append(root_default)
    candidates.append(Path("/etc/sunshine/sunshine.conf"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _split_assignment(line: str) -> Assignment | None:
    body = line.rstrip("\r\n")
    ending = line[len(body):]
    match = re.match(r"^(\s*global_prep_cmd\s*=\s*)(.*)$", body, re.DOTALL)
    if not match:
        return None
    prefix, raw = match.groups()
    try:
        value, end = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"cannot parse {CONFIG_KEY}: {exc.msg} (line: {line.strip()})"
        ) from exc
    trailing = raw[end:].strip()
    if trailing and not trailing.startswith("#"):
        raise ConfigError(f"unexpected text after {CONFIG_KEY}: {trailing!r}")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConfigError(f"{CONFIG_KEY} must be a JSON list of objects")
    return Assignment(prefix, value, trailing, ending)


def _find_assignment(lines: list[str]) -> tuple[int, Assignment] | None:
    found: tuple[int, Assignment] | None = None
    for index, line in enumerate(lines):
        assignment = _split_assignment(line)
        if assignment is None:
            continue
        if found is not None:
            raise ConfigError(f"found more than one {CONFIG_KEY} line")
        found = (index, assignment)
    return found


def _rewrite(
    lines: list[str], newline: str, executable: str | None, *, remove: bool
) -> tuple[str, bool]:
    found = _find_assignment(lines)
    if found is None:
        if remove:
            return "".join(lines), False
        if executable is None:
            raise ConfigError("no nc/socat executable selected")
        line = (
            f"{CONFIG_KEY} = "
            f"{json.dumps([_commands(executable)], separators=(',', ':'), ensure_ascii=False)}"
            f"{newline}"
        )
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines = [*lines[:-1], lines[-1] + newline]
        lines = [*lines, line]
        return "".join(lines), True

    index, assignment = found
    kept = [command for command in assignment.commands if not _is_ours(command)]
    if remove and len(kept) == len(assignment.commands):
        return "".join(lines), False
    if not remove:
        if executable is None:
            raise ConfigError("no nc/socat executable selected")
        kept.append(_commands(executable))
    if not kept:
        del lines[index]
        return "".join(lines), True
    trailing = f" {assignment.trailing}" if assignment.trailing else ""
    ending = assignment.ending or newline
    new_line = (
        f"{assignment.prefix}"
        f"{json.dumps(kept, separators=(',', ':'), ensure_ascii=False)}"
        f"{trailing}{ending}"
    )
    if new_line == lines[index]:
        return "".join(lines), False
    lines[index] = new_line
    return "".join(lines), True


def _read_config(path: Path) -> tuple[list[str], str]:
    if path.is_symlink():
        raise ConfigError(f"{path} is a symlink; refusing to modify it")
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.splitlines(keepends=True), newline


def _write_config(path: Path, text: str) -> Path:
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise ConfigError(f"cannot stat {path}: {exc}") from exc
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    if backup.is_symlink():
        raise ConfigError(f"{backup} is a symlink; refusing to overwrite it")
    try:
        shutil.copy2(path, backup)
        _chown_like(backup, file_stat)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.chmod(tmp_name, stat.S_IMODE(file_stat.st_mode))
            _chown_like(tmp_name, file_stat)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    except OSError as exc:
        raise ConfigError(f"cannot write {path}: {exc}") from exc
    return backup


def _chown_like(path: str | Path, file_stat: os.stat_result) -> None:
    try:
        os.chown(path, file_stat.st_uid, file_stat.st_gid)
    except OSError:
        pass


def configure(config: Path, executable: str) -> bool:
    lines, newline = _read_config(config)
    new_text, changed = _rewrite(lines, newline, executable, remove=False)
    if changed:
        _write_config(config, new_text)
    return changed


def unconfigure(config: Path) -> bool:
    lines, newline = _read_config(config)
    new_text, changed = _rewrite(lines, newline, None, remove=True)
    if changed:
        _write_config(config, new_text)
    return changed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--config", help="path to sunshine.conf (default: auto-detect)")
    parser.add_argument("--user", help="user whose Sunshine config to edit")
    parser.add_argument("--command", help="nc or socat to use (default: auto-detect)")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        path = _find_config(args.user, args.config)
        if path is None:
            if args.action == "uninstall":
                print("  ✓ Sunshine config not found; nothing to remove")
                return 0
            raise ConfigError(
                "Sunshine config not found. Start Sunshine once, or pass --config PATH."
            )
        executable = _find_executable(args.command) if args.action == "install" else None
        if args.dry_run:
            lines, newline = _read_config(path)
            new_text, changed = _rewrite(lines, newline, executable, remove=args.action == "uninstall")
            if not changed:
                print(f"  ✓ {path}: already up to date")
                return 0
            print(f"  Would update {path}:")
            print(new_text, end="")
            return 0
        changed = configure(path, executable) if executable else unconfigure(path)
        if not changed:
            print(f"  ✓ {path}: already up to date")
            return 0
        action = "Removed" if args.action == "uninstall" else "Added"
        print(f"  ✓ {action} Do/Undo command in {path}")
        print(f"  Backup: {path.with_name(path.name + BACKUP_SUFFIX)}")
        return 0
    except ConfigError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
