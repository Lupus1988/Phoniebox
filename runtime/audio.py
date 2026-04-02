from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


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


def track_title_from_entry(entry):
    name = Path(entry).stem.replace("_", " ").replace("-", " ").strip()
    return name or entry


def build_track_queue(entries, start_index=0):
    queue = []
    for entry in entries[start_index + 1:]:
        queue.append(track_title_from_entry(entry))
    return queue


def pick_track_duration(entry):
    suffix = Path(entry).suffix.lower()
    if suffix == ".mp3":
        return 180
    if suffix in {".m4a", ".aac"}:
        return 210
    if suffix == ".wav":
        return 120
    if suffix == ".flac":
        return 240
    return 180
