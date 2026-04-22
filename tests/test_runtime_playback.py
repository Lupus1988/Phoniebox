import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from runtime import playback as playback_module
from services.audio_backends import CurrentAudioBackend, MPDAudioBackend, create_audio_backend


class PlaybackControllerTest(unittest.TestCase):
    def setUp(self):
        self.controller = playback_module.PlaybackController()

    def test_audio_backend_factory_returns_current_backend_by_default(self):
        backend = create_audio_backend()

        self.assertIsInstance(backend, CurrentAudioBackend)

    def test_audio_backend_factory_can_create_mpd_placeholder(self):
        backend = create_audio_backend("mpd")

        self.assertIsInstance(backend, MPDAudioBackend)
        status = backend.status()
        self.assertEqual(status["active_backend"], "mpd")
        self.assertFalse(status["system_ready"])


    def test_build_command_for_mpv_uses_start_time_and_volume(self):
        with patch.object(playback_module, "configured_alsa_device", return_value="alsa/plughw:1,0"):
            command = self.controller._build_command("mpv", "/tmp/test.mp3", position_seconds=37, volume=50)

        self.assertEqual(command[:4], ["mpv", "--no-video", "--really-quiet", "--audio-display=no"])
        self.assertIn("--ao=alsa", command)
        self.assertIn("--audio-device=alsa/plughw:1,0", command)
        self.assertIn("--cache=yes", command)
        self.assertIn("--audio-buffer=0.2", command)
        self.assertIn("--demuxer-readahead-secs=2", command)
        self.assertIn("--volume=50", command)
        self.assertIn("--start=37", command)
        self.assertEqual(command[-1], "/tmp/test.mp3")

    def test_build_playlist_command_for_mpv_uses_playlist_start(self):
        with patch.object(playback_module, "configured_alsa_device", return_value="alsa/plughw:1,0"):
            command = self.controller._build_mpv_playlist_command("/tmp/test.m3u", current_index=2, position_seconds=11, volume=50)

        self.assertIn("--ao=alsa", command)
        self.assertIn("--audio-device=alsa/plughw:1,0", command)
        self.assertIn("--playlist-start=2", command)
        self.assertIn("--start=11", command)
        self.assertIn("--playlist=/tmp/test.m3u", command)

    def test_mpv_alsa_device_uses_plughw_for_resampling(self):
        self.assertEqual(playback_module._mpv_alsa_device("hw:0,0"), "alsa/plughw:0,0")
        self.assertEqual(playback_module._mpv_alsa_device("plughw:1,0"), "alsa/plughw:1,0")
        self.assertEqual(playback_module._mpv_alsa_device("default"), "alsa/default")

    def test_audio_output_available_requires_configured_usb_card(self):
        snapshot = {
            "cards": [{"card_index": "1", "card_id": "vc4hdmi", "name": "vc4-hdmi"}],
            "playback_devices": [{"card_index": "1", "name": "vc4hdmi", "device_name": "vc4-hdmi"}],
        }

        ready, reason = playback_module._audio_output_available(snapshot, {"output_mode": "usb_dac"})

        self.assertFalse(ready)
        self.assertEqual(reason, "USB-Soundkarte nicht erkannt.")

    def test_audio_output_available_accepts_configured_usb_card(self):
        snapshot = {
            "cards": [{"card_index": "0", "card_id": "Device", "name": "USB2.0 Device"}],
            "playback_devices": [{"card_index": "0", "name": "USB2.0 Device", "device_name": "USB Audio"}],
        }

        ready, reason = playback_module._audio_output_available(snapshot, {"output_mode": "usb_dac"})

        self.assertTrue(ready)
        self.assertEqual(reason, "")

    def test_audio_output_available_rejects_usb_card_without_playback_device(self):
        snapshot = {
            "cards": [{"card_index": "0", "card_id": "Device", "name": "USB2.0 Device"}],
            "playback_devices": [],
        }

        ready, reason = playback_module._audio_output_available(snapshot, {"output_mode": "usb_dac"})

        self.assertFalse(ready)
        self.assertEqual(reason, "USB-Soundkarte ohne nutzbares ALSA-Playback-Gerät.")

    def test_detect_backend_uses_mpv_when_available(self):
        with patch.object(
            playback_module.shutil, "which", side_effect=lambda name: "/usr/bin/" + name if name == "mpv" else None
        ):
            status = playback_module.detect_backend()

        self.assertEqual(status["preferred_backend"], "mpv")
        self.assertEqual(status["active_backend"], "mpv")
        self.assertEqual(status["available_backends"], ["mpv", "mock"])

    def test_detect_backend_uses_mock_when_mpv_is_missing(self):
        with patch.object(playback_module.shutil, "which", return_value=None):
            status = playback_module.detect_backend()

        self.assertEqual(status["preferred_backend"], "mpv")
        self.assertEqual(status["active_backend"], "mock")
        self.assertFalse(status["system_ready"])

    def test_terminate_known_process_reaps_registered_handle(self):
        process = Mock()
        process.pid = 4321
        process.poll.side_effect = [None, None]
        self.controller._processes[process.pid] = process

        with patch.object(self.controller, "_signal_process_group", return_value=True) as signal_group:
            self.controller._terminate_process_group(process.pid)

        process.wait.assert_called_once_with(timeout=0.75)
        self.assertEqual(signal_group.call_args_list[0].args, (process.pid, signal.SIGCONT))
        self.assertEqual(signal_group.call_args_list[1].args, (process.pid, signal.SIGTERM))
        self.assertNotIn(process.pid, self.controller._processes)

    def test_terminate_known_process_kills_after_timeout(self):
        process = Mock()
        process.pid = 9876
        process.poll.side_effect = [None, None]
        process.wait.side_effect = [
            playback_module.subprocess.TimeoutExpired(cmd="mpv", timeout=0.75),
            None,
        ]
        self.controller._processes[process.pid] = process

        with patch.object(self.controller, "_signal_process_group", return_value=True) as signal_group:
            self.controller._terminate_process_group(process.pid)

        self.assertEqual(process.wait.call_args_list[0].kwargs["timeout"], 0.75)
        self.assertEqual(process.wait.call_args_list[1].kwargs["timeout"], 0.5)
        self.assertEqual(signal_group.call_args_list[2].args, (process.pid, signal.SIGKILL))
        self.assertNotIn(process.pid, self.controller._processes)

    def test_launch_reports_error_when_configured_audio_output_is_missing(self):
        session = {
            "backend": "mpv",
            "state": "ready",
            "track_path": "/tmp/test.mp3",
            "position_seconds": 0,
            "volume": 45,
        }

        with patch.object(playback_module, "configured_audio_output_ready", return_value=(False, "USB-Soundkarte nicht erkannt.")):
            with patch.object(playback_module.subprocess, "Popen") as popen:
                updated = self.controller._launch(dict(session))

        popen.assert_not_called()
        self.assertEqual(updated["state"], "error")
        self.assertEqual(updated["error"], "USB-Soundkarte nicht erkannt.")
        self.assertIsNone(updated["pid"])

    def test_set_volume_uses_mpv_ipc_without_relaunch(self):
        session = {
            "backend": "mpv",
            "state": "playing",
            "pid": 1234,
            "socket_path": "/tmp/phoniebox-mpv.sock",
            "position_seconds": 41,
            "started_at": 100.0,
            "volume": 45,
        }

        with patch.object(self.controller, "sync_session", return_value=dict(session)) as sync_session:
            with patch.object(self.controller, "_process_exists", return_value=True):
                with patch.object(self.controller, "_mpv_request", return_value={"error": "success"}) as mpv_request:
                    with patch.object(self.controller, "_terminate_process_group") as terminate_group:
                        with patch.object(self.controller, "_launch") as launch:
                            updated = self.controller.set_volume(dict(session), 52)

        sync_session.assert_called_once()
        mpv_request.assert_called_once_with(updated, ["set_property", "volume", 52])
        terminate_group.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(updated["volume"], 52)
        self.assertEqual(updated["pid"], 1234)
        self.assertEqual(updated["state"], "playing")

    def test_next_track_uses_mpv_playlist_command_without_relaunch(self):
        session = {
            "backend": "mpv",
            "state": "playing",
            "pid": 1234,
            "socket_path": "/tmp/phoniebox-mpv.sock",
            "position_seconds": 4,
            "current_index": 0,
        }

        with patch.object(
            self.controller,
            "sync_session",
            side_effect=[dict(session), {**session, "current_index": 1}, {**session, "current_index": 1}],
        ):
            with patch.object(self.controller, "_process_exists", return_value=True):
                with patch.object(self.controller, "_mpv_request", return_value={"error": "success"}) as mpv_request:
                    updated = self.controller.next_track(dict(session))

        mpv_request.assert_called_once_with(session, ["playlist-next", "force"])
        self.assertEqual(updated["current_index"], 1)

    def test_sync_session_keeps_mpv_running_when_eof_reached_but_not_idle(self):
        session = {
            "backend": "mpv",
            "state": "playing",
            "pid": 1234,
            "socket_path": "/tmp/phoniebox-mpv.sock",
            "position_seconds": 176,
            "duration_seconds": 180,
            "current_index": 0,
            "track_path": "/tmp/test.mp3",
        }

        values = {
            "time-pos": 177,
            "pause": False,
            "idle-active": False,
            "playlist-pos": 0,
            "duration": 180,
            "path": "/tmp/test.mp3",
        }

        with patch.object(self.controller, "_process_exists", return_value=True):
            with patch.object(self.controller, "_mpv_command_succeeded", return_value=True):
                with patch.object(self.controller, "_mpv_get_property", side_effect=lambda current, name, default=None: values.get(name, default)):
                    updated = self.controller.sync_session(dict(session))

        self.assertEqual(updated["state"], "playing")
        self.assertEqual(updated["pid"], 1234)
        self.assertEqual(updated["position_seconds"], 177)

    def test_sync_session_marks_mpv_error_when_ipc_is_unreachable(self):
        session = {
            "backend": "mpv",
            "state": "playing",
            "pid": 1234,
            "socket_path": "/tmp/phoniebox-mpv.sock",
            "position_seconds": 23,
            "started_at": 100.0,
        }

        with patch.object(self.controller, "_process_exists", return_value=True):
            with patch.object(self.controller, "_mpv_command_succeeded", return_value=False):
                updated = self.controller.sync_session(dict(session))

        self.assertEqual(updated["state"], "error")
        self.assertEqual(updated["error"], "mpv IPC nicht erreichbar.")
        self.assertEqual(updated["pid"], 1234)
        self.assertIsNone(updated["started_at"])

    def test_sync_session_relaunches_mpv_when_time_position_stalls(self):
        session = {
            "backend": "mpv",
            "state": "playing",
            "pid": 1234,
            "socket_path": "/tmp/phoniebox-mpv.sock",
            "position_seconds": 33,
            "duration_seconds": 90,
            "current_index": 0,
            "track_path": "/tmp/test.mp3",
            "mpv_health_time_pos": 33.987521,
            "mpv_stall_started_at": 100.0,
        }

        values = {
            "time-pos": 33.987521,
            "pause": False,
            "idle-active": False,
            "playlist-pos": 0,
            "duration": 90,
            "path": "/tmp/test.mp3",
        }
        relaunched = {**session, "state": "playing", "pid": 5678, "error": ""}

        with patch.object(self.controller, "_process_exists", return_value=True):
            with patch.object(self.controller, "_mpv_command_succeeded", return_value=True):
                with patch.object(self.controller, "_mpv_get_property", side_effect=lambda current, name, default=None: values.get(name, default)):
                    with patch.object(playback_module.time, "time", return_value=106.0):
                        with patch.object(self.controller, "_relaunch_mpv_session", return_value=relaunched) as relaunch:
                            updated = self.controller.sync_session(dict(session))

        relaunch.assert_called_once()
        self.assertEqual(relaunch.call_args.args[1], "mpv Zeitposition steht trotz laufender Wiedergabe.")
        self.assertEqual(updated["pid"], 5678)
        self.assertEqual(updated["state"], "playing")

    def test_play_restarts_paused_mpv_instead_of_reusing_audio_handle(self):
        session = {
            "backend": "mpv",
            "state": "paused",
            "pid": 1234,
            "socket_path": "/tmp/phoniebox-mpv.sock",
            "position_seconds": 23,
            "started_at": None,
        }

        with patch.object(self.controller, "sync_session", return_value=dict(session)):
            with patch.object(self.controller, "_process_exists", return_value=True):
                with patch.object(self.controller, "_mpv_command_succeeded") as mpv_command:
                    with patch.object(self.controller, "_terminate_process_group") as terminate_group:
                        with patch.object(self.controller, "_cleanup_socket") as cleanup_socket:
                            with patch.object(self.controller, "_launch", side_effect=lambda current: {**current, "state": "playing", "pid": 5678}) as launch:
                                updated = self.controller.play(dict(session))

        mpv_command.assert_not_called()
        terminate_group.assert_called_once_with(1234)
        cleanup_socket.assert_called_once_with("/tmp/phoniebox-mpv.sock")
        launch.assert_called_once()
        self.assertEqual(updated["state"], "playing")
        self.assertEqual(updated["pid"], 5678)

    def test_pause_stops_mpv_and_preserves_resume_position(self):
        session = {
            "backend": "mpv",
            "state": "playing",
            "pid": 1234,
            "socket_path": "/tmp/phoniebox-mpv.sock",
            "generated_playlist_source": "/tmp/phoniebox-runtime-test.m3u",
            "position_seconds": 42,
            "started_at": 100.0,
        }

        with patch.object(self.controller, "sync_session", return_value=dict(session)):
            with patch.object(self.controller, "_terminate_process_group") as terminate_group:
                with patch.object(self.controller, "_cleanup_socket") as cleanup_socket:
                    with patch.object(self.controller, "_mpv_command_succeeded") as mpv_command:
                        updated = self.controller.pause(dict(session))

        mpv_command.assert_not_called()
        terminate_group.assert_called_once_with(1234)
        cleanup_socket.assert_called_once_with("/tmp/phoniebox-mpv.sock")
        self.assertEqual(updated["state"], "paused")
        self.assertEqual(updated["position_seconds"], 42)
        self.assertIsNone(updated["pid"])
        self.assertEqual(updated["socket_path"], "")
        self.assertEqual(updated["generated_playlist_source"], "/tmp/phoniebox-runtime-test.m3u")

    def test_sync_session_aligns_mpv_index_to_current_file_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            album_dir = base_dir / "media" / "albums" / "test"
            album_dir.mkdir(parents=True, exist_ok=True)
            playlist = album_dir / "playlist.m3u"
            playlist.write_text("#EXTM3U\nRunnin_Wild.mp3\nMetal_United.mp3\n", encoding="utf-8")
            (album_dir / "Runnin_Wild.mp3").write_bytes(b"")
            metal_united = album_dir / "Metal_United.mp3"
            metal_united.write_bytes(b"")

            session = {
                "backend": "mpv",
                "state": "playing",
                "pid": 1234,
                "socket_path": "/tmp/phoniebox-mpv.sock",
                "playlist": "media/albums/test/playlist.m3u",
                "playlist_entries": ["Runnin_Wild.mp3", "Metal_United.mp3"],
                "position_seconds": 12,
                "duration_seconds": 234,
                "current_index": 0,
                "track_path": str(album_dir / "Runnin_Wild.mp3"),
            }
            values = {
                "time-pos": 13,
                "pause": False,
                "idle-active": False,
                "playlist-pos": 0,
                "duration": 234,
                "path": str(metal_united),
            }

            with patch.object(playback_module, "BASE_DIR", base_dir):
                with patch.object(self.controller, "_process_exists", return_value=True):
                    with patch.object(self.controller, "_mpv_command_succeeded", return_value=True):
                        with patch.object(self.controller, "_mpv_get_property", side_effect=lambda current, name, default=None: values.get(name, default)):
                            updated = self.controller.sync_session(dict(session))

        self.assertEqual(updated["current_index"], 1)
        self.assertEqual(updated["entry"], "Metal_United.mp3")
        self.assertEqual(updated["track_path"], str(metal_united))

    def test_open_track_creates_runtime_playlist_for_shuffled_mpv_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            album_dir = base_dir / "media" / "albums" / "test"
            album_dir.mkdir(parents=True, exist_ok=True)
            playlist = album_dir / "playlist.m3u"
            playlist.write_text("#EXTM3U\n01.mp3\n02.mp3\n", encoding="utf-8")
            (album_dir / "01.mp3").write_bytes(b"")
            (album_dir / "02.mp3").write_bytes(b"")

            with patch.object(playback_module, "BASE_DIR", base_dir), patch.object(
                self.controller, "status", return_value={"active_backend": "mpv"}
            ):
                session = self.controller.open_track(
                    "media/albums/test/playlist.m3u",
                    "02.mp3",
                    current_index=0,
                    entries=["02.mp3", "01.mp3"],
                )

            runtime_playlist = Path(session["generated_playlist_source"])
            self.assertTrue(runtime_playlist.exists())
            self.assertTrue(session["playlist_mode"])
            lines = runtime_playlist.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[1:], [str((album_dir / "02.mp3").resolve()), str((album_dir / "01.mp3").resolve())])
            runtime_playlist.unlink()

    def test_stop_cleans_up_generated_runtime_playlist(self):
        with tempfile.NamedTemporaryFile("w", suffix=".m3u", delete=False) as handle:
            playlist_path = handle.name

        session = {
            "backend": "mpv",
            "state": "paused",
            "pid": None,
            "socket_path": "",
            "generated_playlist_source": playlist_path,
            "position_seconds": 0,
        }

        stopped = self.controller.stop(session)

        self.assertEqual(stopped["state"], "stopped")
        self.assertFalse(Path(playlist_path).exists())


if __name__ == "__main__":
    unittest.main()
