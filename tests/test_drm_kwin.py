"""Tests for src/drm/de/kwin.py"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.drm.de.kwin import clear_kwin_output_config


class TestClearKwinOutputConfig:
    def test_no_sudo_user_returns_early(self):
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise, just return
            clear_kwin_output_config("DP-1")

    def test_unknown_sudo_user_returns_early(self):
        import pwd
        with patch.dict(os.environ, {"SUDO_USER": "nonexistent_user_xyz"}):
            with patch("pwd.getpwnam", side_effect=KeyError("not found")):
                clear_kwin_output_config("DP-1")  # should not raise

    def test_missing_config_file_returns_early(self, tmp_path):
        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                # No kwinoutputconfig.json in tmp_path
                clear_kwin_output_config("DP-1")  # should not raise

    def test_removes_port_from_list_format(self, tmp_path, capsys):
        config = [
            {"name": "DP-1", "res": "1920x1080"},
            {"name": "DP-2", "res": "2560x1440"},
        ]
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        remaining = json.loads(config_file.read_text())
        assert len(remaining) == 1
        assert remaining[0]["name"] == "DP-2"
        assert "Cleared" in capsys.readouterr().out

    def test_no_match_in_list_format(self, tmp_path, capsys):
        config = [{"name": "DP-2", "res": "2560x1440"}]
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        assert "No stale" in capsys.readouterr().out

    def test_removes_port_from_dict_format(self, tmp_path, capsys):
        config = {
            "outputs": [
                {"name": "DP-1", "res": "1920x1080"},
                {"name": "HDMI-1", "res": "1280x720"},
            ]
        }
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        result = json.loads(config_file.read_text())
        assert len(result["outputs"]) == 1
        assert result["outputs"][0]["name"] == "HDMI-1"
        assert "Cleared" in capsys.readouterr().out

    def test_no_match_in_dict_format(self, tmp_path, capsys):
        config = {"outputs": [{"name": "HDMI-1", "res": "1280x720"}]}
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        assert "No stale" in capsys.readouterr().out

    def test_handles_json_parse_error(self, tmp_path, capsys):
        config_path = tmp_path / ".config"
        config_path.mkdir()
        config_file = config_path / "kwinoutputconfig.json"
        config_file.write_text("not valid json{{{")

        with patch.dict(os.environ, {"SUDO_USER": "testuser"}):
            with patch("pwd.getpwnam") as mock_pw:
                mock_pw.return_value.pw_dir = str(tmp_path)
                clear_kwin_output_config("DP-1")

        assert "Warning" in capsys.readouterr().out
