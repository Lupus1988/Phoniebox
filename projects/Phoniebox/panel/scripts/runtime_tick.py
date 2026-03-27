#!/usr/bin/env python3
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from runtime.service import RuntimeService


def main():
    service = RuntimeService()
    state = service.tick()
    print(state["runtime"]["last_event"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
