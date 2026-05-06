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

    def test_fallback_hotspot_cycle_keeps_running_hotspot_up(self):
        config = {"mode": "client_with_fallback_hotspot", "fallback_hotspot": True}

        with patch.object(networking, "command_exists", return_value=True), patch.object(
            networking, "connection_active", side_effect=lambda name: name == "phoniebox-hotspot"
        ), patch.object(
            networking, "active_wifi_connected", return_value=True
        ), patch.object(
            networking, "run_command"
        ) as run_command:
            result = networking.fallback_hotspot_cycle(config)

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], "Fallback-Hotspot läuft bereits.")
        run_command.assert_not_called()

    def test_fallback_hotspot_cycle_respects_runtime_wifi_disabled_without_touching_inactive_hotspot(self):
        config = {"mode": "client_with_fallback_hotspot", "fallback_hotspot": True}
        runtime_state = {"powered_on": True, "wifi_enabled": False}
        calls = []

        def fake_run(command):
            calls.append(command)
            return {"ok": True, "output": ""}

        with patch.object(networking, "command_exists", return_value=True), patch.object(
            networking, "connection_active", return_value=False
        ), patch.object(
            networking, "run_command", side_effect=fake_run
        ):
            result = networking.fallback_hotspot_cycle(config, runtime_state=runtime_state)

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], "Hotspot bleibt aus.")
        self.assertEqual(calls, [])

    def test_fallback_hotspot_cycle_turns_active_hotspot_off_when_runtime_disables_wifi(self):
        config = {"mode": "client_with_fallback_hotspot", "fallback_hotspot": True}
        runtime_state = {"powered_on": False, "wifi_enabled": True}
        calls = []

        def fake_run(command):
            calls.append(command)
            return {"ok": True, "output": ""}

        with patch.object(networking, "command_exists", return_value=True), patch.object(
            networking, "connection_active", return_value=True
        ), patch.object(
            networking, "run_command", side_effect=fake_run
        ):
            result = networking.fallback_hotspot_cycle(config, runtime_state=runtime_state)

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], "Hotspot deaktiviert.")
        self.assertEqual(calls, [["sudo", "nmcli", "connection", "down", "phoniebox-hotspot"]])

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

    def test_recreate_hotspot_profile_open_does_not_set_wep_key_mgmt(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            if command[:5] == ["nmcli", "-t", "-f", "NAME", "connection"]:
                return {"ok": True, "output": ""}
            return {"ok": True, "output": ""}

        with patch.object(networking, "run_command", side_effect=fake_run):
            result = networking.recreate_hotspot_profile({"hotspot_ssid": "Phonie-hotspot", "hotspot_security": "open"})

        self.assertTrue(result["ok"])
        self.assertFalse(any("wifi-sec.key-mgmt" in cmd for cmd in calls))

    def test_recreate_hotspot_profile_sets_configured_host_address(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            if command[:5] == ["nmcli", "-t", "-f", "NAME", "connection"]:
                return {"ok": True, "output": ""}
            return {"ok": True, "output": ""}

        with patch.object(networking, "run_command", side_effect=fake_run):
            result = networking.recreate_hotspot_profile(
                {"hotspot_ssid": "Phonie-hotspot", "hotspot_security": "open", "hotspot_address": "192.168.77.1"}
            )

        self.assertTrue(result["ok"])
        self.assertTrue(any("ipv4.addresses" in cmd and "192.168.77.1/24" in cmd for cmd in calls))

    def test_ensure_hotspot_dns_alias_writes_browser_name_and_hostname(self):
        calls = []
        captured = {}

        def fake_run(command):
            calls.append(command)
            if command[:4] == ["sudo", "install", "-m", "644"]:
                with open(command[4], encoding="utf-8") as handle:
                    captured["content"] = handle.read()
            return {"ok": True, "output": ""}

        with patch.object(networking, "run_command", side_effect=fake_run):
            result = networking.ensure_hotspot_dns_alias(
                {
                    "browser_name": "phoniebox.local",
                    "hostname": "phoniebox",
                    "hotspot_address": "10.42.0.1",
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0], ["sudo", "mkdir", "-p", str(networking.DNSMASQ_SHARED_DIR)])
        self.assertEqual(calls[1][:4], ["sudo", "install", "-m", "644"])
        self.assertIn("address=/phoniebox.local/10.42.0.1", captured["content"])
        self.assertIn("address=/phoniebox/10.42.0.1", captured["content"])

    def test_apply_wifi_profile_includes_hotspot_dns_alias(self):
        config = {"saved_networks": []}
        call_order = []

        def mark(name, payload):
            call_order.append(name)
            return payload

        with patch.object(networking, "command_exists", return_value=True), patch.object(
            networking, "run_command", return_value={"ok": True, "output": ""}
        ), patch.object(
            networking, "recreate_hotspot_profile", side_effect=lambda cfg: mark("hotspot", {"ok": True, "details": ["hotspot"]})
        ), patch.object(
            networking, "ensure_hotspot_dns_alias", side_effect=lambda cfg: mark("dns", {"ok": True, "details": ["dns"]})
        ), patch.object(
            networking, "apply_mode", side_effect=lambda cfg: mark("mode", {"ok": True, "details": ["mode"]})
        ):
            result = networking.apply_wifi_profile(config)

        self.assertTrue(result["ok"])
        self.assertEqual(call_order, ["hotspot", "dns", "mode"])


if __name__ == "__main__":
    unittest.main()
