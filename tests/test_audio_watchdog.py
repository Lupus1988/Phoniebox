import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import audio_watchdog


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class AudioWatchdogTest(unittest.TestCase):
    def test_disable_usb_audio_autosuspend_sets_power_control_on(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sysfs = Path(temp_dir)
            device = sysfs / "1-1"
            interface = sysfs / "1-1:1.0"
            (device / "power").mkdir(parents=True)
            interface.mkdir(parents=True)
            (device / "idVendor").write_text("8087", encoding="utf-8")
            (device / "idProduct").write_text("1024", encoding="utf-8")
            (device / "product").write_text("USB2.0 Device", encoding="utf-8")
            (device / "power" / "control").write_text("auto", encoding="utf-8")
            (device / "power" / "autosuspend_delay_ms").write_text("2000", encoding="utf-8")
            (interface / "bInterfaceClass").write_text("01", encoding="utf-8")
            usbcore_autosuspend = sysfs / "usbcore_autosuspend"
            usbcore_autosuspend.write_text("2", encoding="utf-8")

            with patch.object(audio_watchdog, "USB_SYSFS", sysfs), patch.object(audio_watchdog, "USBCORE_AUTOSUSPEND", usbcore_autosuspend):
                touched = audio_watchdog.disable_usb_audio_autosuspend()

            self.assertEqual(len(touched), 2)
            self.assertEqual(usbcore_autosuspend.read_text(encoding="utf-8"), "-1")
            self.assertEqual((device / "power" / "control").read_text(encoding="utf-8"), "on")
            self.assertEqual((device / "power" / "autosuspend_delay_ms").read_text(encoding="utf-8"), "-1")

    def test_watchdog_pauses_playback_when_audio_disappears(self):
        service = Mock()
        runtime_state = {
            "playback_state": "playing",
            "playback_session": {
                "backend": "mpv",
                "state": "playing",
                "pid": 1234,
                "position_seconds": 42,
            },
            "audio_watchdog": {"ready": True},
            "event_log": [],
        }
        player = {"is_playing": True, "position_seconds": 41}
        paused_session = {
            **runtime_state["playback_session"],
            "state": "paused",
            "pid": None,
            "position_seconds": 42,
        }
        original_session = dict(runtime_state["playback_session"])
        service.state_transaction.return_value = nullcontext()
        service.ensure_runtime.return_value = runtime_state
        service.load_player.return_value = player
        service.playback.pause.return_value = paused_session
        service.add_event.side_effect = lambda state, message, level="info", mark_activity=True: {**state, "last_event": message}

        updated = audio_watchdog._mark_audio_state(service, False, "USB-Soundkarte nicht erkannt.")

        service.playback.pause.assert_called_once_with(original_session)
        self.assertEqual(updated["playback_state"], "paused")
        self.assertFalse(player["is_playing"])
        self.assertEqual(updated["playback_session"]["state"], "error")
        self.assertEqual(updated["playback_session"]["error"], "USB-Soundkarte nicht erkannt.")
        self.assertEqual(updated["audio_watchdog"]["ready"], False)
        self.assertTrue(updated["audio_watchdog"]["resume_on_recovery"])
        self.assertEqual(updated["last_event"], "Audioausgabe verloren: USB-Soundkarte nicht erkannt.")
        service.save_runtime.assert_called_once()
        service.save_player.assert_called_once()

    def test_watchdog_resumes_playback_when_audio_returns(self):
        service = Mock()
        runtime_state = {
            "playback_state": "paused",
            "playback_session": {
                "backend": "mpv",
                "state": "error",
                "pid": None,
                "position_seconds": 42,
                "error": "USB-Soundkarte nicht erkannt.",
            },
            "audio_watchdog": {
                "ready": False,
                "resume_on_recovery": True,
            },
            "event_log": [],
        }
        player = {"is_playing": False, "position_seconds": 42}
        resumed_session = {
            **runtime_state["playback_session"],
            "state": "playing",
            "pid": 4321,
            "error": "",
        }
        paused_session = dict(runtime_state["playback_session"])
        service.state_transaction.return_value = nullcontext()
        service.ensure_runtime.return_value = runtime_state
        service.load_player.return_value = player
        service.playback.play.return_value = resumed_session
        service.add_event.side_effect = lambda state, message, level="info", mark_activity=True: {**state, "last_event": message}

        updated = audio_watchdog._mark_audio_state(service, True, "")

        service.playback.play.assert_called_once_with(paused_session)
        self.assertEqual(updated["playback_state"], "playing")
        self.assertEqual(updated["playback_session"]["pid"], 4321)
        self.assertTrue(player["is_playing"])
        self.assertEqual(player["position_seconds"], 42)
        self.assertEqual(updated["audio_watchdog"]["ready"], True)
        self.assertFalse(updated["audio_watchdog"]["resume_on_recovery"])
        self.assertEqual(updated["last_event"], "Audioausgabe wieder verfügbar: Wiedergabe fortgesetzt")
        service.save_runtime.assert_called_once()
        service.save_player.assert_called_once()


if __name__ == "__main__":
    unittest.main()
