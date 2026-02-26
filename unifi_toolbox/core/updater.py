"""Auto-updater that checks GitHub releases for new versions."""

import os
import sys
import threading
import webbrowser
from typing import Optional, Tuple, Callable

import requests

from ..version import __version__, GITHUB_REPO

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _parse_version(tag: str) -> Tuple[int, ...]:
    """Parse a version tag like 'v1.2.3' or '1.2.3' into a tuple of ints."""
    tag = tag.lstrip("vV").strip()
    parts = []
    for p in tag.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_update() -> Optional[dict]:
    """Check GitHub for a newer release.

    Returns a dict with update info if available, or None if up to date.
    Keys: version, tag, url, download_url, body (release notes)
    """
    try:
        resp = requests.get(
            GITHUB_API,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        remote_tag = data.get("tag_name", "")
        remote_ver = _parse_version(remote_tag)
        local_ver = _parse_version(__version__)

        if remote_ver <= local_ver:
            return None

        # Find the .exe asset if available
        download_url = data.get("html_url", "")
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if name.endswith(".exe"):
                download_url = asset.get("browser_download_url", download_url)
                break

        return {
            "version": remote_tag.lstrip("vV"),
            "tag": remote_tag,
            "url": data.get("html_url", ""),
            "download_url": download_url,
            "body": data.get("body", ""),
        }
    except Exception:
        return None


def check_for_update_async(callback: Callable[[Optional[dict]], None]):
    """Check for updates in a background thread, then call callback on result."""
    def worker():
        result = check_for_update()
        callback(result)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def open_download_page(url: str):
    """Open the release/download URL in the user's browser."""
    try:
        webbrowser.open(url)
    except Exception:
        pass


def download_update(download_url: str, dest_dir: str, log: Callable[[str], None] = None) -> Optional[str]:
    """Download the update .exe to dest_dir. Returns the file path or None on failure."""
    try:
        if log:
            log("Downloading update...")
        resp = requests.get(download_url, stream=True, timeout=120)
        resp.raise_for_status()

        filename = download_url.split("/")[-1]
        if not filename.endswith(".exe"):
            filename = "UniFi_Toolbox_update.exe"

        dest_path = os.path.join(dest_dir, filename)
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if log and total > 0:
                    pct = int(downloaded / total * 100)
                    log(f"Downloading... {pct}%")

        if log:
            log(f"Download complete: {dest_path}")
        return dest_path
    except Exception as e:
        if log:
            log(f"Download failed: {e}")
        return None
