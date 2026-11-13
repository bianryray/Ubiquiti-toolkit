"""Fetch and parse the IEEE MAC-prefix registry (shared by the in-app
"Update manufacturer list" button and tools/update_oui.py).

Sources, tried in order:
  1. IEEE's official CSVs (MA-L 24-bit, MA-M 28-bit, MA-S 36-bit)
  2. The `oui-data` npm package (a daily-refreshed JSON copy of the same
     IEEE registry, BSD-2-Clause) via the public npm registry -- used when
     the IEEE site is unreachable or refuses the request.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import tarfile
from typing import Callable, Dict, Optional

import requests

IEEE_CSVS = [
    "https://standards-oui.ieee.org/oui/oui.csv",      # MA-L (6 hex)
    "https://standards-oui.ieee.org/oui28/mam.csv",    # MA-M (7 hex)
    "https://standards-oui.ieee.org/oui36/oui36.csv",  # MA-S (9 hex)
]
NPM_META = "https://registry.npmjs.org/oui-data/latest"
_UA = {"User-Agent": "Mozilla/5.0 (UniFi Toolbox OUI updater)"}

# Corporate suffixes trimmed for display so names fit the table column.
_SUFFIX = re.compile(
    r"(?:[\s,]+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|"
    r"llc|l\.l\.c|gmbh|ag|s\.?a|s\.?p\.?a|b\.?v|n\.?v|oy|ab|as|a/s|kg|"
    r"pte|pty|plc|srl|s\.r\.l|sas|kk|k\.k|co\.,?\s*ltd|technology|"
    r"technologies|electronics)\.?)+\s*$",
    re.IGNORECASE,
)


def clean_name(name: str) -> str:
    """'Ubiquiti Inc' -> 'Ubiquiti', 'Shenzhen Foo Technology Co.,Ltd' ->
    'Shenzhen Foo'. Falls back to the original if trimming empties it."""
    name = " ".join((name or "").split()).strip(" ,.")
    trimmed = name
    for _ in range(3):
        new = _SUFFIX.sub("", trimmed).strip(" ,.")
        if new == trimmed:
            break
        trimmed = new
    return trimmed if len(trimmed) >= 2 else name


def _from_ieee(log: Callable[[str], None]) -> Dict[str, str]:
    table: Dict[str, str] = {}
    for url in IEEE_CSVS:
        resp = requests.get(url, headers=_UA, timeout=60)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8", "replace")))
        n = 0
        for row in reader:
            prefix = (row.get("Assignment") or "").strip().upper()
            org = (row.get("Organization Name") or "").strip()
            if prefix and org:
                table[prefix] = clean_name(org)
                n += 1
        log(f"  {url.rsplit('/', 1)[-1]}: {n} entries")
    return table


def _from_npm(log: Callable[[str], None]) -> Dict[str, str]:
    meta = requests.get(NPM_META, timeout=30).json()
    log(f"  oui-data {meta.get('version')} from the npm registry")
    tgz = requests.get(meta["dist"]["tarball"], timeout=120)
    tgz.raise_for_status()
    with tarfile.open(fileobj=io.BytesIO(tgz.content), mode="r:gz") as tar:
        member = tar.getmember("package/index.json")
        data = json.load(tar.extractfile(member))
    # Values are "Org\nAddress lines..." -- keep the first line only.
    return {k.upper(): clean_name(v.split("\n", 1)[0]) for k, v in data.items() if v}


def fetch_registry(log: Callable[[str], None] = lambda m: None) -> Dict[str, str]:
    """Return {hex_prefix: vendor} with 6/7/9-hex-digit prefixes."""
    errors = []
    for name, fn in (("IEEE", _from_ieee), ("npm mirror", _from_npm)):
        try:
            log(f"Downloading manufacturer list from {name} ...")
            table = fn(log)
            if len(table) > 20000:  # sanity: the real registry is ~50k
                return table
            errors.append(f"{name}: only {len(table)} entries")
        except Exception as e:  # try the next source
            errors.append(f"{name}: {e}")
            log(f"  {name} failed: {e}")
    raise RuntimeError("; ".join(errors))


def save_table(table: Dict[str, str], path: str, source_note: str = "") -> None:
    """Write as gzip'd 'PREFIX<TAB>Vendor' lines, sorted."""
    lines = [f"# {source_note}".rstrip()] if source_note else []
    lines += [f"{k}\t{v}" for k, v in sorted(table.items())]
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as f:
        f.write("\n".join(lines) + "\n")


def load_table(path: str) -> Optional[Dict[str, str]]:
    try:
        table = {}
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or "\t" not in line:
                    continue
                k, v = line.rstrip("\n").split("\t", 1)
                table[k] = v
        return table or None
    except (OSError, ValueError, EOFError):
        return None
