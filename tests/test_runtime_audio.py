import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import audio as audio_module


class RuntimeAudioTest(unittest.TestCase):
    def test_pick_track_duration_reads_length_from_mutagen_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            album_dir = base_dir / "media" / "albums" / "test"
            album_dir.mkdir(parents=True, exist_ok=True)
            (album_dir / "playlist.m3u").write_text("01-track.mp3\n", encoding="utf-8")
            track_path = album_dir / "01-track.mp3"
            track_path.write_bytes(b"fake")

            fake_info = type("FakeInfo", (), {"length": 123.4})()
            fake_file = type("FakeFile", (), {"info": fake_info})()

            with patch.object(audio_module, "BASE_DIR", base_dir):
                with patch.object(audio_module, "MutagenFile", return_value=fake_file):
                    duration = audio_module.pick_track_duration("media/albums/test/playlist.m3u", "01-track.mp3")

        self.assertEqual(duration, 123)


if __name__ == "__main__":
    unittest.main()
