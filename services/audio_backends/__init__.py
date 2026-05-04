from .current_backend import CurrentAudioBackend
from .mpd_backend import MPDAudioBackend


BACKEND_ALIASES = {
    "current": CurrentAudioBackend,
    "playback_controller": CurrentAudioBackend,
    "mpv": CurrentAudioBackend,
    "mpd": MPDAudioBackend,
}


def create_audio_backend(name=None, config=None):
    backend_name = str(name or "current").strip().lower()
    backend_cls = BACKEND_ALIASES.get(backend_name, CurrentAudioBackend)
    return backend_cls(config=config)


__all__ = [
    "CurrentAudioBackend",
    "MPDAudioBackend",
    "create_audio_backend",
]
