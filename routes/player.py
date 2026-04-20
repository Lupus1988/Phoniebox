from flask import Blueprint, flash, redirect, render_template, request, url_for

from services import (
    get_audio_environment,
    get_hardware_profile,
    get_player_snapshot,
    get_runtime_snapshot,
    handle_player_action,
    load_link_session,
    runtime_trigger_audio_test,
    runtime_trigger_button,
    runtime_trigger_load_album,
    runtime_trigger_queue_album,
    runtime_trigger_reset,
    runtime_trigger_rfid,
    runtime_trigger_rfid_remove,
    runtime_trigger_seek,
    runtime_trigger_tick,
    save_link_session,
)
from utils import is_json_request, json_error, json_success


player_bp = Blueprint("player_routes", __name__)


def _json_result(result, status_code=200, default_message=""):
    payload = dict(result or {})
    ok = bool(payload.pop("ok", status_code < 400))
    message = payload.pop("message", default_message)
    if ok:
        return json_success(message, status_code=status_code, **payload)
    return json_error(message or "Aktion fehlgeschlagen.", status_code=status_code, **payload)


@player_bp.route("/")
def index():
    return redirect(url_for("player_routes.player"))


@player_bp.route("/player", methods=["GET", "POST"])
def player():
    if request.method == "POST":
        action = request.form.get("action", "").strip()
        result, status_code = handle_player_action(
            action,
            {"seek_position": request.form.get("seek_position", 0)},
        )
        if is_json_request():
            return _json_result(result, status_code, "Playerstatus aktualisiert.")
        if status_code == 400:
            flash("Unbekannte Player-Aktion.", "error")
        else:
            flash("Playerstatus aktualisiert.", "success")
        return redirect(url_for("player_routes.player"))
    context = get_player_snapshot()
    return render_template("player.html", **context)


@player_bp.route("/api/runtime")
def api_runtime():
    payload = dict(get_runtime_snapshot())
    payload.pop("ok", None)
    payload.pop("message", None)
    return json_success(**payload)


@player_bp.route("/api/hardware")
def api_hardware():
    payload = get_hardware_profile()
    payload = payload if isinstance(payload, dict) else {"data": payload}
    return json_success(**payload)


@player_bp.route("/api/audio")
def api_audio():
    payload = get_audio_environment()
    payload = payload if isinstance(payload, dict) else {"data": payload}
    return json_success(**payload)


@player_bp.route("/api/runtime/tick", methods=["POST"])
def api_runtime_tick():
    payload = request.get_json(silent=True) or {}
    payload["elapsed"] = payload.get("elapsed", request.form.get("elapsed", 1))
    return _json_result(runtime_trigger_tick(payload))


@player_bp.route("/api/runtime/rfid", methods=["POST"])
def api_runtime_rfid():
    payload = request.get_json(silent=True) or {}
    payload["uid"] = payload.get("uid", request.form.get("uid", ""))
    result, status_code = runtime_trigger_rfid(payload, load_link_session, save_link_session)
    return _json_result(result, status_code)


@player_bp.route("/api/runtime/rfid/remove", methods=["POST"])
def api_runtime_rfid_remove():
    payload = request.get_json(silent=True) or {}
    payload["uid"] = payload.get("uid", request.form.get("uid", ""))
    return _json_result(runtime_trigger_rfid_remove(payload))


@player_bp.route("/api/runtime/audio-test", methods=["POST"])
def api_runtime_audio_test():
    result, status_code = runtime_trigger_audio_test()
    return _json_result(result, status_code)


@player_bp.route("/api/runtime/playback")
def api_runtime_playback():
    snapshot = get_runtime_snapshot()
    payload = snapshot["runtime"].get("playback_session", {})
    payload = payload if isinstance(payload, dict) else {"data": payload}
    return json_success(**payload)


@player_bp.route("/api/player/action", methods=["POST"])
def api_player_action():
    payload = request.get_json(silent=True) or {}
    payload["action"] = str(payload.get("action", request.form.get("action", ""))).strip()
    payload["seek_position"] = payload.get("seek_position", request.form.get("seek_position", 0))
    result, status_code = handle_player_action(payload["action"], payload)
    return _json_result(result, status_code, "Playerstatus aktualisiert.")


@player_bp.route("/api/player/snapshot")
def api_player_snapshot():
    payload = dict(get_player_snapshot())
    payload.pop("ok", None)
    payload.pop("message", None)
    return json_success(**payload)


@player_bp.route("/api/runtime/button", methods=["POST"])
def api_runtime_button():
    payload = request.get_json(silent=True) or {}
    payload["name"] = payload.get("name", request.form.get("name", ""))
    payload["press_type"] = payload.get("press_type", request.form.get("press_type", "kurz"))
    payload["held_seconds"] = payload.get("held_seconds", request.form.get("held_seconds"))
    return _json_result(runtime_trigger_button(payload))


@player_bp.route("/api/runtime/seek", methods=["POST"])
def api_runtime_seek():
    payload = request.get_json(silent=True) or {}
    payload["position_seconds"] = payload.get("position_seconds", request.form.get("position_seconds", 0))
    return _json_result(runtime_trigger_seek(payload))


@player_bp.route("/api/runtime/reset", methods=["POST"])
def api_runtime_reset():
    return _json_result(runtime_trigger_reset())


@player_bp.route("/api/runtime/load-album", methods=["POST"])
def api_runtime_load_album():
    payload = request.get_json(silent=True) or {}
    payload["album_id"] = payload.get("album_id", request.form.get("album_id", ""))
    payload["autoplay"] = payload.get("autoplay", request.form.get("autoplay", "false"))
    if "shuffle" not in payload and "shuffle" in request.form:
        payload["shuffle"] = request.form.get("shuffle")
    result, status_code = runtime_trigger_load_album(payload)
    return _json_result(result, status_code)


@player_bp.route("/api/runtime/queue-album", methods=["POST"])
def api_runtime_queue_album():
    payload = request.get_json(silent=True) or {}
    payload["album_id"] = payload.get("album_id", request.form.get("album_id", ""))
    if "shuffle" not in payload and "shuffle" in request.form:
        payload["shuffle"] = request.form.get("shuffle")
    result, status_code = runtime_trigger_queue_album(payload)
    return _json_result(result, status_code)
