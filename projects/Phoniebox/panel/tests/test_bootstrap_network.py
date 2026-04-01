import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import bootstrap_network


class BootstrapNetworkTests(unittest.TestCase):
    def test_find_password_in_wpa_supplicant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "wpa_supplicant.conf"
            path.write_text(
                """
network={
    ssid="Hausnetz"
    psk="geheim123"
}
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with patch.object(bootstrap_network, "WPA_SUPPLICANT_FILE", path):
                self.assertEqual(bootstrap_network.find_password_in_wpa_supplicant("Hausnetz"), "geheim123")

    def test_imports_active_network_and_switches_mode(self):
        config = {"wifi": {"mode": "hotspot_only", "fallback_hotspot": True, "saved_networks": []}}
        with patch.object(bootstrap_network, "detect_active_ssid", return_value="Hausnetz"), patch.object(
            bootstrap_network, "find_current_wifi_password", return_value="geheim123"
        ):
            changed, message = bootstrap_network.ensure_current_network_saved(config)
        self.assertTrue(changed)
        self.assertIn("Hausnetz", message)
        self.assertEqual(config["wifi"]["mode"], "client_with_fallback_hotspot")
        self.assertEqual(config["wifi"]["saved_networks"][0]["ssid"], "Hausnetz")
        self.assertEqual(config["wifi"]["saved_networks"][0]["password"], "geheim123")


if __name__ == "__main__":
    unittest.main()
