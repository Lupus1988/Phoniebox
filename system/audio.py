import platform
import shutil
import subprocess
from pathlib import Path


I2S_PROFILE_OPTIONS = {
    "auto": {
        "label": "Automatisch / später auswählen",
        "dtoverlay": "",
        "notes": ["Noch kein fester I2S-HAT ausgewählt."],
    },
    "hifiberry-dac": {
        "label": "HiFiBerry DAC / DAC+",
        "dtoverlay": "dtoverlay=hifiberry-dac",
        "notes": ["Typischer I2S-DAC ohne zusätzliche Buttons."],
    },
    "googlevoicehat": {
        "label": "Google Voice HAT",
        "dtoverlay": "dtoverlay=googlevoicehat-soundcard",
        "notes": ["Audio-HAT mit zusätzlicher Voice-HAT-Unterstützung."],
    },
    "wm8960": {
        "label": "WM8960 Audio HAT",
        "dtoverlay": "dtoverlay=wm8960-soundcard",
        "notes": ["Häufig bei kompakten Lautsprecher-/Mikrofon-HATs."],
    },
    "seeed-2mic": {
        "label": "Seeed 2-Mic Voice Card",
        "dtoverlay": "dtoverlay=seeed-2mic-voicecard",
        "notes": ["Voicecard mit Mikrofon-Fokus."],
    },
}


def command_exists(name):
    return shutil.which(name) is not None


def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (result.stdout or result.stderr or "").strip()
    return {"ok": result.returncode == 0, "output": output}


def detect_device_model():
    model_path = Path("/proc/device-tree/model")
    if model_path.exists():
        try:
            return model_path.read_text(encoding="utf-8", errors="ignore").replace("\x00", "").strip()
        except OSError:
            return ""
    return platform.platform()


def parse_asound_cards():
    cards_path = Path("/proc/asound/cards")
    devices = []
    if not cards_path.exists():
        return devices
    lines = cards_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if "[" not in line or "]" not in line:
            index += 1
            continue
        raw_index, rest = line.split("[", 1)
        card_id, name = rest.split("]", 1)
        description = ""
        if index + 1 < len(lines):
            description = lines[index + 1].strip()
        devices.append(
            {
                "card_index": raw_index.strip(),
                "card_id": card_id.strip(),
                "name": name.strip(" -"),
                "description": description,
            }
        )
        index += 2
    return devices


def list_playback_devices():
    if not command_exists("aplay"):
        return []
    result = run_command(["aplay", "-l"])
    if not result["ok"]:
        return []
    devices = []
    for line in result["output"].splitlines():
        stripped = line.strip()
        if not stripped.startswith("card "):
            continue
        try:
            prefix, rest = stripped.split(":", 1)
            card_part, device_part = prefix.split(",")
            card_index = card_part.replace("card", "").strip()
            card_name = rest.split("[", 1)[0].strip()
            device_index = device_part.replace("device", "").strip()
            device_name = rest.split("[", 1)[1].split("]", 1)[0].strip() if "[" in rest else rest.strip()
            devices.append(
                {
                    "card_index": card_index,
                    "device_index": device_index,
                    "name": card_name,
                    "device_name": device_name,
                    "alsa_hw": f"hw:{card_index},{device_index}",
                }
            )
        except ValueError:
            continue
    return devices


