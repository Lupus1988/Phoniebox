#!/opt/phoniebox-panel/.venv/bin/python
import json
import os
import sysconfig
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def add_system_site_packages():
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        Path(f"/usr/local/lib/python{version}/dist-packages"),
        Path("/usr/lib/python3/dist-packages"),
        Path(f"/usr/lib/python{version}/dist-packages"),
    ]
    for path in candidates:
        raw = str(path)
        if path.exists() and raw not in sys.path:
            sys.path.append(raw)


add_system_site_packages()

from hardware.rfid import decode_keycode_to_char, discover_usb_keyboard_devices, evdev_available

if evdev_available():
    from evdev import InputDevice, categorize, ecodes
else:
    InputDevice = None
    categorize = None
    ecodes = None

try:
    import lgpio
except ImportError:
    lgpio = None


DATA_DIR = BASE_DIR / "data"
SETUP_FILE = DATA_DIR / "setup.json"
READER_STATUS_FILE = DATA_DIR / "reader_status.json"
LINK_SESSION_FILE = DATA_DIR / "rfid_link_session.json"
PANEL_PORT = int(os.environ.get("PHONIEBOX_PORT", "80"))
RUNTIME_RFID_URL = f"http://127.0.0.1:{PANEL_PORT}/api/runtime/rfid"
RUNTIME_RFID_REMOVE_URL = f"http://127.0.0.1:{PANEL_PORT}/api/runtime/rfid/remove"
VALID_RC522_VERSION_REG_VALUES = {0x91, 0x92}
RC522_PROBE_ORDER = ((0, 25), (1, 25))
RC522_DEFAULT_IRQ_PIN = None
RFID_BOOT_SUPPRESS_SECONDS = 6.0
RFID_UID_CONFIRM_SECONDS = 0.25
SETUP_CACHE_TTL_SECONDS = 1.0
LINK_SESSION_CACHE_TTL_SECONDS = 0.15
RFID_ACTIVE_SLEEP_SECONDS = 0.015
RFID_IDLE_SLEEP_SECONDS = 0.05
RFID_ERROR_SLEEP_SECONDS = 0.12
RFID_READER_MISSING_SLEEP_SECONDS = 0.3


