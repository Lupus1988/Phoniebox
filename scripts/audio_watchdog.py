#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from runtime.playback import configured_audio_output_ready
from runtime.service import RuntimeService, default_runtime_state


USB_SYSFS = Path("/sys/bus/usb/devices")
USB_AUDIO_CLASS = "01"
USBCORE_AUTOSUSPEND = Path("/sys/module/usbcore/parameters/autosuspend")


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _write_text(path, value):
    try:
        path.write_text(str(value), encoding="utf-8")
        return True
    except OSError:
        return False


def _usb_device_for_interface(interface_path):
    direct_device = interface_path.parent / interface_path.name.split(":", 1)[0]
    if (direct_device / "idVendor").exists() and (direct_device / "idProduct").exists():
        return direct_device
    current = interface_path
    while current != USB_SYSFS and current.parent != current:
        if (current / "idVendor").exists() and (current / "idProduct").exists():
            return current
        current = current.parent
    return None


def usb_audio_devices():
    devices = {}
    if not USB_SYSFS.exists():
        return []
    for interface_class in USB_SYSFS.glob("*/bInterfaceClass"):
        if _read_text(interface_class).lower() != USB_AUDIO_CLASS:
            continue
        device = _usb_device_for_interface(interface_class.parent)
        if device is not None:
            devices[str(device)] = device
    return list(devices.values())


def disable_usb_audio_autosuspend():
    touched = []
    if USBCORE_AUTOSUSPEND.exists() and _read_text(USBCORE_AUTOSUSPEND) != "-1":
        if _write_text(USBCORE_AUTOSUSPEND, "-1"):
            touched.append(
                {
                    "path": str(USBCORE_AUTOSUSPEND),
                    "vendor": "usbcore",
                    "product": "autosuspend",
                    "name": "Global USB autosuspend disabled",
                }
            )
    for device in usb_audio_devices():
        power_dir = device / "power"
        control = power_dir / "control"
        delay = power_dir / "autosuspend_delay_ms"
        changed = False
        if control.exists() and _read_text(control) != "on":
            changed = _write_text(control, "on") or changed
        if delay.exists() and _read_text(delay) != "-1":
            changed = _write_text(delay, "-1") or changed
        if changed:
            touched.append(
                {
                    "path": str(device),
                    "vendor": _read_text(device / "idVendor"),
                    "product": _read_text(device / "idProduct"),
                    "name": _read_text(device / "product"),
                }
            )
    return touched


def _load_player(service):
    return service.load_player()


def _mark_audio_state(service, ready, reason):
    with service.state_transaction():
        runtime_state = service.ensure_runtime()
        player = _load_player(service)
        watchdog = dict(runtime_state.get("audio_watchdog") or {})
        previous_ready = watchdog.get("ready")
        session = runtime_state.get("playback_session", {})
        session_had_process = bool(session.get("pid"))
        should_stop_playback = (not ready) and (
            runtime_state.get("playback_state") == "playing"
            or session_had_process
        )

        if should_stop_playback and session:
            runtime_state["playback_session"] = service.playback.pause(session)
            runtime_state["playback_state"] = "paused"
            player["is_playing"] = False
            player["position_seconds"] = max(
                0,
                int(runtime_state["playback_session"].get("position_seconds", player.get("position_seconds", 0)) or 0),
            )
            runtime_state["playback_session"]["state"] = "error"
            runtime_state["playback_session"]["error"] = reason

        watchdog.update(
            {
                "ready": bool(ready),
                "message": "" if ready else str(reason or "Audioausgabe nicht verfügbar."),
                "updated_at": int(time.time()),
            }
        )
        runtime_state["audio_watchdog"] = watchdog

        if should_stop_playback:
            runtime_state = service.add_event(runtime_state, f"Audioausgabe verloren: {reason}", "warning")
        elif ready and previous_ready is False:
            runtime_state = service.add_event(runtime_state, "Audioausgabe wieder verfügbar")
        elif (not ready) and previous_ready is not False:
            runtime_state = service.add_event(runtime_state, f"Audioausgabe nicht verfügbar: {reason}", "warning")

        service.save_runtime(runtime_state)
        service.save_player(player)
        return runtime_state


def watchdog_tick(service=None):
    disable_usb_audio_autosuspend()
    ready, reason = configured_audio_output_ready()
    service = service or RuntimeService()
    return _mark_audio_state(service, ready, reason)


def run_forever(interval_seconds=5.0):
    service = RuntimeService()
    interval = max(1.0, float(interval_seconds or 5.0))
    while True:
        started_at = time.monotonic()
        try:
            watchdog_tick(service)
        except Exception:
            pass
        elapsed = time.monotonic() - started_at
        time.sleep(max(0.25, interval - elapsed))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Phoniebox USB audio watchdog")
    parser.add_argument("--daemon", action="store_true", help="Watchdog dauerhaft ausführen")
    parser.add_argument("--interval", type=float, default=5.0, help="Intervall in Sekunden für --daemon")
    parser.add_argument("--json", action="store_true", help="Einmal ausführen und Runtime-State als JSON ausgeben")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.daemon:
        run_forever(args.interval)
        return 0
    runtime_state = watchdog_tick()
    if args.json:
        print(json.dumps(runtime_state.get("audio_watchdog", {}), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
