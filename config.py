import os
import secrets
import sys
from dataclasses import dataclass


SYSTEMD_ENV_FILE = "/etc/default/phoniebox-panel"


@dataclass(frozen=True)
class RuntimeConfig:
    secret_key: str
    host: str
    port: int
    secret_key_source: str


def _read_env(name, default=""):
    value = os.environ.get(name, default)
    return str(value).strip()


def _load_secret_key():
    configured = _read_env("PHONIEBOX_SECRET_KEY")
    if configured:
        return configured, "environment"
    return secrets.token_hex(32), "generated-ephemeral"


def load_config():
    secret_key, source = _load_secret_key()
    if source != "environment":
        print(
            "WARNING: PHONIEBOX_SECRET_KEY ist nicht gesetzt. "
            f"Es wird ein fluechtiger Laufzeit-Schluessel verwendet. "
            f"Fuer stabile Sessions PHONIEBOX_SECRET_KEY per Umgebung oder {SYSTEMD_ENV_FILE} setzen.",
            file=sys.stderr,
        )
    return RuntimeConfig(
        secret_key=secret_key,
        host=_read_env("PHONIEBOX_HOST", "0.0.0.0") or "0.0.0.0",
        port=int(_read_env("PHONIEBOX_PORT", "80") or "80"),
        secret_key_source=source,
    )
