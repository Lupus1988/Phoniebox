import subprocess
import wave
from pathlib import Path

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None


BASE_DIR = Path(__file__).resolve().parent.parent
_DURATION_CACHE = {}


def load_playlist_entries(playlist_relative_path):
    if not playlist_relative_path:
        return []
    playlist_path = BASE_DIR / playlist_relative_path
    if not playlist_path.exists():
        return []
    lines = playlist_path.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return entries


def resolve_track_path(playlist_relative_path, entry):
    if not playlist_relative_path or not entry:
        return None
    playlist_path = BASE_DIR / playlist_relative_path
    if not playlist_path.exists():
        return None
    track_path = (playlist_path.parent / entry).resolve()
    try:
        track_path.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    if not track_path.exists() or not track_path.is_file():
        return None
    return track_path


def track_title_from_entry(entry):
    name = Path(entry).stem.replace("_", " ").replace("-", " ").strip()
    return name or entry


def build_track_queue(entries, start_index=0):
    queue = []
    for entry in entries[start_index + 1:]:
        queue.append(track_title_from_entry(entry))
    return queue


def _cache_key(path):
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _duration_from_mutagen(path):
    if MutagenFile is None:
        return None
    try:
        metadata = MutagenFile(path)
    except Exception:
        return None
    if metadata is None or not getattr(metadata, "info", None):
        return None
    length = getattr(metadata.info, "length", None)
    if length is None:
        return None
    return max(0, int(round(float(length))))


def _duration_from_wave(path):
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as handle:
            frame_rate = handle.getframerate() or 0
            frame_count = handle.getnframes() or 0
    except (OSError, wave.Error):
        return None
    if frame_rate <= 0:
        return None
    return max(0, int(round(frame_count / frame_rate)))


def _duration_from_ffprobe(path):
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    output = (completed.stdout or "").strip()
    if not output:
        return None
    try:
        return max(0, int(round(float(output))))
    except ValueError:
        return None


def track_duration_seconds(path):
    if not path:
        return 0
    key = _cache_key(path)
    if key in _DURATION_CACHE:
        return _DURATION_CACHE[key]
    duration = _duration_from_mutagen(path)
    if duration is None:
        duration = _duration_from_wave(path)
    if duration is None:
        duration = _duration_from_ffprobe(path)
    duration = max(0, int(duration or 0))
    _DURATION_CACHE[key] = duration
    return duration


def pick_track_duration(playlist_relative_path, entry):
    track_path = resolve_track_path(playlist_relative_path, entry)
    return track_duration_seconds(track_path)
