from typing import Dict, List

import requests

from ..utils import HTTP_TIMEOUT, LogFn, noop_log


class UniFiAPI:
    """Minimal UniFi OS API wrapper for Network app calls."""

    def __init__(
        self,
        base_url: str,
        verify_ssl: bool = False,
        log: LogFn = noop_log,
    ):
        self.base_url = base_url.rstrip("/")
        self.sess = requests.Session()
        self.sess.verify = verify_ssl
        self.log = log

    def login(self, username: str, password: str) -> None:
        url = f"{self.base_url}/api/auth/login"
        payload = {
            "username": username,
            "password": password,
            "rememberMe": True,
        }
        self.log("Logging in to UniFi OS ...")
        r = self.sess.post(url, json=payload, timeout=HTTP_TIMEOUT)
        if r.status_code not in (200, 204):
            raise RuntimeError(
                f"Login failed: HTTP {r.status_code} - {r.text[:200]}"
            )
        self.log("Login OK.")

    def list_sites(self) -> List[Dict]:
        url = f"{self.base_url}/proxy/network/api/self/sites"
        r = self.sess.get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(
                f"List sites failed: HTTP {r.status_code} - {r.text[:200]}"
            )
        data = r.json()
        sites = []
        for item in data:
            sites.append(
                {
                    "name": item.get("name")
                    or item.get("desc")
                    or item.get("attr_no_delete"),
                    "desc": item.get("desc") or "",
                    "id": item.get("_id") or item.get("name"),
                }
            )
        return sites

    def create_site(self, site_name: str) -> Dict:
        url = f"{self.base_url}/proxy/network/api/s/default/cmd/sitemgr"
        payload = {"cmd": "add-site", "name": site_name}
        self.log(f"Creating site '{site_name}' ...")
        r = self.sess.post(url, json=payload, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(
                f"Create site failed: HTTP {r.status_code} - {r.text[:200]}"
            )
        self.log("Site created.")
        return r.json()

    def adopt_device(self, site_name_or_id: str, mac: str) -> Dict:
        site = site_name_or_id
        url = f"{self.base_url}/proxy/network/api/s/{site}/cmd/devmgr"
        payload = {"cmd": "adopt", "mac": mac.lower()}
        self.log(f"Adopting {mac} into site '{site}' ...")
        r = self.sess.post(url, json=payload, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(
                f"Adopt failed: HTTP {r.status_code} - {r.text[:200]}"
            )
        self.log("Adopt request sent.")
        return r.json()
