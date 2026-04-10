import configparser
import copy
import io
import json
import services.library_service as library_service_module
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename
try:
    import gpiod
except ImportError:
    gpiod = None
try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.gpio import GPIO_PINS, GPIO_TO_BOARD_PIN, gpio_display_label, gpio_name_to_bcm, sample_gpio_levels_pinctrl, sample_gpio_levels_sysfs
from hardware.leds import LEDController
from hardware.pins import potential_system_pins, reserved_system_pins
from config import load_config
from routes import register_blueprints
from services import runtime_service
from services.library_service import (
    add_tracks_to_album,
    album_conflict,
    album_editor_payload,
    apply_link_uid,
    create_empty_album,
    default_link_session,
    effective_track_entries,
    finish_link_session,
    import_album_folder,
    library_storage_summary,
    load_library,
    load_link_session,
    rename_track_in_album,
    refresh_album_metadata,
    remove_track_from_album,
    remove_tracks_from_album,
    reorder_album_tracks,
    save_library,
    save_link_session,
    start_link_session,
    track_rows,
)
from system.audio import apply_audio_profile, deploy_audio_profile, detect_audio_environment
from system.networking import apply_wifi_profile, ensure_hostname, fallback_hotspot_cycle
from utils import (
    album_editor_response,
    format_mmss,
    is_json_request,
    json_error,
    json_success,
    load_json,
    merge_defaults,
    normalize_hotspot_security,
    progress_percent,
    safe_relative_path,
    save_json,
    slugify_name,
    to_float,
    to_int,
)

DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = BASE_DIR / "media"
ALBUMS_DIR = MEDIA_DIR / "albums"
PLAYER_FILE = DATA_DIR / "player_state.json"
LIBRARY_FILE = DATA_DIR / "library.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SETUP_FILE = DATA_DIR / "setup.json"
APPLY_REPORT_FILE = DATA_DIR / "last_apply_report.json"
NM_CONNECTIONS_DIR = Path("/etc/NetworkManager/system-connections")
WPA_SUPPLICANT_FILE = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
RUNTIME_FILE = DATA_DIR / "runtime_state.json"
LINK_SESSION_FILE = DATA_DIR / "rfid_link_session.json"
READER_STATUS_FILE = DATA_DIR / "reader_status.json"
BUTTON_DETECT_FILE = DATA_DIR / "button_detect.json"
LED_PREVIEW_FILE = DATA_DIR / "led_preview.json"
AUDIO_PROFILE_DIR = DATA_DIR / "generated" / "audio"
READER_GUIDE_DIR = BASE_DIR / "assets" / "reader-guides"
AUDIO_GUIDE_DIR = BASE_DIR / "assets" / "audio-guides"
READER_NONE_ID = "NONE"
APP_CONFIG = load_config()

def create_app():
    application = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    application.config["SECRET_KEY"] = APP_CONFIG.secret_key
    register_blueprints(application)
    return application


app = create_app()
app.secret_key = app.config["SECRET_KEY"]
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
    {"id": READER_NONE_ID, "label": "Kein Reader installiert", "driver": "-", "transport": "-"},
    {"id": "USB", "label": "USB-Reader", "driver": "hid/keyboard-reader", "transport": "usb"},
    {"id": "RC522", "label": "RC522", "driver": "mfrc522", "transport": "spi"},
    {"id": "PN532_SPI", "label": "PN532 (SPI)", "driver": "pn532", "transport": "spi"},
]


def default_player():
    return {
        "current_album": "",
        "current_track": "",
        "cover_url": "",
        "volume": 45,
        "muted": False,
        "volume_before_mute": 45,
        "position_seconds": 0,
        "duration_seconds": 0,
        "sleep_timer_minutes": 0,
        "is_playing": False,
        "playlist": "",
        "playlist_entries": [],
        "current_track_index": 0,
        "queue": [],
    }


def default_library():
    return {"albums": []}


def default_reader_status():
    return {
        "configured_type": READER_NONE_ID,
        "ready": False,
        "message": "Kein Reader installiert.",
        "details": [],
        "updated_at": 0,
    }


def default_settings():
    return {
        "max_volume": 85,
        "volume_step": 5,
        "sleep_timer_step": 5,
        "sleep_timer_button_rotation": False,
        "use_startup_volume": False,
        "startup_volume": 45,
        "rfid_read_action": "play",
        "rfid_remove_action": "stop",
        "reader_mode": "album_load",
        "performance_profile": "auto",
    }


