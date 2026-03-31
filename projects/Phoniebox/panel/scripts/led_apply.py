#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.leds import LEDController, load_json


DATA_DIR = BASE_DIR / "data"
RUNTIME_FILE = DATA_DIR / "runtime_state.json"


def main():
    controller = LEDController()
    last_payload = None
    try:
        while True:
            runtime = load_json(RUNTIME_FILE, {})
            led_status = runtime.get("led_status", [])
            payload = json.dumps(led_status, sort_keys=True, ensure_ascii=False)
            if payload != last_payload:
                controller.apply_leds(led_status)
                last_payload = payload
            time.sleep(0.2)
    finally:
        controller.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
