import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from auditor.llm.base import LLMResult, Usage


@dataclass
class TraceEvent:
    rule_id: str
    node: str
    started_at: str
    duration_s: float
    input: str
    output: str
    models: list[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class NodeSpan:
    input: str
    output: str = ""
    usage: Usage = field(default_factory=Usage)
    models: list[str] = field(default_factory=list)

    def add(self, result: LLMResult) -> None:
        self.usage = self.usage + result.usage
        if result.model not in self.models:
            self.models.append(result.model)


class TraceRecorder:
    def __init__(self):
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()

    @contextmanager
    def node(self, rule_id: str, node: str, input_summary: str):
        span = NodeSpan(input_summary)
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        t0 = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.output = span.output or f"error: {exc}"
            raise
        finally:
            event = TraceEvent(
                rule_id=rule_id,
                node=node,
                started_at=started_at,
                duration_s=round(time.perf_counter() - t0, 3),
                input=span.input,
                output=span.output,
                models=list(span.models),
                input_tokens=span.usage.input_tokens,
                output_tokens=span.usage.output_tokens,
                cost_usd=span.usage.cost_usd,
            )
            with self._lock:
                self._events.append(event)

    def events(self) -> list[TraceEvent]:
        with self._lock:
            return list(self._events)

    def to_dicts(self) -> list[dict]:
        return [asdict(event) for event in self.events()]

    def totals(self) -> Usage:
        total = Usage()
        for event in self.events():
            total = total + Usage(event.input_tokens, event.output_tokens, event.cost_usd)
        return total