def detect_audio_environment():
    model = detect_device_model()
    cards = parse_asound_cards()
    playback_devices = list_playback_devices()
    card_ids = {entry.get("card_id", "").lower() for entry in cards}
    card_texts = [
        " ".join(
            [
                entry.get("card_id", ""),
                entry.get("name", ""),
                entry.get("description", ""),
            ]
        ).lower()
        for entry in cards
    ]
    lower_model = model.lower()
    is_pi_zero_2w = "raspberry pi zero 2" in lower_model
    has_analog = any(("bcm2835" in item or "headphones" in item or "analog" in item) for item in card_texts)
    has_hdmi = any("vc4hdmi" in item or "hdmi" in item for item in card_ids)
    has_usb = any("usb" in item or "audio" in item for item in card_ids)
    has_i2s_hat = any(
        token in item
        for item in card_ids
        for token in {"hifiberry", "seeed", "iqaudio", "sndrpihifiberry", "googlevoicehat", "adau", "wm8960"}
    )
    notes = []
    if not cards:
        notes.append("Keine ALSA-Soundkarten erkannt.")
    if is_pi_zero_2w and not (has_usb or has_i2s_hat):
        notes.append("Pi Zero 2 W erkannt. Für Audio ist meist eine USB- oder I2S-Soundkarte nötig.")
    if has_usb:
        notes.append("USB-Audio erkannt.")
    if has_i2s_hat:
        notes.append("I2S-/GPIO-Audio-HAT erkannt.")
    if has_analog:
        notes.append("Onboard-Analog-Audio erkannt.")
    return {
        "device_model": model or "Unbekannt",
        "is_pi_zero_2w": is_pi_zero_2w,
        "cards": cards,
        "playback_devices": playback_devices,
        "has_usb_audio": has_usb,
        "has_i2s_audio": has_i2s_hat,
        "has_hdmi_audio": has_hdmi,
        "has_analog_audio": has_analog,
        "recommended_external_card": is_pi_zero_2w and not (has_usb or has_i2s_hat),
        "notes": notes,
    }


def i2s_profile_catalog():
    return [{"id": key, "label": value["label"]} for key, value in I2S_PROFILE_OPTIONS.items()]


def _card_tokens(card):
    return " ".join(
        [
            str(card.get("card_id", "")),
            str(card.get("name", "")),
            str(card.get("description", "")),
        ]
    ).lower()


def _card_matches_mode(card, mode):
    tokens = _card_tokens(card)
    if mode == "usb_dac":
        return "usb" in tokens or "audio" in tokens
    if mode == "analog_jack":
        return "bcm2835" in tokens or "analog" in tokens
    if mode == "i2s_dac":
        return any(token in tokens for token in {"hifiberry", "seeed", "iqaudio", "sndrpihifiberry", "googlevoicehat", "adau", "wm8960"})
    return False


def resolve_output_device(snapshot, config):
    mode = config.get("output_mode", "usb_dac")
    cards = snapshot.get("cards", [])
    playback_devices = snapshot.get("playback_devices", [])
    for device in playback_devices:
        card_index = str(device.get("card_index", ""))
        matching_card = next((card for card in cards if str(card.get("card_index", "")) == card_index), None)
        if matching_card and _card_matches_mode(matching_card, mode):
            return device.get("alsa_hw", "default")
    for card in cards:
        if _card_matches_mode(card, mode):
            return f"hw:{card.get('card_index', '0')},0"
    if playback_devices:
        return playback_devices[0].get("alsa_hw", "default")
    if cards:
        return f"hw:{cards[0].get('card_index', '0')},0"
    return "default"


def build_asound_conf(snapshot, config):
    output_device = resolve_output_device(snapshot, config)
    mono_type = "plug" if config.get("mono_downmix") else "asym"
    extra_slave = ""
    if config.get("mono_downmix"):
        extra_slave = """
    slave {
      pcm "hw_output"
      channels 2
    }
    ttable.0.0 1
    ttable.0.1 1
    ttable.1.0 1
    ttable.1.1 1
"""
    return f"""# Generiert durch Phoniebox Panel
pcm.hw_output {{
  type hw
  card {output_device.split(':', 1)[1].split(',')[0] if output_device.startswith('hw:') else output_device}
}}

pcm.!default {{
  type {mono_type}{extra_slave if extra_slave else f'''
  playback.pcm "{output_device}"
  capture.pcm "{output_device}"
'''} }}

ctl.!default {{
  type hw
  card {output_device.split(':', 1)[1].split(',')[0] if output_device.startswith('hw:') else output_device}
}}
"""


def build_boot_config(config):
    mode = config.get("output_mode", "auto")
    i2s_profile = I2S_PROFILE_OPTIONS.get(config.get("i2s_profile", "auto"), I2S_PROFILE_OPTIONS["auto"])
    lines = ["# Generiert durch Phoniebox Panel", "# Snippet für /boot/firmware/config.txt oder /boot/config.txt"]
    notes = []
    if mode == "analog_jack":
        lines.append("dtparam=audio=on")
        notes.append("Analog-Ausgang aktivieren.")
    elif mode == "hdmi":
        lines.append("hdmi_drive=2")
        notes.append("HDMI-Audio erzwingen.")
    elif mode == "i2s_dac":
        lines.append("dtparam=audio=off")
        if i2s_profile["dtoverlay"]:
            lines.append(i2s_profile["dtoverlay"])
        notes.extend(i2s_profile["notes"])
    else:
        lines.append("# Kein spezielles Boot-Overlay nötig.")
    return "\n".join(lines) + "\n", notes


