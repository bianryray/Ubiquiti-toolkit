"""UniFi Toolbox — Standalone GUI for Ubiquiti device SSH adoption and management."""

import sys


def main():
    from unifi_toolbox.app import UniFiToolboxApp

    app = UniFiToolboxApp()
    app.mainloop()


if __name__ == "__main__":
    main()
