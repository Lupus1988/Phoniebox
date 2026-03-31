import unittest
from unittest.mock import patch

from hardware import leds as leds_module
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


if __name__ == "__main__":
    unittest.main()
