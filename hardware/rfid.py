from pathlib import Path

try:
    from evdev import InputDevice, ecodes, list_devices
except ImportError:
    InputDevice = None
    ecodes = None
    list_devices = None


KEYCODE_MAP = {
    "KEY_0": "0",
    "KEY_1": "1",
    "KEY_2": "2",
    "KEY_3": "3",
    "KEY_4": "4",
    "KEY_5": "5",
    "KEY_6": "6",
    "KEY_7": "7",
    "KEY_8": "8",
    "KEY_9": "9",
    "KEY_KP0": "0",
    "KEY_KP1": "1",
    "KEY_KP2": "2",
    "KEY_KP3": "3",
    "KEY_KP4": "4",
    "KEY_KP5": "5",
    "KEY_KP6": "6",
    "KEY_KP7": "7",
    "KEY_KP8": "8",
    "KEY_KP9": "9",
    "KEY_A": "A",
    "KEY_B": "B",
    "KEY_C": "C",
    "KEY_D": "D",
    "KEY_E": "E",
    "KEY_F": "F",
}


def evdev_available():
    return InputDevice is not None and ecodes is not None and list_devices is not None


def decode_keycode_to_char(keycode):
    return KEYCODE_MAP.get(keycode, "")


def discover_usb_keyboard_devices():
    if not evdev_available():
        return []

    candidates = []
    by_id = Path("/dev/input/by-id")
    if by_id.exists():
        for path in sorted(by_id.glob("*-event-kbd")):
            try:
                candidates.append(path.resolve())
            except OSError:
                continue

    if candidates:
        return [str(path) for path in candidates]

    fallback = []
    for device_path in list_devices():
        try:
            device = InputDevice(device_path)
            capabilities = device.capabilities(verbose=True)
            if any(str(item[0]).endswith("EV_KEY") for item in capabilities):
                fallback.append(device.path)
            device.close()
        except OSError:
            continue
    return fallback
