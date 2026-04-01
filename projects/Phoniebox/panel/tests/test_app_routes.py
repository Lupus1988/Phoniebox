import unittest

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
