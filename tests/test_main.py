"""Tests for main.py"""

import sys
from unittest.mock import patch

import pytest


class TestMain:
    def _run(self, argv: list[str], expected_exit: int = 0) -> None:
        with patch("sys.argv", ["main.py"] + argv), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == expected_exit

    def test_connect_success(self):
        with patch("sys.argv", ["main.py", "--connect", "--width", "1920", "--height", "1080"]), \
             patch("os.geteuid", return_value=0), \
             patch("src.display.connect", return_value=True), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == 0

    def test_connect_failure(self):
        with patch("sys.argv", ["main.py", "--connect", "--width", "1920", "--height", "1080"]), \
             patch("os.geteuid", return_value=0), \
             patch("src.display.connect", return_value=False), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == 1

    def test_connect_missing_dimensions(self, capsys):
        with patch("sys.argv", ["main.py", "--connect"]), \
             patch("os.geteuid", return_value=0), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == 1

    def test_disconnect_success(self):
        with patch("sys.argv", ["main.py", "--disconnect"]), \
             patch("os.geteuid", return_value=0), \
             patch("src.display.disconnect", return_value=True), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == 0

    def test_disconnect_failure(self):
        with patch("sys.argv", ["main.py", "--disconnect"]), \
             patch("os.geteuid", return_value=0), \
             patch("src.display.disconnect", return_value=False), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == 1

    def test_no_args_prints_help(self):
        with patch("sys.argv", ["main.py"]), \
             patch("os.geteuid", return_value=0), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == 1

    def test_not_root_exits(self):
        with patch("sys.argv", ["main.py", "--connect", "--width", "1920", "--height", "1080"]), \
             patch("os.geteuid", return_value=1000), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == 1

    def test_connect_with_refresh_rate(self):
        with patch("sys.argv", ["main.py", "--connect", "--width", "1920", "--height", "1080", "--refresh-rate", "120"]), \
             patch("os.geteuid", return_value=0), \
             patch("src.display.connect", return_value=True) as mock_connect, \
             pytest.raises(SystemExit):
            import main
            import importlib
            importlib.reload(main)
            main.main()
        mock_connect.assert_called_once_with(1920, 1080, 120, device=None)

    def test_connect_with_device(self):
        with patch("sys.argv", ["main.py", "--connect", "--width", "1920", "--height", "1080", "-d", "card1"]), \
             patch("os.geteuid", return_value=0), \
             patch("src.display.connect", return_value=True) as mock_connect, \
             pytest.raises(SystemExit):
            import main
            import importlib
            importlib.reload(main)
            main.main()
        mock_connect.assert_called_once_with(1920, 1080, 60, device="card1")

    def test_fatal_exception_exits_1(self, capsys):
        with patch("sys.argv", ["main.py", "--connect", "--width", "1920", "--height", "1080"]), \
             patch("os.geteuid", return_value=0), \
             patch("src.display.connect", side_effect=RuntimeError("boom")), \
             pytest.raises(SystemExit) as exc:
            import main
            import importlib
            importlib.reload(main)
            main.main()
        assert exc.value.code == 1


class TestEdidInit:
    def test_imports_create_edid(self):
        from src.edid import create_edid
        assert callable(create_edid)

    def test_imports_get_pixel_clock_info(self):
        from src.edid import get_pixel_clock_info
        assert callable(get_pixel_clock_info)

    def test_imports_find_best_vic_resolution(self):
        from src.edid import find_best_vic_resolution
        assert callable(find_best_vic_resolution)

    def test_imports_check_if_calculation_breaks(self):
        from src.edid import check_if_calculation_breaks
        assert callable(check_if_calculation_breaks)
