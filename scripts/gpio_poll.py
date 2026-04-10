#!/usr/bin/env python3
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from runtime.service import RuntimeService


def main():
    service = RuntimeService()
    service.poll_buttons_forever(interval_seconds=service.button_poll_interval_seconds())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
