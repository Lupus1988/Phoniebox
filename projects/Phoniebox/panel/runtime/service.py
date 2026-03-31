import json
import os
import secrets
import sys
import time
from pathlib import Path

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.gpio import GPIO_TO_BOARD_PIN, SysfsGPIOInput, gpio_display_label, sysfs_gpio_available
from hardware.manager import detect_hardware
from runtime.audio import build_track_queue, load_playlist_entries, pick_track_duration, track_title_from_entry
from runtime.playback import PlaybackController

DATA_DIR = BASE_DIR / "data"
PLAYER_FILE = DATA_DIR / "player_state.json"
LIBRARY_FILE = DATA_DIR / "library.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SETUP_FILE = DATA_DIR / "setup.json"
RUNTIME_FILE = DATA_DIR / "runtime_state.json"
BUTTON_DETECT_FILE = DATA_DIR / "button_detect.json"


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


def default_runtime_state():
    return {
        "powered_on": True,
        "playback_state": "paused",
        "active_album_id": "album-1",
        "active_rfid_uid": "1234567890",
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
        },
        "hardware": {
            "reader_connected": False,
            "reader_type": "USB",
            "last_scanned_uid": "",
            "last_button": "",
            "last_button_press_type": "",
            "pressed_buttons": [],
            "profile": {},
        },
        "led_status": [],
        "queue_revision": secrets.token_hex(4),
        "playback_session": {},
        "event_log": [],
    }


def default_button_detect():
    return {
        "active": False,
        "status": "idle",
        "deadline_at": 0.0,
    }


