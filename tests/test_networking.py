import unittest
from unittest.mock import patch

from system import networking


class NetworkingTest(unittest.TestCase):
    def test_activate_hotspot_succeeds_directly(self):
        with patch.object(networking, "run_command", return_value={"ok": True, "output": "ok"}):
            result = networking.activate_hotspot_with_recovery("phoniebox-hotspot")

        self.assertTrue(result["ok"])
        self.assertIn("ok", " ".join(result["details"]))

    def test_activate_hotspot_recovers_from_unavailable_device(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            if command[:5] == ["sudo", "nmcli", "connection", "up", "phoniebox-hotspot"] and len(command) == 5:
                return {"ok": False, "output": "No suitable device found for this connection (device wlan0 not available because device is not available)"}
            if command == ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"]:
                return {"ok": True, "output": "wlp1s0:wifi:disconnected\neth0:ethernet:connected"}
            if command[:5] == ["sudo", "nmcli", "connection", "up", "phoniebox-hotspot"] and "ifname" in command:
                return {"ok": True, "output": "ok"}
            return {"ok": True, "output": ""}

        with patch.object(networking, "run_command", side_effect=fake_run):
            result = networking.activate_hotspot_with_recovery("phoniebox-hotspot")

        self.assertTrue(result["ok"])
        self.assertTrue(any(cmd[:6] == ["sudo", "nmcli", "connection", "modify", "phoniebox-hotspot", "connection.interface-name"] for cmd in calls))
        self.assertTrue(any("wlp1s0" in " ".join(cmd) for cmd in calls))

    def test_activate_hotspot_recovery_runs_even_without_known_error_text(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            if command[:5] == ["sudo", "nmcli", "connection", "up", "phoniebox-hotspot"] and len(command) == 5:
                return {"ok": False, "output": "Activation failed with no extra context"}
            if command == ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"]:
                return {"ok": True, "output": "wlan1:wifi:disconnected"}
            if command[:5] == ["sudo", "nmcli", "connection", "up", "phoniebox-hotspot"] and "ifname" in command:
                return {"ok": True, "output": "ok"}
            return {"ok": True, "output": ""}

        with patch.object(networking, "run_command", side_effect=fake_run):
            result = networking.activate_hotspot_with_recovery("phoniebox-hotspot")

        self.assertTrue(result["ok"])
        self.assertTrue(any(cmd == ["sudo", "nmcli", "radio", "wifi", "on"] for cmd in calls))
        self.assertTrue(any(cmd[:6] == ["sudo", "nmcli", "connection", "modify", "phoniebox-hotspot", "connection.interface-name"] for cmd in calls))

    def test_fallback_hotspot_cycle_uses_recovery_activation(self):
        config = {"mode": "client_with_fallback_hotspot", "fallback_hotspot": True}
        with patch.object(networking, "command_exists", return_value=True), patch.object(
            networking, "active_wifi_connected", return_value=False
        ), patch.object(networking, "activate_hotspot_with_recovery", return_value={"ok": True, "details": ["Hotspot auf wlp1s0 aktiviert."]}):
            result = networking.fallback_hotspot_cycle(config)

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], "Fallback-Hotspot aktiviert.")


if __name__ == "__main__":
    unittest.main()
