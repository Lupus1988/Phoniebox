import json
import time
from pathlib import Path

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None


PWM_PINS = {12, 13, 18, 19}


def gpio_name_to_bcm(gpio_name):
    if not gpio_name or not str(gpio_name).startswith("GPIO"):
        return None
    try:
        return int(str(gpio_name).replace("GPIO", "", 1))
    except ValueError:
        return None


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


class LEDController:
    def __init__(self):
        self._gpio_ready = False
        self._pwm = {}
        self._configured_pins = set()

    def available(self):
        return GPIO is not None

    def ensure_gpio(self):
        if not self.available():
            return False
        if not self._gpio_ready:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            self._gpio_ready = True
        return True

    def _ensure_output(self, bcm_pin):
        if not self.ensure_gpio():
            return False
        GPIO.setup(bcm_pin, GPIO.OUT, initial=GPIO.LOW)
        self._configured_pins.add(bcm_pin)
        return True

    def _ensure_pwm(self, bcm_pin):
        if bcm_pin not in self._pwm:
            self._ensure_output(bcm_pin)
            pwm = GPIO.PWM(bcm_pin, 200)
            pwm.start(0)
            self._pwm[bcm_pin] = pwm
        return self._pwm[bcm_pin]

    def _disable_pwm(self, bcm_pin):
        pwm = self._pwm.pop(bcm_pin, None)
        if pwm is not None:
            try:
                pwm.ChangeDutyCycle(0)
                pwm.stop()
            except RuntimeError:
                pass

    def apply_leds(self, led_status):
        if not self.ensure_gpio():
            return False

        desired_pins = set()
        for led in led_status:
            bcm_pin = gpio_name_to_bcm(led.get("pin", ""))
            if bcm_pin is None:
                continue
            desired_pins.add(bcm_pin)
            brightness = max(0, min(100, int(led.get("brightness", 0) or 0)))
            active = bool(led.get("is_on")) and brightness > 0

            if bcm_pin in PWM_PINS and 0 < brightness < 100:
                pwm = self._ensure_pwm(bcm_pin)
                try:
                    pwm.ChangeDutyCycle(brightness if active else 0)
                except RuntimeError:
                    continue
                continue

            self._disable_pwm(bcm_pin)
            if not self._ensure_output(bcm_pin):
                continue
            try:
                GPIO.output(bcm_pin, GPIO.HIGH if active else GPIO.LOW)
            except RuntimeError:
                continue

        for bcm_pin in list(self._configured_pins - desired_pins):
            self._disable_pwm(bcm_pin)
            try:
                GPIO.setup(bcm_pin, GPIO.OUT, initial=GPIO.LOW)
                GPIO.output(bcm_pin, GPIO.LOW)
                GPIO.cleanup(bcm_pin)
            except RuntimeError:
                continue
            self._configured_pins.discard(bcm_pin)

        return True

    def cleanup(self):
        for bcm_pin in list(self._configured_pins):
            self._disable_pwm(bcm_pin)
            try:
                GPIO.output(bcm_pin, GPIO.LOW)
                GPIO.cleanup(bcm_pin)
            except RuntimeError:
                continue
        self._configured_pins.clear()

    def blink_led(self, gpio_name, brightness=100, repeats=3, on_seconds=0.22, off_seconds=0.18):
        bcm_pin = gpio_name_to_bcm(gpio_name)
        if bcm_pin is None:
            return False
        if not self.ensure_gpio():
            return False

        brightness = max(0, min(100, int(brightness or 0)))
        active_brightness = 100 if brightness <= 0 else brightness

        try:
            if 0 < active_brightness < 100:
                pwm = self._ensure_pwm(bcm_pin)
                for _ in range(max(1, int(repeats))):
                    pwm.ChangeDutyCycle(active_brightness)
                    time.sleep(max(0.02, float(on_seconds)))
                    pwm.ChangeDutyCycle(0)
                    time.sleep(max(0.02, float(off_seconds)))
            else:
                self._disable_pwm(bcm_pin)
                if not self._ensure_output(bcm_pin):
                    return False
                for _ in range(max(1, int(repeats))):
                    GPIO.output(bcm_pin, GPIO.HIGH)
                    time.sleep(max(0.02, float(on_seconds)))
                    GPIO.output(bcm_pin, GPIO.LOW)
                    time.sleep(max(0.02, float(off_seconds)))
        except RuntimeError:
            return False
        finally:
            self._disable_pwm(bcm_pin)
            try:
                GPIO.output(bcm_pin, GPIO.LOW)
            except RuntimeError:
                pass

        return True
