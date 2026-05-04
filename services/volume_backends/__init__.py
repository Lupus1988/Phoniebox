from .amixer_backend import AmixerVolumeBackend
from .mpd_backend import MpdVolumeBackend


BACKEND_ALIASES = {
    "amixer": AmixerVolumeBackend,
    "mpd": MpdVolumeBackend,
}


def create_volume_backend(name=None, config=None):
    backend_name = str(name or "mpd").strip().lower()
    backend_cls = BACKEND_ALIASES.get(backend_name, MpdVolumeBackend)
    return backend_cls(config=config)


__all__ = [
    "AmixerVolumeBackend",
    "MpdVolumeBackend",
    "create_volume_backend",
]
