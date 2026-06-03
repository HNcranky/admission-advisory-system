from abc import ABC, abstractmethod


class BaseInferenceProvider(ABC):
    @abstractmethod
    def generate(self, request, policy):
        raise NotImplementedError