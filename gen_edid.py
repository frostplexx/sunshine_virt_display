#!/usr/bin/env python3
"""
Interactive EDID Generator with Steam Deck OLED characteristics
Supports custom resolution, refresh rate, and HDR settings
"""

import struct
import sys
import argparse

# Common resolution presets
COMMON_RESOLUTIONS = {
    "1": ("720p", 1280, 720),
    "2": ("1080p", 1920, 1080),
    "3": ("1440p", 2560, 1440),
    "4": ("4K", 3840, 2160),
    "5": ("UWQHD", 3440, 1440),
    "6": ("Steam Deck (landscape)", 1280, 800),
    "7": ("Steam Deck (portrait)", 800, 1280),
    "8": ("WUXGA", 1920, 1200),
    "9": ("WQHD", 2560, 1600),
}

# Common refresh rates
COMMON_REFRESH_RATES = {
    "1": 60,
    "2": 75,
    "3": 90,
    "4": 120,
    "5": 144,
    "6": 165,
    "7": 240,
}

# CEA-861 Video Identification Code (VIC) standard resolutions
# Complete list from https://en.wikipedia.org/wiki/Extended_Display_Identification_Data
# Format: VIC: (width, height, refresh_rate, name)
# Note: Using integer refresh rates for interlaced (i) formats, actual rates like 59.94 rounded to 60
VIC_RESOLUTIONS = {
    1: (640, 480, 60, "DMT0659"),
    2: (720, 480, 60, "480p"),
    3: (720, 480, 60, "480pH"),
    4: (1280, 720, 60, "720p"),
    5: (1920, 1080, 60, "1080i"),
    6: (1440, 480, 60, "480i"),
    7: (1440, 480, 60, "480iH"),
    8: (1440, 240, 60, "240p"),
    9: (1440, 240, 60, "240pH"),
    10: (2880, 480, 60, "480i4x"),
    11: (2880, 480, 60, "480i4xH"),
    12: (2880, 240, 60, "240p4x"),
    13: (2880, 240, 60, "240p4xH"),
    14: (1440, 480, 60, "480p2x"),
    15: (1440, 480, 60, "480p2xH"),
    16: (1920, 1080, 60, "1080p"),
    17: (720, 576, 50, "576p"),
    18: (720, 576, 50, "576pH"),
    19: (1280, 720, 50, "720p50"),
    20: (1920, 1080, 50, "1080i25"),
    21: (1440, 576, 50, "576i"),
    22: (1440, 576, 50, "576iH"),
    23: (1440, 288, 50, "288p"),
    24: (1440, 288, 50, "288pH"),
    25: (2880, 576, 50, "576i4x"),
    26: (2880, 576, 50, "576i4xH"),
    27: (2880, 288, 50, "288p4x"),
    28: (2880, 288, 50, "288p4xH"),
    29: (1440, 576, 50, "576p2x"),
    30: (1440, 576, 50, "576p2xH"),
    31: (1920, 1080, 50, "1080p50"),
    32: (1920, 1080, 24, "1080p24"),
    33: (1920, 1080, 25, "1080p25"),
    34: (1920, 1080, 30, "1080p30"),
    35: (2880, 480, 60, "480p4x"),
    36: (2880, 480, 60, "480p4xH"),
    37: (2880, 576, 50, "576p4x"),
    38: (2880, 576, 50, "576p4xH"),
    39: (1920, 1080, 50, "1080i25_2"),
    40: (1920, 1080, 100, "1080i50"),
    41: (1280, 720, 100, "720p100"),
    42: (720, 576, 100, "576p100"),
    43: (720, 576, 100, "576p100H"),
    44: (1440, 576, 100, "576i50"),
    45: (1440, 576, 100, "576i50H"),
    46: (1920, 1080, 120, "1080i60"),
    47: (1280, 720, 120, "720p120"),
    48: (720, 480, 120, "480p119"),
    49: (720, 480, 120, "480p119H"),
    50: (1440, 480, 120, "480i59"),
    51: (1440, 480, 120, "480i59H"),
    52: (720, 576, 200, "576p200"),
    53: (720, 576, 200, "576p200H"),
    54: (1440, 288, 200, "576i100"),
    55: (1440, 288, 200, "576i100H"),
    56: (720, 480, 240, "480p239"),
    57: (720, 480, 240, "480p239H"),
    58: (1440, 240, 240, "480i119"),
    59: (1440, 240, 240, "480i119H"),
    60: (1280, 720, 24, "720p24"),
    61: (1280, 720, 25, "720p25"),
    62: (1280, 720, 30, "720p30"),
    63: (1920, 1080, 120, "1080p120"),
    64: (1920, 1080, 100, "1080p100"),
    65: (1280, 720, 24, "720p24_64:27"),
    66: (1280, 720, 25, "720p25_64:27"),
    67: (1280, 720, 30, "720p30_64:27"),
    68: (1280, 720, 50, "720p50_64:27"),
    69: (1280, 720, 60, "720p_64:27"),
    70: (1280, 720, 100, "720p100_64:27"),
    71: (1280, 720, 120, "720p120_64:27"),
    72: (1920, 1080, 24, "1080p24_64:27"),
    73: (1920, 1080, 25, "1080p25_64:27"),
    74: (1920, 1080, 30, "1080p30_64:27"),
    75: (1920, 1080, 50, "1080p50_64:27"),
    76: (1920, 1080, 60, "1080p_64:27"),
    77: (1920, 1080, 100, "1080p100_64:27"),
    78: (1920, 1080, 120, "1080p120_64:27"),
    79: (1680, 720, 24, "720p2x24"),
    80: (1680, 720, 25, "720p2x25"),
    81: (1680, 720, 30, "720p2x30"),
    82: (1680, 720, 50, "720p2x50"),
    83: (1680, 720, 60, "720p2x"),
    84: (1680, 720, 100, "720p2x100"),
    85: (1680, 720, 120, "720p2x120"),
    86: (2560, 1080, 24, "1080p2x24"),
    87: (2560, 1080, 25, "1080p2x25"),
    88: (2560, 1080, 30, "1080p2x30"),
    89: (2560, 1080, 50, "1080p2x50"),
    90: (2560, 1080, 60, "1080p2x"),
    91: (2560, 1080, 100, "1080p2x100"),
    92: (2560, 1080, 120, "1080p2x120"),
    93: (3840, 2160, 24, "2160p24"),
    94: (3840, 2160, 25, "2160p25"),
    95: (3840, 2160, 30, "2160p30"),
    96: (3840, 2160, 50, "2160p50"),
    97: (3840, 2160, 60, "2160p60"),
    98: (4096, 2160, 24, "2160p24_256:135"),
    99: (4096, 2160, 25, "2160p25_256:135"),
    100: (4096, 2160, 30, "2160p30_256:135"),
    101: (4096, 2160, 50, "2160p50_256:135"),
    102: (4096, 2160, 60, "2160p_256:135"),
    103: (3840, 2160, 24, "2160p24_64:27"),
    104: (3840, 2160, 25, "2160p25_64:27"),
    105: (3840, 2160, 30, "2160p30_64:27"),
    106: (3840, 2160, 50, "2160p50_64:27"),
    107: (3840, 2160, 60, "2160p_64:27"),
    108: (1280, 720, 48, "720p48"),
    109: (1280, 720, 48, "720p48_64:27"),
    110: (1680, 720, 48, "720p2x48"),
    111: (1920, 1080, 48, "1080p48"),
    112: (1920, 1080, 48, "1080p48_64:27"),
    113: (2560, 1080, 48, "1080p2x48"),
    114: (3840, 2160, 48, "2160p48"),
    115: (4096, 2160, 48, "2160p48_256:135"),
    116: (3840, 2160, 48, "2160p48_64:27"),
    117: (3840, 2160, 100, "2160p100"),
    118: (3840, 2160, 120, "2160p120"),
    119: (3840, 2160, 100, "2160p100_64:27"),
    120: (3840, 2160, 120, "2160p120_64:27"),
    121: (5120, 2160, 24, "2160p2x24"),
    122: (5120, 2160, 25, "2160p2x25"),
    123: (5120, 2160, 30, "2160p2x30"),
    124: (5120, 2160, 48, "2160p2x48"),
    125: (5120, 2160, 50, "2160p2x50"),
    126: (5120, 2160, 60, "2160p2x"),
    127: (5120, 2160, 100, "2160p2x100"),
    193: (5120, 2160, 120, "2160p2x120"),
    194: (7680, 4320, 24, "4320p24"),
    195: (7680, 4320, 25, "4320p25"),
    196: (7680, 4320, 30, "4320p30"),
    197: (7680, 4320, 48, "4320p48"),
    198: (7680, 4320, 50, "4320p50"),
    199: (7680, 4320, 60, "4320p"),
    200: (7680, 4320, 100, "4320p100"),
    201: (7680, 4320, 120, "4320p120"),
    202: (7680, 4320, 24, "4320p24_64:27"),
    203: (7680, 4320, 25, "4320p25_64:27"),
    204: (7680, 4320, 30, "4320p30_64:27"),
    205: (7680, 4320, 48, "4320p48_64:27"),
    206: (7680, 4320, 50, "4320p50_64:27"),
    207: (7680, 4320, 60, "4320p_64:27"),
    208: (7680, 4320, 100, "4320p100_64:27"),
    209: (7680, 4320, 120, "4320p120_64:27"),
    210: (10240, 4320, 24, "4320p2x24"),
    211: (10240, 4320, 25, "4320p2x25"),
    212: (10240, 4320, 30, "4320p2x30"),
    213: (10240, 4320, 48, "4320p2x48"),
    214: (10240, 4320, 50, "4320p2x50"),
    215: (10240, 4320, 60, "4320p2x"),
    216: (10240, 4320, 100, "4320p2x100"),
    217: (10240, 4320, 120, "4320p2x120"),
    218: (4096, 2160, 100, "2160p100_256:135"),
    219: (4096, 2160, 120, "2160p120_256:135"),
}


