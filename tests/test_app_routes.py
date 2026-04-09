import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import ANY, patch

import app as app_module

from app import (
    app,
    create_app,
    collect_conflicts,
    cross_role_pin_errors,
    default_setup,
    effective_track_entries,
    ensure_data_files,
    normalize_setup_data,
    pin_choices,
    remove_tracks_from_album,
    reader_runtime_cleanup_packages,
    reader_runtime_commands,
)


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

    def test_create_app_sets_secret_key_and_registers_blueprints(self):
        application = create_app()

        self.assertEqual(application.config["SECRET_KEY"], app_module.APP_CONFIG.secret_key)
        self.assertIn("player_routes.player", application.view_functions)
        self.assertIn("library", application.view_functions)
        self.assertNotIn("settings", application.view_functions)
        self.assertIn("settings", app.view_functions)


    def test_album_editor_page_renders(self):
        library_payload = {
            "albums": [
                {
                    "id": "album-1",
                    "name": "Testalbum",
                    "folder": "media/albums/test",
                    "playlist": "media/albums/test/playlist.m3u",
                    "track_count": 2,
                    "rfid_uid": "",
                    "cover_url": "",
                    "track_entries": ["eins.mp3", "zwei.mp3"],
                }
            ]
        }

        with patch("routes.library.load_library", return_value=library_payload), patch("routes.library.refresh_album_metadata") as refresh_album:
            response = self.client.get("/library/album/album-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Albumname", response.get_data(as_text=True))
        self.assertIn("Auswahl löschen", response.get_data(as_text=True))
        self.assertIn("Auswahl 0/2", response.get_data(as_text=True))
        refresh_album.assert_called_once()

    def test_setup_page_hides_reader_details_when_reader_is_ready(self):
        runtime_snapshot = {"runtime": {"hardware": {"profile": {"reader": {"notes": ["Interne Notiz"]}}}}}
        reader_status = {"ready": True, "message": "RC522 bereit.", "details": ["Soll nicht sichtbar sein."]}

        with patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "app.load_reader_status", return_value=reader_status
        ):
            response = self.client.get("/setup")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Reader installiert", body)
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
        self.assertIn("Kein Reader installiert", body)
        self.assertNotIn("RC522 nicht erkannt.", body)
        self.assertNotIn("Der Chip antwortet nicht über SPI.", body)

    def test_api_endpoints_render(self):
        for path in ("/api/runtime", "/api/audio", "/api/hardware"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_player_snapshot_endpoint_renders(self):
        response = self.client.get("/api/player/snapshot")
        self.assertEqual(response.status_code, 200)

    def test_player_post_xhr_returns_json_snapshot(self):
        with patch(
            "routes.player.handle_player_action",
            return_value=({"ok": True, "player_state": {"current_album": "Test"}, "runtime_state": {}, "settings": {}}, 200),
        ) as handle_action:
            response = self.client.post(
                "/player",
                data={"action": "toggle_play"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "Playerstatus aktualisiert.")
        handle_action.assert_called_once()

    def test_settings_post_xhr_returns_json(self):
        with patch("app.load_settings", return_value=app_module.default_settings()), patch("app.save_settings") as save_settings:
            response = self.client.post(
                "/settings",
                data={"volume_step": "7", "max_volume": "85"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "Einstellungen gespeichert.")
        self.assertEqual(payload["settings"]["volume_step"], 7)
        self.assertEqual(payload["settings"]["max_volume"], 85)
        save_settings.assert_called_once()

    def test_api_settings_returns_stable_json_contract(self):
        with patch("app.load_settings", return_value=app_module.default_settings()), patch("app.save_settings") as save_settings:
            response = self.client.post(
                "/api/settings",
                json={"volume_step": 9, "max_volume": 88},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertEqual(set(["ok", "message", "settings"]).difference(payload.keys()), set())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "Einstellungen gespeichert.")
        self.assertEqual(payload["settings"]["volume_step"], 9)
        self.assertEqual(payload["settings"]["max_volume"], 88)
        save_settings.assert_called_once()

    def test_library_save_album_xhr_returns_json_on_conflict(self):
        setup = default_setup()
        runtime_snapshot = {"runtime": {"hardware": {"profile": {}}}}
        library_payload = {
            "albums": [
                {"id": "album-1", "name": "Vorhanden", "folder": "media/albums/alt", "playlist": "", "track_count": 1, "rfid_uid": "", "cover_url": ""}
            ]
        }

        with patch("app.load_setup", return_value=setup), patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "routes.library.load_library", return_value=library_payload
        ):
            response = self.client.post(
                "/library",
                data={"action": "save_album", "album_id": "album-2", "name": "Vorhanden"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["category"], "error")
        self.assertIn("Albumname bereits vorhanden", payload["message"])

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

    def test_default_setup_has_no_reader_installed(self):
        setup = default_setup()

        self.assertEqual(setup["reader"]["type"], "NONE")
        self.assertEqual(setup["reader"]["target_type"], "NONE")
        self.assertEqual(setup["reader"]["install_state"], "not_installed")

    def test_normalize_setup_migrates_existing_reader_type_to_target_type(self):
        setup = normalize_setup_data({"reader": {"type": "RC522"}, "audio": {"output_mode": "usb_dac"}})

        self.assertEqual(setup["reader"]["type"], "RC522")
        self.assertEqual(setup["reader"]["target_type"], "RC522")
        self.assertEqual(setup["reader"]["install_state"], "installed")

    def test_default_setup_has_no_factory_button_or_led_pin_assignments(self):
        setup = default_setup()

        self.assertTrue(all(not button["pin"] for button in setup["buttons"]))
        self.assertTrue(all(not led["pin"] for led in setup["leds"]))
        self.assertFalse(setup["hardware_buttons_enabled"])

    def test_audio_test_endpoint_plays_test_sound(self):
        with patch("services.player_runtime_service.runtime_service.play_system_sound", return_value={"ok": True, "details": ["ok"]}) as play_sound:
            response = self.client.post("/api/runtime/audio-test")
        self.assertEqual(response.status_code, 200)
        play_sound.assert_called_once_with("test")

    def test_led_blink_endpoint_uses_selected_pin(self):
        with patch("app.save_json") as save_json:
            response = self.client.post("/api/setup/led-blink", json={"pin": "GPIO12", "brightness": 55})
        self.assertEqual(response.status_code, 200)
        save_json.assert_called_once_with(
            app_module.LED_PREVIEW_FILE,
            {
                "id": ANY,
                "pin": "GPIO12",
                "brightness": 55,
                "repeats": 3,
                "on_seconds": 0.22,
                "off_seconds": 0.18,
                "status": "pending",
                "requested_at": ANY,
            },
        )

    def test_button_detect_start_uses_available_gpio_baseline(self):
        setup = default_setup()

        with patch("app.load_setup", return_value=setup), patch("app.sample_gpio_levels", return_value={"GPIO17": 1}):
            response = self.client.post("/api/setup/button-detect/start")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "listening")
        self.assertEqual(payload["baseline"], {"GPIO17": 1})

    def test_cross_role_pin_errors_detect_button_led_overlap(self):
        setup = default_setup()
        setup["buttons"][0]["pin"] = "GPIO17"
        setup["leds"][0]["pin"] = "GPIO17"

        errors = cross_role_pin_errors(setup)

        self.assertTrue(errors)

    def test_collect_conflicts_marks_gpio25_as_reserved_for_rc522(self):
        setup = default_setup()
        setup["reader"]["type"] = "RC522"
        setup["buttons"][0]["pin"] = "GPIO25"

        warnings = collect_conflicts(setup)

        self.assertTrue(any("GPIO25" in warning and "für Reader reserviert" in warning for warning in warnings))

    def test_collect_conflicts_warns_about_potential_reader_pins_even_without_active_reader(self):
        setup = default_setup()
        setup["reader"]["type"] = "USB"
        setup["buttons"][0]["pin"] = "GPIO25"

        warnings = collect_conflicts(setup)

        self.assertTrue(any("GPIO25" in warning and "grundsätzlich" in warning for warning in warnings))

    def test_pin_choices_hide_potential_reader_and_audio_pins_by_default(self):
        setup = default_setup()

        button_pins = pin_choices(setup, "button")
        led_pins = pin_choices(setup, "led")

        self.assertNotIn("GPIO25", button_pins)
        self.assertNotIn("GPIO25", led_pins)

    def test_unknown_reader_action_does_not_save_setup(self):
        setup = default_setup()
        runtime_snapshot = {"runtime": {"hardware": {"profile": {}}}}

        with patch("app.load_setup", return_value=setup), patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "app.save_setup"
        ) as save_setup:
            response = self.client.post(
                "/setup",
                data={"section": "reader", "reader_action": "select", "reader_type": "RC522"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        save_setup.assert_not_called()

    def test_reader_install_action_uses_transition_helper(self):
        setup = default_setup()
        runtime_snapshot = {"runtime": {"hardware": {"profile": {}}}}

        with patch("app.load_setup", return_value=setup), patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "app.apply_reader_install_action",
            return_value={"ok": True, "message": "RC522 wurde vorbereitet.", "reboot_scheduled": True},
        ) as apply_action:
            response = self.client.post(
                "/setup",
                data={"section": "reader", "reader_action": "install", "reader_type": "RC522"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        apply_action.assert_called_once()

    def test_reader_runtime_cleanup_packages_keep_only_rc522_set(self):
        cleanup = reader_runtime_cleanup_packages("RC522")

        self.assertNotIn("spidev", cleanup)
        self.assertIn("evdev", cleanup)
        self.assertIn("adafruit-circuitpython-pn532", cleanup)

    def test_reader_runtime_commands_for_rc522_install_only_rc522_stack(self):
        commands = reader_runtime_commands("RC522")
        joined = [" ".join(command) for command in commands]

        self.assertTrue(any("pip uninstall -y" in item and "evdev" in item for item in joined))
        self.assertTrue(any("pip install --upgrade spidev" in item for item in joined))
        self.assertTrue(any("pi-rc522==2.3.0" in item and "--no-deps" in item for item in joined))
        self.assertFalse(any("pip install --upgrade adafruit-circuitpython-pn532" in item for item in joined))

    def test_add_tracks_xhr_returns_json_error_when_no_files_selected(self):
        setup = default_setup()
        runtime_snapshot = {"runtime": {"hardware": {"profile": {}}}}

        with patch("app.load_setup", return_value=setup), patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "routes.library.load_library",
            return_value={"albums": [{"id": "album-1", "name": "Test", "folder": "media/albums/test", "playlist": "", "track_count": 0, "rfid_uid": "", "cover_url": ""}]},
        ):
            response = self.client.post(
                "/library",
                data={"action": "add_tracks", "album_id": "album-1"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        self.assertFalse(response.get_json()["ok"])

    def test_add_tracks_xhr_returns_json_success(self):
        setup = default_setup()
        runtime_snapshot = {"runtime": {"hardware": {"profile": {}}}}
        library_payload = {"albums": [{"id": "album-1", "name": "Test", "folder": "media/albums/test", "playlist": "", "track_count": 0, "rfid_uid": "", "cover_url": ""}]}

        with patch("app.load_setup", return_value=setup), patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "routes.library.load_library", return_value=library_payload
        ), patch("routes.library.add_tracks_to_album") as add_tracks, patch("routes.library.save_library") as save_library:
            response = self.client.post(
                "/library",
                data={"action": "add_tracks", "album_id": "album-1", "track_files": (BytesIO(b"fake"), "song.mp3")},
                content_type="multipart/form-data",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        self.assertTrue(response.get_json()["ok"])
        add_tracks.assert_called_once()
        save_library.assert_called_once_with(library_payload)

    def test_remove_tracks_from_album_requires_selection(self):
        with self.assertRaises(ValueError):
            remove_tracks_from_album({"folder": "media/albums/test"}, [])

    def test_remove_tracks_xhr_returns_json_success(self):
        setup = default_setup()
        runtime_snapshot = {"runtime": {"hardware": {"profile": {}}}}
        album = {"id": "album-1", "name": "Test", "folder": "media/albums/test", "playlist": "", "track_count": 2, "rfid_uid": "", "cover_url": ""}
        library_payload = {"albums": [album]}

        with patch("app.load_setup", return_value=setup), patch("app.runtime_service.status", return_value=runtime_snapshot), patch(
            "routes.library.load_library", return_value=library_payload
        ), patch("routes.library.remove_tracks_from_album", return_value=2) as remove_tracks, patch("routes.library.save_library") as save_library:
            response = self.client.post(
                "/library",
                data={"action": "remove_tracks", "album_id": "album-1", "track_path": ["eins.mp3", "zwei.mp3"]},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        self.assertTrue(response.get_json()["ok"])
        remove_tracks.assert_called_once()
        save_library.assert_called_once_with(library_payload)

    def test_album_editor_reorder_tracks_redirects_back_to_editor(self):
        album = {"id": "album-1", "name": "Test", "folder": "media/albums/test", "playlist": "", "track_count": 2, "rfid_uid": "", "cover_url": ""}
        library_payload = {"albums": [album]}

        with patch("routes.library.load_library", return_value=library_payload), patch("routes.library.reorder_album_tracks") as reorder_tracks, patch(
            "routes.library.save_library"
        ) as save_library:
            response = self.client.post(
                "/library/album/album-1",
                data={"action": "reorder_tracks", "track_order": ["zwei.mp3", "eins.mp3"]},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/library/album/album-1", response.headers["Location"])
        reorder_tracks.assert_called_once()
        save_library.assert_called_once_with(library_payload)

    def test_album_editor_rename_track_uses_helper(self):
        album = {"id": "album-1", "name": "Test", "folder": "media/albums/test", "playlist": "", "track_count": 2, "rfid_uid": "", "cover_url": ""}
        library_payload = {"albums": [album]}

        with patch("routes.library.load_library", return_value=library_payload), patch("routes.library.rename_track_in_album") as rename_track, patch(
            "routes.library.save_library"
        ) as save_library:
            response = self.client.post(
                "/library/album/album-1",
                data={"action": "rename_track", "track_path": "eins.mp3", "new_name": "Erstes Lied"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/library/album/album-1", response.headers["Location"])
        rename_track.assert_called_once_with(album, "eins.mp3", "Erstes Lied")
        save_library.assert_called_once_with(library_payload)

    def test_effective_track_entries_preserves_playlist_order_and_appends_new_files(self):
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            album_dir = base_dir / "media" / "albums" / "test"
            album_dir.mkdir(parents=True)
            (album_dir / "b_track.mp3").write_bytes(b"b")
            (album_dir / "a_track.mp3").write_bytes(b"a")
            (album_dir / "c_track.mp3").write_bytes(b"c")
            (album_dir / "playlist.m3u").write_text("#EXTM3U\nb_track.mp3\na_track.mp3\n", encoding="utf-8")
            album = {"folder": "media/albums/test", "playlist": "media/albums/test/playlist.m3u"}

            with patch("app.BASE_DIR", base_dir):
                entries = effective_track_entries(album)

        self.assertEqual(entries, ["b_track.mp3", "a_track.mp3", "c_track.mp3"])
