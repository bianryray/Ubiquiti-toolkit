"""Refresh the bundled manufacturer (OUI) database.

    python tools/update_oui.py            # download from IEEE (npm mirror fallback)
    python tools/update_oui.py --json F   # build from a local oui-data index.json

Writes unifi_toolbox/data/oui.txt.gz. The release workflow runs this before
every build so each published .exe ships the current IEEE registry.
"""

import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from unifi_toolbox.core.oui_sources import (  # noqa: E402
    clean_name, fetch_registry, save_table,
)

OUT = os.path.join(ROOT, "unifi_toolbox", "data", "oui.txt.gz")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="local oui-data index.json instead of downloading")
    args = ap.parse_args()

    if args.json:
        with open(args.json, encoding="utf-8") as f:
            data = json.load(f)
        table = {k.upper(): clean_name(v.split("\n", 1)[0]) for k, v in data.items() if v}
    else:
        table = fetch_registry(print)

    save_table(table, OUT, f"IEEE MA-L/MA-M/MA-S registry, built {date.today()}")
    print(f"Wrote {len(table)} prefixes to {OUT} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
