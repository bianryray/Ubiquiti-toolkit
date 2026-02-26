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

### Connection Profiles
- Save and load connection profiles (controller URL, SSH credentials, console credentials, SSH options)
- Profiles stored in `%APPDATA%/UniFiToolbox/`
- Auto-load last used profile on startup (optional)
- Passwords are base64-obfuscated on disk

## Screenshots

*Dark mode UI with tabbed interface — SSH Adoption, Console/API, Discovery, and Profiles tabs with a shared log panel.*

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

```bash
# Windows — double-click build.bat, or:
pip install -r requirements.txt
pyinstaller --onefile --windowed --name "UniFi Toolbox" --collect-all customtkinter main.py
```

The output will be at `dist/UniFi Toolbox.exe`. Share this single file — it runs on any Windows machine with no dependencies.

## Project Structure

```
unifi-toolbox/
├── main.py                       # Entry point
├── build.bat                     # One-click build script
├── requirements.txt              # Python dependencies
├── unifi_toolbox/
│   ├── app.py                    # Main window, tabs, theme, log panel
│   ├── utils.py                  # Constants, helpers, IP parsing
│   ├── core/
│   │   ├── ssh_manager.py        # SSH connection & command execution
│   │   ├── api_client.py         # UniFi OS REST API wrapper
│   │   ├── discovery.py          # Network port scanner
│   │   ├── profiles.py           # JSON profile storage
│   │   └── tasks.py              # Threaded tasks (adopt, batch, reset)
│   └── tabs/
│       ├── ssh_tab.py            # SSH adoption tab (single + batch)
│       ├── console_tab.py        # Console / API management tab
│       ├── discovery_tab.py      # Network discovery tab
│       └── profiles_tab.py       # Profile management tab
```

## Usage Tips

- **Default SSH credentials** for factory-fresh Ubiquiti devices are usually `ubnt` / `ubnt`
- **Controller URL** format: `http://<controller-ip>:8080` (the tool appends `/inform` automatically)
- **UDM/UDR/UDM-Pro** devices run their own controller — create a site on the device itself
- **UXG/UAP/USW** leaf devices need to be adopted into an existing controller's site
- Use **Discovery** to find devices on your network, then click **Adopt Selected** to send them to batch adoption
- **Profiles** save all connection settings so you don't re-enter credentials across sessions

## License

MIT
