import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from system import audio as audio_module


class AudioSystemTest(unittest.TestCase):
    def test_parse_proc_asound_pcm_finds_playback_devices(self):
        payload = "\n".join(
            [
                "00-00: USB Audio : USB Audio : playback 1 : capture 1",
                "01-00: MAI PCM i2s-hifi-0 : MAI PCM i2s-hifi-0 : playback 1",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            pcm_path = Path(temp_dir) / "pcm"
            pcm_path.write_text(payload, encoding="utf-8")

            devices = audio_module.parse_proc_asound_pcm(pcm_path)

        self.assertEqual(
            devices[0],
            {
                "card_index": "00",
                "device_index": "00",
                "name": "USB Audio",
                "device_name": "USB Audio",
                "alsa_hw": "hw:00,00",
            },
        )

    @patch.object(audio_module, "parse_proc_asound_pcm")
    @patch.object(audio_module, "run_command")
    @patch.object(audio_module, "command_exists")
    def test_list_playback_devices_falls_back_to_proc_pcm_when_aplay_fails(
        self,
        mock_command_exists,
        mock_run,
        mock_proc_pcm,
    ):
        mock_command_exists.return_value = True
        mock_run.return_value = {"ok": False, "output": "aplay: device_list:279: no soundcards found..."}
        mock_proc_pcm.return_value = [{"card_index": "0", "device_index": "0", "alsa_hw": "hw:0,0"}]

        devices = audio_module.list_playback_devices()

        self.assertEqual(devices, [{"card_index": "0", "device_index": "0", "alsa_hw": "hw:0,0"}])

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
    def test_detect_audio_environment_marks_usb_from_card_description(
        self,
        mock_model,
        mock_cards,
        mock_devices,
    ):
        mock_model.return_value = "Raspberry Pi Zero 2 W Rev 1.0"
        mock_cards.return_value = [
            {
                "card_index": "0",
                "card_id": "Device",
                "name": ": USB-Audio - USB2.0 Device",
                "description": "Generic USB2.0 Device at usb-3f980000.usb-1, full speed",
            }
        ]
        mock_devices.return_value = [{"card_index": "0", "device_index": "0", "alsa_hw": "hw:0,0"}]

        snapshot = audio_module.detect_audio_environment()

        self.assertTrue(snapshot["has_usb_audio"])
        self.assertFalse(snapshot["recommended_external_card"])
        self.assertIn("USB-Audio erkannt.", snapshot["notes"])

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
                    "playback_backend": "mpv",
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

    @patch.object(audio_module, "command_exists")
    @patch.object(audio_module, "detect_audio_environment")
    def test_apply_audio_profile_usb_dac_boot_config_no_longer_depends_on_i2s_profiles(self, mock_environment, mock_command_exists):
        mock_environment.return_value = {
            "device_model": "Raspberry Pi Zero 2 W Rev 1.0",
            "cards": [{"card_index": "1", "card_id": "Device", "name": "USB DAC", "description": "USB Audio"}],
            "playback_devices": [{"alsa_hw": "hw:1,0", "name": "USB DAC", "device_name": "USB Audio"}],
            "notes": ["USB-Audio erkannt."],
            "recommended_external_card": False,
        }
        mock_command_exists.return_value = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = audio_module.apply_audio_profile(
                {
                    "output_mode": "usb_dac",
                    "use_startup_volume": False,
                    "apply_boot_config": False,
                },
                Path(temp_dir),
            )

            self.assertTrue(result["ok"])
            boot_config = (Path(temp_dir) / "boot-config.txt").read_text(encoding="utf-8")
            self.assertIn("Kein spezielles Boot-Overlay nötig.", boot_config)


if __name__ == "__main__":
    unittest.main()
