import secrets
import shutil

from flask import flash, render_template, request, url_for

from services import runtime_service
from services.library_service import (
    ALBUMS_DIR,
    BASE_DIR,
    add_tracks_to_album,
    album_conflict,
    album_editor_payload,
    audio_processing_status_summary,
    apply_link_uid,
    describe_audio_processing,
    create_empty_album,
    create_album_with_tracks,
    enrich_library_data,
    finish_link_session,
    library_storage_summary,
    load_library,
    load_link_session,
    refresh_album_metadata,
    remove_track_from_album,
    remove_tracks_from_album,
    replace_album_cover,
    rename_track_in_album,
    reorder_album_tracks,
    schedule_volume_adjustment,
    save_library,
    start_link_session,
    track_rows,
)
from utils import album_editor_response, is_json_request, json_error, json_success, library_action_response, to_int


def _album_editor_json(album, message, status_code=200, category="success"):
    payload = dict(album_editor_payload(album, message))
    payload.pop("ok", None)
    payload.pop("message", None)
    return json_success(message, status_code=status_code, category=category, **payload)


def _extract_album_and_audio_report(result, fallback_album=None):
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        album = result[0] if isinstance(result[0], dict) else fallback_album
        return album or fallback_album or {}, result[1]
    if isinstance(result, dict):
        return result, {}
    return fallback_album or {}, {}


