"""
EDID binary generator — builds a 256-byte EDID (base block + CEA-861 extension).
"""

import struct

from src.edid.timing import calculate_checksum


def create_edid(
    width=1920,
    height=1080,
    refresh_rate=60,
    enable_hdr=False,
    display_name="Custom Display",
):
    """
    Create EDID with custom settings.

    Args:
        width: Horizontal resolution
        height: Vertical resolution
        refresh_rate: Refresh rate in Hz
        enable_hdr: Enable HDR support
        display_name: Display product name (max 13 chars)
    """

    # EDID structure (128 bytes base block + 128 bytes CEA extension)
    edid = bytearray(256)

    # ===== BASE EDID BLOCK (128 bytes) =====

    # Header (8 bytes)
    edid[0:8] = [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00]

    # Manufacturer ID — "VHD" for Virtual HDR Display
    edid[8] = 0x56
    edid[9] = 0x24

    # Product code
    edid[10:12] = struct.pack("<H", 0x4844 if enable_hdr else 0x5344)

    # Serial number (unique per resolution/refresh)
    serial = (width << 16) | (height << 4) | (refresh_rate & 0x0F)
    edid[12:16] = struct.pack("<I", serial)

    # Week of manufacture, year
    edid[16] = 1   # Week 1
    edid[17] = 33  # 2023

    # EDID version
    edid[18] = 1  # Version 1
    edid[19] = 4  # Revision 4

    # Video input definition (digital)
    if enable_hdr:
        edid[20] = 0xB5  # Digital, 10-bit, DisplayPort
    else:
        edid[20] = 0xA5  # Digital, 8-bit, DisplayPort

    # Screen size (cm)
    diagonal_inches = ((width**2 + height**2) ** 0.5) / 96
    aspect_ratio = width / height
    h_size_cm = int((diagonal_inches * 2.54) / (1 + (1 / aspect_ratio) ** 2) ** 0.5)
    v_size_cm = int(h_size_cm / aspect_ratio)
    edid[21] = min(h_size_cm, 255)
    edid[22] = min(v_size_cm, 255)

    # Display gamma (2.2)
    edid[23] = 220

    # Feature support
    if enable_hdr:
        edid[24] = 0x1A  # RGB+YCbCr444, preferred timing, continuous
    else:
        edid[24] = 0x1E  # RGB 4:4:4, sRGB, preferred timing, continuous

    # Color characteristics (10 bytes)
    if enable_hdr:
        edid[25:35] = [0xEE, 0x91, 0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54]
    else:
        edid[25:35] = [0xEE, 0x91, 0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54]

    # Established timings
    edid[35:38] = [0x00, 0x00, 0x00]

    # Standard timings — all unused
    edid[38:54] = [0x01, 0x01] * 8

    # Detailed timing descriptor 1 (18 bytes) — custom resolution
    h_active = width
    v_active = height
    h_blank = max(80, int(width * 0.08))
    h_total = h_active + h_blank

    v_blank_estimate = max(23, int(height * 0.025))
    pixel_clock_hz = h_total * (v_active + v_blank_estimate) * refresh_rate

    v_blank = int((pixel_clock_hz / (h_total * refresh_rate)) - v_active)
    v_blank = max(23, v_blank)

    pixel_clock_hz = h_total * (v_active + v_blank) * refresh_rate
    pixel_clock = min(int(pixel_clock_hz / 10000), 65535)
    edid[54:56] = struct.pack("<H", pixel_clock)

    edid[56] = h_active & 0xFF
    edid[57] = h_blank & 0xFF
    edid[58] = ((h_active >> 8) << 4) | (h_blank >> 8)

    edid[59] = v_active & 0xFF
    edid[60] = v_blank & 0xFF
    edid[61] = ((v_active >> 8) << 4) | (v_blank >> 8)

    h_sync_offset = int(h_blank * 0.2)
    h_sync_width = int(h_blank * 0.4)
    v_sync_offset = 2
    v_sync_width = 6

    edid[62] = h_sync_offset & 0xFF
    edid[63] = h_sync_width & 0xFF
    edid[64] = ((v_sync_offset & 0x0F) << 4) | (v_sync_width & 0x0F)
    edid[65] = (
        (((h_sync_offset >> 8) & 0x03) << 6)
        | (((h_sync_width >> 8) & 0x03) << 4)
        | (((v_sync_offset >> 4) & 0x03) << 2)
        | ((v_sync_width >> 4) & 0x03)
    )

    # Image size (mm)
    h_size_mm = h_size_cm * 10
    v_size_mm = v_size_cm * 10
    edid[66] = h_size_mm & 0xFF
    edid[67] = v_size_mm & 0xFF
    edid[68] = ((h_size_mm >> 8) << 4) | (v_size_mm >> 8)

    edid[69] = 0     # H border
    edid[70] = 0     # V border
    edid[71] = 0x18  # Non-interlaced, digital separate sync

    # Display product name descriptor
    name_bytes = display_name[:13].encode("ascii")
    name_bytes = name_bytes + b" " * (13 - len(name_bytes))
    edid[72:90] = [0x00, 0x00, 0x00, 0xFC, 0x00] + list(name_bytes)

    # Display range limits
    min_v_rate = max(24, refresh_rate - 20)
    max_v_rate = refresh_rate + 20
    edid[90:108] = [
        0x00, 0x00, 0x00, 0xFD, 0x00,
        min_v_rate, max_v_rate,
        30, 160,   # H rate (30-160 kHz)
        220,       # Max pixel clock (2200 MHz)
        0x00, 0x0A,
        0x20, 0x20, 0x20, 0x20, 0x20, 0x20,
    ]

    # Dummy descriptor
    edid[108:126] = [0x00, 0x00, 0x00, 0x10, 0x00] + [0x00] * 13

    # Extension flag
    edid[126] = 1  # 1 extension block

    # Checksum for base block
    edid[127] = calculate_checksum(edid[0:127])

    # ===== CEA-861 EXTENSION BLOCK (128 bytes) =====

    cea_start = 128

    edid[cea_start] = 0x02      # CEA-861 tag
    edid[cea_start + 1] = 0x03  # Revision 3

    offset = cea_start + 4

    if enable_hdr:
        # Colorimetry Data Block
        edid[offset] = 0xE3
        edid[offset + 1] = 0x05  # Extended tag = Colorimetry
        edid[offset + 2] = 0xE0  # BT2020RGB, BT2020YCC, BT2020cYCC
        edid[offset + 3] = 0x00
        offset += 4

        # HDR Static Metadata Data Block
        edid[offset] = 0xE6
        edid[offset + 1] = 0x06  # Extended tag = HDR Static Metadata
        edid[offset + 2] = 0x07  # SDR + HDR + PQ
        edid[offset + 3] = 0x01  # Static metadata descriptor type 1
        edid[offset + 4] = 0x78  # Max luminance: 1000 cd/m²
        edid[offset + 5] = 0x5A  # Max frame-avg: 400 cd/m²
        edid[offset + 6] = 0x32  # Min luminance: 0.05 cd/m²
        offset += 7

    # Video Capability Data Block
    edid[offset] = 0xE2
    edid[offset + 1] = 0x00  # Extended tag = Video Capability
    edid[offset + 2] = 0x00
    offset += 3

    # HDMI Forum Vendor Specific Data Block
    edid[offset] = 0x67
    edid[offset + 1] = 0xD8  # IEEE OUI for HDMI Forum
    edid[offset + 2] = 0x5D
    edid[offset + 3] = 0xC4
    edid[offset + 4] = 0x01  # Version
    edid[offset + 5] = 0x78  # Max TMDS: 600 MHz
    edid[offset + 6] = 0x00
    edid[offset + 7] = 0x00
    offset += 8

    # DTD offset
    edid[cea_start + 2] = offset - cea_start

    # Support flags
    edid[cea_start + 3] = 0x70  # Underscan, Basic Audio, YCbCr 4:4:4

    # Duplicate DTD from base block
    if offset + 18 <= 255:
        for i in range(18):
            edid[offset + i] = edid[54 + i]
        offset += 18

    # Pad remaining
    while offset < 255:
        edid[offset] = 0x00
        offset += 1

    # CEA checksum
    edid[255] = calculate_checksum(edid[128:255])

    return bytes(edid)
