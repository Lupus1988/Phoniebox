import unittest
from unittest.mock import patch

from app import app, collect_conflicts, default_setup, ensure_data_files


class AppRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_data_files()

    def setUp(self):
        self.client = app.test_client()

    def test_pages_render(self):
        for path in ("/player", "/library", "/settings", "/setup"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_api_endpoints_render(self):
        for path in ("/api/runtime", "/api/audio", "/api/hardware"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_hotspot_password_warning_uses_current_security_value(self):
        setup = default_setup()
        setup["wifi"]["hotspot_security"] = "wpa-psk"
        setup["wifi"]["hotspot_password"] = "1234"

        warnings = collect_conflicts(setup)

        self.assertTrue(any("mindestens 8 Zeichen" in warning for warning in warnings))

    def test_default_setup_has_no_placeholder_wifi_networks(self):
        setup = default_setup()

        self.assertEqual(setup["wifi"]["mode"], "hotspot_only")
        self.assertEqual(setup["wifi"]["saved_networks"], [])

    def test_default_setup_has_no_factory_button_or_led_pin_assignments(self):
        setup = default_setup()

        self.assertTrue(all(not button["pin"] for button in setup["buttons"]))
        self.assertTrue(all(not led["pin"] for led in setup["leds"]))

    def test_audio_test_endpoint_plays_test_sound(self):
        with patch("app.runtime_service.play_system_sound", return_value={"ok": True, "details": ["ok"]}) as play_sound:
            response = self.client.post("/api/runtime/audio-test")
        self.assertEqual(response.status_code, 200)
        play_sound.assert_called_once_with("test")
