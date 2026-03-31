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
                    "read_behavior": "play",
                    "remove_behavior": "stop",
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

        self.patchers = [
            patch.object(service_module, "PLAYER_FILE", self.data_dir / "player_state.json"),
            patch.object(service_module, "LIBRARY_FILE", self.data_dir / "library.json"),
            patch.object(service_module, "SETTINGS_FILE", self.data_dir / "settings.json"),
            patch.object(service_module, "SETUP_FILE", self.data_dir / "setup.json"),
            patch.object(service_module, "RUNTIME_FILE", self.data_dir / "runtime_state.json"),
            patch.object(audio_module, "BASE_DIR", self.base_dir),
            patch.object(playback_module, "BASE_DIR", self.base_dir),
            patch.object(playback_module.shutil, "which", return_value=None),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.service = service_module.RuntimeService()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

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


if __name__ == "__main__":
    unittest.main()
