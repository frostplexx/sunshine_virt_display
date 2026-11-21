"""Tests for scripts/sunshine_prep_cmd.py."""

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import sunshine_prep_cmd as prep

NC = "/usr/bin/nc"
SOCAT = "/usr/bin/socat"


def _write_config(tmp_path: Path, text: str, mode: int = 0o640) -> Path:
    path = tmp_path / "sunshine.conf"
    path.write_text(text, encoding="utf-8", newline="")
    path.chmod(mode)
    return path


def _commands(path: Path) -> list[dict] | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("global_prep_cmd"):
            raw = line.split("=", 1)[1].strip()
            return json.JSONDecoder().raw_decode(raw)[0]
    return None


class TestRewrite:
    def test_adds_key(self, tmp_path):
        path = _write_config(tmp_path, "locale = en\n")
        assert prep.configure(path, SOCAT) is True
        commands = _commands(path)
        assert len(commands) == 1
        assert "socat - UNIX-CONNECT:/tmp/sunshineVD.sock" in commands[0]["do"]
        assert "--disconnect" in commands[0]["undo"]
        assert path.read_text().endswith("\n")
        assert (tmp_path / "sunshine.conf.bak").read_text() == "locale = en\n"

    def test_preserves_existing_commands(self, tmp_path):
        user = {"do": "echo user", "undo": "echo undo"}
        path = _write_config(tmp_path, f"global_prep_cmd = {json.dumps([user])}\n")
        assert prep.configure(path, NC) is True
        assert _commands(path) == [user, prep._commands(NC)]

    def test_preserves_elevated_key(self, tmp_path):
        user = {"do": "echo user", "elevated": True, "undo": "echo undo"}
        path = _write_config(tmp_path, f"global_prep_cmd = {json.dumps([user])}\n")
        prep.configure(path, NC)
        assert _commands(path)[0] == user

    def test_idempotent(self, tmp_path):
        path = _write_config(tmp_path, "")
        assert prep.configure(path, NC) is True
        first = path.read_text()
        assert prep.configure(path, NC) is False
        assert path.read_text() == first
        assert len(_commands(path)) == 1

    def test_preserves_trailing_comment(self, tmp_path):
        user = {"do": "echo user", "undo": "echo undo"}
        path = _write_config(tmp_path, f"global_prep_cmd = {json.dumps([user])} # keep me\n")
        prep.configure(path, NC)
        assert _commands(path) == [user, prep._commands(NC)]
        assert path.read_text().rstrip().endswith("# keep me")

    @pytest.mark.parametrize("line", [
        "global_prep_cmd = [{]\n",
        'global_prep_cmd = {"do": "x", "undo": "y"}\n',
        'global_prep_cmd = ["echo user"]\n',
        'global_prep_cmd = [{"do": "x", "undo": "y"}]\nglobal_prep_cmd = []\n',
        "global_prep_cmd = [1]\n",
    ])
    def test_rejects_unsafe_input(self, tmp_path, line):
        path = _write_config(tmp_path, line)
        before = path.read_text()
        with pytest.raises(prep.ConfigError):
            prep.configure(path, NC)
        assert path.read_text() == before
        assert not (tmp_path / "sunshine.conf.bak").exists()

    def test_preserves_crlf(self, tmp_path):
        path = _write_config(tmp_path, "locale = en\r\n")
        prep.configure(path, NC)
        text = path.read_text(encoding="utf-8", newline="")
        assert all(line.endswith("\r\n") for line in text.splitlines(keepends=True))

    def test_preserves_utf8(self, tmp_path):
        user = {"do": "echo café", "undo": "echo fin"}
        path = _write_config(tmp_path, f"global_prep_cmd = {json.dumps([user], ensure_ascii=False)}\n")
        prep.configure(path, NC)
        assert _commands(path)[0] == user
        assert "café" in path.read_text(encoding="utf-8")

    def test_preserves_mode_and_owner(self, tmp_path):
        path = _write_config(tmp_path, "", mode=0o600)
        before = path.stat()
        prep.configure(path, NC)
        after = path.stat()
        assert stat.S_IMODE(after.st_mode) == 0o600
        assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)

    def test_refuses_symlink_config(self, tmp_path):
        target = _write_config(tmp_path, "")
        link = tmp_path / "link.conf"
        link.symlink_to(target)
        with pytest.raises(prep.ConfigError):
            prep.configure(link, NC)
        assert target.read_text() == ""

    def test_refuses_symlink_backup(self, tmp_path):
        path = _write_config(tmp_path, "")
        other = tmp_path / "other"
        other.write_text("do not touch")
        (tmp_path / "sunshine.conf.bak").symlink_to(other)
        with pytest.raises(prep.ConfigError):
            prep.configure(path, NC)
        assert other.read_text() == "do not touch"

    def test_uninstall_keeps_other_commands(self, tmp_path):
        user = {"do": "echo user", "undo": "echo undo"}
        path = _write_config(tmp_path, f"global_prep_cmd = {json.dumps([prep._commands(NC), user])}\n")
        assert prep.unconfigure(path) is True
        assert _commands(path) == [user]

    def test_uninstall_removes_empty_key(self, tmp_path):
        path = _write_config(tmp_path, f"global_prep_cmd = {json.dumps([prep._commands(NC)])}\n")
        assert prep.unconfigure(path) is True
        assert _commands(path) is None
        assert "global_prep_cmd" not in path.read_text()

    def test_uninstall_noop(self, tmp_path):
        path = _write_config(tmp_path, "locale = en\n")
        assert prep.unconfigure(path) is False
        assert path.read_text() == "locale = en\n"

    def test_uninstall_does_not_reformat_when_nothing_matches(self, tmp_path):
        text = 'global_prep_cmd = [ {"do": "echo user", "undo": "echo undo"} ]\n'
        path = _write_config(tmp_path, text)
        assert prep.unconfigure(path) is False
        assert path.read_text() == text


