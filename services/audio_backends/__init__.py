from .current_backend import CurrentAudioBackend
from .mpd_backend import MPDAudioBackend


BACKEND_ALIASES = {
    "current": CurrentAudioBackend,
    "playback_controller": CurrentAudioBackend,
    "mpd": MPDAudioBackend,
}


def create_audio_backend(name=None):
    backend_name = str(name or "current").strip().lower()
    backend_cls = BACKEND_ALIASES.get(backend_name, CurrentAudioBackend)
    return backend_cls()


__all__ = [
    "CurrentAudioBackend",
    "MPDAudioBackend",
    "create_audio_backend",
]
