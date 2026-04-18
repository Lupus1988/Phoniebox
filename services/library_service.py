import secrets
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from werkzeug.utils import secure_filename

from runtime.audio import track_duration_seconds, track_title_from_entry
from utils import load_json, safe_relative_path, save_json, slugify_name


BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_DIR / "media"
ALBUMS_DIR = MEDIA_DIR / "albums"
LIBRARY_FILE = BASE_DIR / "data" / "library.json"
LINK_SESSION_FILE = BASE_DIR / "data" / "rfid_link_session.json"
AUDIO_PROCESSING_QUEUE_DIR = BASE_DIR / "data" / "audio-processing"
AUDIO_PROCESSING_STATUS_DIR = BASE_DIR / "data" / "audio-processing-status"
AUDIO_PROCESSING_RESULTS_DIR = BASE_DIR / "data" / "audio-processing-results"
AUDIO_PROCESSING_WORKER_PID_FILE = AUDIO_PROCESSING_QUEUE_DIR / "worker.pid"
AUDIO_NORMALIZE_TARGET_I = -16.0
AUDIO_NORMALIZE_TARGET_TP = -1.5
AUDIO_NORMALIZE_TARGET_LRA = 11.0
AUDIO_NORMALIZE_TOLERANCE_LU = 1.0
AUDIO_NORMALIZE_TOLERANCE_TP = 0.2


def default_library():
    return {"albums": []}


def default_link_session():
    return {
        "active": False,
        "album_id": "",
        "album_name": "",
        "started_at": 0.0,
        "status": "idle",
        "message": "",
        "last_uid": "",
    }


def load_library():
    return load_json(LIBRARY_FILE, default_library())


def save_library(data):
    save_json(LIBRARY_FILE, data)


def load_link_session():
    return load_json(LINK_SESSION_FILE, default_link_session())


def save_link_session(data):
    save_json(LINK_SESSION_FILE, data)


def is_audio_file(path):
    return path.suffix.lower() in {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".opus", ".oga", ".aif", ".aiff", ".m4b", ".mp4"}


def is_cover_file(path):
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def default_audio_processing_report():
    return {
        "tool_available": False,
        "scheduled": 0,
        "checked": 0,
        "normalized": 0,
        "unchanged": 0,
        "failed": 0,
        "skipped": 0,
        "issue": "",
        "jobs": [],
    }


def merge_audio_processing_reports(*reports):
    merged = default_audio_processing_report()
    for report in reports:
        if not isinstance(report, dict):
            continue
        merged["tool_available"] = merged["tool_available"] or bool(report.get("tool_available", False))
        for key in ("scheduled", "checked", "normalized", "unchanged", "failed", "skipped"):
            merged[key] += int(report.get(key, 0) or 0)
        if not merged.get("issue") and str(report.get("issue", "") or "").strip():
            merged["issue"] = str(report.get("issue", "")).strip()
        for job in report.get("jobs", []) or []:
            if isinstance(job, dict):
                merged["jobs"].append(dict(job))
    return merged


def describe_audio_processing(report):
    if not isinstance(report, dict):
        return ""
    checked = int(report.get("checked", 0) or 0)
    normalized = int(report.get("normalized", 0) or 0)
    unchanged = int(report.get("unchanged", 0) or 0)
    failed = int(report.get("failed", 0) or 0)
    skipped = int(report.get("skipped", 0) or 0)
    scheduled = int(report.get("scheduled", 0) or 0)
    issue = str(report.get("issue", "") or "").strip()
    if not any((scheduled, checked, normalized, unchanged, failed, skipped)) and not issue:
        return ""
    if scheduled:
        return f" Audio-Normalisierung läuft im Hintergrund für {scheduled} Titel."
    if issue:
        return f" {issue}"
    if skipped and not bool(report.get("tool_available", False)):
        return " Audio-Prüfung übersprungen, weil ffmpeg/ffprobe fehlen."
    parts = [f"Audio geprüft: {checked}"]
    if normalized:
        parts.append(f"{normalized} normalisiert")
    if unchanged:
        parts.append(f"{unchanged} unverändert")
    if failed:
        parts.append(f"{failed} mit Prüffehler")
    return " " + ", ".join(parts) + "."


def audio_processing_tools_available():
    return bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))


def _run_media_command(command):
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _ffmpeg_json_object(text):
    decoder = json.JSONDecoder()
    for index in range(len(text) - 1, -1, -1):
        if text[index] != "{":
            continue
        snippet = text[index:].strip()
        try:
            payload, end_index = decoder.raw_decode(snippet)
        except json.JSONDecodeError:
            continue
        if snippet[end_index:].strip():
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _probe_audio_file(path):
    result = _run_media_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams") or []
    if not streams:
        return None
    return payload


