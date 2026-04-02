import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from system import audio as audio_module


class AudioSystemTest(unittest.TestCase):
    @patch.object(audio_module, "list_playback_devices")
    @patch.object(audio_module, "parse_asound_cards")
    @patch.object(audio_module, "detect_device_model")
    def test_detect_audio_environment_marks_headphones_as_internal_soundcard(
        self,
        mock_model,
        mock_cards,
        mock_devices,
    ):
        mock_model.return_value = "Raspberry Pi 4 Model B Rev 1.1"
        mock_cards.return_value = [
            {
                "card_index": "0",
                "card_id": "Headphones",
                "name": "bcm2835 Headphones",
                "description": "bcm2835 Headphones",
            }
        ]
        mock_devices.return_value = []

        snapshot = audio_module.detect_audio_environment()

        self.assertTrue(snapshot["has_analog_audio"])
        self.assertIn("Onboard-Analog-Audio erkannt.", snapshot["notes"])

    @patch.object(audio_module, "list_playback_devices")
    @patch.object(audio_module, "parse_asound_cards")
    @patch.object(audio_module, "detect_device_model")
    def test_detect_audio_environment_marks_pi_zero_external_card_need(
        self,
        mock_model,
        mock_cards,
        mock_devices,
    ):
        mock_model.return_value = "Raspberry Pi Zero 2 W Rev 1.0"
        mock_cards.return_value = []
        mock_devices.return_value = []

        snapshot = audio_module.detect_audio_environment()

        self.assertTrue(snapshot["is_pi_zero_2w"])
        self.assertTrue(snapshot["recommended_external_card"])
        self.assertIn("Pi Zero 2 W erkannt", " ".join(snapshot["notes"]))

    @patch.object(audio_module, "command_exists")
    @patch.object(audio_module, "detect_audio_environment")
    def test_apply_audio_profile_reports_partial_without_cards(self, mock_environment, mock_command_exists):
        mock_environment.return_value = {
            "device_model": "Raspberry Pi Zero 2 W Rev 1.0",
            "cards": [],
            "playback_devices": [],
            "notes": ["Keine ALSA-Soundkarten erkannt."],
            "recommended_external_card": True,
        }
        mock_command_exists.return_value = False

        result = audio_module.apply_audio_profile(
            {
                "output_mode": "usb_dac",
                "use_startup_volume": False,
            }
        )

        self.assertFalse(result["ok"])
        self.assertIn("Noch keine Soundkarte erkannt", " ".join(result["details"]))

    @patch.object(audio_module, "command_exists")
    @patch.object(audio_module, "detect_audio_environment")
    def test_apply_audio_profile_generates_artifacts(self, mock_environment, mock_command_exists):
        mock_environment.return_value = {
            "device_model": "Raspberry Pi 4 Model B Rev 1.5",
            "cards": [{"card_index": "1", "card_id": "Device", "name": "USB DAC", "description": "USB Audio"}],
            "playback_devices": [{"alsa_hw": "hw:1,0", "name": "USB DAC", "device_name": "USB Audio"}],
            "notes": ["USB-Audio erkannt."],
            "recommended_external_card": False,
        }
        mock_command_exists.return_value = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = audio_module.apply_audio_profile(
                {
                    "output_mode": "usb_dac",
                    "use_startup_volume": True,
                    "startup_volume": 55,
                    "playback_backend": "mpg123",
                    "i2s_profile": "auto",
                },
                Path(temp_dir),
            )

            self.assertTrue(result["ok"])
            self.assertTrue((Path(temp_dir) / "asound.conf").exists())
            self.assertTrue((Path(temp_dir) / "boot-config.txt").exists())
            self.assertTrue((Path(temp_dir) / "set-startup-volume.sh").exists())
            self.assertTrue((Path(temp_dir) / "README.txt").exists())

    def test_deploy_audio_profile_installs_generated_files(self):
        with tempfile.TemporaryDirectory() as generated_dir, tempfile.TemporaryDirectory() as target_root:
            generated_path = Path(generated_dir)
            (generated_path / "asound.conf").write_text("pcm.!default {}", encoding="utf-8")
            (generated_path / "boot-config.txt").write_text("dtparam=audio=off\n", encoding="utf-8")
            startup_script = generated_path / "set-startup-volume.sh"
            startup_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            startup_script.chmod(0o755)

            result = audio_module.deploy_audio_profile(
                {
                    "apply_boot_config": True,
                    "enable_audio_service": False,
                },
                generated_path,
                target_root=target_root,
            )

            self.assertTrue(result["ok"])
            self.assertTrue((Path(target_root) / "etc" / "asound.conf").exists())
            self.assertTrue((Path(target_root) / "usr" / "local" / "bin" / "phoniebox-set-startup-volume.sh").exists())
            self.assertTrue((Path(target_root) / "etc" / "systemd" / "system" / "phoniebox-audio-init.service").exists())
            self.assertTrue((Path(target_root) / "boot" / "firmware" / "usercfg.txt").exists())


if __name__ == "__main__":
    unittest.main()