def default_setup():
    return {
        "reader": {
            "type": READER_NONE_ID,
            "target_type": READER_NONE_ID,
            "install_state": "not_installed",
            "needs_reboot": False,
            "last_action_message": "Noch kein Reader installiert.",
            "connection_hint": "USB-Reader anstecken oder Reader per SPI verdrahten",
        },
        "hardware_buttons_enabled": False,
        "button_long_press_seconds": 2,
        "buttons": [
            {"id": "btn-1", "name": "Play/Pause", "pin": "", "press_type": "kurz"},
            {"id": "btn-2", "name": "Stopp", "pin": "", "press_type": "kurz"},
            {"id": "btn-3", "name": "Vor", "pin": "", "press_type": "kurz"},
            {"id": "btn-4", "name": "Zurück", "pin": "", "press_type": "kurz"},
            {"id": "btn-5", "name": "Lautstärke +", "pin": "", "press_type": "kurz"},
            {"id": "btn-6", "name": "Lautstärke -", "pin": "", "press_type": "kurz"},
            {"id": "btn-7", "name": "Sleep Timer +", "pin": "", "press_type": "kurz"},
            {"id": "btn-8", "name": "Sleep Timer -", "pin": "", "press_type": "kurz"},
            {"id": "btn-9", "name": "Wifi on/off", "pin": "", "press_type": "kurz"},
            {"id": "btn-10", "name": "Power on/off", "pin": "", "press_type": "lang"},
        ],
        "leds": [
            {"id": "led-1", "name": "Power", "pin": "", "function": "power_on", "brightness": 50},
            {"id": "led-2", "name": "Stand-by", "pin": "", "function": "standby", "brightness": 30},
            {"id": "led-3", "name": "Sleep 1/3", "pin": "", "function": "sleep_1", "brightness": 50},
            {"id": "led-4", "name": "Sleep 2/3", "pin": "", "function": "sleep_2", "brightness": 70},
            {"id": "led-5", "name": "Sleep 3/3", "pin": "", "function": "sleep_3", "brightness": 90},
            {"id": "led-6", "name": "Wifi", "pin": "", "function": "wifi_on", "brightness": 55},
        ],
        "power_routines": {
            "power_on": "sleep_count_up_5",
            "power_off": "sleep_count_down_5",
        },
        "audio": {
            "output_mode": "usb_dac",
            "i2s_profile": "auto",
            "connection_hint": "Onboard- oder USB-Soundkarte auswählen",
        },
        "wifi": {
            "mode": "hotspot_only",
            "allow_button_toggle": False,
            "country": "DE",
            "fallback_hotspot": True,
            "hotspot_security": "open",
            "hotspot_ssid": "Phonie-hotspot",
            "hotspot_password": "",
            "hotspot_channel": 6,
            "hostname": "phoniebox",
            "browser_name": "phoniebox.local",
            "saved_networks": [],
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


def format_storage_size(num_bytes):
    value = max(0, int(num_bytes or 0))
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    value_float = float(value)
    while value_float >= 1024 and index < len(units) - 1:
        value_float /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value_float)} {units[index]}"
    return f"{value_float:.1f} {units[index]}"




def load_settings():
    return merge_defaults(load_json(SETTINGS_FILE, default_settings()), default_settings())


def save_settings(data):
    save_json(SETTINGS_FILE, data)


def load_setup():
    data = merge_defaults(load_json(SETUP_FILE, default_setup()), default_setup())
    original = copy.deepcopy(data)
    normalized = normalize_setup_data(data)
    imported_wifi = import_active_wifi_into_setup(normalized)
    if normalized != original or imported_wifi:
        save_setup(normalized)
    return normalized


def save_setup(data):
    save_json(SETUP_FILE, data)


def valid_reader_ids():
    return {option["id"] for option in READER_OPTIONS}


def normalize_reader_type(value):
    reader_type = (value or READER_NONE_ID).strip()
    if reader_type not in valid_reader_ids():
        return READER_NONE_ID
    return reader_type


def reader_requires_reboot(current_type, target_type):
    current_type = normalize_reader_type(current_type)
    target_type = normalize_reader_type(target_type)
    if current_type == target_type:
        return False
    return any(reader_type in {READER_NONE_ID, "RC522", "PN532_SPI"} for reader_type in (current_type, target_type))


