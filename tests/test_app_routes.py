import unittest
from unittest.mock import patch

from app import app, collect_conflicts, cross_role_pin_errors, default_setup, ensure_data_files, pin_choices


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

    def test_setup_page_hides_reader_details_when_reader_is_ready(self):
        runtime_snapshot = {"runtime": {"hardware": {"profile": {"reader": {"notes": ["Interne Notiz"]}}}}}
        reader_status = {"ready": True, "message": "RC522 bereit.", "details": ["Soll nicht sichtbar sein."]}

        with patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "app.load_reader_status", return_value=reader_status
        ):
            response = self.client.get("/setup")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("RC522 bereit.", body)
        self.assertNotIn("Soll nicht sichtbar sein.", body)
        self.assertNotIn("Interne Notiz", body)

    def test_setup_page_shows_reader_details_when_reader_is_not_ready(self):
        runtime_snapshot = {"runtime": {"hardware": {"profile": {"reader": {"notes": ["Interne Notiz"]}}}}}
        reader_status = {"ready": False, "message": "RC522 nicht erkannt.", "details": ["Der Chip antwortet nicht über SPI."]}

        with patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "app.load_reader_status", return_value=reader_status
        ):
            response = self.client.get("/setup")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("RC522 nicht erkannt.", body)
        self.assertIn("Der Chip antwortet nicht über SPI.", body)

    def test_api_endpoints_render(self):
        for path in ("/api/runtime", "/api/audio", "/api/hardware"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_player_snapshot_endpoint_renders(self):
        response = self.client.get("/api/player/snapshot")
        self.assertEqual(response.status_code, 200)

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
        self.assertFalse(setup["hardware_buttons_enabled"])

    def test_audio_test_endpoint_plays_test_sound(self):
        with patch("app.runtime_service.play_system_sound", return_value={"ok": True, "details": ["ok"]}) as play_sound:
            response = self.client.post("/api/runtime/audio-test")
        self.assertEqual(response.status_code, 200)
        play_sound.assert_called_once_with("test")

    def test_led_blink_endpoint_uses_selected_pin(self):
        with patch("app.LEDController") as led_controller:
            led_controller.return_value.blink_led.return_value = True
            response = self.client.post("/api/setup/led-blink", json={"pin": "GPIO12", "brightness": 55})
        self.assertEqual(response.status_code, 200)
        led_controller.return_value.blink_led.assert_called_once_with(
            "GPIO12",
            brightness=55,
            repeats=3,
            on_seconds=0.22,
            off_seconds=0.18,
        )

    def test_cross_role_pin_errors_detect_button_led_overlap(self):
        setup = default_setup()
        setup["buttons"][0]["pin"] = "GPIO17"
        setup["leds"][0]["pin"] = "GPIO17"

        errors = cross_role_pin_errors(setup)

        self.assertTrue(errors)

    def test_collect_conflicts_marks_gpio22_as_reserved_for_rc522(self):
        setup = default_setup()
        setup["reader"]["type"] = "RC522"
        setup["buttons"][0]["pin"] = "GPIO22"

        warnings = collect_conflicts(setup)

        self.assertTrue(any("GPIO22" in warning and "Reader oder Soundkarte" in warning for warning in warnings))

    def test_collect_conflicts_warns_about_potential_reader_pins_even_without_active_reader(self):
        setup = default_setup()
        setup["reader"]["type"] = "USB"
        setup["buttons"][0]["pin"] = "GPIO22"

        warnings = collect_conflicts(setup)

        self.assertTrue(any("GPIO22" in warning and "grundsätzlich" in warning for warning in warnings))

    def test_pin_choices_hide_potential_reader_and_audio_pins_by_default(self):
        setup = default_setup()

        button_pins = pin_choices(setup, "button")
        led_pins = pin_choices(setup, "led")

        self.assertNotIn("GPIO22", button_pins)
        self.assertNotIn("GPIO25", button_pins)
        self.assertNotIn("GPIO20", button_pins)
        self.assertNotIn("GPIO22", led_pins)
