import json
import time
from pathlib import Path

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

try:
    from gpiozero import LED as GpioZeroLED
    from gpiozero import PWMLED as GpioZeroPWMLED
    from gpiozero.pins.lgpio import LGPIOFactory
except ImportError:
    GpioZeroLED = None
    GpioZeroPWMLED = None
    LGPIOFactory = None


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


def normalize_brightness(value):
    try:
        brightness = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, brightness))


class LEDController:
    def __init__(self):
        self._gpio_ready = False
        self._gpiozero_factory = None
        self._gpiozero_unavailable = False
        self._digital = {}
        self._pwm = {}
        self._configured_pins = set()

    def available(self):
        return self._gpiozero_available() or GPIO is not None

    def _gpiozero_available(self):
        return (
            not self._gpiozero_unavailable
            and GpioZeroLED is not None
            and GpioZeroPWMLED is not None
            and LGPIOFactory is not None
        )

    def _ensure_gpiozero_factory(self):
        if not self._gpiozero_available():
            return None
        if self._gpiozero_factory is None:
            try:
                self._gpiozero_factory = LGPIOFactory()
            except Exception:
                self._gpiozero_unavailable = True
                return None
        return self._gpiozero_factory

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
        try:
            GPIO.setup(bcm_pin, GPIO.OUT, initial=GPIO.LOW)
        except Exception:
            return False
        self._configured_pins.add(bcm_pin)
        return True

    def _ensure_pwm(self, bcm_pin):
        if bcm_pin not in self._pwm:
            if not self._ensure_output(bcm_pin):
                return None
            try:
                pwm = GPIO.PWM(bcm_pin, 200)
                pwm.start(0)
            except Exception:
                return None
            self._pwm[bcm_pin] = pwm
        return self._pwm[bcm_pin]

    def _close_gpiozero_device(self, bcm_pin):
        pwm = self._pwm.pop(bcm_pin, None)
        if pwm is not None:
            try:
                pwm.off()
                pwm.close()
            except Exception:
                pass
        led = self._digital.pop(bcm_pin, None)
        if led is not None:
            try:
                led.off()
                led.close()
            except Exception:
                pass

    def _ensure_gpiozero_pwm(self, bcm_pin):
        factory = self._ensure_gpiozero_factory()
        if factory is None:
            return None
        self._close_gpiozero_device(bcm_pin)
        try:
            pwm = GpioZeroPWMLED(bcm_pin, pin_factory=factory, frequency=120, initial_value=0)
        except Exception:
            self._gpiozero_unavailable = True
            self._gpiozero_factory = None
            return None
        self._pwm[bcm_pin] = pwm
        self._configured_pins.add(bcm_pin)
        return pwm

    def _ensure_gpiozero_output(self, bcm_pin):
        factory = self._ensure_gpiozero_factory()
        if factory is None:
            return None
        self._close_gpiozero_device(bcm_pin)
        try:
            led = GpioZeroLED(bcm_pin, pin_factory=factory, initial_value=False)
        except Exception:
            self._gpiozero_unavailable = True
            self._gpiozero_factory = None
            return None
        self._digital[bcm_pin] = led
        self._configured_pins.add(bcm_pin)
        return led

    def _disable_pwm(self, bcm_pin):
        pwm = self._pwm.pop(bcm_pin, None)
        if pwm is not None:
            try:
                pwm.ChangeDutyCycle(0)
                pwm.stop()
            except RuntimeError:
                pass

    def _apply_leds_gpiozero(self, led_status):
        desired_pins = set()
        for led in led_status:
            bcm_pin = gpio_name_to_bcm(led.get("pin", ""))
            if bcm_pin is None:
                continue
            desired_pins.add(bcm_pin)
            brightness = normalize_brightness(led.get("brightness", 0))
            active = bool(led.get("is_on")) and brightness > 0

            if active and 0 < brightness < 100:
                pwm = self._pwm.get(bcm_pin)
                if pwm is None:
                    pwm = self._ensure_gpiozero_pwm(bcm_pin)
                if pwm is None:
                    return False
                try:
                    pwm.value = brightness / 100.0
                except Exception:
                    return False
                continue

            led_device = self._digital.get(bcm_pin)
            if led_device is None:
                led_device = self._ensure_gpiozero_output(bcm_pin)
            if led_device is None:
                return False
            try:
                if active:
                    led_device.on()
                else:
                    led_device.off()
            except Exception:
                return False

        for bcm_pin in list(self._configured_pins - desired_pins):
            self._close_gpiozero_device(bcm_pin)
            self._configured_pins.discard(bcm_pin)

        return True

    def _apply_leds_rpigpio(self, led_status):
        if not self.ensure_gpio():
            return False

        desired_pins = set()
        for led in led_status:
            bcm_pin = gpio_name_to_bcm(led.get("pin", ""))
            if bcm_pin is None:
                continue
            desired_pins.add(bcm_pin)
            brightness = normalize_brightness(led.get("brightness", 0))
            active = bool(led.get("is_on")) and brightness > 0

            if active and 0 < brightness < 100:
                pwm = self._ensure_pwm(bcm_pin)
                if pwm is None:
                    continue
                try:
                    pwm.ChangeDutyCycle(brightness)
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

    def apply_leds(self, led_status):
        if self._gpiozero_available():
            ok = self._apply_leds_gpiozero(led_status)
            if ok:
                return True
        return self._apply_leds_rpigpio(led_status)

    def cleanup(self):
        for bcm_pin in list(self._configured_pins):
            self._close_gpiozero_device(bcm_pin)
        if GPIO is not None:
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

        brightness = max(0, min(100, int(brightness or 0)))
        active_brightness = 100 if brightness <= 0 else brightness

        if self._gpiozero_available():
            try:
                if 0 < active_brightness < 100:
                    pwm = self._pwm.get(bcm_pin)
                    if pwm is None:
                        pwm = self._ensure_gpiozero_pwm(bcm_pin)
                    if pwm is None:
                        return False
                    value = active_brightness / 100.0
                    for _ in range(max(1, int(repeats))):
                        pwm.value = value
                        time.sleep(max(0.02, float(on_seconds)))
                        pwm.value = 0
                        time.sleep(max(0.02, float(off_seconds)))
                else:
                    led_device = self._digital.get(bcm_pin)
                    if led_device is None:
                        led_device = self._ensure_gpiozero_output(bcm_pin)
                    if led_device is None:
                        return False
                    for _ in range(max(1, int(repeats))):
                        led_device.on()
                        time.sleep(max(0.02, float(on_seconds)))
                        led_device.off()
                        time.sleep(max(0.02, float(off_seconds)))
            except Exception:
                return False
            finally:
                self._close_gpiozero_device(bcm_pin)
            return True

        if not self.ensure_gpio():
            return False

        try:
            if 0 < active_brightness < 100:
                pwm = self._ensure_pwm(bcm_pin)
                if pwm is None:
                    return False
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