class TestIsOurs:
    @pytest.mark.parametrize("command,expected", [
        ({"do": 'sh -c "echo --connect | nc -U /tmp/sunshineVD.sock"',
          "undo": 'sh -c "echo --disconnect | nc -U /tmp/sunshineVD.sock"'}, True),
        ({"do": "sh -c \"echo --connect | /usr/bin/socat - UNIX-CONNECT:/tmp/sunshineVD.sock\"",
          "undo": "sh -c \"echo --disconnect | /usr/bin/socat - UNIX-CONNECT:/tmp/sunshineVD.sock\""}, True),
        ({"do": "echo user", "undo": "echo undo"}, False),
        ({"do": None, "undo": None}, False),
    ])
    def test_variants(self, command, expected):
        assert prep._is_ours(command) is expected


class TestExecutable:
    def test_prefers_socat(self):
        which = {"socat": SOCAT, "nc": NC}
        with patch("shutil.which", side_effect=lambda name: which.get(name)):
            assert prep._find_executable(None) == SOCAT

    def test_accepts_nc_with_unix_socket_support(self):
        help_text = SimpleNamespace(stdout="", stderr="usage: nc -U ...")
        with patch("shutil.which", side_effect=lambda name: NC if name == "nc" else None), \
             patch("subprocess.run", return_value=help_text):
            assert prep._find_executable(None) == NC

    def test_rejects_nc_without_unix_socket_support(self):
        help_text = SimpleNamespace(stdout="usage: nc ...", stderr="")
        with patch("shutil.which", side_effect=lambda name: NC if name == "nc" else None), \
             patch("subprocess.run", return_value=help_text):
            with pytest.raises(prep.ConfigError):
                prep._find_executable(None)

    def test_explicit_custom_nc_path(self, tmp_path):
        fake = tmp_path / "my-nc"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        help_text = SimpleNamespace(stdout="nc -U", stderr="")
        with patch("subprocess.run", return_value=help_text):
            assert prep._find_executable(str(fake)) == str(fake)

    def test_explicit_path_with_unsupported_characters(self, tmp_path):
        fake = tmp_path / "my nc"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        help_text = SimpleNamespace(stdout="nc -U", stderr="")
        with patch("subprocess.run", return_value=help_text):
            with pytest.raises(prep.ConfigError, match="unsupported characters"):
                prep._find_executable(str(fake))

    def test_explicit_missing_path(self, tmp_path):
        with patch("shutil.which", return_value=None):
            with pytest.raises(prep.ConfigError):
                prep._find_executable(str(tmp_path / "missing"))


