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

    def test_no_active_wifi_keeps_empty_setup_on_hotspot_only(self):
        config = {"wifi": {"mode": "hotspot_only", "fallback_hotspot": True, "saved_networks": []}}
        with patch.object(bootstrap_network, "detect_active_ssid", return_value=""):
            changed, message = bootstrap_network.ensure_current_network_saved(config)
        self.assertFalse(changed)
        self.assertIn("Kein aktives WLAN", message)
        self.assertEqual(config["wifi"]["mode"], "hotspot_only")
        self.assertEqual(config["wifi"]["saved_networks"], [])

    def test_prepare_network_profiles_creates_client_and_hotspot_profiles(self):
        config = {
            "wifi": {
                "saved_networks": [{"ssid": "Hausnetz", "password": "geheim123", "priority": 100}],
                "hotspot_ssid": "Phonie-hotspot",
            }
        }
        with patch.object(bootstrap_network, "run_command", return_value=(True, "")), patch.object(
            bootstrap_network, "detect_active_ssid", return_value=""
        ), patch.object(
            bootstrap_network, "detect_active_connection_name", return_value=""
        ), patch.object(
            bootstrap_network, "recreate_wifi_client", return_value={"ok": True, "details": ["Client-WLAN gespeichert: Hausnetz"]}
        ) as recreate_client, patch.object(
            bootstrap_network, "ensure_hotspot_profile", return_value={"ok": True, "details": ["Hotspot-Profil vorbereitet: Phonie-hotspot"]}
        ) as ensure_hotspot:
            result = bootstrap_network.prepare_network_profiles(config)
        self.assertTrue(result["ok"])
        recreate_client.assert_called_once()
        ensure_hotspot.assert_called_once()

    def test_prepare_network_profiles_keeps_active_system_profile(self):
        config = {
            "wifi": {
                "saved_networks": [{"ssid": "Hausnetz", "password": "", "priority": 100}],
                "hotspot_ssid": "Phonie-hotspot",
            }
        }
        with patch.object(bootstrap_network, "run_command", return_value=(True, "")), patch.object(
            bootstrap_network, "detect_active_ssid", return_value="Hausnetz"
        ), patch.object(
            bootstrap_network, "detect_active_connection_name", return_value="netplan-wlan0-Hausnetz"
        ), patch.object(
            bootstrap_network, "recreate_wifi_client"
        ) as recreate_client, patch.object(
            bootstrap_network, "ensure_hotspot_profile", return_value={"ok": True, "details": ["Hotspot-Profil bereits vorhanden: Phonie-hotspot"]}
        ):
            result = bootstrap_network.prepare_network_profiles(config)
        self.assertTrue(result["ok"])
        recreate_client.assert_not_called()
        self.assertTrue(any("Vorhandenes Systemprofil bleibt aktiv" in detail for detail in result["details"]))

    def test_prepare_network_profiles_removes_stale_open_phonie_profile(self):
        with patch.object(bootstrap_network, "delete_connection_if_exists", return_value={"ok": True, "details": ["Vorhandenes Profil entfernt: phonie-client-Hausnetz"]}):
            result = bootstrap_network.cleanup_stale_client_profile("Hausnetz", "netplan-wlan0-Hausnetz", "")
        self.assertTrue(result["ok"])
        self.assertIn("Vorhandenes Profil entfernt", result["details"][0])


if __name__ == "__main__":
    unittest.main()