def reader_transition_commands(target_type):
    target_type = normalize_reader_type(target_type)
    commands = []
    if target_type in {"RC522", "PN532_SPI"}:
        commands.append(["raspi-config", "nonint", "do_spi", "0"])
    return commands


def reader_runtime_cleanup_packages(target_type):
    target_type = normalize_reader_type(target_type)
    profile_packages = {
        "USB": {"evdev"},
        "RC522": {"pi-rc522", "spidev"},
        "PN532_SPI": {"adafruit-blinka", "adafruit-circuitpython-pn532", "spidev"},
    }
    keep = profile_packages.get(target_type, set())
    all_packages = set().union(*profile_packages.values())
    return sorted(all_packages - keep)


def reader_runtime_commands(target_type):
    python_bin = sys.executable
    target_type = normalize_reader_type(target_type)
    commands = []

    cleanup_packages = reader_runtime_cleanup_packages(target_type)
    if cleanup_packages:
        commands.append([python_bin, "-m", "pip", "uninstall", "-y", *cleanup_packages])

    if target_type == "USB":
        commands.append([python_bin, "-m", "pip", "install", "--upgrade", "evdev"])
    elif target_type == "RC522":
        commands.append([python_bin, "-m", "pip", "uninstall", "-y", "RPi.GPIO"])
        commands.append([python_bin, "-m", "pip", "install", "--upgrade", "spidev"])
        commands.append([python_bin, "-m", "pip", "install", "--upgrade", "rpi-lgpio"])
        commands.append([python_bin, "-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-deps", "pi-rc522==2.3.0"])
    elif target_type == "PN532_SPI":
        commands.append([python_bin, "-m", "pip", "install", "--upgrade", "adafruit-blinka>=8.0,<9.0"])
        commands.append([python_bin, "-m", "pip", "install", "--upgrade", "adafruit-circuitpython-pn532>=2.0,<3.0"])
        commands.append([python_bin, "-m", "pip", "install", "--upgrade", "spidev"])

    return commands


