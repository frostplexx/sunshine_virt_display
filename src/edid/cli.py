"""
Interactive and command-line interface for standalone EDID generation.
"""

import argparse
import sys

from src.edid.generator import create_edid
from src.edid.timing import check_if_calculation_breaks
from src.edid.vic import find_best_vic_resolution

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

COMMON_REFRESH_RATES = {
    "1": 60,
    "2": 75,
    "3": 90,
    "4": 120,
    "5": 144,
    "6": 165,
    "7": 240,
}


def interactive_mode():
    """Interactive mode for selecting options."""
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
    """Generate and output EDID binary."""
    parser = argparse.ArgumentParser(
        description="Generate custom EDID with configurable settings and automatic VIC fallback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                         # Interactive mode
  %(prog)s -r 1920x1080 --hz 60                    # 1080p@60Hz with HDR
  %(prog)s -r 2560x1440 --hz 144                   # 1440p@144Hz
  %(prog)s -r 3840x2160 --hz 240 --no-hdr          # Would exceed limits, auto-fallback to VIC
  %(prog)s -r 1920x1080 --hz 120 --use-vic         # Force VIC resolution matching
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
        help="Force use of the closest VIC standard resolution",
    )

    args = parser.parse_args()

    if args.interactive or (not args.resolution and not args.refresh_rate):
        width, height, refresh_rate, enable_hdr, display_name, output_file = (
            interactive_mode()
        )
    else:
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

        if width < 640 or width > 7680:
            print(f"Error: Width {width} out of range (640-7680)")
            sys.exit(1)
        if height < 480 or height > 4320:
            print(f"Error: Height {height} out of range (480-4320)")
            sys.exit(1)
        if refresh_rate < 24 or refresh_rate > 240:
            print(f"Error: Refresh rate {refresh_rate} out of range (24-240)")
            sys.exit(1)

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

            if not (
                args.interactive or (not args.resolution and not args.refresh_rate)
            ):
                width, height, refresh_rate = vic_width, vic_height, vic_refresh
                print(
                    f"\nAutomatically using VIC {vic_code}: {width}x{height} @ {refresh_rate}Hz"
                )
            else:
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

    print("\nFirst 32 bytes (hex):")
    hex_str = " ".join(f"{b:02X}" for b in edid[0:32])
    print(f"  {hex_str}")
    print("=" * 60)


if __name__ == "__main__":
    main()
