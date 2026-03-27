#!/usr/bin/env python3
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SETUP_FILE = BASE_DIR / "data" / "setup.json"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from system.networking import fallback_hotspot_cycle


def main():
    if not SETUP_FILE.exists():
        print("setup.json fehlt")
        return 1

    config = json.loads(SETUP_FILE.read_text(encoding="utf-8"))
    result = fallback_hotspot_cycle(config.get("wifi", {}))
    print(result.get("summary", "kein Status"))
    for detail in result.get("details", []):
        print(detail)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
