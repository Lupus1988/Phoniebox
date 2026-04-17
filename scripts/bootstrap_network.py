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

from system.networking import (
    apply_wifi_profile,
    connection_exists,
    delete_connection_if_exists,
    recreate_hotspot_profile,
    recreate_wifi_client,
)


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


def detect_active_connection_name():
    ok, output = run_command(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
    if not ok:
        return ""
    for line in output.splitlines():
        name, _, kind = line.partition(":")
        if name and kind == "802-11-wireless":
            return name
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


def find_password_via_nmcli(connection_name):
    if not connection_name:
        return None
    ok, output = run_command(["sudo", "nmcli", "-s", "-g", "802-11-wireless-security.psk", "connection", "show", connection_name])
    if ok and output:
        return output.strip()
    return None


def find_current_wifi_password(ssid, connection_name=""):
    return (
        find_password_via_nmcli(connection_name)
        or find_password_in_nmconnections(ssid)
        or find_password_in_wpa_supplicant(ssid)
    )


def normalize_saved_networks(saved_networks):
    normalized = []
    seen = set()
    for entry in saved_networks or []:
        ssid = (entry.get("ssid") or "").strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        normalized.append(
            {
                "id": entry.get("id") or f"wifi-{ssid}",
                "ssid": ssid,
                "password": (entry.get("password") or "").strip(),
                "priority": int(entry.get("priority", 10) or 10),
            }
        )
    return normalized


def ensure_current_network_saved(config):
    wifi = config.setdefault("wifi", {})
    saved_networks = normalize_saved_networks(wifi.setdefault("saved_networks", []))
    wifi["saved_networks"] = saved_networks

    ssid = detect_active_ssid()
    connection_name = detect_active_connection_name()
    if not ssid:
        changed = False
        if not saved_networks and wifi.get("mode") != "hotspot_only":
            wifi["mode"] = "hotspot_only"
            changed = True
        wifi["fallback_hotspot"] = True
        return changed, "Kein aktives WLAN zum Import gefunden."

    password = find_current_wifi_password(ssid, connection_name=connection_name) or ""
    existing = next((entry for entry in saved_networks if entry["ssid"] == ssid), None)
    changed = False
    if existing is None:
        saved_networks.append(
            {
                "id": "wifi-bootstrap",
                "ssid": ssid,
                "password": password,
                "priority": 100,
            }
        )
        changed = True
    elif password and existing.get("password") != password:
        existing["password"] = password
        changed = True

    if wifi.get("mode") != "client_with_fallback_hotspot":
        wifi["mode"] = "client_with_fallback_hotspot"
        changed = True
    if not wifi.get("fallback_hotspot", True):
        wifi["fallback_hotspot"] = True
        changed = True
    return changed, f"Aktives WLAN {ssid} importiert."


def cleanup_stale_client_profile(ssid, active_connection_name, password):
    details = []
    if not ssid:
        return {"ok": True, "details": details}

    phonie_connection_name = f"phonie-client-{ssid}"
    if active_connection_name == phonie_connection_name:
        return {"ok": True, "details": details}

    # If another system-managed profile currently owns this SSID, remove the
    # parallel Phoniebox client profile to avoid future autoconnect races.
    if active_connection_name:
        result = delete_connection_if_exists(phonie_connection_name)
        details.extend(result["details"])
        return {"ok": result["ok"], "details": details}

    result = delete_connection_if_exists(phonie_connection_name)
    details.extend(result["details"])
    return {"ok": result["ok"], "details": details}


def ensure_hotspot_profile(config):
    wifi = config.get("wifi", {})
    hotspot_name = "phoniebox-hotspot"
    if connection_exists(hotspot_name):
        return {"ok": True, "details": [f"Hotspot-Profil bereits vorhanden: {wifi.get('hotspot_ssid', 'Phonie-hotspot')}"]}
    return recreate_hotspot_profile(wifi)


def prepare_network_profiles(config):
    wifi = config.get("wifi", {})
    details = []
    active_ssid = detect_active_ssid()
    active_connection_name = detect_active_connection_name()

    ok, output = run_command(["sudo", "nmcli", "radio", "wifi", "on"])
    if not ok:
        return {"ok": False, "details": [f"WLAN-Funk konnte nicht aktiviert werden: {output}"]}
    details.append("WLAN-Funk aktiviert.")

    for network in wifi.get("saved_networks", []):
        ssid = network.get("ssid", "").strip()
        password = network.get("password", "").strip()
        cleanup = cleanup_stale_client_profile(ssid, active_connection_name, password)
        details.extend(cleanup["details"])
        if not cleanup["ok"]:
            return {"ok": False, "details": details}
        if active_ssid and ssid == active_ssid and active_connection_name and active_connection_name != f"phonie-client-{ssid}":
            details.append(f"Vorhandenes Systemprofil bleibt aktiv fuer {ssid}: {active_connection_name}")
            continue
        result = recreate_wifi_client(
            ssid,
            password,
            network.get("priority", 10),
        )
        details.extend(result["details"])
        if not result["ok"]:
            return {"ok": False, "details": details}

    hotspot = ensure_hotspot_profile(config)
    details.extend(hotspot["details"])
    return {"ok": hotspot["ok"], "details": details}


def seed_only(config):
    return prepare_network_profiles(config)


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
