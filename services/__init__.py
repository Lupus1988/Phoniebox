from importlib import import_module


class _RuntimeServiceProxy:
    def __getattr__(self, name):
        return getattr(_player_runtime_module().runtime_service, name)


def _player_runtime_module():
    return import_module("services.player_runtime_service")


def _library_module():
    return import_module("services.library_service")


runtime_service = _RuntimeServiceProxy()


def build_player_context(*args, **kwargs):
    return _player_runtime_module().build_player_context(*args, **kwargs)


def get_audio_environment(*args, **kwargs):
    return _player_runtime_module().get_audio_environment(*args, **kwargs)


def get_hardware_profile(*args, **kwargs):
    return _player_runtime_module().get_hardware_profile(*args, **kwargs)


def get_player_snapshot(*args, **kwargs):
    return _player_runtime_module().get_player_snapshot(*args, **kwargs)


def get_runtime_snapshot(*args, **kwargs):
    return _player_runtime_module().get_runtime_snapshot(*args, **kwargs)


def handle_player_action(*args, **kwargs):
    return _player_runtime_module().handle_player_action(*args, **kwargs)


def runtime_trigger_audio_test(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_audio_test(*args, **kwargs)


def runtime_trigger_button(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_button(*args, **kwargs)


def runtime_trigger_load_album(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_load_album(*args, **kwargs)


def runtime_trigger_queue_album(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_queue_album(*args, **kwargs)


def runtime_trigger_reset(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_reset(*args, **kwargs)


def runtime_trigger_rfid(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_rfid(*args, **kwargs)


def runtime_trigger_rfid_remove(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_rfid_remove(*args, **kwargs)


def runtime_trigger_seek(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_seek(*args, **kwargs)


def runtime_trigger_tick(*args, **kwargs):
    return _player_runtime_module().runtime_trigger_tick(*args, **kwargs)


def load_link_session(*args, **kwargs):
    return _library_module().load_link_session(*args, **kwargs)


def save_link_session(*args, **kwargs):
    return _library_module().save_link_session(*args, **kwargs)


__all__ = [
    "build_player_context",
    "get_audio_environment",
    "get_hardware_profile",
    "get_player_snapshot",
    "get_runtime_snapshot",
    "handle_player_action",
    "runtime_service",
    "runtime_trigger_audio_test",
    "runtime_trigger_button",
    "runtime_trigger_load_album",
    "runtime_trigger_queue_album",
    "runtime_trigger_reset",
    "runtime_trigger_rfid",
    "runtime_trigger_rfid_remove",
    "runtime_trigger_seek",
    "runtime_trigger_tick",
    "load_link_session",
    "save_link_session",
]