def find_best_vic_resolution(target_width, target_height, target_refresh):
    """
    Find the next best VIC resolution from the standard list.
    Prioritizes: 1) Refresh rate, 2) Resolution (if aspect is reasonable), 3) Aspect ratio

    Args:
        target_width: Desired horizontal resolution
        target_height: Desired vertical resolution
        target_refresh: Desired refresh rate in Hz

    Returns:
        Tuple of (width, height, refresh_rate, vic_code, name) or None if no match
    """
    target_pixels = target_width * target_height
    target_aspect = target_width / target_height

    # Create a list of (vic, score, width, height, refresh, name) tuples
    candidates = []

    for vic, (width, height, refresh, name) in VIC_RESOLUTIONS.items():
        pixels = width * height
        aspect = width / height

        # Skip VIC resolutions that would also break the calculation
        if check_if_calculation_breaks(width, height, refresh):
            continue

        # Calculate score components:
        # 1. Refresh rate difference (highest priority - weighted at 100000)
        refresh_diff = abs(refresh - target_refresh)

        # 2. Resolution difference (high priority - weighted at 1000)
        #    We want to maximize resolution when possible
        resolution_diff = abs(pixels - target_pixels) / target_pixels

        # 3. Aspect ratio difference (medium priority - weighted at 500)
        #    But penalize extreme aspect ratio mismatches heavily
        aspect_diff = abs(aspect - target_aspect)
        aspect_penalty = aspect_diff * 500

        # Add extra penalty for extreme aspect mismatches (>0.3 difference)
        if aspect_diff > 0.3:
            aspect_penalty += (aspect_diff - 0.3) * 2000

        # Combined score: prioritize refresh rate >> resolution >> aspect ratio
        score = (refresh_diff * 100000) + (resolution_diff * 1000) + aspect_penalty

        candidates.append((vic, score, width, height, refresh, name, aspect))

    # Sort by score (lower is better)
    candidates.sort(key=lambda x: x[1])

    if candidates:
        best = candidates[0]
        vic, score, width, height, refresh, name, aspect = best
        print(f"\nBest VIC match: VIC {vic} - {name}")
        print(f"  Resolution: {width}x{height} @ {refresh}Hz (aspect: {aspect:.2f})")
        print(
            f"  Requested:  {target_width}x{target_height} @ {target_refresh}Hz (aspect: {target_aspect:.2f})"
        )
        return (width, height, refresh, vic, name)

    return None


