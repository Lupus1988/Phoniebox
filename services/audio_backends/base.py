from abc import ABC, abstractmethod


class AudioBackend(ABC):
    @abstractmethod
    def status(self):
        raise NotImplementedError

    @abstractmethod
    def play_preview(self, file_path, volume=50):
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def sync_session(self, session):
        raise NotImplementedError

    @abstractmethod
    def play(self, session):
        raise NotImplementedError

    @abstractmethod
    def pause(self, session):
        raise NotImplementedError

    @abstractmethod
    def stop(self, session):
        raise NotImplementedError

    @abstractmethod
    def seek(self, session, position_seconds):
        raise NotImplementedError

    @abstractmethod
    def set_volume(self, session, volume):
        raise NotImplementedError

    @abstractmethod
    def next_track(self, session):
        raise NotImplementedError

    @abstractmethod
    def previous_track(self, session):
        raise NotImplementedError
