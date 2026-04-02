import os
import shutil
import signal
import subprocess
import time
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


def _process_exists(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _signal_process_group(pid, sig):
    if not _process_exists(pid):
        return False
    try:
        os.killpg(os.getpgid(int(pid)), sig)
        return True
    except (OSError, ProcessLookupError, ValueError):
        return False


def _terminate_process_group(pid):
    if not _process_exists(pid):
        return
    _signal_process_group(pid, signal.SIGCONT)
    _signal_process_group(pid, signal.SIGTERM)
    deadline = time.time() + 1.5
    while time.time() < deadline:
        if not _process_exists(pid):
            return
        time.sleep(0.05)
    _signal_process_group(pid, signal.SIGKILL)


class PlaybackController:
    def __init__(self):
        self.backend_info = detect_backend()

    def status(self):
        self.backend_info = detect_backend()
        return self.backend_info

    def _resolve_track_path(self, playlist_relative_path, entry):
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

    def _build_command(self, backend, track_path, position_seconds=0, volume=50):
        position_seconds = max(0, int(position_seconds))
        volume = max(0, min(100, int(volume)))
        if backend == "mpg123":
            return ["mpg123", "-q", str(track_path)]
        if backend == "cvlc":
            command = [
                "cvlc",
                "--intf",
                "dummy",
                "--play-and-exit",
                "--no-video",
                f"--volume={max(0, min(256, int(round(volume * 2.56))))}",
            ]
            if position_seconds > 0:
                command.append(f"--start-time={position_seconds}")
            command.append(str(track_path))
            return command
        return []

    def _launch(self, session):
        backend = session.get("backend") or self.status()["active_backend"]
        track_path = session.get("track_path", "")
        if backend == "mock" or not track_path:
            session["state"] = "playing"
            session["started_at"] = time.time() - int(session.get("position_seconds", 0))
            session["pid"] = None
            return session

        command = self._build_command(
            backend,
            track_path,
            session.get("position_seconds", 0),
            session.get("volume", 50),
        )
        if not command:
            session["state"] = "error"
            session["error"] = f"Kein Kommando für Backend {backend} verfügbar."
            return session

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
        except OSError as exc:
            session["state"] = "error"
            session["error"] = str(exc)
            session["pid"] = None
            return session

        session["pid"] = process.pid
        session["started_at"] = time.time() - int(session.get("position_seconds", 0))
        session["state"] = "playing"
        session.pop("error", None)
        return session

    def open_track(self, playlist_relative_path, entry, start_position=0, volume=50, previous_session=None):
        if previous_session:
            self.stop(previous_session)
        track_path = self._resolve_track_path(playlist_relative_path, entry)
        return {
            "backend": self.status()["active_backend"],
            "playlist": playlist_relative_path,
            "entry": entry,
            "track_path": str(track_path) if track_path else "",
            "position_seconds": max(0, int(start_position)),
            "volume": max(0, min(100, int(volume))),
            "state": "ready",
            "pid": None,
            "started_at": None,
        }

    def sync_session(self, session):
        if not session:
            return {}
        session["backend"] = session.get("backend") or self.status()["active_backend"]
        if session["backend"] == "mock":
            if session.get("state") == "playing" and session.get("started_at") is not None:
                session["position_seconds"] = max(0, int(time.time() - float(session["started_at"])))
            return session

        pid = session.get("pid")
        if pid and _process_exists(pid):
            if session.get("state") == "playing" and session.get("started_at") is not None:
                session["position_seconds"] = max(0, int(time.time() - float(session["started_at"])))
            return session

        session["pid"] = None
        session["started_at"] = None
        if session.get("state") == "playing":
            session["state"] = "stopped"
        return session

    def play(self, session):
        session = self.sync_session(session)
        if session.get("state") == "playing":
            return session
        if session.get("backend") == "mock":
            session["state"] = "playing"
            session["started_at"] = time.time() - int(session.get("position_seconds", 0))
            return session
        if session.get("pid") and _process_exists(session["pid"]):
            _signal_process_group(session["pid"], signal.SIGCONT)
            session["started_at"] = time.time() - int(session.get("position_seconds", 0))
            session["state"] = "playing"
            return session
        return self._launch(session)

    def pause(self, session):
        session = self.sync_session(session)
        if session.get("state") != "playing":
            session["state"] = "paused"
            return session
        if session.get("backend") == "mock":
            session["position_seconds"] = max(0, int(time.time() - float(session.get("started_at") or time.time())))
            session["started_at"] = None
            session["state"] = "paused"
            return session
        if session.get("pid") and _process_exists(session["pid"]):
            session["position_seconds"] = max(0, int(time.time() - float(session.get("started_at") or time.time())))
            _signal_process_group(session["pid"], signal.SIGSTOP)
        session["started_at"] = None
        session["state"] = "paused"
        return session

    def stop(self, session):
        session = self.sync_session(session)
        if session.get("backend") != "mock" and session.get("pid"):
            _terminate_process_group(session["pid"])
        session["state"] = "stopped"
        session["position_seconds"] = 0
        session["started_at"] = None
        session["pid"] = None
        return session

    def seek(self, session, position_seconds):
        session = self.sync_session(session)
        session["position_seconds"] = max(0, int(position_seconds))
        was_playing = session.get("state") == "playing"
        if session.get("backend") == "mock":
            if was_playing:
                session["started_at"] = time.time() - session["position_seconds"]
            return session
        if session.get("pid"):
            _terminate_process_group(session["pid"])
            session["pid"] = None
            session["started_at"] = None
        session["state"] = "ready"
        if was_playing:
            return self._launch(session)
        return session

    def set_volume(self, session, volume):
        session = self.sync_session(session)
        session["volume"] = max(0, min(100, int(volume)))
        if session.get("backend") == "mock":
            return session
        if session.get("state") == "playing":
            current_position = session.get("position_seconds", 0)
            if session.get("pid"):
                _terminate_process_group(session["pid"])
                session["pid"] = None
                session["started_at"] = None
            session["state"] = "ready"
            session["position_seconds"] = current_position
            return self._launch(session)
        return session
