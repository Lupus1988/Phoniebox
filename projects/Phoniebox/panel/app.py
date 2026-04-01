import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename
try:
    import gpiod
except ImportError:
    gpiod = None


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.gpio import GPIO_PINS, GPIO_TO_BOARD_PIN, gpio_display_label, sample_gpio_levels_sysfs
from runtime.service import RuntimeService
from system.audio import apply_audio_profile, deploy_audio_profile, detect_audio_environment, i2s_profile_catalog
from system.networking import apply_wifi_profile, ensure_hostname, fallback_hotspot_cycle

DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = BASE_DIR / "media"
ALBUMS_DIR = MEDIA_DIR / "albums"
PLAYER_FILE = DATA_DIR / "player_state.json"
LIBRARY_FILE = DATA_DIR / "library.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SETUP_FILE = DATA_DIR / "setup.json"
APPLY_REPORT_FILE = DATA_DIR / "last_apply_report.json"
RUNTIME_FILE = DATA_DIR / "runtime_state.json"
LINK_SESSION_FILE = DATA_DIR / "rfid_link_session.json"
BUTTON_DETECT_FILE = DATA_DIR / "button_detect.json"
AUDIO_PROFILE_DIR = DATA_DIR / "generated" / "audio"
READER_GUIDE_DIR = BASE_DIR / "assets" / "reader-guides"
AUDIO_GUIDE_DIR = BASE_DIR / "assets" / "audio-guides"
HOTSPOT_SECURITY_CHOICES = {"open", "wpa-psk"}

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.secret_key = "phoniebox-panel-dev-secret"
runtime_service = RuntimeService()
PWM_PINS = {"GPIO12", "GPIO13", "GPIO18", "GPIO19"}
BUTTON_FUNCTIONS = [
    "Play/Pause",
    "Stopp",
    "Vor",
    "Zurück",
    "Lautstärke +",
    "Lautstärke -",
    "Sleep Timer +",
    "Sleep Timer -",
    "Wifi on/off",
    "Power on/off",
]
LED_FUNCTIONS = ["power_on", "standby", "sleep_1", "sleep_2", "sleep_3", "wifi_on"]
POWER_ROUTINE_OPTIONS = [
    {
        "id": "sleep_count_up_5",
        "label": "5s LEDs hoch",
        "type": "power_on",
        "duration_seconds": 5.0,
        "animation": "sleep_count_up",
        "description": "5 Sekunden halten. Die drei Sleeptimer-LEDs laufen von aus über 1, 1+2 bis 1+2+3 hoch. Danach geht die Box aus dem Standby an.",
    },
    {
        "id": "sleep_count_up_3",
        "label": "3s LEDs hoch",
        "type": "power_on",
        "duration_seconds": 3.0,
        "animation": "sleep_count_up",
        "description": "3 Sekunden halten. Die drei Sleeptimer-LEDs laufen von aus über 1, 1+2 bis 1+2+3 hoch. Danach geht die Box aus dem Standby an.",
    },
    {
        "id": "power_flicker_up_5",
        "label": "5s Power schnell",
        "type": "power_on",
        "duration_seconds": 5.0,
        "animation": "power_flicker_up",
        "description": "5 Sekunden halten. Die Power-LED blinkt erst langsam und dann immer schneller, bis sie dauerhaft leuchtet. Danach ist die Box an.",
    },
    {
        "id": "power_flicker_up_3",
        "label": "3s Power schnell",
        "type": "power_on",
        "duration_seconds": 3.0,
        "animation": "power_flicker_up",
        "description": "3 Sekunden halten. Die Power-LED blinkt erst langsam und dann immer schneller, bis sie dauerhaft leuchtet. Danach ist die Box an.",
    },
    {
        "id": "sleep_count_down_5",
        "label": "5s LEDs runter",
        "type": "power_off",
        "duration_seconds": 5.0,
        "animation": "sleep_count_down",
        "description": "5 Sekunden halten. Die drei Sleeptimer-LEDs laufen von 1+2+3 über 1+2 und 1 herunter, danach geht die Box in den Standby.",
    },
    {
        "id": "sleep_count_down_3",
        "label": "3s LEDs runter",
        "type": "power_off",
        "duration_seconds": 3.0,
        "animation": "sleep_count_down",
        "description": "3 Sekunden halten. Die drei Sleeptimer-LEDs laufen von 1+2+3 über 1+2 und 1 herunter, danach geht die Box in den Standby.",
    },
    {
        "id": "power_flicker_down_5",
        "label": "5s Power langsam",
        "type": "power_off",
        "duration_seconds": 5.0,
        "animation": "power_flicker_down",
        "description": "5 Sekunden halten. Die Power-LED blinkt erst schnell und dann immer langsamer, bis sie ausgeht. Danach geht die Box in den Standby.",
    },
    {
        "id": "power_flicker_down_3",
        "label": "3s Power langsam",
        "type": "power_off",
        "duration_seconds": 3.0,
        "animation": "power_flicker_down",
        "description": "3 Sekunden halten. Die Power-LED blinkt erst schnell und dann immer langsamer, bis sie ausgeht. Danach geht die Box in den Standby.",
    },
]
READER_OPTIONS = [
    {"id": "USB", "label": "USB-Reader", "driver": "hid/keyboard-reader", "transport": "usb"},
    {"id": "RC522", "label": "RC522", "driver": "mfrc522", "transport": "spi"},
    {"id": "PN532_I2C", "label": "PN532 (I2C)", "driver": "pn532", "transport": "i2c"},
    {"id": "PN532_SPI", "label": "PN532 (SPI)", "driver": "pn532", "transport": "spi"},
    {"id": "PN532_UART", "label": "PN532 (UART)", "driver": "pn532", "transport": "uart"},
]


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.stem}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    temp_path.replace(path)


def merge_defaults(data, defaults):
    if not isinstance(defaults, dict):
        return data if data is not None else defaults
    result = dict(defaults)
    if not isinstance(data, dict):
        return result
    for key, value in data.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_defaults(value, result[key])
        else:
            result[key] = value
    return result


def slugify_name(value):
    cleaned = secure_filename((value or "").strip())
    return cleaned.replace("_", "-").lower() or f"album-{secrets.token_hex(4)}"


def safe_relative_path(raw_name):
    parts = []
    for part in Path(raw_name).parts:
        if part in {"", ".", ".."}:
            continue
        cleaned = secure_filename(part)
        if cleaned:
            parts.append(cleaned)
    return Path(*parts) if parts else Path("datei")


