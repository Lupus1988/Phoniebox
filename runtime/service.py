import fcntl
import json
import os
import random
import secrets
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None


BASE_DIR = Path(__file__).resolve().parent.parent
SOUNDS_DIR = BASE_DIR / "assets" / "sounds"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.gpio import GPIO_TO_BOARD_PIN, SysfsGPIOInput, gpio_display_label, sample_gpio_levels_pinctrl, sysfs_gpio_available
from hardware.manager import detect_hardware
from hardware.pins import filter_reserved_gpio_names, potential_system_pins, reserved_system_pins
from runtime.audio import build_track_queue, load_playlist_entries, pick_track_duration, track_title_from_entry
from services.audio_backends import create_audio_backend
from system.networking import run_wifi_state_command, wifi_radio_enabled

DATA_DIR = BASE_DIR / "data"
PLAYER_FILE = DATA_DIR / "player_state.json"
LIBRARY_FILE = DATA_DIR / "library.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SETUP_FILE = DATA_DIR / "setup.json"
RUNTIME_FILE = DATA_DIR / "runtime_state.json"
BUTTON_DETECT_FILE = DATA_DIR / "button_detect.json"
LED_PREVIEW_FILE = DATA_DIR / "led_preview.json"
STATE_LOCK_FILE = DATA_DIR / "state.lock"


def current_boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    tmp.replace(path)


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
        "playlist_tracks": [],
        "current_track_index": 0,
        "queued_tracks": [],
        "queue": [],
    }


def default_runtime_state():
    return {
        "powered_on": True,
        "playback_state": "paused",
        "active_album_id": "",
        "active_rfid_uid": "",
        "last_event": "Systemstart",
        "last_event_at": int(time.time()),
        "sleep_timer": {
            "remaining_seconds": 0,
            "step_seconds": 300,
            "level": 0,
        },
        "power_hold": {
            "pressed": False,
            "seconds": 0,
            "mode": "idle",
            "pin": "",
            "started_at": 0.0,
            "threshold_seconds": 0.0,
            "routine_id": "",
            "animation": "",
            "completed": False,
        },
        "hardware": {
            "reader_connected": False,
            "reader_type": "USB",
            "last_scanned_uid": "",
            "last_button": "",
            "last_button_press_type": "",
            "pressed_buttons": [],
            "encoder_debug": [],
            "profile": {},
        },
        "led_status": [],
        "queue_revision": secrets.token_hex(4),
        "playback_session": {},
        "event_log": [],
        "wifi_enabled": True,
        "last_activity_at": int(time.time()),
        "last_wifi_activity_at": int(time.time()),
        "wifi_auto_off_started_at": int(time.time()),
        "system": {
            "boot_id": current_boot_id(),
            "last_boot_recovery_at": 0,
        },
    }


def default_button_detect():
    return {
        "active": False,
        "status": "idle",
        "deadline_at": 0.0,
    }