def build_startup_volume_script(config):
    if not config.get("use_startup_volume"):
        return """#!/usr/bin/env bash
set -euo pipefail
exit 0
"""
    volume = max(0, min(100, int(config.get("startup_volume", 45))))
    mixer = (config.get("mixer_control") or "auto").strip()
    mixer_target = "Master" if mixer == "auto" else mixer
    return f"""#!/usr/bin/env bash
set -euo pipefail

if command -v amixer >/dev/null 2>&1; then
  amixer sset '{mixer_target}' '{volume}%'
fi
"""


def build_summary(snapshot, config):
    lines = [
        "Phoniebox Audio-Profil",
        f"Gerät: {snapshot.get('device_model', 'Unbekannt')}",
        f"Verwendete Soundkarte: {config.get('output_mode', 'usb_dac')}",
        f"Playback-Backend: {config.get('playback_backend', 'auto')}",
    ]
    if config.get("use_startup_volume"):
        lines.append(f"Startlautstärke: {config.get('startup_volume', 45)}%")
    else:
        lines.append("Startlautstärke: letzte Lautstärke übernehmen")
    if config.get("output_mode") == "i2s_dac":
        profile = I2S_PROFILE_OPTIONS.get(config.get("i2s_profile", "auto"), I2S_PROFILE_OPTIONS["auto"])
        lines.append(f"I2S-Profil: {profile['label']}")
    if snapshot.get("notes"):
        lines.append("")
        lines.append("Hinweise:")
        lines.extend(f"- {note}" for note in snapshot["notes"])
    return "\n".join(lines) + "\n"


def write_audio_artifacts(output_dir, snapshot, config):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    asound_conf = build_asound_conf(snapshot, config)
    boot_config, boot_notes = build_boot_config(config)
    startup_script = build_startup_volume_script(config)
    summary = build_summary(snapshot, config)

    asound_path = output_dir / "asound.conf"
    boot_path = output_dir / "boot-config.txt"
    startup_path = output_dir / "set-startup-volume.sh"
    summary_path = output_dir / "README.txt"

    asound_path.write_text(asound_conf, encoding="utf-8")
    boot_path.write_text(boot_config, encoding="utf-8")
    startup_path.write_text(startup_script, encoding="utf-8")
    summary_path.write_text(summary, encoding="utf-8")
    startup_path.chmod(0o755)

    return {
        "asound_conf": asound_path,
        "boot_config": boot_path,
        "startup_script": startup_path,
        "summary": summary_path,
        "boot_notes": boot_notes,
    }


def _backup_file(path):
    if not path.exists():
        return None
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path


def _replace_managed_block(path, content):
    begin = "# >>> Phoniebox Audio >>>"
    end = "# <<< Phoniebox Audio <<<"
    block = f"{begin}\n{content.rstrip()}\n{end}\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if begin in existing and end in existing:
        before, rest = existing.split(begin, 1)
        _, after = rest.split(end, 1)
        updated = before.rstrip() + "\n" + block + after.lstrip("\n")
    else:
        updated = existing.rstrip() + ("\n\n" if existing.strip() else "") + block
    path.write_text(updated, encoding="utf-8")


