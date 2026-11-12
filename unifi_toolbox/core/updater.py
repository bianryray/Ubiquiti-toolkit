"""Auto-updater that checks GitHub releases for new versions.

How updates reach a PC without git:
  1. A version bump merged to `main` makes the GitHub Actions workflow
     (.github/workflows/release.yml) build the .exe and publish it as a
     GitHub Release tagged v<version>.
  2. The app asks the public GitHub API for the latest release on startup
     (and when "Check for Updates" is clicked).
  3. When running as the packaged .exe, "Update Now" downloads the new .exe
     next to the current one, then a tiny helper script swaps the files once
     the app exits and relaunches it. From source, it opens the release page.
"""

import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

import requests

from ..version import __version__, GITHUB_REPO

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "UniFi-Toolbox-Updater",
}


def _parse_version(tag: str) -> Tuple[int, ...]:
    """Parse a version tag like 'v1.2.3' or '1.2.3' into a tuple of ints."""
    tag = tag.lstrip("vV").strip()
    parts = []
    for p in tag.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


@dataclass
class UpdateCheck:
    """Outcome of an update check."""
    status: str                     # "available" | "current" | "error"
    message: str = ""
    version: str = ""
    tag: str = ""
    url: str = RELEASES_PAGE
    download_url: str = ""          # direct .exe asset URL, if published
    body: str = ""                  # release notes (markdown)
    extra: dict = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.status == "available"


def is_frozen() -> bool:
    """True when running as the PyInstaller-packaged .exe."""
    return bool(getattr(sys, "frozen", False))


def check_for_update() -> UpdateCheck:
    """Ask GitHub for the latest release and compare against this build."""
    try:
        resp = requests.get(GITHUB_API, headers=_HEADERS, timeout=10)
    except requests.RequestException as e:
        return UpdateCheck("error", f"Could not reach GitHub: {e}")

    if resp.status_code == 404:
        return UpdateCheck(
            "error", "No releases have been published on GitHub yet.",
        )
    if resp.status_code == 403:
        return UpdateCheck(
            "error", "GitHub rate limit hit - try again in a few minutes.",
        )
    if resp.status_code != 200:
        return UpdateCheck("error", f"GitHub returned HTTP {resp.status_code}.")

    try:
        data = resp.json()
    except ValueError:
        return UpdateCheck("error", "GitHub returned an unreadable response.")

    remote_tag = data.get("tag_name", "")
    remote_ver = remote_tag.lstrip("vV")
    html_url = data.get("html_url", RELEASES_PAGE)

    if _parse_version(remote_tag) <= _parse_version(__version__):
        return UpdateCheck(
            "current", f"You're on the latest version (v{__version__}).",
            version=remote_ver, tag=remote_tag, url=html_url,
        )

    download_url = ""
    for asset in data.get("assets", []):
        if asset.get("name", "").lower().endswith(".exe"):
            download_url = asset.get("browser_download_url", "")
            break

    return UpdateCheck(
        "available", f"Version v{remote_ver} is available (you have v{__version__}).",
        version=remote_ver, tag=remote_tag, url=html_url,
        download_url=download_url, body=data.get("body", "") or "",
    )


def check_for_update_async(callback: Callable[[UpdateCheck], None]):
    """Check for updates in a background thread, then call callback on result."""
    def worker():
        try:
            result = check_for_update()
        except Exception as e:  # never let the updater crash the app
            result = UpdateCheck("error", f"Update check failed: {e}")
        callback(result)

    threading.Thread(target=worker, daemon=True).start()


def open_download_page(url: str):
    """Open the release/download URL in the user's browser."""
    try:
        webbrowser.open(url or RELEASES_PAGE)
    except Exception:
        pass


def download_update(
    download_url: str,
    dest_path: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Download the update to dest_path. Raises on failure. Returns dest_path."""
    tmp_path = dest_path + ".part"
    with requests.get(download_url, headers={"User-Agent": _HEADERS["User-Agent"]},
                      stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)

    # Sanity checks: complete download and a real Windows executable.
    size = os.path.getsize(tmp_path)
    if total and size != total:
        os.remove(tmp_path)
        raise IOError(f"Download incomplete ({size} of {total} bytes).")
    with open(tmp_path, "rb") as f:
        if f.read(2) != b"MZ":
            os.remove(tmp_path)
            raise IOError("Downloaded file is not a Windows executable.")

    if os.path.exists(dest_path):
        os.remove(dest_path)
    os.replace(tmp_path, dest_path)
    return dest_path


def staging_path_for(exe_path: str) -> str:
    """Where to put the downloaded .exe: next to the running one if writable,
    otherwise the temp folder."""
    folder = os.path.dirname(exe_path)
    candidate = os.path.join(folder, os.path.basename(exe_path) + ".new")
    try:
        with open(candidate + ".test", "wb"):
            pass
        os.remove(candidate + ".test")
        return candidate
    except OSError:
        return os.path.join(tempfile.gettempdir(), "UniFi_Toolbox_update.exe")


def launch_swap_and_restart(new_exe: str, current_exe: str) -> None:
    """Spawn a helper .bat that waits for this process to exit, replaces the
    current .exe with the new one (keeping a .old backup), and relaunches it."""
    pid = os.getpid()
    backup = current_exe + ".old"
    script = os.path.join(tempfile.gettempdir(), "unifi_toolbox_update.bat")
    # Written without ( ) blocks so %tries% expands correctly each pass.
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "set tries=0",
        ":wait",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
        "if errorlevel 1 goto swap",
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":swap",
        # The PyInstaller bootloader can hold the .exe for a moment after the
        # app exits, so retry the move for up to ~30 seconds.
        f'if exist "{backup}" del /f /q "{backup}" >nul 2>&1',
        f'move /y "{current_exe}" "{backup}" >nul 2>&1',
        "if not errorlevel 1 goto swapped",
        "set /a tries+=1",
        "if %tries% GEQ 30 goto launch",
        "ping -n 2 127.0.0.1 >nul",
        "goto swap",
        ":swapped",
        f'move /y "{new_exe}" "{current_exe}" >nul 2>&1',
        "if not errorlevel 1 goto launch",
        f'move /y "{backup}" "{current_exe}" >nul 2>&1',
        ":launch",
        f'start "" "{current_exe}"',
        '(goto) 2>nul & del "%~f0"',
    ]
    with open(script, "w", encoding="utf-8") as f:  # chcp 65001 above
        f.write("\r\n".join(lines) + "\r\n")

    flags = 0
    if os.name == "nt":
        # No console window; `timeout` needs a console, hence ping above.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["cmd", "/c", script], creationflags=flags, close_fds=True)


def cleanup_old_build() -> None:
    """Remove the .old backup left over from a previous self-update."""
    if not is_frozen():
        return
    old = sys.executable + ".old"
    try:
        if os.path.exists(old):
            os.remove(old)
    except OSError:
        pass
