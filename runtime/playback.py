import os
import json
import shutil
import socket
import signal
import subprocess
import tempfile
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
MP3_FRAMES_PER_SECOND = 38.28125


def configured_backend():
    setup_path = BASE_DIR / "data" / "setup.json"
    try:
        payload = json.loads(setup_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "auto"
    audio = payload.get("audio") or {}
    preferred = str(audio.get("playback_backend", "auto") or "auto").strip().lower()
    return preferred if preferred in {"auto", "mpv", "mpg123", "cvlc"} else "auto"


def backend_candidates():
    candidates = []
    if shutil.which("mpv"):
        candidates.append("mpv")
    if shutil.which("mpg123"):
        candidates.append("mpg123")
    if shutil.which("cvlc"):
        candidates.append("cvlc")
    candidates.append("mock")
    return candidates


def detect_backend(preferred_backend=None):
    candidates = backend_candidates()
    preferred = str(preferred_backend or configured_backend() or "auto").strip().lower()
    if preferred not in {"auto", "mpv", "mpg123", "cvlc"}:
        preferred = "auto"
    backend = preferred if preferred != "auto" and preferred in candidates else (candidates[0] if candidates else "mock")
    return {
        "active_backend": backend,
        "available_backends": candidates,
        "preferred_backend": preferred,
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
        self.preview_pid = None
        self._processes = {}

    def status(self):
        self.backend_info = detect_backend()
        return self.backend_info

    def _process_exists(self, pid):
        if not pid:
            return False
        process = self._processes.get(int(pid))
        if process is not None:
            if process.poll() is None:
                return True
            self._processes.pop(int(pid), None)
            return False
        return _process_exists(pid)

    def _signal_process_group(self, pid, sig):
        if not self._process_exists(pid):
            return False
        try:
            os.killpg(os.getpgid(int(pid)), sig)
            return True
        except (OSError, ProcessLookupError, ValueError):
            return False

    def _terminate_process_group(self, pid):
        if not pid:
            return
        process = self._processes.get(int(pid))
        if process is not None:
            if process.poll() is not None:
                self._processes.pop(int(pid), None)
                return
            self._signal_process_group(pid, signal.SIGCONT)
            self._signal_process_group(pid, signal.SIGTERM)
            try:
                process.wait(timeout=0.75)
            except subprocess.TimeoutExpired:
                self._signal_process_group(pid, signal.SIGKILL)
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
            self._processes.pop(int(pid), None)
            return
        _terminate_process_group(pid)

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

    def _resolve_playlist_path(self, playlist_relative_path):
        if not playlist_relative_path:
            return None
        playlist_path = (BASE_DIR / playlist_relative_path).resolve()
        try:
            playlist_path.relative_to(BASE_DIR.resolve())
        except ValueError:
            return None
        if not playlist_path.exists() or not playlist_path.is_file():
            return None
        return playlist_path

    def _socket_path_for_pid(self, pid):
        return f"/tmp/phoniebox-mpv-{int(pid)}.sock"

    def _make_socket_path(self):
        return f"/tmp/phoniebox-mpv-{os.getpid()}-{time.time_ns()}.sock"

    def _cleanup_socket(self, socket_path):
        if not socket_path:
            return
        try:
            if Path(socket_path).exists():
                Path(socket_path).unlink()
        except OSError:
            pass

    def _cleanup_generated_playlist(self, playlist_path):
        if not playlist_path:
            return
        try:
            path = Path(playlist_path)
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _build_runtime_playlist(self, playlist_relative_path, entries):
        playlist_path = self._resolve_playlist_path(playlist_relative_path)
        if not playlist_path or not entries:
            return ""
        lines = ["#EXTM3U"]
        for entry in entries:
            track_path = self._resolve_track_path(playlist_relative_path, entry)
            if not track_path:
                continue
            lines.append(str(track_path))
        if len(lines) <= 1:
            return ""
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".m3u", prefix="phoniebox-runtime-", delete=False)
        with handle:
            handle.write("\n".join(lines) + "\n")
        return handle.name

    def _mpv_request(self, session, command):
        socket_path = session.get("socket_path", "")
        if not socket_path or not Path(socket_path).exists():
            return None
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(0.75)
        try:
            connection.connect(socket_path)
            payload = json.dumps({"command": command}).encode("utf-8") + b"\n"
            connection.sendall(payload)
            response = b""
            while b"\n" not in response:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                response += chunk
        except OSError:
            return None
        finally:
            try:
                connection.close()
            except OSError:
                pass
        if not response:
            return None
        try:
            return json.loads(response.splitlines()[0].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _mpv_get_property(self, session, property_name, default=None):
        response = self._mpv_request(session, ["get_property", property_name])
        if not isinstance(response, dict) or response.get("error") != "success":
            return default
        return response.get("data", default)

    def _build_command(self, backend, track_path, position_seconds=0, volume=50):
        position_seconds = max(0, int(position_seconds))
        volume = max(0, min(100, int(volume)))
        if backend == "mpv":
            return [
                "mpv",
                "--no-video",
                "--really-quiet",
                "--audio-display=no",
                "--idle=no",
                "--cache=no",
                "--audio-buffer=0.03",
                "--demuxer-readahead-secs=0",
                "--prefetch-playlist=no",
                f"--volume={volume}",
                *( [f"--start={position_seconds}"] if position_seconds > 0 else [] ),
                str(track_path),
            ]
        if backend == "mpg123":
            scale = max(0, min(32768, int(round((volume / 100) * 32768))))
            command = ["mpg123", "-q", "-f", str(scale)]
            if position_seconds > 0:
                skip_frames = max(0, int(round(position_seconds * MP3_FRAMES_PER_SECOND)))
                if skip_frames > 0:
                    command.extend(["-k", str(skip_frames)])
            command.append(str(track_path))
            return command
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

    def _build_mpv_playlist_command(self, playlist_path, current_index=0, position_seconds=0, volume=50):
        position_seconds = max(0, int(position_seconds))
        volume = max(0, min(100, int(volume)))
        return [
            "mpv",
            "--no-video",
            "--really-quiet",
            "--audio-display=no",
            "--idle=no",
            "--cache=no",
            "--audio-buffer=0.03",
            "--demuxer-readahead-secs=0",
            "--prefetch-playlist=no",
            f"--volume={volume}",
            f"--playlist-start={max(0, int(current_index))}",
            *( [f"--start={position_seconds}"] if position_seconds > 0 else [] ),
            f"--playlist={playlist_path}",
        ]

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
        if backend == "mpv" and session.get("playlist_mode") and session.get("playlist_source"):
            command = self._build_mpv_playlist_command(
                session.get("playlist_source", ""),
                current_index=session.get("current_index", 0),
                position_seconds=session.get("position_seconds", 0),
                volume=session.get("volume", 50),
            )
        if not command:
            session["state"] = "error"
            session["error"] = f"Kein Kommando für Backend {backend} verfügbar."
            return session

        if backend == "mpv":
            socket_path = self._make_socket_path()
            self._cleanup_socket(socket_path)
            command.insert(-1, f"--input-ipc-server={socket_path}")
            session["socket_path"] = socket_path

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

        self._processes[process.pid] = process
        session["pid"] = process.pid
        session["started_at"] = time.time() - int(session.get("position_seconds", 0))
        session["state"] = "playing"
        session.pop("error", None)
        if backend == "mpv":
            deadline = time.time() + 1.5
            while time.time() < deadline:
                if Path(session["socket_path"]).exists():
                    break
                if process.poll() is not None:
                    session["state"] = "error"
                    session["error"] = "mpv wurde beendet, bevor der IPC-Socket bereit war."
                    session["pid"] = process.pid
                    return session
                time.sleep(0.02)
        return session

    def _launch_preview(self, command):
        if not command:
            return {"ok": False, "details": ["Kein Audio-Kommando verfügbar."]}
        if self.preview_pid:
            self._terminate_process_group(self.preview_pid)
            self.preview_pid = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
        except OSError as exc:
            return {"ok": False, "details": [str(exc)]}
        self._processes[process.pid] = process
        self.preview_pid = process.pid
        return {"ok": True, "details": ["Sound gestartet."]}

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
        if previous_session:
            self.stop(previous_session)
        backend = self.status()["active_backend"]
        playlist_path = self._resolve_playlist_path(playlist_relative_path)
        track_path = self._resolve_track_path(playlist_relative_path, entry)
        runtime_playlist_path = ""
        playlist_mode = False
        playlist_source = str(playlist_path) if playlist_path else ""
        if backend == "mpv" and playlist_path and entries:
            runtime_playlist_path = self._build_runtime_playlist(playlist_relative_path, entries)
            playlist_source = runtime_playlist_path or playlist_source
            playlist_mode = bool(playlist_source)
        return {
            "backend": backend,
            "playlist": playlist_relative_path,
            "playlist_source": playlist_source,
            "generated_playlist_source": runtime_playlist_path,
            "playlist_entries": list(entries or []),
            "playlist_mode": playlist_mode,
            "entry": entry,
            "current_index": max(0, int(current_index)),
            "track_path": str(track_path) if track_path else "",
            "position_seconds": max(0, int(start_position)),
            "duration_seconds": 0,
            "volume": max(0, min(100, int(volume))),
            "state": "ready",
            "pid": None,
            "started_at": None,
            "socket_path": "",
        }

    def sync_session(self, session):
        if not session:
            return {}
        session["backend"] = session.get("backend") or self.status()["active_backend"]
        if session["backend"] == "mock":
            if session.get("state") == "playing" and session.get("started_at") is not None:
                session["position_seconds"] = max(0, int(time.time() - float(session["started_at"])))
            return session

        if session["backend"] == "mpv":
            pid = session.get("pid")
            if pid and self._process_exists(pid):
                position = self._mpv_get_property(session, "time-pos", session.get("position_seconds", 0))
                paused = bool(self._mpv_get_property(session, "pause", session.get("state") == "paused"))
                idle_active = bool(self._mpv_get_property(session, "idle-active", False))
                playlist_pos = self._mpv_get_property(session, "playlist-pos", session.get("current_index", 0))
                duration_seconds = self._mpv_get_property(session, "duration", session.get("duration_seconds", 0))
                current_path = self._mpv_get_property(session, "path", session.get("track_path", ""))
                session["position_seconds"] = max(0, int(float(position or 0)))
                session["current_index"] = max(0, int(playlist_pos or 0))
                session["duration_seconds"] = max(0, int(float(duration_seconds or 0)))
                if current_path:
                    session["track_path"] = str(current_path)
                    current_entry = Path(str(current_path)).name
                    if current_entry:
                        session["entry"] = current_entry
                session["started_at"] = None if paused else time.time() - session["position_seconds"]
                # `eof-reached` can transiently flip to true while mpv is still
                # alive and advancing within the current playlist. Treat only an
                # actually idle player as a finished session.
                if idle_active:
                    session["state"] = "stopped"
                    session["pid"] = None
                    session["started_at"] = None
                    self._cleanup_socket(session.get("socket_path", ""))
                    session["socket_path"] = ""
                    self._cleanup_generated_playlist(session.get("generated_playlist_source", ""))
                    session["generated_playlist_source"] = ""
                else:
                    session["state"] = "paused" if paused else "playing"
                return session

        pid = session.get("pid")
        if pid and self._process_exists(pid):
            if session.get("state") == "playing" and session.get("started_at") is not None:
                session["position_seconds"] = max(0, int(time.time() - float(session["started_at"])))
            return session

        session["pid"] = None
        session["started_at"] = None
        self._cleanup_socket(session.get("socket_path", ""))
        session["socket_path"] = ""
        if session.get("state") == "playing":
            session["state"] = "stopped"
        return session

    def next_track(self, session):
        session = self.sync_session(session)
        if session.get("backend") == "mpv" and session.get("pid") and self._process_exists(session["pid"]):
            current_index = int(session.get("current_index", 0))
            response = self._mpv_request(session, ["playlist-next", "force"])
            if not isinstance(response, dict) or response.get("error") != "success":
                return session
            deadline = time.time() + 0.5
            while time.time() < deadline:
                session = self.sync_session(session)
                if session.get("state") == "stopped" or int(session.get("current_index", 0)) != current_index:
                    break
                time.sleep(0.02)
            time.sleep(0.05)
            session = self.sync_session(session)
            session["position_seconds"] = 0
            session["started_at"] = time.time() if session.get("state") == "playing" else None
            return session
        return session

    def previous_track(self, session):
        session = self.sync_session(session)
        if session.get("backend") == "mpv" and session.get("pid") and self._process_exists(session["pid"]):
            current_index = int(session.get("current_index", 0))
            response = self._mpv_request(session, ["playlist-prev", "force"])
            if not isinstance(response, dict) or response.get("error") != "success":
                return session
            deadline = time.time() + 0.5
            while time.time() < deadline:
                session = self.sync_session(session)
                if int(session.get("current_index", 0)) != current_index:
                    break
                time.sleep(0.02)
            time.sleep(0.05)
            session = self.sync_session(session)
            session["position_seconds"] = 0
            session["started_at"] = time.time() if session.get("state") == "playing" else None
            return session
        return session

    def play(self, session):
        session = self.sync_session(session)
        if session.get("state") == "playing":
            return session
        if session.get("backend") == "mock":
            session["state"] = "playing"
            session["started_at"] = time.time() - int(session.get("position_seconds", 0))
            return session
        if session.get("backend") == "mpv" and session.get("pid") and self._process_exists(session["pid"]):
            if self._mpv_request(session, ["set_property", "pause", False]):
                session["started_at"] = time.time() - int(session.get("position_seconds", 0))
                session["state"] = "playing"
                return session
        if session.get("pid") and self._process_exists(session["pid"]):
            self._signal_process_group(session["pid"], signal.SIGCONT)
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
        if session.get("backend") == "mpv":
            session["position_seconds"] = max(0, int(time.time() - float(session.get("started_at") or time.time())))
            self._mpv_request(session, ["set_property", "pause", True])
            session["started_at"] = None
            session["state"] = "paused"
            return session
        if session.get("pid") and self._process_exists(session["pid"]):
            session["position_seconds"] = max(0, int(time.time() - float(session.get("started_at") or time.time())))
            self._signal_process_group(session["pid"], signal.SIGSTOP)
        session["started_at"] = None
        session["state"] = "paused"
        return session

    def stop(self, session):
        session = self.sync_session(session)
        if session.get("backend") != "mock" and session.get("pid"):
            self._terminate_process_group(session["pid"])
        self._cleanup_socket(session.get("socket_path", ""))
        self._cleanup_generated_playlist(session.get("generated_playlist_source", ""))
        session["generated_playlist_source"] = ""
        session["state"] = "stopped"
        session["position_seconds"] = 0
        session["started_at"] = None
        session["pid"] = None
        session["socket_path"] = ""
        return session

    def seek(self, session, position_seconds):
        session = self.sync_session(session)
        session["position_seconds"] = max(0, int(position_seconds))
        was_playing = session.get("state") == "playing"
        if session.get("backend") == "mock":
            if was_playing:
                session["started_at"] = time.time() - session["position_seconds"]
            return session
        if session.get("backend") == "mpv" and session.get("pid") and self._process_exists(session["pid"]):
            self._mpv_request(session, ["set_property", "time-pos", session["position_seconds"]])
            if was_playing:
                session["started_at"] = time.time() - session["position_seconds"]
            return session
        if session.get("pid"):
            self._terminate_process_group(session["pid"])
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
        if session.get("backend") == "mpv" and session.get("pid") and self._process_exists(session["pid"]):
            self._mpv_request(session, ["set_property", "volume", session["volume"]])
            return session
        if session.get("state") == "playing":
            current_position = session.get("position_seconds", 0)
            if session.get("pid"):
                self._terminate_process_group(session["pid"])
                session["pid"] = None
                session["started_at"] = None
            session["state"] = "ready"
            session["position_seconds"] = current_position
            return self._launch(session)
        return session

    def play_preview(self, file_path, volume=50):
        backend = self.status()["active_backend"]
        track_path = Path(file_path).resolve()
        try:
            track_path.relative_to(BASE_DIR.resolve())
        except ValueError:
            return {"ok": False, "details": ["Audiodatei liegt außerhalb des Projektpfads."]}
        if not track_path.exists() or not track_path.is_file():
            return {"ok": False, "details": ["Audiodatei nicht gefunden."]}
        if backend == "mock":
            return {"ok": True, "details": ["Mock-Backend aktiv, Sound nur simuliert."]}
        command = self._build_command(backend, track_path, 0, volume)
        result = self._launch_preview(command)
        if result["ok"]:
            result["backend"] = backend
        return result
