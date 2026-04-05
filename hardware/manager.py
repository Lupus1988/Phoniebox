import shutil
import json
from pathlib import Path

from hardware.gpio import sysfs_gpio_available
from hardware.pins import reserved_system_pins
from system.audio import detect_audio_environment


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
READER_STATUS_FILE = DATA_DIR / "reader_status.json"


def command_exists(name):
    return shutil.which(name) is not None


def gpio_backend_available():
    return any(Path("/dev").glob("gpiochip*")) or sysfs_gpio_available()


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def detect_reader(setup_data):
    reader = setup_data.get("reader", {})
    reader_type = (reader.get("type") or "NONE").strip()
    target_type = (reader.get("target_type") or reader_type).strip()
    reader_status = load_json(READER_STATUS_FILE, {})
    result = {
        "configured_type": reader_type,
        "ready": False,
        "driver": "",
        "transport": "",
        "notes": [],
    }
    if reader_type == "NONE":
        result["notes"].append("Kein Reader installiert.")
        if target_type != "NONE":
            result["notes"].append(f"Ausgewählt: {target_type}. Installation im Setup ausführen.")
    elif reader_type == "USB":
        result["driver"] = "hid/keyboard-reader"
        result["transport"] = "usb"
        result["ready"] = True
        result["notes"].append("USB-RFID-Reader kann später als Tastatur-Input eingebunden werden.")
    elif reader_type == "RC522":
        result["driver"] = "mfrc522"
        result["transport"] = "spi"
        result["ready"] = bool(reader_status.get("ready")) if reader_status.get("configured_type") == "RC522" else False
        if reader_status.get("configured_type") == "RC522":
            if reader_status.get("message"):
                result["notes"].append(reader_status["message"])
            result["notes"].extend([detail for detail in reader_status.get("details", []) if detail])
        elif not (Path("/dev/spidev0.0").exists() or Path("/dev/spidev0.1").exists()):
            result["notes"].append("SPI-Gerät nicht sichtbar. Für echte Hardware später SPI aktivieren.")
        else:
            result["notes"].append("RC522 ausgewählt. Referenzpfad: CE0/GPIO8, RST/GPIO22, IRQ/GPIO18.")
    elif reader_type == "PN532_I2C":
        result["driver"] = "pn532"
        result["transport"] = "i2c"
        result["ready"] = Path("/dev/i2c-1").exists()
        if not result["ready"]:
            result["notes"].append("Kein I2C-Gerät sichtbar. Für echte Hardware später I2C aktivieren.")
    elif reader_type == "PN532_SPI":
        result["driver"] = "pn532"
        result["transport"] = "spi"
        result["ready"] = Path("/dev/spidev0.0").exists() or Path("/dev/spidev0.1").exists()
        if not result["ready"]:
            result["notes"].append("Kein SPI-Gerät sichtbar. Für echte Hardware später SPI aktivieren.")
    elif reader_type == "PN532_UART":
        result["driver"] = "pn532"
        result["transport"] = "uart"
        result["ready"] = Path("/dev/ttyS0").exists() or Path("/dev/serial0").exists()
        if not result["ready"]:
            result["notes"].append("Kein UART-Gerät sichtbar. Für echte Hardware später serielle Schnittstelle aktivieren.")
    else:
        result["notes"].append("Unbekannter Reader-Typ.")
    return result


def detect_buttons(setup_data):
    buttons = setup_data.get("buttons", [])
    reserved = reserved_system_pins(setup_data)
    conflicting = [button.get("pin", "").strip() for button in buttons if button.get("pin", "").strip() in reserved]
    active_buttons = [button for button in buttons if button.get("pin", "").strip() and button.get("pin", "").strip() not in reserved]
    notes = []
    if conflicting:
        notes.append(f"Tasten auf reservierten Pins werden ignoriert: {', '.join(sorted(set(conflicting)))}")
    notes.append("Button-Mapping ist vorbereitet." if buttons else "Noch keine Tasten konfiguriert.")
    return {
        "configured": len(buttons),
        "backend": "gpio",
        "ready": gpio_backend_available(),
        "active": len(active_buttons),
        "notes": notes,
    }


def detect_leds(setup_data):
    leds = setup_data.get("leds", [])
    reserved = reserved_system_pins(setup_data)
    pwm_pins = {"GPIO12", "GPIO13", "GPIO18", "GPIO19"}
    conflicting = [led.get("pin", "").strip() for led in leds if led.get("pin", "").strip() in reserved]
    active_leds = [led for led in leds if led.get("pin", "").strip() and led.get("pin", "").strip() not in reserved]
    invalid_pwm = [
        led.get("pin", "").strip()
        for led in active_leds
        if led.get("pin", "").strip() and int(led.get("brightness", 0)) not in {0, 100} and led.get("pin", "").strip() not in pwm_pins
    ]
    notes = []
    if conflicting:
        notes.append(f"LEDs auf reservierten Pins werden ignoriert: {', '.join(sorted(set(conflicting)))}")
    if invalid_pwm:
        notes.append(f"Für Helligkeit fehlen PWM-Pins: {', '.join(invalid_pwm)}")
    if leds:
        notes.append("LED-Konfiguration ist vorbereitet.")
    return {
        "configured": len(leds),
        "backend": "gpio-pwm",
        "ready": gpio_backend_available(),
        "active": len(active_leds),
        "notes": notes or ["Keine LED-Konflikte erkannt."],
    }


def detect_audio(library_data, setup_data=None):
    albums = library_data.get("albums", [])
    playlist_count = sum(1 for album in albums if album.get("playlist"))
    setup_data = setup_data or {}
    audio_setup = setup_data.get("audio", {})
    audio_env = detect_audio_environment()
    backend = "python-playlist-core"
    ready = bool(audio_env.get("cards")) or command_exists("mpg123") or command_exists("cvlc")
    notes = list(audio_env.get("notes", []))
    if command_exists("mpg123"):
        notes.append("mpg123 vorhanden, kann später als Playback-Backend dienen.")
    elif command_exists("cvlc"):
        notes.append("cvlc vorhanden, kann später als Playback-Backend dienen.")
    else:
        notes.append("Noch kein System-Playback-Backend gefunden. Softwarekern bleibt aber kompatibel.")
    return {
        "configured_albums": len(albums),
        "albums_with_playlist": playlist_count,
        "backend": backend,
        "ready": ready,
        "notes": notes,
        "device_model": audio_env.get("device_model", "Unbekannt"),
        "detected_cards": audio_env.get("cards", []),
        "playback_devices": audio_env.get("playback_devices", []),
        "selected_output_mode": audio_setup.get("output_mode", "auto"),
        "selected_output": audio_setup.get("preferred_output", "auto"),
        "startup_volume": audio_setup.get("startup_volume", 45),
        "recommended_external_card": audio_env.get("recommended_external_card", False),
        "is_pi_zero_2w": audio_env.get("is_pi_zero_2w", False),
    }


def detect_hardware(setup_data, library_data):
    reader = detect_reader(setup_data)
    buttons = detect_buttons(setup_data)
    leds = detect_leds(setup_data)
    audio = detect_audio(library_data, setup_data)
    warnings = []
    for block in [reader, buttons, leds, audio]:
        warnings.extend(block.get("notes", []))
    return {
        "reader": reader,
        "buttons": buttons,
        "leds": leds,
        "audio": audio,
        "ready_for_integration": audio["ready"],
        "warnings": warnings,
    }