class RuntimeService:
    HARDWARE_PROFILE_TTL_SECONDS = 5.0
    WIFI_STATE_TTL_SECONDS = 5.0
    SETUP_CACHE_TTL_SECONDS = 0.5
    SETTINGS_CACHE_TTL_SECONDS = 1.0
    PERFORMANCE_PROFILES = {
        "pi_zero2w": {
            "label": "Raspberry Pi Zero 2 W",
            "button_poll_interval_seconds": 0.07,
            "player_poll_visible_ms": 1200,
            "player_poll_hidden_ms": 3500,
        },
        "standard": {
            "label": "Standard",
            "button_poll_interval_seconds": 0.05,
            "player_poll_visible_ms": 1000,
            "player_poll_hidden_ms": 3000,
        },
        "pi4_plus": {
            "label": "Raspberry Pi 4 / schneller",
            "button_poll_interval_seconds": 0.035,
            "player_poll_visible_ms": 850,
            "player_poll_hidden_ms": 2200,
        },
        "dev": {
            "label": "Entwicklungsmodus",
            "button_poll_interval_seconds": 0.08,
            "player_poll_visible_ms": 1400,
            "player_poll_hidden_ms": 4000,
        },
    }
    SLEEP_TIMER_FADE_SECONDS = 5.0
    SLEEP_TIMER_FADE_STEPS = 10
    PRESENCE_READER_TYPES = {"RC522", "PN532_SPI"}
    PREVIOUS_TRACK_RESTART_THRESHOLD_SECONDS = 3
    ENCODER_ROTATION_EVENTS = {"cw", "ccw"}
    ENCODER_TRANSITION_DEBOUNCE_SECONDS = 0.004
    ENCODER_STEPS_PER_EVENT = 4
    ENCODER_ACTIVE_POLL_INTERVAL_SECONDS = 0.006
    ENCODER_IDLE_POLL_INTERVAL_SECONDS = 0.025
    ENCODER_DEEP_IDLE_POLL_INTERVAL_SECONDS = 0.05
    ENCODER_ACTIVE_HOLD_SECONDS = 0.2
    GPIO_ACTIVITY_HOLD_SECONDS = 1.0
    ENCODER_CLOCKWISE_TRANSITIONS = {
        (0b00, 0b01),
        (0b01, 0b11),
        (0b11, 0b10),
        (0b10, 0b00),
    }
    ENCODER_COUNTERCLOCKWISE_TRANSITIONS = {
        (0b00, 0b10),
        (0b10, 0b11),
        (0b11, 0b01),
        (0b01, 0b00),
    }

    def __init__(self):
        self.runtime_path = RUNTIME_FILE
        self.audio_backend = create_audio_backend()
        self.playback = self.audio_backend
        self._gpio_ready = False
        self._gpio_backend = None
        self._configured_gpio_pins = set()
        self._idle_low_gpio_pins = set()
        self._button_poll_state = {}
        self._encoder_poll_state = {}
        self._last_pressed_pins = []
        self._sysfs_gpio = SysfsGPIOInput()
        self._hardware_profile_cache = None
        self._hardware_profile_cached_at = 0.0
        self._wifi_enabled_cache = True
        self._wifi_enabled_cached_at = 0.0
        self._device_model_cache = None
        self._settings_cache = None
        self._settings_cached_at = 0.0
        self._settings_cache_stat = (-1, -1)
        self._setup_cache = None
        self._setup_cached_at = 0.0
        self._setup_cache_stat = (-1, -1)
        self._button_poll_config_cache = None
        self._button_poll_config_cache_key = None
        self._state_lock = threading.RLock()
        self._state_lock_handle = None
        self._state_lock_depth = 0
        self._boot_recovery_checked = False
        self._encoder_fast_poll_until = 0.0
        self._gpio_activity_until = 0.0

    def _wifi_radio_enabled_cached(self, force_refresh=False):
        now = time.monotonic()
        if not force_refresh and (now - self._wifi_enabled_cached_at) < self.WIFI_STATE_TTL_SECONDS:
            return bool(self._wifi_enabled_cache)
        enabled = wifi_radio_enabled()
        self._wifi_enabled_cache = bool(enabled)
        self._wifi_enabled_cached_at = now
        return self._wifi_enabled_cache

    def _device_model(self):
        if self._device_model_cache is not None:
            return self._device_model_cache
        model = ""
        for path in (Path("/proc/device-tree/model"), Path("/sys/firmware/devicetree/base/model")):
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            model = raw.replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()
            if model:
                break
        self._device_model_cache = model
        return self._device_model_cache

    def _auto_performance_profile_id(self):
        model = self._device_model().lower()
        if "zero 2" in model:
            return "pi_zero2w"
        if "raspberry pi 4" in model or "raspberry pi 5" in model:
            return "pi4_plus"
        if not model:
            return "dev"
        return "standard"

    def performance_profile_catalog(self):
        return [
            {
                "id": "auto",
                "label": "Automatisch",
                "description": "Profil passend zur erkannten Hardware wählen.",
            },
            {
                "id": "pi_zero2w",
                "label": "Pi Zero 2 W",
                "description": "Schonenderes Polling für kleine Systeme.",
            },
            {
                "id": "standard",
                "label": "Standard",
                "description": "Ausgewogen für typische Systeme.",
            },
            {
                "id": "pi4_plus",
                "label": "Pi 4 / schneller",
                "description": "Aggressiveres Polling auf starken Systemen.",
            },
            {
                "id": "dev",
                "label": "Entwicklung",
                "description": "Stabil und sparsam für Entwicklungsmaschinen.",
            },
        ]

    def performance_profile(self):
        settings = self.load_settings()
        selected = str(settings.get("performance_profile", "auto") or "auto").strip().lower()
        valid = {"auto", *self.PERFORMANCE_PROFILES.keys()}
        if selected not in valid:
            selected = "auto"
        resolved = self._auto_performance_profile_id() if selected == "auto" else selected
        preset = dict(self.PERFORMANCE_PROFILES.get(resolved, self.PERFORMANCE_PROFILES["standard"]))
        return {
            "selected_profile": selected,
            "resolved_profile": resolved,
            "device_model": self._device_model(),
            **preset,
        }

    def button_poll_interval_seconds(self):
        profile = self.performance_profile()
        return float(profile.get("button_poll_interval_seconds", 0.05) or 0.05)

    def gpio_poll_interval_seconds(self, setup=None):
        interval = float(self.button_poll_interval_seconds())
        active_setup = setup if setup is not None else self.load_setup()
        if self._encoder_rotation_assignments(active_setup):
            return min(interval, self.ENCODER_ACTIVE_POLL_INTERVAL_SECONDS)
        return interval

    def current_gpio_poll_interval_seconds(self, setup=None, now=None):
        interval = float(self.button_poll_interval_seconds())
        active_setup = setup if setup is not None else self.load_setup()
        if not self._encoder_rotation_assignments(active_setup):
            return interval
        current_now = time.monotonic() if now is None else float(now)
        if current_now < float(self._encoder_fast_poll_until or 0.0):
            return min(interval, self.ENCODER_ACTIVE_POLL_INTERVAL_SECONDS)
        if current_now < float(self._gpio_activity_until or 0.0):
            return min(interval, self.ENCODER_IDLE_POLL_INTERVAL_SECONDS)
        return min(interval, self.ENCODER_DEEP_IDLE_POLL_INTERVAL_SECONDS)

    def sound_path(self, sound_name):
        mapping = {
            "power_on": SOUNDS_DIR / "power_on.mp3",
            "power_off": SOUNDS_DIR / "power_off.mp3",
            "test": SOUNDS_DIR / "test.mp3",
        }
        return mapping.get(sound_name)

    @contextmanager
    def state_transaction(self):
        with self._state_lock:
            if self._state_lock_depth == 0:
                STATE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
                self._state_lock_handle = STATE_LOCK_FILE.open("a+", encoding="utf-8")
                fcntl.flock(self._state_lock_handle.fileno(), fcntl.LOCK_EX)
            self._state_lock_depth += 1
        try:
            yield
        finally:
            with self._state_lock:
                self._state_lock_depth = max(0, self._state_lock_depth - 1)
                if self._state_lock_depth == 0 and self._state_lock_handle is not None:
                    fcntl.flock(self._state_lock_handle.fileno(), fcntl.LOCK_UN)
                    self._state_lock_handle.close()
                    self._state_lock_handle = None

    def play_system_sound(self, sound_name):
        sound_path = self.sound_path(sound_name)
        if not sound_path:
            return {"ok": False, "details": [f"Unbekannter Sound: {sound_name}"]}
        player = self.load_player()
        volume = int(player.get("volume", 45) or 0)
        if player.get("muted"):
            volume = 0
        return self.playback.play_preview(sound_path, volume=volume)

    def volume_step(self):
        settings = self.load_settings()
        return int(settings.get("volume_step", 5) or 5)

    def sleep_button_rotation_enabled(self):
        settings = self.load_settings()
        return bool(settings.get("sleep_timer_button_rotation", False))

    def next_sleep_level_up(self, current_level):
        current_level = max(0, min(3, int(current_level or 0)))
        if current_level >= 3:
            return 0 if self.sleep_button_rotation_enabled() else 3
        return current_level + 1

    def _power_routine_options(self):
        return {
            "sleep_count_up_5": {"duration_seconds": 5.0, "animation": "sleep_count_up"},
            "sleep_count_up_3": {"duration_seconds": 3.0, "animation": "sleep_count_up"},
            "power_flicker_up_5": {"duration_seconds": 5.0, "animation": "power_flicker_up"},
            "power_flicker_up_3": {"duration_seconds": 3.0, "animation": "power_flicker_up"},
            "sleep_count_down_5": {"duration_seconds": 5.0, "animation": "sleep_count_down"},
            "sleep_count_down_3": {"duration_seconds": 3.0, "animation": "sleep_count_down"},
            "power_flicker_down_5": {"duration_seconds": 5.0, "animation": "power_flicker_down"},
            "power_flicker_down_3": {"duration_seconds": 3.0, "animation": "power_flicker_down"},
        }

    def _configured_power_routine(self, powered_on):
        setup = self.load_setup()
        routines = setup.get("power_routines", {})
        routine_id = (routines.get("power_off") if powered_on else routines.get("power_on")) or ""
        options = self._power_routine_options()
        if routine_id in options:
            return {"id": routine_id, **options[routine_id]}
        fallback = "sleep_count_down_5" if powered_on else "sleep_count_up_5"
        return {"id": fallback, **options[fallback]}

    def load_runtime(self):
        return load_json(self.runtime_path, default_runtime_state())

    def save_runtime(self, state):
        current = load_json(self.runtime_path, default_runtime_state())
        if current != state:
            save_json(self.runtime_path, state)

    def load_player(self):
        return merge_defaults(load_json(PLAYER_FILE, default_player()), default_player())

    def save_player(self, state):
        current = merge_defaults(load_json(PLAYER_FILE, default_player()), default_player())
        if current != state:
            save_json(PLAYER_FILE, state)

    def _current_boot_id(self):
        return current_boot_id()

    def _clear_playback_context(self, runtime_state, player, keep_loaded_media=False):
        runtime_state["playback_session"] = {}
        runtime_state["playback_state"] = "stopped"
        runtime_state["active_rfid_uid"] = ""
        runtime_state["hardware"]["last_scanned_uid"] = ""
        player["is_playing"] = False
        player["position_seconds"] = 0
        if keep_loaded_media:
            player["queued_tracks"] = []
            self._rebuild_queue_display(player)
            return runtime_state, player
        player.update(
            {
                "current_album": "",
                "current_track": "",
                "cover_url": "",
                "position_seconds": 0,
                "duration_seconds": 0,
                "playlist": "",
                "playlist_entries": [],
                "playlist_tracks": [],
                "current_track_index": 0,
                "queued_tracks": [],
                "queue": [],
            }
        )
        runtime_state["active_album_id"] = ""
        return runtime_state, player

    def _current_player_entry(self, player):
        entries = list(player.get("playlist_entries", []))
        if not entries:
            return "", 0
        current_index = max(0, min(len(entries) - 1, int(player.get("current_track_index", 0) or 0)))
        return entries[current_index], current_index

    def _track_metadata_for_entry(self, player, entry):
        for item in player.get("playlist_tracks", []) or []:
            if str(item.get("path", "") or "") == str(entry):
                return dict(item)
        return {}

    def _track_title_for_entry(self, player, entry):
        metadata = self._track_metadata_for_entry(player, entry)
        return str(metadata.get("title", "") or track_title_from_entry(entry))

    def _track_duration_for_entry(self, player, playlist, entry):
        metadata = self._track_metadata_for_entry(player, entry)
        duration = int(metadata.get("duration_seconds", 0) or 0)
        if duration > 0:
            return duration
        return pick_track_duration(playlist, entry)

    def _ordered_album_tracks(self, album, entries):
        track_map = {
            str(item.get("path", "") or ""): dict(item)
            for item in (album.get("tracks", []) or [])
            if isinstance(item, dict)
        }
        ordered = []
        for entry in entries:
            metadata = dict(track_map.get(entry, {}))
            metadata["path"] = entry
            metadata["title"] = str(metadata.get("title", "") or track_title_from_entry(entry))
            if int(metadata.get("duration_seconds", 0) or 0) <= 0:
                metadata["duration_seconds"] = pick_track_duration(album.get("playlist", ""), entry)
            ordered.append(metadata)
        return ordered

    def _reopen_current_track_session(self, runtime_state, player, autoplay=False):
        entry, current_index = self._current_player_entry(player)
        playlist = player.get("playlist", "")
        if not playlist or not entry:
            return runtime_state, player, False
        runtime_state["playback_session"] = self.playback.open_track(
            playlist,
            entry,
            0,
            volume=player.get("volume", 45),
            previous_session=runtime_state.get("playback_session", {}),
            current_index=current_index,
            entries=list(player.get("playlist_entries", [])),
        )
        runtime_state["playback_state"] = "playing" if autoplay else "paused"
        if runtime_state["playback_session"]:
            runtime_state["playback_session"] = (
                self.playback.play(runtime_state["playback_session"])
                if autoplay
                else self.playback.pause(runtime_state["playback_session"])
            )
        player["is_playing"] = bool(autoplay)
        player["position_seconds"] = 0
        self._rebuild_queue_display(player)
        return runtime_state, player, True

    def _apply_boot_recovery(self, runtime_state, player):
        system_state = merge_defaults(runtime_state.get("system", {}), default_runtime_state()["system"])
        stored_boot_id = str(system_state.get("boot_id", "") or "")
        current_id = self._current_boot_id()
        runtime_state["system"] = system_state
        if current_id and stored_boot_id == current_id:
            return runtime_state, player, False
        runtime_state["system"]["boot_id"] = current_id
        runtime_state["system"]["last_boot_recovery_at"] = int(time.time())
        runtime_state["powered_on"] = True
        runtime_state, player = self._clear_playback_context(runtime_state, player, keep_loaded_media=False)
        runtime_state["wifi_enabled"] = True
        runtime_state["wifi_auto_off_started_at"] = int(time.time())
        runtime_state["sleep_timer"]["remaining_seconds"] = 0
        runtime_state["sleep_timer"]["level"] = 0
        runtime_state["power_hold"] = merge_defaults({}, default_runtime_state()["power_hold"])
        runtime_state = self.add_event(runtime_state, "Sicherer Neustartzustand hergestellt", mark_activity=False)
        return runtime_state, player, True

    def load_library(self):
        return load_json(LIBRARY_FILE, {"albums": []})

    def load_settings(self):
        try:
            stat = SETTINGS_FILE.stat()
            current_stat = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            current_stat = (-1, -1)
        now = time.monotonic()
        if (
            self._settings_cache is not None
            and self._settings_cache_stat == current_stat
            and (now - self._settings_cached_at) < self.SETTINGS_CACHE_TTL_SECONDS
        ):
            return self._settings_cache
        self._settings_cache = load_json(SETTINGS_FILE, {})
        self._settings_cached_at = now
        self._settings_cache_stat = current_stat
        return self._settings_cache

    def load_setup(self):
        try:
            stat = SETUP_FILE.stat()
            current_stat = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            current_stat = (-1, -1)
        now = time.monotonic()
        if (
            self._setup_cache is not None
            and self._setup_cache_stat == current_stat
            and (now - self._setup_cached_at) < self.SETUP_CACHE_TTL_SECONDS
        ):
            return self._setup_cache
        self._setup_cache = load_json(SETUP_FILE, {})
        self._setup_cached_at = now
        self._setup_cache_stat = current_stat
        self._button_poll_config_cache = None
        self._button_poll_config_cache_key = None
        return self._setup_cache

    def load_button_detect(self):
        return merge_defaults(load_json(BUTTON_DETECT_FILE, default_button_detect()), default_button_detect())

    def button_long_press_seconds(self):
        setup = self.load_setup()
        try:
            value = float(str(setup.get("button_long_press_seconds", 2)).strip().replace(",", "."))
        except (TypeError, ValueError):
            value = 2.0
        return max(1.0, min(10.0, value))

    def hardware_buttons_enabled(self):
        setup = self.load_setup()
        return bool(setup.get("hardware_buttons_enabled", True))

    def classify_press_type(self, held_seconds=None, fallback="kurz"):
        if held_seconds is None:
            return fallback
        try:
            duration = float(held_seconds)
        except (TypeError, ValueError):
            return fallback
        return "lang" if duration >= float(self.button_long_press_seconds()) else "kurz"

    def _gpio_name_to_bcm(self, gpio_name):
        if not gpio_name or not str(gpio_name).startswith("GPIO"):
            return None
        try:
            return int(str(gpio_name).replace("GPIO", "", 1))
        except ValueError:
            return None

    def gpio_polling_available(self):
        return GPIO is not None or sysfs_gpio_available() or bool(sample_gpio_levels_pinctrl(["GPIO4"]))

    def _ensure_gpio_inputs(self, gpio_names):
        gpio_names = {name for name in gpio_names if name}
        if not gpio_names or not self.gpio_polling_available():
            return False
        if self._gpio_backend in {None, "rpi"} and GPIO is not None:
            try:
                if not self._gpio_ready:
                    GPIO.setwarnings(False)
                    GPIO.setmode(GPIO.BCM)
                    self._gpio_ready = True
                    self._gpio_backend = "rpi"

                target_bcm = set()
                for gpio_name in gpio_names:
                    bcm = self._gpio_name_to_bcm(gpio_name)
                    if bcm is None:
                        continue
                    target_bcm.add(bcm)
                    if bcm in self._idle_low_gpio_pins:
                        try:
                            GPIO.cleanup(bcm)
                        except Exception:
                            pass
                        self._idle_low_gpio_pins.discard(bcm)
                    if bcm not in self._configured_gpio_pins:
                        GPIO.setup(bcm, GPIO.IN, pull_up_down=GPIO.PUD_UP)

                for bcm in sorted(self._configured_gpio_pins - target_bcm):
                    try:
                        GPIO.cleanup(bcm)
                    except Exception:
                        continue

                self._configured_gpio_pins = target_bcm
                return bool(self._configured_gpio_pins)
            except Exception:
                self._gpio_ready = False
                self._gpio_backend = "sysfs"
                self._configured_gpio_pins = set()

        if self._gpio_backend in {None, "sysfs"} and sysfs_gpio_available():
            self._gpio_backend = "sysfs"
            ready = False
            for gpio_name in gpio_names:
                ready = self._sysfs_gpio.ensure_input(gpio_name) or ready
            if ready:
                return True

        pinctrl_sample = sample_gpio_levels_pinctrl(gpio_names)
        if pinctrl_sample:
            self._gpio_backend = "pinctrl"
            return True

        return False

    def _available_idle_low_pins(self, setup):
        assigned_button_pins = {button.get("pin", "").strip() for button in setup.get("buttons", []) if button.get("pin", "").strip()}
        assigned_led_pins = {led.get("pin", "").strip() for led in setup.get("leds", []) if led.get("pin", "").strip()}
        preview = load_json(LED_PREVIEW_FILE, {})
        preview_pin = ""
        if isinstance(preview, dict) and preview.get("status") == "pending":
            preview_pin = str(preview.get("pin", "")).strip()
        detect = self.load_button_detect()
        detect_pins = set()
        if detect.get("active"):
            detect_pins = {str(pin).strip() for pin in detect.get("candidate_pins", []) if str(pin).strip()}
        blocked = potential_system_pins() | assigned_button_pins | assigned_led_pins | detect_pins | ({preview_pin} if preview_pin else set())
        return sorted(gpio_name for gpio_name in GPIO_TO_BOARD_PIN if gpio_name not in blocked)

    def _sync_idle_low_outputs(self, setup):
        if GPIO is None:
            return
        try:
            if not self._gpio_ready:
                GPIO.setwarnings(False)
                GPIO.setmode(GPIO.BCM)
                self._gpio_ready = True
                self._gpio_backend = "rpi"
        except Exception:
            self._gpio_ready = False
            return

        target_bcm = set()
        for gpio_name in self._available_idle_low_pins(setup):
            bcm = self._gpio_name_to_bcm(gpio_name)
            if bcm is None or bcm in self._configured_gpio_pins:
                continue
            target_bcm.add(bcm)
            if bcm in self._idle_low_gpio_pins:
                continue
            try:
                GPIO.setup(bcm, GPIO.OUT, initial=GPIO.LOW)
                GPIO.output(bcm, GPIO.LOW)
            except Exception:
                target_bcm.discard(bcm)
                continue

        for bcm in sorted(self._idle_low_gpio_pins - target_bcm):
            try:
                GPIO.cleanup(bcm)
            except Exception:
                continue

        self._idle_low_gpio_pins = target_bcm

    def _release_idle_low_outputs(self):
        if GPIO is None:
            return
        for bcm in sorted(self._idle_low_gpio_pins):
            try:
                GPIO.cleanup(bcm)
            except Exception:
                continue
        self._idle_low_gpio_pins.clear()

    def _release_unassigned_gpio_inputs(self, setup):
        if GPIO is None or not self._configured_gpio_pins:
            return
        assigned_button_bcms = {
            bcm
            for bcm in (self._gpio_name_to_bcm(button.get("pin", "").strip()) for button in setup.get("buttons", []))
            if bcm is not None
        }
        stale_bcms = sorted(self._configured_gpio_pins - assigned_button_bcms)
        for bcm in stale_bcms:
            try:
                GPIO.cleanup(bcm)
            except Exception:
                continue
            self._configured_gpio_pins.discard(bcm)

    def _read_gpio_levels(self, gpio_names):
        if not self._ensure_gpio_inputs(gpio_names):
            return {}
        if self._gpio_backend == "sysfs":
            levels = self._sysfs_gpio.sample(gpio_names)
            if levels:
                return levels
            return sample_gpio_levels_pinctrl(gpio_names)
        if self._gpio_backend == "pinctrl":
            return sample_gpio_levels_pinctrl(gpio_names)
        levels = {}
        for gpio_name in gpio_names:
            bcm = self._gpio_name_to_bcm(gpio_name)
            if bcm is None:
                continue
            try:
                levels[gpio_name] = int(GPIO.input(bcm))
            except RuntimeError:
                continue
        if levels:
            return levels
        return sample_gpio_levels_pinctrl(gpio_names)

    def _set_pressed_buttons(self, pins):
        pins = sorted([pin for pin in pins if pin])
        runtime_state = self.ensure_runtime()
        current = sorted([pin for pin in runtime_state.get("hardware", {}).get("pressed_buttons", []) if pin])
        if pins == self._last_pressed_pins and pins == current:
            return
        runtime_state["hardware"]["pressed_buttons"] = pins
        self.save_runtime(runtime_state)
        self._last_pressed_pins = pins

    def _append_encoder_debug_sample(self, setup, slot, clk_level, dt_level, direction="", action_name=""):
        runtime_state = self.ensure_runtime()
        modules = self._encoder_module_map(setup)
        module = modules.get(slot, {})
        samples = list(runtime_state.get("hardware", {}).get("encoder_debug", []) or [])
        samples.insert(
            0,
            {
                "slot": slot,
                "label": module.get("label", slot) if module else slot,
                "clk": int(clk_level),
                "dt": int(dt_level),
                "direction": direction,
                "action": action_name,
                "at": int(time.time()),
            },
        )
        runtime_state["hardware"]["encoder_debug"] = samples[:20]
        self.save_runtime(runtime_state)

    def _encoder_state_value(self, clk_level, dt_level):
        return ((int(clk_level) & 1) << 1) | (int(dt_level) & 1)

    def _encoder_transition_delta(self, previous_state, current_state):
        transition = (int(previous_state), int(current_state))
        if transition in self.ENCODER_CLOCKWISE_TRANSITIONS:
            return 1
        if transition in self.ENCODER_COUNTERCLOCKWISE_TRANSITIONS:
            return -1
        return 0

    def _button_mapping_for_pin(self, setup, pin, press_type):
        for button in setup.get("buttons", []):
            if button.get("pin", "").strip() != pin:
                continue
            if (button.get("input_mode") or "").strip() == "encoder":
                continue
            if button.get("press_type", "kurz") != press_type:
                continue
            return button.get("name", "")
        modules = self._encoder_module_map(setup)
        for button in setup.get("buttons", []):
            if (button.get("input_mode") or "").strip() != "encoder":
                continue
            if (button.get("encoder_event") or "press").strip() != "press":
                continue
            slot = (button.get("encoder_slot") or "").strip()
            module = modules.get(slot, {})
            if module.get("sw_pin", "").strip() != pin:
                continue
            if button.get("press_type", "kurz") != press_type:
                continue
            return button.get("name", "")
        return ""

    def _button_active_level(self, setup, pin):
        configured = 0
        per_pin = setup.get("button_active_levels", {})
        if isinstance(per_pin, dict):
            configured = per_pin.get(pin, configured)
        configured = setup.get("button_active_level", configured)
        normalized = str(configured).strip().lower()
        return 1 if normalized in {"1", "high", "true"} else 0

    def _is_power_hold_pin(self, setup, pin):
        mapped = self._button_mapping_for_pin(setup, pin, "lang")
        return mapped.strip().lower() in {"power on/off", "sleep/power"}

    def _encoder_module_map(self, setup):
        modules = {}
        for module in setup.get("encoder_modules", []) or []:
            slot = (module.get("id") or "").strip()
            if not slot:
                continue
            modules[slot] = {
                "label": (module.get("label") or slot).strip(),
                "clk_pin": (module.get("clk_pin") or "").strip(),
                "dt_pin": (module.get("dt_pin") or "").strip(),
                "sw_pin": (module.get("sw_pin") or "").strip(),
            }
        return modules

    def _encoder_rotation_assignments(self, setup):
        assignments = {}
        for button in setup.get("buttons", []):
            if (button.get("input_mode") or "").strip() != "encoder":
                continue
            event = (button.get("encoder_event") or "press").strip()
            if event not in self.ENCODER_ROTATION_EVENTS:
                continue
            slot = (button.get("encoder_slot") or "").strip()
            if not slot:
                continue
            assignments.setdefault(slot, {})[event] = button.get("name", "")
        return assignments

    def _button_poll_config(self, setup):
        cache_key = id(setup)
        if self._button_poll_config_cache_key == cache_key and self._button_poll_config_cache is not None:
            return self._button_poll_config_cache

        encoder_modules = self._encoder_module_map(setup)
        encoder_assignments = self._encoder_rotation_assignments(setup)
        encoder_press_pins = {
            module.get("sw_pin", "").strip()
            for module in encoder_modules.values()
            if module.get("sw_pin", "").strip()
        }
        normal_button_pins = {
            button.get("pin", "").strip()
            for button in setup.get("buttons", [])
            if button.get("pin", "").strip() and (button.get("input_mode") or "").strip() != "encoder"
        }
        encoder_rotation_pins = {
            pin
            for module in encoder_modules.values()
            for pin in (module.get("clk_pin", "").strip(), module.get("dt_pin", "").strip())
            if pin
        }
        config = {
            "encoder_modules": encoder_modules,
            "encoder_assignments": encoder_assignments,
            "configured_pins": sorted(
                filter_reserved_gpio_names(
                    normal_button_pins | encoder_press_pins | encoder_rotation_pins,
                    setup,
                )
            ),
            "active_button_pins": set(filter_reserved_gpio_names(normal_button_pins | encoder_press_pins, setup)),
        }
        self._button_poll_config_cache_key = cache_key
        self._button_poll_config_cache = config
        return config

    def _poll_encoder_rotations(self, setup, levels, now, modules=None, assignments=None):
        modules = modules if modules is not None else self._encoder_module_map(setup)
        assignments = assignments if assignments is not None else self._encoder_rotation_assignments(setup)
        active_slots = set(assignments)
        for slot in list(self._encoder_poll_state):
            if slot not in active_slots:
                self._encoder_poll_state.pop(slot, None)

        for slot, slot_assignments in assignments.items():
            module = modules.get(slot, {})
            clk_pin = module.get("clk_pin", "")
            dt_pin = module.get("dt_pin", "")
            if not clk_pin or not dt_pin:
                continue
            if clk_pin not in levels or dt_pin not in levels:
                continue
            clk_level = int(levels[clk_pin])
            dt_level = int(levels[dt_pin])
            current_state = self._encoder_state_value(clk_level, dt_level)
            state = self._encoder_poll_state.setdefault(
                slot,
                {
                    "state": current_state,
                    "accumulator": 0,
                    "last_direction": 0,
                    "last_transition_at": 0.0,
                },
            )
            previous_state = state.get("state")
            if previous_state is None:
                state["state"] = current_state
                continue
            if current_state == previous_state:
                continue
            if now - float(state.get("last_transition_at", 0.0) or 0.0) < self.ENCODER_TRANSITION_DEBOUNCE_SECONDS:
                continue

            step_delta = self._encoder_transition_delta(previous_state, current_state)
            state["state"] = current_state
            self._encoder_fast_poll_until = max(self._encoder_fast_poll_until, now + self.ENCODER_ACTIVE_HOLD_SECONDS)
            self._gpio_activity_until = max(self._gpio_activity_until, now + self.GPIO_ACTIVITY_HOLD_SECONDS)
            if step_delta == 0:
                state["accumulator"] = 0
                state["last_direction"] = 0
                self._append_encoder_debug_sample(setup, slot, clk_level, dt_level, direction="invalid", action_name="")
                continue

            state["last_transition_at"] = now
            if state.get("last_direction") and step_delta != state.get("last_direction"):
                state["accumulator"] = step_delta
            else:
                state["accumulator"] = int(state.get("accumulator", 0) or 0) + step_delta
            state["last_direction"] = step_delta

            direction = "cw" if step_delta > 0 else "ccw"
            action_name = slot_assignments.get(direction, "").strip()
            if state["accumulator"] >= self.ENCODER_STEPS_PER_EVENT:
                state["accumulator"] -= self.ENCODER_STEPS_PER_EVENT
                self._append_encoder_debug_sample(setup, slot, clk_level, dt_level, direction="cw", action_name=action_name)
                if action_name:
                    self.trigger_button(action_name, press_type="kurz")
            elif state["accumulator"] <= -self.ENCODER_STEPS_PER_EVENT:
                state["accumulator"] += self.ENCODER_STEPS_PER_EVENT
                self._append_encoder_debug_sample(setup, slot, clk_level, dt_level, direction="ccw", action_name=action_name)
                if action_name:
                    self.trigger_button(action_name, press_type="kurz")

    def _update_power_hold_state(self, runtime_state, pin, now, released=False):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            hold = runtime_state.get("power_hold", {})
            if not hold.get("pressed") and not released:
                live_powered_on = bool(runtime_state.get("powered_on", True))
                routine = self._configured_power_routine(live_powered_on)
                mode = "pending_off" if live_powered_on else "pending_on"
                hold.update(
                    {
                        "pressed": True,
                        "seconds": 0.0,
                        "mode": mode,
                        "pin": pin,
                        "started_at": now,
                        "trigger_seconds": float(self.button_long_press_seconds()),
                        "threshold_seconds": float(routine["duration_seconds"]),
                        "routine_id": routine["id"],
                        "animation": routine["animation"],
                        "completed": False,
                    }
                )
            elif hold.get("pressed") and not released:
                hold["seconds"] = max(0.0, now - float(hold.get("started_at", now)))
                if not hold.get("completed") and hold.get("seconds", 0.0) >= float(hold.get("threshold_seconds", 0.0) or 0.0):
                    completed_hold = dict(hold)
                    target_power_on = completed_hold.get("mode") == "pending_on"
                    if target_power_on:
                        result = self.power_on(runtime_state=runtime_state, player=self.load_player())
                    else:
                        result = self.power_off(runtime_state=runtime_state, player=self.load_player())
                    runtime_state = result["runtime"]
                    completed_hold.update(
                        {
                            "pressed": True,
                            "seconds": float(completed_hold.get("threshold_seconds", 0.0) or 0.0),
                            "pin": pin,
                            "started_at": now - float(completed_hold.get("threshold_seconds", 0.0) or 0.0),
                            "completed": True,
                        }
                    )
                    hold = completed_hold
            if released:
                if hold.get("pressed"):
                    hold["seconds"] = max(0.0, now - float(hold.get("started_at", now)))
                    trigger_seconds = max(0.0, float(hold.get("trigger_seconds", self.button_long_press_seconds()) or self.button_long_press_seconds()))
                    threshold_seconds = max(trigger_seconds, float(hold.get("threshold_seconds", trigger_seconds) or trigger_seconds))
                    # In der letzten Sekunde der Routine darf losgelassen werden.
                    release_ready_seconds = max(trigger_seconds, threshold_seconds - 1.0)
                    if not hold.get("completed") and hold.get("seconds", 0.0) >= release_ready_seconds:
                        target_power_on = hold.get("mode") == "pending_on"
                        if target_power_on:
                            result = self.power_on(runtime_state=runtime_state, player=self.load_player())
                        else:
                            result = self.power_off(runtime_state=runtime_state, player=self.load_player())
                        runtime_state = result["runtime"]
                runtime_state["power_hold"] = merge_defaults({}, default_runtime_state()["power_hold"])
            else:
                runtime_state["power_hold"] = hold
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            return runtime_state

    def _poll_button_detection(self, session, now):
        candidates = [pin for pin in session.get("candidate_pins", []) if pin]
        levels = self._read_gpio_levels(candidates)
        if not levels:
            session["active"] = False
            session["status"] = "unavailable"
            session["message"] = "Keine GPIO-Tasterkennung verfügbar."
            save_json(BUTTON_DETECT_FILE, session)
            self._set_pressed_buttons([])
            return

        baseline = session.get("baseline", {})
        pressed_now = [pin for pin, value in levels.items() if int(value) == 0]
        self._set_pressed_buttons(pressed_now)

        if now >= float(session.get("deadline_at", 0)):
            session["active"] = False
            session["status"] = "timeout"
            session["message"] = "Keine Taste erkannt."
            session["remaining_seconds"] = 0
            save_json(BUTTON_DETECT_FILE, session)
            self._set_pressed_buttons([])
            return

        for gpio_name in candidates:
            if gpio_name not in levels or gpio_name not in baseline:
                continue
            if int(levels[gpio_name]) != int(baseline[gpio_name]):
                session["active"] = False
                session["status"] = "detected"
                session["detected_gpio"] = gpio_name
                session["detected_pin"] = str(GPIO_TO_BOARD_PIN.get(gpio_name, ""))
                session["message"] = gpio_display_label(gpio_name)
                session["remaining_seconds"] = 0
                save_json(BUTTON_DETECT_FILE, session)
                self._set_pressed_buttons([gpio_name] if int(levels[gpio_name]) == 0 else [])
                return

    def poll_buttons_once(self, now=None):
        button_now = float(now if now is not None else time.monotonic())
        detect_now = float(now if now is not None else time.time())
        long_press_threshold = float(self.button_long_press_seconds())
        setup = self.load_setup()
        detect_state = self.load_button_detect()
        if detect_state.get("active"):
            self._release_idle_low_outputs()
            self._poll_button_detection(detect_state, detect_now)
            detect_state = self.load_button_detect()
            if detect_state.get("active"):
                return
        self._release_unassigned_gpio_inputs(setup)
        self._sync_idle_low_outputs(setup)

        if not bool(setup.get("hardware_buttons_enabled", True)):
            self._set_pressed_buttons([])
            self._button_poll_state.clear()
            runtime_state = self.ensure_runtime()
            if runtime_state.get("power_hold", {}).get("pressed"):
                runtime_state["power_hold"] = merge_defaults({}, default_runtime_state()["power_hold"])
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
            return

        poll_config = self._button_poll_config(setup)
        configured_pins = poll_config.get("configured_pins", [])
        levels = self._read_gpio_levels(configured_pins)
        if not configured_pins or not levels:
            self._set_pressed_buttons([])
            return

        active_button_pins = set(poll_config.get("active_button_pins", set()))
        for pin in list(self._button_poll_state):
            if pin not in active_button_pins:
                self._button_poll_state.pop(pin, None)

        pressed_now = []
        for pin in active_button_pins:
            level = levels.get(pin)
            if level is None:
                continue
            state = self._button_poll_state.setdefault(pin, {"pressed": False, "pressed_at": 0.0, "long_triggered": False})
            is_pressed = int(level) == self._button_active_level(setup, pin)
            if is_pressed:
                pressed_now.append(pin)
        if pressed_now:
            self._gpio_activity_until = max(self._gpio_activity_until, button_now + self.GPIO_ACTIVITY_HOLD_SECONDS)
        self._set_pressed_buttons(pressed_now)

        for pin in active_button_pins:
            level = levels.get(pin)
            if level is None:
                continue
            state = self._button_poll_state.setdefault(pin, {"pressed": False, "pressed_at": 0.0, "long_triggered": False})
            is_pressed = int(level) == self._button_active_level(setup, pin)
            if is_pressed and not state["pressed"]:
                state["pressed"] = True
                state["pressed_at"] = button_now
                state["long_triggered"] = False
                self._gpio_activity_until = max(self._gpio_activity_until, button_now + self.GPIO_ACTIVITY_HOLD_SECONDS)
                if self._is_power_hold_pin(setup, pin):
                    runtime_state = self.ensure_runtime()
                    self._update_power_hold_state(runtime_state, pin, button_now, released=False)
                continue
            if is_pressed:
                held_seconds = max(0.0, button_now - float(state.get("pressed_at", button_now)))
                if self._is_power_hold_pin(setup, pin):
                    runtime_state = self.ensure_runtime()
                    self._update_power_hold_state(runtime_state, pin, button_now, released=False)
                    runtime_state = self.ensure_runtime()
                    hold_state = runtime_state.get("power_hold", {})
                    trigger_seconds = float(hold_state.get("trigger_seconds", long_press_threshold) or long_press_threshold)
                    if hold_state.get("completed") or held_seconds >= trigger_seconds:
                        state["long_triggered"] = True
                elif (not state.get("long_triggered", False)) and held_seconds >= long_press_threshold:
                    if self._button_mapping_for_pin(setup, pin, "lang"):
                        self.trigger_gpio_pin(pin, press_type="lang", held_seconds=held_seconds)
                    state["long_triggered"] = True
                continue
            if not state["pressed"]:
                continue

            held_seconds = max(0.0, button_now - float(state.get("pressed_at", button_now)))
            state["pressed"] = False
            state["pressed_at"] = 0.0
            self._gpio_activity_until = max(self._gpio_activity_until, button_now + self.GPIO_ACTIVITY_HOLD_SECONDS)
            if self._is_power_hold_pin(setup, pin):
                runtime_state = self.ensure_runtime()
                hold_was_completed = bool(runtime_state.get("power_hold", {}).get("completed"))
                self._update_power_hold_state(runtime_state, pin, button_now, released=True)
                if (not hold_was_completed) and held_seconds < long_press_threshold and self._button_mapping_for_pin(setup, pin, "kurz"):
                    self.trigger_gpio_pin(pin, press_type="kurz", held_seconds=held_seconds)
                state["long_triggered"] = False
                continue
            if held_seconds < 0.03:
                state["long_triggered"] = False
                continue
            if state.get("long_triggered", False):
                state["long_triggered"] = False
                continue
            if not self._button_mapping_for_pin(setup, pin, "kurz"):
                state["long_triggered"] = False
                continue
            self.trigger_gpio_pin(pin, press_type="kurz", held_seconds=held_seconds)
            state["long_triggered"] = False
        self._poll_encoder_rotations(
            setup,
            levels,
            button_now,
            modules=poll_config.get("encoder_modules"),
            assignments=poll_config.get("encoder_assignments"),
        )

    def poll_buttons_forever(self, interval_seconds=None):
        while True:
            try:
                self.poll_buttons_once()
            except Exception:
                fallback_interval = (
                    float(interval_seconds)
                    if interval_seconds is not None
                    else self.current_gpio_poll_interval_seconds()
                )
                time.sleep(max(0.1, fallback_interval))
                continue
            current_interval = (
                float(interval_seconds)
                if interval_seconds is not None
                else self.current_gpio_poll_interval_seconds()
            )
            time.sleep(max(0.001, current_interval))

    def ensure_runtime(self):
        defaults = default_runtime_state()
        if not self.runtime_path.exists():
            self.save_runtime(defaults)
            return defaults
        current = self.load_runtime()
        merged = merge_defaults(current, defaults)
        player = None
        changed = merged != current
        if not self._boot_recovery_checked:
            player = self.load_player()
            merged, player, boot_changed = self._apply_boot_recovery(merged, player)
            changed = changed or boot_changed
            self._boot_recovery_checked = True
        if changed:
            self.save_runtime(merged)
            if player is not None:
                self.save_player(player)
        return merged

    def add_event(self, runtime_state, message, level="info", mark_activity=True):
        runtime_state["last_event"] = message
        runtime_state["last_event_at"] = int(time.time())
        if mark_activity:
            runtime_state["last_activity_at"] = runtime_state["last_event_at"]
        event_log = list(runtime_state.get("event_log", []))
        event_log.insert(0, {"message": message, "level": level, "at": runtime_state["last_event_at"]})
        runtime_state["event_log"] = event_log[:20]
        return runtime_state

    def _power_routine_settings(self):
        setup = self.load_setup()
        return dict((setup.get("power_routines") or {}))

    def _should_play_power_sound(self, target_powered_on, reason):
        routines = self._power_routine_settings()
        if target_powered_on:
            return bool(routines.get("startup_sound_enabled", True))
        if not bool(routines.get("shutdown_sound_enabled", True)):
            return False
        if reason == "sleep_timer":
            return bool(routines.get("play_shutdown_sound_for_sleep_timer", False))
        if reason == "inactivity":
            return bool(routines.get("play_shutdown_sound_for_inactivity", False))
        return True

    def _auto_standby_config(self):
        routines = self._power_routine_settings()
        enabled = bool(routines.get("auto_standby_enabled", False))
        minutes = max(1, int(routines.get("auto_standby_minutes", 30) or 30))
        return {"enabled": enabled, "minutes": minutes}

    def _auto_wifi_off_config(self):
        setup = self.load_setup()
        wifi = setup.get("wifi") or {}
        enabled = bool(wifi.get("auto_wifi_off_enabled", False))
        minutes = max(1, int(wifi.get("auto_wifi_off_minutes", 30) or 30))
        return {"enabled": enabled, "minutes": minutes}

    def _apply_inactivity_wifi_off(self, runtime_state, player):
        config = self._auto_wifi_off_config()
        if not config["enabled"] or not runtime_state.get("powered_on", True):
            return runtime_state, player
        if not bool(runtime_state.get("wifi_enabled", True)):
            return runtime_state, player

        now = int(time.time())
        started_at = int(runtime_state.get("wifi_auto_off_started_at", 0) or 0)
        if started_at <= 0:
            runtime_state["wifi_auto_off_started_at"] = now
            return runtime_state, player
        threshold_seconds = int(config["minutes"]) * 60
        if now - started_at < threshold_seconds:
            return runtime_state, player

        runtime_state["wifi_enabled"] = False
        runtime_state = self.add_event(runtime_state, f"WiFi automatisch aus nach {config['minutes']} Min", mark_activity=False)
        return runtime_state, player

    def _apply_inactivity_standby(self, runtime_state, player):
        config = self._auto_standby_config()
        if not config["enabled"] or not runtime_state.get("powered_on", True):
            return runtime_state, player
        if runtime_state.get("playback_state") == "playing":
            return runtime_state, player
        if int(runtime_state.get("sleep_timer", {}).get("remaining_seconds", 0) or 0) > 0:
            return runtime_state, player

        now = int(time.time())
        last_activity_at = int(runtime_state.get("last_activity_at", runtime_state.get("last_event_at", now)) or now)
        threshold_seconds = int(config["minutes"]) * 60
        if now - last_activity_at < threshold_seconds:
            return runtime_state, player

        result = self.power_off(
            runtime_state=runtime_state,
            player=player,
            event_message=f"Inaktiv seit {config['minutes']} Min, Standby aktiv",
            reason="inactivity",
        )
        return result["runtime"], result["player"]

    def get_reader_behavior(self):
        settings = self.load_settings()
        return {
            "read": settings.get("rfid_read_action", "play"),
            "remove": settings.get("rfid_remove_action", "stop"),
        }

    def _desired_wifi_state(self, runtime_state):
        return bool(runtime_state.get("powered_on", True)) and bool(runtime_state.get("wifi_enabled", True))

    def _set_service_active(self, service_name, active):
        try:
            subprocess.run(
                ["systemctl", "start" if active else "stop", service_name],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return False
        return True

    def apply_wifi_policy(self, runtime_state):
        desired = self._desired_wifi_state(runtime_state)
        runtime_state["wifi_enabled"] = bool(desired)
        current_enabled = bool(runtime_state.get("hardware", {}).get("wifi_enabled", self._wifi_enabled_cache))
        cache_age = time.monotonic() - float(self._wifi_enabled_cached_at or 0.0)
        if cache_age < self.WIFI_STATE_TTL_SECONDS:
            current_enabled = bool(self._wifi_enabled_cache)
        else:
            current_enabled = self._wifi_radio_enabled_cached(force_refresh=True)
        if current_enabled == bool(desired):
            runtime_state["hardware"]["wifi_enabled"] = current_enabled
            return runtime_state

        result = run_wifi_state_command(desired)
        if result.get("ok"):
            self._wifi_enabled_cache = bool(desired)
            self._wifi_enabled_cached_at = time.monotonic()
            runtime_state["hardware"]["wifi_enabled"] = bool(desired)
        else:
            runtime_state["hardware"]["wifi_enabled"] = self._wifi_radio_enabled_cached(force_refresh=True)
        return runtime_state

    def toggle_wifi(self):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            if not runtime_state.get("powered_on", True):
                runtime_state["wifi_enabled"] = False
                runtime_state = self.add_event(runtime_state, "Wifi im Standby nicht verfügbar", "warning")
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                return {"runtime": runtime_state, "player": self.load_player()}
            current_enabled = bool(runtime_state.get("wifi_enabled", True))
            runtime_state["wifi_enabled"] = not current_enabled
            runtime_state = self.add_event(runtime_state, "Wifi an" if runtime_state["wifi_enabled"] else "Wifi aus")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            return {"runtime": runtime_state, "player": self.load_player()}

    def update_hardware_profile(self, runtime_state):
        now = time.monotonic()
        profile = self._hardware_profile_cache
        if profile is None or (now - self._hardware_profile_cached_at) >= self.HARDWARE_PROFILE_TTL_SECONDS:
            setup = self.load_setup()
            library = self.load_library()
            profile = detect_hardware(setup, library)
            self._hardware_profile_cache = profile
            self._hardware_profile_cached_at = now
        runtime_state["hardware"]["profile"] = profile
        runtime_state["hardware"]["profile"]["audio"]["playback_backend"] = self.playback.status()["active_backend"]
        runtime_state["hardware"]["reader_type"] = runtime_state["hardware"]["profile"]["reader"].get("configured_type", "USB")
        runtime_state["hardware"]["reader_connected"] = runtime_state["hardware"]["profile"]["reader"].get("ready", False)
        runtime_state["hardware"]["wifi_enabled"] = self._wifi_radio_enabled_cached()
        return runtime_state

    def player_snapshot(self):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state = self._refresh_sleep_step(runtime_state)
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            return {
                "runtime": runtime_state,
                "player": player,
                "settings": self.load_settings(),
                "performance": self.performance_profile(),
            }

    def update_led_status(self, runtime_state):
        setup = self.load_setup()
        led_tuning = dict(setup.get("led_tuning") or {})
        reserved = reserved_system_pins(setup)
        leds = setup.get("leds", [])
        sleep_level = runtime_state.get("sleep_timer", {}).get("level", 0)
        powered_on = runtime_state.get("powered_on", True)
        playback_state = runtime_state.get("playback_state", "paused")
        led_status = []
        power_hold = runtime_state.get("power_hold", {})
        override = self._build_power_hold_led_override(runtime_state, leds) if power_hold.get("pressed") else {}
        effect_override = self._build_power_hold_led_effects(runtime_state) if power_hold.get("pressed") else {}
        wifi_active = bool(runtime_state.get("hardware", {}).get("wifi_enabled", runtime_state.get("wifi_enabled", True)))
        wifi_led_pins = {
            (led.get("pin") or "").strip()
            for led in leds
            if (led.get("function") or "").strip() == "wifi_on"
        }
        active_wifi_led_pins = {pin for pin in wifi_led_pins if pin and wifi_active}
        for led in leds:
            if led.get("pin", "").strip() in reserved:
                continue
            pin = (led.get("pin") or "").strip()
            function = led.get("function", "")
            if pin and function != "wifi_on" and pin in active_wifi_led_pins:
                is_on = False
                effect = ""
                effect_progress = None
                led_status.append(
                    {
                        "id": led.get("id", ""),
                        "name": led.get("name", "LED"),
                        "pin": led.get("pin", ""),
                        "brightness": led.get("brightness", 0),
                        "pwm_frequency_hz": led_tuning.get("pwm_frequency_hz", 800),
                        "brightness_gamma": led_tuning.get("brightness_gamma", 1.0),
                        "update_rate_ms": led_tuning.get("update_rate_ms", 70),
                        "is_on": is_on,
                        "effect": effect,
                        "effect_progress": effect_progress,
                    }
                )
                continue
            is_on = False
            if function == "power_on":
                is_on = powered_on
            elif function == "standby":
                is_on = not powered_on
            elif function == "sleep_1":
                is_on = sleep_level >= 1
            elif function == "sleep_2":
                is_on = sleep_level >= 2
            elif function == "sleep_3":
                is_on = sleep_level >= 3
            elif function == "wifi_on":
                is_on = wifi_active
            if function in override:
                is_on = override[function]
            effect = "blink" if function == "wifi_on" and is_on else ""
            effect_progress = None
            if function in effect_override:
                override_effect = effect_override[function]
                if "is_on" in override_effect:
                    is_on = bool(override_effect["is_on"])
                effect = override_effect.get("effect", effect)
                effect_progress = override_effect.get("progress")
            led_status.append(
                {
                    "id": led.get("id", ""),
                    "name": led.get("name", "LED"),
                    "pin": led.get("pin", ""),
                    "brightness": led.get("brightness", 0),
                    "pwm_frequency_hz": led_tuning.get("pwm_frequency_hz", 800),
                    "brightness_gamma": led_tuning.get("brightness_gamma", 1.0),
                    "update_rate_ms": led_tuning.get("update_rate_ms", 70),
                    "is_on": is_on,
                    "effect": effect,
                    "effect_progress": effect_progress,
                }
            )
        runtime_state["led_status"] = led_status
        return runtime_state

    def _build_power_hold_led_override(self, runtime_state, leds):
        hold = runtime_state.get("power_hold", {})
        if hold.get("completed"):
            return {}
        animation = hold.get("animation", "")
        progress = self._power_hold_animation_progress(hold)
        if progress is None:
            return {}
        sleep_functions = {"sleep_1": False, "sleep_2": False, "sleep_3": False}
        power_on = runtime_state.get("powered_on", True)

        if animation == "sleep_count_up":
            active_count = 0 if progress <= 0 else min(3, int((progress * 3) + 0.999))
            sleep_functions["sleep_1"] = active_count >= 1
            sleep_functions["sleep_2"] = active_count >= 2
            sleep_functions["sleep_3"] = active_count >= 3
            return {"power_on": False, "standby": False, **sleep_functions}

        if animation == "sleep_count_down":
            completed_count = 0 if progress <= 0 else min(3, int((progress * 3) + 0.999))
            active_count = max(0, 3 - completed_count)
            sleep_functions["sleep_1"] = active_count >= 1
            sleep_functions["sleep_2"] = active_count >= 2
            sleep_functions["sleep_3"] = active_count >= 3
            return {"power_on": power_on, "standby": False, **sleep_functions}

        if animation in {"power_flicker_up", "power_flicker_down"}:
            return {
                "power_on": True,
                "standby": False,
                "sleep_1": False,
                "sleep_2": False,
                "sleep_3": False,
            }

        return {}

    def _power_hold_animation_progress(self, hold):
        trigger_seconds = max(0.0, float(hold.get("trigger_seconds", self.button_long_press_seconds()) or self.button_long_press_seconds()))
        threshold_seconds = max(trigger_seconds, float(hold.get("threshold_seconds", trigger_seconds) or trigger_seconds))
        seconds = max(0.0, float(hold.get("seconds", 0.0) or 0.0))
        if seconds < trigger_seconds:
            return None
        animation_window = max(0.1, threshold_seconds - trigger_seconds)
        return max(0.0, min(1.0, (seconds - trigger_seconds) / animation_window))

    def _build_power_hold_led_effects(self, runtime_state):
        hold = runtime_state.get("power_hold", {})
        if hold.get("completed"):
            return {}
        animation = hold.get("animation", "")
        progress = self._power_hold_animation_progress(hold)
        if progress is None:
            return {}
        if animation == "power_flicker_up":
            return {"power_on": {"is_on": True, "effect": "power_ramp_up", "progress": progress}}
        if animation == "power_flicker_down":
            return {"power_on": {"is_on": True, "effect": "power_ramp_down", "progress": progress}}
        return {}

    def _refresh_sleep_step(self, runtime_state):
        settings = self.load_settings()
        runtime_state["sleep_timer"]["step_seconds"] = int(settings.get("sleep_timer_step", 5)) * 60
        return runtime_state

    def _reader_supports_presence(self):
        setup = self.load_setup()
        reader_type = str(((setup.get("reader") or {}).get("type")) or "NONE").strip()
        return reader_type in self.PRESENCE_READER_TYPES

    def _sync_playback_session(self, runtime_state, player):
        session = runtime_state.get("playback_session", {})
        if not session:
            if runtime_state.get("playback_state") == "stopped":
                player["position_seconds"] = 0
            player["is_playing"] = False
            return runtime_state, player, False

        desired_state = runtime_state.get("playback_state", "paused")
        was_playing = session.get("state") == "playing"
        session = self.playback.sync_session(session)
        if desired_state == "stopped" and session.get("state") != "stopped":
            session = self.playback.stop(session)
        elif desired_state == "paused" and session.get("state") == "playing":
            session = self.playback.pause(session)
        runtime_state["playback_session"] = session
        entries = list(player.get("playlist_entries", []))
        if entries:
            current_index = max(0, min(len(entries) - 1, int(session.get("current_index", player.get("current_track_index", 0)))))
            player["current_track_index"] = current_index
            player["current_track"] = self._track_title_for_entry(player, entries[current_index])
            actual_duration = self._track_duration_for_entry(player, player.get("playlist", ""), entries[current_index])
            player["duration_seconds"] = max(0, int(actual_duration or session.get("duration_seconds", 0)))
        if desired_state == "stopped" or session.get("state") == "stopped":
            player["position_seconds"] = 0
        else:
            player["position_seconds"] = max(0, int(session.get("position_seconds", player.get("position_seconds", 0))))
        self._rebuild_queue_display(player)
        session_finished = (
            runtime_state.get("playback_state") == "playing" and session.get("state") == "stopped" and was_playing
        )
        if runtime_state.get("playback_state") == "playing" and session.get("state") == "paused":
            runtime_state["playback_state"] = "paused"
        if runtime_state.get("playback_state") == "playing" and session.get("state") == "error":
            runtime_state["playback_state"] = "paused"
        if session.get("state") == "stopped" and runtime_state.get("playback_state") != "stopped":
            runtime_state["playback_state"] = "stopped"
        if session_finished:
            player["is_playing"] = False
            return runtime_state, player, True
        player["is_playing"] = runtime_state.get("playback_state") == "playing" and session.get("state") == "playing"
        return runtime_state, player, False

    def _finish_playlist(self, runtime_state, player):
        runtime_state["playback_state"] = "stopped"
        player["is_playing"] = False
        runtime_state["playback_session"] = self.playback.stop(runtime_state.get("playback_session", {}))
        runtime_state = self.add_event(runtime_state, "Wiedergabe beendet")
        return runtime_state, player

    def _album_by_id(self, album_id):
        library = self.load_library()
        return next((album for album in library.get("albums", []) if album.get("id") == album_id), None)

    def _queue_track_items(self, album, entries):
        track_map = {
            str(item.get("path", "") or ""): dict(item)
            for item in (album.get("tracks", []) or [])
            if isinstance(item, dict)
        }
        return [
            {
                "album": album.get("name", ""),
                "album_id": album.get("id", ""),
                "cover_url": album.get("cover_url", ""),
                "playlist": album.get("playlist", ""),
                "entry": entry,
                "title": str(track_map.get(entry, {}).get("title", "") or track_title_from_entry(entry)),
                "duration_seconds": int(track_map.get(entry, {}).get("duration_seconds", 0) or 0),
            }
            for entry in entries
        ]

    def _rebuild_queue_display(self, player):
        entries = list(player.get("playlist_entries", []))
        current_index = max(0, int(player.get("current_track_index", 0)))
        queue = build_track_queue(entries, current_index) if entries else []
        queue.extend(item.get("title", "") for item in player.get("queued_tracks", []) if item.get("title"))
        player["queue"] = queue
        return player

    def _load_queued_track_item(self, track_item, runtime_state, player, autoplay=False):
        playlist = track_item.get("playlist", "")
        entry = track_item.get("entry", "")
        if not playlist or not entry:
            return runtime_state, player
        powered_on = bool(runtime_state.get("powered_on", True))
        autoplay = bool(autoplay and powered_on)
        player["playlist"] = playlist
        player["playlist_entries"] = [entry]
        player["playlist_tracks"] = [
            {
                "path": entry,
                "title": track_item.get("title", track_title_from_entry(entry)),
                "duration_seconds": int(track_item.get("duration_seconds", 0) or 0),
            }
        ]
        player["current_track_index"] = 0
        player["current_track"] = track_item.get("title", track_title_from_entry(entry))
        player["current_album"] = track_item.get("album", player.get("current_album", ""))
        player["cover_url"] = track_item.get("cover_url", "")
        player["duration_seconds"] = int(track_item.get("duration_seconds", 0) or pick_track_duration(playlist, entry))
        player["position_seconds"] = 0
        runtime_state["active_album_id"] = track_item.get("album_id", "")
        runtime_state["playback_session"] = self.playback.open_track(
            playlist,
            entry,
            0,
            volume=player.get("volume", 45),
            previous_session=runtime_state.get("playback_session", {}),
            current_index=0,
            entries=[entry],
        )
        runtime_state["playback_state"] = "playing" if autoplay else "paused"
        player["is_playing"] = runtime_state["playback_state"] == "playing"
        if runtime_state["playback_session"]:
            runtime_state["playback_session"] = (
                self.playback.play(runtime_state["playback_session"])
                if autoplay
                else self.playback.pause(runtime_state["playback_session"])
            )
        self._rebuild_queue_display(player)
        return runtime_state, player

    def _unique_playlist_entries(self, entries):
        unique_entries = []
        seen = set()
        for entry in entries or []:
            normalized = str(entry or "").strip()
            if not normalized or normalized in seen:
                continue
            unique_entries.append(normalized)
            seen.add(normalized)
        return unique_entries

    def _playlist_entries_for_album(self, album, shuffle=False):
        entries = self._unique_playlist_entries(load_playlist_entries(album.get("playlist", "")))
        if shuffle and len(entries) > 1:
            entries = list(entries)
            random.shuffle(entries)
        return entries

    def _session_matches_playlist(self, session, player, entries):
        if not session:
            return False
        if session.get("playlist") != player.get("playlist", ""):
            return False
        session_entries = list(session.get("playlist_entries", []) or [])
        return bool(session_entries) and session_entries == list(entries or [])

    def load_album_into_player(self, album, runtime_state=None, player=None, autoplay=False, shuffle=None):
        runtime_state = runtime_state or self.ensure_runtime()
        player = player or self.load_player()
        powered_on = bool(runtime_state.get("powered_on", True))
        autoplay = bool(autoplay and powered_on)
        if shuffle is None:
            shuffle = bool(album.get("shuffle_enabled", False))
        entries = self._playlist_entries_for_album(album, shuffle=shuffle)
        player["playlist"] = album.get("playlist", "")
        player["playlist_entries"] = entries
        player["playlist_tracks"] = self._ordered_album_tracks(album, entries)
        player["current_track_index"] = 0
        player["queued_tracks"] = []
        if entries:
            player["current_track"] = self._track_title_for_entry(player, entries[0])
            player["duration_seconds"] = self._track_duration_for_entry(player, album.get("playlist", ""), entries[0])
            runtime_state["playback_session"] = self.playback.open_track(
                album.get("playlist", ""),
                entries[0],
                0,
                volume=player.get("volume", 45),
                previous_session=runtime_state.get("playback_session", {}),
                current_index=0,
                entries=entries,
            )
        else:
            player["current_track"] = album.get("name", player.get("current_track", ""))
            player["duration_seconds"] = 0
            runtime_state["playback_session"] = {}
        player["current_album"] = album.get("name", player.get("current_album", ""))
        player["cover_url"] = album.get("cover_url", "")
        player["position_seconds"] = 0
        self._rebuild_queue_display(player)
        runtime_state["active_album_id"] = album.get("id", "")
        runtime_state["playback_state"] = "playing" if autoplay else "paused"
        player["is_playing"] = runtime_state["playback_state"] == "playing"
        if runtime_state["playback_session"]:
            runtime_state["playback_session"] = (
                self.playback.play(runtime_state["playback_session"])
                if autoplay
                else self.playback.pause(runtime_state["playback_session"])
            )
        return runtime_state, player

    def tick(self, elapsed_seconds=1):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state = self._refresh_sleep_step(runtime_state)
            runtime_state, player, session_finished = self._sync_playback_session(runtime_state, player)

            if runtime_state.get("powered_on", True) and runtime_state.get("playback_state") == "playing":
                session_backend = runtime_state.get("playback_session", {}).get("backend")
                duration = int(player.get("duration_seconds", 0))
                if session_backend == "mock":
                    position = int(player.get("position_seconds", 0))
                    player["position_seconds"] = min(duration, position + elapsed_seconds)
                    if runtime_state.get("playback_session"):
                        runtime_state["playback_session"]["position_seconds"] = player["position_seconds"]
                        runtime_state["playback_session"]["started_at"] = time.time() - player["position_seconds"]
                if session_backend == "mock" and duration > 0 and player["position_seconds"] >= duration:
                    result = self.next_track(runtime_state=runtime_state, player=player, autoplay=True)
                    runtime_state = result["runtime"]
                    player = result["player"]
                elif session_finished:
                    entries = list(player.get("playlist_entries", []))
                    current_index = int(player.get("current_track_index", 0))
                    if (entries and current_index + 1 < len(entries)) or player.get("queued_tracks"):
                        result = self.next_track(runtime_state=runtime_state, player=player, autoplay=True)
                        runtime_state = result["runtime"]
                        player = result["player"]
                    else:
                        runtime_state, player = self._finish_playlist(runtime_state, player)

            remaining = int(runtime_state.get("sleep_timer", {}).get("remaining_seconds", 0))
            if remaining > 0:
                remaining = max(0, remaining - elapsed_seconds)
                runtime_state["sleep_timer"]["remaining_seconds"] = remaining
                runtime_state["sleep_timer"]["level"] = self.compute_sleep_level(
                    remaining, runtime_state["sleep_timer"]["step_seconds"]
                )
                if remaining == 0:
                    result = self.enter_standby_after_sleep_timer(runtime_state=runtime_state, player=player)
                    runtime_state = result["runtime"]
                    player = result["player"]

            runtime_state, player = self._apply_inactivity_wifi_off(runtime_state, player)
            runtime_state, player = self._apply_inactivity_standby(runtime_state, player)

            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            player["is_playing"] = runtime_state.get("playback_state") == "playing"
            self.save_player(player)
            self.save_runtime(runtime_state)
            return {"runtime": runtime_state, "player": player}

    def compute_sleep_level(self, remaining_seconds, step_seconds):
        if remaining_seconds <= 0 or step_seconds <= 0:
            return 0
        if remaining_seconds <= step_seconds:
            return 1
        if remaining_seconds <= step_seconds * 2:
            return 2
        return 3

    def set_sleep_level(self, level):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            runtime_state = self._refresh_sleep_step(runtime_state)
            if not runtime_state.get("powered_on", True):
                runtime_state = self.add_event(runtime_state, "Sleeptimer im Standby nicht verfügbar", "warning")
                self.save_runtime(runtime_state)
                return runtime_state
            level = max(0, min(3, int(level)))
            runtime_state["sleep_timer"]["level"] = level
            runtime_state["sleep_timer"]["remaining_seconds"] = runtime_state["sleep_timer"]["step_seconds"] * level
            runtime_state = self.add_event(runtime_state, f"Sleeptimer auf Stufe {level}" if level else "Sleeptimer aus")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            return runtime_state

    def _set_power_state(self, powered_on, runtime_state=None, player=None, event_message=None, reason="manual"):
        with self.state_transaction():
            persisted_runtime = self.ensure_runtime()
            runtime_state = runtime_state or persisted_runtime
            runtime_state["powered_on"] = bool(
                persisted_runtime.get("powered_on", runtime_state.get("powered_on", True))
            )
            player = player or self.load_player()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            current_powered_on = bool(runtime_state.get("powered_on", True))
            target_powered_on = bool(powered_on)
            runtime_state["power_hold"] = merge_defaults({}, default_runtime_state()["power_hold"])
            if current_powered_on == target_powered_on:
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"runtime": runtime_state, "player": player}

            runtime_state["powered_on"] = target_powered_on
            if target_powered_on:
                runtime_state["playback_state"] = "paused"
                runtime_state["wifi_enabled"] = True
                player["is_playing"] = False
                message = event_message or "Power an"
                runtime_state["last_activity_at"] = int(time.time())
                runtime_state["last_wifi_activity_at"] = int(time.time())
                runtime_state["wifi_auto_off_started_at"] = int(time.time())
            else:
                if runtime_state.get("playback_session"):
                    runtime_state["playback_session"] = self.playback.stop(runtime_state["playback_session"])
                runtime_state["wifi_enabled"] = False
                runtime_state["wifi_auto_off_started_at"] = int(time.time())
                runtime_state["sleep_timer"]["remaining_seconds"] = 0
                runtime_state["sleep_timer"]["level"] = 0
                runtime_state, player = self._clear_playback_context(runtime_state, player, keep_loaded_media=False)
                message = event_message or "Standby aktiv"
            runtime_state = self.add_event(runtime_state, message)
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            self._set_service_active("phoniebox-rfid.service", target_powered_on)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            if self._should_play_power_sound(target_powered_on, reason):
                self.play_system_sound("power_on" if target_powered_on else "power_off")
            return {"runtime": runtime_state, "player": player}

    def power_off(self, runtime_state=None, player=None, event_message=None, reason="manual"):
        return self._set_power_state(
            False,
            runtime_state=runtime_state,
            player=player,
            event_message=event_message or "Standby aktiv",
            reason=reason,
        )

    def power_on(self, runtime_state=None, player=None, event_message=None, reason="manual"):
        return self._set_power_state(
            True,
            runtime_state=runtime_state,
            player=player,
            event_message=event_message or "Power an",
            reason=reason,
        )

    def toggle_power(self):
        runtime_state = self.ensure_runtime()
        if runtime_state.get("powered_on", True):
            return self.power_off()
        return self.power_on()

    def _fade_out_playback(self, runtime_state, player):
        session = runtime_state.get("playback_session", {})
        if not session or runtime_state.get("playback_state") != "playing":
            return runtime_state, player
        start_volume = max(0, int(player.get("volume", 0)))
        if start_volume <= 0:
            return runtime_state, player
        step_sleep = self.SLEEP_TIMER_FADE_SECONDS / max(1, self.SLEEP_TIMER_FADE_STEPS)
        for step in range(self.SLEEP_TIMER_FADE_STEPS):
            remaining_ratio = max(0.0, (self.SLEEP_TIMER_FADE_STEPS - step - 1) / self.SLEEP_TIMER_FADE_STEPS)
            target_volume = int(round(start_volume * remaining_ratio))
            runtime_state["playback_session"] = self.playback.set_volume(runtime_state["playback_session"], target_volume)
            time.sleep(step_sleep)
        return runtime_state, player

    def enter_standby_after_sleep_timer(self, runtime_state=None, player=None):
        runtime_state = runtime_state or self.ensure_runtime()
        player = player or self.load_player()
        runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
        runtime_state, player = self._fade_out_playback(runtime_state, player)
        return self.power_off(
            runtime_state=runtime_state,
            player=player,
            event_message="Sleeptimer abgelaufen, Standby aktiv",
            reason="sleep_timer",
        )

    def seek(self, position_seconds):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            duration = int(player.get("duration_seconds", 0))
            target_position = max(0, int(position_seconds))
            if duration > 0:
                target_position = min(duration, target_position)
            player["position_seconds"] = target_position
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = self.playback.seek(
                    runtime_state["playback_session"],
                    target_position,
                )
            runtime_state = self.add_event(runtime_state, f"Position gesetzt auf {target_position}s")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def clear_queue(self):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            entries = list(player.get("playlist_entries", []))
            current_index = max(0, int(player.get("current_track_index", 0)))
            if entries:
                player["playlist_entries"] = entries[: current_index + 1]
            player["queued_tracks"] = []
            self._rebuild_queue_display(player)
            runtime_state["queue_revision"] = secrets.token_hex(4)
            runtime_state = self.add_event(runtime_state, "Warteschlange geleert")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def load_album_by_id(self, album_id, autoplay=False, shuffle=None):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            album = self._album_by_id(album_id)
            if not album:
                runtime_state = self.add_event(runtime_state, f"Album nicht gefunden: {album_id}", "warning")
                self.save_runtime(runtime_state)
                return {"ok": False, "runtime": runtime_state, "player": player}
            effective_shuffle = bool(album.get("shuffle_enabled", False)) if shuffle is None else bool(shuffle)
            runtime_state, player = self.load_album_into_player(
                album,
                runtime_state,
                player,
                autoplay=autoplay,
                shuffle=effective_shuffle,
            )
            runtime_state = self.add_event(
                runtime_state,
                (
                    f"Album geladen: {album.get('name', '')}"
                    if not autoplay
                    else f"Album gestartet: {album.get('name', '')}"
                ) + (" (Shuffle)" if effective_shuffle else ""),
            )
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"ok": True, "runtime": runtime_state, "player": player, "album": album}

    def queue_album_by_id(self, album_id, shuffle=None):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            album = self._album_by_id(album_id)
            if not album:
                runtime_state = self.add_event(runtime_state, f"Album nicht gefunden: {album_id}", "warning")
                self.save_runtime(runtime_state)
                return {"ok": False, "runtime": runtime_state, "player": player}
            result = self.append_album_to_queue(album, runtime_state, player, shuffle=shuffle)
            return {"ok": True, "runtime": result["runtime"], "player": result["player"], "album": album}

    def reset_state(self):
        with self.state_transaction():
            player = self.load_player()
            runtime_state = self.ensure_runtime()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = self.playback.stop(runtime_state["playback_session"])
            runtime_state = default_runtime_state()
            player = {
                "current_album": "",
                "current_track": "",
                "cover_url": "",
                "volume": int(player.get("volume", 45)),
                "position_seconds": 0,
                "duration_seconds": 0,
                "sleep_timer_minutes": 0,
                "is_playing": False,
                "queue": [],
                "playlist": "",
                "playlist_entries": [],
                "playlist_tracks": [],
                "current_track_index": 0,
                "queued_tracks": [],
            }
            runtime_state["powered_on"] = False
            runtime_state["playback_state"] = "stopped"
            runtime_state["active_album_id"] = ""
            runtime_state["active_rfid_uid"] = ""
            runtime_state["hardware"]["last_scanned_uid"] = ""
            runtime_state["hardware"]["last_button"] = ""
            runtime_state["hardware"]["last_button_press_type"] = ""
            runtime_state["hardware"]["pressed_buttons"] = []
            runtime_state = self.add_event(runtime_state, "Runtime zurückgesetzt")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def toggle_playback(self):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            if not runtime_state.get("playback_session") and not player.get("playlist_entries") and player.get("queued_tracks"):
                queued_tracks = list(player.get("queued_tracks", []))
                next_item = queued_tracks.pop(0)
                player["queued_tracks"] = queued_tracks
                runtime_state, player = self._load_queued_track_item(next_item, runtime_state, player, autoplay=False)
            elif not runtime_state.get("playback_session"):
                runtime_state, player, _ = self._reopen_current_track_session(runtime_state, player, autoplay=False)
            if not runtime_state.get("powered_on", True):
                runtime_state["playback_state"] = "stopped"
                player["is_playing"] = False
                runtime_state = self.add_event(runtime_state, "Wiedergabe im Standby nicht verfügbar", "warning")
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"runtime": runtime_state, "player": player}
            if runtime_state.get("playback_state") == "playing":
                runtime_state["playback_state"] = "paused"
                player["is_playing"] = False
                event = "Wiedergabe pausiert"
                if runtime_state.get("playback_session"):
                    runtime_state["playback_session"] = self.playback.pause(runtime_state["playback_session"])
            else:
                runtime_state["playback_state"] = "playing"
                player["is_playing"] = True
                event = "Wiedergabe gestartet"
                if runtime_state.get("playback_session"):
                    runtime_state["playback_session"] = self.playback.play(runtime_state["playback_session"])
            runtime_state = self.add_event(runtime_state, event)
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def stop(self):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            runtime_state["playback_state"] = "stopped"
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = self.playback.stop(runtime_state["playback_session"])
            runtime_state, player = self._clear_playback_context(runtime_state, player, keep_loaded_media=False)
            runtime_state = self.add_event(runtime_state, "Wiedergabe gestoppt")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def next_track(self, runtime_state=None, player=None, autoplay=False):
        with self.state_transaction():
            runtime_state = runtime_state or self.ensure_runtime()
            player = player or self.load_player()
            entries = list(player.get("playlist_entries", []))
            current_index = int(player.get("current_track_index", 0))
            if not entries:
                runtime_state, player, reopened = self._reopen_current_track_session(runtime_state, player, autoplay=autoplay)
                if reopened:
                    runtime_state["queue_revision"] = secrets.token_hex(4)
                    runtime_state = self.add_event(runtime_state, f"Nächster Titel: {player.get('current_track', '')}")
                    runtime_state = self.update_hardware_profile(runtime_state)
                    runtime_state = self.apply_wifi_policy(runtime_state)
                    runtime_state = self.update_led_status(runtime_state)
                    self.save_runtime(runtime_state)
                    self.save_player(player)
                    return {"runtime": runtime_state, "player": player}
            if entries and current_index + 1 < len(entries):
                current_index += 1
                session = runtime_state.get("playback_session", {})
                if self._session_matches_playlist(session, player, entries):
                    advanced_session = self.playback.next_track(session)
                    if int(advanced_session.get("current_index", -1) or -1) == current_index:
                        runtime_state["playback_session"] = advanced_session
                    else:
                        runtime_state["playback_session"] = self.playback.open_track(
                            player.get("playlist", ""),
                            entries[current_index],
                            0,
                            volume=player.get("volume", 45),
                            previous_session=session,
                            current_index=current_index,
                            entries=entries,
                        )
                else:
                    runtime_state["playback_session"] = self.playback.open_track(
                        player.get("playlist", ""),
                        entries[current_index],
                        0,
                        volume=player.get("volume", 45),
                        previous_session=session,
                        current_index=current_index,
                        entries=entries,
                    )
                runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            elif player.get("queued_tracks"):
                queued_tracks = list(player.get("queued_tracks", []))
                next_item = queued_tracks.pop(0)
                player["queued_tracks"] = queued_tracks
                runtime_state, player = self._load_queued_track_item(next_item, runtime_state, player, autoplay=autoplay)
            else:
                runtime_state, player = self._finish_playlist(runtime_state, player)
                runtime_state["queue_revision"] = secrets.token_hex(4)
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"runtime": runtime_state, "player": player}
            player["position_seconds"] = 0
            runtime_state["playback_state"] = "playing" if autoplay or runtime_state.get("playback_state") == "playing" else "paused"
            player["is_playing"] = runtime_state["playback_state"] == "playing"
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = (
                    self.playback.play(runtime_state["playback_session"])
                    if runtime_state["playback_state"] == "playing"
                    else self.playback.pause(runtime_state["playback_session"])
                )
            runtime_state["queue_revision"] = secrets.token_hex(4)
            runtime_state = self.add_event(runtime_state, f"Nächster Titel: {player.get('current_track', '')}")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def previous_track(self):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            entries = list(player.get("playlist_entries", []))
            current_index = int(player.get("current_track_index", 0))
            position_seconds = float(player.get("position_seconds", 0) or 0)
            should_restart_current = bool(entries) and position_seconds >= self.PREVIOUS_TRACK_RESTART_THRESHOLD_SECONDS
            if should_restart_current:
                if runtime_state.get("playback_session"):
                    runtime_state["playback_session"] = self.playback.seek(runtime_state["playback_session"], 0)
                runtime_state = self.add_event(runtime_state, f"Titel neu gestartet: {player.get('current_track', '')}")
            elif entries and current_index > 0:
                current_index -= 1
                session = runtime_state.get("playback_session", {})
                if self._session_matches_playlist(session, player, entries):
                    previous_session = self.playback.previous_track(session)
                    if int(previous_session.get("current_index", -1) or -1) == current_index:
                        runtime_state["playback_session"] = previous_session
                    else:
                        runtime_state["playback_session"] = self.playback.open_track(
                            player.get("playlist", ""),
                            entries[current_index],
                            0,
                            volume=player.get("volume", 45),
                            previous_session=session,
                            current_index=current_index,
                            entries=entries,
                        )
                else:
                    runtime_state["playback_session"] = self.playback.open_track(
                        player.get("playlist", ""),
                        entries[current_index],
                        0,
                        volume=player.get("volume", 45),
                        previous_session=session,
                        current_index=current_index,
                        entries=entries,
                    )
                runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
                runtime_state = self.add_event(runtime_state, f"Vorheriger Titel: {player.get('current_track', '')}")
            else:
                runtime_state = self.add_event(runtime_state, "Titel zurückgesetzt")
            player["position_seconds"] = 0
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = (
                    self.playback.play(runtime_state["playback_session"])
                    if runtime_state.get("playback_state") == "playing"
                    else self.playback.pause(runtime_state["playback_session"])
                )
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def set_volume(self, delta):
        with self.state_transaction():
            settings = self.load_settings()
            player = self.load_player()
            volume = int(player.get("volume", 0))
            max_volume = int(settings.get("max_volume", 100))
            player["volume"] = max(0, min(max_volume, volume + int(delta)))
            player["muted"] = False
            if player["volume"] > 0:
                player["volume_before_mute"] = player["volume"]
            runtime_state = self.ensure_runtime()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = self.playback.set_volume(
                    runtime_state["playback_session"],
                    player["volume"],
                )
            runtime_state = self.add_event(runtime_state, f"Lautstärke {player['volume']}%")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def toggle_mute(self):
        with self.state_transaction():
            settings = self.load_settings()
            player = self.load_player()
            max_volume = int(settings.get("max_volume", 100))
            runtime_state = self.ensure_runtime()

            if player.get("muted"):
                restore = int(player.get("volume_before_mute", 45) or 45)
                player["volume"] = max(0, min(max_volume, restore))
                player["muted"] = False
            else:
                current_volume = int(player.get("volume", 0))
                if current_volume > 0:
                    player["volume_before_mute"] = current_volume
                player["volume"] = 0
                player["muted"] = True

            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = self.playback.set_volume(
                    runtime_state["playback_session"],
                    player["volume"],
                )
            runtime_state = self.add_event(runtime_state, "Stumm" if player.get("muted") else f"Lautstärke {player['volume']}%")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def append_album_to_queue(self, album, runtime_state=None, player=None, shuffle=None):
        runtime_state = runtime_state or self.ensure_runtime()
        player = player or self.load_player()
        if shuffle is None:
            shuffle = bool(album.get("shuffle_enabled", False))
        entries = self._playlist_entries_for_album(album, shuffle=shuffle)
        queued_items = self._queue_track_items(album, entries)
        if not player.get("current_track") and not player.get("playlist_entries") and queued_items:
            next_item = queued_items.pop(0)
            runtime_state, player = self._load_queued_track_item(next_item, runtime_state, player, autoplay=False)
        player["queued_tracks"] = list(player.get("queued_tracks", [])) + queued_items
        self._rebuild_queue_display(player)
        runtime_state["queue_revision"] = secrets.token_hex(4)
        runtime_state = self.add_event(
            runtime_state,
            f"Album zur Warteschlange hinzugefügt: {album.get('name', '')}" + (" (Shuffle)" if shuffle else ""),
        )
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def remove_rfid_tag(self):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            action = self.get_reader_behavior()["remove"]
            active_uid = runtime_state.get("active_rfid_uid", "").strip()
            runtime_state["active_rfid_uid"] = ""
            if not active_uid:
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"runtime": runtime_state, "player": player}
            if action == "stop":
                if runtime_state.get("playback_session"):
                    runtime_state["playback_session"] = self.playback.stop(runtime_state["playback_session"])
                runtime_state, player = self._clear_playback_context(runtime_state, player, keep_loaded_media=False)
                runtime_state = self.add_event(runtime_state, "Tag entfernt: Wiedergabe gestoppt")
            elif action == "pause":
                runtime_state["playback_state"] = "paused"
                player["is_playing"] = False
                if runtime_state.get("playback_session"):
                    runtime_state["playback_session"] = self.playback.pause(runtime_state["playback_session"])
                    player["position_seconds"] = max(
                        0,
                        int(runtime_state["playback_session"].get("position_seconds", player.get("position_seconds", 0))),
                    )
                runtime_state = self.add_event(runtime_state, "Tag entfernt: Wiedergabe pausiert")
            else:
                runtime_state = self.add_event(runtime_state, "Tag entfernt: keine Aktion")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"runtime": runtime_state, "player": player}

    def assign_album_by_rfid(self, uid):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            library = self.load_library()
            behavior = self.get_reader_behavior()
            normalized_uid = uid.strip()
            target_album = next(
                (album for album in library.get("albums", []) if album.get("rfid_uid", "").strip() == normalized_uid),
                None,
            )
            if not target_album:
                return {"ok": False, "ignored": True, "runtime": runtime_state, "player": player}

            runtime_state["hardware"]["last_scanned_uid"] = normalized_uid
            if not runtime_state.get("powered_on", True):
                runtime_state = self.add_event(runtime_state, "RFID im Standby ignoriert", "warning")
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"ok": False, "ignored": True, "runtime": runtime_state, "player": player}

            same_album_active = runtime_state.get("active_album_id", "").strip() == target_album.get("id", "").strip()
            same_uid_active = runtime_state.get("active_rfid_uid", "").strip() == normalized_uid
            session = runtime_state.get("playback_session", {})
            session_has_track = bool(session.get("track_path") or session.get("entry"))
            mode = behavior["read"]

            if same_uid_active and same_album_active and mode != "queue_append":
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"ok": True, "runtime": runtime_state, "player": player}

            if (
                mode == "play"
                and same_album_active
                and runtime_state.get("playback_state") == "playing"
                and session_has_track
            ):
                runtime_state["active_rfid_uid"] = normalized_uid
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"ok": True, "runtime": runtime_state, "player": player}

            runtime_state["active_rfid_uid"] = normalized_uid
            if mode == "queue_append":
                result = self.append_album_to_queue(target_album, runtime_state, player)
                result["runtime"]["active_rfid_uid"] = normalized_uid
                result["runtime"]["hardware"]["last_scanned_uid"] = normalized_uid
                result["runtime"] = self.add_event(result["runtime"], f"RFID geladen: {target_album.get('name', '')}")
                self.save_runtime(result["runtime"])
                return {"ok": True, "runtime": result["runtime"], "player": result["player"]}

            if (
                mode == "play"
                and same_album_active
                and runtime_state.get("playback_state") == "paused"
                and session_has_track
            ):
                runtime_state["playback_state"] = "playing"
                player["is_playing"] = True
                runtime_state["playback_session"] = self.playback.play(session)
                runtime_state = self.add_event(runtime_state, f"RFID fortgesetzt: {target_album.get('name', '')}")
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.apply_wifi_policy(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"ok": True, "runtime": runtime_state, "player": player}

            runtime_state, player = self.load_album_into_player(target_album, runtime_state, player, autoplay=(mode == "play"))
            runtime_state = self.add_event(runtime_state, f"RFID geladen: {target_album.get('name', '')}")
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            self.save_runtime(runtime_state)
            self.save_player(player)
            return {"ok": True, "runtime": runtime_state, "player": player}

    def trigger_button(self, name, press_type="kurz"):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            detect_state = self.load_button_detect()
            if detect_state.get("active"):
                runtime_state = self.add_event(runtime_state, "Tastenerkennung aktiv: Tastenfunktion ausgesetzt.", "warning")
                self.save_runtime(runtime_state)
                return {"runtime": runtime_state, "player": self.load_player()}
            last_button = name
            last_press_type = press_type
            runtime_state["hardware"]["last_button"] = last_button
            runtime_state["hardware"]["last_button_press_type"] = last_press_type

            normalized = name.strip().lower()
            if normalized == "play/pause":
                result = self.toggle_playback()
                result["runtime"]["hardware"]["last_button"] = last_button
                result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(result["runtime"])
                return result
            if normalized == "stopp":
                result = self.stop()
                result["runtime"]["hardware"]["last_button"] = last_button
                result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(result["runtime"])
                return result
            if normalized == "vor":
                result = self.next_track()
                result["runtime"]["hardware"]["last_button"] = last_button
                result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(result["runtime"])
                return result
            if normalized == "zurück":
                result = self.previous_track()
                result["runtime"]["hardware"]["last_button"] = last_button
                result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(result["runtime"])
                return result
            if normalized == "lautstärke +":
                result = self.set_volume(self.volume_step())
                result["runtime"]["hardware"]["last_button"] = last_button
                result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(result["runtime"])
                return result
            if normalized == "lautstärke -":
                result = self.set_volume(-self.volume_step())
                result["runtime"]["hardware"]["last_button"] = last_button
                result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(result["runtime"])
                return result
            if normalized == "sleep timer +":
                current_level = int(runtime_state.get("sleep_timer", {}).get("level", 0))
                runtime_state = self.set_sleep_level(self.next_sleep_level_up(current_level))
                runtime_state["hardware"]["last_button"] = last_button
                runtime_state["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(runtime_state)
                return {"runtime": runtime_state, "player": self.load_player()}
            if normalized == "sleep timer -":
                current_level = int(runtime_state.get("sleep_timer", {}).get("level", 0))
                runtime_state = self.set_sleep_level(max(0, current_level - 1))
                runtime_state["hardware"]["last_button"] = last_button
                runtime_state["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(runtime_state)
                return {"runtime": runtime_state, "player": self.load_player()}
            if normalized == "wifi on/off":
                result = self.toggle_wifi()
                result["runtime"]["hardware"]["last_button"] = last_button
                result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(result["runtime"])
                return result
            if normalized in {"power on/off", "sleep/power"}:
                result = self.toggle_power()
                result["runtime"]["hardware"]["last_button"] = last_button
                result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(result["runtime"])
                return result

            runtime_state = self.update_led_status(runtime_state)
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.apply_wifi_policy(runtime_state)
            self.save_runtime(runtime_state)
            return {"runtime": runtime_state, "player": self.load_player()}

    def trigger_gpio_pin(self, pin, press_type="kurz", held_seconds=None):
        setup = self.load_setup()
        runtime_state = self.ensure_runtime()
        runtime_state["hardware"]["pressed_buttons"] = [pin] if pin else []
        press_type = self.classify_press_type(held_seconds, press_type)
        detect_state = self.load_button_detect()
        if detect_state.get("active"):
            runtime_state = self.add_event(runtime_state, f"GPIO erkannt für Tastenerkennung: {pin}")
            self.save_runtime(runtime_state)
            return {"runtime": runtime_state, "player": self.load_player()}
        if not self.hardware_buttons_enabled():
            runtime_state["hardware"]["pressed_buttons"] = []
            runtime_state = self.add_event(runtime_state, "Hardwaretasten deaktiviert")
            self.save_runtime(runtime_state)
            return {"runtime": runtime_state, "player": self.load_player()}
        mapped_name = self._button_mapping_for_pin(setup, pin, press_type)
        if mapped_name:
            runtime_state = self.add_event(runtime_state, f"GPIO erkannt: {pin} -> {mapped_name}")
            self.save_runtime(runtime_state)
            return self.trigger_button(mapped_name, press_type)

        runtime_state = self.add_event(runtime_state, f"GPIO erkannt ohne Zuordnung: {pin} ({press_type})", "warning")
        self.save_runtime(runtime_state)
        return {"runtime": runtime_state, "player": self.load_player()}

    def status(self):
        with self.state_transaction():
            runtime_state = self.ensure_runtime()
            player = self.load_player()
            runtime_state = self._refresh_sleep_step(runtime_state)
            runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
            runtime_state = self.update_hardware_profile(runtime_state)
            runtime_state = self.update_led_status(runtime_state)
            return {
                "runtime": runtime_state,
                "player": player,
                "settings": self.load_settings(),
                "setup": self.load_setup(),
                "performance": self.performance_profile(),
            }
