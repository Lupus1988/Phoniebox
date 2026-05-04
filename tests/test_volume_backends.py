import unittest
from unittest.mock import patch

from services.volume_backends import create_volume_backend
from services.volume_backends.amixer_backend import AmixerVolumeBackend
from services.volume_backends.mpd_backend import MpdVolumeBackend


class VolumeBackendsTest(unittest.TestCase):
    def test_create_volume_backend_uses_amixer_alias(self):
        backend = create_volume_backend(
            "amixer",
            config={"alsa_volume_card": "Device", "alsa_mixer_control": "PCM"},
        )

        self.assertIsInstance(backend, AmixerVolumeBackend)

    @patch("services.volume_backends.amixer_backend.shutil.which", return_value="/usr/bin/amixer")
    @patch("services.volume_backends.amixer_backend.subprocess.run")
    def test_amixer_backend_parses_pcm_volume(self, mock_run, _mock_which):
        mock_run.return_value.stdout = (
            "Simple mixer control 'PCM',0\n"
            "  Capabilities: pvolume pvolume-joined pswitch pswitch-joined\n"
            "  Playback channels: Mono\n"
            "  Limits: Playback 0 - 255\n"
            "  Mono: Playback 135 [53%] [on]\n"
        )
        mock_run.return_value.returncode = 0

        backend = AmixerVolumeBackend({"alsa_volume_card": "Device", "alsa_mixer_control": "PCM"})
        status = backend.status()

        self.assertTrue(status["available"])
        self.assertEqual(status["volume"], 75)
        self.assertFalse(status["muted"])

    @patch("services.volume_backends.amixer_backend.shutil.which", return_value="/usr/bin/amixer")
    @patch("services.volume_backends.amixer_backend.subprocess.run")
    def test_amixer_backend_sets_raw_value_with_gamma_curve(self, mock_run, _mock_which):
        mock_run.return_value.stdout = (
            "Simple mixer control 'PCM',0\n"
            "  Capabilities: pvolume pvolume-joined pswitch pswitch-joined\n"
            "  Playback channels: Mono\n"
            "  Limits: Playback 0 - 255\n"
            "  Mono: Playback 135 [53%] [on]\n"
        )
        mock_run.return_value.returncode = 0

        backend = AmixerVolumeBackend({"alsa_volume_card": "Device", "alsa_mixer_control": "PCM"})
        status = backend.set_volume(75)

        self.assertEqual(status["volume"], 75)
        self.assertEqual(status["raw_target"], 135)

    @patch("services.volume_backends.mpd_backend.shutil.which", return_value="/usr/bin/mpc")
    @patch("services.volume_backends.mpd_backend.subprocess.run")
    def test_mpd_volume_backend_parses_status_volume(self, mock_run, _mock_which):
        mock_run.return_value.stdout = "volume: 42%   repeat: off   random: off   single: off   consume: off\n"
        mock_run.return_value.returncode = 0

        backend = MpdVolumeBackend({})
        status = backend.status()

        self.assertTrue(status["available"])
        self.assertEqual(status["volume"], 42)


if __name__ == "__main__":
    unittest.main()
