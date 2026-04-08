import json
import os
import secrets
from pathlib import Path

from werkzeug.utils import secure_filename


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.stem}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    temp_path.replace(path)


def merge_defaults(data, defaults):
    if not isinstance(defaults, dict):
        return data if data is not None else defaults
    result = dict(defaults)
    if not isinstance(data, dict):
        return result
    for key, value in data.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_defaults(value, result[key])
        else:
            result[key] = value
    return result


def slugify_name(value):
    cleaned = secure_filename((value or "").strip())
    return cleaned.replace("_", "-").lower() or f"album-{secrets.token_hex(4)}"


def safe_relative_path(raw_name):
    parts = []
    for part in Path(raw_name).parts:
        if part in {"", ".", ".."}:
            continue
        cleaned = secure_filename(part)
        if cleaned:
            parts.append(cleaned)
    return Path(*parts) if parts else Path("datei")
