import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hardware import leds as leds_module
from hardware import manager as manager_module
from hardware import rfid as rfid_module
from services import library_service


class FakePWM:
    def __init__(self, pin, freq):
        self.pin = pin
        self.freq = freq
        self.started = None
        self.duty = None
        self.value = 0

    def start(self, duty):
        self.started = duty

    def ChangeDutyCycle(self, duty):
        self.duty = duty

    def stop(self):
        pass

    def off(self):
        self.value = 0

    def close(self):
        return None


class FakeLEDDevice:
    def __init__(self, pin, pin_factory=None, initial_value=False, frequency=None):
        self.pin = pin
        self.pin_factory = pin_factory
        self.is_lit = bool(initial_value)

    def on(self):
        self.is_lit = True

    def off(self):
        self.is_lit = False

    def close(self):
        return None


class FakePWMLEDDevice(FakeLEDDevice):
    def __init__(self, pin, pin_factory=None, initial_value=0, frequency=None):
        super().__init__(pin, pin_factory=pin_factory, initial_value=bool(initial_value), frequency=frequency)
        self.value = initial_value
        self.frequency = frequency


class FakeFactory:
    pass


class FakeGPIO:
    BCM = "BCM"
    OUT = "OUT"
    LOW = 0
    HIGH = 1

    def __init__(self):
        self.outputs = {}
        self.setups = []

    def setwarnings(self, flag):
        return None

    def setmode(self, mode):
        self.mode = mode

    def setup(self, pin, mode, initial=None):
        self.setups.append((pin, mode, initial))

    def output(self, pin, value):
        self.outputs[pin] = value

    def cleanup(self, pin=None):
        return None

    def PWM(self, pin, freq):
        return FakePWM(pin, freq)


class HardwareHelpersTest(unittest.TestCase):
    def test_decode_keycode_to_char_maps_hex_digits(self):
        self.assertEqual(rfid_module.decode_keycode_to_char("KEY_7"), "7")
        self.assertEqual(rfid_module.decode_keycode_to_char("KEY_A"), "A")
        self.assertEqual(rfid_module.decode_keycode_to_char("KEY_Z"), "")

    def test_led_controller_handles_digital_and_pwm_outputs(self):
        with (
            patch.object(leds_module, "GPIO", None),
            patch.object(leds_module, "GpioZeroLED", FakeLEDDevice),
            patch.object(leds_module, "GpioZeroPWMLED", FakePWMLEDDevice),
            patch.object(leds_module, "LGPIOFactory", FakeFactory),
        ):
            controller = leds_module.LEDController()
            ok = controller.apply_leds(
                [
                    {"pin": "GPIO23", "brightness": 100, "is_on": True},
                    {"pin": "GPIO18", "brightness": 40, "is_on": True},
                ]
            )

            self.assertTrue(ok)
            self.assertTrue(controller._digital[23].is_lit)
            self.assertIn(18, controller._pwm)
            self.assertEqual(controller._pwm[18].value, 0.4)

    def test_led_controller_drives_inactive_pwm_pin_low_without_pwm(self):
        with (
            patch.object(leds_module, "GPIO", None),
            patch.object(leds_module, "GpioZeroLED", FakeLEDDevice),
            patch.object(leds_module, "GpioZeroPWMLED", FakePWMLEDDevice),
            patch.object(leds_module, "LGPIOFactory", FakeFactory),
        ):
            controller = leds_module.LEDController()
            ok = controller.apply_leds(
                [
                    {"pin": "GPIO18", "brightness": 40, "is_on": False},
                ]
            )

            self.assertTrue(ok)
            self.assertNotIn(18, controller._pwm)
            self.assertFalse(controller._digital[18].is_lit)

    def test_led_controller_uses_pwm_on_non_pwm_pin(self):
        with (
            patch.object(leds_module, "GPIO", None),
            patch.object(leds_module, "GpioZeroLED", FakeLEDDevice),
            patch.object(leds_module, "GpioZeroPWMLED", FakePWMLEDDevice),
            patch.object(leds_module, "LGPIOFactory", FakeFactory),
        ):
            controller = leds_module.LEDController()
            ok = controller.apply_leds(
                [
                    {"pin": "GPIO16", "brightness": 40, "is_on": True},
                ]
            )

            self.assertTrue(ok)
            self.assertIn(16, controller._pwm)
            self.assertEqual(controller._pwm[16].value, 0.4)

    def test_led_controller_returns_false_on_busy_pwm_pin(self):
        class BusyPWMLEDDevice(FakePWMLEDDevice):
            def __init__(self, pin, pin_factory=None, initial_value=0, frequency=None):
                if pin == 18:
                    raise RuntimeError("GPIO busy")
                super().__init__(pin, pin_factory=pin_factory, initial_value=initial_value, frequency=frequency)

        with (
            patch.object(leds_module, "GPIO", None),
            patch.object(leds_module, "GpioZeroLED", FakeLEDDevice),
            patch.object(leds_module, "GpioZeroPWMLED", BusyPWMLEDDevice),
            patch.object(leds_module, "LGPIOFactory", FakeFactory),
        ):
            controller = leds_module.LEDController()
            ok = controller.blink_led("GPIO18", brightness=40)

        self.assertFalse(ok)

    def test_detect_leds_reports_reserved_pin_conflicts_without_blank_pwm_noise(self):
        setup = {
            "reader": {"type": "RC522"},
            "audio": {"output_mode": "usb_dac"},
            "leds": [
                {"pin": "GPIO25", "brightness": 50},
                {"pin": "", "brightness": 30},
            ],
        }

        result = manager_module.detect_leds(setup)

        self.assertTrue(any("GPIO25" in note for note in result["notes"]))
        self.assertFalse(any(" , " in note for note in result["notes"]))

    def test_detect_reader_uses_reader_status_for_rc522(self):
        setup = {"reader": {"type": "RC522"}}

        with patch.object(
            manager_module,
            "load_json",
            return_value={
                "configured_type": "RC522",
                "ready": False,
                "message": "RC522 nicht erkannt.",
                "details": ["CE0/RST25=0x0"],
            },
        ):
            result = manager_module.detect_reader(setup)

        self.assertFalse(result["ready"])
        self.assertIn("RC522 nicht erkannt.", result["notes"])

    def test_detect_reader_reports_none_as_not_installed(self):
        setup = {"reader": {"type": "NONE", "target_type": "RC522"}}

        result = manager_module.detect_reader(setup)

        self.assertFalse(result["ready"])
        self.assertIn("Kein Reader installiert.", result["notes"])

    def test_detect_cover_appends_cache_token(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            album_dir = base_dir / "media" / "albums" / "test"
            album_dir.mkdir(parents=True, exist_ok=True)
            cover = album_dir / "cover.png"
            cover.write_bytes(b"png")

            with patch.object(library_service, "BASE_DIR", base_dir):
                cover_url = library_service.detect_cover(album_dir)

            self.assertTrue(cover_url.startswith("media/albums/test/cover.png?v="))


if __name__ == "__main__":
    unittest.main()
