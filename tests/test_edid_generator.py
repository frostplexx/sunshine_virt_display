"""Tests for src/edid/generator.py"""

import struct

from src.edid.generator import create_edid
from src.edid.timing import calculate_checksum


class TestCreateEdid:
    def test_returns_bytes(self):
        assert isinstance(create_edid(), bytes)

    def test_length_256(self):
        assert len(create_edid()) == 256

    def test_base_block_header(self):
        edid = create_edid()
        assert edid[0:8] == bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])

    def test_base_checksum_valid(self):
        edid = create_edid()
        assert sum(edid[0:128]) % 256 == 0

    def test_cea_checksum_valid(self):
        edid = create_edid()
        assert sum(edid[128:256]) % 256 == 0

    def test_edid_version(self):
        edid = create_edid()
        assert edid[18] == 1  # version 1
        assert edid[19] == 4  # revision 4

    def test_extension_flag(self):
        edid = create_edid()
        assert edid[126] == 1

    def test_cea_tag(self):
        edid = create_edid()
        assert edid[128] == 0x02
        assert edid[129] == 0x03

    def test_non_hdr_video_input(self):
        edid = create_edid(enable_hdr=False)
        assert edid[20] == 0xA5

    def test_hdr_video_input(self):
        edid = create_edid(enable_hdr=True)
        assert edid[20] == 0xB5

    def test_non_hdr_product_code(self):
        edid = create_edid(enable_hdr=False)
        code = struct.unpack_from("<H", edid, 10)[0]
        assert code == 0x5344

    def test_hdr_product_code(self):
        edid = create_edid(enable_hdr=True)
        code = struct.unpack_from("<H", edid, 10)[0]
        assert code == 0x4844

    def test_display_name_in_edid(self):
        edid = create_edid(display_name="TestDisp")
        # FC descriptor at bytes 72-89: [0x00,0x00,0x00,0xFC,0x00, <13 name bytes>]
        assert edid[75] == 0xFC
        name_bytes = edid[77:90]
        assert b"TestDisp" in name_bytes

    def test_display_name_truncated_to_13(self):
        edid = create_edid(display_name="A" * 20)
        name_bytes = edid[77:90]
        assert b"AAAAAAAAAAAAA" in name_bytes

    def test_hdr_colorimetry_block_present(self):
        edid = create_edid(enable_hdr=True)
        # Colorimetry block starts at offset 128+4=132
        assert edid[132] == 0xE3

    def test_non_hdr_no_colorimetry(self):
        edid = create_edid(enable_hdr=False)
        # First data block after cea header (offset 132) should NOT be 0xE3
        assert edid[132] != 0xE3

    def test_serial_encodes_resolution(self):
        edid = create_edid(width=1920, height=1080, refresh_rate=60)
        serial = struct.unpack_from("<I", edid, 12)[0]
        assert serial == (1920 << 16) | (1080 << 4) | (60 & 0x0F)

    def test_pixel_clock_nonzero(self):
        edid = create_edid()
        pc = struct.unpack_from("<H", edid, 54)[0]
        assert pc > 0

    def test_h_active_in_edid(self):
        edid = create_edid(width=1280, height=720, refresh_rate=60)
        h_active = edid[56] | ((edid[58] >> 4) << 8)
        assert h_active == 1280

    def test_v_active_in_edid(self):
        edid = create_edid(width=1280, height=720, refresh_rate=60)
        v_active = edid[59] | ((edid[61] >> 4) << 8)
        assert v_active == 720

    def test_different_resolutions_produce_different_edids(self):
        e1 = create_edid(width=1920, height=1080, refresh_rate=60)
        e2 = create_edid(width=1280, height=720, refresh_rate=60)
        assert e1 != e2

    def test_hdr_feature_support_byte(self):
        edid = create_edid(enable_hdr=True)
        assert edid[24] == 0x1A

    def test_non_hdr_feature_support_byte(self):
        edid = create_edid(enable_hdr=False)
        assert edid[24] == 0x1E

    def test_range_limits_descriptor(self):
        edid = create_edid(refresh_rate=60)
        # FD descriptor at bytes 90-107
        assert edid[93] == 0xFD

    def test_dummy_descriptor(self):
        edid = create_edid()
        # 10 descriptor at bytes 108-125
        assert edid[111] == 0x10

    def test_cea_support_flags(self):
        edid = create_edid()
        assert edid[131] == 0x70

    def test_screen_size_nonzero(self):
        edid = create_edid(width=1920, height=1080)
        assert edid[21] > 0
        assert edid[22] > 0

    def test_gamma(self):
        edid = create_edid()
        assert edid[23] == 220
