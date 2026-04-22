import os
import json
import shutil
import socket
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from system.audio import detect_audio_environment, resolve_output_device


BASE_DIR = Path(__file__).resolve().parent.parent
MPV_STALL_GRACE_SECONDS = 5.0
MPV_STALL_POSITION_EPSILON_SECONDS = 0.25


def configured_backend():
    return "mpv"


def configured_audio():
    setup_path = BASE_DIR / "data" / "setup.json"
    try:
        payload = json.loads(setup_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload.get("audio") or {}


def configured_alsa_device():
    audio = configured_audio()
    try:
        snapshot = detect_audio_environment()
        output_device = resolve_output_device(snapshot, audio)
    except (OSError, ValueError):
        output_device = "default"
    return _mpv_alsa_device(output_device)


def _mpv_alsa_device(output_device):
    output_device = str(output_device or "default").strip()
    if not output_device or output_device == "default":
        return "alsa/default"
    if output_device.startswith("alsa/"):
        return output_device
    if output_device.startswith("plughw:"):
        return f"alsa/{output_device}"
    if output_device.startswith("hw:"):
        return f"alsa/plug{output_device}"
    return f"alsa/{output_device}"


def _audio_tokens(item):
    return " ".join(
        [
            str(item.get("card_id", "")),
            str(item.get("name", "")),
            str(item.get("description", "")),
            str(item.get("device_name", "")),
        ]
    ).lower()


def _audio_item_matches_mode(item, mode):
    tokens = _audio_tokens(item)
    if mode == "usb_dac":
        return "usb" in tokens or "audio" in tokens
    if mode == "analog_jack":
        return "bcm2835" in tokens or "analog" in tokens or "headphones" in tokens
    return bool(tokens.strip())


def _audio_output_available(snapshot, audio):
    mode = str((audio or {}).get("output_mode", "usb_dac") or "usb_dac").strip()
    cards = list((snapshot or {}).get("cards", []) or [])
    playback_devices = list((snapshot or {}).get("playback_devices", []) or [])
    if not cards and not playback_devices:
        return False, "Keine ALSA-Soundkarte erkannt."

    if mode in {"usb_dac", "analog_jack"}:
        matching_cards = [
            card for card in cards
            if _audio_item_matches_mode(card, mode)
        ]
        matching_card_indices = {str(card.get("card_index", "")) for card in matching_cards}
        matching_playback = [
            device for device in playback_devices
            if _audio_item_matches_mode(device, mode)
            or str(device.get("card_index", "")) in matching_card_indices
        ]
        label = "USB-Soundkarte" if mode == "usb_dac" else "Onboard-Soundkarte"
        if not matching_cards:
            return False, f"{label} nicht erkannt."
        if not matching_playback:
            return False, f"{label} ohne nutzbares ALSA-Playback-Gerät."

    return True, ""


def configured_audio_output_ready():
    audio = configured_audio()
    try:
        snapshot = detect_audio_environment()
    except OSError:
        return False, "Audio-System konnte nicht geprüft werden."
    return _audio_output_available(snapshot, audio)


def backend_candidates():
    candidates = []
    if shutil.which("mpv"):
        candidates.append("mpv")
    candidates.append("mock")
    return candidates


def detect_backend(preferred_backend=None):
    candidates = backend_candidates()
    preferred = "mpv"
    backend = "mpv" if "mpv" in candidates else "mock"
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

    def _cleanup_stale_mpv_processes(self, exclude_pid=None):
        try:
            completed = subprocess.run(
                ["pgrep", "-f", r"mpv .*--input-ipc-server=/tmp/phoniebox-mpv-"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return
        exclude = str(exclude_pid or "")
        for line in completed.stdout.splitlines():
            pid = line.strip()
            if not pid or pid == exclude:
                continue
            try:
                self._terminate_process_group(int(pid))
            except (OSError, ValueError):
                continue

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

    def _entry_for_current_path(self, playlist_relative_path, current_path, entries):
        if not current_path:
            return ""
        normalized_entries = [str(entry or "") for entry in entries or [] if str(entry or "")]
        playlist_path = self._resolve_playlist_path(playlist_relative_path)
        try:
            resolved_current = Path(str(current_path)).resolve()
        except OSError:
            resolved_current = Path(str(current_path))

        if playlist_path:
            try:
                relative_entry = resolved_current.relative_to(playlist_path.parent.resolve()).as_posix()
            except ValueError:
                relative_entry = ""
            if relative_entry and (not normalized_entries or relative_entry in normalized_entries):
                return relative_entry

        for entry in normalized_entries:
            track_path = self._resolve_track_path(playlist_relative_path, entry)
            if track_path and track_path == resolved_current:
                return entry

        basename = Path(str(current_path)).name
        if basename in normalized_entries:
            return basename
        return ""

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

    def _mpv_command_succeeded(self, session, command):
        response = self._mpv_request(session, command)
        return isinstance(response, dict) and response.get("error") == "success"

    def _reset_mpv_progress_health(self, session):
        session.pop("mpv_health_time_pos", None)
        session.pop("mpv_health_checked_at", None)
        session.pop("mpv_stall_started_at", None)

    def _mpv_playback_stalled(self, session, position_seconds, paused, idle_active):
        if session.get("state") != "playing" or paused or idle_active:
            self._reset_mpv_progress_health(session)
            return False

        now = time.time()
        try:
            position = float(position_seconds or 0)
        except (TypeError, ValueError):
            self._reset_mpv_progress_health(session)
            return False

        previous_position = session.get("mpv_health_time_pos")
        if previous_position is None:
            session["mpv_health_time_pos"] = position
            session["mpv_health_checked_at"] = now
            session.pop("mpv_stall_started_at", None)
            return False

        try:
            previous_position = float(previous_position)
        except (TypeError, ValueError):
            session["mpv_health_time_pos"] = position
            session["mpv_health_checked_at"] = now
            session.pop("mpv_stall_started_at", None)
            return False

        if position > previous_position + MPV_STALL_POSITION_EPSILON_SECONDS:
            session["mpv_health_time_pos"] = position
            session["mpv_health_checked_at"] = now
            session.pop("mpv_stall_started_at", None)
            return False

        stalled_since = float(session.get("mpv_stall_started_at") or now)
        session["mpv_stall_started_at"] = stalled_since
        session["mpv_health_checked_at"] = now
        return (now - stalled_since) >= MPV_STALL_GRACE_SECONDS

    def _relaunch_mpv_session(self, session, reason):
        old_pid = session.get("pid")
        if old_pid:
            self._terminate_process_group(old_pid)
        self._cleanup_socket(session.get("socket_path", ""))
        session["pid"] = None
        session["socket_path"] = ""
        session["state"] = "ready"
        session["started_at"] = None
        session["error"] = reason
        self._reset_mpv_progress_health(session)
        return self._launch(session)

    def _build_command(self, backend, track_path, position_seconds=0, volume=50):
        position_seconds = max(0, int(position_seconds))
        volume = max(0, min(100, int(volume)))
        if backend == "mpv":
            audio_device = configured_alsa_device()
            return [
                "mpv",
                "--no-video",
                "--really-quiet",
                "--audio-display=no",
                "--idle=no",
                "--ao=alsa",
                f"--audio-device={audio_device}",
                "--cache=yes",
                "--audio-buffer=0.2",
                "--demuxer-readahead-secs=2",
                f"--volume={volume}",
                *( [f"--start={position_seconds}"] if position_seconds > 0 else [] ),
                str(track_path),
            ]
        return []

    def _build_mpv_playlist_command(self, playlist_path, current_index=0, position_seconds=0, volume=50):
        position_seconds = max(0, int(position_seconds))
        volume = max(0, min(100, int(volume)))
        audio_device = configured_alsa_device()
        return [
            "mpv",
            "--no-video",
            "--really-quiet",
            "--audio-display=no",
            "--idle=no",
            "--ao=alsa",
            f"--audio-device={audio_device}",
            "--cache=yes",
            "--audio-buffer=0.2",
            "--demuxer-readahead-secs=2",
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

        audio_ready, audio_error = configured_audio_output_ready()
        if not audio_ready:
            session["state"] = "error"
            session["error"] = audio_error
            session["pid"] = None
            session["started_at"] = None
            self._cleanup_socket(session.get("socket_path", ""))
            session["socket_path"] = ""
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
            self._cleanup_stale_mpv_processes()
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
        self._watch_process(process)
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
                    self._terminate_process_group(process.pid)
                    self._processes.pop(process.pid, None)
                    self._cleanup_socket(session.get("socket_path", ""))
                    session["state"] = "error"
                    session["error"] = "mpv wurde beendet, bevor der IPC-Socket bereit war."
                    session["pid"] = None
                    session["socket_path"] = ""
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
        self._watch_process(process)
        self.preview_pid = process.pid
        return {"ok": True, "details": ["Sound gestartet."]}

    def _watch_process(self, process):
        def reap():
            try:
                process.wait()
            except OSError:
                return
            self._processes.pop(process.pid, None)

        thread = threading.Thread(target=reap, daemon=True)
        thread.start()

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
                if not self._mpv_command_succeeded(session, ["get_property", "pid"]):
                    self._terminate_process_group(pid)
                    session["state"] = "error"
                    session["error"] = "mpv IPC nicht erreichbar."
                    session["pid"] = None
                    session["started_at"] = None
                    self._cleanup_socket(session.get("socket_path", ""))
                    session["socket_path"] = ""
                    return session
                position = self._mpv_get_property(session, "time-pos", session.get("position_seconds", 0))
                paused = bool(self._mpv_get_property(session, "pause", session.get("state") == "paused"))
                idle_active = bool(self._mpv_get_property(session, "idle-active", False))
                playlist_pos = self._mpv_get_property(session, "playlist-pos", session.get("current_index", 0))
                duration_seconds = self._mpv_get_property(session, "duration", session.get("duration_seconds", 0))
                current_path = self._mpv_get_property(session, "path", session.get("track_path", ""))
                position_float = float(position or 0)
                session["position_seconds"] = max(0, int(position_float))
                session["current_index"] = max(0, int(playlist_pos or 0))
                session["duration_seconds"] = max(0, int(float(duration_seconds or 0)))
                if current_path:
                    session["track_path"] = str(current_path)
                    current_entry = self._entry_for_current_path(
                        session.get("playlist", ""),
                        current_path,
                        session.get("playlist_entries", []),
                    ) or Path(str(current_path)).name
                    if current_entry:
                        session["entry"] = current_entry
                        entries = list(session.get("playlist_entries", []) or [])
                        if current_entry in entries:
                            session["current_index"] = entries.index(current_entry)
                session["started_at"] = None if paused else time.time() - session["position_seconds"]
                # `eof-reached` can transiently flip to true while mpv is still
                # alive and advancing within the current playlist. Treat only an
                # actually idle player as a finished session.
                if idle_active:
                    self._reset_mpv_progress_health(session)
                    session["state"] = "stopped"
                    session["pid"] = None
                    session["started_at"] = None
                    self._cleanup_socket(session.get("socket_path", ""))
                    session["socket_path"] = ""
                    self._cleanup_generated_playlist(session.get("generated_playlist_source", ""))
                    session["generated_playlist_source"] = ""
                else:
                    session["state"] = "paused" if paused else "playing"
                    if self._mpv_playback_stalled(session, position_float, paused, idle_active):
                        return self._relaunch_mpv_session(session, "mpv Zeitposition steht trotz laufender Wiedergabe.")
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
            if not self._mpv_command_succeeded(session, ["playlist-next", "force"]):
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
            if not self._mpv_command_succeeded(session, ["playlist-prev", "force"]):
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
            self._terminate_process_group(session["pid"])
            self._cleanup_socket(session.get("socket_path", ""))
            session["pid"] = None
            session["socket_path"] = ""
            session["state"] = "ready"
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
            session["position_seconds"] = max(0, int(session.get("position_seconds", 0) or 0))
            if session.get("pid"):
                self._terminate_process_group(session["pid"])
            self._cleanup_socket(session.get("socket_path", ""))
            session["pid"] = None
            session["socket_path"] = ""
            session["started_at"] = None
            session["state"] = "paused"
            self._reset_mpv_progress_health(session)
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
