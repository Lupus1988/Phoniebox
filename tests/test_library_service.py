import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

from services import library_service


class LibraryServiceAudioProcessingTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.audio_path = Path(self.temp_dir.name) / "song.mp3"
        self.audio_path.write_bytes(b"fake-audio")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_describe_audio_processing_reports_missing_tools(self):
        message = library_service.describe_audio_processing(
            {"tool_available": False, "checked": 0, "normalized": 0, "unchanged": 0, "failed": 0, "skipped": 1}
        )

        self.assertIn("ffmpeg/ffprobe fehlen", message)

    def test_describe_audio_processing_reports_background_schedule(self):
        message = library_service.describe_audio_processing(
            {"tool_available": True, "scheduled": 3, "checked": 0, "normalized": 0, "unchanged": 0, "failed": 0, "skipped": 0, "issue": ""}
        )

        self.assertIn("läuft im Hintergrund", message)

    def test_describe_audio_processing_reports_background_start_failure(self):
        message = library_service.describe_audio_processing(
            {"tool_available": True, "scheduled": 0, "checked": 0, "normalized": 0, "unchanged": 0, "failed": 1, "skipped": 0, "issue": "Audio-Normalisierung konnte nicht im Hintergrund gestartet werden."}
        )

        self.assertIn("konnte nicht im Hintergrund gestartet werden", message)

    def test_process_uploaded_audio_files_skips_when_tools_are_missing(self):
        with patch.object(library_service, "audio_processing_tools_available", return_value=False):
            report = library_service.process_uploaded_audio_files([self.audio_path])

        self.assertFalse(report["tool_available"])
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(report["checked"], 0)

    def test_process_uploaded_audio_files_normalizes_when_needed(self):
        with patch.object(library_service, "audio_processing_tools_available", return_value=True), patch.object(
            library_service, "_probe_audio_file", return_value={"streams": [{"codec_type": "audio"}]}
        ), patch.object(library_service, "_analyze_audio_loudness", return_value={"input_i": "-24.0", "input_tp": "-0.2"}), patch.object(
            library_service, "_normalize_audio_file", return_value=True
        ) as normalize_audio:
            report = library_service.process_uploaded_audio_files([self.audio_path])

        self.assertTrue(report["tool_available"])
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["normalized"], 1)
        normalize_audio.assert_called_once()

    def test_process_uploaded_audio_files_keeps_already_balanced_file(self):
        with patch.object(library_service, "audio_processing_tools_available", return_value=True), patch.object(
            library_service, "_probe_audio_file", return_value={"streams": [{"codec_type": "audio"}]}
        ), patch.object(library_service, "_analyze_audio_loudness", return_value={"input_i": "-16.2", "input_tp": "-2.1"}), patch.object(
            library_service, "_normalize_audio_file"
        ) as normalize_audio:
            report = library_service.process_uploaded_audio_files([self.audio_path])

        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["unchanged"], 1)
        normalize_audio.assert_not_called()

    def test_schedule_uploaded_audio_processing_starts_background_job(self):
        manifest_files = []

        def fake_save_json(path, data):
            manifest_files.append(Path(path))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("{}", encoding="utf-8")

        with patch.object(library_service, "audio_processing_tools_available", return_value=True), patch.object(
            library_service, "AUDIO_PROCESSING_QUEUE_DIR", Path(self.temp_dir.name) / "queue"
        ), patch.object(library_service, "save_json", side_effect=fake_save_json), patch.object(
            library_service, "audio_processing_worker_running", return_value=False
        ), patch.object(
            library_service, "_spawn_audio_processing_worker"
        ) as spawn_worker:
            report = library_service.schedule_uploaded_audio_processing([self.audio_path])

        self.assertTrue(report["tool_available"])
        self.assertEqual(report["scheduled"], 1)
        self.assertGreaterEqual(len(manifest_files), 2)
        self.assertTrue(any(path.name.endswith(".json") and "job-" in path.name for path in manifest_files))
        spawn_worker.assert_called_once()

    def test_schedule_uploaded_audio_processing_reuses_running_worker(self):
        queue_dir = Path(self.temp_dir.name) / "queue"

        with patch.object(library_service, "audio_processing_tools_available", return_value=True), patch.object(
            library_service, "AUDIO_PROCESSING_QUEUE_DIR", queue_dir
        ), patch.object(
            library_service, "audio_processing_worker_running", return_value=True
        ), patch.object(
            library_service, "_spawn_audio_processing_worker"
        ) as spawn_worker:
            report = library_service.schedule_uploaded_audio_processing([self.audio_path])

        self.assertTrue(report["tool_available"])
        self.assertEqual(report["scheduled"], 1)
        self.assertTrue(any(queue_dir.glob("job-*.json")))
        spawn_worker.assert_not_called()

    def test_schedule_uploaded_audio_processing_includes_job_metadata(self):
        queue_dir = Path(self.temp_dir.name) / "queue"
        status_dir = Path(self.temp_dir.name) / "status"

        with patch.object(library_service, "audio_processing_tools_available", return_value=True), patch.object(
            library_service, "AUDIO_PROCESSING_QUEUE_DIR", queue_dir
        ), patch.object(
            library_service, "AUDIO_PROCESSING_STATUS_DIR", status_dir
        ), patch.object(
            library_service, "audio_processing_worker_running", return_value=True
        ):
            report = library_service.schedule_uploaded_audio_processing([self.audio_path])

        self.assertEqual(len(report["jobs"]), 1)
        self.assertTrue(report["jobs"][0]["job"].startswith("job-"))

    def test_schedule_uploaded_audio_processing_reports_failed_background_start(self):
        with patch.object(library_service, "audio_processing_tools_available", return_value=True), patch.object(
            library_service, "AUDIO_PROCESSING_QUEUE_DIR", Path(self.temp_dir.name) / "queue"
        ), patch.object(
            library_service, "audio_processing_worker_running", return_value=False
        ), patch.object(
            library_service, "_spawn_audio_processing_worker", side_effect=OSError("spawn failed")
        ):
            report = library_service.schedule_uploaded_audio_processing([self.audio_path])

        self.assertTrue(report["tool_available"])
        self.assertEqual(report["failed"], 1)
        self.assertIn("konnte nicht im Hintergrund gestartet werden", report["issue"])

    def test_audio_processing_status_summary_reads_status_and_result(self):
        status_dir = Path(self.temp_dir.name) / "status"
        results_dir = Path(self.temp_dir.name) / "results"
        status_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        library_service.save_json(
            status_dir / "job-a.status.json",
            {
                "job": "job-a.json",
                "state": "running",
                "total_files": 2,
                "completed_files": 1,
                "progress_ratio": 0.5,
                "files": [
                    {"name": "one.mp3", "state": "normalized", "progress_ratio": 1.0, "detail": "Normalisiert"},
                    {"name": "two.mp3", "state": "normalizing", "progress_ratio": 0.75, "detail": "Wird normalisiert"},
                ],
            },
        )
        library_service.save_json(
            results_dir / "job-b.result.json",
            {
                "job": "job-b.json",
                "created_at": 1,
                "finished_at": 2,
                "paths": [str(self.audio_path)],
                "report": {"normalized": 0, "unchanged": 1, "failed": 0},
            },
        )

        with patch.object(library_service, "AUDIO_PROCESSING_STATUS_DIR", status_dir), patch.object(
            library_service, "AUDIO_PROCESSING_RESULTS_DIR", results_dir
        ):
            summary = library_service.audio_processing_status_summary(["job-a.json", "job-b.json"])

        self.assertEqual(summary["job_count"], 2)
        self.assertEqual(summary["total_files"], 3)
        self.assertEqual(summary["completed_files"], 2)
        self.assertTrue(summary["active"])

    def test_process_volume_adjustment_applies_gain(self):
        with patch.object(library_service, "audio_processing_tools_available", return_value=True), patch.object(
            library_service, "_apply_gain_to_audio_file", return_value=True
        ) as apply_gain:
            report = library_service.process_volume_adjustment([self.audio_path], 1.5)

        self.assertTrue(report["tool_available"])
        self.assertEqual(report["normalized"], 1)
        apply_gain.assert_called_once()

    def test_schedule_volume_adjustment_includes_job_metadata(self):
        queue_dir = Path(self.temp_dir.name) / "queue"
        status_dir = Path(self.temp_dir.name) / "status"
        with patch.object(library_service, "audio_processing_tools_available", return_value=True), patch.object(
            library_service, "AUDIO_PROCESSING_QUEUE_DIR", queue_dir
        ), patch.object(
            library_service, "AUDIO_PROCESSING_STATUS_DIR", status_dir
        ), patch.object(
            library_service, "audio_processing_worker_running", return_value=True
        ):
            report = library_service.schedule_volume_adjustment(self.audio_path, 1.5)

        self.assertEqual(report["scheduled"], 1)
        self.assertEqual(len(report["jobs"]), 1)


class LibraryServiceMetadataTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.media_dir = self.base_dir / "media" / "albums" / "test"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        (self.media_dir / "01-track.mp3").write_bytes(b"a")
        (self.media_dir / "02-next.mp3").write_bytes(b"bb")
        self.patchers = [
            patch.object(library_service, "BASE_DIR", self.base_dir),
            patch.object(library_service, "MEDIA_DIR", self.base_dir / "media"),
            patch.object(library_service, "ALBUMS_DIR", self.base_dir / "media" / "albums"),
            patch.object(library_service, "LIBRARY_FILE", self.base_dir / "data" / "library.json"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_refresh_album_metadata_persists_track_metadata(self):
        album = {
            "id": "album-1",
            "name": "Test",
            "folder": "media/albums/test",
            "playlist": "",
            "track_count": 0,
            "rfid_uid": "",
            "cover_url": "",
            "tracks": [],
        }

        with patch.object(library_service, "track_duration_seconds", side_effect=[123, 234]):
            updated = library_service.refresh_album_metadata(album)

        self.assertEqual(updated["track_entries"], ["01-track.mp3", "02-next.mp3"])
        self.assertEqual(updated["tracks"][0]["path"], "01-track.mp3")
        self.assertEqual(updated["tracks"][0]["title"], "01 track")
        self.assertEqual(updated["tracks"][0]["duration_seconds"], 123)
        self.assertEqual(updated["tracks"][0]["size_bytes"], 1)
        self.assertEqual(updated["tracks"][1]["path"], "02-next.mp3")
        self.assertEqual(updated["tracks"][1]["duration_seconds"], 234)
        self.assertEqual(updated["tracks"][1]["size_bytes"], 2)

    def test_refresh_album_metadata_reuses_cached_track_duration_when_file_is_unchanged(self):
        track_path = self.media_dir / "01-track.mp3"
        (self.media_dir / "02-next.mp3").unlink()
        stat = track_path.stat()
        album = {
            "id": "album-1",
            "name": "Test",
            "folder": "media/albums/test",
            "playlist": "",
            "track_count": 1,
            "rfid_uid": "",
            "cover_url": "",
            "tracks": [
                {
                    "path": "01-track.mp3",
                    "title": "Mein Titel",
                    "duration_seconds": 456,
                    "modified_ns": int(stat.st_mtime_ns),
                    "size_bytes": int(stat.st_size),
                }
            ],
        }

        with patch.object(library_service, "track_duration_seconds", side_effect=AssertionError("duration should be reused")):
            updated = library_service.refresh_album_metadata(album)

        self.assertEqual(updated["tracks"][0]["duration_seconds"], 456)
        self.assertEqual(updated["tracks"][0]["title"], "Mein Titel")

    def test_is_audio_file_accepts_only_mp3(self):
        self.assertTrue(library_service.is_audio_file(Path("track.mp3")))
        self.assertFalse(library_service.is_audio_file(Path("track.wav")))
        self.assertFalse(library_service.is_audio_file(Path("track.flac")))
        self.assertFalse(library_service.is_audio_file(Path("track.m4a")))


class _FakeStorage:
    def __init__(self, filename, content=b"fake-audio"):
        self.filename = filename
        self._content = content

    def save(self, target):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(self._content)


class LibraryServiceMpdRefreshTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        (self.base_dir / "data").mkdir(parents=True, exist_ok=True)
        self.patchers = [
            patch.object(library_service, "BASE_DIR", self.base_dir),
            patch.object(library_service, "MEDIA_DIR", self.base_dir / "media"),
            patch.object(library_service, "ALBUMS_DIR", self.base_dir / "media" / "albums"),
            patch.object(library_service, "LIBRARY_FILE", self.base_dir / "data" / "library.json"),
        ]
        for patcher in self.patchers:
            patcher.start()
        library_service.save_json(
            self.base_dir / "data" / "setup.json",
            {"audio": {"playback_backend": "mpd"}},
        )

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_refresh_mpd_library_if_needed_uses_wait_and_falls_back_without_raising(self):
        commands = []

        def fake_run(cmd, check, capture_output, text):
            commands.append(cmd)
            if cmd[-2:] == ["update", "--wait"]:
                return subprocess.CompletedProcess(cmd, 1, "", "mpc: unrecognized option '--wait'")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch.object(library_service.shutil, "which", return_value="/usr/bin/mpc"), patch.object(
            library_service.subprocess, "run", side_effect=fake_run
        ):
            refreshed = library_service.refresh_mpd_library_if_needed()

        self.assertTrue(refreshed)
        self.assertEqual(commands[0], ["/usr/bin/mpc", "--port", "6600", "update", "--wait"])
        self.assertEqual(commands[1], ["/usr/bin/mpc", "--port", "6600", "update"])

    def test_import_album_folder_refreshes_mpd_library(self):
        files = [_FakeStorage("Bauernhof/01-track.mp3", b"one"), _FakeStorage("Bauernhof/cover.jpg", b"jpg")]

        with patch.object(library_service, "refresh_mpd_library_if_needed", return_value=True) as refresh_mpd:
            album, _report = library_service.import_album_folder(files, "Bauernhof")

        self.assertEqual(album["track_count"], 1)
        refresh_mpd.assert_called_once()

    def test_add_tracks_to_album_refreshes_mpd_library_after_saving_audio(self):
        album_dir = self.base_dir / "media" / "albums" / "test"
        album_dir.mkdir(parents=True, exist_ok=True)
        album = {
            "id": "album-1",
            "name": "Test",
            "folder": "media/albums/test",
            "playlist": "",
            "track_count": 0,
            "rfid_uid": "",
            "cover_url": "",
            "tracks": [],
        }

        with patch.object(library_service, "refresh_mpd_library_if_needed", return_value=True) as refresh_mpd:
            updated, _report = library_service.add_tracks_to_album(album, [_FakeStorage("01-track.mp3", b"one")])

        self.assertEqual(updated["track_count"], 1)
        refresh_mpd.assert_called_once()
