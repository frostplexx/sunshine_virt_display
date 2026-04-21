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


def calculate_checksum(data):
    """Calculate EDID checksum (sum of all bytes must be 0 mod 256)"""
    return (256 - (sum(data) % 256)) % 256


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
        description="Generate custom EDID with configurable settings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Interactive mode
  %(prog)s -r 1920x1080 --hz 60               # 1080p@60Hz with HDR
  %(prog)s -r 2560x1440 --hz 144              # 1440p@144Hz with HDR
  %(prog)s -r 3840x2160 --hz 120 --no-hdr     # 4K@120Hz without HDR
  %(prog)s -r 1280x800 --hz 90 -o deck.bin    # Steam Deck specs
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