def calculate_checksum(data):
    """Calculate EDID checksum (sum of all bytes must be 0 mod 256)"""
    return (256 - (sum(data) % 256)) % 256


def check_if_calculation_breaks(width, height, refresh_rate):
    """
    Check if the given resolution/refresh rate combination would break EDID calculation.
    Returns True if it would break, False otherwise.

    The calculation breaks when pixel clock exceeds the maximum value (655.35 MHz).
    """
    # Calculate blanking intervals (same as in create_edid)
    h_blank = max(80, int(width * 0.08))
    h_total = width + h_blank

    # Estimate v_blank
    v_blank_estimate = max(23, int(height * 0.025))
    pixel_clock_hz = h_total * (height + v_blank_estimate) * refresh_rate

    # EDID pixel clock is in units of 10 kHz, max value is 65535
    pixel_clock = int(pixel_clock_hz / 10000)
    max_pixel_clock = 65535

    # Check if pixel clock exceeds maximum
    if pixel_clock > max_pixel_clock:
        return True

    return False


def get_pixel_clock_info(width, height, refresh_rate):
    """
    Get detailed pixel clock information for diagnostics.
    Returns (pixel_clock_mhz, max_mhz, would_break)
    """
    h_blank = max(80, int(width * 0.08))
    h_total = width + h_blank
    v_blank_estimate = max(23, int(height * 0.025))
    pixel_clock_hz = h_total * (height + v_blank_estimate) * refresh_rate
    pixel_clock = int(pixel_clock_hz / 10000)
    max_pixel_clock = 65535

    pixel_clock_mhz = pixel_clock_hz / 1000000
    max_mhz = max_pixel_clock * 10000 / 1000000
    would_break = pixel_clock > max_pixel_clock

    return (pixel_clock_mhz, max_mhz, would_break)


