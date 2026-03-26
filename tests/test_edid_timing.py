"""Tests for src/edid/timing.py"""

import pytest

from src.edid.timing import (
    calculate_checksum,
    check_if_calculation_breaks,
    get_pixel_clock_info,
)


class TestCalculateChecksum:
    def test_empty_bytes(self):
        assert calculate_checksum(b"") == 0

    def test_empty_bytearray(self):
        assert calculate_checksum(bytearray()) == 0

    def test_single_zero(self):
        assert calculate_checksum(b"\x00") == 0

    def test_single_nonzero(self):
        result = calculate_checksum(b"\x01")
        assert (1 + result) % 256 == 0
        assert result == 255

    def test_checksum_makes_sum_zero(self):
        data = bytes(range(127))
        cs = calculate_checksum(data)
        assert (sum(data) + cs) % 256 == 0

    def test_known_value(self):
        # sum=255, checksum should be 1
        assert calculate_checksum(b"\xff") == 1

    def test_bytearray_input(self):
        data = bytearray([0x10, 0x20, 0x30])
        cs = calculate_checksum(data)
        assert (sum(data) + cs) % 256 == 0

    def test_all_zeros_128_bytes(self):
        assert calculate_checksum(bytes(128)) == 0

    def test_overflow_wraps(self):
        # 256 bytes of 0x01 = sum 256, so checksum = (256 - 0) % 256 = 0
        data = bytes([0x01] * 256)
        assert calculate_checksum(data) == 0


class TestCheckIfCalculationBreaks:
    def test_low_res_does_not_break(self):
        assert check_if_calculation_breaks(640, 480, 60) is False

    def test_1080p60_does_not_break(self):
        assert check_if_calculation_breaks(1920, 1080, 60) is False

    def test_4320p120_breaks(self):
        # Very high resolution at high refresh rate should exceed limit
        assert check_if_calculation_breaks(7680, 4320, 120) is True

    def test_4k120_breaks(self):
        assert check_if_calculation_breaks(3840, 2160, 120) is True

    def test_720p60_does_not_break(self):
        assert check_if_calculation_breaks(1280, 720, 60) is False

    def test_hblank_min_80(self):
        # For very small widths, h_blank should be at least 80
        # width=100: int(100*0.08)=8 < 80, so h_blank=80
        assert check_if_calculation_breaks(100, 100, 60) is False

    def test_vblank_min_23(self):
        # height=100: int(100*0.025)=2 < 23, so v_blank=23
        assert check_if_calculation_breaks(100, 100, 60) is False

    def test_boundary_just_under(self):
        # pixel_clock = 65535 → does not break
        # Just verify it returns a bool
        result = check_if_calculation_breaks(1920, 1080, 60)
        assert isinstance(result, bool)


class TestGetPixelClockInfo:
    def test_returns_tuple_of_three(self):
        result = get_pixel_clock_info(1920, 1080, 60)
        assert len(result) == 3

    def test_1080p60_within_limit(self):
        mhz, max_mhz, would_break = get_pixel_clock_info(1920, 1080, 60)
        assert mhz > 0
        assert max_mhz == pytest.approx(655.35, rel=1e-3)
        assert would_break is False

    def test_4k120_exceeds_limit(self):
        mhz, max_mhz, would_break = get_pixel_clock_info(3840, 2160, 120)
        assert mhz > max_mhz
        assert would_break is True

    def test_max_mhz_constant(self):
        # max_mhz should always be 65535 * 10000 / 1_000_000
        _, max_mhz, _ = get_pixel_clock_info(640, 480, 60)
        assert max_mhz == pytest.approx(655.35, rel=1e-3)

    def test_pixel_clock_scales_with_refresh(self):
        mhz_60, _, _ = get_pixel_clock_info(1920, 1080, 60)
        mhz_30, _, _ = get_pixel_clock_info(1920, 1080, 30)
        assert mhz_60 > mhz_30

    def test_pixel_clock_scales_with_resolution(self):
        mhz_4k, _, _ = get_pixel_clock_info(3840, 2160, 60)
        mhz_1080, _, _ = get_pixel_clock_info(1920, 1080, 60)
        assert mhz_4k > mhz_1080

    def test_consistency_with_check_if_breaks(self):
        for w, h, r in [(1920, 1080, 60), (3840, 2160, 120), (1280, 720, 30)]:
            _, _, would_break = get_pixel_clock_info(w, h, r)
            assert would_break == check_if_calculation_breaks(w, h, r)
