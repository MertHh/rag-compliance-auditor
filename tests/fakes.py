import math
import re
import zlib

from auditor.index.store import SparseVec

_WORD = re.compile(r"\w+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _word_id(word: str) -> int:
    return zlib.crc32(word.encode("utf-8"))


class FakeEmbedder:
    dim = 64

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in _words(text):
            v[_word_id(word) % self.dim] += 1.0
        if not any(v):
            v[0] = 1.0
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class FakeSparseEncoder:
    def _vec(self, text: str) -> SparseVec:
        counts: dict[int, float] = {}
        for word in _words(text):
            counts[_word_id(word)] = counts.get(_word_id(word), 0.0) + 1.0
        indices = sorted(counts)
        return SparseVec(indices, [counts[i] for i in indices])

    def encode_documents(self, texts: list[str]) -> list[SparseVec]:
        return [self._vec(t) for t in texts]

    def encode_query(self, text: str) -> SparseVec:
        return self._vec(text)


class FakeReranker:
    def score(self, query: str, texts: list[str]) -> list[float]:
        wanted = set(_words(query))
        if not wanted:
            return [0.0 for _ in texts]
        return [len(wanted & set(_words(t))) / len(wanted) for t in texts]