class RuntimeService:
    def __init__(self):
        self.runtime_path = RUNTIME_FILE
        self.playback = PlaybackController()
        self._gpio_ready = False
        self._gpio_backend = None
        self._configured_gpio_pins = set()
        self._button_poll_state = {}
        self._last_pressed_pins = []
        self._sysfs_gpio = SysfsGPIOInput()

    def load_runtime(self):
        return load_json(self.runtime_path, default_runtime_state())

    def save_runtime(self, state):
        save_json(self.runtime_path, state)

    def load_player(self):
        return merge_defaults(load_json(PLAYER_FILE, default_player()), default_player())

    def save_player(self, state):
        save_json(PLAYER_FILE, state)

    def load_library(self):
        return load_json(LIBRARY_FILE, {"albums": []})

    def load_settings(self):
        return load_json(SETTINGS_FILE, {})

    def load_setup(self):
        return load_json(SETUP_FILE, {})

    def load_button_detect(self):
        return merge_defaults(load_json(BUTTON_DETECT_FILE, default_button_detect()), default_button_detect())

    def button_long_press_seconds(self):
        setup = self.load_setup()
        try:
            value = float(str(setup.get("button_long_press_seconds", 2)).strip().replace(",", "."))
        except (TypeError, ValueError):
            value = 2.0
        return max(1.0, min(10.0, value))

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
        return GPIO is not None or sysfs_gpio_available()

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
                    if bcm not in self._configured_gpio_pins:
                        GPIO.setup(bcm, GPIO.IN, pull_up_down=GPIO.PUD_UP)

                for bcm in sorted(self._configured_gpio_pins - target_bcm):
                    try:
                        GPIO.cleanup(bcm)
                    except RuntimeError:
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
            return ready

        return False

    def _read_gpio_levels(self, gpio_names):
        if not self._ensure_gpio_inputs(gpio_names):
            return {}
        if self._gpio_backend == "sysfs":
            return self._sysfs_gpio.sample(gpio_names)
        levels = {}
        for gpio_name in gpio_names:
            bcm = self._gpio_name_to_bcm(gpio_name)
            if bcm is None:
                continue
            try:
                levels[gpio_name] = int(GPIO.input(bcm))
            except RuntimeError:
                continue
        return levels

    def _set_pressed_buttons(self, pins):
        pins = sorted([pin for pin in pins if pin])
        if pins == self._last_pressed_pins:
            return
        runtime_state = self.ensure_runtime()
        runtime_state["hardware"]["pressed_buttons"] = pins
        self.save_runtime(runtime_state)
        self._last_pressed_pins = pins

    def _button_mapping_for_pin(self, setup, pin, press_type):
        for button in setup.get("buttons", []):
            if button.get("pin", "").strip() != pin:
                continue
            if button.get("press_type", "kurz") != press_type:
                continue
            return button.get("name", "")
        return ""

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
        now = float(now if now is not None else time.monotonic())
        detect_state = self.load_button_detect()
        if detect_state.get("active"):
            self._poll_button_detection(detect_state, now)
            return

        setup = self.load_setup()
        configured_pins = sorted({button.get("pin", "").strip() for button in setup.get("buttons", []) if button.get("pin", "").strip()})
        levels = self._read_gpio_levels(configured_pins)
        if not configured_pins or not levels:
            self._set_pressed_buttons([])
            return

        pressed_now = [pin for pin, value in levels.items() if int(value) == 0]
        self._set_pressed_buttons(pressed_now)

        for pin in configured_pins:
            level = levels.get(pin)
            if level is None:
                continue
            state = self._button_poll_state.setdefault(pin, {"pressed": False, "pressed_at": 0.0})
            is_pressed = int(level) == 0
            if is_pressed and not state["pressed"]:
                state["pressed"] = True
                state["pressed_at"] = now
                continue
            if is_pressed:
                continue
            if not state["pressed"]:
                continue

            held_seconds = max(0.0, now - float(state.get("pressed_at", now)))
            state["pressed"] = False
            state["pressed_at"] = 0.0
            if held_seconds < 0.03:
                continue
            press_type = self.classify_press_type(held_seconds, "kurz")
            if not self._button_mapping_for_pin(setup, pin, press_type):
                continue
            self.trigger_gpio_pin(pin, press_type=press_type, held_seconds=held_seconds)

    def poll_buttons_forever(self, interval_seconds=0.05):
        while True:
            try:
                self.poll_buttons_once()
            except Exception:
                time.sleep(max(0.1, interval_seconds))
                continue
            time.sleep(max(0.02, interval_seconds))

    def ensure_runtime(self):
        if not self.runtime_path.exists():
            self.save_runtime(default_runtime_state())
        return self.load_runtime()

    def add_event(self, runtime_state, message, level="info"):
        runtime_state["last_event"] = message
        runtime_state["last_event_at"] = int(time.time())
        event_log = list(runtime_state.get("event_log", []))
        event_log.insert(0, {"message": message, "level": level, "at": runtime_state["last_event_at"]})
        runtime_state["event_log"] = event_log[:20]
        return runtime_state

    def get_reader_behavior(self):
        settings = self.load_settings()
        return {
            "read": settings.get("rfid_read_action", "play"),
            "remove": settings.get("rfid_remove_action", "stop"),
        }

    def update_hardware_profile(self, runtime_state):
        setup = self.load_setup()
        library = self.load_library()
        runtime_state["hardware"]["profile"] = detect_hardware(setup, library)
        runtime_state["hardware"]["profile"]["audio"]["playback_backend"] = self.playback.status()["active_backend"]
        runtime_state["hardware"]["reader_type"] = setup.get("reader", {}).get("type", "USB")
        runtime_state["hardware"]["reader_connected"] = runtime_state["hardware"]["profile"]["reader"].get("ready", False)
        return runtime_state

    def update_led_status(self, runtime_state):
        setup = self.load_setup()
        leds = setup.get("leds", [])
        sleep_level = runtime_state.get("sleep_timer", {}).get("level", 0)
        powered_on = runtime_state.get("powered_on", True)
        playback_state = runtime_state.get("playback_state", "paused")
        led_status = []
        for led in leds:
            function = led.get("function", "")
            is_on = False
            if function == "power_on":
                is_on = powered_on
            elif function == "standby":
                is_on = powered_on and playback_state != "playing"
            elif function == "sleep_1":
                is_on = sleep_level >= 1
            elif function == "sleep_2":
                is_on = sleep_level >= 2
            elif function == "sleep_3":
                is_on = sleep_level >= 3
            led_status.append(
                {
                    "id": led.get("id", ""),
                    "name": led.get("name", "LED"),
                    "pin": led.get("pin", ""),
                    "brightness": led.get("brightness", 0),
                    "is_on": is_on,
                }
            )
        runtime_state["led_status"] = led_status
        return runtime_state

    def _refresh_sleep_step(self, runtime_state):
        settings = self.load_settings()
        runtime_state["sleep_timer"]["step_seconds"] = int(settings.get("sleep_timer_step", 5)) * 60
        return runtime_state

    def _sync_playback_session(self, runtime_state, player):
        session = runtime_state.get("playback_session", {})
        if not session:
            return runtime_state, player, False

        was_playing = session.get("state") == "playing"
        session = self.playback.sync_session(session)
        runtime_state["playback_session"] = session
        player["position_seconds"] = max(0, int(session.get("position_seconds", player.get("position_seconds", 0))))
        if runtime_state.get("playback_state") == "playing" and session.get("state") == "paused":
            runtime_state["playback_state"] = "paused"
        if runtime_state.get("playback_state") == "playing" and session.get("state") == "stopped" and was_playing:
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

    def load_album_into_player(self, album, runtime_state=None, player=None, autoplay=False):
        runtime_state = runtime_state or self.ensure_runtime()
        player = player or self.load_player()
        entries = load_playlist_entries(album.get("playlist", ""))
        player["playlist"] = album.get("playlist", "")
        player["playlist_entries"] = entries
        player["current_track_index"] = 0
        if entries:
            player["current_track"] = track_title_from_entry(entries[0])
            player["duration_seconds"] = pick_track_duration(entries[0])
            player["queue"] = build_track_queue(entries, 0)
            runtime_state["playback_session"] = self.playback.open_track(
                album.get("playlist", ""),
                entries[0],
                0,
                volume=player.get("volume", 45),
                previous_session=runtime_state.get("playback_session", {}),
            )
        else:
            player["current_track"] = album.get("name", player.get("current_track", ""))
            player["duration_seconds"] = 0
            player["queue"] = []
            runtime_state["playback_session"] = {}
        player["current_album"] = album.get("name", player.get("current_album", ""))
        player["cover_url"] = album.get("cover_url", "")
        player["position_seconds"] = 0
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
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        runtime_state = self._refresh_sleep_step(runtime_state)
        runtime_state, player, session_finished = self._sync_playback_session(runtime_state, player)

        if runtime_state.get("powered_on", True) and runtime_state.get("playback_state") == "playing":
            duration = int(player.get("duration_seconds", 0))
            if runtime_state.get("playback_session", {}).get("backend") == "mock":
                position = int(player.get("position_seconds", 0))
                player["position_seconds"] = min(duration, position + elapsed_seconds)
                if runtime_state.get("playback_session"):
                    runtime_state["playback_session"]["position_seconds"] = player["position_seconds"]
                    runtime_state["playback_session"]["started_at"] = time.time() - player["position_seconds"]
            if duration > 0 and player["position_seconds"] >= duration:
                result = self.next_track(runtime_state=runtime_state, player=player, autoplay=True)
                runtime_state = result["runtime"]
                player = result["player"]
            elif session_finished:
                entries = list(player.get("playlist_entries", []))
                current_index = int(player.get("current_track_index", 0))
                if entries and current_index + 1 < len(entries):
                    result = self.next_track(runtime_state=runtime_state, player=player, autoplay=True)
                    runtime_state = result["runtime"]
                    player = result["player"]
                else:
                    runtime_state, player = self._finish_playlist(runtime_state, player)

        remaining = int(runtime_state.get("sleep_timer", {}).get("remaining_seconds", 0))
        if remaining > 0:
            remaining = max(0, remaining - elapsed_seconds)
            runtime_state["sleep_timer"]["remaining_seconds"] = remaining
            if remaining == 0:
                runtime_state["playback_state"] = "paused"
                player["is_playing"] = False
                if runtime_state.get("playback_session"):
                    runtime_state["playback_session"] = self.playback.pause(runtime_state["playback_session"])
                runtime_state = self.add_event(runtime_state, "Sleeptimer abgelaufen")
            runtime_state["sleep_timer"]["level"] = self.compute_sleep_level(
                remaining, runtime_state["sleep_timer"]["step_seconds"]
            )

        runtime_state = self.update_hardware_profile(runtime_state)
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
        runtime_state = self.ensure_runtime()
        runtime_state = self._refresh_sleep_step(runtime_state)
        level = max(0, min(3, int(level)))
        runtime_state["sleep_timer"]["level"] = level
        runtime_state["sleep_timer"]["remaining_seconds"] = runtime_state["sleep_timer"]["step_seconds"] * level
        runtime_state = self.add_event(runtime_state, f"Sleeptimer auf Stufe {level}" if level else "Sleeptimer aus")
        runtime_state = self.update_hardware_profile(runtime_state)
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        return runtime_state

    def seek(self, position_seconds):
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
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def clear_queue(self):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        player["queue"] = []
        runtime_state["queue_revision"] = secrets.token_hex(4)
        runtime_state = self.add_event(runtime_state, "Warteschlange geleert")
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def load_album_by_id(self, album_id, autoplay=False):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        album = self._album_by_id(album_id)
        if not album:
            runtime_state = self.add_event(runtime_state, f"Album nicht gefunden: {album_id}", "warning")
            self.save_runtime(runtime_state)
            return {"ok": False, "runtime": runtime_state, "player": player}
        runtime_state, player = self.load_album_into_player(album, runtime_state, player, autoplay=autoplay)
        runtime_state = self.add_event(
            runtime_state,
            f"Album geladen: {album.get('name', '')}" if not autoplay else f"Album gestartet: {album.get('name', '')}",
        )
        runtime_state = self.update_hardware_profile(runtime_state)
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"ok": True, "runtime": runtime_state, "player": player, "album": album}

    def queue_album_by_id(self, album_id):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        album = self._album_by_id(album_id)
        if not album:
            runtime_state = self.add_event(runtime_state, f"Album nicht gefunden: {album_id}", "warning")
            self.save_runtime(runtime_state)
            return {"ok": False, "runtime": runtime_state, "player": player}
        result = self.append_album_to_queue(album, runtime_state, player)
        return {"ok": True, "runtime": result["runtime"], "player": result["player"], "album": album}

    def reset_state(self):
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
            "current_track_index": 0,
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
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def toggle_playback(self):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
        if not runtime_state.get("powered_on", True):
            runtime_state["powered_on"] = True
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
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def stop(self):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
        runtime_state["playback_state"] = "stopped"
        player["is_playing"] = False
        player["position_seconds"] = 0
        if runtime_state.get("playback_session"):
            runtime_state["playback_session"] = self.playback.stop(runtime_state["playback_session"])
        runtime_state = self.add_event(runtime_state, "Wiedergabe gestoppt")
        runtime_state = self.update_hardware_profile(runtime_state)
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def next_track(self, runtime_state=None, player=None, autoplay=False):
        runtime_state = runtime_state or self.ensure_runtime()
        player = player or self.load_player()
        entries = list(player.get("playlist_entries", []))
        current_index = int(player.get("current_track_index", 0))
        if entries and current_index + 1 < len(entries):
            current_index += 1
            player["current_track_index"] = current_index
            player["current_track"] = track_title_from_entry(entries[current_index])
            player["duration_seconds"] = pick_track_duration(entries[current_index])
            player["queue"] = build_track_queue(entries, current_index)
            runtime_state["playback_session"] = self.playback.open_track(
                player.get("playlist", ""),
                entries[current_index],
                0,
                volume=player.get("volume", 45),
                previous_session=runtime_state.get("playback_session", {}),
            )
        else:
            runtime_state, player = self._finish_playlist(runtime_state, player)
            runtime_state["queue_revision"] = secrets.token_hex(4)
            runtime_state = self.update_hardware_profile(runtime_state)
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
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def previous_track(self):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
        entries = list(player.get("playlist_entries", []))
        current_index = int(player.get("current_track_index", 0))
        if entries and current_index > 0:
            current_index -= 1
            player["current_track_index"] = current_index
            player["current_track"] = track_title_from_entry(entries[current_index])
            player["duration_seconds"] = pick_track_duration(entries[current_index])
            player["queue"] = build_track_queue(entries, current_index)
            runtime_state["playback_session"] = self.playback.open_track(
                player.get("playlist", ""),
                entries[current_index],
                0,
                volume=player.get("volume", 45),
                previous_session=runtime_state.get("playback_session", {}),
            )
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
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def toggle_mute(self):
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
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def append_album_to_queue(self, album, runtime_state=None, player=None):
        runtime_state = runtime_state or self.ensure_runtime()
        player = player or self.load_player()
        entries = load_playlist_entries(album.get("playlist", ""))
        appended = [track_title_from_entry(entry) for entry in entries]
        queue = list(player.get("queue", []))
        queue.extend(appended)
        player["queue"] = queue
        runtime_state["queue_revision"] = secrets.token_hex(4)
        runtime_state = self.add_event(runtime_state, f"Album zur Warteschlange hinzugefügt: {album.get('name', '')}")
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def remove_rfid_tag(self):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
        action = self.get_reader_behavior()["remove"]
        runtime_state["active_rfid_uid"] = ""
        if action == "stop":
            runtime_state["playback_state"] = "stopped"
            player["is_playing"] = False
            player["position_seconds"] = 0
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = self.playback.stop(runtime_state["playback_session"])
            runtime_state = self.add_event(runtime_state, "Tag entfernt: Wiedergabe gestoppt")
        elif action == "pause":
            runtime_state["playback_state"] = "paused"
            player["is_playing"] = False
            if runtime_state.get("playback_session"):
                runtime_state["playback_session"] = self.playback.pause(runtime_state["playback_session"])
            runtime_state = self.add_event(runtime_state, "Tag entfernt: Wiedergabe pausiert")
        else:
            runtime_state = self.add_event(runtime_state, "Tag entfernt: keine Aktion")
        runtime_state = self.update_hardware_profile(runtime_state)
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        self.save_player(player)
        return {"runtime": runtime_state, "player": player}

    def assign_album_by_rfid(self, uid):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        library = self.load_library()
        behavior = self.get_reader_behavior()
        for album in library.get("albums", []):
            if album.get("rfid_uid", "").strip() == uid.strip():
                runtime_state["active_rfid_uid"] = uid
                runtime_state["hardware"]["last_scanned_uid"] = uid
                mode = behavior["read"]
                if mode == "queue_append":
                    result = self.append_album_to_queue(album, runtime_state, player)
                    result["runtime"]["active_rfid_uid"] = uid
                    result["runtime"]["hardware"]["last_scanned_uid"] = uid
                    result["runtime"] = self.add_event(result["runtime"], f"RFID geladen: {album.get('name', '')}")
                    self.save_runtime(result["runtime"])
                    return {"ok": True, "runtime": result["runtime"], "player": result["player"]}

                runtime_state, player = self.load_album_into_player(album, runtime_state, player, autoplay=(mode == "play"))
                runtime_state = self.add_event(runtime_state, f"RFID geladen: {album.get('name', '')}")
                runtime_state = self.update_hardware_profile(runtime_state)
                runtime_state = self.update_led_status(runtime_state)
                self.save_runtime(runtime_state)
                self.save_player(player)
                return {"ok": True, "runtime": runtime_state, "player": player}
        runtime_state["hardware"]["last_scanned_uid"] = uid
        runtime_state = self.add_event(runtime_state, f"Unbekannter RFID-Tag: {uid}", "warning")
        runtime_state = self.update_hardware_profile(runtime_state)
        self.save_runtime(runtime_state)
        return {"ok": False, "runtime": runtime_state, "player": player}

    def trigger_button(self, name, press_type="kurz"):
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
            result = self.set_volume(5)
            result["runtime"]["hardware"]["last_button"] = last_button
            result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
            self.save_runtime(result["runtime"])
            return result
        if normalized == "lautstärke -":
            result = self.set_volume(-5)
            result["runtime"]["hardware"]["last_button"] = last_button
            result["runtime"]["hardware"]["last_button_press_type"] = last_press_type
            self.save_runtime(result["runtime"])
            return result
        if normalized == "sleep timer +":
            current_level = int(runtime_state.get("sleep_timer", {}).get("level", 0))
            runtime_state = self.set_sleep_level(min(3, current_level + 1))
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
        if normalized in {"power on/off", "sleep/power"}:
            runtime_state["powered_on"] = not runtime_state.get("powered_on", True)
            runtime_state["playback_state"] = "paused" if runtime_state["powered_on"] else "stopped"
            runtime_state = self.add_event(runtime_state, "Power an" if runtime_state["powered_on"] else "Power aus")

        runtime_state = self.update_led_status(runtime_state)
        runtime_state = self.update_hardware_profile(runtime_state)
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
        for button in setup.get("buttons", []):
            if button.get("pin", "").strip() == pin:
                if button.get("press_type", "kurz") != press_type:
                    continue
                runtime_state = self.add_event(runtime_state, f"GPIO erkannt: {pin} -> {button.get('name', '')}")
                self.save_runtime(runtime_state)
                return self.trigger_button(button.get("name", ""), press_type)

        runtime_state = self.add_event(runtime_state, f"GPIO erkannt ohne Zuordnung: {pin} ({press_type})", "warning")
        self.save_runtime(runtime_state)
        return {"runtime": runtime_state, "player": self.load_player()}

    def status(self):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
        runtime_state = self._refresh_sleep_step(runtime_state)
        runtime_state, player, _ = self._sync_playback_session(runtime_state, player)
        runtime_state = self.update_hardware_profile(runtime_state)
        runtime_state = self.update_led_status(runtime_state)
        self.save_player(player)
        self.save_runtime(runtime_state)
        return {
            "runtime": runtime_state,
            "player": player,
            "settings": self.load_settings(),
            "setup": self.load_setup(),
        }