def register_library_routes(app):
    @app.route("/library", methods=["GET", "POST"], endpoint="library")
    def library():
        library_data = load_library()
        if request.method == "POST":
            action = request.form.get("action", "").strip()
            albums = library_data["albums"]
            if action == "import_album":
                files = [item for item in request.files.getlist("track_files") if getattr(item, "filename", "")]
                if not files:
                    files = [item for item in request.files.getlist("album_files") if getattr(item, "filename", "")]
                album_name = request.form.get("name", "").strip()
                rfid_uid = request.form.get("rfid_uid", "").strip()
                if not album_name:
                    return library_action_response(False, "Albumname ist erforderlich.", "error", 400)
                try:
                    create_result = create_album_with_tracks(files, album_name, rfid_uid) if files else create_empty_album(album_name, rfid_uid)
                except ValueError as exc:
                    return library_action_response(False, str(exc), "error", 400)
                album_entry, audio_report = _extract_album_and_audio_report(create_result)
                message = (
                    f"Album {album_entry['name']} angelegt und Titel hochgeladen."
                    if files
                    else f"Leeres Album {album_entry['name']} angelegt."
                )
                message += describe_audio_processing(audio_report)
                return library_action_response(
                    True,
                    message,
                    "success",
                    album=album_entry,
                    audio_processing=audio_report,
                )

            if action == "save_album":
                album_id = request.form.get("album_id", "").strip() or f"album-{secrets.token_hex(4)}"
                name = request.form.get("name", "").strip() or "Neues Album"
                folder = request.form.get("folder", "").strip()
                rfid_uid = request.form.get("rfid_uid", "").strip()
                cover_url = request.form.get("cover_url", "").strip()
                name_conflict = next(
                    (
                        album for album in albums
                        if album.get("id") != album_id and album.get("name", "").strip().lower() == name.lower()
                    ),
                    None,
                )
                if name_conflict:
                    return library_action_response(False, f"Albumname bereits vorhanden: {name_conflict['name']}.", "error", 400)
                conflict = album_conflict(albums, album_id, rfid_uid)
                if conflict:
                    return library_action_response(False, f"RFID-Tag bereits mit {conflict['name']} verknüpft.", "error", 409)

                payload = {
                    "id": album_id,
                    "name": name,
                    "folder": folder,
                    "playlist": request.form.get("playlist", "").strip(),
                    "track_count": to_int(request.form.get("track_count"), 0, 0, 5000),
                    "rfid_uid": rfid_uid,
                    "cover_url": cover_url,
                }
                existing = next((album for album in albums if album["id"] == album_id), None)
                if existing:
                    existing.update(payload)
                    save_library(library_data)
                    return library_action_response(True, f"Album {name} aktualisiert.", "success", album=existing)
                albums.append(payload)
                save_library(library_data)
                return library_action_response(True, f"Album {name} angelegt.", "success", album=payload)

            if action == "delete_album":
                album_id = request.form.get("album_id", "").strip()
                target_album = next((album for album in albums if album["id"] == album_id), None)
                if not target_album:
                    return library_action_response(False, "Album nicht gefunden.", "error", 404)
                album_path = BASE_DIR / target_album.get("folder", "")
                if album_path.exists() and ALBUMS_DIR in album_path.parents:
                    shutil.rmtree(album_path, ignore_errors=True)
                library_data["albums"] = [album for album in albums if album["id"] != album_id]
                save_library(library_data)
                return library_action_response(True, "Album entfernt.", "success")

            if action == "unlink_rfid":
                album_id = request.form.get("album_id", "").strip()
                target_album = next((album for album in albums if album["id"] == album_id), None)
                if not target_album:
                    return library_action_response(False, "Album nicht gefunden.", "error", 404)
                target_album["rfid_uid"] = ""
                save_library(library_data)
                return library_action_response(True, "RFID-Zuordnung entfernt.", "success", album=target_album)

            if action == "play_album":
                album_id = request.form.get("album_id", "").strip()
                result = runtime_service.load_album_by_id(album_id, autoplay=True)
                return library_action_response(bool(result.get("ok")), result["runtime"]["last_event"], "success" if result.get("ok") else "error", 200 if result.get("ok") else 404, runtime=result.get("runtime", {}), player=result.get("player", {}))

            if action == "load_album":
                album_id = request.form.get("album_id", "").strip()
                result = runtime_service.load_album_by_id(album_id, autoplay=False)
                return library_action_response(bool(result.get("ok")), result["runtime"]["last_event"], "success" if result.get("ok") else "error", 200 if result.get("ok") else 404, runtime=result.get("runtime", {}), player=result.get("player", {}))

            if action == "queue_album":
                album_id = request.form.get("album_id", "").strip()
                result = runtime_service.queue_album_by_id(album_id)
                return library_action_response(bool(result.get("ok")), result["runtime"]["last_event"], "success" if result.get("ok") else "error", 200 if result.get("ok") else 404, runtime=result.get("runtime", {}), player=result.get("player", {}))

            if action == "add_tracks":
                album_id = request.form.get("album_id", "").strip()
                album = next((entry for entry in albums if entry["id"] == album_id), None)
                if not album:
                    return library_action_response(False, "Album nicht gefunden.", "error", 404)
                try:
                    add_result = add_tracks_to_album(album, request.files.getlist("track_files"))
                    save_library(library_data)
                except ValueError as exc:
                    return library_action_response(False, str(exc), "error", 400)
                album, audio_report = _extract_album_and_audio_report(add_result, album)
                return library_action_response(
                    True,
                    f"Titel ergänzt.{describe_audio_processing(audio_report)}",
                    "success",
                    album=album,
                    audio_processing=audio_report,
                )

            if action == "replace_cover":
                album_id = request.form.get("album_id", "").strip()
                album = next((entry for entry in albums if entry["id"] == album_id), None)
                if not album:
                    return library_action_response(False, "Album nicht gefunden.", "error", 404)
                cover_file = request.files.get("cover_file")
                try:
                    replace_album_cover(album, cover_file)
                    save_library(library_data)
                except ValueError as exc:
                    return library_action_response(False, str(exc), "error", 400)
                return library_action_response(True, "Cover aktualisiert.", "success", album=album)

            if action == "remove_track":
                album_id = request.form.get("album_id", "").strip()
                track_path = request.form.get("track_path", "").strip()
                album = next((entry for entry in albums if entry["id"] == album_id), None)
                if not album:
                    return library_action_response(False, "Album nicht gefunden.", "error", 404)
                try:
                    remove_track_from_album(album, track_path)
                    save_library(library_data)
                except ValueError as exc:
                    return library_action_response(False, str(exc), "error", 400)
                return library_action_response(True, "Titel entfernt.", "success", album=album)

            if action == "remove_tracks":
                album_id = request.form.get("album_id", "").strip()
                album = next((entry for entry in albums if entry["id"] == album_id), None)
                if not album:
                    return library_action_response(False, "Album nicht gefunden.", "error", 404)
                try:
                    removed = remove_tracks_from_album(album, request.form.getlist("track_path"))
                    save_library(library_data)
                except ValueError as exc:
                    return library_action_response(False, str(exc), "error", 400)
                return library_action_response(True, f"{removed} Titel entfernt.", "success", album=album)

        enrich_library_data(library_data)
        return render_template(
            "library.html",
            library_data=library_data,
            link_session=load_link_session(),
            storage_summary=library_storage_summary(),
        )

    @app.route("/library/album/<album_id>", methods=["GET", "POST"], endpoint="library_album")
    def library_album(album_id):
        library_data = load_library()
        album = next((entry for entry in library_data.get("albums", []) if entry.get("id") == album_id), None)
        if not album:
            return album_editor_response(album_id, False, "Album nicht gefunden.", "error", 404)

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            try:
                if action == "rename_album":
                    name = request.form.get("name", "").strip()
                    if not name:
                        return album_editor_response(album_id, False, "Albumname ist erforderlich.", "error", 400)
                    conflict = next(
                        (
                            entry
                            for entry in library_data["albums"]
                            if entry.get("id") != album_id and entry.get("name", "").strip().lower() == name.lower()
                        ),
                        None,
                    )
                    if conflict:
                        return album_editor_response(album_id, False, f"Albumname bereits vorhanden: {conflict['name']}.", "error", 400)
                    album["name"] = name
                    save_library(library_data)
                    return _album_editor_json(album, "Albumname aktualisiert.") if is_json_request() else album_editor_response(album_id, True, "Albumname aktualisiert.", "success")

                if action == "add_tracks":
                    add_result = add_tracks_to_album(album, request.files.getlist("track_files"))
                    save_library(library_data)
                    album, audio_report = _extract_album_and_audio_report(add_result, album)
                    message = f"Titel ergänzt.{describe_audio_processing(audio_report)}"
                    if is_json_request():
                        payload = dict(album_editor_payload(album, message))
                        payload["audio_processing"] = audio_report
                        payload.pop("ok", None)
                        payload.pop("message", None)
                        return json_success(message, category="success", **payload)
                    return album_editor_response(album_id, True, message, "success")

                if action == "remove_tracks":
                    removed = remove_tracks_from_album(album, request.form.getlist("track_path"))
                    save_library(library_data)
                    return _album_editor_json(album, f"{removed} Titel entfernt.") if is_json_request() else album_editor_response(album_id, True, f"{removed} Titel entfernt.", "success")

                if action == "rename_track":
                    rename_track_in_album(
                        album,
                        request.form.get("track_path", "").strip(),
                        request.form.get("new_name", "").strip(),
                    )
                    save_library(library_data)
                    return _album_editor_json(album, "Titel umbenannt.") if is_json_request() else album_editor_response(album_id, True, "Titel umbenannt.", "success")

                if action == "reorder_tracks":
                    reorder_album_tracks(album, request.form.getlist("track_order"))
                    save_library(library_data)
                    return _album_editor_json(album, "Reihenfolge gespeichert.") if is_json_request() else album_editor_response(album_id, True, "Reihenfolge gespeichert.", "success")

                if action == "set_shuffle":
                    album["shuffle_enabled"] = request.form.get("shuffle_enabled", "").strip().lower() in {"1", "true", "on", "yes"}
                    save_library(library_data)
                    return _album_editor_json(album, "Shuffle gespeichert.")

                if action == "volume_edit":
                    track_path = request.form.get("track_path", "").strip()
                    gain_db = round(float(request.form.get("gain_db", "0").replace(",", ".")), 1)
                    track_entries = set(album.get("track_entries", []) or [])
                    if track_path not in track_entries:
                        return album_editor_response(album_id, False, "Titel konnte nicht gefunden werden.", "error", 404)
                    audio_report = schedule_volume_adjustment(BASE_DIR / album.get("folder", "") / track_path, gain_db)
                    if audio_report.get("failed") or audio_report.get("issue"):
                        return album_editor_response(album_id, False, audio_report.get("issue") or "Lautstärke-Anpassung fehlgeschlagen.", "error", 400)
                    message = f"Lautstärke-Anpassung gestartet ({gain_db:+.1f} dB)."
                    if is_json_request():
                        payload = dict(album_editor_payload(album, message))
                        payload["audio_processing"] = audio_report
                        payload.pop("ok", None)
                        payload.pop("message", None)
                        return json_success(message, category="success", **payload)
                    return album_editor_response(album_id, True, message, "success")
            except ValueError as exc:
                return album_editor_response(album_id, False, str(exc), "error", 400)

        refresh_album_metadata(album)
        return render_template(
            "album_editor.html",
            album=album,
            track_rows=track_rows(album),
        )

    @app.route("/api/library/album/<album_id>", endpoint="api_library_album")
    def api_library_album(album_id):
        library_data = load_library()
        album = next((entry for entry in library_data.get("albums", []) if entry.get("id") == album_id), None)
        if not album:
            return json_error("Album nicht gefunden.", status_code=404)
        return _album_editor_json(album, "")

    @app.route("/api/library/audio-processing-status", methods=["GET"], endpoint="api_library_audio_processing_status")
    def api_library_audio_processing_status():
        job_ids = [item.strip() for item in request.args.getlist("job_id") if item.strip()]
        return json_success("", audio_processing=audio_processing_status_summary(job_ids))

    @app.route("/api/library/link-session", methods=["POST"], endpoint="api_library_link_session_start")
    def api_library_link_session_start():
        payload = request.get_json(silent=True) or {}
        album_id = str(payload.get("album_id", request.form.get("album_id", ""))).strip()
        library_data = load_library()
        album = next((entry for entry in library_data.get("albums", []) if entry["id"] == album_id), None)
        if not album:
            return json_error("Album nicht gefunden.", status_code=404)
        return json_success("Verlinkung gestartet.", link_session=start_link_session(album))

    @app.route("/api/library/link-session", methods=["GET"], endpoint="api_library_link_session_status")
    def api_library_link_session_status():
        return json_success(link_session=load_link_session())

    @app.route("/api/library/link-session/confirm", methods=["POST"], endpoint="api_library_link_session_confirm")
    def api_library_link_session_confirm():
        payload = request.get_json(silent=True) or {}
        album_id = str(payload.get("album_id", request.form.get("album_id", ""))).strip()
        uid = str(payload.get("uid", request.form.get("uid", ""))).strip()
        if not album_id:
            return json_error("Album nicht gefunden.", status_code=404)
        if not uid:
            return json_error("Tag-ID fehlt.", status_code=400)
        response_payload, status_code = apply_link_uid(album_id, uid)
        payload = dict(response_payload)
        ok = bool(payload.pop("ok", status_code < 400))
        message = payload.pop("message", "")
        return json_success(message, status_code=status_code, **payload) if ok else json_error(message, status_code=status_code, **payload)

    @app.route("/api/library/link-session/cancel", methods=["POST"], endpoint="api_library_link_session_cancel")
    def api_library_link_session_cancel():
        session = load_link_session()
        updated = finish_link_session(session, "cancelled", "Verlinkung abgebrochen.")
        return json_success("Verlinkung abgebrochen.", link_session=updated)
