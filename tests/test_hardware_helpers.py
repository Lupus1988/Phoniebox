import unittest
from unittest.mock import patch

from hardware import leds as leds_module
from hardware import manager as manager_module
from hardware import rfid as rfid_module


class FakePWM:
    def __init__(self, pin, freq):
        self.pin = pin
        self.freq = freq
        self.started = None
        self.duty = None

    def start(self, duty):
        self.started = duty

    def ChangeDutyCycle(self, duty):
        self.duty = duty

    def stop(self):
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
        fake_gpio = FakeGPIO()
        with patch.object(leds_module, "GPIO", fake_gpio):
            controller = leds_module.LEDController()
            ok = controller.apply_leds(
                [
                    {"pin": "GPIO23", "brightness": 100, "is_on": True},
                    {"pin": "GPIO18", "brightness": 40, "is_on": True},
                ]
            )

            self.assertTrue(ok)
            self.assertEqual(fake_gpio.outputs[23], fake_gpio.HIGH)
            self.assertIn(18, controller._pwm)
            self.assertEqual(controller._pwm[18].duty, 40)

    def test_led_controller_drives_inactive_pwm_pin_low_without_pwm(self):
        fake_gpio = FakeGPIO()
        with patch.object(leds_module, "GPIO", fake_gpio):
            controller = leds_module.LEDController()
            ok = controller.apply_leds(
                [
                    {"pin": "GPIO18", "brightness": 40, "is_on": False},
                ]
            )

            self.assertTrue(ok)
            self.assertNotIn(18, controller._pwm)
            self.assertEqual(fake_gpio.outputs[18], fake_gpio.LOW)

    def test_led_controller_returns_false_on_busy_pwm_pin(self):
        class BusyGPIO(FakeGPIO):
            def setup(self, pin, mode, initial=None):
                if pin == 18:
                    raise RuntimeError("GPIO busy")
                super().setup(pin, mode, initial=initial)

        fake_gpio = BusyGPIO()
        with patch.object(leds_module, "GPIO", fake_gpio):
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


if __name__ == "__main__":
    unittest.main()
