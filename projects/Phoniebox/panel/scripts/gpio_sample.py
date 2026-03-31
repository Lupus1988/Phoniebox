#!/usr/bin/env python3
import json
import sys
from pathlib import Path

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.gpio import SysfsGPIOInput, gpio_name_to_bcm


def sample_with_rpi(gpio_names):
    if GPIO is None:
        return {}
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    sampled = {}
    for gpio_name in gpio_names:
        bcm = gpio_name_to_bcm(gpio_name)
        if bcm is None:
            continue
        GPIO.setup(bcm, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        sampled[gpio_name] = int(GPIO.input(bcm))
    return sampled


def main(argv):
    gpio_names = [item for item in argv[1:] if item]
    if not gpio_names:
        print("{}")
        return 0
    try:
        sampled = sample_with_rpi(gpio_names)
    except Exception:
        sampled = {}
    if not sampled:
        sampled = SysfsGPIOInput().sample(gpio_names)
    print(json.dumps(sampled, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