def is_audio_file(path):
    return path.suffix.lower() in {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"}


def is_cover_file(path):
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


def build_playlist(album_dir):
    audio_files = sorted(
        [path for path in album_dir.rglob("*") if path.is_file() and is_audio_file(path)],
        key=lambda item: str(item.relative_to(album_dir)).lower(),
    )
    playlist_path = album_dir / "playlist.m3u"
    playlist_lines = ["#EXTM3U"]
    for track in audio_files:
        playlist_lines.append(track.relative_to(album_dir).as_posix())
    playlist_path.write_text("\n".join(playlist_lines) + "\n", encoding="utf-8")
    return playlist_path, audio_files


def detect_cover(album_dir):
    image_files = sorted([path for path in album_dir.rglob("*") if path.is_file() and is_cover_file(path)])
    if not image_files:
        return ""
    preferred = next((path for path in image_files if path.stem.lower() in {"cover", "folder"}), image_files[0])
    return preferred.relative_to(BASE_DIR).as_posix()


def import_album_folder(files, album_name, rfid_uid=""):
    if not files:
        raise ValueError("Kein Ordnerinhalt hochgeladen.")

    library_data = load_library()
    requested_name = album_name.strip()
    if any((album.get("name", "").strip().lower() == requested_name.lower()) for album in library_data.get("albums", [])):
        raise ValueError("Albumname bereits vorhanden.")
    album_slug = slugify_name(album_name)
    album_dir = ALBUMS_DIR / album_slug
    if album_dir.exists():
        shutil.rmtree(album_dir)
    album_dir.mkdir(parents=True, exist_ok=True)

    raw_paths = [safe_relative_path(getattr(storage, "filename", "") or "") for storage in files]
    root_prefix = None
    if raw_paths:
        first_parts = [path.parts[0] for path in raw_paths if len(path.parts) > 1]
        if first_parts and len(first_parts) == len(raw_paths) and len(set(first_parts)) == 1:
            root_prefix = first_parts[0]

    for storage, raw_path in zip(files, raw_paths):
        source_name = getattr(storage, "filename", "") or ""
        relative_path = raw_path
        if root_prefix and relative_path.parts and relative_path.parts[0] == root_prefix:
            relative_path = Path(*relative_path.parts[1:]) if len(relative_path.parts) > 1 else Path(relative_path.name)
        if str(relative_path) in {"", "."}:
            relative_path = safe_relative_path(source_name)
        target = album_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        storage.save(target)

    playlist_path, audio_files = build_playlist(album_dir)
    if not audio_files:
        shutil.rmtree(album_dir, ignore_errors=True)
        raise ValueError("Im hochgeladenen Ordner wurden keine Audiodateien gefunden.")

    cover_url = detect_cover(album_dir)
    album_entry = {
        "id": f"album-{secrets.token_hex(4)}",
        "name": album_name.strip() or album_slug,
        "folder": album_dir.relative_to(BASE_DIR).as_posix(),
        "playlist": playlist_path.relative_to(BASE_DIR).as_posix(),
        "track_count": len(audio_files),
        "rfid_uid": rfid_uid.strip(),
        "cover_url": cover_url,
    }

    conflict = album_conflict(library_data["albums"], album_entry["id"], album_entry["rfid_uid"])
    if conflict:
        shutil.rmtree(album_dir, ignore_errors=True)
        raise ValueError(f"RFID-Tag bereits mit {conflict['name']} verknüpft.")

    library_data["albums"].append(album_entry)
    save_library(library_data)
    return album_entry


def unique_album_dir(album_name):
    base_slug = slugify_name(album_name)
    album_dir = ALBUMS_DIR / base_slug
    counter = 2
    while album_dir.exists():
        album_dir = ALBUMS_DIR / f"{base_slug}-{counter}"
        counter += 1
    album_dir.mkdir(parents=True, exist_ok=True)
    return album_dir


def write_empty_playlist(album_dir):
    playlist_path = album_dir / "playlist.m3u"
    playlist_path.write_text("#EXTM3U\n", encoding="utf-8")
    return playlist_path


def read_playlist_entries(album):
    playlist_path = BASE_DIR / album.get("playlist", "")
    if not playlist_path.exists():
        return []
    entries = []
    for line in playlist_path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        entries.append(item)
    return entries


def refresh_album_metadata(album):
    album_dir = BASE_DIR / album.get("folder", "")
    if not album_dir.exists():
        return album
    audio_files = sorted(
        [path for path in album_dir.rglob("*") if path.is_file() and is_audio_file(path)],
        key=lambda item: str(item.relative_to(album_dir)).lower(),
    )
    if audio_files:
        playlist_path, _ = build_playlist(album_dir)
    else:
        playlist_path = write_empty_playlist(album_dir)
    album["playlist"] = playlist_path.relative_to(BASE_DIR).as_posix()
    album["track_count"] = len(audio_files)
    album["cover_url"] = detect_cover(album_dir)
    album["track_entries"] = read_playlist_entries(album)
    return album


def create_empty_album(album_name, rfid_uid=""):
    library_data = load_library()
    requested_name = album_name.strip()
    if any((album.get("name", "").strip().lower() == requested_name.lower()) for album in library_data.get("albums", [])):
        raise ValueError("Albumname bereits vorhanden.")
    album_dir = unique_album_dir(album_name)
    playlist_path = write_empty_playlist(album_dir)
    album_entry = {
        "id": f"album-{secrets.token_hex(4)}",
        "name": album_name.strip() or album_dir.name,
        "folder": album_dir.relative_to(BASE_DIR).as_posix(),
        "playlist": playlist_path.relative_to(BASE_DIR).as_posix(),
        "track_count": 0,
        "rfid_uid": rfid_uid.strip(),
        "cover_url": "",
    }
    conflict = album_conflict(library_data["albums"], album_entry["id"], album_entry["rfid_uid"])
    if conflict:
        shutil.rmtree(album_dir, ignore_errors=True)
        raise ValueError(f"RFID-Tag bereits mit {conflict['name']} verknüpft.")
    library_data["albums"].append(album_entry)
    save_library(library_data)
    return album_entry


def add_tracks_to_album(album, files):
    album_dir = BASE_DIR / album.get("folder", "")
    album_dir.mkdir(parents=True, exist_ok=True)
    valid_files = [item for item in files if getattr(item, "filename", "")]
    if not valid_files:
        raise ValueError("Keine Dateien ausgewählt.")

    raw_paths = [safe_relative_path(getattr(storage, "filename", "") or "") for storage in valid_files]
    root_prefix = None
    if raw_paths:
        first_parts = [path.parts[0] for path in raw_paths if len(path.parts) > 1]
        if first_parts and len(first_parts) == len(raw_paths) and len(set(first_parts)) == 1:
            root_prefix = first_parts[0]

    saved_audio = 0
    for storage, raw_path in zip(valid_files, raw_paths):
        relative_path = raw_path
        if root_prefix and relative_path.parts and relative_path.parts[0] == root_prefix:
            relative_path = Path(*relative_path.parts[1:]) if len(relative_path.parts) > 1 else Path(relative_path.name)
        if str(relative_path) in {"", "."}:
            relative_path = safe_relative_path(getattr(storage, "filename", "") or "")
        if not is_audio_file(relative_path):
            continue
        target = album_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        storage.save(target)
        saved_audio += 1

    if not saved_audio:
        raise ValueError("Es wurden keine unterstützten Audiodateien hochgeladen.")
    return refresh_album_metadata(album)


def remove_track_from_album(album, track_path):
    album_dir = BASE_DIR / album.get("folder", "")
    target = (album_dir / safe_relative_path(track_path)).resolve()
    if not target.exists() or album_dir.resolve() not in target.parents:
        raise ValueError("Titel konnte nicht gefunden werden.")
    target.unlink(missing_ok=True)
    current = target.parent
    album_root = album_dir.resolve()
    while current != album_root and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
    return refresh_album_metadata(album)


def enrich_library_data(library_data):
    for album in library_data.get("albums", []):
        refresh_album_metadata(album)
    return library_data


def default_player():
    return {
        "current_album": "Lieblingsgeschichten",
        "current_track": "Lieblingsgeschichten",
        "cover_url": "",
        "volume": 45,
        "muted": False,
        "volume_before_mute": 45,
        "position_seconds": 0,
        "duration_seconds": 278,
        "sleep_timer_minutes": 0,
        "is_playing": True,
        "playlist": "media/albums/lieblingsgeschichten/playlist.m3u",
        "playlist_entries": [],
        "current_track_index": 0,
        "queue": [],
    }


def default_library():
    return {
        "albums": [
            {
                "id": "album-1",
                "name": "Lieblingsgeschichten",
                "folder": "media/albums/lieblingsgeschichten",
                "playlist": "media/albums/lieblingsgeschichten/playlist.m3u",
                "track_count": 0,
                "rfid_uid": "1234567890",
                "cover_url": "",
            },
            {
                "id": "album-2",
                "name": "Schlaflieder",
                "folder": "media/albums/schlaflieder",
                "playlist": "media/albums/schlaflieder/playlist.m3u",
                "track_count": 0,
                "rfid_uid": "",
                "cover_url": "",
            },
            {
                "id": "album-3",
                "name": "Tierstimmen",
                "folder": "media/albums/tierstimmen",
                "playlist": "media/albums/tierstimmen/playlist.m3u",
                "track_count": 0,
                "rfid_uid": "",
                "cover_url": "",
            },
        ]
    }


def default_settings():
    return {
        "max_volume": 85,
        "volume_step": 5,
        "sleep_timer_step": 5,
        "use_startup_volume": False,
        "startup_volume": 45,
        "rfid_read_action": "play",
        "rfid_remove_action": "stop",
    }


def default_setup():
    return {
        "reader": {
            "type": "USB",
            "connection_hint": "USB-Reader anstecken oder RC522 per SPI verdrahten",
        },
        "button_long_press_seconds": 2,
        "buttons": [
            {"id": "btn-1", "name": "Play/Pause", "pin": "GPIO17", "press_type": "kurz"},
            {"id": "btn-2", "name": "Stopp", "pin": "", "press_type": "kurz"},
            {"id": "btn-3", "name": "Vor", "pin": "GPIO27", "press_type": "kurz"},
            {"id": "btn-4", "name": "Zurück", "pin": "GPIO22", "press_type": "kurz"},
            {"id": "btn-5", "name": "Lautstärke +", "pin": "GPIO23", "press_type": "kurz"},
            {"id": "btn-6", "name": "Lautstärke -", "pin": "GPIO24", "press_type": "kurz"},
            {"id": "btn-7", "name": "Sleep Timer +", "pin": "", "press_type": "kurz"},
            {"id": "btn-8", "name": "Sleep Timer -", "pin": "", "press_type": "kurz"},
            {"id": "btn-9", "name": "Wifi on/off", "pin": "", "press_type": "kurz"},
            {"id": "btn-10", "name": "Power on/off", "pin": "GPIO25", "press_type": "lang"},
        ],
        "leds": [
            {"id": "led-1", "name": "Power", "pin": "GPIO12", "function": "power_on", "brightness": 50},
            {"id": "led-2", "name": "Stand-by", "pin": "GPIO13", "function": "standby", "brightness": 30},
            {"id": "led-3", "name": "Sleep 1/3", "pin": "GPIO18", "function": "sleep_1", "brightness": 50},
            {"id": "led-4", "name": "Sleep 2/3", "pin": "GPIO19", "function": "sleep_2", "brightness": 70},
            {"id": "led-5", "name": "Sleep 3/3", "pin": "GPIO20", "function": "sleep_3", "brightness": 90},
            {"id": "led-6", "name": "Wifi", "pin": "GPIO21", "function": "wifi_on", "brightness": 55},
        ],
        "power_routines": {
            "power_on": "sleep_count_up_5",
            "power_off": "sleep_count_down_5",
        },
        "audio": {
            "output_mode": "usb_dac",
            "i2s_profile": "auto",
            "connection_hint": "USB- oder I2S-Soundkarte anschließen und auswählen",
        },
        "wifi": {
            "mode": "client_with_fallback_hotspot",
            "allow_button_toggle": False,
            "country": "DE",
            "fallback_hotspot": True,
            "hotspot_security": "open",
            "hotspot_ssid": "Phonie-hotspot",
            "hotspot_password": "",
            "hotspot_channel": 6,
            "hostname": "phoniebox",
            "browser_name": "phoniebox.local",
            "saved_networks": [
                {"id": "wifi-1", "ssid": "Wohnzimmer", "password": "", "priority": 10},
            ],
        },
    }


def factory_wifi_defaults():
    return {
        "mode": "hotspot_only",
        "country": "DE",
        "fallback_hotspot": True,
        "hotspot_security": "open",
        "hotspot_ssid": "Phonie-hotspot",
        "hotspot_password": "",
        "hotspot_channel": 6,
        "hostname": "phoniebox",
        "browser_name": "phoniebox.local",
        "saved_networks": [],
    }


def default_apply_report():
    return {"ok": True, "summary": "Noch nicht angewendet.", "details": []}


def default_button_detect():
    return {
        "active": False,
        "started_at": 0.0,
        "deadline_at": 0.0,
        "status": "idle",
        "message": "",
        "detected_gpio": "",
        "detected_pin": "",
        "baseline": {},
        "candidate_pins": [],
    }


def default_link_session():
    return {
        "active": False,
        "album_id": "",
        "album_name": "",
        "status": "idle",
        "message": "",
        "last_uid": "",
    }


def ensure_data_files():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ALBUMS_DIR.mkdir(parents=True, exist_ok=True)
    defaults = {
        PLAYER_FILE: default_player(),
        LIBRARY_FILE: default_library(),
        SETTINGS_FILE: default_settings(),
        SETUP_FILE: default_setup(),
        APPLY_REPORT_FILE: default_apply_report(),
        RUNTIME_FILE: runtime_service.ensure_runtime(),
        LINK_SESSION_FILE: default_link_session(),
        BUTTON_DETECT_FILE: default_button_detect(),
    }
    for path, default in defaults.items():
        if not path.exists():
            save_json(path, default)


def load_player():
    return merge_defaults(load_json(PLAYER_FILE, default_player()), default_player())


def save_player(data):
    save_json(PLAYER_FILE, data)


def load_library():
    return load_json(LIBRARY_FILE, default_library())


def save_library(data):
    save_json(LIBRARY_FILE, data)


def load_settings():
    return merge_defaults(load_json(SETTINGS_FILE, default_settings()), default_settings())


def save_settings(data):
    save_json(SETTINGS_FILE, data)


def load_setup():
    return merge_defaults(load_json(SETUP_FILE, default_setup()), default_setup())


def save_setup(data):
    save_json(SETUP_FILE, data)


def build_audio_runtime_config(audio_setup, settings):
    config = dict(audio_setup or {})
    config["playback_backend"] = "mpg123"
    config["mixer_control"] = "auto"
    config["preferred_output"] = "auto"
    config["mono_downmix"] = False
    config["external_soundcard_required"] = False
    config["apply_boot_config"] = config.get("output_mode") == "i2s_dac"
    config["use_startup_volume"] = bool(settings.get("use_startup_volume", False))
    config["enable_audio_service"] = config["use_startup_volume"]
    config["startup_volume"] = to_int(settings.get("startup_volume"), 45, 0, 100)
    return config


def load_apply_report():
    return load_json(APPLY_REPORT_FILE, default_apply_report())


def save_apply_report(data):
    save_json(APPLY_REPORT_FILE, data)


def load_link_session():
    return load_json(LINK_SESSION_FILE, default_link_session())


def save_link_session(data):
    save_json(LINK_SESSION_FILE, data)


def load_button_detect():
    return merge_defaults(load_json(BUTTON_DETECT_FILE, default_button_detect()), default_button_detect())


def save_button_detect(data):
    save_json(BUTTON_DETECT_FILE, data)


def sample_gpio_levels(gpio_names):
    gpio_names = [name for name in gpio_names if name]
    helper_script = BASE_DIR / "scripts" / "gpio_sample.py"
    if helper_script.exists():
        result = subprocess.run(
            ["/usr/bin/python3", str(helper_script), *gpio_names],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout.strip() or "{}")
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict) and payload:
                return {str(name): int(value) for name, value in payload.items()}
    if shutil.which("gpioget") is not None:
        result = subprocess.run(
            ["gpioget", "--numeric", "--by-name", *gpio_names],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            values = result.stdout.strip().split()
            if len(values) == len(gpio_names):
                return {name: int(value == "1") for name, value in zip(gpio_names, values)}
    sysfs_sample = sample_gpio_levels_sysfs(gpio_names)
    if sysfs_sample:
        return sysfs_sample
    if gpiod is None:
        return {}
    chip_paths = sorted(Path("/dev").glob("gpiochip*"))
    if not chip_paths:
        return {}

    sampled = {}
    settings = gpiod.LineSettings(direction=gpiod.line.Direction.INPUT, bias=gpiod.line.Bias.AS_IS)
    for chip_path in chip_paths:
        if len(sampled) == len(gpio_names):
            break
        try:
            chip = gpiod.Chip(str(chip_path))
        except OSError:
            continue
        try:
            pending = []
            for gpio_name in gpio_names:
                if gpio_name in sampled:
                    continue
                try:
                    offset = chip.line_offset_from_id(gpio_name)
                except OSError:
                    continue
                pending.append((gpio_name, offset))
            if not pending:
                chip.close()
                continue
            request = chip.request_lines({(offset,): settings for _, offset in pending}, consumer="phoniebox-button-detect")
            try:
                for gpio_name, offset in pending:
                    sampled[gpio_name] = int(request.get_value(offset) == gpiod.line.Value.ACTIVE)
            finally:
                request.release()
                chip.close()
        except OSError:
            chip.close()
            continue
    return sampled


def button_detection_candidates(setup_data):
    return pin_choices(setup_data, "button")


def button_detect_status_payload(setup_data=None):
    session = load_button_detect()
    if not session.get("active"):
        return session

    now = time.time()
    if now >= float(session.get("deadline_at", 0)):
        session["active"] = False
        session["status"] = "timeout"
        session["message"] = "Keine Taste erkannt."
        save_button_detect(session)
        return session

    setup_data = setup_data or load_setup()
    candidates = session.get("candidate_pins") or button_detection_candidates(setup_data)
    current_levels = sample_gpio_levels(candidates)
    baseline = session.get("baseline", {})
    for gpio_name in candidates:
        if gpio_name not in current_levels or gpio_name not in baseline:
            continue
        if int(current_levels[gpio_name]) != int(baseline[gpio_name]):
            session["active"] = False
            session["status"] = "detected"
            session["detected_gpio"] = gpio_name
            session["detected_pin"] = str(GPIO_TO_BOARD_PIN.get(gpio_name, ""))
            session["message"] = gpio_display_label(gpio_name)
            save_button_detect(session)
            return session

    session["remaining_seconds"] = max(0, int(session["deadline_at"] - now + 0.999))
    return session

def start_link_session(album):
    session = {
        "active": True,
        "album_id": album.get("id", ""),
        "album_name": album.get("name", ""),
        "status": "waiting_for_uid",
        "message": "Tag-scannen oder ID eingeben",
        "last_uid": "",
    }
    save_link_session(session)
    return session


def finish_link_session(session, status, message, uid=""):
    session["active"] = False
    session["status"] = status
    session["message"] = message
    session["last_uid"] = uid
    save_link_session(session)
    return session


def apply_link_uid(album_id, uid):
    uid = uid.strip()
    session = load_link_session()
    library_data = load_library()
    albums = library_data.get("albums", [])
    target = next((album for album in albums if album["id"] == album_id), None)
    if not target:
        updated = finish_link_session(session, "error", "Album nicht mehr vorhanden.", uid)
        return {"ok": False, "message": updated["message"], "link_session": updated}, 404
    conflict = album_conflict(albums, target["id"], uid)
    if conflict:
        updated = finish_link_session(session, "conflict", "Tag bereits anderweitig verlinkt", uid)
        return {"ok": False, "message": updated["message"], "link_session": updated}, 409
    target["rfid_uid"] = uid
    save_library(library_data)
    updated = finish_link_session(session, "linked", f"Tag mit {target['name']} verknüpft", uid)
    return {"ok": True, "linked_album": target, "link_session": updated}, 200


def to_int(value, fallback, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def to_float(value, fallback, minimum=None, maximum=None):
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        number = float(fallback)
    if minimum is not None:
        number = max(float(minimum), number)
    if maximum is not None:
        number = min(float(maximum), number)
    return number


def normalize_hotspot_security(value):
    security = (value or "open").strip().lower()
    if security == "wpa2":
        return "wpa-psk"
    if security not in HOTSPOT_SECURITY_CHOICES:
        return "open"
    return security


def format_mmss(total_seconds):
    minutes = max(total_seconds, 0) // 60
    seconds = max(total_seconds, 0) % 60
    return f"{minutes:02d}:{seconds:02d}"


def progress_percent(position, duration):
    if duration <= 0:
        return 0
    return round((position / duration) * 100, 1)


def album_conflict(albums, album_id, rfid_uid):
    if not rfid_uid:
        return None
    for album in albums:
        if album["id"] != album_id and album.get("rfid_uid", "").strip() == rfid_uid:
            return album
    return None


def nmcli_available():
    return shutil.which("nmcli") is not None


def run_nmcli(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_wifi_snapshot():
    snapshot = {
        "nmcli_available": nmcli_available(),
        "wifi_enabled": "unbekannt",
        "connectivity": "unbekannt",
        "active_ssid": "nicht verbunden",
        "device": "-",
        "scanned_networks": [],
    }
    if not snapshot["nmcli_available"]:
        return snapshot

    general = run_nmcli(["nmcli", "-t", "-f", "WIFI,CONNECTIVITY", "general"])
    if general:
        parts = general.split(":")
        if len(parts) >= 2:
            snapshot["wifi_enabled"] = parts[0]
            snapshot["connectivity"] = parts[1]

    active = run_nmcli(["nmcli", "-t", "-f", "ACTIVE,SSID,DEVICE", "dev", "wifi"])
    if active:
        for line in active.splitlines():
            active_flag, ssid, device = (line.split(":", 2) + ["", ""])[:3]
            if active_flag == "yes":
                snapshot["active_ssid"] = ssid or "verbunden"
                snapshot["device"] = device or "-"
                break

    scanned = run_nmcli(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    if scanned:
        for line in scanned.splitlines():
            in_use, ssid, signal, security = (line.split(":", 3) + ["", "", "", ""])[:4]
            snapshot["scanned_networks"].append(
                {
                    "in_use": in_use == "*",
                    "ssid": ssid or "(versteckt)",
                    "signal": signal or "-",
                    "security": security or "offen",
                }
            )
    return snapshot


def reserved_reader_pins(reader_type):
    reader_type = (reader_type or "").strip().upper()
    if reader_type == "RC522":
        return {"GPIO8", "GPIO9", "GPIO10", "GPIO11", "GPIO25"}
    if reader_type == "PN532_I2C":
        return {"GPIO2", "GPIO3"}
    if reader_type == "PN532_SPI":
        return {"GPIO8", "GPIO9", "GPIO10", "GPIO11"}
    if reader_type == "PN532_UART":
        return {"GPIO14", "GPIO15"}
    return set()


def reserved_audio_pins(output_mode):
    if (output_mode or "").strip() == "i2s_dac":
        return {"GPIO18", "GPIO19", "GPIO20", "GPIO21"}
    return set()


def reserved_system_pins(setup_data):
    reader_type = setup_data.get("reader", {}).get("type", "")
    output_mode = setup_data.get("audio", {}).get("output_mode", "")
    return reserved_reader_pins(reader_type) | reserved_audio_pins(output_mode)


def pin_choices(setup_data, role):
    reserved = reserved_system_pins(setup_data)
    pins = GPIO_PINS
    if role == "led":
        pins = [pin for pin in GPIO_PINS if pin in PWM_PINS or pin not in reserved]
    else:
        pins = [pin for pin in GPIO_PINS if pin not in reserved]
    return pins


def reader_catalog():
    options = []
    for option in READER_OPTIONS:
        enriched = dict(option)
        enriched["guide_available"] = reader_guide_path(option["id"]).exists()
        options.append(enriched)
    return options


def power_routine_catalog():
    return [dict(option) for option in POWER_ROUTINE_OPTIONS]


def power_routine_options(kind):
    return [option for option in power_routine_catalog() if option["type"] == kind]


def normalize_power_routine_id(kind, routine_id):
    options = power_routine_options(kind)
    valid_ids = {option["id"] for option in options}
    if routine_id in valid_ids:
        return routine_id
    return options[0]["id"] if options else ""


def collect_conflicts(setup_data):
    warnings = []
    buttons = setup_data.get("buttons", [])
    leds = setup_data.get("leds", [])

    button_pins = {}
    for button in buttons:
        pin = button.get("pin", "").strip()
        press_type = button.get("press_type", "kurz").strip() or "kurz"
        function_name = button.get("name", "Taste").strip() or "Taste"
        if pin:
            button_pins.setdefault(pin, {}).setdefault(press_type, []).append(function_name)
    for pin, by_press_type in button_pins.items():
        total_assignments = sum(len(names) for names in by_press_type.values())
        if total_assignments > 2:
            warnings.append(f"Tasten an {pin} müssen neu zugeordnet werden. Ein Pin darf nur für kurz und lang verwendet werden.")
        for press_type, names in by_press_type.items():
            if len(names) > 1:
                warnings.append(f"Tasten an {pin} müssen neu zugeordnet werden. {press_type} ist mehrfach belegt: {', '.join(names)}")

    led_pins = {}
    for led in leds:
        pin = led.get("pin", "").strip()
        if pin:
            led_pins.setdefault(pin, []).append(led.get("name", "LED"))
    for pin, names in led_pins.items():
        if len(names) > 1:
            warnings.append(f"LED-PIN {pin} ist mehrfach belegt: {', '.join(names)}")

    overlap = set(button_pins) & set(led_pins)
    for pin in sorted(overlap):
        warnings.append(f"PIN {pin} ist gleichzeitig für Taste und LED vergeben und muss neu zugeordnet werden.")

    reserved = reserved_system_pins(setup_data)
    for pin, by_press_type in button_pins.items():
        if pin in reserved:
            button_names = [name for names in by_press_type.values() for name in names]
            warnings.append(f"Taste {', '.join(button_names)} muss neu zugeordnet werden. {pin} wird jetzt von Reader oder Soundkarte benötigt.")
    for pin, names in led_pins.items():
        if pin in reserved:
            warnings.append(f"LED {', '.join(names)} muss neu zugeordnet werden. {pin} wird jetzt von Reader oder Soundkarte benötigt.")

    wifi = setup_data.get("wifi", {})
    if normalize_hotspot_security(wifi.get("hotspot_security")) == "wpa-psk" and len(wifi.get("hotspot_password", "")) < 8:
        warnings.append("Hotspot mit WPA2 braucht mindestens 8 Zeichen Passwort.")

    return warnings


def mapping_errors(setup_data):
    errors = []
    buttons = setup_data.get("buttons", [])
    pin_usage = {}
    for button in buttons:
        pin = button.get("pin", "").strip()
        press_type = button.get("press_type", "kurz").strip() or "kurz"
        function_name = button.get("name", "").strip()
        if not pin or not function_name:
            continue
        used_presses = pin_usage.setdefault(pin, set())
        if press_type in used_presses:
            errors.append(f"GPIO {pin} ist für {press_type} mehrfach belegt.")
        used_presses.add(press_type)
        if len(used_presses) > 2:
            errors.append(f"GPIO {pin} ist zu oft belegt.")
    return errors


def current_reader_option(reader_type):
    return next((option for option in READER_OPTIONS if option["id"] == reader_type), READER_OPTIONS[0])


def reader_guide_filename(reader_type):
    return {
        "USB": "usb-keyboard-reader.txt",
        "RC522": "rc522-spi.txt",
        "PN532_I2C": "pn532-i2c.txt",
        "PN532_SPI": "pn532-spi.txt",
        "PN532_UART": "pn532-uart.txt",
    }.get(reader_type, "usb-keyboard-reader.txt")


def reader_guide_path(reader_type):
    return READER_GUIDE_DIR / reader_guide_filename(reader_type)


def audio_guide_filename(output_mode):
    return {
        "i2s_dac": "i2s-dac.txt",
    }.get(output_mode, "")


def audio_guide_path(output_mode):
    filename = audio_guide_filename(output_mode)
    return AUDIO_GUIDE_DIR / filename if filename else Path("")


def audio_output_choices(environment=None):
    environment = environment or detect_audio_environment()
    choices = [
        {"id": "usb_dac", "label": "USB-Soundkarte"},
        {"id": "i2s_dac", "label": "I2S-Soundkarte"},
    ]
    if environment.get("has_analog_audio"):
        choices.insert(1, {"id": "analog_jack", "label": "Interne Soundkarte"})
    return choices


def audio_i2s_profile_choices():
    return i2s_profile_catalog()


def network_targets(setup_data):
    wifi = setup_data.get("wifi", {})
    hostname = (wifi.get("hostname") or "phoniebox").strip()
    browser_name = (wifi.get("browser_name") or f"{hostname}.local").strip()
    return {
        "hostname": hostname,
        "browser_name": browser_name,
        "recommended_name": f"{hostname}.local",
        "custom_box_name": "phonie.box",
        "supports_custom_box": False,
    }


def summarize_apply(ok):
    if ok:
        return "Systemprofil erfolgreich angewendet."
    return "Systemprofil konnte nicht vollständig angewendet werden."


def apply_network_setup(wifi_config):
    hostname_result = ensure_hostname(wifi_config.get("hostname", "phoniebox"))
    network_result = apply_wifi_profile(wifi_config)
    details = hostname_result.get("details", []) + network_result.get("details", [])
    ok = hostname_result.get("ok", False) and network_result.get("ok", False)
    report = {
        "ok": ok,
        "summary": summarize_apply(ok),
        "details": details or ["Keine Detailausgabe vorhanden."],
    }
    save_apply_report(report)
    return report


def build_player_context(snapshot):
    player_state = dict(snapshot["player"])
    runtime_state = snapshot["runtime"]
    settings = snapshot["settings"]
    sleep_step_minutes = max(1, int(settings.get("sleep_timer_step", 5)))
    player_state["sleep_timer_minutes"] = int(runtime_state.get("sleep_timer", {}).get("remaining_seconds", 0)) // 60
    return {
        "player_state": player_state,
        "runtime_state": runtime_state,
        "settings": settings,
        "volume_percent": player_state["volume"],
        "volume_muted": bool(player_state.get("muted", False)),
        "volume_step": int(settings.get("volume_step", 5)),
        "sleep_step_minutes": sleep_step_minutes,
        "sleep_level": int(runtime_state.get("sleep_timer", {}).get("level", 0)),
        "position_label": format_mmss(player_state["position_seconds"]),
        "duration_label": format_mmss(player_state["duration_seconds"]),
        "progress_percent": progress_percent(player_state["position_seconds"], player_state["duration_seconds"]),
    }


@app.context_processor
def inject_shell():
    return {"nav_items": nav_items(), "active_path": request.path}


def nav_items():
    return [
        {"endpoint": "player", "label": "Player"},
        {"endpoint": "library", "label": "Bibliothek"},
        {"endpoint": "settings", "label": "Einstellungen"},
        {"endpoint": "setup", "label": "Setup"},
    ]


@app.context_processor
def inject_asset_version():
    style_path = BASE_DIR / "static" / "style.css"
    player_path = BASE_DIR / "static" / "player.js"
    library_path = BASE_DIR / "static" / "library-link.js"
    settings_path = BASE_DIR / "static" / "settings.js"
    setup_path = BASE_DIR / "static" / "setup-dnd.js"
    asset_version = max(
        int(style_path.stat().st_mtime),
        int(player_path.stat().st_mtime),
        int(library_path.stat().st_mtime),
        int(settings_path.stat().st_mtime) if settings_path.exists() else 0,
        int(setup_path.stat().st_mtime),
    )
    return {"asset_version": asset_version}


ensure_data_files()


@app.context_processor
def inject_choices():
    setup_data = load_setup()
    audio_environment = detect_audio_environment()
    return {
        "reader_options": reader_catalog(),
        "button_functions": BUTTON_FUNCTIONS,
        "led_functions": LED_FUNCTIONS,
        "button_pin_choices": pin_choices(setup_data, "button"),
        "led_pin_choices": pin_choices(setup_data, "led"),
        "power_on_routine_options": power_routine_options("power_on"),
        "power_off_routine_options": power_routine_options("power_off"),
        "power_routine_options": power_routine_catalog(),
        "audio_output_options": audio_output_choices(audio_environment),
        "audio_i2s_profile_options": audio_i2s_profile_choices(),
        "audio_environment": audio_environment,
    }


@app.route("/")
def index():
    return redirect(url_for("player"))


@app.route("/player", methods=["GET", "POST"])
def player():
    snapshot = runtime_service.status()
    player_state = snapshot["player"]
    runtime_state = snapshot["runtime"]
    settings = snapshot["settings"]

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        if action == "toggle_play":
            runtime_service.toggle_playback()
        elif action == "stop":
            runtime_service.stop()
        elif action == "prev":
            runtime_service.previous_track()
        elif action == "next":
            runtime_service.next_track()
        elif action == "volume_down":
            runtime_service.set_volume(-settings["volume_step"])
        elif action == "volume_up":
            runtime_service.set_volume(settings["volume_step"])
        elif action == "mute":
            runtime_service.toggle_mute()
        elif action == "sleep_down":
            level = max(0, int(runtime_state.get("sleep_timer", {}).get("level", 0)) - 1)
            runtime_service.set_sleep_level(level)
        elif action == "sleep_up":
            level = min(3, int(runtime_state.get("sleep_timer", {}).get("level", 0)) + 1)
            runtime_service.set_sleep_level(level)
        elif action == "seek":
            runtime_service.seek(to_int(request.form.get("seek_position"), player_state.get("position_seconds", 0), 0))
        elif action == "clear_queue":
            runtime_service.clear_queue()
        flash("Playerstatus aktualisiert.", "success")
        return redirect(url_for("player"))

    context = build_player_context(snapshot)
    return render_template("player.html", **context)


@app.route("/setup/reader-guide/<reader_type>")
def download_reader_guide(reader_type):
    guide_path = reader_guide_path(reader_type)
    if not guide_path.exists():
        flash("Für diesen Reader ist noch kein Anschlussplan hinterlegt.", "error")
        return redirect(url_for("setup"))
    return send_file(guide_path, as_attachment=True, download_name=guide_path.name)


@app.route("/setup/audio-guide/<output_mode>")
def download_audio_guide(output_mode):
    guide_path = audio_guide_path(output_mode)
    if not guide_path or not guide_path.exists():
        flash("Für diese Soundkarte ist noch kein Anschlussplan hinterlegt.", "error")
        return redirect(url_for("setup"))
    return send_file(guide_path, as_attachment=True, download_name=guide_path.name)


@app.route("/setup/logs")
def download_setup_logs():
    snapshot = runtime_service.status()
    payload = {
        "setup": load_setup(),
        "settings": load_settings(),
        "apply_report": load_apply_report(),
        "runtime": snapshot.get("runtime", {}),
        "player": snapshot.get("player", {}),
        "hardware": snapshot.get("hardware", {}),
    }
    content = io.BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))
    return send_file(content, as_attachment=True, download_name="phoniebox-setup-logs.txt", mimetype="text/plain")


@app.route("/library", methods=["GET", "POST"])
def library():
    library_data = load_library()
    if request.method == "POST":
        action = request.form.get("action", "").strip()
        albums = library_data["albums"]
        if action == "import_album":
            files = [item for item in request.files.getlist("album_files") if getattr(item, "filename", "")]
            album_name = request.form.get("name", "").strip()
            rfid_uid = request.form.get("rfid_uid", "").strip()
            if not album_name:
                flash("Albumname ist erforderlich.", "error")
                return redirect(url_for("library"))
            try:
                album_entry = import_album_folder(files, album_name, rfid_uid) if files else create_empty_album(album_name, rfid_uid)
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("library"))
            flash(
                f"Album {album_entry['name']} importiert und Playlist erzeugt." if files else f"Leeres Album {album_entry['name']} angelegt.",
                "success",
            )
            return redirect(url_for("library"))

        if action == "save_album":
            album_id = request.form.get("album_id", "").strip() or f"album-{secrets.token_hex(4)}"
            name = request.form.get("name", "").strip() or "Neues Album"
            folder = request.form.get("folder", "").strip()
            rfid_uid = request.form.get("rfid_uid", "").strip()
            cover_url = request.form.get("cover_url", "").strip()
            name_conflict = next(
                (
                    album for album in albums
                    if album.get("id") != album_id and album.get("name", "").strip().lower() == name.lower()
                ),
                None,
            )
            if name_conflict:
                flash(f"Albumname bereits vorhanden: {name_conflict['name']}.", "error")
                return redirect(url_for("library"))
            conflict = album_conflict(albums, album_id, rfid_uid)
            if conflict:
                flash(f"RFID-Tag bereits mit {conflict['name']} verknüpft.", "error")
                return redirect(url_for("library"))

            existing = next((album for album in albums if album["id"] == album_id), None)
            payload = {
                "id": album_id,
                "name": name,
                "folder": folder,
                "playlist": request.form.get("playlist", "").strip(),
                "track_count": to_int(request.form.get("track_count"), 0, 0, 5000),
                "rfid_uid": rfid_uid,
                "cover_url": cover_url,
            }
            if existing:
                existing.update(payload)
                flash(f"Album {name} aktualisiert.", "success")
            else:
                albums.append(payload)
                flash(f"Album {name} angelegt.", "success")
            save_library(library_data)
            return redirect(url_for("library"))

        if action == "delete_album":
            album_id = request.form.get("album_id", "").strip()
            target_album = next((album for album in albums if album["id"] == album_id), None)
            if target_album:
                album_path = BASE_DIR / target_album.get("folder", "")
                if album_path.exists() and ALBUMS_DIR in album_path.parents:
                    shutil.rmtree(album_path, ignore_errors=True)
            library_data["albums"] = [album for album in albums if album["id"] != album_id]
            save_library(library_data)
            flash("Album entfernt.", "success")
            return redirect(url_for("library"))

        if action == "unlink_rfid":
            album_id = request.form.get("album_id", "").strip()
            for album in albums:
                if album["id"] == album_id:
                    album["rfid_uid"] = ""
                    break
            save_library(library_data)
            flash("RFID-Zuordnung entfernt.", "success")
            return redirect(url_for("library"))

        if action == "play_album":
            album_id = request.form.get("album_id", "").strip()
            result = runtime_service.load_album_by_id(album_id, autoplay=True)
            flash(result["runtime"]["last_event"], "success" if result.get("ok") else "error")
            return redirect(url_for("library"))

        if action == "load_album":
            album_id = request.form.get("album_id", "").strip()
            result = runtime_service.load_album_by_id(album_id, autoplay=False)
            flash(result["runtime"]["last_event"], "success" if result.get("ok") else "error")
            return redirect(url_for("library"))

        if action == "queue_album":
            album_id = request.form.get("album_id", "").strip()
            result = runtime_service.queue_album_by_id(album_id)
            flash(result["runtime"]["last_event"], "success" if result.get("ok") else "error")
            return redirect(url_for("library"))

        if action == "add_tracks":
            album_id = request.form.get("album_id", "").strip()
            album = next((entry for entry in albums if entry["id"] == album_id), None)
            if not album:
                flash("Album nicht gefunden.", "error")
                return redirect(url_for("library"))
            try:
                add_tracks_to_album(album, request.files.getlist("track_files"))
                save_library(library_data)
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("library"))
            flash("Titel ergänzt.", "success")
            return redirect(url_for("library"))

        if action == "remove_track":
            album_id = request.form.get("album_id", "").strip()
            track_path = request.form.get("track_path", "").strip()
            album = next((entry for entry in albums if entry["id"] == album_id), None)
            if not album:
                flash("Album nicht gefunden.", "error")
                return redirect(url_for("library"))
            try:
                remove_track_from_album(album, track_path)
                save_library(library_data)
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("library"))
            flash("Titel entfernt.", "success")
            return redirect(url_for("library"))

    enrich_library_data(library_data)
    return render_template("library.html", library_data=library_data, link_session=load_link_session())