def _analyze_audio_loudness(path):
    result = _run_media_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-threads",
            "1",
            "-i",
            str(path),
            "-af",
            f"loudnorm=I={AUDIO_NORMALIZE_TARGET_I}:TP={AUDIO_NORMALIZE_TARGET_TP}:LRA={AUDIO_NORMALIZE_TARGET_LRA}:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    if result.returncode != 0:
        return {}
    return _ffmpeg_json_object(result.stderr or "")


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalization_needed(metrics):
    input_i = _float_or_none(metrics.get("input_i"))
    input_tp = _float_or_none(metrics.get("input_tp"))
    if input_i is None:
        return True
    if abs(input_i - AUDIO_NORMALIZE_TARGET_I) > AUDIO_NORMALIZE_TOLERANCE_LU:
        return True
    if input_tp is not None and input_tp > (AUDIO_NORMALIZE_TARGET_TP + AUDIO_NORMALIZE_TOLERANCE_TP):
        return True
    return False


def _normalization_filter(metrics):
    base = f"loudnorm=I={AUDIO_NORMALIZE_TARGET_I}:TP={AUDIO_NORMALIZE_TARGET_TP}:LRA={AUDIO_NORMALIZE_TARGET_LRA}"
    measured = {
        "measured_I": _float_or_none(metrics.get("input_i")),
        "measured_LRA": _float_or_none(metrics.get("input_lra")),
        "measured_TP": _float_or_none(metrics.get("input_tp")),
        "measured_thresh": _float_or_none(metrics.get("input_thresh")),
        "offset": _float_or_none(metrics.get("target_offset")),
    }
    if not all(value is not None for value in measured.values()):
        return base
    return (
        base
        + f":measured_I={measured['measured_I']}"
        + f":measured_LRA={measured['measured_LRA']}"
        + f":measured_TP={measured['measured_TP']}"
        + f":measured_thresh={measured['measured_thresh']}"
        + f":offset={measured['offset']}"
        + ":linear=true"
    )


def _normalization_encoder_args(path):
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return ["-codec:a", "libmp3lame", "-q:a", "2"]
    if suffix in {".m4a", ".aac", ".mp4", ".m4b"}:
        return ["-codec:a", "aac", "-b:a", "192k"]
    if suffix == ".flac":
        return ["-codec:a", "flac"]
    if suffix in {".wav"}:
        return ["-codec:a", "pcm_s16le"]
    if suffix in {".aif", ".aiff"}:
        return ["-codec:a", "pcm_s16be"]
    if suffix in {".opus"}:
        return ["-codec:a", "libopus", "-b:a", "128k"]
    if suffix in {".ogg", ".oga"}:
        return ["-codec:a", "libvorbis", "-q:a", "5"]
    return []


def _normalize_audio_file(path, metrics):
    temp_path = path.with_name(f"{path.stem}.normalized-{secrets.token_hex(4)}{path.suffix}")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-threads",
        "1",
        "-i",
        str(path),
        "-map_metadata",
        "0",
        "-af",
        _normalization_filter(metrics),
        *_normalization_encoder_args(path),
        str(temp_path),
    ]
    result = _run_media_command(command)
    if result.returncode != 0 or not temp_path.exists():
        temp_path.unlink(missing_ok=True)
        return False
    temp_path.replace(path)
    return True


def _apply_gain_to_audio_file(path, gain_db):
    temp_path = path.with_name(f"{path.stem}.gain-{secrets.token_hex(4)}{path.suffix}")
    gain_db = round(float(gain_db), 1)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-threads",
        "1",
        "-i",
        str(path),
        "-map_metadata",
        "0",
        "-af",
        f"volume={gain_db}dB",
        *_normalization_encoder_args(path),
        str(temp_path),
    ]
    result = _run_media_command(command)
    if result.returncode != 0 or not temp_path.exists():
        temp_path.unlink(missing_ok=True)
        return False
    temp_path.replace(path)
    return True


def process_uploaded_audio_files(paths, progress_callback=None):
    report = default_audio_processing_report()
    files = [Path(path) for path in paths if Path(path).exists()]
    if not files:
        return report
    if not audio_processing_tools_available():
        report["skipped"] = len(files)
        return report
    report["tool_available"] = True
    for path in files:
        if callable(progress_callback):
            progress_callback(path, "probing", 0.15, "Datei wird geprüft")
        probe = _probe_audio_file(path)
        if probe is None:
            if callable(progress_callback):
                progress_callback(path, "failed", 1.0, "Audio-Prüfung fehlgeschlagen")
            report["failed"] += 1
            continue
        report["checked"] += 1
        if callable(progress_callback):
            progress_callback(path, "analyzing", 0.45, "Lautheit wird analysiert")
        metrics = _analyze_audio_loudness(path)
        if not _normalization_needed(metrics):
            if callable(progress_callback):
                progress_callback(path, "unchanged", 1.0, "Bereits passend")
            report["unchanged"] += 1
            continue
        if callable(progress_callback):
            progress_callback(path, "normalizing", 0.78, "Wird normalisiert")
        if _normalize_audio_file(path, metrics):
            if callable(progress_callback):
                progress_callback(path, "normalized", 1.0, "Normalisiert")
            report["normalized"] += 1
            continue
        if callable(progress_callback):
            progress_callback(path, "failed", 1.0, "Normalisierung fehlgeschlagen")
        report["failed"] += 1
    return report


