import json
import os
import base64
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from ..utils import DEFAULT_SSH_PORT


def _get_config_dir() -> str:
    """Get the config directory path (%APPDATA%/UniFiToolbox or ~/.config/UniFiToolbox)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
        )
    path = os.path.join(base, "UniFiToolbox")
    os.makedirs(path, exist_ok=True)
    return path


def _obfuscate(text: str) -> str:
    """Simple base64 obfuscation (NOT encryption — just prevents casual reading)."""
    if not text:
        return ""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _deobfuscate(text: str) -> str:
    if not text:
        return ""
    try:
        return base64.b64decode(text.encode("ascii")).decode("utf-8")
    except Exception:
        return text


@dataclass
class Profile:
    name: str
    controller_url: str = ""
    ssh_username: str = "ubnt"
    ssh_password: str = ""
    ssh_port: int = DEFAULT_SSH_PORT
    console_ip: str = ""
    console_username: str = ""
    console_password: str = ""
    verify_ssl: bool = False
    accept_host_key: bool = True
    try_keyboard_interactive: bool = True
    use_pkey: bool = False
    pkey_path: str = ""
    pkey_passphrase: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["ssh_password"] = _obfuscate(self.ssh_password)
        d["console_password"] = _obfuscate(self.console_password)
        d["pkey_passphrase"] = _obfuscate(self.pkey_passphrase)
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "Profile":
        d = dict(d)
        d["ssh_password"] = _deobfuscate(d.get("ssh_password", ""))
        d["console_password"] = _deobfuscate(d.get("console_password", ""))
        d["pkey_passphrase"] = _deobfuscate(d.get("pkey_passphrase", ""))
        # Filter out unknown keys
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        d = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**d)


class ProfileManager:
    """Manages saved connection profiles."""

    def __init__(self):
        self.config_dir = _get_config_dir()
        self.profiles_path = os.path.join(self.config_dir, "profiles.json")
        self.settings_path = os.path.join(self.config_dir, "settings.json")
        self._profiles: Dict[str, Profile] = {}
        self._settings: Dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.profiles_path):
            try:
                with open(self.profiles_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for name, d in data.items():
                    self._profiles[name] = Profile.from_dict(d)
            except Exception:
                self._profiles = {}

        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    self._settings = json.load(f)
            except Exception:
                self._settings = {}

    def _save_profiles(self):
        data = {
            name: profile.to_dict()
            for name, profile in self._profiles.items()
        }
        with open(self.profiles_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _save_settings(self):
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, indent=2)

    def list_profiles(self) -> List[str]:
        return sorted(self._profiles.keys())

    def get(self, name: str) -> Optional[Profile]:
        return self._profiles.get(name)

    def save(self, profile: Profile):
        self._profiles[profile.name] = profile
        self._save_profiles()

    def delete(self, name: str) -> bool:
        if name in self._profiles:
            del self._profiles[name]
            self._save_profiles()
            return True
        return False

    def get_last_used(self) -> Optional[str]:
        return self._settings.get("last_used_profile")

    def set_last_used(self, name: str):
        self._settings["last_used_profile"] = name
        self._save_settings()

    def get_auto_load(self) -> bool:
        return self._settings.get("auto_load_last", False)

    def set_auto_load(self, enabled: bool):
        self._settings["auto_load_last"] = enabled
        self._save_settings()
