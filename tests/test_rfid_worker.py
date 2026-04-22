import unittest
from unittest.mock import patch
from subprocess import CompletedProcess
from urllib.error import HTTPError

from scripts import rfid_worker


class FakeBackend:
    def __init__(self, version):
        self._version = version
        self.cleaned = False

    def version(self):
        return self._version

    def cleanup(self):
        self.cleaned = True


class FakeReader:
    presence_reader = False

    def __init__(self, responses):
        self.responses = iter(responses)
        self.ready = True
        self.status_message = "bereit"
        self.status_details = []
        self.cleaned = False

    def poll(self):
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response

    def cleanup(self):
        self.cleaned = True


class ProbeRC522BackendTest(unittest.TestCase):
    def test_ensure_spi_pinmux_only_inspects_current_state(self):
        completed = CompletedProcess(
            args=["pinctrl", "get", "7-11"],
            returncode=0,
            stdout="7: a0\n8: a0\n",
            stderr="",
        )

        with patch.object(rfid_worker.subprocess, "run", return_value=completed) as run_mock:
            result = rfid_worker.ensure_spi_pinmux()

        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "SPI-Pinmux geprüft.")
        self.assertEqual(result["details"], ["7: a0", "8: a0"])
        run_mock.assert_called_once_with(
            ["pinctrl", "get", "7-11"],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_probe_returns_detected_config(self):
        backend = FakeBackend(0x92)

        with patch.object(rfid_worker, "LowLevelRC522Backend", return_value=backend):
            result = rfid_worker.probe_rc522_backend()

        self.assertTrue(result["ok"])
        self.assertEqual(result["config"]["spi_device"], 0)
        self.assertEqual(result["config"]["rst_pin"], 25)
        self.assertIsNone(result["config"]["irq_pin"])
        self.assertTrue(backend.cleaned)

    def test_probe_cleans_failed_backend(self):
        backend = FakeBackend(0x00)

        with patch.object(rfid_worker, "LowLevelRC522Backend", return_value=backend):
            result = rfid_worker.probe_rc522_backend()

        self.assertFalse(result["ok"])
        self.assertTrue(backend.cleaned)
        self.assertIn("Der Chip antwortet nicht über SPI.", result["details"])

    def test_probe_only_requires_spidev(self):
        backend = FakeBackend(0x92)

        with patch.dict("sys.modules", {"spidev": object()}), patch.object(rfid_worker, "LowLevelRC522Backend", return_value=backend):
            result = rfid_worker.probe_rc522_backend()

        self.assertTrue(result["ok"])

    def test_worker_posts_uid_immediately_without_boot_grace_period(self):
        reader = FakeReader(["ABC123", KeyboardInterrupt()])

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid") as post_uid, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 1.0, 1.1, 1.2]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertGreaterEqual(post_uid.call_count, 1)
        post_uid.assert_any_call("ABC123")
        self.assertTrue(reader.cleaned)

    def test_worker_posts_usb_uid_once_when_same_uid_repeats(self):
        reader = FakeReader(["ABC123", "ABC123", KeyboardInterrupt()])

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "USB"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.6, 6.8, 7.0]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertGreaterEqual(post_uid.call_count, 1)
        post_uid.assert_any_call("ABC123")
        self.assertTrue(reader.cleaned)

    def test_presence_reader_posts_uid_after_boot_grace_when_tag_stays_present(self):
        reader = FakeReader(["ABC123", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.6, 6.9, 7.2]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertGreaterEqual(post_uid.call_count, 1)
        post_uid.assert_any_call("ABC123")
        self.assertTrue(reader.cleaned)

    def test_presence_reader_posts_uid_after_configured_confirm_reads(self):
        reader = FakeReader(["ABC123", "", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.0, 6.1, 6.2, 6.3, 6.4, 6.5]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        post_uid.assert_called_once_with("ABC123")
        self.assertTrue(reader.cleaned)

    def test_presence_reader_refreshes_present_uid_to_enforce_tag_on_play(self):
        reader = FakeReader(["ABC123", "ABC123", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(
            rfid_worker, "post_uid", return_value=200
        ) as post_uid, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.0, 6.1, 8.3, 8.4]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertEqual([call.args[0] for call in post_uid.call_args_list], ["ABC123", "ABC123"])
        self.assertTrue(reader.cleaned)

    def test_presence_reader_does_not_post_unconfirmed_new_uid(self):
        reader = FakeReader(["ABC123", "", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.0, 6.1, 6.2, 6.3]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        post_uid.assert_not_called()
        self.assertTrue(reader.cleaned)

    def test_presence_reader_ignores_different_uid_until_current_tag_removed(self):
        reader = FakeReader(["ABC123", "ABC123", "XYZ999", "XYZ999", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(
            rfid_worker, "post_uid", return_value=200
        ) as post_uid, patch.object(
            rfid_worker, "post_remove", return_value=200
        ) as post_remove, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.0, 6.1, 6.2, 6.3, 6.4, 6.5]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        post_uid.assert_any_call("ABC123")
        post_remove.assert_not_called()
        self.assertTrue(reader.cleaned)

    def test_presence_reader_accepts_different_uid_after_current_tag_removed(self):
        reader = FakeReader(["ABC123", "ABC123", "", "", "XYZ999", "XYZ999", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(
            rfid_worker, "post_uid", return_value=200
        ) as post_uid, patch.object(
            rfid_worker, "post_remove", return_value=200
        ) as post_remove, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.0, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertEqual([call.args[0] for call in post_uid.call_args_list], ["ABC123", "XYZ999"])
        post_remove.assert_called_once_with("ABC123")
        self.assertTrue(reader.cleaned)

    def test_presence_reader_does_not_post_remove_before_configured_miss_count(self):
        reader = FakeReader(["ABC123", "ABC123", "", "", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(
            rfid_worker,
            "load_setup",
            return_value={"reader": {"type": "RC522", "tag_confirm_count": 1, "presence_miss_count": 3, "presence_interval_seconds": 0.55}},
        ), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(
            rfid_worker, "post_uid", return_value=200
        ) as post_uid, patch.object(
            rfid_worker, "post_remove", return_value=200
        ) as post_remove, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.6, 7.4, 8.0, 8.3]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        post_uid.assert_any_call("ABC123")
        post_remove.assert_not_called()
        self.assertTrue(reader.cleaned)

    def test_presence_reader_posts_remove_after_stable_absence(self):
        reader = FakeReader(["ABC123", "ABC123", "", "", "", "", "", "", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(
            rfid_worker, "post_uid", return_value=200
        ) as post_uid, patch.object(
            rfid_worker, "post_remove", return_value=200
        ) as post_remove, patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.6, 6.75, 6.9, 7.05, 7.2, 7.35, 7.5, 7.65]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        post_uid.assert_called_once_with("ABC123")
        post_remove.assert_called_once_with("ABC123")
        self.assertTrue(reader.cleaned)

    def test_post_json_treats_http_404_as_handled(self):
        error = HTTPError("http://127.0.0.1/api/runtime/rfid", 404, "Not Found", hdrs=None, fp=None)

        with patch.object(rfid_worker.urllib.request, "urlopen", side_effect=error):
            status_code = rfid_worker.post_json("http://127.0.0.1/api/runtime/rfid", {"uid": "ABC123"})

        self.assertEqual(status_code, 404)

    def test_presence_reader_uses_fast_idle_sleep_before_tag_is_active(self):
        reader = FakeReader([])
        reader.presence_reader = True

        with patch.object(rfid_worker.time, "sleep") as sleep:
            rfid_worker.loop_sleep(reader, idle_interval=0.08, presence_interval=0.75, active=False)

        sleep.assert_called_once_with(0.08)

    def test_presence_reader_uses_configured_interval_after_tag_is_active(self):
        reader = FakeReader([])
        reader.presence_reader = True

        with patch.object(rfid_worker.time, "sleep") as sleep:
            rfid_worker.loop_sleep(reader, idle_interval=0.08, presence_interval=0.75, active=True)

        sleep.assert_called_once_with(0.75)

    def test_reader_presence_config_clamps_idle_interval(self):
        idle_interval, presence_interval, confirm_count, miss_count = rfid_worker.reader_presence_config(
            {
                "reader": {
                    "idle_scan_interval_seconds": "0.001",
                    "tag_confirm_count": "99",
                    "presence_interval_seconds": "9",
                    "presence_miss_count": "99",
                }
            }
        )

        self.assertEqual(idle_interval, 0.02)
        self.assertEqual(presence_interval, 5.0)
        self.assertEqual(confirm_count, 10)
        self.assertEqual(miss_count, 20)

    def test_presence_reader_reposts_same_uid_when_link_session_becomes_active(self):
        reader = FakeReader(["ABC123", "ABC123", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker, "load_link_session_state", side_effect=[
                {"active": False, "status": "idle", "started_at": 0.0, "last_uid": ""},
                {"active": False, "status": "idle", "started_at": 0.0, "last_uid": ""},
                {"active": True, "status": "waiting_for_uid", "started_at": 1.0, "album_id": "a", "last_uid": ""},
                {"active": True, "status": "waiting_for_uid", "started_at": 1.0, "album_id": "a", "last_uid": ""},
                {"active": True, "status": "waiting_for_uid", "started_at": 1.0, "album_id": "a", "last_uid": ""},
            ]
        ), patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.6, 7.0, 7.4, 7.8]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertGreaterEqual(post_uid.call_count, 2)
        post_uid.assert_called_with("ABC123")

    def test_presence_reader_reposts_when_new_link_session_restarts_while_already_active(self):
        reader = FakeReader(["ABC123", "ABC123", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker, "load_link_session_state", side_effect=[
                {"active": True, "status": "uid_detected", "started_at": 1.0, "album_id": "a", "last_uid": "ABC123"},
                {"active": True, "status": "uid_detected", "started_at": 1.0, "album_id": "a", "last_uid": "ABC123"},
                {"active": True, "status": "waiting_for_uid", "started_at": 2.0, "album_id": "a", "last_uid": ""},
                {"active": True, "status": "waiting_for_uid", "started_at": 2.0, "album_id": "a", "last_uid": ""},
                {"active": True, "status": "waiting_for_uid", "started_at": 2.0, "album_id": "a", "last_uid": ""},
            ]
        ), patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.6, 7.0, 7.4, 7.8]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertGreaterEqual(post_uid.call_count, 1)

    def test_link_session_waiting_posts_uid_without_presence_suppression(self):
        reader = FakeReader(["ABC123", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker, "load_link_session_state", return_value={"active": True, "status": "waiting_for_uid", "started_at": 2.0, "album_id": "a", "last_uid": ""}
        ), patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.4, 6.7, 7.0]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        post_uid.assert_called_once_with("ABC123")

    def test_link_session_waiting_throttles_duplicate_uid_posts(self):
        reader = FakeReader(["ABC123", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker, "load_link_session_state", return_value={"active": True, "status": "waiting_for_uid", "started_at": 2.0, "album_id": "a", "last_uid": ""}
        ), patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.5, 6.8, 7.0]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        post_uid.assert_called_once_with("ABC123")

    def test_presence_reader_reposts_same_uid_after_link_session_ends(self):
        reader = FakeReader(["ABC123", "ABC123", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(rfid_worker, "post_uid", return_value=True) as post_uid, patch.object(
            rfid_worker, "load_link_session_state", side_effect=[
                {"active": True, "status": "waiting_for_uid", "started_at": 2.0, "album_id": "a", "last_uid": ""},
                {"active": True, "status": "uid_detected", "started_at": 2.0, "album_id": "a", "last_uid": "ABC123"},
                {"active": False, "status": "linked", "started_at": 2.0, "album_id": "a", "last_uid": "ABC123"},
                {"active": False, "status": "linked", "started_at": 2.0, "album_id": "a", "last_uid": "ABC123"},
                {"active": False, "status": "linked", "started_at": 2.0, "album_id": "a", "last_uid": "ABC123"},
                {"active": False, "status": "linked", "started_at": 2.0, "album_id": "a", "last_uid": "ABC123"},
            ]
        ), patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.6, 7.0, 7.4, 7.8]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertGreaterEqual(post_uid.call_count, 2)
        post_uid.assert_called_with("ABC123")

    def test_presence_reader_posts_playback_uid_immediately_when_link_session_finishes_with_present_tag(self):
        reader = FakeReader(["ABC123", "ABC123", "ABC123", KeyboardInterrupt()])
        reader.presence_reader = True

        with patch.object(rfid_worker, "load_setup", return_value={"reader": {"type": "RC522"}}), patch.object(
            rfid_worker, "build_reader", return_value=reader
        ), patch.object(rfid_worker, "save_reader_status"), patch.object(
            rfid_worker, "post_uid", return_value=200
        ) as post_uid, patch.object(
            rfid_worker, "load_link_session_state", side_effect=[
                {"active": True, "status": "waiting_for_uid", "started_at": 2.0, "album_id": "a", "last_uid": ""},
                {"active": True, "status": "uid_detected", "started_at": 2.0, "album_id": "a", "last_uid": "ABC123"},
                {"active": False, "status": "linked", "started_at": 2.0, "album_id": "a", "last_uid": "ABC123"},
                {"active": False, "status": "linked", "started_at": 2.0, "album_id": "a", "last_uid": "ABC123"},
            ]
        ), patch.object(
            rfid_worker.time, "monotonic", side_effect=[0.0, 0.1, 6.2, 6.6, 7.0, 7.4]
        ):
            with self.assertRaises(KeyboardInterrupt):
                rfid_worker.main()

        self.assertEqual([call.args[0] for call in post_uid.call_args_list], ["ABC123", "ABC123"])


if __name__ == "__main__":
    unittest.main()
