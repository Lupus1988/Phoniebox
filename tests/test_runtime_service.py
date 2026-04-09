import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import audio as audio_module
from runtime import playback as playback_module
from runtime import service as service_module


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class RuntimeServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.data_dir = self.base_dir / "data"
        self.media_dir = self.base_dir / "media" / "albums"
        self.album_dir = self.media_dir / "test-album"
        self.album_dir_2 = self.media_dir / "queue-album"
        self.album_dir.mkdir(parents=True, exist_ok=True)
        self.album_dir_2.mkdir(parents=True, exist_ok=True)

        (self.album_dir / "playlist.m3u").write_text("#EXTM3U\n01-start.mp3\n02-weiter.mp3\n", encoding="utf-8")
        (self.album_dir_2 / "playlist.m3u").write_text("#EXTM3U\n03-bonus.mp3\n", encoding="utf-8")
        (self.album_dir / "01-start.mp3").write_bytes(b"")
        (self.album_dir / "02-weiter.mp3").write_bytes(b"")
        (self.album_dir_2 / "03-bonus.mp3").write_bytes(b"")

        write_json(
            self.data_dir / "player_state.json",
            {
                "current_album": "",
                "current_track": "",
                "cover_url": "",
                "volume": 45,
                "position_seconds": 0,
                "duration_seconds": 0,
                "sleep_timer_minutes": 0,
                "is_playing": False,
                "queue": [],
                "playlist": "",
                "playlist_entries": [],
                "current_track_index": 0,
            },
        )
        write_json(
            self.data_dir / "settings.json",
            {
                "max_volume": 85,
                "volume_step": 5,
                "sleep_timer_step": 5,
                "rfid_read_action": "play",
                "rfid_remove_action": "stop",
                "reader_mode": "album_load",
            },
        )
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {
                    "type": "USB",
                    "connection_hint": "",
                },
                "buttons": [],
                "leds": [],
                "wifi": {},
            },
        )
        write_json(
            self.data_dir / "library.json",
            {
                "albums": [
                    {
                        "id": "album-1",
                        "name": "Testalbum",
                        "folder": "media/albums/test-album",
                        "playlist": "media/albums/test-album/playlist.m3u",
                        "track_count": 2,
                        "rfid_uid": "1234567890",
                        "cover_url": "",
                    },
                    {
                        "id": "album-2",
                        "name": "Queuealbum",
                        "folder": "media/albums/queue-album",
                        "playlist": "media/albums/queue-album/playlist.m3u",
                        "track_count": 1,
                        "rfid_uid": "",
                        "cover_url": "",
                    },
                ]
            },
        )
        write_json(self.data_dir / "runtime_state.json", service_module.default_runtime_state())
        write_json(self.data_dir / "button_detect.json", service_module.default_button_detect())

        self.patchers = [
            patch.object(service_module, "PLAYER_FILE", self.data_dir / "player_state.json"),
            patch.object(service_module, "LIBRARY_FILE", self.data_dir / "library.json"),
            patch.object(service_module, "SETTINGS_FILE", self.data_dir / "settings.json"),
            patch.object(service_module, "SETUP_FILE", self.data_dir / "setup.json"),
            patch.object(service_module, "RUNTIME_FILE", self.data_dir / "runtime_state.json"),
            patch.object(service_module, "BUTTON_DETECT_FILE", self.data_dir / "button_detect.json"),
            patch.object(audio_module, "BASE_DIR", self.base_dir),
            patch.object(playback_module, "BASE_DIR", self.base_dir),
            patch.object(playback_module.shutil, "which", return_value=None),
            patch.object(service_module, "pick_track_duration", return_value=180),
            patch.object(service_module, "set_wifi_radio", return_value={"ok": True, "details": ["ok"]}),
            patch.object(service_module, "wifi_radio_enabled", return_value=True),
            patch.object(service_module.subprocess, "run"),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.service = service_module.RuntimeService()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_runtime_service_uses_audio_backend_factory(self):
        self.assertIs(self.service.playback, self.service.audio_backend)

    def test_load_album_by_id_autoplay_populates_player(self):
        result = self.service.load_album_by_id("album-1", autoplay=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["runtime"]["playback_state"], "playing")
        self.assertEqual(result["player"]["current_album"], "Testalbum")
        self.assertEqual(result["player"]["current_track"], "01 start")
        self.assertEqual(result["player"]["queue"], ["02 weiter"])
        self.assertEqual(result["runtime"]["playback_session"]["backend"], "mock")

    def test_queue_seek_and_clear_queue_work_without_hardware(self):
        self.service.load_album_by_id("album-1", autoplay=False)
        queued = self.service.queue_album_by_id("album-2")
        sought = self.service.seek(37)
        cleared = self.service.clear_queue()

        self.assertTrue(queued["ok"])
        self.assertIn("03 bonus", queued["player"]["queue"])
        self.assertEqual(sought["player"]["position_seconds"], 37)
        self.assertEqual(cleared["player"]["queue"], [])

    def test_remove_rfid_stop_resets_position_and_session(self):
        started = self.service.assign_album_by_rfid("1234567890")
        self.service.seek(37)

        removed = self.service.remove_rfid_tag()

        self.assertTrue(started["ok"])
        self.assertEqual(removed["runtime"]["playback_state"], "stopped")
        self.assertEqual(removed["player"]["position_seconds"], 0)
        self.assertEqual(removed["runtime"]["active_rfid_uid"], "")
        self.assertEqual(removed["runtime"]["playback_session"]["state"], "stopped")
        self.assertFalse(removed["player"]["is_playing"])

    def test_remove_rfid_pause_uses_settings_and_preserves_position(self):
        write_json(
            self.data_dir / "settings.json",
            {
                "max_volume": 85,
                "volume_step": 5,
                "sleep_timer_step": 5,
                "rfid_read_action": "play",
                "rfid_remove_action": "pause",
            },
        )
        self.service.assign_album_by_rfid("1234567890")
        self.service.seek(37)

        removed = self.service.remove_rfid_tag()

        self.assertEqual(removed["runtime"]["playback_state"], "paused")
        self.assertEqual(removed["player"]["position_seconds"], 37)
        self.assertEqual(removed["runtime"]["active_rfid_uid"], "")
        self.assertEqual(removed["runtime"]["playback_session"]["state"], "paused")
        self.assertFalse(removed["player"]["is_playing"])

    def test_repeated_presence_rfid_scan_does_not_reload_same_album(self):
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {
                    "type": "RC522",
                    "connection_hint": "",
                },
                "buttons": [],
                "leds": [],
                "wifi": {},
            },
        )

        with patch.object(self.service, "load_album_into_player", wraps=self.service.load_album_into_player) as load_album:
            first = self.service.assign_album_by_rfid("1234567890")
            second = self.service.assign_album_by_rfid("1234567890")

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(load_album.call_count, 1)
        self.assertEqual(second["runtime"]["active_rfid_uid"], "1234567890")

    def test_presence_rfid_resumes_paused_same_album_instead_of_reloading(self):
        write_json(
            self.data_dir / "settings.json",
            {
                "max_volume": 85,
                "volume_step": 5,
                "sleep_timer_step": 5,
                "rfid_read_action": "play",
                "rfid_remove_action": "pause",
            },
        )
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {
                    "type": "RC522",
                    "connection_hint": "",
                },
                "buttons": [],
                "leds": [],
                "wifi": {},
            },
        )

        self.service.assign_album_by_rfid("1234567890")
        self.service.seek(37)
        self.service.remove_rfid_tag()

        with patch.object(self.service, "load_album_into_player", wraps=self.service.load_album_into_player) as load_album:
            resumed = self.service.assign_album_by_rfid("1234567890")

        self.assertTrue(resumed["ok"])
        self.assertEqual(load_album.call_count, 0)
        self.assertEqual(resumed["runtime"]["playback_state"], "playing")
        self.assertEqual(resumed["runtime"]["active_album_id"], "album-1")
        self.assertEqual(resumed["runtime"]["active_rfid_uid"], "1234567890")
        self.assertEqual(resumed["player"]["position_seconds"], 37)
        self.assertEqual(resumed["runtime"]["playback_session"]["position_seconds"], 37)

    def test_sync_playback_session_updates_current_track_from_mpv_playlist_position(self):
        self.service.load_album_by_id("album-1", autoplay=True)
        runtime_state = self.service.ensure_runtime()
        player = self.service.load_player()
        runtime_state["playback_state"] = "playing"
        runtime_state["playback_session"] = {
            **runtime_state["playback_session"],
            "backend": "mpv",
            "state": "playing",
            "current_index": 1,
            "position_seconds": 12,
            "duration_seconds": 222,
        }

        with patch.object(self.service.playback, "sync_session", return_value=dict(runtime_state["playback_session"])):
            with patch.object(service_module, "pick_track_duration", return_value=0):
                runtime_state, player, session_finished = self.service._sync_playback_session(runtime_state, player)

        self.assertFalse(session_finished)
        self.assertEqual(player["current_track_index"], 1)
        self.assertEqual(player["current_track"], "02 weiter")
        self.assertEqual(player["queue"], [])
        self.assertEqual(player["duration_seconds"], 222)
        self.assertEqual(player["position_seconds"], 12)

    def test_reader_behavior_comes_from_settings_only(self):
        write_json(
            self.data_dir / "settings.json",
            {
                "max_volume": 85,
                "volume_step": 5,
                "sleep_timer_step": 5,
                "rfid_read_action": "queue_append",
                "rfid_remove_action": "pause",
            },
        )
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {
                    "type": "USB",
                    "connection_hint": "",
                    "read_behavior": "play",
                    "remove_behavior": "stop",
                },
                "buttons": [],
                "leds": [],
                "wifi": {},
            },
        )

        behavior = self.service.get_reader_behavior()

        self.assertEqual(behavior["read"], "queue_append")
        self.assertEqual(behavior["remove"], "pause")

    def test_reset_state_returns_clean_runtime(self):
        self.service.load_album_by_id("album-1", autoplay=True)
        self.service.queue_album_by_id("album-2")

        reset = self.service.reset_state()

        self.assertEqual(reset["runtime"]["playback_state"], "stopped")
        self.assertFalse(reset["runtime"]["powered_on"])
        self.assertEqual(reset["runtime"]["active_album_id"], "")
        self.assertEqual(reset["player"]["current_album"], "")
        self.assertEqual(reset["player"]["queue"], [])
        self.assertEqual(reset["runtime"]["last_event"], "Runtime zurückgesetzt")

    def test_power_toggle_stops_playback_and_clears_sleep_timer(self):
        self.service.load_album_by_id("album-1", autoplay=True)
        self.service.set_sleep_level(3)

        with patch.object(self.service, "play_system_sound", return_value={"ok": True, "details": ["ok"]}) as play_sound:
            powered_off = self.service.trigger_button("Power on/off", press_type="lang")
            powered_on = self.service.trigger_button("Power on/off", press_type="lang")

        self.assertFalse(powered_off["runtime"]["powered_on"])
        self.assertEqual(powered_off["runtime"]["playback_state"], "stopped")
        self.assertEqual(powered_off["runtime"]["sleep_timer"]["remaining_seconds"], 0)
        self.assertEqual(powered_off["runtime"]["sleep_timer"]["level"], 0)
        self.assertFalse(powered_off["player"]["is_playing"])
        self.assertEqual(powered_off["player"]["position_seconds"], 0)
        self.assertEqual(powered_off["runtime"]["last_event"], "Standby aktiv")

        self.assertTrue(powered_on["runtime"]["powered_on"])
        self.assertEqual(powered_on["runtime"]["playback_state"], "paused")
        self.assertFalse(powered_on["player"]["is_playing"])
        self.assertEqual(powered_on["runtime"]["last_event"], "Power an")
        self.assertEqual(play_sound.call_count, 2)
        self.assertEqual(play_sound.call_args_list[0].args[0], "power_off")
        self.assertEqual(play_sound.call_args_list[1].args[0], "power_on")

    def test_duplicate_power_off_does_not_replay_power_off_sound(self):
        self.service.power_off()

        with patch.object(self.service, "play_system_sound", return_value={"ok": True, "details": ["ok"]}) as play_sound:
            result = self.service.power_off()

        self.assertFalse(result["runtime"]["powered_on"])
        play_sound.assert_not_called()

    def test_system_sound_uses_current_player_volume(self):
        write_json(
            self.data_dir / "player_state.json",
            {
                "current_album": "",
                "current_track": "",
                "cover_url": "",
                "volume": 23,
                "muted": False,
                "volume_before_mute": 45,
                "position_seconds": 0,
                "duration_seconds": 0,
                "sleep_timer_minutes": 0,
                "is_playing": False,
                "queue": [],
                "playlist": "",
                "playlist_entries": [],
                "current_track_index": 0,
            },
        )
        with patch.object(self.service.playback, "play_preview", return_value={"ok": True, "details": ["ok"]}) as preview:
            result = self.service.play_system_sound("test")
        self.assertTrue(result["ok"])
        self.assertEqual(preview.call_args.kwargs["volume"], 23)

    def test_hardware_profile_detection_is_cached_within_ttl(self):
        with patch.object(service_module, "detect_hardware", return_value=service_module.detect_hardware({}, {"albums": []})) as detect:
            runtime_state = self.service.ensure_runtime()

            self.service.update_hardware_profile(runtime_state)
            self.service.update_hardware_profile(runtime_state)

        self.assertEqual(detect.call_count, 1)

    def test_poll_buttons_ignores_reader_reserved_pins(self):
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {"type": "RC522", "connection_hint": ""},
                "audio": {"output_mode": "usb_dac"},
                "hardware_buttons_enabled": True,
                "buttons": [
                    {"id": "btn-1", "name": "Play/Pause", "pin": "GPIO25", "press_type": "kurz"},
                    {"id": "btn-2", "name": "Stopp", "pin": "GPIO17", "press_type": "kurz"},
                ],
                "leds": [],
                "wifi": {},
            },
        )

        with patch.object(self.service, "_read_gpio_levels", return_value={"GPIO17": 1}) as read_gpio:
            self.service.poll_buttons_once(now=123.0)

        read_gpio.assert_called_once_with(["GPIO17"])

    def test_update_led_status_ignores_reader_reserved_pins(self):
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {"type": "RC522", "connection_hint": ""},
                "audio": {"output_mode": "usb_dac"},
                "buttons": [],
                "leds": [
                    {"id": "led-1", "name": "Power", "pin": "GPIO25", "function": "power_on", "brightness": 50},
                    {"id": "led-2", "name": "Wifi", "pin": "GPIO17", "function": "wifi_on", "brightness": 55},
                ],
                "wifi": {},
            },
        )

        runtime_state = self.service.ensure_runtime()
        runtime_state = self.service.update_led_status(runtime_state)

        self.assertEqual([entry["pin"] for entry in runtime_state["led_status"]], ["GPIO17"])

    @patch.object(service_module.time, "sleep", return_value=None)
    def test_sleep_timer_expiry_fades_out_and_enters_standby(self, _sleep):
        self.service.load_album_by_id("album-1", autoplay=True)
        self.service.set_sleep_level(1)

        result = self.service.tick(elapsed_seconds=300)

        self.assertFalse(result["runtime"]["powered_on"])
        self.assertEqual(result["runtime"]["playback_state"], "stopped")
        self.assertEqual(result["runtime"]["sleep_timer"]["level"], 0)
        self.assertEqual(result["runtime"]["last_event"], "Sleeptimer abgelaufen, Standby aktiv")

    def test_standby_led_only_lights_in_standby(self):
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {"type": "USB", "connection_hint": ""},
                "buttons": [],
                "leds": [
                    {"id": "led-1", "name": "Power", "pin": "GPIO12", "function": "power_on", "brightness": 50},
                    {"id": "led-2", "name": "Standby", "pin": "GPIO13", "function": "standby", "brightness": 30},
                ],
                "power_routines": {"power_on": "sleep_count_up_5", "power_off": "sleep_count_down_5"},
                "audio": {"output_mode": "usb_dac", "i2s_profile": "auto"},
                "wifi": {},
            },
        )
        runtime_state = self.service.ensure_runtime()
        runtime_state["powered_on"] = True
        runtime_state["playback_state"] = "paused"
        runtime_state = self.service.update_led_status(runtime_state)
        led_map = {entry["name"]: entry["is_on"] for entry in runtime_state["led_status"]}
        self.assertFalse(led_map["Standby"])

        standby_state = self.service.power_off()["runtime"]
        led_map = {entry["name"]: entry["is_on"] for entry in standby_state["led_status"]}
        self.assertTrue(led_map["Standby"])

    def test_wifi_toggle_button_controls_wifi_when_enabled_in_setup(self):
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {"type": "USB", "connection_hint": ""},
                "buttons": [{"id": "btn-1", "name": "Wifi on/off", "pin": "GPIO17", "press_type": "kurz"}],
                "leds": [{"id": "led-1", "name": "Wifi", "pin": "GPIO12", "function": "wifi_on", "brightness": 55}],
                "power_routines": {"power_on": "sleep_count_up_5", "power_off": "sleep_count_down_5"},
                "audio": {"output_mode": "usb_dac", "i2s_profile": "auto"},
                "wifi": {"allow_button_toggle": True},
            },
        )

        first = self.service.trigger_button("Wifi on/off", press_type="kurz")
        second = self.service.trigger_button("Wifi on/off", press_type="kurz")

        self.assertFalse(first["runtime"]["wifi_enabled"])
        self.assertEqual(first["runtime"]["last_event"], "Wifi aus")
        self.assertTrue(second["runtime"]["wifi_enabled"])
        self.assertEqual(second["runtime"]["last_event"], "Wifi an")

    def test_hardware_volume_buttons_use_configured_step_size(self):
        write_json(
            self.data_dir / "settings.json",
            {
                "max_volume": 85,
                "volume_step": 7,
                "sleep_timer_step": 5,
                "rfid_read_action": "play",
                "rfid_remove_action": "stop",
                "reader_mode": "album_load",
            },
        )
        lowered = self.service.trigger_button("Lautstärke -", press_type="kurz")
        raised = self.service.trigger_button("Lautstärke +", press_type="kurz")
        self.assertEqual(lowered["player"]["volume"], 38)
        self.assertEqual(raised["player"]["volume"], 45)

    def test_sleep_timer_plus_rotates_to_zero_when_enabled(self):
        write_json(
            self.data_dir / "settings.json",
            {
                "max_volume": 85,
                "volume_step": 5,
                "sleep_timer_step": 5,
                "sleep_timer_button_rotation": True,
                "rfid_read_action": "play",
                "rfid_remove_action": "stop",
                "reader_mode": "album_load",
            },
        )
        one = self.service.trigger_button("Sleep Timer +", press_type="kurz")
        two = self.service.trigger_button("Sleep Timer +", press_type="kurz")
        three = self.service.trigger_button("Sleep Timer +", press_type="kurz")
        zero = self.service.trigger_button("Sleep Timer +", press_type="kurz")
        self.assertEqual(one["runtime"]["sleep_timer"]["level"], 1)
        self.assertEqual(two["runtime"]["sleep_timer"]["level"], 2)
        self.assertEqual(three["runtime"]["sleep_timer"]["level"], 3)
        self.assertEqual(zero["runtime"]["sleep_timer"]["level"], 0)

    def test_sleep_timer_plus_stops_at_three_when_rotation_disabled(self):
        one = self.service.trigger_button("Sleep Timer +", press_type="kurz")
        two = self.service.trigger_button("Sleep Timer +", press_type="kurz")
        three = self.service.trigger_button("Sleep Timer +", press_type="kurz")
        still_three = self.service.trigger_button("Sleep Timer +", press_type="kurz")
        self.assertEqual(one["runtime"]["sleep_timer"]["level"], 1)
        self.assertEqual(two["runtime"]["sleep_timer"]["level"], 2)
        self.assertEqual(three["runtime"]["sleep_timer"]["level"], 3)
        self.assertEqual(still_three["runtime"]["sleep_timer"]["level"], 3)

    def test_sleep_timer_cannot_be_started_in_standby(self):
        self.service.power_off()
        result = self.service.set_sleep_level(1)
        self.assertEqual(result["sleep_timer"]["level"], 0)
        self.assertEqual(result["last_event"], "Sleeptimer im Standby nicht verfügbar")

    def test_gpio_buttons_can_be_disabled_in_setup(self):
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {"type": "USB", "connection_hint": ""},
                "hardware_buttons_enabled": False,
                "buttons": [{"id": "btn-1", "name": "Lautstärke +", "pin": "GPIO17", "press_type": "kurz"}],
                "leds": [],
                "wifi": {},
            },
        )

        result = self.service.trigger_gpio_pin("GPIO17", press_type="kurz")

        self.assertEqual(result["player"]["volume"], 45)
        self.assertEqual(result["runtime"]["last_event"], "Hardwaretasten deaktiviert")

    @patch.object(service_module, "sample_gpio_levels_pinctrl", return_value={"GPIO17": 0})
    @patch.object(service_module, "GPIO", None)
    def test_read_gpio_levels_uses_pinctrl_fallback_when_gpio_backend_missing(self, _sample_pinctrl):
        levels = self.service._read_gpio_levels(["GPIO17"])

        self.assertEqual(levels, {"GPIO17": 0})

    def test_power_hold_uses_smooth_power_effect_metadata(self):
        write_json(
            self.data_dir / "setup.json",
            {
                "reader": {"type": "USB", "connection_hint": ""},
                "buttons": [],
                "leds": [
                    {"id": "led-1", "name": "Power", "pin": "GPIO12", "function": "power_on", "brightness": 50},
                    {"id": "led-2", "name": "Standby", "pin": "GPIO13", "function": "standby", "brightness": 30},
                ],
                "power_routines": {"power_on": "power_flicker_up_5", "power_off": "power_flicker_down_5"},
                "wifi": {},
            },
        )
        runtime_state = self.service.ensure_runtime()
        runtime_state["powered_on"] = False
        runtime_state["power_hold"] = {
            "pressed": True,
            "seconds": 2.5,
            "mode": "pending_on",
            "pin": "GPIO17",
            "started_at": 10.0,
            "threshold_seconds": 5.0,
            "routine_id": "power_flicker_up_5",
            "animation": "power_flicker_up",
            "completed": False,
        }

        runtime_state = self.service.update_led_status(runtime_state)

        power_led = next(entry for entry in runtime_state["led_status"] if entry["name"] == "Power")
        self.assertTrue(power_led["is_on"])
        self.assertEqual(power_led["effect"], "power_ramp_up")
        self.assertEqual(power_led["effect_progress"], 0.5)


if __name__ == "__main__":
    unittest.main()