@app.route("/settings", methods=["GET", "POST"])
def settings():
    data = load_settings()
    if request.method == "POST":
        data = apply_settings_form(data, request.form)
        save_settings(data)
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", settings=data)


def apply_settings_form(data, source):
    data["max_volume"] = to_int(source.get("max_volume"), data["max_volume"], 10, 100)
    data["volume_step"] = to_int(source.get("volume_step"), data["volume_step"], 1, 25)
    data["sleep_timer_step"] = to_int(source.get("sleep_timer_step"), data["sleep_timer_step"], 1, 60)
    data["use_startup_volume"] = source.get("use_startup_volume") == "on"
    data["startup_volume"] = to_int(source.get("startup_volume"), data.get("startup_volume", 45), 0, 100)
    data["rfid_read_action"] = source.get("rfid_read_action", data["rfid_read_action"])
    data["rfid_remove_action"] = source.get("rfid_remove_action", data["rfid_remove_action"])
    return data


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = load_settings()
    payload = request.get_json(silent=True) or {}
    data = apply_settings_form(data, payload)
    save_settings(data)
    return jsonify({"ok": True, "settings": data})


def collect_rows(prefix, columns):
    rows = []
    row_count = to_int(request.form.get(f"{prefix}_count"), 0, 0, 50)
    for index in range(row_count):
        row = {}
        is_empty = True
        for column in columns:
            value = request.form.get(f"{prefix}_{column}_{index}", "").strip()
            row[column] = value
            if value:
                is_empty = False
        if not is_empty:
            rows.append(row)
    return rows


