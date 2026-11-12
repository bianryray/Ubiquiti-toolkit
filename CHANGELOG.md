# Changelog

All notable changes to UniFi Toolbox are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/).

## [1.2.0] - 2026-11-12

### Added
- **Updates without git** — every version bump merged to `main` now builds the
  `.exe` on GitHub and publishes it as a Release automatically
- **Check for Updates** button in the header (tells you if you're current)
- **Update Now** — the packaged `.exe` downloads the new version, closes,
  swaps itself and reopens. No browser or manual file copying needed
- **What's New** button on the update banner shows the release notes
- **Discovery: search box** — filter by MAC, IP, manufacturer, port or banner.
  MAC search ignores separators (`aabbcc`, `aa:bb:cc`, `AA-BB-CC` all match).
  Several words narrow the results further (e.g. `ubiquiti 8080`). Ctrl+F jumps to it
- **Discovery: sortable columns** — click IP, MAC, Manufacturer, Ports or Banner
  to sort; click again to reverse. IPs sort numerically (.9 before .100)
- **Discovery: right-click a row** — copy IP / MAC, open the web UI, adopt just that device
- **Discovery: Copy IPs / Copy MACs / Export CSV** for the selected rows
- Discovery progress bar, "Showing X of Y" counter and an end-of-scan summary
- Log panel: timestamps, **Copy** and **Save...** buttons
- Keyboard shortcuts: Ctrl+1..5 switch tabs, Ctrl+F search devices, Ctrl+L clear log

### Changed
- Discovery results are sorted by IP by default instead of arrival order
- Select All / Deselect All / Adopt Selected act on the rows currently shown,
  so a search or "Only Ubiquiti" filter is respected
- Stop button is only enabled while a scan is running
- Subnet field is a dropdown of the PC's detected subnets (still editable); Enter starts a scan

### Fixed (since 1.1.0)
- Adoption now runs `set-inform` in a real interactive shell, so it resolves
  like a manual SSH session (fixes "command not found" on some devices)
- Device's `set-inform` reply is echoed to the log for clearer results

## [1.0.0] - 2026-02-26

### Added
- **GUI application** built with CustomTkinter (dark/light theme toggle)
- **SSH Adoption tab** — single device adoption via `set-inform` over SSH
- **Batch adoption** — adopt multiple devices from comma-separated IPs, IP ranges, or CIDR notation
- **Model detection** — identify console vs leaf devices via SSH probing
- **Quick SSH command** runner for arbitrary commands
- **SSH test** button to verify connectivity
- **Factory reset** support (`syswrapper.sh restore-default` and `set-default`)
- **Dry run mode** to preview adoption commands without executing
- **Pause / Stop controls** for long-running tasks
- **SSH options** — auto-accept host keys, keyboard-interactive auth, private key support
- **Console / API tab** — UniFi OS REST API integration
  - Login to UniFi controllers
  - List sites
  - Create sites
  - Adopt devices by MAC address
  - Open web setup in browser
  - Self-signed SSL support
- **Network Discovery tab** — TCP port scanner for Ubiquiti devices
  - Scans ports 22, 443, 8080, 8443 across a subnet
  - Auto-detects local subnet from network interfaces
  - Concurrent scanning with 50 threads
  - Results table with select/deselect and "Adopt Selected" integration
- **Profiles tab** — connection profile management
  - Save/load/delete named profiles
  - Stores controller URL, SSH credentials, console credentials, SSH options
  - JSON storage in `%APPDATA%/UniFiToolbox/`
  - Passwords obfuscated with base64 encoding
  - Auto-load last used profile on startup (optional)
- **Shared log panel** at bottom of window with clear button
- **PyInstaller build** — `build.bat` produces a standalone `.exe`
- **IP target parsing** — supports single IPs, comma-separated, ranges (`x.x.x.1-50`), and CIDR (`x.x.x.0/24`)

### Changed (vs. original Python reference)
- Replaced Tkinter with **CustomTkinter** for modern UI with dark mode
- Restructured codebase into `core/` (business logic) and `tabs/` (UI) packages
- Removed runtime auto-install of pip packages (dependencies bundled in `.exe`)
- Extracted SSH interactive auth fallback into dedicated `_connect_interactive` method
- Added `BatchAdoptionTask` for multi-device adoption with progress tracking
- Added `NetworkScanner` with concurrent `ThreadPoolExecutor` scanning
- Added `ProfileManager` with JSON persistence and base64 password obfuscation
- Discovery tab bridges to SSH tab — selected devices auto-populate batch input
- Profile loading populates both SSH and Console tabs simultaneously