class TestFindConfig:
    def test_explicit_wins(self, tmp_path):
        path = _write_config(tmp_path, "")
        assert prep._find_config(None, str(path)) == path

    def test_missing_explicit_path(self, tmp_path):
        with pytest.raises(prep.ConfigError):
            prep._find_config(None, str(tmp_path / "missing.conf"))

    def test_environment_path(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, "")
        monkeypatch.setenv("SUNSHINE_CONF", str(path))
        assert prep._find_config(None, None) == path

    def test_default_user_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SUNSHINE_CONF", raising=False)
        home = tmp_path / "home"
        (home / ".config/sunshine").mkdir(parents=True)
        path = home / ".config/sunshine/sunshine.conf"
        path.write_text("")
        with patch("scripts.sunshine_prep_cmd._config_from_running_sunshine", return_value=None), \
             patch("scripts.sunshine_prep_cmd._home_for_user", return_value=home):
            assert prep._find_config(None, None) == path

    def test_returns_none_when_nothing_exists(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SUNSHINE_CONF", raising=False)
        with patch("scripts.sunshine_prep_cmd._config_from_running_sunshine", return_value=None), \
             patch("scripts.sunshine_prep_cmd._home_for_user", return_value=tmp_path), \
             patch.object(Path, "is_file", return_value=False):
            assert prep._find_config(None, None) is None


class _FakeFile:
    def __init__(self, data: bytes):
        self._data = data

    def read_text(self) -> str:
        return self._data.decode()

    def read_bytes(self) -> bytes:
        return self._data


class _FakeEntry:
    def __init__(self, name: str, uid: int, cmdline: bytes, root: Path | None = None):
        self.name = name
        self._uid = uid
        self._cmdline = cmdline
        self._root = root or Path("/")

    def stat(self):
        return SimpleNamespace(st_uid=self._uid)

    def __truediv__(self, other: str):
        if other == "comm":
            return _FakeFile(b"sunshine\n")
        if other == "cmdline":
            return _FakeFile(self._cmdline)
        if other == "root":
            return self._root
        return Path("/")


class TestRunningSunshine:
    def test_reads_custom_config_path(self, tmp_path):
        conf = tmp_path / "custom.conf"
        conf.write_text("")
        entry = _FakeEntry(
            "1234", os.getuid(), b"sunshine\0" + str(conf).encode() + b"\0"
        )
        with patch.object(Path, "iterdir", return_value=[entry]):
            assert prep._config_from_running_sunshine(None) == conf

    def test_ignores_other_users(self, tmp_path):
        conf = tmp_path / "custom.conf"
        conf.write_text("")
        entry = _FakeEntry(
            "1234", os.getuid() + 1, b"sunshine\0" + str(conf).encode() + b"\0"
        )
        with patch.object(Path, "iterdir", return_value=[entry]):
            assert prep._config_from_running_sunshine(None) is None

    def test_ignores_flags(self):
        entry = _FakeEntry("1234", os.getuid(), b"sunshine\0--version\0")
        with patch.object(Path, "iterdir", return_value=[entry]):
            assert prep._config_from_running_sunshine(None) is None

    def test_refuses_sandboxed_sunshine(self, tmp_path):
        entry = _FakeEntry("1234", os.getuid(), b"sunshine\0", root=tmp_path)
        with patch.object(Path, "iterdir", return_value=[entry]):
            with pytest.raises(prep.ConfigError, match="sandbox"):
                prep._config_from_running_sunshine(None)


class TestCli:
    def test_install(self, tmp_path, capsys):
        path = _write_config(tmp_path, "")
        with patch("scripts.sunshine_prep_cmd._find_executable", return_value=SOCAT):
            assert prep.main(["install", "--config", str(path)]) == 0
        assert _commands(path)
        out = capsys.readouterr().out
        assert "Added" in out
        assert "Backup" in out

    def test_error_exit_code(self, tmp_path, capsys):
        path = _write_config(tmp_path, "global_prep_cmd = [{]\n")
        assert prep.main(["install", "--config", str(path)]) == 1
        assert "Error" in capsys.readouterr().err

    def test_dry_run(self, tmp_path, capsys):
        path = _write_config(tmp_path, "")
        with patch("scripts.sunshine_prep_cmd._find_executable", return_value=SOCAT):
            assert prep.main(["install", "--config", str(path), "--dry-run"]) == 0
        assert path.read_text() == ""
        assert not (tmp_path / "sunshine.conf.bak").exists()
        assert "Would update" in capsys.readouterr().out

    def test_uninstall_missing_config_is_not_an_error(self, capsys):
        with patch("scripts.sunshine_prep_cmd._find_config", return_value=None):
            assert prep.main(["uninstall"]) == 0
        assert "nothing to remove" in capsys.readouterr().out
