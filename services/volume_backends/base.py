from abc import ABC, abstractmethod


class VolumeBackend(ABC):
    backend_name = "volume"

    @abstractmethod
    def status(self):
        raise NotImplementedError

    @abstractmethod
    def set_volume(self, volume):
        raise NotImplementedError
