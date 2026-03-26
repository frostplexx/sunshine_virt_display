"""
DRM package — re-exports the public API for backward compatibility.
"""

from src.drm.crtc import force_crtc_assignment, release_crtc, wait_for_output_ready
from src.drm.sysfs import (
    find_empty_slot,
    get_card_name_from_device,
    get_connected_displays,
    get_display_ports,
    get_drm_devices,
    run_command,
)

__all__ = [
    "find_empty_slot",
    "force_crtc_assignment",
    "get_card_name_from_device",
    "get_connected_displays",
    "get_display_ports",
    "get_drm_devices",
    "release_crtc",
    "run_command",
    "wait_for_output_ready",
]
