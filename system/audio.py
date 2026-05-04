import platform
import shutil
import subprocess
from pathlib import Path

APP_ROOT = Path("/opt/phoniebox-panel")
MPD_CONFIG_PATH = Path("/etc/mpd.conf")
MPD_SERVICE_NAME = "mpd.service"


def command_exists(name):
    return shutil.which(name) is not None


def run_command(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=2.0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "Zeitüberschreitung bei Systemabfrage."}
    output = (result.stdout or result.stderr or "").strip()
    return {"ok": result.returncode == 0, "output": output}


def parse_simple_mixer_controls(output):
    controls = []
    for line in (output or "").splitlines():
        stripped = line.strip()
        prefix = "Simple mixer control '"
        if not stripped.startswith(prefix):
            continue
        remainder = stripped[len(prefix) :]
        if "'," not in remainder:
            continue
        control_name = remainder.split("',", 1)[0].strip()
        if control_name and control_name not in controls:
            controls.append(control_name)
    return controls


def normalize_alsa_index(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return str(int(text))
    return text


def preferred_mixer_control(controls):
    normalized = [str(control or "").strip() for control in list(controls or []) if str(control or "").strip()]
    preferred_names = ("PCM", "Master", "Speaker", "Digital")
    for preferred in preferred_names:
        for control in normalized:
            if control.lower() == preferred.lower():
                return control
    return normalized[0] if normalized else ""


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
                "card_index": normalize_alsa_index(raw_index),
                "card_id": card_id.strip(),
                "name": name.strip(" -"),
                "description": description,
            }
        )
        index += 2
    return devices


def list_playback_devices():
    devices = []
    if not command_exists("aplay"):
        return parse_proc_asound_pcm()
    result = run_command(["aplay", "-l"])
    if not result["ok"]:
        return parse_proc_asound_pcm()
    for line in result["output"].splitlines():
        stripped = line.strip()
        if not stripped.startswith("card "):
            continue
        try:
            prefix, rest = stripped.split(":", 1)
            card_part, device_part = prefix.split(",")
            card_index = normalize_alsa_index(card_part.replace("card", ""))
            card_name = rest.split("[", 1)[0].strip()
            device_index = normalize_alsa_index(device_part.replace("device", ""))
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
    return devices or parse_proc_asound_pcm()


def mixer_controls_for_card(card_name):
    if not command_exists("amixer"):
        return []
    result = run_command(["amixer", "-c", str(card_name), "scontrols"])
    if not result["ok"]:
        return []
    return parse_simple_mixer_controls(result["output"])