def run_local_command(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (result.stdout or result.stderr or "").strip()
    return {"ok": result.returncode == 0, "output": output}


def save_reader_status(configured_type, ready, message, details=None):
    save_json(
        READER_STATUS_FILE,
        {
            "configured_type": normalize_reader_type(configured_type),
            "ready": bool(ready),
            "message": str(message or ""),
            "details": list(details or []),
            "updated_at": int(time.time()),
        },
    )


def effective_track_entries(album):
    original_base_dir = library_service_module.BASE_DIR
    try:
        library_service_module.BASE_DIR = BASE_DIR
        return library_service_module.effective_track_entries(album)
    finally:
        library_service_module.BASE_DIR = original_base_dir


def current_boot_timestamp():
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return 0
    return int(time.time() - uptime_seconds)


def normalize_setup_data(data):
    reader = data.setdefault("reader", {})
    installed_type = normalize_reader_type(reader.get("type"))
    target_type = normalize_reader_type(reader.get("target_type", installed_type))
    reader["type"] = installed_type
    reader["target_type"] = target_type
    state = (reader.get("install_state") or "").strip() or ("installed" if installed_type != READER_NONE_ID else "not_installed")
    needs_reboot = bool(reader.get("needs_reboot", False))
    reboot_requested_at = to_int(reader.get("reboot_requested_at"), 0, 0, 9999999999)
    if state not in {"not_installed", "selected", "installed", "reboot_pending", "error"}:
        state = "installed" if installed_type != READER_NONE_ID else "not_installed"
    if state == "reboot_pending":
        booted_at = current_boot_timestamp()
        if reboot_requested_at and booted_at and booted_at >= reboot_requested_at:
            installed_type = target_type
            reader["type"] = installed_type
            state = "installed" if installed_type != READER_NONE_ID else "not_installed"
            needs_reboot = False
            reboot_requested_at = 0
            reader["last_action_message"] = (
                "Noch kein Reader installiert."
                if installed_type == READER_NONE_ID
                else f"{current_reader_option(installed_type)['label']} ist installiert."
            )
    else:
        reboot_requested_at = 0
    reader["install_state"] = state
    reader["needs_reboot"] = needs_reboot
    reader["reboot_requested_at"] = reboot_requested_at
    reader["last_action_message"] = (reader.get("last_action_message") or "").strip() or (
        "Noch kein Reader installiert." if installed_type == READER_NONE_ID else f"{current_reader_option(installed_type)['label']} ist installiert."
    )
    return data


def reader_install_state(reader_config):
    installed_type = normalize_reader_type(reader_config.get("type"))
    target_type = normalize_reader_type(reader_config.get("target_type", installed_type))
    installed_option = current_reader_option(installed_type)
    target_option = current_reader_option(target_type)
    state = (reader_config.get("install_state") or "not_installed").strip()
    needs_reboot = bool(reader_config.get("needs_reboot"))
    message = (reader_config.get("last_action_message") or "").strip()
    if not message:
        message = "Noch kein Reader installiert." if installed_type == READER_NONE_ID else f"{installed_option['label']} ist installiert."
    return {
        "installed_type": installed_type,
        "target_type": target_type,
        "installed_option": installed_option,
        "target_option": target_option,
        "state": state,
        "needs_reboot": needs_reboot,
        "message": message,
        "can_install": target_type != READER_NONE_ID and target_type != installed_type,
        "can_uninstall": installed_type != READER_NONE_ID,
    }


READER_REBOOT_DELAY_SECONDS = 8


def schedule_reboot(delay_seconds=READER_REBOOT_DELAY_SECONDS):
    subprocess.Popen(
        ["/bin/sh", "-c", f"sleep {max(int(delay_seconds), 1)} && systemctl reboot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def apply_reader_install_action(data, action, selected_type):
    reader = data.setdefault("reader", {})
    current_type = normalize_reader_type(reader.get("type"))
    selected_type = normalize_reader_type(selected_type)
    target_type = READER_NONE_ID if action == "uninstall" else selected_type
    details = []

    for command in reader_runtime_commands(target_type):
        result = run_local_command(command)
        details.append(result["output"] or "OK")
        if not result["ok"]:
            reader["target_type"] = selected_type
            reader["install_state"] = "error"
            reader["needs_reboot"] = False
            reader["last_action_message"] = f"Reader-Pakete konnten nicht eingerichtet werden: {' '.join(command)}"
            save_setup(data)
            return {
                "ok": False,
                "message": reader["last_action_message"],
                "details": [entry for entry in details if entry],
                "target_type": target_type,
            }

    for command in reader_transition_commands(target_type):
        result = run_local_command(command)
        details.append(result["output"] or "OK")
        if not result["ok"]:
            reader["target_type"] = selected_type
            reader["install_state"] = "error"
            reader["needs_reboot"] = False
            reader["last_action_message"] = f"Reader-Aktion fehlgeschlagen: {' '.join(command)}"
            save_setup(data)
            return {
                "ok": False,
                "message": reader["last_action_message"],
                "details": [entry for entry in details if entry],
                "target_type": target_type,
            }

    reboot_required = reader_requires_reboot(current_type, target_type)
    reader["type"] = current_type if reboot_required else target_type
    reader["target_type"] = target_type
    reader["install_state"] = "reboot_pending" if reboot_required else ("installed" if target_type != READER_NONE_ID else "not_installed")
    reader["needs_reboot"] = reboot_required
    reader["reboot_requested_at"] = int(time.time()) if reboot_required else 0
    if action == "install":
        reader["last_action_message"] = (
            f"{current_reader_option(target_type)['label']} wird nach dem Neustart installiert."
            if reboot_required
            else f"{current_reader_option(target_type)['label']} wurde vorbereitet."
        )
        save_reader_status(
            target_type,
            False,
            "Reader-Installation vorbereitet.",
            ["System wird für den gewählten Reader eingerichtet."] + ([f"Neustart erforderlich für {current_reader_option(target_type)['label']}."] if reboot_required else []),
        )
    else:
        reader["last_action_message"] = "Reader wird nach dem Neustart entfernt." if reboot_required else "Reader wurde deinstalliert."
        save_reader_status(
            current_type if reboot_required else READER_NONE_ID,
            False,
            "Reader-Deinstallation vorbereitet." if reboot_required else "Kein Reader installiert.",
            ["System bereitet die Reader-Entfernung vor."] if reboot_required else [],
        )
    save_setup(data)
    if reader["needs_reboot"]:
        schedule_reboot()
    return {
        "ok": True,
        "message": reader["last_action_message"],
        "details": [entry for entry in details if entry],
        "target_type": target_type,
        "reboot_scheduled": reader["needs_reboot"],
    }


def build_audio_runtime_config(audio_setup, settings):
    config = dict(audio_setup or {})
    config["playback_backend"] = "mpv"
    config["mixer_control"] = "auto"
    config["preferred_output"] = "auto"
    config["mono_downmix"] = False
    config["external_soundcard_required"] = False
    config["apply_boot_config"] = False
    config["use_startup_volume"] = bool(settings.get("use_startup_volume", False))
    config["enable_audio_service"] = config["use_startup_volume"]
    config["startup_volume"] = to_int(settings.get("startup_volume"), 45, 0, 100)
    return config


def load_apply_report():
    return load_json(APPLY_REPORT_FILE, default_apply_report())


def save_apply_report(data):
    save_json(APPLY_REPORT_FILE, data)


def load_reader_status():
    return merge_defaults(load_json(READER_STATUS_FILE, default_reader_status()), default_reader_status())


def load_button_detect():
    return merge_defaults(load_json(BUTTON_DETECT_FILE, default_button_detect()), default_button_detect())


def save_button_detect(data):
    save_json(BUTTON_DETECT_FILE, data)


def set_gpio_poll_service_active(active):
    try:
        subprocess.run(
            ["systemctl", "start" if active else "stop", "phoniebox-gpio-poll.service"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return True


def restart_gpio_poll_service_later(delay_seconds=2.0):
    timer = threading.Timer(max(0.1, float(delay_seconds)), lambda: set_gpio_poll_service_active(True))
    timer.daemon = True
    timer.start()
    return timer


def prepare_button_detect_inputs(gpio_names):
    gpio_names = [name for name in gpio_names if name]
    if GPIO is None or not gpio_names:
        return False
    try:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        configured = False
        for gpio_name in gpio_names:
            bcm = gpio_name_to_bcm(gpio_name)
            if bcm is None:
                continue
            try:
                GPIO.setup(bcm, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            except Exception:
                continue
            configured = True
        return configured
    except Exception:
        return False


def release_button_detect_inputs(gpio_names):
    gpio_names = [name for name in gpio_names if name]
    if GPIO is None or not gpio_names:
        return False
    released = False
    for gpio_name in gpio_names:
        bcm = gpio_name_to_bcm(gpio_name)
        if bcm is None:
            continue
        try:
            GPIO.cleanup(bcm)
            released = True
        except Exception:
            continue
    return released


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
    pinctrl_sample = sample_gpio_levels_pinctrl(gpio_names)
    if pinctrl_sample:
        return pinctrl_sample
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
        release_button_detect_inputs(session.get("candidate_pins", []))
        set_gpio_poll_service_active(True)
        return session

    now = time.time()
    if now >= float(session.get("deadline_at", 0)):
        session["active"] = False
        session["status"] = "timeout"
        session["message"] = "Keine Taste erkannt."
        save_button_detect(session)
        release_button_detect_inputs(session.get("candidate_pins", []))
        set_gpio_poll_service_active(True)
        return session

    setup_data = setup_data or load_setup()
    candidates = session.get("candidate_pins") or button_detection_candidates(setup_data)
    prepare_button_detect_inputs(candidates)
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
            release_button_detect_inputs(session.get("candidate_pins", []))
            set_gpio_poll_service_active(True)
            return session

    session["remaining_seconds"] = max(0, int(session["deadline_at"] - now + 0.999))
    return session


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


def detect_active_ssid():
    active = run_nmcli(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
    if active:
        for line in active.splitlines():
            active_flag, ssid = (line.split(":", 1) + [""])[:2]
            if active_flag == "yes" and ssid:
                return ssid

    result = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return (result.stdout or "").strip()
    return ""


def find_password_in_nmconnections(ssid):
    if not ssid or not NM_CONNECTIONS_DIR.exists():
        return ""

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
    return ""


def find_password_in_wpa_supplicant(ssid):
    if not ssid or not WPA_SUPPLICANT_FILE.exists():
        return ""

    current_ssid = None
    current_psk = None
    content = WPA_SUPPLICANT_FILE.read_text(encoding="utf-8", errors="ignore")
    for raw_line in content.splitlines():
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
    return ""


def find_current_wifi_password(ssid):
    return find_password_in_nmconnections(ssid) or find_password_in_wpa_supplicant(ssid)


def import_active_wifi_into_setup(setup_data):
    wifi = setup_data.setdefault("wifi", {})
    saved_networks = wifi.setdefault("saved_networks", [])
    ssid = detect_active_ssid()
    if not ssid:
        return False

    password = find_current_wifi_password(ssid)
    existing = next((entry for entry in saved_networks if (entry.get("ssid") or "").strip() == ssid), None)
    changed = False
    if existing is None:
        saved_networks.append(
            {
                "id": f"wifi-{secrets.token_hex(4)}",
                "ssid": ssid,
                "password": password,
                "priority": 100,
            }
        )
        changed = True
    else:
        if password and existing.get("password") != password:
            existing["password"] = password
            changed = True
        if int(existing.get("priority", 10) or 10) < 100:
            existing["priority"] = 100
            changed = True

    if wifi.get("mode") == "hotspot_only":
        wifi["mode"] = "client_with_fallback_hotspot"
        changed = True
    if not wifi.get("fallback_hotspot", True):
        wifi["fallback_hotspot"] = True
        changed = True
    return changed


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


def assigned_button_pins(setup_data):
    return {button.get("pin", "").strip() for button in setup_data.get("buttons", []) if button.get("pin", "").strip()}


def assigned_led_pins(setup_data):
    return {led.get("pin", "").strip() for led in setup_data.get("leds", []) if led.get("pin", "").strip()}


def pin_choices(setup_data, role):
    reserved = potential_system_pins()
    blocked_by_other_role = assigned_led_pins(setup_data) if role == "button" else assigned_button_pins(setup_data)
    pins = GPIO_PINS
    if role == "led":
        pins = [pin for pin in GPIO_PINS if (pin in PWM_PINS or pin not in reserved) and pin not in blocked_by_other_role]
    else:
        pins = [pin for pin in GPIO_PINS if pin not in reserved and pin not in blocked_by_other_role]
    return pins


def cross_role_pin_errors(setup_data):
    overlap = assigned_button_pins(setup_data) & assigned_led_pins(setup_data)
    return [f"PIN {pin} ist bereits der anderen Gerätegruppe zugeordnet." for pin in sorted(overlap)]


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
    potential = potential_system_pins()
    for pin, by_press_type in button_pins.items():
        if pin in reserved:
            button_names = [name for names in by_press_type.values() for name in names]
            warnings.append(f"Taste {', '.join(button_names)} muss neu zugeordnet werden. {pin} ist für Reader reserviert.")
        elif pin in potential:
            button_names = [name for names in by_press_type.values() for name in names]
            warnings.append(f"Taste {', '.join(button_names)} sollte neu zugeordnet werden. {pin} ist grundsätzlich für Reader reserviert.")
    for pin, names in led_pins.items():
        if pin in reserved:
            warnings.append(f"LED {', '.join(names)} muss neu zugeordnet werden. {pin} ist für Reader reserviert.")
        elif pin in potential:
            warnings.append(f"LED {', '.join(names)} sollte neu zugeordnet werden. {pin} ist grundsätzlich für Reader reserviert.")

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
        "PN532_SPI": "pn532-spi.txt",
    }.get(reader_type, "usb-keyboard-reader.txt")


def reader_guide_path(reader_type):
    return READER_GUIDE_DIR / reader_guide_filename(reader_type)


def audio_guide_filename(output_mode):
    return ""


def audio_guide_path(output_mode):
    return Path("")


def audio_output_choices(environment=None):
    environment = environment or detect_audio_environment()
    choices = [{"id": "usb_dac", "label": "USB-Soundkarte"}]
    if environment.get("has_analog_audio"):
        choices.insert(0, {"id": "analog_jack", "label": "Onboard-Soundkarte"})
    return choices


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
        "panel_url": f"http://{hostname}.local",
        "panel_ip_example": "http://192.168.0.xxx",
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


@app.context_processor
def inject_shell():
    return {"nav_items": nav_items(), "active_path": request.path}


def nav_items():
    return [
        {"endpoint": "player_routes.player", "label": "Player"},
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
        "audio_environment": audio_environment,
    }


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


@app.route("/settings", methods=["GET", "POST"])
def settings():
    data = load_settings()
    if request.method == "POST":
        source = request.get_json(silent=True) or request.form
        data = apply_settings_form(data, source)
        save_settings(data)
        if is_json_request():
            return json_success("Einstellungen gespeichert.", settings=data)
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("settings"))
    return render_template(
        "settings.html",
        settings=data,
        performance_profile_options=runtime_service.performance_profile_catalog(),
        performance_profile_state=runtime_service.performance_profile(),
    )


def apply_settings_form(data, source):
    data["max_volume"] = to_int(source.get("max_volume"), data["max_volume"], 10, 100)
    data["volume_step"] = to_int(source.get("volume_step"), data["volume_step"], 1, 25)
    data["sleep_timer_step"] = to_int(source.get("sleep_timer_step"), data["sleep_timer_step"], 1, 60)
    data["sleep_timer_button_rotation"] = source.get("sleep_timer_button_rotation") in {"on", True, "true", "1", 1}
    data["use_startup_volume"] = source.get("use_startup_volume") == "on"
    data["startup_volume"] = to_int(source.get("startup_volume"), data.get("startup_volume", 45), 0, 100)
    data["rfid_read_action"] = source.get("rfid_read_action", data["rfid_read_action"])
    data["rfid_remove_action"] = source.get("rfid_remove_action", data["rfid_remove_action"])
    selected_profile = str(source.get("performance_profile", data.get("performance_profile", "auto")) or "auto").strip().lower()
    valid_profiles = {"auto", "pi_zero2w", "standard", "pi4_plus", "dev"}
    data["performance_profile"] = selected_profile if selected_profile in valid_profiles else "auto"
    return data


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = load_settings()
    payload = request.get_json(silent=True) or {}
    data = apply_settings_form(data, payload)
    save_settings(data)
    return json_success("Einstellungen gespeichert.", settings=data)


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
        {"id": "btn-1", "name": "Play/Pause", "pin": "", "press_type": "kurz"},
        {"id": "btn-2", "name": "Stopp", "pin": "", "press_type": "kurz"},
        {"id": "btn-3", "name": "Vor", "pin": "", "press_type": "kurz"},
        {"id": "btn-4", "name": "Zurück", "pin": "", "press_type": "kurz"},
        {"id": "btn-5", "name": "Lautstärke +", "pin": "", "press_type": "kurz"},
        {"id": "btn-6", "name": "Lautstärke -", "pin": "", "press_type": "kurz"},
        {"id": "btn-7", "name": "Sleep Timer +", "pin": "", "press_type": "kurz"},
        {"id": "btn-8", "name": "Sleep Timer -", "pin": "", "press_type": "kurz"},
        {"id": "btn-9", "name": "Wifi on/off", "pin": "", "press_type": "kurz"},
        {"id": "btn-10", "name": "Power on/off", "pin": "", "press_type": "lang"},
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
            action = request.form.get("reader_action", "").strip()
            selected_type = normalize_reader_type(request.form.get("reader_type", data.get("reader", {}).get("target_type")))
            data["reader"]["target_type"] = selected_type
            if action in {"install", "uninstall"}:
                result = apply_reader_install_action(data, action, selected_type)
                redirect_kwargs = {}
                if result.get("reboot_scheduled"):
                    redirect_kwargs = {
                        "reader_reboot": "1",
                        "reader_action": action,
                        "reboot_seconds": READER_REBOOT_DELAY_SECONDS,
                    }
                flash(
                    f"{result['message']} Reboot wird gestartet." if result.get("reboot_scheduled") else result["message"],
                    "success" if result["ok"] else "error",
                )
                return redirect(url_for("setup", **redirect_kwargs))
            flash("Unbekannte Reader-Aktion.", "error")
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
            candidate["hardware_buttons_enabled"] = request.form.get("hardware_buttons_enabled") == "on"
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
            errors.extend(cross_role_pin_errors(candidate))
            if errors:
                for error in errors:
                    flash(error, "error")
                return redirect(url_for("setup"))
            data["buttons"] = new_buttons
            data["hardware_buttons_enabled"] = candidate["hardware_buttons_enabled"]
            data["button_long_press_seconds"] = candidate["button_long_press_seconds"]
            save_setup(data)
            flash("Tastenbelegung gespeichert.", "success")
            return redirect(url_for("setup"))

        if section == "leds":
            rows = collect_rows("led", ["name", "pin", "function", "brightness"])
            candidate_leds = [
                {
                    "id": f"led-{index + 1}",
                    "name": row["name"],
                    "pin": row["pin"],
                    "function": row["function"],
                    "brightness": to_int(row["brightness"], 50, 0, 100),
                }
                for index, row in enumerate(rows)
            ]
            candidate = dict(data)
            candidate["leds"] = candidate_leds
            errors = cross_role_pin_errors(candidate)
            if errors:
                for error in errors:
                    flash(error, "error")
                return redirect(url_for("setup"))
            data["leds"] = candidate_leds
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
            if audio["output_mode"] not in {"analog_jack", "usb_dac"}:
                audio["output_mode"] = "usb_dac"
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
    reader_management = reader_install_state(data.get("reader", {}))
    reader_reboot_notice = {
        "active": request.args.get("reader_reboot") == "1",
        "action": request.args.get("reader_action", "").strip(),
        "seconds": to_int(request.args.get("reboot_seconds"), READER_REBOOT_DELAY_SECONDS, 1, 60),
    }
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
        reader_status=load_reader_status(),
        reader_management=reader_management,
        runtime_state=runtime_snapshot["runtime"],
        button_mapping_rows=button_mapping_rows(data),
        reader_option=reader_management["target_option"],
        reader_reboot_notice=reader_reboot_notice,
    )


@app.route("/api/setup/button-detect/start", methods=["POST"])
def api_setup_button_detect_start():
    setup_data = load_setup()
    candidates = button_detection_candidates(setup_data)
    set_gpio_poll_service_active(False)
    now = time.time()
    session = {
        "active": True,
        "started_at": now,
        "deadline_at": now + 15,
        "status": "listening",
        "message": "Warte auf Tastendruck.",
        "detected_gpio": "",
        "detected_pin": "",
        "baseline": {},
        "candidate_pins": candidates,
        "remaining_seconds": 15,
    }
    save_button_detect(session)
    time.sleep(0.12)
    prepare_button_detect_inputs(candidates)
    time.sleep(0.12)
    baseline = sample_gpio_levels(candidates)
    if not baseline:
        session = default_button_detect()
        session["status"] = "unavailable"
        session["message"] = "Keine GPIO-Tasterkennung verfügbar."
        save_button_detect(session)
        release_button_detect_inputs(candidates)
        set_gpio_poll_service_active(True)
        payload = dict(session)
        payload.pop("message", None)
        return json_error(session["message"], status_code=503, **payload)
    session["baseline"] = baseline
    save_button_detect(session)
    payload = dict(session)
    payload.pop("message", None)
    return json_success(session["message"], **payload)


@app.route("/api/setup/button-detect/status")
def api_setup_button_detect_status():
    session = button_detect_status_payload(load_setup())
    payload = dict(session)
    payload.pop("message", None)
    return json_success(session.get("message", ""), **payload)


@app.route("/api/setup/led-blink", methods=["POST"])
def api_setup_led_blink():
    payload = request.get_json(silent=True) or {}
    pin = str(payload.get("pin", request.form.get("pin", ""))).strip()
    brightness = to_int(payload.get("brightness", request.form.get("brightness", 100)), 100, 0, 100)
    if not pin:
        return json_error("Kein LED-PIN ausgewählt.", status_code=400, details=["Kein LED-PIN ausgewählt."])
    detect_state = load_button_detect()
    if detect_state.get("active"):
        release_button_detect_inputs(detect_state.get("candidate_pins", []))
        detect_state = default_button_detect()
        save_button_detect(detect_state)
    set_gpio_poll_service_active(False)
    save_json(
        LED_PREVIEW_FILE,
        {
            "id": secrets.token_hex(6),
            "pin": pin,
            "brightness": brightness,
            "repeats": 3,
            "on_seconds": 0.22,
            "off_seconds": 0.18,
            "status": "pending",
            "requested_at": time.time(),
        },
    )
    restart_gpio_poll_service_later(2.4)
    ok = True
    if not ok:
        return json_error(f"LED-Test für {pin} konnte nicht gestartet werden.", status_code=503, details=[f"LED-Test für {pin} konnte nicht gestartet werden."])
    return json_success(f"LED-Test für {pin} gestartet.", details=[f"LED-Test für {pin} gestartet."])


if __name__ == "__main__":
    ensure_data_files()
    app.run(host=APP_CONFIG.host, port=APP_CONFIG.port, debug=False)