def default_button_rows():
    return [
        {"id": "btn-1", "name": "Play/Pause", "pin": "GPIO17", "press_type": "kurz"},
        {"id": "btn-2", "name": "Stopp", "pin": "", "press_type": "kurz"},
        {"id": "btn-3", "name": "Vor", "pin": "GPIO27", "press_type": "kurz"},
        {"id": "btn-4", "name": "Zurück", "pin": "GPIO22", "press_type": "kurz"},
        {"id": "btn-5", "name": "Lautstärke +", "pin": "GPIO23", "press_type": "kurz"},
        {"id": "btn-6", "name": "Lautstärke -", "pin": "GPIO24", "press_type": "kurz"},
        {"id": "btn-7", "name": "Sleep Timer +", "pin": "", "press_type": "kurz"},
        {"id": "btn-8", "name": "Sleep Timer -", "pin": "", "press_type": "kurz"},
        {"id": "btn-9", "name": "Wifi on/off", "pin": "", "press_type": "kurz"},
        {"id": "btn-10", "name": "Power on/off", "pin": "GPIO25", "press_type": "lang"},
    ]


def available_press_types(rows, row_index):
    current = rows[row_index] if row_index < len(rows) else {}
    current_pin = current.get("pin", "").strip()
    if not current_pin:
        return ["kurz", "lang"]
    used = set()
    for index, button in enumerate(rows):
        if index == row_index:
            continue
        if button.get("pin", "").strip() == current_pin:
            used.add(button.get("press_type", "kurz").strip() or "kurz")
    return [option for option in ["kurz", "lang"] if option not in used] or ["kurz", "lang"]


