import os
import re
import shutil
import subprocess

from .base import VolumeBackend


DEFAULT_MPD_PORT = "6600"
_STATUS_VOLUME_RE = re.compile(r"volume:\s*(\d+)%")


class MpdVolumeBackend(VolumeBackend):
    backend_name = "mpd"

    def __init__(self, config=None):
        self._config = dict(config or {})
        self._mpc_binary = str(self._config.get("mpc_binary") or os.environ.get("PHONIEBOX_MPC_BINARY") or "mpc").strip() or "mpc"
        self._mpd_host = str(self._config.get("mpd_host") or os.environ.get("MPD_HOST") or "").strip()
        self._mpd_port = str(self._config.get("mpd_port") or os.environ.get("MPD_PORT") or DEFAULT_MPD_PORT).strip()
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

    def _run_mpc(self, *args):
        if not self._ready():
            raise FileNotFoundError(self._message)
        try:
            completed = subprocess.run(
                self._command_prefix() + [str(arg) for arg in args],
                capture_output=True,
                text=True,
                check=True,
            )
        except OSError as exc:
            self._message = str(exc)
            raise RuntimeError(str(exc)) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            self._message = detail
            raise RuntimeError(detail) from exc
        return completed.stdout or ""

    def _parse_status(self, output):
        match = _STATUS_VOLUME_RE.search(str(output or ""))
        return {
            "backend": self.backend_name,
            "available": True,
            "volume": max(0, min(100, int(match.group(1)))) if match else None,
            "muted": False,
            "message": self._message,
        }

    def status(self):
        if not self._ready():
            return {
                "backend": self.backend_name,
                "available": False,
                "volume": None,
                "muted": False,
                "message": self._message,
            }
        try:
            output = self._run_mpc("status")
        except (FileNotFoundError, RuntimeError) as exc:
            return {
                "backend": self.backend_name,
                "available": False,
                "volume": None,
                "muted": False,
                "message": str(exc),
            }
        return self._parse_status(output)

    def set_volume(self, volume):
        target = max(0, min(100, int(volume or 0)))
        try:
            output = self._run_mpc("volume", str(target))
        except (FileNotFoundError, RuntimeError) as exc:
            return {
                "backend": self.backend_name,
                "available": False,
                "volume": None,
                "muted": False,
                "message": str(exc),
            }
        status = self._parse_status(output)
        if status.get("volume") is None:
            status["volume"] = target
        return status
