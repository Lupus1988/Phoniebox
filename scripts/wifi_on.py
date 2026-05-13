#!/usr/bin/env python3
import json
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SETUP_FILE = BASE_DIR / "data" / "setup.json"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from system.networking import enable_wifi_with_recovery


def main():
    try:
        payload = json.loads(SETUP_FILE.read_text(encoding="utf-8")) if SETUP_FILE.exists() else {}
    except (json.JSONDecodeError, OSError, ValueError):
        payload = {}
    result = enable_wifi_with_recovery((payload.get("wifi") or {}))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
