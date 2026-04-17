#!/usr/bin/env python3
import json
import math
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.leds import LEDController, load_json


DATA_DIR = BASE_DIR / "data"
RUNTIME_FILE = DATA_DIR / "runtime_state.json"
LED_PREVIEW_FILE = DATA_DIR / "led_preview.json"


def consume_led_preview(controller):
    preview = load_json(LED_PREVIEW_FILE, {})
    if not isinstance(preview, dict) or preview.get("status") != "pending":
        return False

    pin = str(preview.get("pin", "")).strip()
    if not pin:
        try:
            LED_PREVIEW_FILE.unlink()
        except OSError:
            pass
        return False

    ok = False
    for _ in range(8):
        ok = controller.blink_led(
            pin,
            brightness=int(preview.get("brightness", 100) or 100),
            repeats=max(1, int(preview.get("repeats", 3) or 3)),
            on_seconds=max(0.02, float(preview.get("on_seconds", 0.22) or 0.22)),
            off_seconds=max(0.02, float(preview.get("off_seconds", 0.18) or 0.18)),
        )
        if ok:
            break
        time.sleep(0.08)
    preview["status"] = "done" if ok else "error"
    preview["finished_at"] = time.time()
    LED_PREVIEW_FILE.write_text(json.dumps(preview, indent=2, ensure_ascii=False), encoding="utf-8")
    return ok


def main():
    controller = LEDController()
    last_payload = None
    try:
        while True:
            if consume_led_preview(controller):
                last_payload = None
            runtime = load_json(RUNTIME_FILE, {})
            led_status = runtime.get("led_status", [])
            rendered = []
            has_pulse = False
            for led in led_status:
                rendered_led = dict(led)
                if led.get("effect") == "blink" and led.get("is_on"):
                    has_pulse = True
                    phase = (time.monotonic() % 1.8) / 1.8
                    rendered_led["brightness"] = float(led.get("brightness", 0) or 0) if phase < 0.5 else 0.0
                elif led.get("effect") == "pulse" and led.get("is_on"):
                    has_pulse = True
                    phase = (time.monotonic() % 8.0) / 8.0
                    wave = 0.5 - 0.5 * math.cos(phase * 2.0 * math.pi)
                    base = max(0, min(100, int(led.get("brightness", 0) or 0)))
                    rendered_led["brightness"] = round(max(5.0, base * (0.05 + 0.95 * wave)), 1)
                elif led.get("effect") in {"power_ramp_up", "power_ramp_down"} and led.get("is_on"):
                    has_pulse = True
                    progress = max(0.0, min(1.0, float(led.get("effect_progress", 0.0) or 0.0)))
                    base = max(0, min(100, int(led.get("brightness", 0) or 0)))
                    start_duration = 1.35
                    end_duration = 0.22
                    if led.get("effect") == "power_ramp_up":
                        cycle_duration = start_duration + ((end_duration - start_duration) * progress)
                    else:
                        cycle_duration = end_duration + ((start_duration - end_duration) * progress)
                    cycle_duration = max(0.16, cycle_duration)
                    phase = (time.monotonic() / cycle_duration) % 1.0
                    wave = 0.5 - 0.5 * math.cos(phase * 2.0 * math.pi)
                    rendered_led["brightness"] = round(max(3.0, base * (0.12 + 0.88 * wave)), 1)
                rendered.append(rendered_led)
            payload = json.dumps(rendered, sort_keys=True, ensure_ascii=False)
            if has_pulse or payload != last_payload:
                controller.apply_leds(rendered)
                last_payload = payload
            time.sleep(0.07 if has_pulse else 0.2)
    finally:
        controller.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