def button_mapping_rows(setup_data):
    rows = []
    buttons = setup_data.get("buttons", []) or default_button_rows()
    assignments = {button.get("name", ""): button for button in buttons}
    valid_pins = pin_choices(setup_data, "button")
    base_rows = []
    for function_name in BUTTON_FUNCTIONS:
        button = assignments.get(function_name, {"name": function_name, "pin": "", "press_type": "kurz"})
        base_rows.append(button)
    for index, button in enumerate(base_rows):
        function_name = button.get("name", "")
        current_pin = button.get("pin", "")
        pin_options = list(valid_pins)
        current_pin_invalid = bool(current_pin and current_pin not in valid_pins)
        if current_pin_invalid:
            pin_options = [current_pin] + pin_options
        rows.append(
            {
                "index": index,
                "name": function_name,
                "pin": current_pin,
                "press_type": button.get("press_type", "kurz") or "kurz",
                "pin_options": pin_options,
                "press_type_options": available_press_types(base_rows, index),
                "pin_invalid": current_pin_invalid,
            }
        )
    return rows


@app.route("/setup", methods=["GET", "POST"])
def setup():
    data = load_setup()
    runtime_snapshot = runtime_service.status()
    if request.method == "POST":
        section = request.form.get("section", "").strip()

        if section == "reader":
            data["reader"]["type"] = request.form.get("reader_type", data["reader"]["type"]).strip() or "USB"
            save_setup(data)
            flash("Reader-Setup gespeichert.", "success")
            return redirect(url_for("setup"))

        if section == "buttons":
            new_buttons = []
            row_count = to_int(request.form.get("button_count"), 0, 0, 50)
            for index in range(row_count):
                pin = request.form.get(f"button_pin_{index}", "").strip()
                function_name = BUTTON_FUNCTIONS[index] if index < len(BUTTON_FUNCTIONS) else ""
                press_type = request.form.get(f"button_press_type_{index}", "kurz").strip() or "kurz"
                if pin and function_name:
                    new_buttons.append(
                        {
                            "id": f"btn-{len(new_buttons) + 1}",
                            "name": function_name,
                            "pin": pin,
                            "press_type": press_type,
                        }
                    )
            candidate = dict(data)
            candidate["buttons"] = new_buttons
            candidate["button_long_press_seconds"] = round(
                to_float(
                request.form.get("button_long_press_seconds"),
                data.get("button_long_press_seconds", 2),
                1,
                10,
                ),
                1,
            )
            errors = mapping_errors(candidate)
            if errors:
                for error in errors:
                    flash(error, "error")
                return redirect(url_for("setup"))
            data["buttons"] = new_buttons
            data["button_long_press_seconds"] = candidate["button_long_press_seconds"]
            save_setup(data)
            flash("Tastenbelegung gespeichert.", "success")
            return redirect(url_for("setup"))

        if section == "leds":
            rows = collect_rows("led", ["name", "pin", "function", "brightness"])
            data["leds"] = [
                {
                    "id": f"led-{index + 1}",
                    "name": row["name"],
                    "pin": row["pin"],
                    "function": row["function"],
                    "brightness": to_int(row["brightness"], 50, 0, 100),
                }
                for index, row in enumerate(rows)
            ]
            save_setup(data)
            flash("LED-Zuweisungen gespeichert.", "success")
            return redirect(url_for("setup"))

        if section == "power_routines":
            routines = data.setdefault("power_routines", {})
            routines["power_on"] = normalize_power_routine_id(
                "power_on",
                request.form.get("power_on_routine", routines.get("power_on", "")),
            )
            routines["power_off"] = normalize_power_routine_id(
                "power_off",
                request.form.get("power_off_routine", routines.get("power_off", "")),
            )
            save_setup(data)
            flash("Ein-/Ausschaltroutine gespeichert.", "success")
            return redirect(url_for("setup"))

        if section == "audio":
            audio = data["audio"]
            audio["output_mode"] = request.form.get("output_mode", audio.get("output_mode", "usb_dac")).strip() or "usb_dac"
            if audio["output_mode"] == "i2s_dac":
                audio["i2s_profile"] = request.form.get(
                    "i2s_profile",
                    audio.get("i2s_profile", "auto"),
                ).strip() or "auto"
            else:
                audio["i2s_profile"] = "auto"
            save_setup(data)
            audio_config = build_audio_runtime_config(audio, load_settings())
            apply_audio_profile(audio_config, AUDIO_PROFILE_DIR)
            result = deploy_audio_profile(audio_config, AUDIO_PROFILE_DIR)
            report = {
                "ok": result.get("ok", False),
                "summary": "Soundkarte gespeichert und angewendet." if result.get("ok") else "Soundkarte gespeichert, Systemprofil aber nur teilweise angewendet.",
                "details": result.get("details", []) or ["Keine Detailausgabe vorhanden."],
            }
            save_apply_report(report)
            flash(report["summary"], "success" if report["ok"] else "error")
            return redirect(url_for("setup"))

        if section == "simulate_gpio":
            pin = request.form.get("sim_pin", "").strip()
            press_type = request.form.get("sim_press_type", "kurz").strip()
            result = runtime_service.trigger_gpio_pin(pin, press_type)
            flash(result["runtime"]["last_event"], "success")
            return redirect(url_for("setup"))

        if section == "simulate_rfid":
            uid = request.form.get("sim_rfid_uid", "").strip()
            result = runtime_service.assign_album_by_rfid(uid)
            flash(result["runtime"]["last_event"], "success" if result.get("ok") else "error")
            return redirect(url_for("setup"))

        if section == "simulate_tag_remove":
            result = runtime_service.remove_rfid_tag()
            flash(result["runtime"]["last_event"], "success")
            return redirect(url_for("setup"))

        if section == "simulate_tick":
            elapsed = to_int(request.form.get("elapsed"), 5, 1, 120)
            result = runtime_service.tick(elapsed)
            flash(f"Runtime um {elapsed}s fortgeschrieben: {result['runtime']['last_event']}", "success")
            return redirect(url_for("setup"))

        if section == "reset_runtime":
            result = runtime_service.reset_state()
            flash(result["runtime"]["last_event"], "success")
            return redirect(url_for("setup"))

        if section == "wifi":
            wifi = data["wifi"]
            wifi["mode"] = request.form.get("mode", wifi["mode"]).strip()
            wifi["allow_button_toggle"] = request.form.get("allow_button_toggle") == "on"
            wifi["country"] = request.form.get("country", wifi["country"]).strip() or "DE"
            wifi["fallback_hotspot"] = request.form.get("fallback_hotspot") == "on"
            wifi["hotspot_security"] = normalize_hotspot_security(
                request.form.get("hotspot_security", wifi.get("hotspot_security", "open"))
            )
            wifi["hotspot_ssid"] = request.form.get("hotspot_ssid", wifi["hotspot_ssid"]).strip()
            wifi["hotspot_password"] = request.form.get("hotspot_password", wifi["hotspot_password"]).strip()
            wifi["hotspot_channel"] = to_int(request.form.get("hotspot_channel"), wifi["hotspot_channel"], 1, 13)
            wifi["hostname"] = request.form.get("hostname", wifi.get("hostname", "phoniebox")).strip() or "phoniebox"
            wifi["browser_name"] = request.form.get(
                "browser_name", wifi.get("browser_name", f"{wifi['hostname']}.local")
            ).strip() or f"{wifi['hostname']}.local"
            save_setup(data)
            report = apply_network_setup(wifi)
            flash(
                "Hotspot gespeichert und angewendet." if report["ok"] else "Hotspot gespeichert, Systemprofil aber nur teilweise angewendet.",
                "success" if report["ok"] else "error",
            )
            return redirect(url_for("setup"))

        if section == "factory_wifi":
            data["wifi"] = factory_wifi_defaults()
            save_setup(data)
            save_apply_report(
                {
                    "ok": True,
                    "summary": "Factory-Hotspot-Profil geladen.",
                    "details": [
                        "Modus auf hotspot_only gesetzt",
                        "Offener Hotspot Phonie-hotspot vorbereitet",
                        "Hostname auf phoniebox.local gesetzt",
                    ],
                }
            )
            flash("Factory-Hotspot-Profil geladen.", "success")
            return redirect(url_for("setup"))

        if section == "apply_network":
            report = apply_network_setup(data["wifi"])
            flash(report["summary"], "success" if report["ok"] else "error")
            return redirect(url_for("setup"))

        if section == "run_fallback_cycle":
            result = fallback_hotspot_cycle(data["wifi"])
            save_apply_report(
                {
                    "ok": result.get("ok", False),
                    "summary": result.get("summary", "Fallback-Zyklus ausgeführt."),
                    "details": result.get("details", []),
                }
            )
            flash(result.get("summary", "Fallback-Zyklus ausgeführt."), "success" if result.get("ok") else "error")
            return redirect(url_for("setup"))

        if section == "add_wifi_network":
            wifi = data["wifi"]
            ssid = request.form.get("ssid", "").strip()
            password = request.form.get("password", "").strip()
            priority = to_int(request.form.get("priority"), 10, 1, 100)
            if not ssid:
                flash("SSID darf nicht leer sein.", "error")
                return redirect(url_for("setup"))
            existing = next((entry for entry in wifi["saved_networks"] if entry["ssid"] == ssid), None)
            if existing:
                existing["password"] = password
                existing["priority"] = priority
                flash(f"Netzwerk {ssid} aktualisiert.", "success")
            else:
                wifi["saved_networks"].append(
                    {
                        "id": f"wifi-{secrets.token_hex(4)}",
                        "ssid": ssid,
                        "password": password,
                        "priority": priority,
                    }
                )
            save_setup(data)
            report = apply_network_setup(wifi)
            flash(
                f"Netzwerk {ssid} gespeichert und angewendet." if report["ok"] else f"Netzwerk {ssid} gespeichert, Systemprofil aber nur teilweise angewendet.",
                "success" if report["ok"] else "error",
            )
            return redirect(url_for("setup"))

        if section == "delete_wifi_network":
            network_id = request.form.get("network_id", "").strip()
            wifi = data["wifi"]
            wifi["saved_networks"] = [
                network for network in wifi["saved_networks"] if network["id"] != network_id
            ]
            save_setup(data)
            report = apply_network_setup(wifi)
            flash(
                "Gespeichertes WLAN entfernt und Systemprofil aktualisiert." if report["ok"] else "WLAN entfernt, Systemprofil aber nur teilweise aktualisiert.",
                "success" if report["ok"] else "error",
            )
            return redirect(url_for("setup"))

    wifi_snapshot = get_wifi_snapshot()
    return render_template(
        "setup.html",
        setup_data=data,
        wifi_snapshot=wifi_snapshot,
        setup_warnings=collect_conflicts(data),
        network_info=network_targets(data),
        apply_report=load_apply_report(),
        audio_environment=detect_audio_environment(),
        audio_profile_dir=AUDIO_PROFILE_DIR,
        hardware_profile=runtime_snapshot["runtime"]["hardware"].get("profile", {}),
        runtime_state=runtime_snapshot["runtime"],
        button_mapping_rows=button_mapping_rows(data),
        reader_option=current_reader_option(data.get("reader", {}).get("type", "USB")),
    )