def process_volume_adjustment(paths, gain_db, progress_callback=None):
    report = default_audio_processing_report()
    files = [Path(path) for path in paths if Path(path).exists()]
    if not files:
        return report
    if not audio_processing_tools_available():
        report["skipped"] = len(files)
        report["issue"] = "Lautstärke-Anpassung übersprungen, weil ffmpeg fehlt."
        return report
    report["tool_available"] = True
    for path in files:
        if callable(progress_callback):
            progress_callback(path, "processing", 0.25, "Lautstärke wird angepasst")
        if abs(float(gain_db)) < 0.05:
            if callable(progress_callback):
                progress_callback(path, "unchanged", 1.0, "Keine Änderung")
            report["unchanged"] += 1
            continue
        if _apply_gain_to_audio_file(path, gain_db):
            if callable(progress_callback):
                progress_callback(path, "normalized", 1.0, f"{gain_db:+.1f} dB angewendet")
            report["normalized"] += 1
            continue
        if callable(progress_callback):
            progress_callback(path, "failed", 1.0, "Lautstärke-Anpassung fehlgeschlagen")
        report["failed"] += 1
    return report


def _audio_processing_script_path():
    return BASE_DIR / "scripts" / "audio_postprocess.py"


def audio_processing_status_path(job_name):
    return AUDIO_PROCESSING_STATUS_DIR / f"{Path(job_name).stem}.status.json"


def audio_processing_worker_running():
    try:
        pid = int(AUDIO_PROCESSING_WORKER_PID_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        AUDIO_PROCESSING_WORKER_PID_FILE.unlink(missing_ok=True)
        return False


def _spawn_audio_processing_worker():
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "start_new_session": True,
        "cwd": str(BASE_DIR),
    }
    if os.name == "posix":
        kwargs["preexec_fn"] = lambda: os.nice(15)
    return subprocess.Popen([sys.executable, str(_audio_processing_script_path())], **kwargs)


def audio_processing_result_path(job_name):
    return AUDIO_PROCESSING_RESULTS_DIR / f"{Path(job_name).stem}.result.json"


def _audio_file_status_entry(path, state="queued", progress_ratio=0.0, detail="Wartet"):
    source = Path(path)
    return {
        "path": str(source),
        "name": source.name,
        "state": state,
        "progress_ratio": float(progress_ratio),
        "detail": str(detail or ""),
    }


def _audio_job_payload(job_name, paths, state="queued", file_statuses=None, report=None, issue=""):
    statuses = list(file_statuses or [_audio_file_status_entry(path) for path in paths])
    completed = sum(1 for item in statuses if item.get("state") in {"normalized", "unchanged", "failed", "skipped"})
    total = len(statuses)
    return {
        "job": job_name,
        "state": state,
        "created_at": int(time.time()),
        "total_files": total,
        "completed_files": completed,
        "progress_ratio": (completed / total) if total else 1.0,
        "issue": str(issue or ""),
        "files": statuses,
        "report": report or default_audio_processing_report(),
    }


def save_audio_processing_status(job_name, payload):
    AUDIO_PROCESSING_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    save_json(audio_processing_status_path(job_name), payload)


def load_audio_processing_snapshot(job_name):
    status = load_json(audio_processing_status_path(job_name), {})
    if status:
        return status
    result = load_json(audio_processing_result_path(job_name), {})
    if not result:
        return {}
    report = result.get("report", {}) if isinstance(result, dict) else {}
    statuses = []
    for raw_path in result.get("paths", []) or []:
        outcome = "normalized" if int(report.get("normalized", 0) or 0) > 0 else "unchanged"
        if int(report.get("failed", 0) or 0) > 0:
            outcome = "failed"
        detail = {
            "normalized": "Normalisiert",
            "unchanged": "Bereits passend",
            "failed": "Fehlgeschlagen",
        }.get(outcome, "Fertig")
        statuses.append(_audio_file_status_entry(raw_path, state=outcome, progress_ratio=1.0, detail=detail))
    if not statuses:
        return {}
    snapshot = _audio_job_payload(
        result.get("job", job_name),
        result.get("paths", []),
        state="completed",
        file_statuses=statuses,
        report=report,
        issue=report.get("issue", ""),
    )
    snapshot["created_at"] = int(result.get("created_at", snapshot["created_at"]))
    snapshot["finished_at"] = int(result.get("finished_at", snapshot["created_at"]))
    snapshot["progress_ratio"] = 1.0
    snapshot["completed_files"] = snapshot["total_files"]
    return snapshot


