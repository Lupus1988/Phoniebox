#!/usr/bin/env python3

import os
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.library_service import (
    AUDIO_PROCESSING_QUEUE_DIR,
    audio_processing_status_path,
    AUDIO_PROCESSING_WORKER_PID_FILE,
    process_volume_adjustment,
    process_uploaded_audio_files,
    save_audio_processing_status,
    save_audio_processing_result,
)
from utils import load_json


def _claim_worker():
    AUDIO_PROCESSING_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(AUDIO_PROCESSING_WORKER_PID_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            existing_pid = int(AUDIO_PROCESSING_WORKER_PID_FILE.read_text(encoding="utf-8").strip())
            os.kill(existing_pid, 0)
            return False
        except (OSError, ValueError):
            AUDIO_PROCESSING_WORKER_PID_FILE.unlink(missing_ok=True)
            return _claim_worker()
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return True


def _release_worker():
    AUDIO_PROCESSING_WORKER_PID_FILE.unlink(missing_ok=True)


def _process_manifest(manifest_path):
    job = load_json(manifest_path, {"paths": []})
    paths = [Path(item) for item in job.get("paths", []) if str(item).strip()]
    operation = str(job.get("operation", "normalize_upload") or "normalize_upload").strip()
    gain_db = float(job.get("gain_db", 0.0) or 0.0)
    file_states = {
        str(path): {
            "path": str(path),
            "name": path.name,
            "state": "queued",
            "progress_ratio": 0.0,
            "detail": "Wartet",
        }
        for path in paths
    }

    def persist_status(state="running", issue=""):
        statuses = list(file_states.values())
        completed = sum(1 for item in statuses if item.get("state") in {"normalized", "unchanged", "failed", "skipped"})
        total = len(statuses)
        progress_ratio = 1.0 if total == 0 else completed / total
        if state == "running" and total:
            partial = max((float(item.get("progress_ratio", 0) or 0.0) for item in statuses), default=0.0)
            progress_ratio = min(0.99, progress_ratio + (partial / total))
        save_audio_processing_status(
            manifest_path.name,
            {
                "job": manifest_path.name,
                "created_at": int(job.get("created_at", 0) or 0),
                "state": state,
                "total_files": total,
                "completed_files": completed,
                "progress_ratio": progress_ratio,
                "issue": str(issue or ""),
                "files": statuses,
            },
        )

    def update_path(path, state, progress_ratio, detail):
        key = str(path)
        if key not in file_states:
            file_states[key] = {
                "path": key,
                "name": Path(path).name,
            }
        file_states[key].update(
            {
                "state": state,
                "progress_ratio": float(progress_ratio),
                "detail": str(detail or ""),
            }
        )
        persist_status("running")

    persist_status("running")
    try:
        if operation == "volume_adjust":
            report = process_volume_adjustment(paths, gain_db, progress_callback=update_path)
        else:
            report = process_uploaded_audio_files(paths, progress_callback=update_path)
        persist_status("completed", issue=report.get("issue", ""))
        save_audio_processing_result(
            manifest_path.name,
            {
                "job": manifest_path.name,
                "created_at": job.get("created_at", 0),
                "finished_at": int(time.time()),
                "paths": [str(path) for path in paths],
                "report": report,
            },
        )
    except Exception as exc:
        persist_status("failed", issue=str(exc))
        save_audio_processing_result(
            manifest_path.name,
            {
                "job": manifest_path.name,
                "created_at": job.get("created_at", 0),
                "finished_at": int(time.time()),
                "paths": [str(path) for path in paths],
                "report": {
                    "tool_available": True,
                    "scheduled": 0,
                    "checked": 0,
                    "normalized": 0,
                    "unchanged": 0,
                    "failed": len(paths),
                    "skipped": 0,
                    "issue": f"Audio-Normalisierung im Hintergrund fehlgeschlagen: {exc}",
                },
            },
        )
        raise
    finally:
        manifest_path.unlink(missing_ok=True)
        audio_processing_status_path(manifest_path.name).unlink(missing_ok=True)


def _queued_manifests():
    return sorted(path for path in AUDIO_PROCESSING_QUEUE_DIR.glob("job-*.json") if path.is_file())


def main(_argv):
    if os.name == "posix":
        try:
            os.nice(15)
        except OSError:
            pass
    if not _claim_worker():
        return 0
    try:
        while True:
            manifests = _queued_manifests()
            if not manifests:
                break
            for manifest_path in manifests:
                _process_manifest(manifest_path.resolve())
    finally:
        _release_worker()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
