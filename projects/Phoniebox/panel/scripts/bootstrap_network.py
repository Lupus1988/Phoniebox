#!/usr/bin/env python3
import argparse
import configparser
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SETUP_FILE = BASE_DIR / "data" / "setup.json"
NM_CONNECTIONS_DIR = Path("/etc/NetworkManager/system-connections")
WPA_SUPPLICANT_FILE = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from system.networking import apply_wifi_profile, recreate_hotspot_profile


def load_setup():
    if not SETUP_FILE.exists():
        raise FileNotFoundError(f"{SETUP_FILE} fehlt")
    return json.loads(SETUP_FILE.read_text(encoding="utf-8"))


def save_setup(data):
    SETUP_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode == 0, (result.stdout or result.stderr or "").strip()


def detect_active_ssid():
    ok, output = run_command(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
    if ok:
        for line in output.splitlines():
            active, _, ssid = line.partition(":")
            if active == "yes" and ssid:
                return ssid

    ok, output = run_command(["iwgetid", "-r"])
    if ok and output:
        return output.strip()
    return ""


def find_password_in_nmconnections(ssid):
    if not ssid or not NM_CONNECTIONS_DIR.exists():
        return None

    for candidate in sorted(NM_CONNECTIONS_DIR.glob("*.nmconnection")):
        parser = configparser.ConfigParser()
        try:
            parser.read(candidate, encoding="utf-8")
        except configparser.Error:
            continue
        if parser.get("wifi", "ssid", fallback="") != ssid:
            continue
        password = parser.get("wifi-security", "psk", fallback="")
        if password:
            return password
    return None


def find_password_in_wpa_supplicant(ssid):
    if not ssid or not WPA_SUPPLICANT_FILE.exists():
        return None

    current_ssid = None
    current_psk = None
    for raw_line in WPA_SUPPLICANT_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if line.startswith("network={"):
            current_ssid = None
            current_psk = None
            continue
        if line == "}":
            if current_ssid == ssid and current_psk:
                return current_psk
            current_ssid = None
            current_psk = None
            continue
        if line.startswith("ssid="):
            current_ssid = line.split("=", 1)[1].strip().strip('"')
        if line.startswith("psk="):
            current_psk = line.split("=", 1)[1].strip().strip('"')
    return None


def find_current_wifi_password(ssid):
    return find_password_in_nmconnections(ssid) or find_password_in_wpa_supplicant(ssid)


def ensure_current_network_saved(config):
    wifi = config.setdefault("wifi", {})
    saved_networks = wifi.setdefault("saved_networks", [])
    if saved_networks:
        return False, "Vorhandene WLAN-Profile bleiben unverändert."

    ssid = detect_active_ssid()
    if not ssid:
        return False, "Kein aktives WLAN zum Import gefunden."

    password = find_current_wifi_password(ssid) or ""
    saved_networks.append(
        {
            "id": "wifi-bootstrap",
            "ssid": ssid,
            "password": password,
            "priority": 100,
        }
    )
    if wifi.get("mode") == "hotspot_only":
        wifi["mode"] = "client_with_fallback_hotspot"
        wifi["fallback_hotspot"] = True
        return True, f"Aktives WLAN {ssid} importiert und Modus auf client_with_fallback_hotspot gesetzt."
    return True, f"Aktives WLAN {ssid} importiert."


def seed_only(config):
    return recreate_hotspot_profile(config.get("wifi", {}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-only", action="store_true")
    args = parser.parse_args()

    config = load_setup()
    changed, message = ensure_current_network_saved(config)
    if changed:
        save_setup(config)

    print(message)

    if args.seed_only:
        result = seed_only(config)
    else:
        result = apply_wifi_profile(config.get("wifi", {}))

    print("OK" if result.get("ok") else "FEHLER")
    for detail in result.get("details", []):
        print(detail)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