def audio_processing_status_summary(job_names):
    jobs = []
    for job_name in job_names or []:
        snapshot = load_audio_processing_snapshot(job_name)
        if snapshot:
            jobs.append(snapshot)
    total_files = sum(int(job.get("total_files", 0) or 0) for job in jobs)
    completed_files = sum(int(job.get("completed_files", 0) or 0) for job in jobs)
    active = any(job.get("state") not in {"completed", "failed"} for job in jobs)
    failed = any(
        file_status.get("state") == "failed"
        for job in jobs
        for file_status in (job.get("files", []) or [])
        if isinstance(file_status, dict)
    )
    progress_ratio = (completed_files / total_files) if total_files else 1.0
    return {
        "ok": True,
        "job_count": len(jobs),
        "total_files": total_files,
        "completed_files": completed_files,
        "progress_ratio": progress_ratio,
        "active": active,
        "complete": bool(jobs) and not active,
        "failed": failed,
        "jobs": jobs,
    }


def save_audio_processing_result(job_name, payload):
    AUDIO_PROCESSING_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    save_json(audio_processing_result_path(job_name), payload)


def schedule_uploaded_audio_processing(paths):
    report = default_audio_processing_report()
    files = [str(Path(path).resolve()) for path in paths if Path(path).exists()]
    if not files:
        return report
    if not audio_processing_tools_available():
        report["skipped"] = len(files)
        report["issue"] = "Audio-Prüfung übersprungen, weil ffmpeg/ffprobe fehlen."
        return report
    AUDIO_PROCESSING_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = AUDIO_PROCESSING_QUEUE_DIR / f"job-{int(time.time())}-{secrets.token_hex(4)}.json"
    manifest_payload = {
        "created_at": int(time.time()),
        "paths": files,
    }
    save_json(manifest_path, manifest_payload)
    save_audio_processing_status(
        manifest_path.name,
        _audio_job_payload(manifest_path.name, files, state="queued"),
    )
    if audio_processing_worker_running():
        report["tool_available"] = True
        report["scheduled"] = len(files)
        report["jobs"] = [{"job": manifest_path.name, "paths": files}]
        return report
    try:
        _spawn_audio_processing_worker()
    except OSError:
        manifest_path.unlink(missing_ok=True)
        audio_processing_status_path(manifest_path.name).unlink(missing_ok=True)
        report["tool_available"] = True
        report["failed"] = len(files)
        report["issue"] = "Audio-Normalisierung konnte nicht im Hintergrund gestartet werden."
        return report
    report["tool_available"] = True
    report["scheduled"] = len(files)
    report["jobs"] = [{"job": manifest_path.name, "paths": files}]
    return report


def schedule_volume_adjustment(path, gain_db):
    report = default_audio_processing_report()
    track_path = Path(path)
    if not track_path.exists():
        report["failed"] = 1
        report["issue"] = "Titel konnte nicht gefunden werden."
        return report
    if not audio_processing_tools_available():
        report["skipped"] = 1
        report["issue"] = "Lautstärke-Anpassung übersprungen, weil ffmpeg fehlt."
        return report
    AUDIO_PROCESSING_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = AUDIO_PROCESSING_QUEUE_DIR / f"job-{int(time.time())}-{secrets.token_hex(4)}.json"
    manifest_payload = {
        "created_at": int(time.time()),
        "operation": "volume_adjust",
        "gain_db": round(float(gain_db), 1),
        "paths": [str(track_path.resolve())],
    }
    save_json(manifest_path, manifest_payload)
    gain_label = f"{manifest_payload['gain_db']:+.1f} dB"
    save_audio_processing_status(
        manifest_path.name,
        _audio_job_payload(
            manifest_path.name,
            manifest_payload["paths"],
            state="queued",
            file_statuses=[_audio_file_status_entry(track_path, state="queued", progress_ratio=0.0, detail=f"Wartet auf {gain_label}")],
        ),
    )
    if audio_processing_worker_running():
        report["tool_available"] = True
        report["scheduled"] = 1
        report["jobs"] = [{"job": manifest_path.name, "paths": manifest_payload["paths"]}]
        return report
    try:
        _spawn_audio_processing_worker()
    except OSError:
        manifest_path.unlink(missing_ok=True)
        audio_processing_status_path(manifest_path.name).unlink(missing_ok=True)
        report["tool_available"] = True
        report["failed"] = 1
        report["issue"] = "Lautstärke-Anpassung konnte nicht gestartet werden."
        return report
    report["tool_available"] = True
    report["scheduled"] = 1
    report["jobs"] = [{"job": manifest_path.name, "paths": manifest_payload["paths"]}]
    return report


