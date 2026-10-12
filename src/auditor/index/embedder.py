from typing import Protocol

from auditor.index.store import SparseVec


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SparseEncoder(Protocol):
    def encode_documents(self, texts: list[str]) -> list[SparseVec]: ...

    def encode_query(self, text: str) -> SparseVec: ...


class BgeM3Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", device: str | None = None,
                 batch_size: int = 16):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device=device)
        self._batch_size = batch_size
        get_dim = getattr(self._model, "get_embedding_dimension", None) \n            or self._model.get_sentence_embedding_dimension
        self.dim = get_dim()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts, batch_size=self._batch_size, normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class Bm25SparseEncoder:
    def __init__(self, model_name: str = "Qdrant/bm25"):
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name)

    @staticmethod
    def _convert(embedding) -> SparseVec:
        return SparseVec(
            [int(i) for i in embedding.indices], [float(v) for v in embedding.values]
        )

    def encode_documents(self, texts: list[str]) -> list[SparseVec]:
        return [self._convert(e) for e in self._model.embed(texts)]

    def encode_query(self, text: str) -> SparseVec:
        return self._convert(next(iter(self._model.query_embed(text))))
