import shutil
from pathlib import Path

from hardware.gpio import sysfs_gpio_available
from system.audio import detect_audio_environment


def command_exists(name):
    return shutil.which(name) is not None


def gpio_backend_available():
    return any(Path("/dev").glob("gpiochip*")) or sysfs_gpio_available()


def detect_reader(setup_data):
    reader = setup_data.get("reader", {})
    reader_type = reader.get("type", "USB")
    result = {
        "configured_type": reader_type,
        "ready": False,
        "driver": "",
        "transport": "",
        "notes": [],
    }
    if reader_type == "USB":
        result["driver"] = "hid/keyboard-reader"
        result["transport"] = "usb"
        result["ready"] = True
        result["notes"].append("USB-RFID-Reader kann später als Tastatur-Input eingebunden werden.")
    elif reader_type == "RC522":
        result["driver"] = "mfrc522"
        result["transport"] = "spi"
        result["ready"] = Path("/dev/spidev0.0").exists() or Path("/dev/spidev0.1").exists()
        if not result["ready"]:
            result["notes"].append("SPI-Gerät nicht sichtbar. Für echte Hardware später SPI aktivieren.")
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
    return {
        "configured": len(buttons),
        "backend": "gpio",
        "ready": gpio_backend_available(),
        "notes": ["Button-Mapping ist vorbereitet."] if buttons else ["Noch keine Tasten konfiguriert."],
    }


def detect_leds(setup_data):
    leds = setup_data.get("leds", [])
    pwm_pins = {"GPIO12", "GPIO13", "GPIO18", "GPIO19"}
    invalid_pwm = [led.get("pin", "") for led in leds if int(led.get("brightness", 0)) not in {0, 100} and led.get("pin", "") not in pwm_pins]
    notes = []
    if invalid_pwm:
        notes.append(f"Für Helligkeit fehlen PWM-Pins: {', '.join(invalid_pwm)}")
    if leds:
        notes.append("LED-Konfiguration ist vorbereitet.")
    return {
        "configured": len(leds),
        "backend": "gpio-pwm",
        "ready": gpio_backend_available(),
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
