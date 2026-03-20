"""
Pixel clock calculations and EDID checksum utilities.
"""


def calculate_checksum(data):
    """Calculate EDID checksum (sum of all bytes must be 0 mod 256)."""
    return (256 - (sum(data) % 256)) % 256


def check_if_calculation_breaks(width, height, refresh_rate):
    """
    Check if the given resolution/refresh rate combination would exceed
    the EDID pixel clock limit (655.35 MHz).
    Returns True if it would break.
    """
    h_blank = max(80, int(width * 0.08))
    h_total = width + h_blank
    v_blank_estimate = max(23, int(height * 0.025))
    pixel_clock_hz = h_total * (height + v_blank_estimate) * refresh_rate
    pixel_clock = int(pixel_clock_hz / 10000)

    return pixel_clock > 65535


def get_pixel_clock_info(width, height, refresh_rate):
    """
    Get detailed pixel clock information for diagnostics.
    Returns (pixel_clock_mhz, max_mhz, would_break).
    """
    h_blank = max(80, int(width * 0.08))
    h_total = width + h_blank
    v_blank_estimate = max(23, int(height * 0.025))
    pixel_clock_hz = h_total * (height + v_blank_estimate) * refresh_rate
    pixel_clock = int(pixel_clock_hz / 10000)
    max_pixel_clock = 65535

    pixel_clock_mhz = pixel_clock_hz / 1000000
    max_mhz = max_pixel_clock * 10000 / 1000000

    return (pixel_clock_mhz, max_mhz, pixel_clock > max_pixel_clock)
