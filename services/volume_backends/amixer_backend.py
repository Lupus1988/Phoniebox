import re
import shutil
import subprocess

from .base import VolumeBackend


_PERCENT_RE = re.compile(r"\[(\d+)%\]")
_SWITCH_RE = re.compile(r"\[(on|off)\]")
_RAW_RE = re.compile(r"Playback\s+(\d+)\s+\[(\d+)%\]")


class AmixerVolumeBackend(VolumeBackend):
    backend_name = "amixer"
    USER_VOLUME_GAMMA = 2.2

    def __init__(self, config=None):
        self._config = dict(config or {})
        self._amixer_binary = str(self._config.get("amixer_binary") or "amixer").strip() or "amixer"
        self._card = str(
            self._config.get("alsa_volume_card")
            or self._config.get("mixer_card")
            or self._config.get("card_id")
            or ""
        ).strip()
        self._control = str(
            self._config.get("mixer_control")
            or self._config.get("alsa_mixer_control")
            or self._config.get("preferred_mixer_control")
            or "PCM"
        ).strip()
        self._message = ""
        self._limits = None

    def _ready(self):
        if not shutil.which(self._amixer_binary):
            self._message = f"{self._amixer_binary} ist nicht installiert."
            return False
        if not self._card or not self._control:
            self._message = "ALSA-Mixer ist nicht vollständig konfiguriert."
            return False
        self._message = ""
        return True

    def _command_prefix(self):
        return [self._amixer_binary, "-c", self._card]

    def _run_amixer(self, *args):
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

    def _load_limits(self):
        if self._limits is not None:
            return self._limits
        output = self._run_amixer("get", self._control)
        minimum = 0
        maximum = 100
        for line in str(output or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("Limits: Playback "):
                try:
                    payload = stripped.replace("Limits: Playback ", "", 1)
                    minimum_text, maximum_text = payload.split(" - ", 1)
                    minimum = int(minimum_text.strip())
                    maximum = int(maximum_text.strip())
                except (TypeError, ValueError):
                    minimum = 0
                    maximum = 100
                break
        self._limits = (minimum, max(minimum + 1, maximum))
        return self._limits

    def _user_to_raw(self, volume):
        user_volume = max(0, min(100, int(volume or 0)))
        minimum, maximum = self._load_limits()
        span = max(1, maximum - minimum)
        normalized = (user_volume / 100.0) ** self.USER_VOLUME_GAMMA
        return minimum + int(round(normalized * span))

    def _raw_to_user(self, raw_value):
        minimum, maximum = self._load_limits()
        span = max(1, maximum - minimum)
        normalized = max(0.0, min(1.0, (int(raw_value) - minimum) / span))
        return max(0, min(100, int(round((normalized ** (1.0 / self.USER_VOLUME_GAMMA)) * 100))))

    def _parse_output(self, output):
        volume = None
        muted = False
        raw_value = None
        raw_matches = _RAW_RE.findall(str(output or ""))
        if raw_matches:
            raw_value = int(raw_matches[-1][0])
        percentages = _PERCENT_RE.findall(str(output or ""))
        if percentages:
            volume = max(0, min(100, int(percentages[-1])))
        if raw_value is not None:
            volume = self._raw_to_user(raw_value)
        switches = _SWITCH_RE.findall(str(output or ""))
        if switches:
            muted = switches[-1] == "off"
        return {
            "backend": self.backend_name,
            "available": True,
            "volume": volume,
            "raw_volume": raw_value,
            "muted": muted,
            "card": self._card,
            "control": self._control,
            "message": self._message,
        }

    def status(self):
        if not self._ready():
            return {
                "backend": self.backend_name,
                "available": False,
                "volume": None,
                "muted": False,
                "card": self._card,
                "control": self._control,
                "message": self._message,
            }
        try:
            output = self._run_amixer("get", self._control)
        except (FileNotFoundError, RuntimeError) as exc:
            return {
                "backend": self.backend_name,
                "available": False,
                "volume": None,
                "muted": False,
                "card": self._card,
                "control": self._control,
                "message": str(exc),
            }
        return self._parse_output(output)

    def set_volume(self, volume):
        target = max(0, min(100, int(volume or 0)))
        try:
            raw_target = self._user_to_raw(target)
            output = self._run_amixer("sset", self._control, str(raw_target))
        except (FileNotFoundError, RuntimeError) as exc:
            return {
                "backend": self.backend_name,
                "available": False,
                "volume": None,
                "muted": False,
                "card": self._card,
                "control": self._control,
                "message": str(exc),
            }
        status = self._parse_output(output)
        if status.get("volume") is None:
            status["volume"] = target
        status["raw_target"] = locals().get("raw_target")
        return status
