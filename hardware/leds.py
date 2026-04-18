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

try:
    import lgpio
except ImportError:
    lgpio = None


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


def normalize_pwm_frequency(value, default):
    try:
        frequency = int(float(value or default))
    except (TypeError, ValueError):
        frequency = int(default)
    return max(50, min(10000, frequency))


def normalize_gamma(value, default=1.0):
    try:
        gamma = float(value or default)
    except (TypeError, ValueError):
        gamma = float(default)
    return max(0.2, min(3.0, gamma))


def apply_gamma(brightness, gamma=1.0):
    normalized = normalize_brightness(brightness) / 100.0
    gamma = normalize_gamma(gamma, 1.0)
    if normalized <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (normalized ** gamma) * 100.0)), 4)


class LEDController:
    GPIOZERO_PWM_FREQUENCY = 800
    RPI_GPIO_PWM_FREQUENCY = 1000
    LGPIO_PWM_FREQUENCY = 800

    def __init__(self):
        self._gpio_ready = False
        self._lgpio_handle = None
        self._lgpio_unavailable = False
        self._lgpio_claimed = set()
        self._lgpio_pwm = set()
        self._gpiozero_factory = None
        self._gpiozero_unavailable = False
        self._digital = {}
        self._pwm = {}
        self._pwm_frequency = {}
        self._configured_pins = set()

    def available(self):
        return self._lgpio_available() or self._gpiozero_available() or GPIO is not None

    def _lgpio_available(self):
        return not self._lgpio_unavailable and lgpio is not None

    def _ensure_lgpio_handle(self):
        if not self._lgpio_available():
            return None
        if self._lgpio_handle is None:
            try:
                self._lgpio_handle = lgpio.gpiochip_open(0)
            except Exception:
                self._lgpio_unavailable = True
                return None
            if self._lgpio_handle is None or self._lgpio_handle < 0:
                self._lgpio_handle = None
                self._lgpio_unavailable = True
                return None
        return self._lgpio_handle

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

    def _ensure_pwm(self, bcm_pin, frequency=None):
        requested_frequency = normalize_pwm_frequency(frequency, self.RPI_GPIO_PWM_FREQUENCY)
        if bcm_pin in self._pwm and self._pwm_frequency.get(bcm_pin) != requested_frequency:
            self._disable_pwm(bcm_pin)
        if bcm_pin not in self._pwm:
            if not self._ensure_output(bcm_pin):
                return None
            try:
                pwm = GPIO.PWM(bcm_pin, requested_frequency)
                pwm.start(0)
            except Exception:
                return None
            self._pwm[bcm_pin] = pwm
            self._pwm_frequency[bcm_pin] = requested_frequency
        return self._pwm[bcm_pin]

    def _close_gpiozero_device(self, bcm_pin):
        pwm = self._pwm.pop(bcm_pin, None)
        self._pwm_frequency.pop(bcm_pin, None)
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

    def _ensure_gpiozero_pwm(self, bcm_pin, frequency=None):
        factory = self._ensure_gpiozero_factory()
        if factory is None:
            return None
        requested_frequency = normalize_pwm_frequency(frequency, self.GPIOZERO_PWM_FREQUENCY)
        if bcm_pin in self._pwm and self._pwm_frequency.get(bcm_pin) == requested_frequency:
            return self._pwm[bcm_pin]
        self._close_gpiozero_device(bcm_pin)
        try:
            pwm = GpioZeroPWMLED(
                bcm_pin,
                pin_factory=factory,
                frequency=requested_frequency,
                initial_value=0,
            )
        except Exception:
            self._gpiozero_unavailable = True
            self._gpiozero_factory = None
            return None
        self._pwm[bcm_pin] = pwm
        self._pwm_frequency[bcm_pin] = requested_frequency
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
        self._pwm_frequency.pop(bcm_pin, None)

    def _ensure_lgpio_output(self, bcm_pin):
        handle = self._ensure_lgpio_handle()
        if handle is None:
            return None
        if bcm_pin in self._lgpio_claimed:
            return handle
        try:
            result = lgpio.gpio_claim_output(handle, bcm_pin, 0)
        except Exception:
            self._lgpio_unavailable = True
            return None
        if result < 0:
            return None
        self._lgpio_claimed.add(bcm_pin)
        self._configured_pins.add(bcm_pin)
        return handle

    def _stop_lgpio_pwm(self, bcm_pin):
        if bcm_pin not in self._lgpio_pwm:
            return
        handle = self._ensure_lgpio_handle()
        if handle is None:
            return
        try:
            lgpio.tx_pwm(handle, bcm_pin, 0, 0)
        except Exception:
            pass
        self._lgpio_pwm.discard(bcm_pin)

    def _apply_leds_lgpio(self, led_status):
        handle = self._ensure_lgpio_handle()
        if handle is None:
            return False

        desired_pins = set()
        for led in led_status:
            bcm_pin = gpio_name_to_bcm(led.get("pin", ""))
            if bcm_pin is None:
                continue
            if self._ensure_lgpio_output(bcm_pin) is None:
                return False
            desired_pins.add(bcm_pin)
            brightness = apply_gamma(led.get("brightness", 0), led.get("brightness_gamma", 1.0))
            pwm_frequency_hz = normalize_pwm_frequency(led.get("pwm_frequency_hz"), self.LGPIO_PWM_FREQUENCY)
            active = bool(led.get("is_on")) and brightness > 0

            if active and 0 < brightness < 100:
                try:
                    result = lgpio.tx_pwm(handle, bcm_pin, pwm_frequency_hz, brightness)
                except Exception:
                    return False
                if result < 0:
                    return False
                self._lgpio_pwm.add(bcm_pin)
                continue

            self._stop_lgpio_pwm(bcm_pin)
            try:
                result = lgpio.gpio_write(handle, bcm_pin, 1 if active else 0)
            except Exception:
                return False
            if result < 0:
                return False

        for bcm_pin in list(self._configured_pins - desired_pins):
            self._stop_lgpio_pwm(bcm_pin)
            if bcm_pin in self._lgpio_claimed and handle is not None:
                try:
                    lgpio.gpio_write(handle, bcm_pin, 0)
                except Exception:
                    pass
                try:
                    lgpio.gpio_free(handle, bcm_pin)
                except Exception:
                    pass
                self._lgpio_claimed.discard(bcm_pin)
            self._close_gpiozero_device(bcm_pin)
            self._disable_pwm(bcm_pin)
            self._configured_pins.discard(bcm_pin)

        return True

    def _apply_leds_gpiozero(self, led_status):
        desired_pins = set()
        for led in led_status:
            bcm_pin = gpio_name_to_bcm(led.get("pin", ""))
            if bcm_pin is None:
                continue
            desired_pins.add(bcm_pin)
            brightness = apply_gamma(led.get("brightness", 0), led.get("brightness_gamma", 1.0))
            pwm_frequency_hz = normalize_pwm_frequency(led.get("pwm_frequency_hz"), self.GPIOZERO_PWM_FREQUENCY)
            active = bool(led.get("is_on")) and brightness > 0

            if active and 0 < brightness < 100:
                pwm = self._pwm.get(bcm_pin)
                if pwm is None:
                    pwm = self._ensure_gpiozero_pwm(bcm_pin, pwm_frequency_hz)
                elif self._pwm_frequency.get(bcm_pin) != pwm_frequency_hz:
                    pwm = self._ensure_gpiozero_pwm(bcm_pin, pwm_frequency_hz)
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
            brightness = apply_gamma(led.get("brightness", 0), led.get("brightness_gamma", 1.0))
            pwm_frequency_hz = normalize_pwm_frequency(led.get("pwm_frequency_hz"), self.RPI_GPIO_PWM_FREQUENCY)
            active = bool(led.get("is_on")) and brightness > 0

            if active and 0 < brightness < 100:
                pwm = self._ensure_pwm(bcm_pin, pwm_frequency_hz)
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
        if self._lgpio_available():
            ok = self._apply_leds_lgpio(led_status)
            if ok:
                return True
        if self._gpiozero_available():
            ok = self._apply_leds_gpiozero(led_status)
            if ok:
                return True
        return self._apply_leds_rpigpio(led_status)

    def cleanup(self):
        for bcm_pin in list(self._configured_pins):
            self._stop_lgpio_pwm(bcm_pin)
            if bcm_pin in self._lgpio_claimed and self._lgpio_handle is not None:
                try:
                    lgpio.gpio_write(self._lgpio_handle, bcm_pin, 0)
                except Exception:
                    pass
                try:
                    lgpio.gpio_free(self._lgpio_handle, bcm_pin)
                except Exception:
                    pass
                self._lgpio_claimed.discard(bcm_pin)
            self._close_gpiozero_device(bcm_pin)
        if GPIO is not None:
            for bcm_pin in list(self._configured_pins):
                self._disable_pwm(bcm_pin)
                try:
                    GPIO.output(bcm_pin, GPIO.LOW)
                    GPIO.cleanup(bcm_pin)
                except RuntimeError:
                    continue
        if self._lgpio_handle is not None:
            try:
                lgpio.gpiochip_close(self._lgpio_handle)
            except Exception:
                pass
            self._lgpio_handle = None
        self._configured_pins.clear()

    def blink_led(self, gpio_name, brightness=100, pwm_frequency_hz=None, brightness_gamma=1.0, repeats=3, on_seconds=0.22, off_seconds=0.18):
        bcm_pin = gpio_name_to_bcm(gpio_name)
        if bcm_pin is None:
            return False

        brightness = apply_gamma(brightness, brightness_gamma)
        active_brightness = 100 if brightness <= 0 else brightness

        if self._lgpio_available():
            handle = self._ensure_lgpio_handle()
            if handle is None or self._ensure_lgpio_output(bcm_pin) is None:
                return False
            pwm_frequency_hz = normalize_pwm_frequency(pwm_frequency_hz, self.LGPIO_PWM_FREQUENCY)
            try:
                if 0 < active_brightness < 100:
                    for _ in range(max(1, int(repeats))):
                        lgpio.tx_pwm(handle, bcm_pin, pwm_frequency_hz, active_brightness)
                        self._lgpio_pwm.add(bcm_pin)
                        time.sleep(max(0.02, float(on_seconds)))
                        self._stop_lgpio_pwm(bcm_pin)
                        lgpio.gpio_write(handle, bcm_pin, 0)
                        time.sleep(max(0.02, float(off_seconds)))
                else:
                    for _ in range(max(1, int(repeats))):
                        lgpio.gpio_write(handle, bcm_pin, 1)
                        time.sleep(max(0.02, float(on_seconds)))
                        lgpio.gpio_write(handle, bcm_pin, 0)
                        time.sleep(max(0.02, float(off_seconds)))
            except Exception:
                return False
            finally:
                self._stop_lgpio_pwm(bcm_pin)
                try:
                    lgpio.gpio_write(handle, bcm_pin, 0)
                except Exception:
                    pass
            return True

        if self._gpiozero_available():
            try:
                if 0 < active_brightness < 100:
                    pwm = self._pwm.get(bcm_pin)
                    if pwm is None:
                        pwm = self._ensure_gpiozero_pwm(bcm_pin, pwm_frequency_hz)
                    elif self._pwm_frequency.get(bcm_pin) != normalize_pwm_frequency(pwm_frequency_hz, self.GPIOZERO_PWM_FREQUENCY):
                        pwm = self._ensure_gpiozero_pwm(bcm_pin, pwm_frequency_hz)
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
                pwm = self._ensure_pwm(bcm_pin, pwm_frequency_hz)
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
