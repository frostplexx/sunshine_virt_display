# Sunshine Virtual Display

A script to dynamically create virtual displays for Sunshine game streaming on Linux using EDID overrides.

## Overview

This tool creates virtual displays that match the client's resolution and refresh rate when streaming via Sunshine. 
It automatically manages display connections by overriding EDID information and toggling display status.

## Usage


Clone the repo

```bash
git clone http://frostplexx/sunshine_virt_display
```

Modify `virt_display.sh` and add your sudo password at the top. Also make sure that the file is executable by running `chmod +x virt_display.sh`.

Configure Sunshine to run these commands when clients connect/disconnect in the "General" tab:

**Do Command (On Client Connect):**

```bash
sh -c "path/to/virt_display.sh --connect --width ${SUNSHINE_CLIENT_WIDTH} --height ${SUNSHINE_CLIENT_HEIGHT} --refresh-rate ${SUNSHINE_CLIENT_FPS}"
```

**Undo Command (On Client Disconnect):**

```bash
path/to/virt_display.sh --disconnect
```

### Important Requirements

- The script requires root privileges to modify display settings
- Ensure debugfs is mounted at `/sys/kernel/debug/`
- Python 3

## How It Works

### On Connect:

1. Script receives `--connect` flag
2. Get client resolution and refresh rate from Sunshine
3. Generate custom EDID based on client's display parameters
4. List all currently connected displays
5. Pick the first available empty display slot (prioritizes DisplayPort, falls back to HDMI)
6. Force override EDID for that slot: `sudo sh -c 'cat custom_edid.bin > /sys/kernel/debug/dri/0000:01:00.0/<port>/edid_override'`
7. Disable all currently connected physical displays: `echo off | sudo tee /sys/class/drm/card1-<port>/status`
8. Enable the virtual display: `echo on | sudo tee /sys/class/drm/card1-<port>/status`

### On Disconnect:

1. Script receives `--disconnect` flag
2. Disable the virtual display: `echo off | sudo tee /sys/class/drm/card1-<port>/status`
3. Re-enable previously connected physical displays: `echo on | sudo tee /sys/class/drm/card1-<port>/status`

## Known Issues

- Everything is small when a device with retina display connects
- Disconnecting is sometimes slow and janky but will fix itself after ~15s
- On MacBooks with notches the notch will be ignored and will cut into content

## Tested On

- Bazzite