def parse_proc_asound_pcm(pcm_path=None):
    pcm_path = Path(pcm_path or "/proc/asound/pcm")
    devices = []
    if not pcm_path.exists():
        return devices
    for line in pcm_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if ": playback " not in stripped:
            continue
        try:
            raw_index, rest = stripped.split(":", 1)
            card_index, device_index = raw_index.split("-", 1)
            name_part, device_part = rest.split(":", 1)
            name = name_part.strip()
            device_name = device_part.split(":", 1)[0].strip()
            devices.append(
                {
                    "card_index": normalize_alsa_index(card_index),
                    "device_index": normalize_alsa_index(device_index),
                    "name": name,
                    "device_name": device_name,
                    "alsa_hw": f"hw:{normalize_alsa_index(card_index)},{normalize_alsa_index(device_index)}",
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
    has_hdmi = any("vc4hdmi" in item or "hdmi" in item for item in card_texts)
    has_usb = any("usb" in item or "audio" in item for item in card_texts)
    has_i2s_hat = False
    notes = []
    if not cards:
        notes.append("Keine ALSA-Soundkarten erkannt.")
    if is_pi_zero_2w and not has_usb:
        notes.append("Pi Zero 2 W erkannt.")
    if has_usb:
        notes.append("USB-Audio erkannt.")
    if has_analog:
        notes.append("Onboard-Analog-Audio erkannt.")
    mixer_controls = []
    volume_card = None
    for card in cards:
        card_id = str(card.get("card_id", "") or "").strip()
        card_index = str(card.get("card_index", "") or "").strip()
        controls = mixer_controls_for_card(card_id) if card_id else []
        if not controls and card_index:
            controls = mixer_controls_for_card(card_index)
        if controls:
            mixer_controls = controls
            volume_card = card_index or card_id
            break
    has_alsa = bool(cards)
    if has_alsa:
        notes.append("ALSA-Soundsystem erkannt.")
    if mixer_controls:
        notes.append(f"ALSA-Mixer erkannt ({', '.join(mixer_controls)}).")
    return {
        "device_model": model or "Unbekannt",
        "is_pi_zero_2w": is_pi_zero_2w,
        "cards": cards,
        "playback_devices": playback_devices,
        "has_alsa": has_alsa,
        "has_alsa_mixer": bool(mixer_controls),
        "alsa_mixer_controls": mixer_controls,
        "alsa_volume_card": volume_card or "",
        "alsa_mixer_control": preferred_mixer_control(mixer_controls),
        "has_usb_audio": has_usb,
        "has_i2s_audio": has_i2s_hat,
        "has_hdmi_audio": has_hdmi,
        "has_analog_audio": has_analog,
        "recommended_external_card": is_pi_zero_2w and not has_usb,
        "notes": notes,
    }



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
    return False


def resolve_output_device(snapshot, config):
    mode = config.get("output_mode", "usb_dac")
    cards = snapshot.get("cards", [])
    playback_devices = snapshot.get("playback_devices", [])
    for device in playback_devices:
        card_index = normalize_alsa_index(device.get("card_index", ""))
        matching_card = next(
            (card for card in cards if normalize_alsa_index(card.get("card_index", "")) == card_index),
            None,
        )
        if matching_card and _card_matches_mode(matching_card, mode):
            return device.get("alsa_hw", "default")
    for card in cards:
        if _card_matches_mode(card, mode):
            return f"hw:{normalize_alsa_index(card.get('card_index', '0'))},0"
    if playback_devices:
        return playback_devices[0].get("alsa_hw", "default")
    if cards:
        return f"hw:{normalize_alsa_index(cards[0].get('card_index', '0'))},0"
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
    mode = config.get("output_mode", "usb_dac")
    lines = ["# Generiert durch Phoniebox Panel", "# Snippet für /boot/firmware/config.txt oder /boot/config.txt"]
    notes = []
    if mode == "analog_jack":
        lines.append("dtparam=audio=on")
        notes.append("Analog-Ausgang aktivieren.")
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
    if snapshot.get("notes"):
        lines.append("")
        lines.append("Hinweise:")
        lines.extend(f"- {note}" for note in snapshot["notes"])
    return "\n".join(lines) + "\n"


def build_mpd_conf(snapshot, config, app_root=APP_ROOT):
    app_root = Path(app_root)
    output_device = resolve_output_device(snapshot, config)
    mpd_device = f"plug{output_device}" if str(output_device).startswith("hw:") else str(output_device)
    volume_backend = str(config.get("volume_backend", "mpd") or "mpd").strip().lower()
    mixer_control = str(config.get("mixer_control", "auto") or "auto").strip()
    if volume_backend == "amixer":
        mixer_type = "null"
        mixer_block = ""
    else:
        mixer_type = "hardware" if mixer_control not in {"", "auto"} else "software"
        mixer_block = ""
        if mixer_type == "hardware":
            mixer_block = f'\n  mixer_control "{mixer_control}"'
    db_dir = Path("/var/lib/mpd")
    playlists_dir = db_dir / "playlists"
    state_dir = Path("/var/run/mpd")
    return f"""# Generiert durch Phoniebox Panel
music_directory "{app_root}"
playlist_directory "{playlists_dir}"
db_file "{db_dir / 'database'}"
state_file "{db_dir / 'state'}"
sticker_file "{db_dir / 'sticker.sql'}"
pid_file "{state_dir / 'pid'}"
bind_to_address "localhost"
auto_update "yes"
restore_paused "yes"
follow_inside_symlinks "yes"
follow_outside_symlinks "no"

audio_output {{
  type "alsa"
  name "Phoniebox ALSA"
  device "{mpd_device}"
  auto_resample "no"
  auto_channels "no"
  auto_format "no"
  mixer_type "{mixer_type}"{mixer_block}
}}
"""


def write_audio_artifacts(output_dir, snapshot, config):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    asound_conf = build_asound_conf(snapshot, config)
    boot_config, boot_notes = build_boot_config(config)
    startup_script = build_startup_volume_script(config)
    summary = build_summary(snapshot, config)
    mpd_conf = build_mpd_conf(snapshot, config)

    asound_path = output_dir / "asound.conf"
    boot_path = output_dir / "boot-config.txt"
    startup_path = output_dir / "set-startup-volume.sh"
    summary_path = output_dir / "README.txt"
    mpd_path = output_dir / "mpd.conf"

    asound_path.write_text(asound_conf, encoding="utf-8")
    boot_path.write_text(boot_config, encoding="utf-8")
    startup_path.write_text(startup_script, encoding="utf-8")
    summary_path.write_text(summary, encoding="utf-8")
    mpd_path.write_text(mpd_conf, encoding="utf-8")
    startup_path.chmod(0o755)

    return {
        "asound_conf": asound_path,
        "boot_config": boot_path,
        "startup_script": startup_path,
        "summary": summary_path,
        "mpd_conf": mpd_path,
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
        mpd_target = target_root / MPD_CONFIG_PATH.relative_to("/")

        for target in [asound_target, startup_target, service_target, mpd_target]:
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

        shutil.copy2(generated_dir / "mpd.conf", mpd_target)
        deployed_files.append(mpd_target)
        details.append(f"MPD-Konfiguration installiert: {mpd_target}")

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

        if (
            str(config.get("playback_backend", "current") or "current").strip().lower() == "mpd"
            and command_exists("systemctl")
            and target_root == Path("/")
        ):
            enable_mpd = run_command(["sudo", "systemctl", "enable", MPD_SERVICE_NAME])
            restart_mpd = run_command(["sudo", "systemctl", "restart", MPD_SERVICE_NAME])
            if enable_mpd["ok"] and restart_mpd["ok"]:
                details.append("MPD-Service aktiviert und neu gestartet.")
            else:
                details.append(f"MPD-Service konnte nicht vollständig aktualisiert werden: {enable_mpd['output'] or restart_mpd['output']}")

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
