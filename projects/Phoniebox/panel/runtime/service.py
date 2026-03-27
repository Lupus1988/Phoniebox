import json
import secrets
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.manager import detect_hardware
from runtime.audio import build_track_queue, load_playlist_entries, pick_track_duration, track_title_from_entry
from runtime.playback import PlaybackController

DATA_DIR = BASE_DIR / "data"
PLAYER_FILE = DATA_DIR / "player_state.json"
LIBRARY_FILE = DATA_DIR / "library.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SETUP_FILE = DATA_DIR / "setup.json"
RUNTIME_FILE = DATA_DIR / "runtime_state.json"


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    tmp.replace(path)


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


class RuntimeService:
    def __init__(self):
        self.runtime_path = RUNTIME_FILE
        self.playback = PlaybackController()

    def load_runtime(self):
        return load_json(self.runtime_path, default_runtime_state())

    def save_runtime(self, state):
        save_json(self.runtime_path, state)

    def load_player(self):
        return load_json(PLAYER_FILE, {})

    def save_player(self, state):
        save_json(PLAYER_FILE, state)

    def load_library(self):
        return load_json(LIBRARY_FILE, {"albums": []})

    def load_settings(self):
        return load_json(SETTINGS_FILE, {})

    def load_setup(self):
        return load_json(SETUP_FILE, {})

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
        setup = self.load_setup()
        settings = self.load_settings()
        reader = setup.get("reader", {})
        return {
            "read": reader.get("read_behavior", settings.get("rfid_read_action", "play")),
            "remove": reader.get("remove_behavior", settings.get("rfid_remove_action", "stop")),
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
            runtime_state["playback_session"] = self.playback.open_track(album.get("playlist", ""), entries[0], 0)
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

        if runtime_state.get("powered_on", True) and runtime_state.get("playback_state") == "playing":
            duration = int(player.get("duration_seconds", 0))
            position = int(player.get("position_seconds", 0))
            player["position_seconds"] = min(duration, position + elapsed_seconds)
            if player["position_seconds"] >= duration and duration > 0:
                runtime_state = self.next_track(runtime_state=runtime_state, player=player, autoplay=True)
            elif runtime_state.get("playback_session"):
                runtime_state["playback_session"]["position_seconds"] = player["position_seconds"]

        remaining = int(runtime_state.get("sleep_timer", {}).get("remaining_seconds", 0))
        if remaining > 0:
            remaining = max(0, remaining - elapsed_seconds)
            runtime_state["sleep_timer"]["remaining_seconds"] = remaining
            if remaining == 0:
                runtime_state["playback_state"] = "paused"
                player["is_playing"] = False
                runtime_state["last_event"] = "Sleeptimer abgelaufen"
                runtime_state["last_event_at"] = int(time.time())
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

    def toggle_playback(self):
        runtime_state = self.ensure_runtime()
        player = self.load_player()
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
            )
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
        runtime_state = self.ensure_runtime()
        runtime_state = self.add_event(runtime_state, f"Lautstärke {player['volume']}%")
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
        if normalized == "sleep/power":
            if press_type == "lang":
                runtime_state["powered_on"] = not runtime_state.get("powered_on", True)
                runtime_state["playback_state"] = "paused" if runtime_state["powered_on"] else "stopped"
                runtime_state = self.add_event(runtime_state, "Power an" if runtime_state["powered_on"] else "Power aus")
            else:
                current_level = int(runtime_state.get("sleep_timer", {}).get("level", 0))
                next_level = 0 if current_level >= 3 else current_level + 1
                runtime_state = self.set_sleep_level(next_level)
                runtime_state["hardware"]["last_button"] = last_button
                runtime_state["hardware"]["last_button_press_type"] = last_press_type
                self.save_runtime(runtime_state)
                return {"runtime": runtime_state, "player": self.load_player()}

        runtime_state = self.update_led_status(runtime_state)
        runtime_state = self.update_hardware_profile(runtime_state)
        self.save_runtime(runtime_state)
        return {"runtime": runtime_state, "player": self.load_player()}

    def trigger_gpio_pin(self, pin, press_type="kurz"):
        setup = self.load_setup()
        runtime_state = self.ensure_runtime()
        runtime_state["hardware"]["pressed_buttons"] = [pin] if pin else []
        for button in setup.get("buttons", []):
            if button.get("pin", "").strip() == pin:
                runtime_state = self.add_event(runtime_state, f"GPIO erkannt: {pin} -> {button.get('name', '')}")
                self.save_runtime(runtime_state)
                return self.trigger_button(button.get("name", ""), press_type)

        runtime_state = self.add_event(runtime_state, f"GPIO erkannt ohne Zuordnung: {pin}", "warning")
        self.save_runtime(runtime_state)
        return {"runtime": runtime_state, "player": self.load_player()}

    def status(self):
        runtime_state = self.ensure_runtime()
        runtime_state = self.update_hardware_profile(runtime_state)
        player = self.load_player()
        runtime_state = self.update_led_status(runtime_state)
        self.save_runtime(runtime_state)
        return {
            "runtime": runtime_state,
            "player": player,
            "settings": self.load_settings(),
            "setup": self.load_setup(),
        }
