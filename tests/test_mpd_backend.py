import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.audio_backends.mpd_backend import MPDAudioBackend


class _Completed:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr


class MPDAudioBackendTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.album_dir = self.base_dir / "media" / "albums" / "test"
        self.album_dir.mkdir(parents=True, exist_ok=True)
        (self.album_dir / "playlist.m3u").write_text("01-start.mp3\n02-next.mp3\n", encoding="utf-8")
        (self.album_dir / "01-start.mp3").write_bytes(b"")
        (self.album_dir / "02-next.mp3").write_bytes(b"")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_open_track_queues_playlist_and_syncs_current_index(self):
        commands = []

        def fake_run(cmd, check, capture_output, text):
            commands.append(cmd)
            if cmd[-1] == "status":
                return _Completed(stdout="Testtrack\n[paused] #2/2   0:00/3:05 (0%)\nvolume: 45%   repeat: off\n")
            if cmd[-3:] == ["%file%", "current"]:
                return _Completed(stdout="media/albums/test/02-next.mp3\n")
            return _Completed(stdout="")

        with patch("runtime.audio.BASE_DIR", self.base_dir), patch(
            "services.audio_backends.mpd_backend.shutil.which", return_value="/usr/bin/mpc"
        ), patch(
            "services.audio_backends.mpd_backend.subprocess.run", side_effect=fake_run
        ):
            backend = MPDAudioBackend({"mpd_music_directory": str(self.base_dir)})
            session = backend.open_track(
                "media/albums/test/playlist.m3u",
                "02-next.mp3",
                volume=45,
                current_index=1,
                entries=["01-start.mp3", "02-next.mp3"],
            )

        self.assertEqual(session["backend"], "mpd")
        self.assertEqual(session["state"], "paused")
        self.assertEqual(session["current_index"], 1)
        self.assertEqual(session["entry"], "02-next.mp3")
        self.assertEqual(
            session["queue_paths"],
            ["media/albums/test/01-start.mp3", "media/albums/test/02-next.mp3"],
        )
        self.assertIn(["mpc", "--port", "6600", "clear"], commands)
        self.assertIn(["mpc", "--port", "6600", "add", "media/albums/test/01-start.mp3"], commands)
        self.assertIn(["mpc", "--port", "6600", "add", "media/albums/test/02-next.mp3"], commands)

    def test_play_seeks_from_stored_position(self):
        commands = []

        def fake_run(cmd, check, capture_output, text):
            commands.append(cmd)
            if cmd[-1] == "status":
                return _Completed(stdout="Track\n[playing] #2/2   0:37/3:05 (20%)\nvolume: 30%   repeat: off\n")
            if cmd[-3:] == ["%file%", "current"]:
                return _Completed(stdout="media/albums/test/02-next.mp3\n")
            return _Completed(stdout="")

        with patch("services.audio_backends.mpd_backend.shutil.which", return_value="/usr/bin/mpc"), patch(
            "services.audio_backends.mpd_backend.subprocess.run", side_effect=fake_run
        ):
            backend = MPDAudioBackend({"mpd_music_directory": str(self.base_dir)})
            session = backend.play(
                {
                    "backend": "mpd",
                    "state": "paused",
                    "playlist_entries": ["01-start.mp3", "02-next.mp3"],
                    "queue_paths": ["media/albums/test/01-start.mp3", "media/albums/test/02-next.mp3"],
                    "current_index": 1,
                    "position_seconds": 37,
                    "volume": 30,
                }
            )

        self.assertEqual(session["state"], "playing")
        self.assertEqual(session["position_seconds"], 37)
        self.assertIn(["mpc", "--port", "6600", "play"], commands)
        self.assertIn(["mpc", "--port", "6600", "seek", "0:37"], commands)

    def test_pause_uses_mpc_pause_without_argument(self):
        commands = []

        def fake_run(cmd, check, capture_output, text):
            commands.append(cmd)
            if cmd[-1] == "status":
                return _Completed(stdout="Track\n[paused] #1/2   0:12/3:05 (6%)\nvolume: 30%   repeat: off\n")
            if cmd[-3:] == ["%file%", "current"]:
                return _Completed(stdout="media/albums/test/01-start.mp3\n")
            return _Completed(stdout="")

        with patch("services.audio_backends.mpd_backend.shutil.which", return_value="/usr/bin/mpc"), patch(
            "services.audio_backends.mpd_backend.subprocess.run", side_effect=fake_run
        ):
            backend = MPDAudioBackend({"mpd_music_directory": str(self.base_dir)})
            session = backend.pause(
                {
                    "backend": "mpd",
                    "state": "playing",
                    "playlist_entries": ["01-start.mp3", "02-next.mp3"],
                    "queue_paths": ["media/albums/test/01-start.mp3", "media/albums/test/02-next.mp3"],
                    "current_index": 0,
                    "position_seconds": 12,
                }
            )

        self.assertEqual(session["state"], "paused")
        self.assertIn(["mpc", "--port", "6600", "pause"], commands)

    def test_status_reports_missing_mpc_binary(self):
        with patch("services.audio_backends.mpd_backend.shutil.which", return_value=None):
            backend = MPDAudioBackend()
            status = backend.status()

        self.assertFalse(status["system_ready"])
        self.assertIn("ist nicht installiert", status["message"])
