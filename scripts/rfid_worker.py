#!/opt/phoniebox-panel/.venv/bin/python
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from hardware.rfid import decode_keycode_to_char, discover_usb_keyboard_devices, evdev_available

if evdev_available():
    from evdev import InputDevice, categorize, ecodes
else:
    InputDevice = None
    categorize = None
    ecodes = None


DATA_DIR = BASE_DIR / "data"
SETUP_FILE = DATA_DIR / "setup.json"
READER_STATUS_FILE = DATA_DIR / "reader_status.json"
RUNTIME_RFID_URL = "http://127.0.0.1:5080/api/runtime/rfid"
RUNTIME_RFID_REMOVE_URL = "http://127.0.0.1:5080/api/runtime/rfid/remove"
VALID_RC522_VERSION_REG_VALUES = {0x91, 0x92}


def load_setup():
    if not SETUP_FILE.exists():
        return {}
    try:
        return json.loads(SETUP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def post_json(url, payload=None):
    raw = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3):
            return True
    except (urllib.error.URLError, TimeoutError):
        return False


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
            ["pinctrl", "-e", "set", "7-11", "a0", "pn"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {
            "ok": False,
            "message": f"SPI-Pinmux konnte nicht gesetzt werden: {exc}",
            "details": ["`pinctrl` ist nicht verfügbar."],
        }
    if result.returncode != 0:
        details = [line.strip() for line in (result.stderr or result.stdout or "").splitlines() if line.strip()]
        return {
            "ok": False,
            "message": "SPI-Pinmux konnte nicht gesetzt werden.",
            "details": details or ["Unbekannter pinctrl-Fehler."],
        }
    details = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return {
        "ok": True,
        "message": "SPI-Pinmux auf SPI0 gesetzt.",
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
        import RPi.GPIO as GPIO

        self._spidev = spidev
        self._gpio = GPIO
        self.spi_bus = spi_bus
        self.spi_device = spi_device
        self.rst_pin = rst_pin
        self.spi = None
        self._open()

    def _open(self):
        self._gpio.setwarnings(False)
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setup(self.rst_pin, self._gpio.OUT)
        self._gpio.output(self.rst_pin, self._gpio.HIGH)
        self.spi = self._spidev.SpiDev()
        self.spi.open(self.spi_bus, self.spi_device)
        self.spi.max_speed_hz = 1_000_000
        self.spi.mode = 0
        self.reset()

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
        try:
            self._gpio.cleanup()
        except Exception:
            pass


def probe_rc522_backend():
    try:
        import spidev  # noqa: F401
        import RPi.GPIO  # noqa: F401
    except Exception as exc:
        return {
            "ok": False,
            "message": f"RC522-Treiber fehlen: {exc}",
            "details": ["Für RC522 werden `spidev` und `RPi.GPIO` benötigt."],
            "backend": None,
        }

    probe_results = []
    for spi_device, rst_pin in ((0, 25), (0, 22), (1, 25), (1, 22)):
        backend = None
        try:
            backend = LowLevelRC522Backend(spi_bus=0, spi_device=spi_device, rst_pin=rst_pin)
            version = backend.version()
            probe_results.append((spi_device, rst_pin, version))
            if is_valid_rc522_version(version):
                return {
                    "ok": True,
                    "message": "RC522 bereit.",
                    "details": [],
                    "backend": backend,
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
        "backend": None,
    }


class BaseReader:
    presence_reader = False
    ready = False
    status_message = "Kein Reader initialisiert."
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
        self.ready = False
        self.status_message = "RC522 noch nicht initialisiert."
        self.status_details = ["Prüfe SPI und Python-Treiber."]
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
        self.reader = probe["backend"]
        self.ready = True
        self.status_message = "RC522 bereit."
        self.status_details = []

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
            self.status_details = []
        except Exception as exc:
            self.ready = False
            self.status_message = f"RC522 Lesefehler: {exc}"
            self.status_details = [
                "Reader wurde erkannt, konnte aber keinen Tag sauber lesen.",
                "Prüfe Verdrahtung und Tag-Abstand.",
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
            from adafruit_pn532.i2c import PN532_I2C
            from adafruit_pn532.spi import PN532_SPI
            from adafruit_pn532.uart import PN532_UART
        except Exception:
            return

        try:
            if transport == "i2c":
                i2c = busio.I2C(board.SCL, board.SDA)
                self.handles.append(i2c)
                self.pn532 = PN532_I2C(i2c, debug=False)
            elif transport == "spi":
                spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
                cs = digitalio.DigitalInOut(board.CE0)
                self.handles.extend([spi, cs])
                self.pn532 = PN532_SPI(spi, cs, debug=False)
            elif transport == "uart":
                uart = busio.UART(board.TX, board.RX, baudrate=115200, timeout=0.1)
                self.handles.append(uart)
                self.pn532 = PN532_UART(uart, debug=False)
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
    if reader_type == "PN532_I2C":
        return PN532Reader("i2c")
    if reader_type == "PN532_SPI":
        return PN532Reader("spi")
    if reader_type == "PN532_UART":
        return PN532Reader("uart")
    return BaseReader()


def main():
    reader = None
    reader_type = None
    last_status = None
    active_uid = ""
    active_seen_at = 0.0
    last_uid = ""
    last_uid_at = 0.0

    try:
        while True:
            setup = load_setup()
            configured_type = (((setup.get("reader") or {}).get("type")) or "USB").strip()
            if configured_type != reader_type:
                if reader is not None:
                    reader.cleanup()
                reader = build_reader(configured_type)
                reader_type = configured_type
                last_status = None
                active_uid = ""
                active_seen_at = 0.0

            if reader is None:
                time.sleep(0.5)
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
                if uid == active_uid and getattr(reader, "presence_reader", False):
                    active_seen_at = now
                    continue
                if uid == last_uid and (now - last_uid_at) < 1.5:
                    active_uid = uid if getattr(reader, "presence_reader", False) else active_uid
                    active_seen_at = now
                    continue
                if post_uid(uid):
                    last_uid = uid
                    last_uid_at = now
                    if getattr(reader, "presence_reader", False):
                        active_uid = uid
                        active_seen_at = now
                continue

            if getattr(reader, "presence_reader", False) and active_uid and (now - active_seen_at) >= 0.8:
                if post_remove():
                    active_uid = ""
                    active_seen_at = 0.0
                else:
                    time.sleep(0.2)
    finally:
        if reader is not None:
            reader.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
