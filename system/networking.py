import shutil
import subprocess


def command_exists(name):
    return shutil.which(name) is not None


def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (result.stdout or result.stderr or "").strip()
    return {"ok": result.returncode == 0, "output": output}


def wifi_radio_enabled():
    if not command_exists("nmcli"):
        return True
    result = run_command(["nmcli", "-t", "-f", "WIFI", "radio"])
    if not result["ok"]:
        return True
    value = (result["output"] or "").strip().lower()
    return value in {"enabled", "ein"}


def set_wifi_radio(enabled):
    if not command_exists("nmcli"):
        return {"ok": False, "details": ["nmcli ist nicht installiert."]}
    command = ["nmcli", "radio", "wifi", "on" if enabled else "off"]
    result = run_command(command)
    details = [f"WLAN {'aktiviert' if enabled else 'deaktiviert'}."]
    if not result["ok"]:
        details = [f"WLAN konnte nicht {'aktiviert' if enabled else 'deaktiviert'} werden: {result['output']}"]
    return {"ok": result["ok"], "details": details}


def normalize_hotspot_security(value):
    security = (value or "open").strip().lower()
    if security == "wpa2":
        return "wpa-psk"
    if security not in {"open", "wpa-psk"}:
        return "open"
    return security


def ensure_hostname(hostname):
    hostname = (hostname or "phoniebox").strip()
    details = [f"Ziel-Hostname: {hostname}"]
    if not command_exists("hostnamectl"):
        details.append("hostnamectl nicht verfügbar.")
        return {"ok": False, "details": details}

    result = run_command(["sudo", "hostnamectl", "set-hostname", hostname])
    if result["ok"]:
        details.append(f"Hostname gesetzt: {hostname}")
    else:
        details.append(f"Hostname konnte nicht gesetzt werden: {result['output']}")
    return {"ok": result["ok"], "details": details}


def connection_exists(name):
    result = run_command(["nmcli", "-t", "-f", "NAME", "connection", "show"])
    if not result["ok"]:
        return False
    return name in result["output"].splitlines()