@app.route("/api/runtime")
def api_runtime():
    return jsonify(runtime_service.status())


@app.route("/api/hardware")
def api_hardware():
    snapshot = runtime_service.status()
    return jsonify(snapshot["runtime"]["hardware"].get("profile", {}))


@app.route("/api/audio")
def api_audio():
    return jsonify(detect_audio_environment())


@app.route("/api/setup/button-detect/start", methods=["POST"])
def api_setup_button_detect_start():
    setup_data = load_setup()
    candidates = button_detection_candidates(setup_data)
    baseline = sample_gpio_levels(candidates)
    if not baseline:
        session = default_button_detect()
        session["status"] = "unavailable"
        session["message"] = "Keine GPIO-Tasterkennung verfügbar."
        save_button_detect(session)
        return jsonify({"ok": False, **session}), 503

    now = time.time()
    session = {
        "active": True,
        "started_at": now,
        "deadline_at": now + 15,
        "status": "listening",
        "message": "Warte auf Tastendruck.",
        "detected_gpio": "",
        "detected_pin": "",
        "baseline": baseline,
        "candidate_pins": candidates,
        "remaining_seconds": 15,
    }
    save_button_detect(session)
    return jsonify({"ok": True, **session})


@app.route("/api/setup/button-detect/status")
def api_setup_button_detect_status():
    session = button_detect_status_payload(load_setup())
    return jsonify({"ok": True, **session})


