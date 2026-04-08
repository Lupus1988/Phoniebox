from .base import AudioBackend


class MPDAudioBackend(AudioBackend):
    backend_name = "mpd"

    def __init__(self):
        self._message = "MPD-Backend ist vorbereitet, aber noch nicht verdrahtet."

    def status(self):
        return {
            "active_backend": "mpd",
            "available_backends": ["mpd"],
            "system_ready": False,
            "message": self._message,
        }

    def play_preview(self, file_path, volume=50):
        return {"ok": False, "details": [self._message], "message": self._message}

    def open_track(
        self,
        playlist_relative_path,
        entry,
        start_position=0,
        volume=50,
        previous_session=None,
        current_index=0,
        entries=None,
    ):
        session = dict(previous_session or {})
        session.update(
            {
                "backend": "mpd",
                "playlist": playlist_relative_path,
                "entry": entry,
                "current_index": max(0, int(current_index)),
                "position_seconds": max(0, int(start_position)),
                "volume": max(0, min(100, int(volume))),
                "state": "error",
                "error": self._message,
                "playlist_entries": list(entries or []),
            }
        )
        return session

    def sync_session(self, session):
        updated = dict(session or {})
        updated.setdefault("backend", "mpd")
        updated.setdefault("state", "error")
        updated.setdefault("error", self._message)
        return updated

    def play(self, session):
        return self.sync_session(session)

    def pause(self, session):
        return self.sync_session(session)

    def stop(self, session):
        updated = self.sync_session(session)
        updated["state"] = "stopped"
        updated["position_seconds"] = 0
        return updated

    def seek(self, session, position_seconds):
        updated = self.sync_session(session)
        updated["position_seconds"] = max(0, int(position_seconds))
        return updated

    def set_volume(self, session, volume):
        updated = self.sync_session(session)
        updated["volume"] = max(0, min(100, int(volume)))
        return updated

    def next_track(self, session):
        return self.sync_session(session)

    def previous_track(self, session):
        return self.sync_session(session)
