from runtime.playback import PlaybackController

from .base import AudioBackend


class CurrentAudioBackend(AudioBackend):
    backend_name = "current"

    def __init__(self):
        self._controller = PlaybackController()

    def status(self):
        return self._controller.status()

    def play_preview(self, file_path, volume=50):
        return self._controller.play_preview(file_path, volume=volume)

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
        return self._controller.open_track(
            playlist_relative_path,
            entry,
            start_position=start_position,
            volume=volume,
            previous_session=previous_session,
            current_index=current_index,
            entries=entries,
        )

    def sync_session(self, session):
        return self._controller.sync_session(session)

    def play(self, session):
        return self._controller.play(session)

    def pause(self, session):
        return self._controller.pause(session)

    def stop(self, session):
        return self._controller.stop(session)

    def seek(self, session, position_seconds):
        return self._controller.seek(session, position_seconds)

    def set_volume(self, session, volume):
        return self._controller.set_volume(session, volume)

    def next_track(self, session):
        return self._controller.next_track(session)

    def previous_track(self, session):
        return self._controller.previous_track(session)
