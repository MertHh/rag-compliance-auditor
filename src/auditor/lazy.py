import threading
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Lazy(Generic[T]):
    """Stands in for an object that is built on first use. Loading the embedding and
    reranker models takes tens of seconds; work that never searches, such as a cached
    audit, skips it. A failed build is retried on the next use."""

    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
        self._value: T | None = None
        self._build_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._value is not None

    def load(self) -> T:
        if self._value is None:
            with self._build_lock:
                if self._value is None:
                    self._value = self._factory()
        return self._value

    def __getattr__(self, name: str):
        return getattr(self.load(), name)
