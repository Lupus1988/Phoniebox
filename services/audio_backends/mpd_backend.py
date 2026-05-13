import os
import re
import shutil
import subprocess
from pathlib import Path

from runtime.audio import resolve_track_path

from .base import AudioBackend


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_MPD_PORT = "6600"
STATE_PLAYING = "playing"
STATE_PAUSED = "paused"
STATE_STOPPED = "stopped"
STATE_ERROR = "error"
_STATUS_STATE_RE = re.compile(r"\[(playing|paused|stopped)\]")
_STATUS_INDEX_RE = re.compile(r"#(\d+)/(\d+)")
_STATUS_TIME_RE = re.compile(r"(\d+:\d+(?::\d+)?)/(\d+:\d+(?::\d+)?)")
_STATUS_VOLUME_RE = re.compile(r"volume:\s*(\d+)%")


def _parse_timecode(value):
    text = str(value or "").strip()
    if not text:
        return 0
    parts = text.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return 0
    total = 0
    for number in numbers:
        total = (total * 60) + number
    return max(0, total)


def _format_seek_time(seconds):
    total = max(0, int(seconds or 0))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class MPDAudioBackend(AudioBackend):
    backend_name = "mpd"

    def __init__(self, config=None):
        self._config = dict(config or {})
        self._mpc_binary = str(self._config.get("mpc_binary") or os.environ.get("PHONIEBOX_MPC_BINARY") or "mpc").strip() or "mpc"
        self._mpd_host = str(self._config.get("mpd_host") or os.environ.get("MPD_HOST") or "").strip()
        self._mpd_port = str(self._config.get("mpd_port") or os.environ.get("MPD_PORT") or DEFAULT_MPD_PORT).strip()
        self._volume_backend = str(self._config.get("volume_backend") or "mpd").strip().lower()
        configured_music_dir = str(
            self._config.get("mpd_music_directory")
            or os.environ.get("PHONIEBOX_MPD_MUSIC_DIR")
            or BASE_DIR
        ).strip()
        self._music_directory = Path(configured_music_dir).expanduser().resolve()
        self._message = ""

    def _command_prefix(self):
        command = [self._mpc_binary]
        if self._mpd_host:
            command.extend(["--host", self._mpd_host])
        if self._mpd_port:
            command.extend(["--port", self._mpd_port])
        return command

    def _ready(self):
        if shutil.which(self._mpc_binary):
            self._message = ""
            return True
        self._message = f"{self._mpc_binary} ist nicht installiert."
        return False

    def _run_mpc(self, *args, check=True):
        if not self._ready():
            raise FileNotFoundError(self._message)
        try:
            completed = subprocess.run(
                self._command_prefix() + [str(arg) for arg in args],
                check=check,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            self._message = str(exc)
            raise RuntimeError(str(exc)) from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            detail = stderr or stdout or str(exc)
            self._message = detail
            raise RuntimeError(detail) from exc
        return completed

    def _session_error(self, previous_session, message, **extra):
        session = dict(previous_session or {})
        session.update(
            {
                "backend": self.backend_name,
                "state": STATE_ERROR,
                "error": str(message or "MPD-Fehler").strip(),
                "position_seconds": max(0, int(session.get("position_seconds", 0) or 0)),
                "duration_seconds": max(0, int(session.get("duration_seconds", 0) or 0)),
            }
        )
        session.update(extra)
        return session

    def _session_defaults(
        self,
        previous_session=None,
        playlist_relative_path="",
        entry="",
        start_position=0,
        volume=50,
        current_index=0,
        entries=None,
        queue_paths=None,
        state=STATE_PAUSED,
    ):
        session = dict(previous_session or {})
        session.update(
            {
                "backend": self.backend_name,
                "playlist": str(playlist_relative_path or ""),
                "entry": str(entry or ""),
                "playlist_entries": list(entries or []),
                "queue_paths": list(queue_paths or []),
                "current_index": max(0, int(current_index or 0)),
                "position_seconds": max(0, int(start_position or 0)),
                "duration_seconds": max(0, int(session.get("duration_seconds", 0) or 0)),
                "volume": max(0, min(100, int(volume or 0))),
                "state": state,
            }
        )
        session.pop("error", None)
        return session

    def _track_uri(self, playlist_relative_path, entry):
        track_path = resolve_track_path(playlist_relative_path, entry)
        if track_path is None:
            raise FileNotFoundError(f"Track nicht gefunden: {entry}")
        track_path = track_path.resolve()
        try:
            return str(track_path.relative_to(self._music_directory)).replace(os.sep, "/")
        except ValueError as exc:
            raise ValueError(
                f"Track liegt außerhalb der MPD-Musikbibliothek: {track_path} (music_directory={self._music_directory})"
            ) from exc

    def _build_queue_paths(self, playlist_relative_path, entries):
        return [self._track_uri(playlist_relative_path, entry) for entry in list(entries or [])]

    def _parse_status(self, output):
        lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
        parsed = {
            "state": STATE_STOPPED,
            "current_number": 0,
            "queue_total": 0,
            "position_seconds": 0,
            "duration_seconds": 0,
            "volume": None,
        }
        for line in lines:
            state_match = _STATUS_STATE_RE.search(line)
            if state_match:
                parsed["state"] = state_match.group(1)
            index_match = _STATUS_INDEX_RE.search(line)
            if index_match:
                parsed["current_number"] = max(0, int(index_match.group(1)))
                parsed["queue_total"] = max(0, int(index_match.group(2)))
            time_match = _STATUS_TIME_RE.search(line)
            if time_match:
                parsed["position_seconds"] = _parse_timecode(time_match.group(1))
                parsed["duration_seconds"] = _parse_timecode(time_match.group(2))
            volume_match = _STATUS_VOLUME_RE.search(line)
            if volume_match:
                parsed["volume"] = max(0, min(100, int(volume_match.group(1))))
        return parsed

    def _status_snapshot(self):
        completed = self._run_mpc("status")
        parsed = self._parse_status(completed.stdout)
        current = self._run_mpc("--format", "%file%", "current", check=False)
        parsed["current_path"] = (current.stdout or "").strip()
        return parsed

    def _sync_from_mpd(self, session):
        try:
            status = self._status_snapshot()
        except (FileNotFoundError, RuntimeError) as exc:
            return self._session_error(session, str(exc))

        updated = dict(session or {})
        updated.setdefault("backend", self.backend_name)
        updated["state"] = status["state"]
        updated["position_seconds"] = max(0, int(status["position_seconds"]))
        updated["duration_seconds"] = max(
            0,
            int(status["duration_seconds"] or updated.get("duration_seconds", 0) or 0),
        )
        if status["volume"] is not None:
            updated["volume"] = status["volume"]

        queue_paths = list(updated.get("queue_paths", []) or [])
        current_path = str(status.get("current_path", "") or "")
        current_index = int(updated.get("current_index", 0) or 0)
        if current_path and current_path in queue_paths:
            current_index = queue_paths.index(current_path)
        elif status["current_number"] > 0:
            current_index = max(0, status["current_number"] - 1)
        elif updated.get("playlist_entries"):
            current_index = max(0, min(len(updated["playlist_entries"]) - 1, current_index))
        else:
            current_index = 0
        updated["current_index"] = current_index

        playlist_entries = list(updated.get("playlist_entries", []) or [])
        if playlist_entries:
            updated["entry"] = playlist_entries[min(current_index, len(playlist_entries) - 1)]
        return updated

    def _apply_queue(self, queue_paths):
        self._run_mpc("clear")
        refreshed_library = False
        for queue_path in queue_paths:
            try:
                self._run_mpc("add", queue_path)
            except RuntimeError as exc:
                detail = str(exc or "").strip().lower()
                needs_refresh = "no such directory" in detail or "no such file" in detail
                if refreshed_library or not needs_refresh:
                    raise
                self._refresh_library()
                refreshed_library = True
                self._run_mpc("clear")
                for retry_path in queue_paths:
                    self._run_mpc("add", retry_path)
                return

    def _refresh_library(self):
        try:
            self._run_mpc("update", "--wait")
        except RuntimeError as exc:
            detail = str(exc or "").strip().lower()
            if "unknown command" not in detail and "unrecognized option" not in detail:
                raise
            self._run_mpc("update")

    def _launch_direct_preview(self, file_path, volume):
        track_path = Path(file_path).expanduser().resolve()
        volume_percent = max(0, min(100, int(volume or 0)))
        mpv_binary = shutil.which("mpv")
        if mpv_binary:
            command = [
                mpv_binary,
                "--no-video",
                "--really-quiet",
                "--no-config",
                "--no-resume-playback",
                f"--volume={volume_percent}",
                str(track_path),
            ]
        else:
            mpg123_binary = shutil.which("mpg123")
            if not mpg123_binary:
                raise FileNotFoundError("Für Systemsounds wird mpg123 oder mpv benötigt.")
            scale = max(0, min(32768, int((32768 * volume_percent) / 100)))
            command = [mpg123_binary, "-q", "-f", str(scale), str(track_path)]
        try:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self._message = str(exc)
            raise RuntimeError(str(exc)) from exc

    def status(self):
        if not self._ready():
            return {
                "active_backend": self.backend_name,
                "available_backends": ["current", "mpd"],
                "system_ready": False,
                "message": self._message,
                "music_directory": str(self._music_directory),
            }
        try:
            snapshot = self._status_snapshot()
        except RuntimeError as exc:
            return {
                "active_backend": self.backend_name,
                "available_backends": ["current", "mpd"],
                "system_ready": False,
                "message": str(exc),
                "music_directory": str(self._music_directory),
            }
        return {
            "active_backend": self.backend_name,
            "available_backends": ["current", "mpd"],
            "system_ready": True,
            "music_directory": str(self._music_directory),
            "player_state": snapshot["state"],
            "position_seconds": snapshot["position_seconds"],
            "duration_seconds": snapshot["duration_seconds"],
            "volume": snapshot["volume"],
        }

    def play_preview(self, file_path, volume=50):
        try:
            self._launch_direct_preview(file_path, volume)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            return {"ok": False, "details": [str(exc)], "message": str(exc)}
        return {"ok": True, "details": ["Testton gestartet."], "message": "Testton gestartet."}

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
        previous_session = previous_session or {}
        playlist_entries = list(entries or ([entry] if entry else []))
        try:
            queue_paths = self._build_queue_paths(playlist_relative_path, playlist_entries)
            self._apply_queue(queue_paths)
            self._run_mpc("stop")
            if self._volume_backend != "amixer":
                self._run_mpc("volume", max(0, min(100, int(volume or 0))))
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            return self._session_error(
                previous_session,
                str(exc),
                playlist=str(playlist_relative_path or ""),
                entry=str(entry or ""),
                playlist_entries=playlist_entries,
                current_index=max(0, int(current_index or 0)),
                queue_paths=[],
            )
        session = self._session_defaults(
            previous_session=previous_session,
            playlist_relative_path=playlist_relative_path,
            entry=entry,
            start_position=start_position,
            volume=volume,
            current_index=current_index,
            entries=playlist_entries,
            queue_paths=queue_paths,
            state=STATE_PAUSED,
        )
        return self._sync_from_mpd(session)

    def sync_session(self, session):
        return self._sync_from_mpd(session)

    def play(self, session):
        updated = dict(session or {})
        try:
            current_index = max(0, int(updated.get("current_index", 0) or 0))
            session_state = str(updated.get("state") or "").strip().lower()
            if session_state == STATE_PAUSED:
                self._run_mpc("play")
            elif session_state != STATE_PLAYING:
                self._run_mpc("play", str(current_index + 1))
            position_seconds = max(0, int(updated.get("position_seconds", 0) or 0))
            if position_seconds > 0:
                self._run_mpc("seek", _format_seek_time(position_seconds))
        except (FileNotFoundError, RuntimeError) as exc:
            return self._session_error(updated, str(exc))
        return self._sync_from_mpd(updated)

    def pause(self, session):
        updated = dict(session or {})
        try:
            if str(updated.get("state") or "").strip().lower() == STATE_PLAYING:
                self._run_mpc("pause")
        except (FileNotFoundError, RuntimeError) as exc:
            return self._session_error(updated, str(exc))
        updated["state"] = STATE_PAUSED
        return self._sync_from_mpd(updated)

    def stop(self, session):
        updated = dict(session or {})
        try:
            self._run_mpc("stop")
        except (FileNotFoundError, RuntimeError) as exc:
            return self._session_error(updated, str(exc))
        updated["state"] = STATE_STOPPED
        updated["position_seconds"] = 0
        return self._sync_from_mpd(updated)

    def seek(self, session, position_seconds):
        updated = dict(session or {})
        target_position = max(0, int(position_seconds or 0))
        updated["position_seconds"] = target_position
        session_state = str(updated.get("state") or "").strip().lower()
        if session_state not in {STATE_PLAYING, STATE_PAUSED}:
            return updated
        try:
            self._run_mpc("seek", _format_seek_time(target_position))
        except (FileNotFoundError, RuntimeError) as exc:
            return self._session_error(updated, str(exc))
        return self._sync_from_mpd(updated)

    def set_volume(self, session, volume):
        updated = dict(session or {})
        target_volume = max(0, min(100, int(volume or 0)))
        if self._volume_backend == "amixer":
            updated["volume"] = 100
            return updated
        try:
            self._run_mpc("volume", str(target_volume))
        except (FileNotFoundError, RuntimeError) as exc:
            return self._session_error(updated, str(exc))
        updated["volume"] = target_volume
        return updated

    def next_track(self, session):
        updated = dict(session or {})
        try:
            self._run_mpc("next")
        except (FileNotFoundError, RuntimeError) as exc:
            return self._session_error(updated, str(exc))
        return self._sync_from_mpd(updated)

    def previous_track(self, session):
        updated = dict(session or {})
        try:
            self._run_mpc("prev")
        except (FileNotFoundError, RuntimeError) as exc:
            return self._session_error(updated, str(exc))
        return self._sync_from_mpd(updated)
