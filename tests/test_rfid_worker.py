import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

from scripts import rfid_worker


class FakeBackend:
    def __init__(self, version):
        self._version = version
        self.cleaned = False

    def version(self):
        return self._version

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


if __name__ == "__main__":
    unittest.main()