@app.route("/api/runtime/tick", methods=["POST"])
def api_runtime_tick():
    payload = request.get_json(silent=True) or {}
    elapsed = to_int(payload.get("elapsed", request.form.get("elapsed", 1)), 1, 1, 60)
    return jsonify(runtime_service.tick(elapsed))


@app.route("/api/runtime/rfid", methods=["POST"])
def api_runtime_rfid():
    payload = request.get_json(silent=True) or {}
    uid = str(payload.get("uid", request.form.get("uid", ""))).strip()
    session = load_link_session()
    if session.get("active") and uid:
        session["last_uid"] = uid
        session["status"] = "uid_detected"
        session["message"] = "Tag erkannt"
        save_link_session(session)
        return jsonify({"ok": True, "link_session": session})
    result = runtime_service.assign_album_by_rfid(uid)
    return jsonify(result), (200 if result.get("ok") else 404)


@app.route("/api/runtime/rfid/remove", methods=["POST"])
def api_runtime_rfid_remove():
    return jsonify(runtime_service.remove_rfid_tag())


@app.route("/api/runtime/audio-test", methods=["POST"])
def api_runtime_audio_test():
    payload = request.get_json(silent=True) or {}
    elapsed = to_int(payload.get("elapsed", request.form.get("elapsed", 5)), 5, 1, 120)
    return jsonify(runtime_service.tick(elapsed))