def build_playlist(album_dir):
    audio_files = sorted(
        [path for path in album_dir.rglob("*") if path.is_file() and is_audio_file(path)],
        key=lambda item: str(item.relative_to(album_dir)).lower(),
    )
    playlist_path = album_dir / "playlist.m3u"
    playlist_lines = ["#EXTM3U"]
    for track in audio_files:
        playlist_lines.append(track.relative_to(album_dir).as_posix())
    playlist_path.write_text("\n".join(playlist_lines) + "\n", encoding="utf-8")
    return playlist_path, audio_files


def list_album_audio_entries(album_dir):
    return sorted(
        [
            path.relative_to(album_dir).as_posix()
            for path in album_dir.rglob("*")
            if path.is_file() and is_audio_file(path)
        ],
        key=str.lower,
    )


def write_playlist_entries(album_dir, entries):
    playlist_path = album_dir / "playlist.m3u"
    playlist_lines = ["#EXTM3U", *entries]
    playlist_path.write_text("\n".join(playlist_lines) + "\n", encoding="utf-8")
    return playlist_path


def build_track_metadata(album_dir, entries, existing_tracks=None):
    existing_map = {}
    for item in existing_tracks or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        if path:
            existing_map[path] = dict(item)

    tracks = []
    for entry in entries:
        track_path = album_dir / entry
        try:
            stat = track_path.stat()
        except OSError:
            continue
        metadata = existing_map.get(entry, {})
        modified_ns = int(stat.st_mtime_ns)
        size_bytes = int(stat.st_size)
        if (
            int(metadata.get("modified_ns", -1) or -1) == modified_ns
            and int(metadata.get("size_bytes", -1) or -1) == size_bytes
        ):
            duration_seconds = int(metadata.get("duration_seconds", 0) or 0)
        else:
            duration_seconds = int(track_duration_seconds(track_path) or 0)
        tracks.append(
            {
                "path": entry,
                "title": str(metadata.get("title", "") or track_title_from_entry(entry)),
                "duration_seconds": duration_seconds,
                "modified_ns": modified_ns,
                "size_bytes": size_bytes,
            }
        )
    return tracks


def detect_cover(album_dir):
    image_files = sorted([path for path in album_dir.rglob("*") if path.is_file() and is_cover_file(path)])
    if not image_files:
        return ""
    preferred = next((path for path in image_files if path.stem.lower() in {"cover", "folder"}), image_files[0])
    cache_token = int(preferred.stat().st_mtime_ns)
    return f"{preferred.relative_to(BASE_DIR).as_posix()}?v={cache_token}"


def replace_album_cover(album, storage):
    filename = getattr(storage, "filename", "") or ""
    relative_name = safe_relative_path(filename)
    if not filename or str(relative_name) in {"", "."}:
        raise ValueError("Keine Cover-Datei ausgewählt.")
    if not is_cover_file(relative_name):
        raise ValueError("Es wurden keine unterstützten Bildformate hochgeladen.")

    album_dir = BASE_DIR / album.get("folder", "")
    album_dir.mkdir(parents=True, exist_ok=True)
    suffix = relative_name.suffix.lower()

    for existing in album_dir.iterdir():
        if not existing.is_file():
            continue
        stem = existing.stem.lower()
        if stem in {"cover", "folder"} and is_cover_file(existing):
            existing.unlink(missing_ok=True)

    target = album_dir / f"cover{suffix}"
    storage.save(target)
    return refresh_album_metadata(album)


def album_conflict(albums, album_id, rfid_uid):
    if not rfid_uid:
        return None
    for album in albums:
        if album["id"] != album_id and album.get("rfid_uid", "").strip() == rfid_uid:
            return album
    return None


