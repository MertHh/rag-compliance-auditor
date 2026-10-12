from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RetrievalConfig:
    mode: Literal["bm25", "dense", "hybrid"] = "hybrid"
    rerank: bool = True
    candidate_k: int = 30
    final_k: int = 5
    rrf_k: int = 60
    min_rerank_score: float = 0.3
