import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def backend_candidates():
    candidates = []
    if shutil.which("mpg123"):
        candidates.append("mpg123")
    if shutil.which("cvlc"):
        candidates.append("cvlc")
    candidates.append("mock")
    return candidates


def detect_backend():
    candidates = backend_candidates()
    backend = candidates[0] if candidates else "mock"
    return {
        "active_backend": backend,
        "available_backends": candidates,
        "system_ready": backend != "mock",
    }


class PlaybackController:
    def __init__(self):
        self.backend_info = detect_backend()

    def status(self):
        return self.backend_info

    def open_track(self, playlist_relative_path, entry, start_position=0):
        return {
            "backend": self.backend_info["active_backend"],
            "playlist": playlist_relative_path,
            "entry": entry,
            "position_seconds": start_position,
            "state": "ready",
        }

    def play(self, session):
        session["state"] = "playing"
        return session

    def pause(self, session):
        session["state"] = "paused"
        return session

    def stop(self, session):
        session["state"] = "stopped"
        session["position_seconds"] = 0
        return session

    def seek(self, session, position_seconds):
        session["position_seconds"] = max(0, int(position_seconds))
        return session