def import_album_folder(files, album_name, rfid_uid=""):
    if not files:
        raise ValueError("Kein Ordnerinhalt hochgeladen.")

    library_data = load_library()
    requested_name = album_name.strip()
    if any((album.get("name", "").strip().lower() == requested_name.lower()) for album in library_data.get("albums", [])):
        raise ValueError("Albumname bereits vorhanden.")
    album_slug = slugify_name(album_name)
    album_dir = ALBUMS_DIR / album_slug
    if album_dir.exists():
        shutil.rmtree(album_dir)
    album_dir.mkdir(parents=True, exist_ok=True)

    raw_paths = [safe_relative_path(getattr(storage, "filename", "") or "") for storage in files]
    root_prefix = None
    if raw_paths:
        first_parts = [path.parts[0] for path in raw_paths if len(path.parts) > 1]
        if first_parts and len(first_parts) == len(raw_paths) and len(set(first_parts)) == 1:
            root_prefix = first_parts[0]

    uploaded_audio_paths = []
    for storage, raw_path in zip(files, raw_paths):
        source_name = getattr(storage, "filename", "") or ""
        relative_path = raw_path
        if root_prefix and relative_path.parts and relative_path.parts[0] == root_prefix:
            relative_path = Path(*relative_path.parts[1:]) if len(relative_path.parts) > 1 else Path(relative_path.name)
        if str(relative_path) in {"", "."}:
            relative_path = safe_relative_path(source_name)
        target = album_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        storage.save(target)
        if is_audio_file(target):
            uploaded_audio_paths.append(target)

    audio_report = default_audio_processing_report()

    playlist_path, audio_files = build_playlist(album_dir)
    if not audio_files:
        shutil.rmtree(album_dir, ignore_errors=True)
        raise ValueError("Im hochgeladenen Ordner wurden keine Audiodateien gefunden.")

    cover_url = detect_cover(album_dir)
    album_entry = {
        "id": f"album-{secrets.token_hex(4)}",
        "name": album_name.strip() or album_slug,
        "folder": album_dir.relative_to(BASE_DIR).as_posix(),
        "playlist": playlist_path.relative_to(BASE_DIR).as_posix(),
        "track_count": len(audio_files),
        "rfid_uid": rfid_uid.strip(),
        "cover_url": cover_url,
    }
    album_entry = refresh_album_metadata(album_entry)

    conflict = album_conflict(library_data["albums"], album_entry["id"], album_entry["rfid_uid"])
    if conflict:
        shutil.rmtree(album_dir, ignore_errors=True)
        raise ValueError(f"RFID-Tag bereits mit {conflict['name']} verknüpft.")

    library_data["albums"].append(album_entry)
    save_library(library_data)
    return album_entry, audio_report


def unique_album_dir(album_name):
    base_slug = slugify_name(album_name)
    album_dir = ALBUMS_DIR / base_slug
    counter = 2
    while album_dir.exists():
        album_dir = ALBUMS_DIR / f"{base_slug}-{counter}"
        counter += 1
    album_dir.mkdir(parents=True, exist_ok=True)
    return album_dir


def write_empty_playlist(album_dir):
    playlist_path = album_dir / "playlist.m3u"
    playlist_path.write_text("#EXTM3U\n", encoding="utf-8")
    return playlist_path


def read_playlist_entries(album):
    playlist_value = str(album.get("playlist", "") or "").strip()
    if not playlist_value:
        return []
    playlist_path = BASE_DIR / playlist_value
    if not playlist_path.exists() or not playlist_path.is_file():
        return []
    entries = []
    for line in playlist_path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        entries.append(item)
    return entries


def effective_track_entries(album):
    album_dir = BASE_DIR / album.get("folder", "")
    if not album_dir.exists():
        return []

    existing = list_album_audio_entries(album_dir)
    existing_set = set(existing)
    ordered = []
    seen = set()

    for entry in read_playlist_entries(album):
        normalized = safe_relative_path(entry).as_posix()
        if normalized in existing_set and normalized not in seen:
            ordered.append(normalized)
            seen.add(normalized)

    for entry in existing:
        if entry not in seen:
            ordered.append(entry)
            seen.add(entry)

    return ordered


def refresh_album_metadata(album):
    album_dir = BASE_DIR / album.get("folder", "")
    if not album_dir.exists():
        return album
    track_entries = effective_track_entries(album)
    if track_entries:
        playlist_path = write_playlist_entries(album_dir, track_entries)
    else:
        playlist_path = write_empty_playlist(album_dir)
    album["playlist"] = playlist_path.relative_to(BASE_DIR).as_posix()
    album["track_count"] = len(track_entries)
    album["cover_url"] = detect_cover(album_dir)
    album["tracks"] = build_track_metadata(album_dir, track_entries, existing_tracks=album.get("tracks", []))
    album["track_entries"] = track_entries
    return album


def create_empty_album(album_name, rfid_uid=""):
    library_data = load_library()
    requested_name = album_name.strip()
    if any((album.get("name", "").strip().lower() == requested_name.lower()) for album in library_data.get("albums", [])):
        raise ValueError("Albumname bereits vorhanden.")
    album_dir = unique_album_dir(album_name)
    playlist_path = write_empty_playlist(album_dir)
    album_entry = {
        "id": f"album-{secrets.token_hex(4)}",
        "name": album_name.strip() or album_dir.name,
        "folder": album_dir.relative_to(BASE_DIR).as_posix(),
        "playlist": playlist_path.relative_to(BASE_DIR).as_posix(),
        "track_count": 0,
        "rfid_uid": rfid_uid.strip(),
        "cover_url": "",
        "shuffle_enabled": False,
        "tracks": [],
    }
    conflict = album_conflict(library_data["albums"], album_entry["id"], album_entry["rfid_uid"])
    if conflict:
        shutil.rmtree(album_dir, ignore_errors=True)
        raise ValueError(f"RFID-Tag bereits mit {conflict['name']} verknüpft.")
    library_data["albums"].append(album_entry)
    save_library(library_data)
    return album_entry


