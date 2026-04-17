import subprocess
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

    def test_fallback_hotspot_cycle_does_not_touch_inactive_hotspot_when_client_is_up(self):
        config = {"mode": "client_with_fallback_hotspot", "fallback_hotspot": True}
        calls = []

        def fake_run(command):
            calls.append(command)
            return {"ok": True, "output": ""}

        with patch.object(networking, "command_exists", return_value=True), patch.object(
            networking, "active_wifi_connected", return_value=True
        ), patch.object(
            networking, "connection_active", return_value=False
        ), patch.object(
            networking, "run_command", side_effect=fake_run
        ):
            result = networking.fallback_hotspot_cycle(config)

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], "Client-WLAN aktiv, Hotspot bleibt aus.")
        self.assertEqual(calls, [])

    def test_recreate_wifi_client_skips_profile_without_password(self):
        with patch.object(networking, "run_command") as run_command:
            result = networking.recreate_wifi_client("Hausnetz", "", 100)

        self.assertTrue(result["ok"])
        self.assertIn("uebersprungen", result["details"][0])
        run_command.assert_not_called()

    def test_run_wifi_state_command_uses_script_output(self):
        fake = '{"ok": true, "details": ["WLAN aktiviert."]}'
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=fake, stderr="")
        with patch.object(networking.subprocess, "run", return_value=completed):
            result = networking.run_wifi_state_command(True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["details"], ["WLAN aktiviert."])

    def test_run_wifi_state_command_falls_back_to_set_wifi_radio_without_script(self):
        with patch.object(networking, "wifi_state_command_path", return_value=networking.BASE_DIR / "scripts" / "missing.py"), patch.object(
            networking, "set_wifi_radio", return_value={"ok": True, "details": ["fallback"]}
        ) as set_wifi_radio:
            result = networking.run_wifi_state_command(False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["details"], ["fallback"])
        set_wifi_radio.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
