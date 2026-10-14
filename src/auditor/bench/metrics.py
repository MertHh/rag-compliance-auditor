from dataclasses import dataclass

Span = tuple[int, int]


def overlaps(a: Span, b: Span) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def first_hit(ranked: list[Span], gold: list[Span]) -> int | None:
    for rank, span in enumerate(ranked, start=1):
        if any(overlaps(span, g) for g in gold):
            return rank
    return None


def recall_at(ranks: list[int | None], k: int) -> float:
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mrr(ranks: list[int | None]) -> float:
    if not ranks:
        return 0.0
    return sum(1 / r for r in ranks if r is not None) / len(ranks)


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int


def prf(tp: int, fp: int, fn: int) -> PRF:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return PRF(precision, recall, f1, tp, fp, fn)


def absence_prf(pairs: list[tuple[float, bool]], threshold: float) -> PRF:
    """Positive class is a missing clause: a score below the threshold predicts 'missing'."""
    tp = sum(1 for score, present in pairs if score < threshold and not present)
    fp = sum(1 for score, present in pairs if score < threshold and present)
    fn = sum(1 for score, present in pairs if score >= threshold and not present)
    return prf(tp, fp, fn)


def best_f1_threshold(pairs: list[tuple[float, bool]]) -> tuple[float, PRF]:
    """Tries every distinct score (and one above the maximum) in one sorted sweep."""
    ordered = sorted(pairs)
    total_missing = sum(1 for _, present in ordered if not present)
    best: tuple[float, PRF] | None = None
    tp = fp = 0
    candidates = sorted({score for score, _ in ordered}) + [ordered[-1][0] + 1e-9] if ordered else []
    i = 0
    for threshold in candidates:
        while i < len(ordered) and ordered[i][0] < threshold:
            if ordered[i][1]:
                fp += 1
            else:
                tp += 1
            i += 1
        result = prf(tp, fp, total_missing - tp)
        if best is None or result.f1 > best[1].f1:
            best = (threshold, result)
    return best if best is not None else (0.0, prf(0, 0, 0))


def threshold_for_present_recall(pairs: list[tuple[float, bool]], min_recall: float = 0.95) -> float:
    """The highest threshold that still keeps min_recall of the present clauses above it."""
    present = sorted(score for score, is_present in pairs if is_present)
    if not present:
        return 0.0
    allowed_misses = int((1 - min_recall) * len(present) + 1e-9)
    return present[allowed_misses]


def citation_hits(citations: list[Span], gold: list[Span]) -> int:
    return sum(1 for c in citations if any(overlaps(c, g) for g in gold))
