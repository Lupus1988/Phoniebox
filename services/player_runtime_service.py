from runtime.service import RuntimeService
from system.audio import detect_audio_environment
from utils import format_mmss, progress_percent, to_int


runtime_service = RuntimeService()


def build_player_context(snapshot):
    player_state = dict(snapshot["player"])
    runtime_state = snapshot["runtime"]
    settings = snapshot["settings"]
    performance = snapshot.get("performance", {}) or {}
    sleep_step_minutes = max(1, int(settings.get("sleep_timer_step", 5)))
    remaining_seconds = int(runtime_state.get("sleep_timer", {}).get("remaining_seconds", 0) or 0)
    player_state["sleep_timer_minutes"] = remaining_seconds // 60
    return {
        "player_state": player_state,
        "runtime_state": runtime_state,
        "settings": settings,
        "volume_percent": player_state["volume"],
        "volume_muted": bool(player_state.get("muted", False)),
        "volume_step": int(settings.get("volume_step", 5)),
        "sleep_step_minutes": sleep_step_minutes,
        "sleep_level": int(runtime_state.get("sleep_timer", {}).get("level", 0)),
        "sleep_remaining_seconds": remaining_seconds,
        "sleep_remaining_label": format_mmss(remaining_seconds),
        "position_label": format_mmss(player_state["position_seconds"]),
        "duration_label": format_mmss(player_state["duration_seconds"]),
        "progress_percent": progress_percent(player_state["position_seconds"], player_state["duration_seconds"]),
        "player_poll_visible_ms": int(performance.get("player_poll_visible_ms", 1000) or 1000),
        "player_poll_hidden_ms": int(performance.get("player_poll_hidden_ms", 3000) or 3000),
        "performance_profile": performance,
    }


def get_runtime_snapshot():
    return runtime_service.status()


def get_player_snapshot():
    return build_player_context(runtime_service.player_snapshot())


def get_hardware_profile():
    snapshot = get_runtime_snapshot()
    return snapshot["runtime"]["hardware"].get("profile", {})


def get_audio_environment():
    return detect_audio_environment()


def _execute_player_action(action, snapshot, seek_position=0):
    runtime_state = snapshot["runtime"]
    settings = snapshot["settings"]

    if action == "toggle_play":
        return runtime_service.toggle_playback()
    if action == "stop":
        return runtime_service.stop()
    if action == "prev":
        return runtime_service.previous_track()
    if action == "next":
        return runtime_service.next_track()
    if action == "volume_down":
        return runtime_service.set_volume(-int(settings.get("volume_step", 5)))
    if action == "volume_up":
        return runtime_service.set_volume(int(settings.get("volume_step", 5)))
    if action == "mute":
        return runtime_service.toggle_mute()
    if action == "sleep_reset":
        return {"runtime": runtime_service.set_sleep_level(0), "player": runtime_service.load_player()}
    if action == "sleep_down":
        level = max(0, int(runtime_state.get("sleep_timer", {}).get("level", 0)) - 1)
        return {"runtime": runtime_service.set_sleep_level(level), "player": runtime_service.load_player()}
    if action == "sleep_up":
        level = min(3, int(runtime_state.get("sleep_timer", {}).get("level", 0)) + 1)
        return {"runtime": runtime_service.set_sleep_level(level), "player": runtime_service.load_player()}
    if action == "clear_queue":
        return runtime_service.clear_queue()
    if action == "seek":
        return runtime_service.seek(to_int(seek_position, 0, 0))
    return None


def handle_player_action(action, payload=None):
    snapshot = runtime_service.player_snapshot()
    result = _execute_player_action(action, snapshot, (payload or {}).get("seek_position", 0))
    if result is None:
        return {"ok": False, "message": "Unbekannte Player-Aktion."}, 400
    return {"ok": True, **get_player_snapshot()}, 200


def runtime_trigger_tick(payload=None):
    payload = payload or {}
    elapsed = to_int(payload.get("elapsed", 1), 1, 1, 60)
    return runtime_service.tick(elapsed)


def runtime_trigger_rfid(payload=None, link_session_loader=None, link_session_saver=None):
    payload = payload or {}
    uid = str(payload.get("uid", "")).strip()
    if link_session_loader is not None and link_session_saver is not None:
        session = link_session_loader()
        if session.get("active") and uid:
            session["last_uid"] = uid
            session["status"] = "uid_detected"
            session["message"] = "Tag erkannt"
            link_session_saver(session)
            return {"ok": True, "link_session": session}, 200
    result = runtime_service.assign_album_by_rfid(uid)
    return result, (200 if result.get("ok") else 404)


def runtime_trigger_rfid_remove():
    return runtime_service.remove_rfid_tag()


def runtime_trigger_audio_test():
    result = runtime_service.play_system_sound("test")
    return result, (200 if result.get("ok") else 404)


def runtime_trigger_button(payload=None):
    payload = payload or {}
    name = str(payload.get("name", "")).strip()
    press_type = str(payload.get("press_type", "kurz")).strip()
    held_seconds = payload.get("held_seconds")
    resolved_press_type = runtime_service.classify_press_type(held_seconds, press_type)
    return runtime_service.trigger_button(name, resolved_press_type)


def runtime_trigger_seek(payload=None):
    payload = payload or {}
    position_seconds = to_int(payload.get("position_seconds", 0), 0, 0)
    return runtime_service.seek(position_seconds)


def runtime_trigger_reset():
    return runtime_service.reset_state()


def runtime_trigger_load_album(payload=None):
    payload = payload or {}
    album_id = str(payload.get("album_id", "")).strip()
    raw_autoplay = payload.get("autoplay", "false")
    if isinstance(raw_autoplay, bool):
        autoplay = raw_autoplay
    else:
        autoplay = str(raw_autoplay).strip().lower() in {"1", "true", "on", "yes"}
    result = runtime_service.load_album_by_id(album_id, autoplay=autoplay)
    return result, (200 if result.get("ok") else 404)


def runtime_trigger_queue_album(payload=None):
    payload = payload or {}
    album_id = str(payload.get("album_id", "")).strip()
    result = runtime_service.queue_album_by_id(album_id)
    return result, (200 if result.get("ok") else 404)
