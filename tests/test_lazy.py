import threading
import time
from concurrent.futures import ThreadPoolExecutor

from auditor.lazy import Lazy


class Model:
    dim = 64

    def encode(self, text):
        return text.upper()


def test_builds_on_first_attribute_access_only():
    built = []
    lazy = Lazy(lambda: built.append(1) or Model())
    assert built == [] and lazy.loaded is False
    assert lazy.dim == 64
    assert lazy.encode("a") == "A"
    assert built == [1] and lazy.loaded is True


def test_concurrent_first_use_builds_once():
    built = []
    lock = threading.Lock()

    def factory():
        time.sleep(0.05)
        with lock:
            built.append(1)
        return Model()

    lazy = Lazy(factory)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda _: lazy.dim, range(8))) == [64] * 8
    assert built == [1]


def test_failed_build_is_retried_on_next_use():
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("download failed")
        return Model()

    lazy = Lazy(factory)
    try:
        lazy.load()
    except OSError:
        pass
    assert lazy.dim == 64
    assert len(attempts) == 2