def deploy_audio_profile(config, generated_dir, target_root="/"):
    generated_dir = Path(generated_dir)
    target_root = Path(target_root)
    details = []
    if not generated_dir.exists():
        return {"ok": False, "details": ["Keine generierten Audio-Artefakte vorhanden."], "deployed_files": []}

    deployed_files = []
    try:
        etc_dir = target_root / "etc"
        usr_local_bin = target_root / "usr" / "local" / "bin"
        systemd_dir = target_root / "etc" / "systemd" / "system"
        etc_dir.mkdir(parents=True, exist_ok=True)
        usr_local_bin.mkdir(parents=True, exist_ok=True)
        systemd_dir.mkdir(parents=True, exist_ok=True)

        asound_target = etc_dir / "asound.conf"
        startup_target = usr_local_bin / "phoniebox-set-startup-volume.sh"
        service_target = systemd_dir / "phoniebox-audio-init.service"

        for target in [asound_target, startup_target, service_target]:
            backup = _backup_file(target)
            if backup:
                details.append(f"Backup erstellt: {backup}")

        shutil.copy2(generated_dir / "asound.conf", asound_target)
        deployed_files.append(asound_target)
        details.append(f"ALSA-Profil installiert: {asound_target}")

        shutil.copy2(generated_dir / "set-startup-volume.sh", startup_target)
        startup_target.chmod(0o755)
        deployed_files.append(startup_target)
        details.append(f"Startlautstärke-Skript installiert: {startup_target}")

        service_content = """[Unit]
Description=Phoniebox Audio Init
After=sound.target
Wants=sound.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/phoniebox-set-startup-volume.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
        service_target.write_text(service_content, encoding="utf-8")
        deployed_files.append(service_target)
        details.append(f"Systemd-Service installiert: {service_target}")

        if config.get("apply_boot_config"):
            boot_candidates = [
                target_root / "boot" / "firmware" / "usercfg.txt",
                target_root / "boot" / "usercfg.txt",
            ]
            boot_target = next((candidate for candidate in boot_candidates if candidate.parent.exists()), boot_candidates[0])
            boot_target.parent.mkdir(parents=True, exist_ok=True)
            backup = _backup_file(boot_target)
            if backup:
                details.append(f"Backup erstellt: {backup}")
            boot_content = (generated_dir / "boot-config.txt").read_text(encoding="utf-8")
            _replace_managed_block(boot_target, boot_content)
            deployed_files.append(boot_target)
            details.append(f"Boot-Konfiguration aktualisiert: {boot_target}")

        if config.get("enable_audio_service") and command_exists("systemctl") and target_root == Path("/"):
            daemon_reload = run_command(["sudo", "systemctl", "daemon-reload"])
            enable = run_command(["sudo", "systemctl", "enable", "phoniebox-audio-init.service"])
            if daemon_reload["ok"] and enable["ok"]:
                details.append("Systemd-Service aktiviert.")
            else:
                details.append(f"Service-Aktivierung unvollständig: {daemon_reload['output'] or enable['output']}")

        return {"ok": True, "details": details, "deployed_files": [str(path) for path in deployed_files]}
    except OSError as exc:
        details.append(f"Deployment fehlgeschlagen: {exc}")
        return {"ok": False, "details": details, "deployed_files": [str(path) for path in deployed_files]}


def apply_audio_profile(config, output_dir=None):
    snapshot = detect_audio_environment()
    details = [f"Gerätemodell: {snapshot['device_model']}"]
    mode = config.get("output_mode", "usb_dac")
    details.append(f"Verwendete Soundkarte: {mode}")
    details.append(
        f"Startlautstärke: {config.get('startup_volume', 45)}%"
        if config.get("use_startup_volume")
        else "Startlautstärke: letzte Lautstärke bleibt erhalten"
    )

    artifacts = None
    if output_dir:
        artifacts = write_audio_artifacts(output_dir, snapshot, config)
        details.append(f"Audio-Artefakte erzeugt unter: {output_dir}")
        details.extend(artifacts.get("boot_notes", []))

    if not snapshot["cards"]:
        details.append("Noch keine Soundkarte erkannt. Profil wird als Soll-Konfiguration gespeichert.")
        return {"ok": False, "details": details, "snapshot": snapshot, "artifacts": artifacts}

    if config.get("use_startup_volume") and command_exists("amixer"):
        target = config.get("mixer_control", "auto")
        details.append(f"Mixer-Steuerung verfügbar ({target}).")
    elif config.get("use_startup_volume"):
        details.append("amixer nicht verfügbar. Lautstärke muss ggf. später manuell oder per Dienst gesetzt werden.")

    details.extend(snapshot["notes"])
    details.append("Audio-Profil erkannt und für spätere Systemintegration vorbereitet.")
    return {"ok": True, "details": details, "snapshot": snapshot, "artifacts": artifacts}
