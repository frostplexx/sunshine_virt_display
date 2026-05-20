# Sunshine Virtual Display

This tool creates virtual displays that match the client's resolution and refresh rate when streaming via Sunshine.
It runs as a persistent daemon and automatically manages display connections by overriding EDID information and toggling display status.

> ⚠️ Enable SSH before using this tool. If your display gets stuck, you can recover by running `sudo systemctl stop sunshineVD` or sending `--disconnect` to the socket.

## Upgrading from v1

v2 replaces the shell script with a persistent daemon. Three things to do when upgrading:

**1. Update your Sunshine commands.** The old `virt_display.sh --connect ...` commands no longer exist. Replace them with the socket-based commands in the [Configure Sunshine](#configure-sunshine) section below.

**2. Remove the old sudoers entry.** v1 required a `NOPASSWD` rule for `python3 main.py`. It is no longer needed — delete it:

```bash
sudo visudo
# Remove the line that contains sunshine_virt_display/main.py
```

**3. Install and start the daemon.** v2 requires the `sunshineVD` service to be running or Sunshine's commands will silently do nothing:

```bash
sudo ./install.sh
```

## Requirements

- Python 3
- `jeepney` Python package (installed automatically by `install.sh`)
- debugfs mounted at `/sys/kernel/debug/`
- systemd

## Installation

Clone the repo:

```bash
git clone https://github.com/frostplexx/sunshine_virt_display
cd sunshine_virt_display
```

Run the install script as root:

```bash
sudo ./install.sh
```

This will:
1. Install `jeepney` via pip
2. Copy the project to `/opt/sunshine-vd/`
3. Install and enable the `sunshineVD` systemd service

The daemon starts automatically at boot and restarts if it crashes. To check it is running:

```bash
systemctl status sunshineVD
journalctl -u sunshineVD -f
```

### Updating

Pull the latest changes and re-run the install script:

```bash
git pull
sudo ./install.sh
```

## Configure Sunshine

The daemon listens on `/tmp/sunshineVD.sock`. Sunshine talks to it by writing comma-separated arguments to that socket.

In Sunshine's **General** tab, set:

**Do Command (On Client Connect):**

```bash
sh -c "echo --connect,--width,${SUNSHINE_CLIENT_WIDTH},--height,${SUNSHINE_CLIENT_HEIGHT},--refresh-rate,${SUNSHINE_CLIENT_FPS} | nc -U /tmp/sunshineVD.sock"
```

**Undo Command (On Client Disconnect):**

```bash
sh -c "echo --disconnect | nc -U /tmp/sunshineVD.sock"
```

`nc -U` is provided by `openbsd-netcat` (available on most distros). If you prefer `socat`:

```bash
# Do Command
sh -c "echo --connect,--width,${SUNSHINE_CLIENT_WIDTH},--height,${SUNSHINE_CLIENT_HEIGHT},--refresh-rate,${SUNSHINE_CLIENT_FPS} | socat - UNIX-CONNECT:/tmp/sunshineVD.sock"

# Undo Command
sh -c "echo --disconnect | socat - UNIX-CONNECT:/tmp/sunshineVD.sock"
```

### Multi-GPU systems

On systems with both an integrated GPU (iGPU) and a discrete GPU (dGPU), the daemon automatically selects the card with the most connected displays. Override with the `-d` flag if it picks the wrong one:

```bash
sh -c "echo --connect,-d,card2,--width,${SUNSHINE_CLIENT_WIDTH},--height,${SUNSHINE_CLIENT_HEIGHT},--refresh-rate,${SUNSHINE_CLIENT_FPS} | nc -U /tmp/sunshineVD.sock"
```

To find the right card name, run the debug script and look at section 2 ("KMS connector/encoder/CRTC state") — each GPU is listed as `/dev/dri/cardN`.

## Development

Use `make` to manage a dev-mode service that runs the daemon straight from the repo directory, so code changes take effect immediately on restart.

**One-time setup:**

```bash
make dev-install
```

**Daily workflow:**

```bash
make dev-start       # start the daemon
make dev-logs        # follow journalctl output  (Ctrl-C to stop)
make dev-status      # check if it's running

# after editing code:
make dev-restart

make dev-stop        # stop the daemon
make dev-uninstall   # remove the dev service entirely
```

The dev service uses `Restart=no` so crashes surface immediately rather than being silently swallowed by an auto-restart loop.

## How It Works

### On Connect

1. Daemon receives `--connect` with width, height, and refresh rate
2. Generates a custom EDID matching the client's display parameters
3. Finds the first available empty display slot (prefers DisplayPort, falls back to HDMI)
4. Overrides EDID for that slot via debugfs
5. Releases CRTCs from and turns off all connected physical displays
6. Enables the virtual display
7. Waits for the compositor to assign a CRTC, or forces one if it doesn't

### On Disconnect

1. Daemon receives `--disconnect`
2. Turns physical displays back on and forces CRTC assignment
3. Releases the CRTC from and turns off the virtual display

### On Sunshine Crash or Stop

The daemon watches `sunshine.service` via the systemd DBus interface. When Sunshine's `ActiveState` becomes `inactive` or `failed`, the daemon automatically disconnects the virtual display so physical monitors are restored without manual intervention.

### On System Sleep / Wake

The daemon holds a systemd sleep inhibitor lock so it can clean up before the system suspends. On sleep it disconnects the virtual display; on wake it reconnects automatically if a session was active.

### On Shutdown

Both `PrepareForShutdown` (via DBus) and SIGTERM trigger a graceful disconnect before the process exits, so physical displays are restored even if Sunshine didn't send an undo command.

## Known Issues

- Everything appears small when a device with a Retina display connects
- Disconnecting is sometimes slow (~15 s) but resolves on its own
- On MacBooks with notches, the notch area cuts into content
- Very high resolutions and refresh rates may not work due to EDID 1.4 pixel-clock limits
- HDR causes the display to freeze and is disabled by default
- Stuttering on some displays: Enable V-Sync and frame pacing in Moonlight.


## Tested On

- Bazzite
- CachyOS
- NixOS
