import unittest
from unittest.mock import patch

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
    def test_probe_returns_detected_config(self):
        backend = FakeBackend(0x92)

        with patch.object(rfid_worker, "LowLevelRC522Backend", return_value=backend):
            result = rfid_worker.probe_rc522_backend()

        self.assertTrue(result["ok"])
        self.assertEqual(result["config"]["spi_device"], 0)
        self.assertEqual(result["config"]["rst_pin"], 22)
        self.assertEqual(result["config"]["irq_pin"], 18)
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