def create_edid(
    width=1920,
    height=1080,
    refresh_rate=60,
    enable_hdr=False,
    display_name="Custom Display",
):
    """
    Create EDID with custom settings

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

    # Manufacturer ID (3 bytes) - "VHD" for Virtual HDR Display
    # Manufacturer ID encoding: 5-bit compressed ASCII (A=1, B=2, etc.)
    # V=22, H=8, D=4: 0x5624 in big-endian
    edid[8] = 0x56
    edid[9] = 0x24

    # Product code (2 bytes) - Use refresh rate to make it unique
    edid[10:12] = struct.pack("<H", 0x4844 if enable_hdr else 0x5344)  # 'HD' or 'SD'

    # Serial number (4 bytes) - Make unique based on resolution and refresh
    serial = (width << 16) | (height << 4) | (refresh_rate & 0x0F)
    edid[12:16] = struct.pack("<I", serial)

    # Week of manufacture, year
    edid[16] = 1  # Week 1
    edid[17] = 33  # 2023

    # EDID version
    edid[18] = 1  # Version 1
    edid[19] = 4  # Revision 4

    # Video input definition (digital)
    # Bit 7: 1 = Digital input
    # Bits 6-4: Color bit depth (0=undefined, 1=6bit, 2=8bit, 3=10bit, 4=12bit)
    # Bits 3-0: Video interface (0=undefined, 5=DisplayPort)
    if enable_hdr:
        edid[20] = 0xB5  # Digital, 10-bit (0x80 | 0x30 | 0x05), DisplayPort
    else:
        edid[20] = 0xA5  # Digital, 8-bit (0x80 | 0x20 | 0x05), DisplayPort

    # Screen size (cm) - calculate based on common display sizes
    diagonal_inches = ((width**2 + height**2) ** 0.5) / 96  # Assume 96 DPI
    aspect_ratio = width / height
    h_size_cm = int((diagonal_inches * 2.54) / (1 + (1 / aspect_ratio) ** 2) ** 0.5)
    v_size_cm = int(h_size_cm / aspect_ratio)
    edid[21] = min(h_size_cm, 255)
    edid[22] = min(v_size_cm, 255)

    # Display gamma (2.2)
    edid[23] = 220  # (gamma * 100) - 100

    # Feature support
    # Bit 7: DPMS standby supported
    # Bit 6: DPMS suspend supported
    # Bit 5: DPMS active-off supported
    # Bit 4-3: Display type (00=RGB, 01=RGB+YCrCb 4:4:4, 10=RGB+YCrCb 4:2:2, 11=RGB+YCrCb both)
    # Bit 2: Standard sRGB color space
    # Bit 1: Preferred timing mode (first detailed timing)
    # Bit 0: Continuous frequency (GTF support)
    if enable_hdr:
        # For HDR: RGB 4:4:4 + YCbCr 4:4:4, preferred timing, NO sRGB (using BT.2020)
        edid[24] = 0x1A  # No DPMS (virtual), RGB+YCbCr444, preferred timing, continuous
    else:
        edid[24] = 0x1E  # No DPMS, RGB 4:4:4, sRGB, preferred timing, continuous

    # Color characteristics (10 bytes) - Wide gamut for HDR, sRGB otherwise
    if enable_hdr:
        # DCI-P3-ish gamut
        edid[25:35] = [0xEE, 0x91, 0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54]
    else:
        # sRGB gamut
        edid[25:35] = [0xEE, 0x91, 0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54]

    # Established timings (3 bytes)
    edid[35:38] = [0x00, 0x00, 0x00]

    # Standard timings (16 bytes) - all unused
    edid[38:54] = [0x01, 0x01] * 8

    # Detailed timing descriptor 1 (18 bytes) - custom resolution
    # Calculate blanking intervals (use CVT-RB v2 reduced blanking for accuracy)
    h_active = width
    v_active = height

    # Horizontal blanking: 80 pixels minimum for reduced blanking
    # Use 8-10% of active width for better compatibility
    h_blank = max(80, int(width * 0.08))

    # Vertical blanking: Calculate to achieve exact refresh rate
    # Pixel Clock (Hz) = (H_Active + H_Blank) × (V_Active + V_Blank) × Refresh_Rate
    # Solve for V_Blank to get exact refresh rate
    h_total = h_active + h_blank

    # Target pixel clock in Hz
    # Start with estimated v_blank
    v_blank_estimate = max(23, int(height * 0.025))  # ~2.5% blanking, minimum 23 lines
    pixel_clock_hz = h_total * (v_active + v_blank_estimate) * refresh_rate

    # Recalculate v_blank for exact refresh rate
    # V_Blank = (Pixel_Clock / (H_Total × Refresh_Rate)) - V_Active
    v_blank = int((pixel_clock_hz / (h_total * refresh_rate)) - v_active)
    v_blank = max(23, v_blank)  # Minimum 23 lines for sync

    # Final pixel clock with correct v_blank
    pixel_clock_hz = h_total * (v_active + v_blank) * refresh_rate

    # EDID pixel clock is in units of 10 kHz
    pixel_clock = int(pixel_clock_hz / 10000)
    # Cap at 65535 (max value for 16-bit)
    pixel_clock = min(pixel_clock, 65535)
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

    edid[69] = 0  # H border
    edid[70] = 0  # V border
    edid[71] = 0x18  # Non-interlaced, digital separate sync

    # Display product name descriptor
    name_bytes = display_name[:13].encode("ascii")
    name_bytes = name_bytes + b" " * (13 - len(name_bytes))
    edid[72:90] = [0x00, 0x00, 0x00, 0xFC, 0x00] + list(name_bytes)

    # Display range limits
    min_v_rate = max(24, refresh_rate - 20)
    max_v_rate = refresh_rate + 20
    edid[90:108] = [
        0x00,
        0x00,
        0x00,
        0xFD,
        0x00,
        min_v_rate,
        max_v_rate,  # V rate
        30,
        160,  # H rate (30-160 kHz)
        220,  # Max pixel clock (2200 MHz)
        0x00,
        0x0A,
        0x20,
        0x20,
        0x20,
        0x20,
        0x20,
        0x20,
    ]

    # Dummy descriptor
    edid[108:126] = [0x00, 0x00, 0x00, 0x10, 0x00] + [0x00] * 13

    # Extension flag
    edid[126] = 1  # 1 extension block

    # Checksum for base block
    edid[127] = calculate_checksum(edid[0:127])

    # ===== CEA-861 EXTENSION BLOCK (128 bytes) =====

    cea_start = 128

    # CEA header
    edid[cea_start] = 0x02  # CEA-861 tag
    edid[cea_start + 1] = 0x03  # Revision 3

    # Data block collection starts at byte 4
    offset = cea_start + 4

    # Data blocks for HDR
    if enable_hdr:
        # Colorimetry Data Block (4 bytes total)
        # Header byte: bits 7-5 = Tag (7 = Extended), bits 4-0 = Length (3)
        edid[offset] = 0xE3  # Tag=7, Length=3
        edid[offset + 1] = 0x05  # Extended tag = Colorimetry
        edid[offset + 2] = 0xE0  # Bit 7=BT2020RGB, Bit 6=BT2020YCC, Bit 5=BT2020cYCC
        edid[offset + 3] = 0x00  # Additional gamut metadata
        offset += 4

        # HDR Static Metadata Data Block (7 bytes total)
        # Header byte: bits 7-5 = Tag (7 = Extended), bits 4-0 = Length (6)
        edid[offset] = 0xE6  # Tag=7, Length=6
        edid[offset + 1] = 0x06  # Extended tag = HDR Static Metadata
        # EOTF (Electro-Optical Transfer Function) byte:
        # Bit 0: Traditional Gamma SDR (required for compatibility)
        # Bit 1: Traditional Gamma HDR
        # Bit 2: SMPTE ST 2084 (PQ) - THIS IS HDR10! Required for KDE/systems to detect HDR
        # Bit 3: Hybrid Log-Gamma (HLG)
        edid[offset + 2] = 0x07  # Enable SDR + HDR + PQ (0x01 | 0x02 | 0x04 = 0x07)
        edid[offset + 3] = 0x01  # Static metadata descriptor type 1
        edid[offset + 4] = 0x78  # Desired content max luminance: 120 (1000 cd/m²)
        edid[offset + 5] = (
            0x5A  # Desired content max frame-avg luminance: 90 (400 cd/m²)
        )
        edid[offset + 6] = 0x32  # Desired content min luminance: 50 (0.05 cd/m²)
        offset += 7

    # Video Capability Data Block (3 bytes total)
    # Header byte: bits 7-5 = Tag (7 = Extended), bits 4-0 = Length (2)
    edid[offset] = 0xE2  # Tag=7, Length=2
    edid[offset + 1] = 0x00  # Extended tag = Video Capability
    edid[offset + 2] = 0x00  # S_PT = 0, S_IT = 0, S_CE = 0, QS = 0, QY = 0
    offset += 3

    # HDMI Vendor Specific Data Block (HDMI 2.0+)
    # Header byte: bits 7-5 = Tag (3 = Vendor), bits 4-0 = Length (varies)
    # For HDMI Forum VSDB, we need at least 7 bytes
    edid[offset] = 0x67  # Tag=3, Length=7
    edid[offset + 1] = 0xD8  # IEEE OUI for HDMI Forum (0xC45DD8)
    edid[offset + 2] = 0x5D
    edid[offset + 3] = 0xC4
    edid[offset + 4] = 0x01  # Version
    edid[offset + 5] = 0x78  # Max TMDS Character Rate: 600 MHz
    edid[offset + 6] = 0x00  # SCDC Present, RR Capable, LTE Scrambling
    edid[offset + 7] = 0x00  # Flags
    offset += 8

    # Update DTD offset to current position
    edid[cea_start + 2] = offset - cea_start

    # Update support flags - Native DTD support
    edid[cea_start + 3] = (
        0x70  # Underscan, Basic Audio, YCbCr 4:4:4 (remove YCbCr 4:2:2 for stability)
    )

    # Add a Detailed Timing Descriptor in CEA block (same as base block)
    # This is critical for some drivers to work correctly with HDR
    if offset + 18 <= 255:
        # Copy the DTD from base block (bytes 54-71)
        for i in range(18):
            edid[offset + i] = edid[54 + i]
        offset += 18

    # Pad remaining space
    while offset < 255:
        edid[offset] = 0x00
        offset += 1

    # CEA checksum
    edid[255] = calculate_checksum(edid[128:255])

    return bytes(edid)


def interactive_mode():
    """Interactive mode for selecting options"""
    print("=" * 60)
    print("Interactive EDID Generator")
    print("=" * 60)

    # Resolution selection
    print("\nSelect Resolution:")
    for key, (name, w, h) in sorted(COMMON_RESOLUTIONS.items()):
        print(f"  {key}. {name} ({w}x{h})")
    print("  0. Custom resolution")

    res_choice = input("\nEnter choice (1-9 or 0 for custom): ").strip()

    if res_choice == "0":
        try:
            custom_res = input(
                "Enter resolution (WIDTHxHEIGHT, e.g., 1920x1080): "
            ).strip()
            width, height = map(int, custom_res.split("x"))
        except ValueError:
            print("Invalid format. Using 1920x1080")
            width, height = 1920, 1080
    elif res_choice in COMMON_RESOLUTIONS:
        _, width, height = COMMON_RESOLUTIONS[res_choice]
    else:
        print("Invalid choice. Using 1920x1080")
        width, height = 1920, 1080

    # Refresh rate selection
    print("\nSelect Refresh Rate:")
    for key, hz in sorted(COMMON_REFRESH_RATES.items()):
        print(f"  {key}. {hz} Hz")
    print("  0. Custom refresh rate")

    hz_choice = input("\nEnter choice (1-7 or 0 for custom): ").strip()

    if hz_choice == "0":
        try:
            refresh_rate = int(input("Enter refresh rate (Hz): ").strip())
        except ValueError:
            print("Invalid input. Using 60 Hz")
            refresh_rate = 60
    elif hz_choice in COMMON_REFRESH_RATES:
        refresh_rate = COMMON_REFRESH_RATES[hz_choice]
    else:
        print("Invalid choice. Using 60 Hz")
        refresh_rate = 60

    # HDR selection
    print("\nEnable HDR?")
    print("  1. Yes (HDR10, BT.2020, 10-bit)")
    print("  2. No (Standard SDR)")

    hdr_choice = input("\nEnter choice (1 or 2): ").strip()
    enable_hdr = hdr_choice != "2"

    # Display name
    display_name = input(
        "\nEnter display name (max 13 chars, or press Enter for 'Custom Display'): "
    ).strip()
    if not display_name:
        display_name = "Custom Display"
    display_name = display_name[:13]

    # Output filename
    output_file = input(
        "\nEnter output filename (or press Enter for 'edid.bin'): "
    ).strip()
    if not output_file:
        output_file = "edid.bin"
    if not output_file.endswith(".bin"):
        output_file += ".bin"

    return width, height, refresh_rate, enable_hdr, display_name, output_file


def main():
    """Generate and output EDID binary"""
    parser = argparse.ArgumentParser(
        description="Generate custom EDID with configurable settings and automatic VIC fallback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                         # Interactive mode
  %(prog)s -r 1920x1080 --hz 60                    # 1080p@60Hz with HDR
  %(prog)s -r 2560x1440 --hz 144                   # 1440p@144Hz (uses custom resolution if valid)
  %(prog)s -r 3840x2160 --hz 240 --no-hdr          # Would exceed limits, auto-fallback to VIC
  %(prog)s -r 1920x1080 --hz 120 --use-vic         # Force VIC resolution matching

VIC Resolution Fallback:
  The generator will automatically fall back to the closest CEA-861 standard 
  resolution (VIC code) when the requested resolution/refresh rate combination 
  would exceed the EDID pixel clock limit (655.35 MHz). 
  
  Matching priority:
    1. Refresh rate (highest priority - maintains smoothness)
    2. Resolution (high priority - maintains detail)
    3. Aspect ratio (penalizes extreme mismatches)
  
  Use --use-vic to force VIC resolution matching even when not required.
        """,
    )

    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Run in interactive mode"
    )
    parser.add_argument(
        "-r", "--resolution", help="Display resolution (e.g., 1920x1080)"
    )
    parser.add_argument(
        "--hz",
        "--refresh-rate",
        type=int,
        dest="refresh_rate",
        help="Refresh rate in Hz",
    )
    parser.add_argument(
        "--no-hdr", action="store_false", dest="enable_hdr", help="Disable HDR support"
    )
    parser.add_argument(
        "-n",
        "--name",
        default="Custom Display",
        help="Display product name (max 13 chars)",
    )
    parser.add_argument(
        "-o", "--output", default="edid.bin", help="Output filename (default: edid.bin)"
    )
    parser.add_argument(
        "--use-vic",
        action="store_true",
        help="Force use of the closest VIC standard resolution (automatic fallback occurs when pixel clock exceeds limits)",
    )

    args = parser.parse_args()

    # If no arguments provided, or -i flag used, run interactive mode
    if args.interactive or (not args.resolution and not args.refresh_rate):
        width, height, refresh_rate, enable_hdr, display_name, output_file = (
            interactive_mode()
        )
    else:
        # Command-line mode
        if args.resolution:
            try:
                width, height = map(int, args.resolution.split("x"))
            except ValueError:
                print(
                    f"Error: Invalid resolution format '{args.resolution}'. Use format like 1920x1080"
                )
                sys.exit(1)
        else:
            width, height = 1920, 1080

        refresh_rate = args.refresh_rate if args.refresh_rate else 60
        enable_hdr = args.enable_hdr
        display_name = args.name[:13]
        output_file = args.output

        # Validate inputs
        if width < 640 or width > 7680:
            print(f"Error: Width {width} out of range (640-7680)")
            sys.exit(1)
        if height < 480 or height > 4320:
            print(f"Error: Height {height} out of range (480-4320)")
            sys.exit(1)
        if refresh_rate < 24 or refresh_rate > 240:
            print(f"Error: Refresh rate {refresh_rate} out of range (24-240)")
            sys.exit(1)

    # Check if calculation would break and use VIC fallback if needed
    will_break = check_if_calculation_breaks(width, height, refresh_rate)

    if will_break:
        print("\n" + "=" * 60)
        print("⚠️  WARNING: Resolution/refresh rate would exceed pixel clock limit!")
        print(f"   Requested: {width}x{height} @ {refresh_rate}Hz")
        print("   Finding best VIC standard resolution as fallback...")
        print("=" * 60)

        vic_result = find_best_vic_resolution(width, height, refresh_rate)

        if vic_result:
            vic_width, vic_height, vic_refresh, vic_code, vic_name = vic_result

            # In command-line mode with --use-vic or when it breaks, use VIC automatically
            if not (
                args.interactive or (not args.resolution and not args.refresh_rate)
            ):
                width, height, refresh_rate = vic_width, vic_height, vic_refresh
                print(
                    f"\nAutomatically using VIC {vic_code}: {width}x{height} @ {refresh_rate}Hz"
                )
            else:
                # In interactive mode, ask the user
                print(
                    f"\nRecommended VIC {vic_code}: {width}x{height} @ {refresh_rate}Hz"
                )
                use_vic = (
                    input("Use this VIC resolution? (y/n, default=y): ").strip().lower()
                )

                if use_vic != "n":
                    width, height, refresh_rate = vic_width, vic_height, vic_refresh
                    print(f"Using VIC {vic_code} standard resolution")
                else:
                    print(
                        "⚠️  Continuing with custom resolution (may not work correctly)"
                    )
        else:
            print("\n⚠️  ERROR: No suitable VIC resolution found!")
            print("   The requested resolution may not work correctly.")
    elif args.use_vic:
        # Only use VIC if explicitly requested and calculation doesn't break
        print("\n" + "=" * 60)
        print("Finding best VIC resolution (--use-vic flag)...")
        print("=" * 60)

        vic_result = find_best_vic_resolution(width, height, refresh_rate)
        if vic_result:
            vic_width, vic_height, vic_refresh, vic_code, vic_name = vic_result
            width, height, refresh_rate = vic_width, vic_height, vic_refresh
            print(
                f"\nUsing VIC {vic_code} standard resolution: {width}x{height} @ {refresh_rate}Hz"
            )

    # Generate EDID
    print("\n" + "=" * 60)
    print("Generating EDID...")
    print("=" * 60)

    edid = create_edid(width, height, refresh_rate, enable_hdr, display_name)

    # Write to file
    with open(output_file, "wb") as f:
        f.write(edid)

    print(f"\n✓ Generated EDID: {output_file}")
    print(f"  Resolution: {width}x{height} @ {refresh_rate}Hz")
    print(f"  Display Name: {display_name}")
    print(f"  HDR: {'Enabled' if enable_hdr else 'Disabled'}")
    if enable_hdr:
        print(f"    - BT.2020 RGB color space")
        print(f"    - HDR10 (PQ/ST 2084)")
        print(f"    - 10-bit color depth")
        print(f"    - Max luminance: 1000 cd/m²")
        print(f"    - Max frame avg: 400 cd/m²")
        print(f"    - Min luminance: 0.05 cd/m²")
    print(f"  File Size: {len(edid)} bytes")
    print("\n" + "=" * 60)

    # Show first 32 bytes as hex
    print("\nFirst 32 bytes (hex):")
    hex_str = " ".join(f"{b:02X}" for b in edid[0:32])
    print(f"  {hex_str}")
    print("=" * 60)


if __name__ == "__main__":
    main()
