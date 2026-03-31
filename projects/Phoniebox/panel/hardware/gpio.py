import time
from pathlib import Path


GPIO_TO_BOARD_PIN = {
    "GPIO2": 3,
    "GPIO3": 5,
    "GPIO4": 7,
    "GPIO5": 29,
    "GPIO6": 31,
    "GPIO7": 26,
    "GPIO8": 24,
    "GPIO9": 21,
    "GPIO10": 19,
    "GPIO11": 23,
    "GPIO12": 32,
    "GPIO13": 33,
    "GPIO16": 36,
    "GPIO17": 11,
    "GPIO18": 12,
    "GPIO19": 35,
    "GPIO20": 38,
    "GPIO21": 40,
    "GPIO22": 15,
    "GPIO23": 16,
    "GPIO24": 18,
    "GPIO25": 22,
    "GPIO26": 37,
    "GPIO27": 13,
}

GPIO_PINS = list(GPIO_TO_BOARD_PIN.keys())
SYSFS_GPIO_DIR = Path("/sys/class/gpio")


def gpio_name_to_bcm(gpio_name):
    if not gpio_name or not str(gpio_name).startswith("GPIO"):
        return None
    try:
        return int(str(gpio_name).replace("GPIO", "", 1))
    except ValueError:
        return None


def gpio_display_label(gpio_name):
    board_pin = GPIO_TO_BOARD_PIN.get(gpio_name)
    return f"{gpio_name} / Pin {board_pin}" if board_pin else gpio_name


def sysfs_gpio_available():
    return (SYSFS_GPIO_DIR / "export").exists() and (SYSFS_GPIO_DIR / "unexport").exists()


class SysfsGPIOInput:
    def __init__(self):
        self.root = SYSFS_GPIO_DIR

    def gpio_dir(self, gpio_name):
        bcm = gpio_name_to_bcm(gpio_name)
        if bcm is None:
            return None
        return self.root / f"gpio{bcm}"

    def ensure_input(self, gpio_name):
        if not sysfs_gpio_available():
            return False
        bcm = gpio_name_to_bcm(gpio_name)
        if bcm is None:
            return False
        gpio_dir = self.gpio_dir(gpio_name)
        if gpio_dir is None:
            return False
        if not gpio_dir.exists():
            try:
                (self.root / "export").write_text(str(bcm), encoding="utf-8")
            except OSError:
                pass
            for _ in range(20):
                if gpio_dir.exists():
                    break
                time.sleep(0.01)
        if not gpio_dir.exists():
            return False
        direction_file = gpio_dir / "direction"
        if direction_file.exists():
            try:
                if direction_file.read_text(encoding="utf-8").strip() != "in":
                    direction_file.write_text("in", encoding="utf-8")
            except OSError:
                return False
        return (gpio_dir / "value").exists()

    def read(self, gpio_name):
        gpio_dir = self.gpio_dir(gpio_name)
        if gpio_dir is None:
            return None
        if not self.ensure_input(gpio_name):
            return None
        try:
            raw = (gpio_dir / "value").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if raw not in {"0", "1"}:
            return None
        return int(raw)

    def sample(self, gpio_names):
        sampled = {}
        for gpio_name in gpio_names:
            value = self.read(gpio_name)
            if value is not None:
                sampled[gpio_name] = value
        return sampled


def sample_gpio_levels_sysfs(gpio_names):
    return SysfsGPIOInput().sample([name for name in gpio_names if name])
