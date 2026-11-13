# UniFi Toolbox

A standalone Windows GUI application for managing and adopting Ubiquiti UniFi devices over SSH and the UniFi Controller API.

Built with Python and [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) for a modern dark-mode interface. Packages into a single `.exe` via PyInstaller — no Python installation required for end users.

## Features

### SSH Adoption
- **Single device** — Connect to a device by IP, run `set-inform` to adopt it to your controller
- **Batch mode** — Adopt multiple devices at once using comma-separated IPs, IP ranges (`192.168.1.1-50`), or CIDR notation (`192.168.1.0/24`)
- **Model detection** — Identify whether a device is a console (UDM, UDR, UXG) or a leaf (UAP, USW)
- **Quick SSH commands** — Run arbitrary commands on a device
- **Factory reset** — `syswrapper.sh restore-default` or `set-default`
- **SSH options** — Auto-accept host keys, keyboard-interactive auth fallback, private key authentication
- **Pause / Stop** — Control long-running tasks mid-execution
- **Dry run** — Preview what commands would be sent without executing them

### Console / API
- **List sites** on a UniFi controller
- **Create sites**
- **Adopt devices by MAC** address into a specific site
- **Open web setup** in your default browser
- Supports self-signed SSL certificates

### Network Discovery
- TCP port scan across a subnet for common Ubiquiti ports (22, 443, 8080, 8443)
- Auto-detects your local subnet
- Concurrent scanning (50 threads) for speed
- Results table with checkboxes — select devices and send them directly to SSH batch adoption
- **Search** by MAC, IP, manufacturer, port or banner (MAC search ignores `:` / `-`; Ctrl+F)
- **Sort** by any column (click the header; click again to reverse)
- Right-click a row to copy IP/MAC, open its web UI or adopt it; Copy IPs / Copy MACs / Export CSV for selected rows

### Network Tests (Beta)
- **Area Check** — run on the AP that serves a slow area; it checks the AP's link to the
  gateway, the internet, DNS, the AP's uplink (cable speed / mesh signal), Wi-Fi channel
  congestion, client signal and load, then says which is the likely cause
- **AP ↔ Gateway**, **PC ↔ Device** and **PC ↔ PC** throughput tests (both directions)
- PC tests listen on TCP port 50555 by default — allow UniFi Toolbox through Windows
  Firewall (Private networks) when prompted
- AP/switch CPUs can limit PC ↔ Device results; AP ↔ Gateway needs `iperf3` on both devices

### Manufacturer identification
- Full IEEE MAC registry (~54,000 prefixes) bundled and refreshed with every release
- **Update manufacturer list** in Discovery downloads the latest copy on demand
- Private / randomized MACs (phones, laptops) and virtual NICs are labelled clearly
- Hostname (reverse DNS / NetBIOS) shown alongside

### Updates
- Checks GitHub Releases on startup and via **Check for Updates**
- **Update Now** downloads the new `.exe`, closes, replaces itself and reopens — no git needed on the PC

### Connection Profiles
- Save and load connection profiles (controller URL, SSH credentials, console credentials, SSH options)
- Profiles stored in `%APPDATA%/UniFiToolbox/`
- Auto-load last used profile on startup (optional)
- Passwords are base64-obfuscated on disk

## Screenshots

*Sidebar navigation (SSH Adoption, Console / API, Discovery, Troubleshoot, Profiles), Light / Dark / System themes, and a collapsible colour-coded activity log.*

## Requirements

- Python 3.10+ (for development/running from source)
- Windows (for `.exe` packaging — the Python source runs cross-platform)

### Dependencies