def create_album_with_tracks(files, album_name, rfid_uid=""):
    valid_files = [item for item in (files or []) if getattr(item, "filename", "")]
    if not valid_files:
        raise ValueError("Bitte Titel auswählen.")

    album_entry = create_empty_album(album_name, rfid_uid)
    try:
        album_entry, audio_report = add_tracks_to_album(album_entry, valid_files)
    except Exception:
        album_dir = BASE_DIR / album_entry.get("folder", "")
        if album_dir.exists() and ALBUMS_DIR in album_dir.parents:
            shutil.rmtree(album_dir, ignore_errors=True)
        library_data = load_library()
        library_data["albums"] = [entry for entry in library_data.get("albums", []) if entry.get("id") != album_entry.get("id")]
        save_library(library_data)
        raise

    library_data = load_library()
    target = next((entry for entry in library_data.get("albums", []) if entry.get("id") == album_entry.get("id")), None)
    if target is None:
        library_data.setdefault("albums", []).append(album_entry)
        save_library(library_data)
        return album_entry, audio_report
    target.update(album_entry)
    save_library(library_data)
    return target, audio_report


def add_tracks_to_album(album, files):
    album_dir = BASE_DIR / album.get("folder", "")
    album_dir.mkdir(parents=True, exist_ok=True)
    valid_files = [item for item in files if getattr(item, "filename", "")]
    if not valid_files:
        raise ValueError("Keine Dateien ausgewählt.")

    raw_paths = [safe_relative_path(getattr(storage, "filename", "") or "") for storage in valid_files]
    root_prefix = None
    if raw_paths:
        first_parts = [path.parts[0] for path in raw_paths if len(path.parts) > 1]
        if first_parts and len(first_parts) == len(raw_paths) and len(set(first_parts)) == 1:
            root_prefix = first_parts[0]

    saved_audio = 0
    uploaded_audio_paths = []
    for storage, raw_path in zip(valid_files, raw_paths):
        relative_path = raw_path
        if root_prefix and relative_path.parts and relative_path.parts[0] == root_prefix:
            relative_path = Path(*relative_path.parts[1:]) if len(relative_path.parts) > 1 else Path(relative_path.name)
        if str(relative_path) in {"", "."}:
            relative_path = safe_relative_path(getattr(storage, "filename", "") or "")
        if not is_audio_file(relative_path):
            continue
        target = album_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        storage.save(target)
        saved_audio += 1
        uploaded_audio_paths.append(target)

    if not saved_audio:
        raise ValueError("Es wurden keine unterstützten Audiodateien hochgeladen.")
    audio_report = default_audio_processing_report()
    return refresh_album_metadata(album), audio_report


def remove_tracks_from_album(album, track_paths):
    requested = [item.strip() for item in (track_paths or []) if str(item or "").strip()]
    if not requested:
        raise ValueError("Keine Titel ausgewählt.")

    removed = 0
    for track_path in requested:
        remove_track_from_album(album, track_path)
        removed += 1
    refresh_album_metadata(album)
    return removed


def remove_track_from_album(album, track_path):
    album_dir = BASE_DIR / album.get("folder", "")
    target = (album_dir / safe_relative_path(track_path)).resolve()
    if not target.exists() or album_dir.resolve() not in target.parents:
        raise ValueError("Titel konnte nicht gefunden werden.")
    target.unlink(missing_ok=True)
    current = target.parent
    album_root = album_dir.resolve()
    while current != album_root and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
    return refresh_album_metadata(album)


def rename_track_in_album(album, track_path, new_name):
    requested_name = str(new_name or "").strip()
    if not requested_name:
        raise ValueError("Neuer Titelname fehlt.")

    album_dir = (BASE_DIR / album.get("folder", "")).resolve()
    source = (album_dir / safe_relative_path(track_path)).resolve()
    if not source.exists() or album_dir not in source.parents:
        raise ValueError("Titel konnte nicht gefunden werden.")
    if not is_audio_file(source):
        raise ValueError("Nur Audiodateien können umbenannt werden.")

    cleaned_name = secure_filename(requested_name)
    if not cleaned_name:
        raise ValueError("Titelname ist ungültig.")
    if Path(cleaned_name).suffix.lower() != source.suffix.lower():
        cleaned_name = f"{Path(cleaned_name).stem or cleaned_name}{source.suffix.lower()}"
    if Path(cleaned_name).name in {"", ".", ".."}:
        raise ValueError("Titelname ist ungültig.")

    target = source.with_name(cleaned_name)
    if target == source:
        return refresh_album_metadata(album)
    if target.exists():
        raise ValueError("Ein Titel mit diesem Namen existiert bereits.")

    source.rename(target)

    old_entry = source.relative_to(album_dir).as_posix()
    new_entry = target.relative_to(album_dir).as_posix()
    entries = [new_entry if entry == old_entry else entry for entry in effective_track_entries(album)]
    write_playlist_entries(album_dir, entries)
    return refresh_album_metadata(album)


