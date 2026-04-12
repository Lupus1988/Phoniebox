#!/usr/bin/env python3
import argparse
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from runtime.service import RuntimeService


def run_once():
    service = RuntimeService()
    service.tick()
    return 0


def run_forever(interval_seconds=1.0):
    service = RuntimeService()
    interval = max(0.2, float(interval_seconds or 1.0))
    while True:
        started_at = time.monotonic()
        try:
            service.tick()
        except Exception:
            time.sleep(interval)
            continue
        elapsed = time.monotonic() - started_at
        time.sleep(max(0.05, interval - elapsed))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Phoniebox Runtime Tick")
    parser.add_argument("--daemon", action="store_true", help="Tick dauerhaft im Hintergrund ausführen")
    parser.add_argument("--interval", type=float, default=1.0, help="Tick-Intervall in Sekunden für --daemon")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.daemon:
        run_forever(args.interval)
        return 0
    return run_once()


if __name__ == "__main__":
    raise SystemExit(main())
