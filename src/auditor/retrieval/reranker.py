from typing import Protocol


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class BgeReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3",
                 device: str | None = None, max_length: int = 512):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name, device=device, max_length=max_length)

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        import torch

        raw = self._model.predict(
            [(query, text) for text in texts],
            activation_fn=torch.nn.Sigmoid(),
            show_progress_bar=False,
        )
        return [float(x) for x in raw]
