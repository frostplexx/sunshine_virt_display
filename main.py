#!/usr/bin/env python3
"""
Virtual Display Manager for Linux
Manages virtual displays by creating custom EDIDs and toggling display ports

This script must be run with sudo privileges.
Usage: echo "password" | sudo python3 main.py --connect --width 1920 --height 1080
"""

import os
import sys
from pathlib import Path

# Ensure the script directory is on the Python path for local imports
sys.path.insert(0, str(Path(__file__).parent.absolute()))

import argparse

from src import display


def ensure_root():
    if os.geteuid() != 0:
        print("Error: This script must be run as root (use sudo)")
        sys.exit(1)


def main():
    try:
        ensure_root()

        parser = argparse.ArgumentParser(
            description="Virtual Display Manager for Linux",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Connect with resolution from Sunshine
  sudo %(prog)s --connect --width 1920 --height 1080 --refresh-rate 60

  # Disconnect virtual display
  sudo %(prog)s --disconnect
        """,
        )

        _ = parser.add_argument(
            "--connect", action="store_true", help="Connect virtual display"
        )
        _ = parser.add_argument(
            "--disconnect", action="store_true", help="Disconnect virtual display"
        )
        _ = parser.add_argument("--width", type=int, help="Display width in pixels")
        _ = parser.add_argument("--height", type=int, help="Display height in pixels")
        _ = parser.add_argument(
            "--refresh-rate",
            type=int,
            default=60,
            help="Refresh rate in Hz (default: 60)",
        )
        _ = parser.add_argument(
            "-d",
            "--device",
            type=str,
            default=None,
            metavar="CARD",
            help="DRM card to use for the virtual display (e.g. card1). "
                 "Auto-detected by default (card with most connected displays).",
        )

        args = parser.parse_args()

        if args.connect:
            if not args.width or not args.height:
                print(
                    "Error: --width and --height are required for --connect",
                    file=sys.stderr,
                )
                sys.exit(1)

            success = display.connect(args.width, args.height, args.refresh_rate, device=args.device)
            sys.exit(0 if success else 1)

        elif args.disconnect:
            success = display.disconnect()
            sys.exit(0 if success else 1)

        else:
            parser.print_help()
            sys.exit(1)

    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
