import secrets
import shutil
from pathlib import Path

from werkzeug.utils import secure_filename

from utils import load_json, safe_relative_path, save_json, slugify_name


BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_DIR / "media"
ALBUMS_DIR = MEDIA_DIR / "albums"
LIBRARY_FILE = BASE_DIR / "data" / "library.json"
LINK_SESSION_FILE = BASE_DIR / "data" / "rfid_link_session.json"


def default_library():
    return {"albums": []}


def default_link_session():
    return {
        "active": False,
        "album_id": "",
        "album_name": "",
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


def detect_cover(album_dir):
    image_files = sorted([path for path in album_dir.rglob("*") if path.is_file() and is_cover_file(path)])
    if not image_files:
        return ""
    preferred = next((path for path in image_files if path.stem.lower() in {"cover", "folder"}), image_files[0])
    return preferred.relative_to(BASE_DIR).as_posix()


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

    conflict = album_conflict(library_data["albums"], album_entry["id"], album_entry["rfid_uid"])
    if conflict:
        shutil.rmtree(album_dir, ignore_errors=True)
        raise ValueError(f"RFID-Tag bereits mit {conflict['name']} verknüpft.")

    library_data["albums"].append(album_entry)
    save_library(library_data)
    return album_entry


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
        add_tracks_to_album(album_entry, valid_files)
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
        return album_entry
    target.update(album_entry)
    save_library(library_data)
    return target


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

    if not saved_audio:
        raise ValueError("Es wurden keine unterstützten Audiodateien hochgeladen.")
    return refresh_album_metadata(album)


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
    for index, track in enumerate(album.get("track_entries", []), start=1):
        rows.append(
            {
                "index": index,
                "path": track,
                "filename": Path(track).name,
                "display_name": track_display_name(track),
            }
        )
    return rows


def enrich_library_data(library_data):
    for album in library_data.get("albums", []):
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
        },
        "track_rows": track_rows(album),
    }


def start_link_session(album):
    session = {
        "active": True,
        "album_id": album.get("id", ""),
        "album_name": album.get("name", ""),
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