@app.route("/api/runtime/playback")
def api_runtime_playback():
    snapshot = runtime_service.status()
    return jsonify(snapshot["runtime"].get("playback_session", {}))


@app.route("/api/player/action", methods=["POST"])
def api_player_action():
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", request.form.get("action", ""))).strip()
    snapshot = runtime_service.status()
    runtime_state = snapshot["runtime"]
    settings = snapshot["settings"]

    if action == "toggle_play":
        result = runtime_service.toggle_playback()
    elif action == "stop":
        result = runtime_service.stop()
    elif action == "prev":
        result = runtime_service.previous_track()
    elif action == "next":
        result = runtime_service.next_track()
    elif action == "volume_down":
        result = runtime_service.set_volume(-int(settings.get("volume_step", 5)))
    elif action == "volume_up":
        result = runtime_service.set_volume(int(settings.get("volume_step", 5)))
    elif action == "mute":
        result = runtime_service.toggle_mute()
    elif action == "sleep_down":
        level = max(0, int(runtime_state.get("sleep_timer", {}).get("level", 0)) - 1)
        result = {"runtime": runtime_service.set_sleep_level(level), "player": runtime_service.load_player()}
    elif action == "sleep_up":
        level = min(3, int(runtime_state.get("sleep_timer", {}).get("level", 0)) + 1)
        result = {"runtime": runtime_service.set_sleep_level(level), "player": runtime_service.load_player()}
    elif action == "clear_queue":
        result = runtime_service.clear_queue()
    elif action == "seek":
        position_seconds = to_int(payload.get("seek_position", request.form.get("seek_position", 0)), 0, 0)
        result = runtime_service.seek(position_seconds)
    else:
        return jsonify({"ok": False, "message": "Unbekannte Player-Aktion."}), 400

    updated_snapshot = runtime_service.status()
    return jsonify({"ok": True, **build_player_context(updated_snapshot)})


@app.route("/api/runtime/button", methods=["POST"])
def api_runtime_button():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", request.form.get("name", ""))).strip()
    press_type = str(payload.get("press_type", request.form.get("press_type", "kurz"))).strip()
    held_seconds = payload.get("held_seconds", request.form.get("held_seconds"))
    resolved_press_type = runtime_service.classify_press_type(held_seconds, press_type)
    return jsonify(runtime_service.trigger_button(name, resolved_press_type))


@app.route("/api/runtime/seek", methods=["POST"])
def api_runtime_seek():
    payload = request.get_json(silent=True) or {}
    position_seconds = to_int(payload.get("position_seconds", request.form.get("position_seconds", 0)), 0, 0)
    return jsonify(runtime_service.seek(position_seconds))


@app.route("/api/runtime/reset", methods=["POST"])
def api_runtime_reset():
    return jsonify(runtime_service.reset_state())


@app.route("/api/runtime/load-album", methods=["POST"])
def api_runtime_load_album():
    payload = request.get_json(silent=True) or {}
    album_id = str(payload.get("album_id", request.form.get("album_id", ""))).strip()
    raw_autoplay = payload.get("autoplay", request.form.get("autoplay", "false"))
    if isinstance(raw_autoplay, bool):
        autoplay = raw_autoplay
    else:
        autoplay = str(raw_autoplay).strip().lower() in {"1", "true", "on", "yes"}
    result = runtime_service.load_album_by_id(album_id, autoplay=autoplay)
    return jsonify(result), (200 if result.get("ok") else 404)


@app.route("/api/runtime/queue-album", methods=["POST"])
def api_runtime_queue_album():
    payload = request.get_json(silent=True) or {}
    album_id = str(payload.get("album_id", request.form.get("album_id", ""))).strip()
    result = runtime_service.queue_album_by_id(album_id)
    return jsonify(result), (200 if result.get("ok") else 404)


@app.route("/api/library/link-session", methods=["POST"])
def api_library_link_session_start():
    payload = request.get_json(silent=True) or {}
    album_id = str(payload.get("album_id", request.form.get("album_id", ""))).strip()
    library_data = load_library()
    album = next((entry for entry in library_data.get("albums", []) if entry["id"] == album_id), None)
    if not album:
        return jsonify({"ok": False, "message": "Album nicht gefunden."}), 404
    return jsonify({"ok": True, "link_session": start_link_session(album)})


@app.route("/api/library/link-session", methods=["GET"])
def api_library_link_session_status():
    return jsonify({"ok": True, "link_session": load_link_session()})


@app.route("/api/library/link-session/confirm", methods=["POST"])
def api_library_link_session_confirm():
    payload = request.get_json(silent=True) or {}
    album_id = str(payload.get("album_id", request.form.get("album_id", ""))).strip()
    uid = str(payload.get("uid", request.form.get("uid", ""))).strip()
    if not album_id:
        return jsonify({"ok": False, "message": "Album nicht gefunden."}), 404
    if not uid:
        return jsonify({"ok": False, "message": "Tag-ID fehlt."}), 400
    payload, status_code = apply_link_uid(album_id, uid)
    return jsonify(payload), status_code


@app.route("/api/library/link-session/cancel", methods=["POST"])
def api_library_link_session_cancel():
    session = load_link_session()
    updated = finish_link_session(session, "cancelled", "Verlinkung abgebrochen.")
    return jsonify({"ok": True, "link_session": updated})


if __name__ == "__main__":
    ensure_data_files()
    host = os.environ.get("PHONIEBOX_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.environ.get("PHONIEBOX_PORT", "5080"))
    app.run(host=host, port=port, debug=False)