def reorder_album_tracks(album, ordered_paths):
    current_entries = effective_track_entries(album)
    if not current_entries:
        return refresh_album_metadata(album)

    normalized = []
    seen = set()
    current_set = set(current_entries)
    for entry in ordered_paths or []:
        candidate = safe_relative_path(entry).as_posix()
        if candidate in current_set and candidate not in seen:
            normalized.append(candidate)
            seen.add(candidate)

    if not normalized:
        raise ValueError("Keine Reihenfolge übergeben.")

    for entry in current_entries:
        if entry not in seen:
            normalized.append(entry)

    album_dir = BASE_DIR / album.get("folder", "")
    write_playlist_entries(album_dir, normalized)
    return refresh_album_metadata(album)


def track_display_name(track_path):
    leaf = Path(track_path).name
    return Path(leaf).stem.replace("_", " ")


def track_rows(album):
    rows = []
    track_map = {
        str(item.get("path", "") or ""): dict(item)
        for item in (album.get("tracks", []) or [])
        if isinstance(item, dict)
    }
    for index, track in enumerate(album.get("track_entries", []), start=1):
        metadata = track_map.get(track, {})
        rows.append(
            {
                "index": index,
                "path": track,
                "filename": Path(track).name,
                "display_name": str(metadata.get("title", "") or track_display_name(track)),
                "duration_seconds": int(metadata.get("duration_seconds", 0) or 0),
            }
        )
    return rows


def enrich_library_data(library_data):
    for album in library_data.get("albums", []):
        album["shuffle_enabled"] = bool(album.get("shuffle_enabled", False))
        refresh_album_metadata(album)
    return library_data


def format_storage_size(num_bytes):
    value = max(0, int(num_bytes or 0))
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    value_float = float(value)
    while value_float >= 1024 and index < len(units) - 1:
        value_float /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value_float)} {units[index]}"
    return f"{value_float:.1f} {units[index]}"


def library_storage_summary():
    target_path = ALBUMS_DIR if ALBUMS_DIR.exists() else BASE_DIR
    try:
        usage = shutil.disk_usage(target_path)
    except OSError:
        return {
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "total_label": "Unbekannt",
            "used_label": "Unbekannt",
            "free_label": "Unbekannt",
            "used_percent": 0,
            "target_path": str(target_path),
        }
    total_bytes = int(usage.total)
    used_bytes = int(usage.used)
    free_bytes = int(usage.free)
    used_percent = int(round((used_bytes / total_bytes) * 100)) if total_bytes > 0 else 0
    return {
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "total_label": format_storage_size(total_bytes),
        "used_label": format_storage_size(used_bytes),
        "free_label": format_storage_size(free_bytes),
        "used_percent": max(0, min(100, used_percent)),
        "target_path": str(target_path),
    }


def album_editor_payload(album, message=""):
    refresh_album_metadata(album)
    return {
        "ok": True,
        "message": str(message or ""),
        "album": {
            "id": album.get("id", ""),
            "name": album.get("name", ""),
            "track_count": int(album.get("track_count", 0) or 0),
            "rfid_uid": album.get("rfid_uid", ""),
            "playlist": album.get("playlist", ""),
            "shuffle_enabled": bool(album.get("shuffle_enabled", False)),
        },
        "track_rows": track_rows(album),
    }


def start_link_session(album):
    session = {
        "active": True,
        "album_id": album.get("id", ""),
        "album_name": album.get("name", ""),
        "started_at": time.time(),
        "status": "waiting_for_uid",
        "message": "Tag-scannen oder ID eingeben",
        "last_uid": "",
    }
    save_link_session(session)
    return session


def finish_link_session(session, status, message, uid=""):
    session["active"] = False
    session["status"] = status
    session["message"] = message
    session["last_uid"] = uid
    save_link_session(session)
    return session


def apply_link_uid(album_id, uid):
    uid = uid.strip()
    session = load_link_session()
    library_data = load_library()
    albums = library_data.get("albums", [])
    target = next((album for album in albums if album["id"] == album_id), None)
    if not target:
        updated = finish_link_session(session, "error", "Album nicht mehr vorhanden.", uid)
        return {"ok": False, "message": updated["message"], "link_session": updated}, 404
    conflict = album_conflict(albums, target["id"], uid)
    if conflict:
        updated = finish_link_session(session, "conflict", "Tag bereits anderweitig verlinkt", uid)
        return {"ok": False, "message": updated["message"], "link_session": updated}, 409
    target["rfid_uid"] = uid
    save_library(library_data)
    updated = finish_link_session(session, "linked", f"Tag mit {target['name']} verknüpft", uid)
    return {"ok": True, "linked_album": target, "link_session": updated}, 200
