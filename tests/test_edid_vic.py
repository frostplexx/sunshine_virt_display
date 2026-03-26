"""Tests for src/edid/vic.py"""

from unittest.mock import patch

from src.edid.vic import VIC_RESOLUTIONS, find_best_vic_resolution


class TestVicResolutions:
    def test_dict_not_empty(self):
        assert len(VIC_RESOLUTIONS) > 0

    def test_vic1_is_640x480_60(self):
        assert VIC_RESOLUTIONS[1] == (640, 480, 60, "DMT0659")

    def test_vic16_is_1080p60(self):
        assert VIC_RESOLUTIONS[16] == (1920, 1080, 60, "1080p")

    def test_vic4_is_720p60(self):
        assert VIC_RESOLUTIONS[4] == (1280, 720, 60, "720p")

    def test_all_entries_have_four_fields(self):
        for vic, entry in VIC_RESOLUTIONS.items():
            assert len(entry) == 4, f"VIC {vic} has wrong number of fields"

    def test_all_widths_positive(self):
        for vic, (w, h, r, name) in VIC_RESOLUTIONS.items():
            assert w > 0 and h > 0 and r > 0, f"VIC {vic} has non-positive dims"


class TestFindBestVicResolution:
    def test_exact_1080p60_match(self):
        result = find_best_vic_resolution(1920, 1080, 60)
        assert result is not None
        w, h, r, vic, name = result
        assert w == 1920 and h == 1080 and r == 60

    def test_exact_720p60_match(self):
        result = find_best_vic_resolution(1280, 720, 60)
        assert result is not None
        w, h, r, vic, name = result
        assert w == 1280 and h == 720 and r == 60

    def test_returns_five_tuple(self):
        result = find_best_vic_resolution(1920, 1080, 60)
        assert result is not None
        assert len(result) == 5

    def test_result_types(self):
        result = find_best_vic_resolution(1920, 1080, 60)
        assert result is not None
        w, h, r, vic, name = result
        assert isinstance(w, int)
        assert isinstance(h, int)
        assert isinstance(r, int)
        assert isinstance(vic, int)
        assert isinstance(name, str)

    def test_refresh_rate_prioritized(self):
        # Ask for 60Hz — result should have 60Hz refresh rate
        result = find_best_vic_resolution(1920, 1080, 60)
        assert result is not None
        _, _, r, _, _ = result
        assert r == 60

    def test_fallback_for_nonstandard_resolution(self):
        # 1600x900 is not a VIC — should fall back to something close
        result = find_best_vic_resolution(1600, 900, 60)
        assert result is not None

    def test_all_vic_calculations_break_returns_none(self):
        # Patch at the source — vic.py imports it locally inside the function
        with patch("src.edid.timing.check_if_calculation_breaks", return_value=True):
            result = find_best_vic_resolution(1920, 1080, 60)
        assert result is None

    def test_vic_code_is_in_dict(self):
        result = find_best_vic_resolution(1920, 1080, 60)
        assert result is not None
        _, _, _, vic, _ = result
        assert vic in VIC_RESOLUTIONS

    def test_aspect_ratio_preference(self):
        # 16:9 target — should prefer 16:9 VIC over 4:3
        result = find_best_vic_resolution(1920, 1080, 60)
        assert result is not None
        w, h, _, _, _ = result
        assert abs(w / h - 16 / 9) < 0.1

    def test_prints_best_match(self, capsys):
        find_best_vic_resolution(1920, 1080, 60)
        out = capsys.readouterr().out
        assert "Best VIC match" in out