def load_setup():
    if not SETUP_FILE.exists():
        return {}
    try:
        return json.loads(SETUP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def link_session_active():
    if not LINK_SESSION_FILE.exists():
        return False
    try:
        payload = json.loads(LINK_SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool((payload or {}).get("active"))


def load_link_session_state():
    if not LINK_SESSION_FILE.exists():
        return {}
    try:
        payload = json.loads(LINK_SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def cached_loader(loader, ttl_seconds):
    cache = {"value": None, "loaded_at": 0.0, "has_value": False}

    def load(force=False):
        now = time.time()
        if force or (not cache["has_value"]) or (now - float(cache["loaded_at"])) >= float(ttl_seconds):
            cache["value"] = loader()
            cache["loaded_at"] = now
            cache["has_value"] = True
        return cache["value"]

    return load


def loop_sleep(reader, observed_uid="", present_uid="", ignored_uid="", link_session_waiting=False, error=False):
    if error:
        time.sleep(RFID_ERROR_SLEEP_SECONDS)
        return
    if link_session_waiting or observed_uid or present_uid or ignored_uid:
        time.sleep(RFID_ACTIVE_SLEEP_SECONDS)
        return
    if getattr(reader, "presence_reader", False):
        time.sleep(RFID_IDLE_SLEEP_SECONDS)
        return
    time.sleep(RFID_ACTIVE_SLEEP_SECONDS)


def post_json(url, payload=None):
    raw = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        return int(getattr(exc, "code", 500) or 500)
    except (urllib.error.URLError, TimeoutError):
        return None


def post_uid(uid):
    return post_json(RUNTIME_RFID_URL, {"uid": uid})


def post_remove():
    return post_json(RUNTIME_RFID_REMOVE_URL, {})


def save_reader_status(configured_type, ready, message, details=None):
    payload = {
        "configured_type": configured_type,
        "ready": bool(ready),
        "message": str(message or ""),
        "details": list(details or []),
        "updated_at": int(time.time()),
    }
    try:
        READER_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        READER_STATUS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return False
    return True


def ensure_spi_pinmux():
    try:
        result = subprocess.run(
            ["pinctrl", "get", "7-11"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {
            "ok": True,
            "message": f"SPI-Pinmux konnte nicht geprüft werden: {exc}",
            "details": ["`pinctrl` ist nicht verfügbar; nutze bestehenden Kernel-/SPI-Zustand."],
        }
    if result.returncode != 0:
        details = [line.strip() for line in (result.stderr or result.stdout or "").splitlines() if line.strip()]
        return {
            "ok": True,
            "message": "SPI-Pinmux konnte nicht geprüft werden.",
            "details": details or ["Unbekannter pinctrl-Fehler; nutze bestehenden Kernel-/SPI-Zustand."],
        }
    details = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return {
        "ok": True,
        "message": "SPI-Pinmux geprüft.",
        "details": details,
    }


def is_valid_rc522_version(version):
    return isinstance(version, int) and version in VALID_RC522_VERSION_REG_VALUES


class LowLevelRC522Backend:
    VERSION_REG = 0x37
    COMMAND_REG = 0x01
    COMM_I_EN_REG = 0x02
    COMM_IRQ_REG = 0x04
    ERROR_REG = 0x06
    FIFO_DATA_REG = 0x09
    FIFO_LEVEL_REG = 0x0A
    CONTROL_REG = 0x0C
    BIT_FRAMING_REG = 0x0D
    MODE_REG = 0x11
    TX_CONTROL_REG = 0x14
    TX_ASK_REG = 0x15
    T_MODE_REG = 0x2A
    T_PRESCALER_REG = 0x2B
    T_RELOAD_REG_H = 0x2C
    T_RELOAD_REG_L = 0x2D

    PCD_IDLE = 0x00
    PCD_AUTHENT = 0x0E
    PCD_TRANSCEIVE = 0x0C
    PCD_RESETPHASE = 0x0F

    PICC_REQIDL = 0x26
    PICC_ANTICOLL = 0x93

    MI_OK = 0
    MI_NOTAGERR = 1
    MI_ERR = 2

    def __init__(self, spi_bus=0, spi_device=0, rst_pin=25):
        import spidev

        self._spidev = spidev
        self._gpio = None
        self._gpiochip = None
        self.spi_bus = spi_bus
        self.spi_device = spi_device
        self.rst_pin = rst_pin
        self.spi = None
        self._open()

    def _open(self):
        self._open_reset_pin()
        self.spi = self._spidev.SpiDev()
        self.spi.open(self.spi_bus, self.spi_device)
        self.spi.max_speed_hz = 1_000_000
        self.spi.mode = 0
        self.reset()

    def _open_reset_pin(self):
        if lgpio is not None:
            self._gpiochip = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(self._gpiochip, self.rst_pin, 1)
            return

        import RPi.GPIO as GPIO

        self._gpio = GPIO
        self._gpio.setwarnings(False)
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setup(self.rst_pin, self._gpio.OUT)
        self._gpio.output(self.rst_pin, self._gpio.HIGH)

    def _write_reg(self, addr, value):
        self.spi.xfer2([((addr << 1) & 0x7E), value])

    def _read_reg(self, addr):
        return self.spi.xfer2([((addr << 1) & 0x7E) | 0x80, 0])[1]

    def _set_bit_mask(self, addr, mask):
        self._write_reg(addr, self._read_reg(addr) | mask)

    def _clear_bit_mask(self, addr, mask):
        self._write_reg(addr, self._read_reg(addr) & (~mask))

    def reset(self):
        self._write_reg(self.COMMAND_REG, self.PCD_RESETPHASE)
        time.sleep(0.05)
        self._write_reg(self.T_MODE_REG, 0x8D)
        self._write_reg(self.T_PRESCALER_REG, 0x3E)
        self._write_reg(self.T_RELOAD_REG_L, 30)
        self._write_reg(self.T_RELOAD_REG_H, 0)
        self._write_reg(self.TX_ASK_REG, 0x40)
        self._write_reg(self.MODE_REG, 0x3D)
        self._antenna_on()

    def _antenna_on(self):
        if not (self._read_reg(self.TX_CONTROL_REG) & 0x03):
            self._set_bit_mask(self.TX_CONTROL_REG, 0x03)

    def version(self):
        return self._read_reg(self.VERSION_REG)

    def _to_card(self, command, send_data):
        recv_data = []
        recv_bits = 0
        irq_en = 0x00
        wait_irq = 0x00
        status = self.MI_ERR

        if command == self.PCD_AUTHENT:
            irq_en = 0x12
            wait_irq = 0x10
        elif command == self.PCD_TRANSCEIVE:
            irq_en = 0x77
            wait_irq = 0x30

        self._write_reg(self.COMM_I_EN_REG, irq_en | 0x80)
        self._clear_bit_mask(self.COMM_IRQ_REG, 0x80)
        self._set_bit_mask(self.FIFO_LEVEL_REG, 0x80)
        self._write_reg(self.COMMAND_REG, self.PCD_IDLE)

        for value in send_data:
            self._write_reg(self.FIFO_DATA_REG, value)
        self._write_reg(self.COMMAND_REG, command)

        if command == self.PCD_TRANSCEIVE:
            self._set_bit_mask(self.BIT_FRAMING_REG, 0x80)

        attempts = 2000
        while attempts:
            irq_value = self._read_reg(self.COMM_IRQ_REG)
            attempts -= 1
            if (irq_value & 0x01) or (irq_value & wait_irq):
                break

        self._clear_bit_mask(self.BIT_FRAMING_REG, 0x80)

        if attempts and (self._read_reg(self.ERROR_REG) & 0x1B) == 0x00:
            status = self.MI_OK
            if irq_value & irq_en & 0x01:
                status = self.MI_NOTAGERR
            if command == self.PCD_TRANSCEIVE:
                count = self._read_reg(self.FIFO_LEVEL_REG)
                last_bits = self._read_reg(self.CONTROL_REG) & 0x07
                recv_bits = (count - 1) * 8 + last_bits if last_bits else count * 8
                count = min(max(count, 1), 16)
                for _ in range(count):
                    recv_data.append(self._read_reg(self.FIFO_DATA_REG))

        return status, recv_data, recv_bits

    def read_uid(self):
        self._write_reg(self.BIT_FRAMING_REG, 0x07)
        status, _recv_data, recv_bits = self._to_card(self.PCD_TRANSCEIVE, [self.PICC_REQIDL])
        if status != self.MI_OK or recv_bits != 0x10:
            return None

        self._write_reg(self.BIT_FRAMING_REG, 0x00)
        status, recv_data, _recv_bits = self._to_card(self.PCD_TRANSCEIVE, [self.PICC_ANTICOLL, 0x20])
        if status != self.MI_OK or len(recv_data) != 5:
            return None

        checksum = 0
        for index in range(4):
            checksum ^= recv_data[index]
        if checksum != recv_data[4]:
            return None

        return "".join(f"{value:02X}" for value in recv_data[:4])

    def cleanup(self):
        if self.spi is not None:
            try:
                self.spi.close()
            except Exception:
                pass
            self.spi = None
        if self._gpiochip is not None and lgpio is not None:
            try:
                lgpio.gpio_write(self._gpiochip, self.rst_pin, 0)
            except Exception:
                pass
            try:
                lgpio.gpio_free(self._gpiochip, self.rst_pin)
            except Exception:
                pass
            try:
                lgpio.gpiochip_close(self._gpiochip)
            except Exception:
                pass
            self._gpiochip = None
        if self._gpio is not None:
            try:
                self._gpio.cleanup()
            except Exception:
                pass
            self._gpio = None


def probe_rc522_backend():
    try:
        import spidev  # noqa: F401
    except Exception as exc:
        return {
            "ok": False,
            "message": f"RC522-Treiber fehlen: {exc}",
            "details": ["Für RC522 wird `spidev` benötigt."],
            "backend": None,
        }

    probe_results = []
    for spi_device, rst_pin in RC522_PROBE_ORDER:
        backend = None
        try:
            backend = LowLevelRC522Backend(spi_bus=0, spi_device=spi_device, rst_pin=rst_pin)
            version = backend.version()
            probe_results.append((spi_device, rst_pin, version))
            if is_valid_rc522_version(version):
                return {
                    "ok": True,
                    "message": "RC522 bereit.",
                    "details": [f"SPI-Antwort erkannt auf CE{spi_device}/RST{rst_pin}."],
                    "config": {"spi_bus": 0, "spi_device": spi_device, "rst_pin": rst_pin, "irq_pin": RC522_DEFAULT_IRQ_PIN},
                }
        except Exception as exc:
            probe_results.append((spi_device, rst_pin, f"ERR:{exc}"))
        finally:
            if backend is not None:
                backend.cleanup()

    formatted = ", ".join(
        f"CE{spi_device}/RST{rst_pin}={value if isinstance(value, str) else hex(value)}"
        for spi_device, rst_pin, value in probe_results
    )
    return {
        "ok": False,
        "message": "RC522 nicht erkannt.",
        "details": [
            "Der Chip antwortet nicht über SPI.",
            formatted,
        ],
        "config": None,
    }


class PiRc522ReaderBackend:
    def __init__(self, spi_bus=0, spi_device=0, rst_pin=25, irq_pin=RC522_DEFAULT_IRQ_PIN):
        from pirc522 import RFID

        self.spi_bus = spi_bus
        self.spi_device = spi_device
        self.rst_pin = rst_pin
        self.irq_pin = irq_pin
        reader_kwargs = {
            "bus": spi_bus,
            "device": spi_device,
            "speed": 1_000_000,
            "pin_rst": rst_pin,
            "pin_ce": spi_device,
        }
        if irq_pin is not None:
            reader_kwargs["pin_irq"] = irq_pin
        self.reader = RFID(**reader_kwargs)

    def read_uid(self):
        error, _tag_type = self.reader.request()
        if error:
            return None
        error, uid = self.reader.anticoll()
        if error or not uid:
            return None
        return "".join(str(value) for value in uid)

    def cleanup(self):
        method = getattr(self.reader, "cleanup", None)
        if callable(method):
            method()


class BaseReader:
    presence_reader = False
    ready = False
    status_message = "Kein Reader installiert."
    status_details = []

    def poll(self):
        return None

    def cleanup(self):
        return None


class USBKeyboardReader(BaseReader):
    def __init__(self):
        self.devices = []
        self.current_paths = []
        self.buffer = ""
        self.last_refresh = 0.0
        self.ready = True
        self.status_message = "USB-Reader aktiv."
        self.status_details = ["Warte auf HID-Tastatur-Reader."]

    def open_devices(self, paths):
        devices = []
        for path in paths:
            try:
                device = InputDevice(path)
                device.grab()
                devices.append(device)
            except OSError:
                continue
        return devices

    def close_devices(self, devices=None):
        for device in list(devices or self.devices):
            try:
                device.ungrab()
            except OSError:
                pass
            try:
                device.close()
            except OSError:
                pass

    def refresh_devices(self, now):
        if not evdev_available():
            return
        if now - self.last_refresh < 3.0 and self.devices:
            return
        new_paths = discover_usb_keyboard_devices()
        if new_paths != self.current_paths:
            self.close_devices()
            self.devices = self.open_devices(new_paths)
            self.current_paths = new_paths
        self.last_refresh = now

    def poll(self):
        now = time.monotonic()
        self.refresh_devices(now)
        if not self.devices:
            time.sleep(0.2)
            return None

        had_event = False
        for device in list(self.devices):
            try:
                event = device.read_one()
            except OSError:
                self.close_devices([device])
                self.devices = [entry for entry in self.devices if entry is not device]
                continue
            if event is None:
                continue
            had_event = True
            if event.type != ecodes.EV_KEY:
                continue
            key_event = categorize(event)
            if key_event.keystate != key_event.key_down:
                continue
            keycode = key_event.keycode[0] if isinstance(key_event.keycode, list) else key_event.keycode
            if keycode in {"KEY_ENTER", "KEY_KPENTER"}:
                uid = self.buffer.strip()
                self.buffer = ""
                return uid or None
            if keycode == "KEY_BACKSPACE":
                self.buffer = self.buffer[:-1]
                continue
            char = decode_keycode_to_char(keycode)
            if char:
                self.buffer += char

        if not had_event:
            time.sleep(0.03)
        return None

    def cleanup(self):
        self.close_devices()
        self.devices = []
        self.current_paths = []


class RC522Reader(BaseReader):
    presence_reader = True

    def __init__(self):
        self.reader = None
        self.reader_config = None
        self.ready = False
        self.status_message = "RC522 noch nicht initialisiert."
        self.status_details = ["Prüfe SPI, Verdrahtung und Python-Treiber."]
        pinmux = ensure_spi_pinmux()
        if not pinmux["ok"]:
            self.status_message = pinmux["message"]
            self.status_details = pinmux["details"]
            return
        probe = probe_rc522_backend()
        if not probe["ok"]:
            self.reader = None
            self.status_message = probe["message"]
            self.status_details = probe["details"]
            return
        self.reader_config = probe["config"]
        try:
            self.reader = LowLevelRC522Backend(
                spi_bus=self.reader_config.get("spi_bus", 0),
                spi_device=self.reader_config.get("spi_device", 0),
                rst_pin=self.reader_config.get("rst_pin", 25),
            )
        except Exception as exc:
            self.reader = None
            self.status_message = f"RC522-Treiber konnte nicht gestartet werden: {exc}"
            self.status_details = [
                "Der Chip antwortet zwar über SPI, der Reader konnte aber nicht geöffnet werden.",
                *probe.get("details", []),
                "Erwartete Verdrahtung: CE0/GPIO8, RST/GPIO25, IRQ unbenutzt.",
            ]
            return
        self.ready = True
        self.status_message = "RC522 bereit."
        self.status_details = [
            *probe.get("details", []),
            "Erwartete Verdrahtung: CE0/GPIO8, RST/GPIO25, IRQ unbenutzt.",
        ]

    def _read_uid(self):
        if self.reader is None:
            return None
        return self.reader.read_uid()

    def poll(self):
        if self.reader is None:
            time.sleep(0.3)
            return None
        try:
            uid = self._read_uid()
            self.ready = True
            self.status_message = "RC522 bereit."
            self.status_details = [
                "Erwartete Verdrahtung: CE0/GPIO8, RST/GPIO25, IRQ unbenutzt.",
            ]
        except Exception as exc:
            self.ready = False
            self.status_message = f"RC522 Lesefehler: {exc}"
            self.status_details = [
                "Reader wurde erkannt, konnte aber keinen Tag sauber lesen.",
                "Prüfe Verdrahtung, IRQ18, Tag-Abstand und mögliche GPIO-Konflikte.",
            ]
            return None
        return str(uid) if uid else None

    def cleanup(self):
        if self.reader is None:
            return
        for method_name in ["cleanup", "close"]:
            method = getattr(self.reader, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass


class PN532Reader(BaseReader):
    presence_reader = True

    def __init__(self, transport):
        self.transport = transport
        self.pn532 = None
        self.handles = []
        self.ready = False
        self.status_message = "PN532 noch nicht initialisiert."
        self.status_details = [f"Prüfe Transport {transport}."]
        pinmux = {"ok": True, "message": "", "details": []}
        if transport == "spi":
            pinmux = ensure_spi_pinmux()
            if not pinmux["ok"]:
                self.status_message = pinmux["message"]
                self.status_details = pinmux["details"]
                return
        try:
            import board
            import busio
            import digitalio
            from adafruit_pn532.spi import PN532_SPI
        except Exception:
            return

        try:
            if transport == "spi":
                spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
                cs = digitalio.DigitalInOut(board.CE0)
                self.handles.extend([spi, cs])
                self.pn532 = PN532_SPI(spi, cs, debug=False)
            if self.pn532 is not None:
                self.pn532.SAM_configuration()
                self.ready = True
                self.status_message = f"PN532 ({transport}) bereit."
                self.status_details = ["Warte auf RFID-Tag.", *pinmux["details"]]
        except Exception:
            self.cleanup()
            self.pn532 = None
            self.status_message = f"PN532 ({transport}) konnte nicht initialisiert werden."

    def poll(self):
        if self.pn532 is None:
            time.sleep(0.3)
            return None
        try:
            uid = self.pn532.read_passive_target(timeout=0.2)
            self.ready = True
            self.status_message = f"PN532 ({self.transport}) bereit."
        except Exception as exc:
            self.ready = False
            self.status_message = f"PN532 Lesefehler: {exc}"
            return None
        if not uid:
            return None
        if isinstance(uid, (bytes, bytearray)):
            return uid.hex().upper()
        return str(uid)

    def cleanup(self):
        while self.handles:
            handle = self.handles.pop()
            for method_name in ["deinit", "close"]:
                method = getattr(handle, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass


def build_reader(reader_type):
    if reader_type == "USB":
        return USBKeyboardReader()
    if reader_type == "RC522":
        return RC522Reader()
    if reader_type == "PN532_SPI":
        return PN532Reader("spi")
    return BaseReader()


def main():
    reader = None
    reader_type = None
    last_status = None
    present_uid = ""
    present_seen_at = 0.0
    ignored_uid = ""
    ignored_seen_at = 0.0
    observed_uid = ""
    observed_since = 0.0
    observed_seen_at = 0.0
    last_link_uid = ""
    last_link_uid_at = 0.0
    startup_deadline = time.monotonic() + RFID_BOOT_SUPPRESS_SECONDS
    last_link_session_marker = None
    load_setup_cached = cached_loader(load_setup, SETUP_CACHE_TTL_SECONDS)
    load_link_session_cached = cached_loader(load_link_session_state, LINK_SESSION_CACHE_TTL_SECONDS)

    try:
        while True:
            setup = load_setup_cached()
            configured_type = (((setup.get("reader") or {}).get("type")) or "NONE").strip()
            if configured_type != reader_type:
                if reader is not None:
                    reader.cleanup()
                reader = build_reader(configured_type)
                reader_type = configured_type
                last_status = None
                present_uid = ""
                present_seen_at = 0.0
                ignored_uid = ""
                ignored_seen_at = 0.0
                observed_uid = ""
                observed_since = 0.0
                observed_seen_at = 0.0
                last_link_uid = ""
                last_link_uid_at = 0.0
                startup_deadline = time.monotonic() + RFID_BOOT_SUPPRESS_SECONDS
                setup = load_setup_cached(force=True)

            if reader is None:
                time.sleep(RFID_READER_MISSING_SLEEP_SECONDS)
                continue

            current_status = (
                reader_type,
                bool(getattr(reader, "ready", False)),
                str(getattr(reader, "status_message", "")),
                tuple(getattr(reader, "status_details", []) or []),
            )
            if current_status != last_status:
                save_reader_status(
                    reader_type,
                    getattr(reader, "ready", False),
                    getattr(reader, "status_message", ""),
                    getattr(reader, "status_details", []),
                )
                last_status = current_status

            uid = reader.poll()
            now = time.monotonic()
            force_link_session_refresh = bool(observed_uid or present_uid or ignored_uid)
            link_session = load_link_session_cached(force=force_link_session_refresh)
            current_link_session_active = bool(link_session.get("active"))
            current_link_session_marker = (
                current_link_session_active,
                str(link_session.get("album_id", "")),
                str(link_session.get("status", "")),
                float(link_session.get("started_at", 0.0) or 0.0),
            )
            link_session_waiting_for_uid = (
                current_link_session_active
                and str(link_session.get("status", "")) == "waiting_for_uid"
            )
            should_reset_for_link_session = (
                link_session_waiting_for_uid
                and not str(link_session.get("last_uid", "")).strip()
                and current_link_session_marker != last_link_session_marker
            )
            link_session_ended = bool(last_link_session_marker and last_link_session_marker[0] and not current_link_session_active)
            if should_reset_for_link_session or link_session_ended:
                present_uid = ""
                present_seen_at = 0.0
                ignored_uid = ""
                ignored_seen_at = 0.0
                observed_uid = ""
                observed_since = 0.0
                observed_seen_at = 0.0
                last_link_uid = ""
                last_link_uid_at = 0.0
            last_link_session_marker = current_link_session_marker

            polled_status = (
                reader_type,
                bool(getattr(reader, "ready", False)),
                str(getattr(reader, "status_message", "")),
                tuple(getattr(reader, "status_details", []) or []),
            )
            if polled_status != last_status:
                save_reader_status(
                    reader_type,
                    getattr(reader, "ready", False),
                    getattr(reader, "status_message", ""),
                    getattr(reader, "status_details", []),
                )
                last_status = polled_status

            if uid:
                if link_session_waiting_for_uid:
                    if uid == last_link_uid and (now - last_link_uid_at) < 1.0:
                        loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid, link_session_waiting=True)
                        continue
                    status_code = post_uid(uid)
                    if status_code is not None and status_code < 500:
                        last_link_uid = uid
                        last_link_uid_at = now
                        load_link_session_cached(force=True)
                    else:
                        loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid, link_session_waiting=True, error=True)
                    continue

                if uid != observed_uid:
                    observed_uid = uid
                    observed_since = now
                observed_seen_at = now

                if uid == present_uid:
                    present_seen_at = now
                    loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid)
                    continue
                if uid == ignored_uid:
                    ignored_seen_at = now
                    loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid)
                    continue
                if now < startup_deadline or (now - observed_since) < RFID_UID_CONFIRM_SECONDS:
                    loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid)
                    continue

                status_code = post_uid(uid)
                if status_code is None or status_code >= 500:
                    loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid, error=True)
                    continue
                observed_uid = ""
                observed_since = 0.0
                observed_seen_at = 0.0
                if status_code < 300:
                    present_uid = uid
                    present_seen_at = now
                    ignored_uid = ""
                    ignored_seen_at = 0.0
                    load_link_session_cached(force=True)
                elif 400 <= status_code < 500:
                    ignored_uid = uid
                    ignored_seen_at = now
                continue

            if (
                getattr(reader, "presence_reader", False)
                and observed_uid
                and (now - observed_seen_at) < RFID_UID_CONFIRM_SECONDS
            ):
                loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid)
                continue
            observed_uid = ""
            observed_since = 0.0
            observed_seen_at = 0.0
            if getattr(reader, "presence_reader", False) and present_uid and (now - present_seen_at) >= 0.8:
                status_code = post_remove()
                if status_code is not None and status_code < 500:
                    present_uid = ""
                    present_seen_at = 0.0
                    load_link_session_cached(force=True)
                else:
                    loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid, error=True)
                continue
            if getattr(reader, "presence_reader", False) and ignored_uid and (now - ignored_seen_at) >= 0.8:
                ignored_uid = ""
                ignored_seen_at = 0.0
                loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid)
                continue
            loop_sleep(reader, observed_uid=observed_uid, present_uid=present_uid, ignored_uid=ignored_uid)
    finally:
        if reader is not None:
            reader.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