| Package | Purpose |
|---------|---------|
| [customtkinter](https://github.com/TomSchimansky/CustomTkinter) | Modern GUI framework |
| [paramiko](https://www.paramiko.org/) | SSH connections |
| [requests](https://requests.readthedocs.io/) | HTTP/API calls |
| [pyinstaller](https://pyinstaller.org/) | Packaging to `.exe` (build only) |

## Quick Start

### Run from source

```bash
pip install -r requirements.txt
python main.py
```

### Build standalone `.exe`

On Windows, just double-click `build.bat`. It uses the `py` launcher (bundled
with standard Python installs) and invokes pip / PyInstaller via `python -m`,
so it works even if the `Scripts\` folder isn't on `PATH`.

If you prefer to run the commands manually:

```bat
py -m pip install -r requirements.txt
py -m PyInstaller --onefile --windowed --name "UniFi Toolbox" --collect-all customtkinter main.py
```

The output will be at `dist/UniFi Toolbox.exe`. Share this single file — it runs on any Windows machine with no dependencies.

#### Troubleshooting: `'pip' is not recognized` / `'pyinstaller' is not recognized`

This means Python's `Scripts\` folder isn't on `PATH`. Two fixes:

1. **Re-run the Python installer** and tick *"Add Python to PATH"* (or *"Add python.exe to PATH"* in newer installers), then restart the terminal.
2. **Or just use the updated `build.bat`** — it calls `py -m pip` and `py -m PyInstaller` directly, which doesn't require `Scripts\` on `PATH`.

## Project Structure

```
unifi-toolbox/
├── main.py                       # Entry point
├── build.bat                     # One-click build script
├── requirements.txt              # Python dependencies
├── tools/
│   └── update_oui.py             # Refresh the bundled manufacturer list
├── .github/workflows/release.yml # Builds + publishes the .exe on version bumps
├── unifi_toolbox/
│   ├── app.py                    # Main window: sidebar, pages, activity log, updater UI
│   ├── theme.py                  # Design system: palette + widget factories
│   ├── version.py                # App version (bump to release)
│   ├── utils.py                  # Constants, helpers, IP parsing
│   ├── data/
│   │   └── oui.txt.gz            # IEEE MAC registry (MA-L / MA-M / MA-S)
│   ├── core/
│   │   ├── ssh_manager.py        # SSH connection & command execution
│   │   ├── api_client.py         # UniFi OS REST API wrapper
│   │   ├── discovery.py          # Network port scanner
│   │   ├── nettest.py            # Area check + speed tests (beta)
│   │   ├── oui.py                # MAC lookup, manufacturer + hostname resolution
│   │   ├── oui_sources.py        # Download / parse the IEEE registry
│   │   ├── profiles.py           # JSON profile + settings storage
│   │   ├── tasks.py              # Threaded tasks (adopt, batch, reset)
│   │   └── updater.py            # GitHub release check + self-update
│   └── tabs/
│       ├── ssh_tab.py            # SSH adoption (single + batch)
│       ├── console_tab.py        # Console / API management
│       ├── discovery_tab.py      # Network discovery
│       ├── troubleshoot_tab.py   # One-click diagnostics
│       ├── profiles_tab.py       # Profile management
│       └── nettest_tab.py        # Network Tests page (beta)
```

## Releasing an Update

1. Bump `__version__` in `unifi_toolbox/version.py` and add a matching
   `## [x.y.z]` section to `CHANGELOG.md` (used as the release notes).
2. Merge to `main`. The **Build & Release** GitHub Action builds the `.exe` on
   Windows and publishes release `vx.y.z` with `UniFi-Toolbox.exe` attached.
   It can also be run by hand from the repo's **Actions** tab.
3. Installed copies see the update banner next time they start (or when
   **Check for Updates** is clicked) and can install it with **Update Now**.

## Usage Tips

- **Default SSH credentials** for factory-fresh Ubiquiti devices are usually `ubnt` / `ubnt`
- **Controller URL** format: `http://<controller-ip>:8080` (the tool appends `/inform` automatically)
- **UDM/UDR/UDM-Pro** devices run their own controller — create a site on the device itself
- **UXG/UAP/USW** leaf devices need to be adopted into an existing controller's site
- Use **Discovery** to find devices on your network, then click **Adopt Selected** to send them to batch adoption
- **Profiles** save all connection settings so you don't re-enter credentials across sessions

## Credits

Manufacturer data comes from the [IEEE Registration Authority](https://regauth.standards.ieee.org/)
MA-L/MA-M/MA-S registries, with [oui-data](https://github.com/silverwind/oui-data)
(BSD-2-Clause) as a fallback mirror. Refresh the bundled copy with
`python tools/update_oui.py`.

## License

MIT