def wifi_devices():
    result = run_command(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
    if not result["ok"]:
        return []
    devices = []
    for line in result["output"].splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        device, kind, state = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if device and kind == "wifi":
            devices.append({"device": device, "state": state})
    return devices


def activate_hotspot_with_recovery(connection_name="phoniebox-hotspot"):
    # First try the direct path.
    first_try = run_command(["sudo", "nmcli", "connection", "up", connection_name])
    if first_try["ok"]:
        return {"ok": True, "details": [first_try["output"] or "Hotspot direkt aktiviert."]}

    details = [first_try["output"] or "Hotspot-Aktivierung fehlgeschlagen."]
    lower = (first_try["output"] or "").lower()
    if "unknown connection" in lower:
        return {"ok": False, "details": details}

    # Self-heal for stale interface bindings (e.g. old wlan0 pinning).
    run_command(["sudo", "nmcli", "radio", "wifi", "on"])
    run_command(["sudo", "nmcli", "connection", "modify", connection_name, "connection.interface-name", ""])

    candidates = [entry["device"] for entry in wifi_devices()]
    if not candidates:
        return {"ok": False, "details": details + ["Kein WLAN-Interface gefunden."]}

    for device in candidates:
        run_command(["sudo", "nmcli", "device", "set", device, "managed", "yes"])
        run_command(["sudo", "nmcli", "device", "connect", device])
        retry = run_command(["sudo", "nmcli", "connection", "up", connection_name, "ifname", device])
        if retry["ok"]:
            return {
                "ok": True,
                "details": details + [f"Hotspot auf {device} aktiviert."],
            }
        details.append(retry["output"] or f"Aktivierung auf {device} fehlgeschlagen.")

    return {"ok": False, "details": details}


def recreate_wifi_client(ssid, password, priority):
    details = []
    if not ssid:
        return {"ok": True, "details": details}

    connection_name = f"phonie-client-{ssid}"
    if connection_exists(connection_name):
        run_command(["sudo", "nmcli", "connection", "delete", connection_name])
        details.append(f"Vorhandenes WLAN-Profil ersetzt: {connection_name}")

    create = run_command(
        ["sudo", "nmcli", "connection", "add", "type", "wifi", "ifname", "*", "con-name", connection_name, "ssid", ssid]
    )
    if not create["ok"]:
        details.append(f"Profil {ssid} konnte nicht angelegt werden: {create['output']}")
        return {"ok": False, "details": details}

    commands = [
        ["sudo", "nmcli", "connection", "modify", connection_name, "connection.autoconnect", "yes"],
        [
            "sudo",
            "nmcli",
            "connection",
            "modify",
            connection_name,
            "connection.autoconnect-priority",
            str(priority),
        ],
    ]
    if password:
        commands.append(
            [
                "sudo",
                "nmcli",
                "connection",
                "modify",
                connection_name,
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                password,
            ]
        )
    else:
        commands.append(
            ["sudo", "nmcli", "connection", "modify", connection_name, "wifi-sec.key-mgmt", "none"]
        )

    for command in commands:
        result = run_command(command)
        if not result["ok"]:
            details.append(f"Profil {ssid} konnte nicht konfiguriert werden: {result['output']}")
            return {"ok": False, "details": details}

    details.append(f"Client-WLAN gespeichert: {ssid}")
    return {"ok": True, "details": details}


def recreate_hotspot_profile(config):
    details = []
    hotspot_name = "phoniebox-hotspot"
    if connection_exists(hotspot_name):
        run_command(["sudo", "nmcli", "connection", "delete", hotspot_name])
        details.append("Vorhandenes Hotspot-Profil ersetzt.")

    create = run_command(
        [
            "sudo",
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            "*",
            "con-name",
            hotspot_name,
            "ssid",
            config.get("hotspot_ssid", "Phonie-hotspot"),
        ]
    )
    if not create["ok"]:
        details.append(f"Hotspot-Profil konnte nicht angelegt werden: {create['output']}")
        return {"ok": False, "details": details}

    commands = [
        [
            "sudo",
            "nmcli",
            "connection",
            "modify",
            hotspot_name,
            "802-11-wireless.mode",
            "ap",
            "802-11-wireless.band",
            "bg",
            "802-11-wireless.channel",
            str(config.get("hotspot_channel", 6)),
            "ipv4.method",
            "shared",
            "ipv6.method",
            "ignore",
            "connection.autoconnect",
            "no",
        ]
    ]
    if normalize_hotspot_security(config.get("hotspot_security")) == "wpa-psk":
        commands.append(
            [
                "sudo",
                "nmcli",
                "connection",
                "modify",
                hotspot_name,
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                config.get("hotspot_password", ""),
            ]
        )
    else:
        commands.append(["sudo", "nmcli", "connection", "modify", hotspot_name, "wifi-sec.key-mgmt", "none"])

    for command in commands:
        result = run_command(command)
        if not result["ok"]:
            details.append(f"Hotspot konnte nicht konfiguriert werden: {result['output']}")
            return {"ok": False, "details": details}

    details.append(f"Hotspot-Profil vorbereitet: {config.get('hotspot_ssid', 'Phonie-hotspot')}")
    return {"ok": True, "details": details}


def apply_mode(config):
    details = []
    mode = config.get("mode", "client_with_fallback_hotspot")
    if mode == "hotspot_only":
        result = activate_hotspot_with_recovery("phoniebox-hotspot")
        if result["ok"]:
            details.append("Hotspot direkt aktiviert.")
        else:
            details.extend(result["details"])
        return {"ok": result["ok"], "details": details}

    run_command(["sudo", "nmcli", "connection", "down", "phoniebox-hotspot"])
    details.append("Hotspot deaktiviert, Client-WLAN hat Vorrang.")
    return {"ok": True, "details": details}


def apply_wifi_profile(config):
    details = []
    if not command_exists("nmcli"):
        return {"ok": False, "details": ["nmcli ist nicht installiert."]}

    radio = run_command(["sudo", "nmcli", "radio", "wifi", "on"])
    if not radio["ok"]:
        return {"ok": False, "details": [f"WLAN-Funk konnte nicht aktiviert werden: {radio['output']}"]}
    details.append("WLAN-Funk aktiviert.")

    for network in config.get("saved_networks", []):
        result = recreate_wifi_client(
            network.get("ssid", "").strip(),
            network.get("password", "").strip(),
            network.get("priority", 10),
        )
        details.extend(result["details"])
        if not result["ok"]:
            return {"ok": False, "details": details}

    hotspot = recreate_hotspot_profile(config)
    details.extend(hotspot["details"])
    if not hotspot["ok"]:
        return {"ok": False, "details": details}

    mode_result = apply_mode(config)
    details.extend(mode_result["details"])
    return {"ok": mode_result["ok"], "details": details}


def active_wifi_connected():
    if not command_exists("nmcli"):
        return False
    result = run_command(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
    if not result["ok"]:
        return False
    for line in result["output"].splitlines():
        parts = line.split(":", 1)
        if len(parts) == 2 and parts[0] == "yes" and parts[1]:
            return True
    return False


def fallback_hotspot_cycle(config):
    if not command_exists("nmcli"):
        return {"ok": False, "summary": "nmcli nicht verfügbar.", "details": ["NetworkManager wird benötigt."]}

    mode = config.get("mode", "client_with_fallback_hotspot")
    if mode != "client_with_fallback_hotspot" or not config.get("fallback_hotspot", True):
        return {
            "ok": True,
            "summary": "Fallback-Hotspot nicht aktiv.",
            "details": ["Modus oder Fallback-Schalter verhindern eine Umschaltung."],
        }

    if active_wifi_connected():
        run_command(["sudo", "nmcli", "connection", "down", "phoniebox-hotspot"])
        return {
            "ok": True,
            "summary": "Client-WLAN aktiv, Hotspot bleibt aus.",
            "details": ["Eine aktive WLAN-Verbindung wurde erkannt."],
        }

    result = activate_hotspot_with_recovery("phoniebox-hotspot")
    return {
        "ok": bool(result.get("ok")),
        "summary": "Fallback-Hotspot aktiviert." if result["ok"] else "Fallback-Hotspot konnte nicht aktiviert werden.",
        "details": result.get("details", []) or ["phoniebox-hotspot hochgefahren."],
    }
