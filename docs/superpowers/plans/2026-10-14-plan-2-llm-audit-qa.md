# Plan 2: LLM Sağlayıcıları, Denetim Ajanı ve Belgeye Sor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** İndekslenmiş bir sözleşmeyi YAML playbook'a göre OpenAI veya Ollama ile denetleyen, her bulguyu doğrulanmış alıntıyla kaynak metne bağlayan, sonucu SQLite'a önbellekli kaydeden; ayrıca belgeye alıntılı soru cevaplayan ve yükleme sırasında belge metadata'sı çıkaran, komut satırından kullanılabilir katman.

**Architecture:** `auditor.llm` küçük bir sağlayıcı arayüzü (`LLMProvider`) ve iki uygulama (OpenAI structured outputs, Ollama JSON şema) içerir. `auditor.audit` her kural için aynı LangGraph grafını çalıştırır (ara → gerekirse sorguyu yeniden yaz → değerlendir → alıntıyı doğrula → yokluk hükmünde geniş tara); durumu kod belirler, LLM yalnızca "madde var mı / ölçüte uyuyor mu" ve alıntı döndürür. `auditor.qa` ve `auditor.ingestion.metadata` aynı sağlayıcı arayüzünü ve alıntı doğrulayıcıyı kullanır. Testler ağ erişimi olmadan `FakeLLM` ile çalışır.

**Tech Stack:** Python 3.11+, openai 3.x (`chat.completions.parse`), ollama 0.6, langgraph 1.x, pydantic 2, PyYAML, python-dotenv, sqlite3, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-rag-compliance-auditor-design.md` (bölüm 2, 3 "Belge metadata", 5, 6, 11)

## Plan dizisi

1. Ingestion ve arama hattı (tamamlandı, master'da)
2. **LLM sağlayıcıları, denetim ajanı, belgeye sor, SQLite kayıt deposu, belge metadata çıkarma** (bu plan)
3. FastAPI ve Streamlit arayüzü
4. Benchmark, playbook'lar, Docker Compose, README

Bu plan bağlam önekini (contextualizer) yazmaz: Plan 1'deki `Indexer(contextualizer=...)` kancası duruyor, LLM'li uygulaması benchmark ile birlikte Plan 4'te gelir.

## Global Constraints

- Python `>=3.11`. Geliştirme ortamı Windows 11; komutlar `.venv/Scripts/python` ile çalıştırılır.
- Kod, tanımlayıcılar, prompt'lar ve hata mesajları İngilizce. Bulgu durum değerleri spec'teki Türkçe değerlerdir: `uyumlu`, `uyumsuz`, `eksik`, `belirsiz`, `hata`.
- Sağlayıcı adları: `openai`, `ollama`. Model adları config'den: `OPENAI_EVAL_MODEL`, `OPENAI_SMALL_MODEL`, `OLLAMA_MODEL`. OpenAI model adı verilmemişse hesaptaki modeller listelenip seçilir (bugünkü hesapta `gpt-5.5` ve `gpt-5.4-mini`).
- Değerlendirme `eval` katmanında (güçlü model); sorgu yeniden yazma, geniş tarama, metadata çıkarma ve belgeye sor `small` katmanında.
- LLM çağrısı veya şema doğrulaması başarısız olursa bir kez tekrar denenir (`complete_with_retry`, toplam 2 deneme).
- Risk puanı: `low`=1, `medium`=2, `high`=3; `uyumlu`=0, `belirsiz`=0.5, `uyumsuz`=1, `eksik`=1; `hata` hesaba katılmaz.
- Önbellek anahtarı: `sha256(belge id + playbook sha256 + sağlayıcı + model etiketi + PROMPT_VERSION)`. Prompt metni değişirse `PROMPT_VERSION` artırılır.
- Sorgu yeniden yazma en fazla 2 kez; geniş tarama ilk 15 aday bölüm.
- Varsayılan test koşusu ağ erişimi gerektirmez. Gerçek LLM kullanan testler `@pytest.mark.slow` ile işaretlenir ve anahtar/sunucu yoksa atlanır.
- `.env` asla commit edilmez (`.gitignore`'da). Gizli anahtar loglanmaz, yazdırılmaz.
- Arama kodu Qdrant'a doğrudan bağlanmaz; `Retriever` ve `VectorStore` arayüzleri kullanılır.
- Her commit mesajı şu satırla biter: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Çalışma `plan-2-llm-audit-qa` dalında yapılır; bitince master'a merge edilip push edilir (PR açılmaz).

## Review Focus

Spec'in söylemediği ama kullanıcının karşılaşacağı durumlar. Her birinin testi ilgili task'e eklendi.

1. **LLM aynı indeksteki başka bir sözleşmeden alıntı getirir** → alıntı denetlenen belgede yoksa atılır; bulgu başka belgeye bağlanmaz (Task 4).
2. **LLM "the Agreement" gibi çok kısa, her yerde geçen bir alıntı döndürür** → 4 token altındaki alıntı kanıt sayılmaz, atılır (Task 4).
3. **Var olmayan belge id'si, var olmayan playbook adı veya kapalı Ollama ile denetim başlatılır** → hiçbir LLM çağrısı yapılmadan anlaşılır hata; kayıt oluşmaz. Playbook hatası mevcut playbook'ları listeler (Task 5, Task 10).
4. **Bir kuralda LLM dışı beklenmedik bir hata çıkar** → yalnızca o kural `hata` olur, diğerleri tamamlanır; hatalı çalıştırma önbelleğe girmez, sonraki çağrı yeniden dener (Task 7, Task 10).
5. **Metadata çıkarımı "March 1st, 2024" gibi serbest biçimli tarih veya boş metin döndürür** → alan boş kalır, yükleme başarısız olmaz (Task 12).

## File Structure

```
.gitignore                    .env eklenir
.env.example                  ortam değişkenleri örneği
pyproject.toml                yeni bağımlılıklar
playbooks/
  commercial_contract.yaml    5 kurallık başlangıç playbook'u (Plan 4 CUAD'dan genişletir)
src/auditor/
  config.py                   Settings: sağlayıcı, model, Ollama, playbook, eşzamanlılık alanları
  services.py                 AuditStore, Auditor ve sağlayıcı fabrikasını bağlar
  cli.py                      ingest (metadata ile), search, ask, audit
  llm/
    __init__.py
    base.py                   LLMProvider, LLMResult, Usage, hatalar, complete_with_retry, models_label
    openai_provider.py        OpenAIProvider, pick_models, parse_prices
    ollama_provider.py        OllamaProvider
    factory.py                build_provider, cached_provider_factory
  audit/
    __init__.py
    playbook.py               Rule, Playbook, load_playbook, find_playbook, list_playbooks
    scoring.py                Status, status_for, is_absence_verdict, rule_risk, risk_score
    citations.py              Citation, verify_quotes
    prompts.py                PROMPT_VERSION, çıktı şemaları, prompt üreticileri
    trace.py                  TraceRecorder, TraceEvent
    nodes.py                  AuditConfig, RuleState, RuleNodes (graf düğümleri)
    graph.py                  yönlendiriciler, build_rule_graph
    report.py                 build_finding, build_report
    runner.py                 Auditor, cache_key
  qa/
    __init__.py
    answer.py                 QuestionAnswerer, Answer, QAOutput
  ingestion/
    metadata.py               MetadataExtractor, DocumentMetadata
    indexer.py                extract_metadata parametresi
  storage/
    db.py                     AuditStore (SQLite)
tests/
  conftest.py                 playbooks_dir fixture'ı
  fakes.py                    FakeLLM, sequence, by_rule, audit_llm, CONTRACT_PAGES, LIABILITY_LINE
  test_llm_base.py, test_openai_provider.py, test_ollama_provider.py, test_llm_slow.py
  test_citations.py, test_playbook.py, test_scoring.py, test_audit_db.py
  test_trace_prompts.py, test_rule_graph.py, test_auditor.py
  test_qa.py, test_metadata.py, test_cli.py
```

---

### Task 1: Bağımlılıklar, ayarlar ve LLM arayüzü

**Files:**
- Modify: `pyproject.toml`, `.gitignore`, `src/auditor/config.py`, `tests/test_config.py`, `tests/fakes.py`
- Create: `src/auditor/llm/__init__.py`, `src/auditor/llm/base.py`, `tests/test_llm_base.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `Tier = Literal["eval", "small"]`
  - `class LLMError(Exception)`, `class ProviderUnavailableError(Exception)`
  - `@dataclass Usage(input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0)`, `Usage + Usage`
  - `@dataclass LLMResult(value: T, model: str, usage: Usage)`
  - `LLMProvider` Protocol: `name: str`, `model_for(tier) -> str`, `check_available() -> None` (hata: `ProviderUnavailableError`), `complete(system: str, user: str, schema: type[T], tier: Tier) -> LLMResult[T]` (hata: `LLMError`)
  - `complete_with_retry(provider, system, user, schema, tier, attempts=2) -> LLMResult[T]`
  - `models_label(provider) -> str` (`"eval+small"` veya iki katman aynıysa tek ad)
  - `Settings` yeni alanları: `provider`, `openai_eval_model`, `openai_small_model`, `openai_prices`, `ollama_host`, `ollama_model`, `ollama_num_ctx`, `playbooks_dir`, `audit_concurrency`; özellik `db_path`
  - `tests/fakes.py`: `FakeLLM(handlers: dict[str, object] | None = None, unavailable: str | None = None)` (`calls: list[tuple[str, str, str]]` = şema adı, katman, user prompt; `count(schema_name) -> int`), `sequence(*values)`

- [ ] **Step 1: Dal aç ve bağımlılıkları ekle**

```bash
git checkout -b plan-2-llm-audit-qa
```

`pyproject.toml` içindeki `dependencies` listesini şu hale getir:

```toml
dependencies = [
    "pymupdf>=1.24",
    "qdrant-client>=1.12",
    "fastembed>=0.4",
    "sentence-transformers>=4.0",
    "openai>=3.0",
    "ollama>=0.6",
    "langgraph>=1.0",
    "pydantic>=2.7",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]
```

`.gitignore` sonunda `.env` satırı yoksa ekle (kullanıcının anahtarı bu dosyada):

```
.env
```

Run: `.venv/Scripts/python -m pip install -e ".[dev]"`
Expected: kurulum hatasız biter.

Run: `git check-ignore .env`
Expected: `.env` yazar. Yazmazsa devam etme.

- [ ] **Step 2: Ayar testlerini güncelle**

`tests/test_config.py` dosyasını şununla değiştir:

```python
from pathlib import Path

from auditor.config import Settings

ENV_NAMES = (
    "AUDITOR_DATA_DIR", "QDRANT_URL", "AUDITOR_COLLECTION", "EMBED_MODEL", "RERANK_MODEL",
    "AUDITOR_DEVICE", "AUDITOR_PROVIDER", "OPENAI_EVAL_MODEL", "OPENAI_SMALL_MODEL",
    "OPENAI_PRICES", "OLLAMA_HOST", "OLLAMA_MODEL", "OLLAMA_NUM_CTX", "AUDITOR_PLAYBOOKS",
    "AUDIT_CONCURRENCY",
)


def test_defaults(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert s.data_dir == Path("data")
    assert s.qdrant_url is None
    assert s.collection == "chunks"
    assert s.embed_model == "BAAI/bge-m3"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert s.device is None
    assert s.provider == "openai"
    assert s.openai_eval_model is None
    assert s.openai_small_model is None
    assert s.openai_prices == ""
    assert s.ollama_host == "http://localhost:11434"
    assert s.ollama_model == "qwen3:8b"
    assert s.ollama_num_ctx == 16384
    assert s.playbooks_dir == Path("playbooks")
    assert s.audit_concurrency == 4
    assert s.db_path == Path("data") / "auditor.db"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("AUDITOR_DATA_DIR", "D:/x")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("AUDITOR_DEVICE", "cpu")
    monkeypatch.setenv("AUDITOR_PROVIDER", "ollama")
    monkeypatch.setenv("OPENAI_EVAL_MODEL", "gpt-5.5")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setenv("AUDIT_CONCURRENCY", "2")
    s = Settings.from_env()
    assert s.data_dir == Path("D:/x")
    assert s.qdrant_url == "http://localhost:6333"
    assert s.device == "cpu"
    assert s.provider == "ollama"
    assert s.openai_eval_model == "gpt-5.5"
    assert s.ollama_model == "llama3.1:8b"
    assert s.audit_concurrency == 2
    assert s.db_path == Path("D:/x") / "auditor.db"
```

- [ ] **Step 3: LLM arayüzü testini yaz**

`tests/test_llm_base.py`:

```python
import pytest
from fakes import FakeLLM, sequence
from pydantic import BaseModel

from auditor.llm.base import LLMError, Usage, complete_with_retry, models_label


class Answer(BaseModel):
    text: str


def test_usage_adds_up():
    assert Usage(10, 2, 0.5) + Usage(5, 1, 0.25) == Usage(15, 3, 0.75)


def test_retry_recovers_from_one_failure():
    llm = FakeLLM({"Answer": sequence(LLMError("bad json"), Answer(text="ok"))})
    result = complete_with_retry(llm, "sys", "user", Answer, "small")
    assert result.value.text == "ok"
    assert result.model == "fake-small"
    assert llm.count("Answer") == 2


def test_retry_gives_up_after_two_attempts():
    llm = FakeLLM({"Answer": LLMError("down")})
    with pytest.raises(LLMError, match="down"):
        complete_with_retry(llm, "sys", "user", Answer, "eval")
    assert llm.count("Answer") == 2


def test_other_exceptions_are_not_retried():
    llm = FakeLLM({"Answer": RuntimeError("bug")})
    with pytest.raises(RuntimeError):
        complete_with_retry(llm, "sys", "user", Answer, "eval")
    assert llm.count("Answer") == 1


def test_missing_fake_handler_is_an_llm_error():
    with pytest.raises(LLMError, match="Answer"):
        FakeLLM().complete("sys", "user", Answer, "eval")


def test_models_label():
    assert models_label(FakeLLM()) == "fake-eval+fake-small"
```

- [ ] **Step 4: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_config.py tests/test_llm_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.llm'` ve `Settings` alan hataları.

- [ ] **Step 5: Ayarları yaz**

`src/auditor/config.py`:

```python
import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    qdrant_url: str | None
    collection: str
    embed_model: str
    rerank_model: str
    device: str | None
    provider: str
    openai_eval_model: str | None
    openai_small_model: str | None
    openai_prices: str
    ollama_host: str
    ollama_model: str
    ollama_num_ctx: int
    playbooks_dir: Path
    audit_concurrency: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "auditor.db"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("AUDITOR_DATA_DIR", "data")),
            qdrant_url=os.environ.get("QDRANT_URL") or None,
            collection=os.environ.get("AUDITOR_COLLECTION", "chunks"),
            embed_model=os.environ.get("EMBED_MODEL", "BAAI/bge-m3"),
            rerank_model=os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
            device=os.environ.get("AUDITOR_DEVICE") or None,
            provider=os.environ.get("AUDITOR_PROVIDER", "openai"),
            openai_eval_model=os.environ.get("OPENAI_EVAL_MODEL") or None,
            openai_small_model=os.environ.get("OPENAI_SMALL_MODEL") or None,
            openai_prices=os.environ.get("OPENAI_PRICES", ""),
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "qwen3:8b"),
            ollama_num_ctx=_int("OLLAMA_NUM_CTX", 16384),
            playbooks_dir=Path(os.environ.get("AUDITOR_PLAYBOOKS", "playbooks")),
            audit_concurrency=_int("AUDIT_CONCURRENCY", 4),
        )
```

`qwen3:8b` geçici varsayılandır; Task 15'te aday karşılaştırmasıyla kesinleşir.

- [ ] **Step 6: LLM arayüzünü yaz**

`src/auditor/llm/__init__.py` boş dosya.

`src/auditor/llm/base.py`:

```python
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel

Tier = Literal["eval", "small"]
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """An LLM call failed or returned output that does not fit the schema."""


class ProviderUnavailableError(Exception):
    """The provider cannot be used at all: missing key, server down, model not pulled."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
        )


@dataclass
class LLMResult(Generic[T]):
    value: T
    model: str
    usage: Usage


class LLMProvider(Protocol):
    name: str

    def model_for(self, tier: Tier) -> str: ...

    def check_available(self) -> None: ...

    def complete(self, system: str, user: str, schema: type[T], tier: Tier) -> LLMResult[T]: ...


def complete_with_retry(provider: LLMProvider, system: str, user: str, schema: type[T],
                        tier: Tier, attempts: int = 2) -> LLMResult[T]:
    error: LLMError | None = None
    for _ in range(attempts):
        try:
            return provider.complete(system, user, schema, tier)
        except LLMError as exc:
            error = exc
    assert error is not None
    raise error


def models_label(provider: LLMProvider) -> str:
    eval_model, small_model = provider.model_for("eval"), provider.model_for("small")
    return eval_model if eval_model == small_model else f"{eval_model}+{small_model}"
```

- [ ] **Step 7: Sahte LLM'i ekle**

`tests/fakes.py` dosyasının en üstündeki import'ları şu hale getir:

```python
import math
import re
import threading
import zlib

from auditor.index.store import SparseVec
from auditor.llm.base import LLMError, LLMResult, ProviderUnavailableError, Usage
```

Dosyanın sonuna ekle:

```python
class FakeLLM:
    """Answers by schema name. A handler is a fixed value, an exception to raise,
    or a callable taking the user prompt and returning either."""

    name = "fake"

    def __init__(self, handlers: dict | None = None, unavailable: str | None = None):
        self.handlers = dict(handlers or {})
        self.unavailable = unavailable
        self.calls: list[tuple[str, str, str]] = []
        self._lock = threading.Lock()

    def model_for(self, tier):
        return f"fake-{tier}"

    def check_available(self):
        if self.unavailable:
            raise ProviderUnavailableError(self.unavailable)

    def complete(self, system, user, schema, tier):
        with self._lock:
            self.calls.append((schema.__name__, tier, user))
        handler = self.handlers.get(schema.__name__)
        if handler is None:
            raise LLMError(f"no fake response for {schema.__name__}")
        value = handler(user) if callable(handler) else handler
        if isinstance(value, Exception):
            raise value
        return LLMResult(value, self.model_for(tier), Usage(100, 20, 0.01))

    def count(self, schema_name: str) -> int:
        return sum(1 for name, _, _ in self.calls if name == schema_name)


def sequence(*values):
    """Handler returning the values in order, then repeating the last one."""
    items = list(values)
    lock = threading.Lock()

    def next_value(_user):
        with lock:
            return items.pop(0) if len(items) > 1 else items[0]

    return next_value
```

- [ ] **Step 8: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest -v`
Expected: tüm testler geçer (Plan 1 testleri dahil), `3 deselected`.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore src/auditor/config.py src/auditor/llm tests/test_config.py tests/test_llm_base.py tests/fakes.py
git commit -m "feat: LLM provider interface, retry helper and settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: OpenAI sağlayıcısı

**Files:**
- Create: `src/auditor/llm/openai_provider.py`, `tests/test_openai_provider.py`

**Interfaces:**
- Consumes: `LLMError`, `LLMResult`, `ProviderUnavailableError`, `Usage`, `Tier` (Task 1); `Settings` (Task 1)
- Produces:
  - `pick_models(model_ids: list[str]) -> tuple[str, str]` — (`eval`, `small`); `gpt-<major>[.<minor>]` en yenisi ve `gpt-<major>[.<minor>]-mini` en yenisi
  - `parse_prices(raw: str) -> dict[str, tuple[float, float]]` — `"model=in/out,..."`, USD / 1M token
  - `OpenAIProvider(client, eval_model: str, small_model: str, prices: dict | None = None)`, `name = "openai"`, `OpenAIProvider.from_settings(settings) -> OpenAIProvider`

- [ ] **Step 1: Testi yaz**

`tests/test_openai_provider.py`:

```python
from dataclasses import replace
from types import SimpleNamespace

import openai
import pytest
from pydantic import BaseModel

from auditor.config import Settings
from auditor.llm import openai_provider
from auditor.llm.base import LLMError, ProviderUnavailableError
from auditor.llm.openai_provider import OpenAIProvider, parse_prices, pick_models

ACCOUNT_MODELS = [
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-5", "gpt-5-mini", "gpt-5.4",
    "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5", "gpt-5.5-pro", "gpt-5.5-2026-04-23",
    "gpt-6-sol", "gpt-6.1-sol", "gpt-image-2", "gpt-realtime-2.1-mini", "whisper-1",
]


class Verdict(BaseModel):
    ok: bool


class FakeCompletions:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _client(outcome=None, models=ACCOUNT_MODELS):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(outcome)),
        models=SimpleNamespace(list=lambda: [SimpleNamespace(id=m) for m in models]),
    )


def _response(parsed, refusal=None, prompt_tokens=1000, completion_tokens=200):
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _settings(**overrides):
    return replace(Settings.from_env(), **overrides)


def test_pick_models_takes_newest_numbered_and_mini():
    assert pick_models(ACCOUNT_MODELS) == ("gpt-5.5", "gpt-5.4-mini")


def test_pick_models_fails_without_candidates():
    with pytest.raises(ProviderUnavailableError, match="OPENAI_EVAL_MODEL"):
        pick_models(["gpt-image-2", "whisper-1"])


def test_parse_prices():
    assert parse_prices("gpt-5.5=1.25/10, gpt-5.4-mini=0.25/2") == {
        "gpt-5.5": (1.25, 10.0),
        "gpt-5.4-mini": (0.25, 2.0),
    }
    assert parse_prices("") == {}
    with pytest.raises(ValueError, match="model=in/out"):
        parse_prices("gpt-5.5:1.25")


def test_complete_returns_value_usage_and_cost():
    client = _client(_response(Verdict(ok=True)))
    provider = OpenAIProvider(client, "gpt-5.5", "gpt-5.4-mini", {"gpt-5.4-mini": (0.25, 2.0)})
    result = provider.complete("system text", "user text", Verdict, "small")
    assert result.value == Verdict(ok=True)
    assert result.model == "gpt-5.4-mini"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 200)
    assert result.usage.cost_usd == pytest.approx(0.00065)
    kwargs = client.chat.completions.kwargs
    assert kwargs["model"] == "gpt-5.4-mini"
    assert kwargs["response_format"] is Verdict
    assert kwargs["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]


def test_eval_tier_uses_eval_model_and_unknown_price_costs_zero():
    client = _client(_response(Verdict(ok=False)))
    provider = OpenAIProvider(client, "gpt-5.5", "gpt-5.4-mini")
    result = provider.complete("s", "u", Verdict, "eval")
    assert client.chat.completions.kwargs["model"] == "gpt-5.5"
    assert result.usage.cost_usd == 0.0


def test_refusal_is_an_llm_error():
    provider = OpenAIProvider(_client(_response(None, refusal="I can't help")), "gpt-5.5", "gpt-5.4-mini")
    with pytest.raises(LLMError, match="I can't help"):
        provider.complete("s", "u", Verdict, "eval")


def test_sdk_error_is_an_llm_error():
    provider = OpenAIProvider(_client(openai.OpenAIError("rate limited")), "gpt-5.5", "gpt-5.4-mini")
    with pytest.raises(LLMError, match="rate limited"):
        provider.complete("s", "u", Verdict, "eval")


def test_from_settings_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailableError, match="OPENAI_API_KEY"):
        OpenAIProvider.from_settings(_settings())


def test_from_settings_picks_models_from_account(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(openai_provider, "OpenAI", lambda **kwargs: _client())
    provider = OpenAIProvider.from_settings(
        _settings(openai_eval_model=None, openai_small_model=None)
    )
    assert (provider.model_for("eval"), provider.model_for("small")) == ("gpt-5.5", "gpt-5.4-mini")


def test_from_settings_keeps_configured_models(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(openai_provider, "OpenAI", lambda **kwargs: _client(models=[]))
    provider = OpenAIProvider.from_settings(
        _settings(openai_eval_model="gpt-5.4", openai_small_model="gpt-5.4-nano", openai_prices="gpt-5.4=1/8")
    )
    assert (provider.model_for("eval"), provider.model_for("small")) == ("gpt-5.4", "gpt-5.4-nano")
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_openai_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.llm.openai_provider'`

- [ ] **Step 3: Sağlayıcıyı yaz**

`src/auditor/llm/openai_provider.py`:

```python
import os
import re

import openai
from openai import OpenAI
from pydantic import ValidationError

from auditor.config import Settings
from auditor.llm.base import LLMError, LLMResult, ProviderUnavailableError, T, Tier, Usage

_EVAL = re.compile(r"^gpt-(\d+)(?:\.(\d+))?$")
_SMALL = re.compile(r"^gpt-(\d+)(?:\.(\d+))?-mini$")


def _newest(model_ids: list[str], pattern: re.Pattern) -> str | None:
    best: tuple[tuple[int, int], str] | None = None
    for model_id in model_ids:
        match = pattern.match(model_id)
        if match:
            version = (int(match.group(1)), int(match.group(2) or 0))
            if best is None or version > best[0]:
                best = (version, model_id)
    return best[1] if best else None


def pick_models(model_ids: list[str]) -> tuple[str, str]:
    eval_model, small_model = _newest(model_ids, _EVAL), _newest(model_ids, _SMALL)
    if not eval_model or not small_model:
        raise ProviderUnavailableError(
            "could not pick OpenAI models from the account; "
            "set OPENAI_EVAL_MODEL and OPENAI_SMALL_MODEL"
        )
    return eval_model, small_model


def parse_prices(raw: str) -> dict[str, tuple[float, float]]:
    """'gpt-5.5=1.25/10,gpt-5.4-mini=0.25/2' -> USD per 1M input and output tokens."""
    prices: dict[str, tuple[float, float]] = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        try:
            model, pair = item.split("=", 1)
            price_in, price_out = pair.split("/", 1)
            prices[model.strip()] = (float(price_in), float(price_out))
        except ValueError as exc:
            raise ValueError(f"OPENAI_PRICES entry must look like model=in/out, got {item!r}") from exc
    return prices


class OpenAIProvider:
    name = "openai"

    def __init__(self, client, eval_model: str, small_model: str,
                 prices: dict[str, tuple[float, float]] | None = None):
        self._client = client
        self._eval = eval_model
        self._small = small_model
        self._prices = prices or {}

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAIProvider":
        if not os.environ.get("OPENAI_API_KEY"):
            raise ProviderUnavailableError("OPENAI_API_KEY is not set")
        client = OpenAI(timeout=120, max_retries=2)
        eval_model, small_model = settings.openai_eval_model, settings.openai_small_model
        if not eval_model or not small_model:
            try:
                model_ids = [model.id for model in client.models.list()]
            except openai.OpenAIError as exc:
                raise ProviderUnavailableError(f"cannot list OpenAI models: {exc}") from exc
            picked_eval, picked_small = pick_models(model_ids)
            eval_model, small_model = eval_model or picked_eval, small_model or picked_small
        return cls(client, eval_model, small_model, parse_prices(settings.openai_prices))

    def model_for(self, tier: Tier) -> str:
        return self._eval if tier == "eval" else self._small

    def check_available(self) -> None:
        # The key and the model names are checked when the provider is built.
        return None

    def complete(self, system: str, user: str, schema: type[T], tier: Tier) -> LLMResult[T]:
        model = self.model_for(tier)
        try:
            response = self._client.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
            )
        except (openai.OpenAIError, ValidationError) as exc:
            raise LLMError(f"{model}: {exc}") from exc
        message = response.choices[0].message
        if message.parsed is None:
            raise LLMError(f"{model}: no structured output ({message.refusal or 'empty response'})")
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        price_in, price_out = self._prices.get(model, (0.0, 0.0))
        cost = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
        return LLMResult(message.parsed, model, Usage(prompt_tokens, completion_tokens, cost))
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_openai_provider.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/llm/openai_provider.py tests/test_openai_provider.py
git commit -m "feat: OpenAI provider with structured outputs and model picking

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Ollama sağlayıcısı ve sağlayıcı fabrikası

**Files:**
- Create: `src/auditor/llm/ollama_provider.py`, `src/auditor/llm/factory.py`, `tests/test_ollama_provider.py`, `tests/test_llm_slow.py`

**Interfaces:**
- Consumes: Task 1 tipleri; `OpenAIProvider.from_settings` (Task 2)
- Produces:
  - `OllamaProvider(client, model: str, host: str, num_ctx: int = 16384)`, `name = "ollama"`, `OllamaProvider.from_settings(settings)`
  - `PROVIDERS = ("openai", "ollama")`
  - `build_provider(name: str, settings: Settings) -> LLMProvider` (bilinmeyen ad: `ValueError`)
  - `cached_provider_factory(settings) -> Callable[[str], LLMProvider]` (her ad için bir kez kurar)

- [ ] **Step 1: Testi yaz**

`tests/test_ollama_provider.py`:

```python
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from auditor.config import Settings
from auditor.llm.base import LLMError, ProviderUnavailableError
from auditor.llm.factory import build_provider, cached_provider_factory
from auditor.llm.ollama_provider import OllamaProvider


class Verdict(BaseModel):
    ok: bool


class FakeOllamaClient:
    def __init__(self, models=("qwen3:8b",), content='{"ok": true}', error=None):
        self.models = models
        self.content = content
        self.error = error
        self.kwargs = None

    def list(self):
        if self.error:
            raise self.error
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self.models])

    def chat(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(
            message=SimpleNamespace(content=self.content), prompt_eval_count=50, eval_count=7
        )


def _provider(**kwargs):
    client = FakeOllamaClient(**kwargs)
    return OllamaProvider(client, "qwen3:8b", "http://localhost:11434", num_ctx=8192), client


def test_complete_parses_json_with_schema_constraint():
    provider, client = _provider()
    result = provider.complete("system text", "user text", Verdict, "eval")
    assert result.value == Verdict(ok=True)
    assert result.model == "qwen3:8b"
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cost_usd) == (50, 7, 0.0)
    assert client.kwargs["model"] == "qwen3:8b"
    assert client.kwargs["format"] == Verdict.model_json_schema()
    assert client.kwargs["options"] == {"temperature": 0, "num_ctx": 8192}
    assert client.kwargs["messages"][0] == {"role": "system", "content": "system text"}


def test_both_tiers_use_the_same_model():
    provider, _ = _provider()
    assert provider.model_for("eval") == provider.model_for("small") == "qwen3:8b"


@pytest.mark.parametrize("content", ["not json", '{"ok": "maybe"}', "{}"])
def test_bad_output_is_an_llm_error(content):
    provider, _ = _provider(content=content)
    with pytest.raises(LLMError):
        provider.complete("s", "u", Verdict, "eval")


def test_connection_failure_during_call_is_an_llm_error():
    provider, _ = _provider(error=ConnectionError("Failed to connect to Ollama"))
    with pytest.raises(LLMError, match="Failed to connect"):
        provider.complete("s", "u", Verdict, "eval")


def test_check_available_reports_unreachable_server():
    provider, _ = _provider(error=ConnectionError("Failed to connect to Ollama"))
    with pytest.raises(ProviderUnavailableError, match="not reachable at http://localhost:11434"):
        provider.check_available()


def test_check_available_reports_missing_model():
    provider, _ = _provider(models=("llama3.1:8b",))
    with pytest.raises(ProviderUnavailableError, match="ollama pull qwen3:8b"):
        provider.check_available()


def test_check_available_accepts_latest_tag():
    client = FakeOllamaClient(models=("mistral:latest",))
    OllamaProvider(client, "mistral", "http://h").check_available()


def test_factory_builds_ollama_and_rejects_unknown_names():
    settings = replace(Settings.from_env(), ollama_model="llama3.1:8b")
    provider = build_provider("ollama", settings)
    assert isinstance(provider, OllamaProvider)
    assert provider.model_for("eval") == "llama3.1:8b"
    with pytest.raises(ValueError, match="openai or ollama"):
        build_provider("anthropic", settings)


def test_factory_reports_missing_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailableError, match="OPENAI_API_KEY"):
        build_provider("openai", Settings.from_env())


def test_cached_factory_builds_each_provider_once():
    get = cached_provider_factory(Settings.from_env())
    assert get("ollama") is get("ollama")
```

`tests/test_llm_slow.py`:

```python
import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from auditor.config import Settings
from auditor.llm.base import ProviderUnavailableError
from auditor.llm.factory import build_provider

pytestmark = pytest.mark.slow


class Capital(BaseModel):
    city: str


@pytest.mark.parametrize("name", ["openai", "ollama"])
def test_real_provider_returns_schema_output(name):
    load_dotenv()
    try:
        provider = build_provider(name, Settings.from_env())
        provider.check_available()
    except ProviderUnavailableError as exc:
        pytest.skip(str(exc))
    result = provider.complete(
        "Answer with the requested JSON.", "What is the capital of France?", Capital, "small"
    )
    assert "paris" in result.value.city.lower()
    assert result.usage.input_tokens > 0
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_ollama_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.llm.factory'`

- [ ] **Step 3: Ollama sağlayıcısını yaz**

`src/auditor/llm/ollama_provider.py`:

```python
import httpx
import ollama
from pydantic import ValidationError

from auditor.config import Settings
from auditor.llm.base import LLMError, LLMResult, ProviderUnavailableError, T, Tier, Usage

_CALL_ERRORS = (ConnectionError, httpx.HTTPError, ollama.ResponseError)


class OllamaProvider:
    name = "ollama"

    def __init__(self, client, model: str, host: str, num_ctx: int = 16384):
        self._client = client
        self._model = model
        self._host = host
        self._num_ctx = num_ctx

    @classmethod
    def from_settings(cls, settings: Settings) -> "OllamaProvider":
        client = ollama.Client(host=settings.ollama_host, timeout=600)
        return cls(client, settings.ollama_model, settings.ollama_host, settings.ollama_num_ctx)

    def model_for(self, tier: Tier) -> str:
        return self._model

    def check_available(self) -> None:
        try:
            listed = self._client.list()
        except _CALL_ERRORS as exc:
            raise ProviderUnavailableError(f"Ollama is not reachable at {self._host}: {exc}") from exc
        names = {model.model for model in listed.models}
        if self._model not in names and f"{self._model}:latest" not in names:
            raise ProviderUnavailableError(
                f"Ollama model {self._model!r} is not pulled; run: ollama pull {self._model}"
            )

    def complete(self, system: str, user: str, schema: type[T], tier: Tier) -> LLMResult[T]:
        try:
            response = self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                format=schema.model_json_schema(),
                options={"temperature": 0, "num_ctx": self._num_ctx},
            )
            value = schema.model_validate_json(response.message.content or "")
        except (*_CALL_ERRORS, ValidationError) as exc:
            raise LLMError(f"{self._model}: {exc}") from exc
        usage = Usage(response.prompt_eval_count or 0, response.eval_count or 0, 0.0)
        return LLMResult(value, self._model, usage)
```

- [ ] **Step 4: Fabrikayı yaz**

`src/auditor/llm/factory.py`:

```python
import threading
from typing import Callable

from auditor.config import Settings
from auditor.llm.base import LLMProvider
from auditor.llm.ollama_provider import OllamaProvider
from auditor.llm.openai_provider import OpenAIProvider

PROVIDERS = ("openai", "ollama")


def build_provider(name: str, settings: Settings) -> LLMProvider:
    if name == "openai":
        return OpenAIProvider.from_settings(settings)
    if name == "ollama":
        return OllamaProvider.from_settings(settings)
    raise ValueError(f"unknown provider {name!r}; choose openai or ollama")


def cached_provider_factory(settings: Settings) -> Callable[[str], LLMProvider]:
    providers: dict[str, LLMProvider] = {}
    lock = threading.Lock()

    def get(name: str) -> LLMProvider:
        with lock:
            if name not in providers:
                providers[name] = build_provider(name, settings)
            return providers[name]

    return get
```

- [ ] **Step 5: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_ollama_provider.py -v`
Expected: 12 passed

- [ ] **Step 6: Gerçek OpenAI ile hızlı kontrol**

Run: `.venv/Scripts/python -m pytest tests/test_llm_slow.py -m slow -v`
Expected: `openai` geçer (`.env` içindeki anahtarla), `ollama` "not reachable" ile SKIPPED. `openai` başarısız olursa hata mesajını kullanıcıya raporla; anahtarı yazdırma.

- [ ] **Step 7: Commit**

```bash
git add src/auditor/llm/ollama_provider.py src/auditor/llm/factory.py tests/test_ollama_provider.py tests/test_llm_slow.py
git commit -m "feat: Ollama provider and provider factory

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Alıntı doğrulayıcı

**Files:**
- Create: `src/auditor/audit/__init__.py`, `src/auditor/audit/citations.py`, `tests/test_citations.py`

**Interfaces:**
- Consumes: `ParsedDocument`, `parse_text`, `parse_pdf` (`auditor.ingestion.parser`); `PageBox` (`auditor.ingestion.chunker`); `ParentPassage` (`auditor.retrieval.pipeline`); `count_tokens`
- Produces:
  - `MIN_QUOTE_TOKENS = 4`
  - `@dataclass Citation(quote: str, document_id: str, char_start: int, char_end: int, page: int | None, section_path: str, bboxes: list[PageBox])`, `Citation.to_dict() -> dict` (`bboxes` → `[{"page": int, "bbox": [x0, y0, x1, y1]}]`)
  - `verify_quotes(doc: ParsedDocument, quotes: list[str], passages: list[ParentPassage]) -> list[Citation]` — yalnızca `doc` içinde bulunan alıntılar döner; `quote` alanı belgedeki özgün metindir

Normalizasyon: tırnak karakterleri (`‘’‚‛″“”„‟` ve bölünmez boşluk) düz karşılıklarına çevrilir, boşluk dizileri tek boşluğa iner; eşleşme büyük/küçük harfe duyarlıdır. Alıntının başındaki ve sonundaki tırnak, nokta ve `…` atılır. Alıntı birden çok yerde geçiyorsa verilen pasajların içindeki ilk geçiş seçilir. Bbox satır düzeyindedir: alıntının değdiği her satırın kutusu.

- [ ] **Step 1: Testi yaz**

`tests/test_citations.py`:

```python
from auditor.audit.citations import verify_quotes
from auditor.ingestion.parser import parse_pdf, parse_text
from auditor.retrieval.pipeline import ParentPassage


def _passage(doc, start_marker, section_path, parent_id="p1"):
    start = doc.text.index(start_marker)
    return ParentPassage(parent_id, doc.document_id, doc.text[start:], start, len(doc.text), section_path, [])


def test_exact_quote_is_verified_with_offsets(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    quote = "Either party may terminate this Agreement upon thirty (30) days written notice."
    [citation] = verify_quotes(doc, [quote], [])
    assert doc.text[citation.char_start:citation.char_end] == citation.quote
    assert citation.quote == "Either party may terminate this Agreement upon thirty (30) days written notice"
    assert citation.document_id == doc.document_id
    assert citation.page is None and citation.bboxes == []


def test_whitespace_line_breaks_and_curly_quotes_are_normalized(sample_contract):
    doc = parse_text("The total liability\nshall not  exceed the fees.\n" + sample_contract, "x.txt")
    [first, second] = verify_quotes(
        doc,
        ["The total liability shall not exceed",
         "1.1 \u201cServices\u201d means the consulting   services"],
        [],
    )
    assert first.quote == "The total liability\nshall not  exceed"
    assert second.quote == '1.1 "Services" means the consulting services'


def test_wrapping_quotes_and_ellipsis_are_ignored(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    [citation] = verify_quotes(doc, ['"\u2026governed by the laws of the State of New York."'], [])
    assert citation.quote == "governed by the laws of the State of New York"


def test_fabricated_quote_is_dropped(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    assert verify_quotes(doc, ["Liability is unlimited for all claims of any kind."], []) == []


def test_short_generic_quote_is_dropped(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    assert verify_quotes(doc, ["this Agreement", "the fees paid"], []) == []


def test_quote_from_another_document_is_dropped(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    other = parse_text("1. Confidentiality\nEach party shall keep the other party's information confidential.", "nda.txt")
    passages = [_passage(other, "1. Confidentiality", "1")]
    quote = "Each party shall keep the other party's information confidential."
    assert verify_quotes(doc, [quote], passages) == []
    assert len(verify_quotes(other, [quote], passages)) == 1


def test_repeated_text_prefers_the_given_passage():
    text = ("1. Payment\nInvoices are payable within thirty days of receipt.\n"
            "2. Late Payment\nInvoices are payable within thirty days of receipt.")
    doc = parse_text(text, "p.txt")
    passage = _passage(doc, "2. Late Payment", "2")
    [citation] = verify_quotes(doc, ["Invoices are payable within thirty days of receipt."], [passage])
    assert citation.char_start > doc.text.index("2. Late Payment")
    assert citation.section_path == "2"


def test_duplicate_quotes_are_cited_once(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    quote = "Neither party shall be liable for indirect or consequential damages."
    assert len(verify_quotes(doc, [quote, quote], [])) == 1


def test_pdf_quote_gets_page_and_line_boxes(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "c.pdf", [
        [("1. Definitions", 11), ("Services means the consulting services.", 11)],
        [("2. Liability", 11), ("The total liability shall not exceed the fees paid.", 11)],
    ])
    doc = parse_pdf(path)
    [citation] = verify_quotes(doc, ["The total liability shall not exceed the fees paid."], [])
    assert citation.page == 2
    assert [box.page for box in citation.bboxes] == [2]
    data = citation.to_dict()
    assert data["page"] == 2
    assert data["bboxes"][0]["page"] == 2
    assert len(data["bboxes"][0]["bbox"]) == 4
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_citations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.audit'`

- [ ] **Step 3: Doğrulayıcıyı yaz**

`src/auditor/audit/__init__.py` boş dosya.

`src/auditor/audit/citations.py`:

```python
from dataclasses import dataclass

from auditor.ingestion.chunker import PageBox
from auditor.ingestion.parser import ParsedDocument
from auditor.retrieval.pipeline import ParentPassage
from auditor.tokens import count_tokens

MIN_QUOTE_TOKENS = 4

_UNIFY = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
    "\u00a0": " ",
})
_EDGE_CHARS = " \"'.\u2026"


@dataclass
class Citation:
    quote: str
    document_id: str
    char_start: int
    char_end: int
    page: int | None
    section_path: str
    bboxes: list[PageBox]

    def to_dict(self) -> dict:
        return {
            "quote": self.quote,
            "document_id": self.document_id,
            "page": self.page,
            "section_path": self.section_path,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "bboxes": [{"page": box.page, "bbox": list(box.bbox)} for box in self.bboxes],
        }


def _normalize(text: str) -> tuple[str, list[int]]:
    """Unify quote characters and collapse whitespace runs to one space.
    Returns the normalized text and the source index of each of its characters."""
    chars: list[str] = []
    index: list[int] = []
    previous_space = False
    for i, ch in enumerate(text.translate(_UNIFY)):
        if ch.isspace():
            if previous_space:
                continue
            ch, previous_space = " ", True
        else:
            previous_space = False
        chars.append(ch)
        index.append(i)
    return "".join(chars), index


def _locate(haystack: str, index: list[int], quote: str,
            prefer: list[tuple[int, int]]) -> tuple[int, int] | None:
    needle = _normalize(quote)[0].strip(_EDGE_CHARS)
    if count_tokens(needle) < MIN_QUOTE_TOKENS:
        return None
    spans = []
    pos = haystack.find(needle)
    while pos != -1:
        spans.append((index[pos], index[pos + len(needle) - 1] + 1))
        pos = haystack.find(needle, pos + 1)
    for start, end in spans:
        if any(a <= start and end <= b for a, b in prefer):
            return start, end
    return spans[0] if spans else None


def verify_quotes(doc: ParsedDocument, quotes: list[str],
                  passages: list[ParentPassage]) -> list[Citation]:
    haystack, index = _normalize(doc.text)
    own = [p for p in passages if p.document_id == doc.document_id]
    ranges = [(p.char_start, p.char_end) for p in own]
    citations: list[Citation] = []
    seen: set[tuple[int, int]] = set()
    for quote in quotes:
        span = _locate(haystack, index, quote, ranges)
        if span is None or span in seen:
            continue
        seen.add(span)
        start, end = span
        touched = [line for line in doc.lines
                   if line.page is not None and line.char_start < end and start < line.char_end]
        section = next((p.section_path for p in own if p.char_start <= start < p.char_end), "")
        citations.append(Citation(
            quote=doc.text[start:end],
            document_id=doc.document_id,
            char_start=start,
            char_end=end,
            page=touched[0].page if touched else None,
            section_path=section,
            bboxes=[PageBox(line.page, line.bbox) for line in touched if line.bbox is not None],
        ))
    return citations
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_citations.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/audit/__init__.py src/auditor/audit/citations.py tests/test_citations.py
git commit -m "feat: quote verifier with normalization and page/bbox mapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Playbook yükleme ve başlangıç playbook'u

**Files:**
- Create: `src/auditor/audit/playbook.py`, `playbooks/commercial_contract.yaml`, `tests/test_playbook.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `RuleType = Literal["must_exist", "must_not_exist", "condition"]`, `Severity = Literal["low", "medium", "high"]`
  - `Rule` (pydantic, frozen): `id`, `title`, `type`, `severity`, `queries: list[str]`, `criteria`
  - `Playbook` (pydantic, frozen): `name`, `rules: list[Rule]`
  - `@dataclass(frozen=True) LoadedPlaybook(key: str, playbook: Playbook, sha256: str)`
  - `class PlaybookError(Exception)`, `class PlaybookNotFound(PlaybookError)`
  - `load_playbook(path) -> LoadedPlaybook`, `list_playbooks(directory) -> list[str]`, `find_playbook(directory, key) -> LoadedPlaybook`
  - `tests/conftest.py`: `playbooks_dir` fixture (içinde `test_pb.yaml`: `liability_cap` must_exist high "Liability cap", `confidentiality` must_exist medium "Confidentiality")

- [ ] **Step 1: Test fixture'ını ekle**

`tests/conftest.py` sonuna ekle:

```python
TEST_PLAYBOOK = """name: Test playbook
rules:
  - id: liability_cap
    title: Liability cap
    type: must_exist
    severity: high
    queries: ["total liability fees"]
    criteria: "Total liability is capped at a stated amount or formula."
  - id: confidentiality
    title: Confidentiality
    type: must_exist
    severity: medium
    queries: ["confidential information disclosure"]
    criteria: "Each party must keep the other party's information confidential."
"""


@pytest.fixture
def playbooks_dir(tmp_path):
    directory = tmp_path / "playbooks"
    directory.mkdir()
    (directory / "test_pb.yaml").write_text(TEST_PLAYBOOK, encoding="utf-8")
    return directory
```

- [ ] **Step 2: Testi yaz**

`tests/test_playbook.py`:

```python
from pathlib import Path

import pytest

from auditor.audit.playbook import (
    PlaybookError,
    PlaybookNotFound,
    find_playbook,
    list_playbooks,
    load_playbook,
)

VALID = """name: Test playbook
rules:
  - id: liability_cap
    title: Liability cap
    type: must_exist
    severity: high
    queries: ["limitation of liability"]
    criteria: "Total liability is capped."
"""


def _write(tmp_path, text, name="pb.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _error(path) -> str:
    with pytest.raises(PlaybookError) as exc:
        load_playbook(path)
    return str(exc.value)


def test_load_valid(tmp_path):
    loaded = load_playbook(_write(tmp_path, VALID))
    assert loaded.key == "pb"
    assert loaded.playbook.name == "Test playbook"
    rule = loaded.playbook.rules[0]
    assert (rule.id, rule.type, rule.severity) == ("liability_cap", "must_exist", "high")
    assert rule.queries == ["limitation of liability"]
    assert len(loaded.sha256) == 64


def test_error_names_rule_and_field(tmp_path):
    message = _error(_write(tmp_path, VALID.replace("severity: high", "severity: critical")))
    assert "rule 'liability_cap' (rules[0])" in message
    assert "'severity'" in message
    assert message.startswith("pb.yaml:")


def test_missing_field(tmp_path):
    text = VALID.replace('    criteria: "Total liability is capped."\n', "")
    message = _error(_write(tmp_path, text))
    assert "'criteria'" in message
    assert "Field required" in message


def test_blank_query_is_rejected(tmp_path):
    message = _error(_write(tmp_path, VALID.replace('["limitation of liability"]', '["  "]')))
    assert "'queries'" in message


def test_duplicate_rule_ids(tmp_path):
    rules = VALID.split("rules:\n")[1]
    assert "duplicate rule id 'liability_cap'" in _error(_write(tmp_path, VALID + rules))


def test_invalid_yaml(tmp_path):
    assert "invalid YAML" in _error(_write(tmp_path, "name: [unclosed"))


def test_not_a_mapping(tmp_path):
    assert "mapping" in _error(_write(tmp_path, "- just a list"))


def test_find_and_list(tmp_path):
    _write(tmp_path, VALID, "b.yaml")
    _write(tmp_path, VALID, "a.yaml")
    _write(tmp_path, "notes", "notes.txt")
    assert list_playbooks(tmp_path) == ["a", "b"]
    assert find_playbook(tmp_path, "a").key == "a"
    with pytest.raises(PlaybookNotFound, match="available: a, b"):
        find_playbook(tmp_path, "missing")
    with pytest.raises(PlaybookNotFound):
        find_playbook(tmp_path, "../a")


def test_shipped_playbook_is_valid():
    path = Path(__file__).parents[1] / "playbooks" / "commercial_contract.yaml"
    loaded = load_playbook(path)
    assert len(loaded.playbook.rules) == 5
    assert {r.type for r in loaded.playbook.rules} == {"must_exist", "must_not_exist", "condition"}
```

- [ ] **Step 3: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_playbook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.audit.playbook'`

- [ ] **Step 4: Playbook modülünü yaz**

`src/auditor/audit/playbook.py`:

```python
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

RuleType = Literal["must_exist", "must_not_exist", "condition"]
Severity = Literal["low", "medium", "high"]

_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


class PlaybookError(Exception):
    pass


class PlaybookNotFound(PlaybookError):
    pass


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    type: RuleType
    severity: Severity
    queries: list[str] = Field(min_length=1)
    criteria: str = Field(min_length=1)

    @field_validator("queries")
    @classmethod
    def _no_blank_queries(cls, value: list[str]) -> list[str]:
        if any(not query.strip() for query in value):
            raise ValueError("queries must not contain blank entries")
        return value


class Playbook(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    rules: list[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> "Playbook":
        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ValueError(f"duplicate rule id {rule.id!r}")
            seen.add(rule.id)
        return self


@dataclass(frozen=True)
class LoadedPlaybook:
    key: str
    playbook: Playbook
    sha256: str


def _describe(raw: dict, error: dict) -> str:
    loc = error["loc"]
    if len(loc) >= 2 and loc[0] == "rules" and isinstance(loc[1], int):
        rules = raw.get("rules")
        entry = rules[loc[1]] if isinstance(rules, list) and loc[1] < len(rules) else None
        rule_id = entry.get("id") if isinstance(entry, dict) else None
        where = f"rule {rule_id!r} (rules[{loc[1]}])" if rule_id else f"rules[{loc[1]}]"
        field = ".".join(str(part) for part in loc[2:]) or "(rule)"
        return f"{where}: field {field!r}: {error['msg']}"
    field = ".".join(str(part) for part in loc) or "(playbook)"
    return f"field {field!r}: {error['msg']}"


def load_playbook(path: str | Path) -> LoadedPlaybook:
    path = Path(path)
    data = path.read_bytes()
    try:
        raw = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise PlaybookError(f"{path.name}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PlaybookError(f"{path.name}: playbook must be a mapping with 'name' and 'rules'")
    try:
        playbook = Playbook.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(_describe(raw, error) for error in exc.errors())
        raise PlaybookError(f"{path.name}: {details}") from exc
    return LoadedPlaybook(path.stem, playbook, hashlib.sha256(data).hexdigest())


def list_playbooks(directory: str | Path) -> list[str]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.yaml"))


def find_playbook(directory: str | Path, key: str) -> LoadedPlaybook:
    path = Path(directory) / f"{key}.yaml"
    if not _KEY.match(key) or not path.is_file():
        available = ", ".join(list_playbooks(directory)) or "none"
        raise PlaybookNotFound(f"playbook {key!r} not found; available: {available}")
    return load_playbook(path)
```

- [ ] **Step 5: Başlangıç playbook'unu yaz**

`playbooks/commercial_contract.yaml` (Plan 4 bunu CUAD madde türlerinden genişletir; bu beş kural Task 15'teki Ollama model karşılaştırmasında da kullanılır):

```yaml
name: Commercial contract
rules:
  - id: liability_cap
    title: Limitation of liability
    type: must_exist
    severity: high
    queries: ["limitation of liability", "liability cap aggregate amount"]
    criteria: "Total liability of a party is limited to a stated amount or a formula, such as fees paid in a period."
  - id: termination_notice
    title: Termination notice period
    type: condition
    severity: medium
    queries: ["termination notice period", "terminate this agreement upon written notice"]
    criteria: "If a party may terminate for convenience, it must give at least 30 days written notice."
  - id: governing_law
    title: Governing law
    type: must_exist
    severity: low
    queries: ["governing law", "governed by the laws of"]
    criteria: "The contract names the law or jurisdiction that governs it."
  - id: confidentiality
    title: Confidentiality
    type: must_exist
    severity: medium
    queries: ["confidential information", "non-disclosure obligations"]
    criteria: "Each party must keep the other party's confidential information secret and use it only for the contract."
  - id: unlimited_liability
    title: Unlimited liability
    type: must_not_exist
    severity: high
    queries: ["unlimited liability", "liability shall not be limited"]
    criteria: "A party's liability is unlimited or expressly excluded from any cap for all claims."
```

- [ ] **Step 6: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_playbook.py -v`
Expected: 9 passed

- [ ] **Step 7: Commit**

```bash
git add src/auditor/audit/playbook.py playbooks/commercial_contract.yaml tests/test_playbook.py tests/conftest.py
git commit -m "feat: playbook schema, loader and starter commercial playbook

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Durum tablosu ve risk puanı

**Files:**
- Create: `src/auditor/audit/scoring.py`, `tests/test_scoring.py`

**Interfaces:**
- Consumes: `RuleType`, `Severity` (Task 5)
- Produces:
  - `class Status(StrEnum)`: `COMPLIANT="uyumlu"`, `NON_COMPLIANT="uyumsuz"`, `MISSING="eksik"`, `UNCERTAIN="belirsiz"`, `ERROR="hata"`
  - `SEVERITY_WEIGHT`, `STATUS_MULTIPLIER`
  - `status_for(rule_type, clause_found: bool, matches_criteria: bool) -> Status`
  - `is_absence_verdict(rule_type, status) -> bool` — `eksik`, veya `must_not_exist` için `uyumlu`
  - `rule_risk(severity, status) -> float | None` (`hata` için `None`)
  - `risk_score(items: list[tuple[str, Status]]) -> float | None` — (önem, durum) çiftleri; sayılacak kural yoksa `None`; bir ondalığa yuvarlanır

- [ ] **Step 1: Testi yaz**

`tests/test_scoring.py`:

```python
import pytest

from auditor.audit.scoring import Status, is_absence_verdict, risk_score, rule_risk, status_for

S = Status


@pytest.mark.parametrize("rule_type, found, matches, expected", [
    ("must_exist", True, True, S.COMPLIANT),
    ("must_exist", True, False, S.NON_COMPLIANT),
    ("must_exist", False, False, S.MISSING),
    ("must_exist", False, True, S.MISSING),
    ("condition", True, True, S.COMPLIANT),
    ("condition", True, False, S.NON_COMPLIANT),
    ("condition", False, False, S.MISSING),
    ("must_not_exist", True, True, S.NON_COMPLIANT),
    ("must_not_exist", True, False, S.COMPLIANT),
    ("must_not_exist", False, False, S.COMPLIANT),
])
def test_status_table(rule_type, found, matches, expected):
    assert status_for(rule_type, found, matches) is expected


def test_status_values_are_the_spec_strings():
    assert [s.value for s in Status] == ["uyumlu", "uyumsuz", "eksik", "belirsiz", "hata"]


@pytest.mark.parametrize("rule_type, status, expected", [
    ("must_exist", S.MISSING, True),
    ("condition", S.MISSING, True),
    ("must_not_exist", S.COMPLIANT, True),
    ("must_exist", S.COMPLIANT, False),
    ("must_not_exist", S.NON_COMPLIANT, False),
    ("must_exist", S.UNCERTAIN, False),
])
def test_absence_verdict(rule_type, status, expected):
    assert is_absence_verdict(rule_type, status) is expected


def test_rule_risk():
    assert rule_risk("high", S.COMPLIANT) == 0.0
    assert rule_risk("medium", S.MISSING) == 2.0
    assert rule_risk("low", S.UNCERTAIN) == 0.5
    assert rule_risk("high", S.NON_COMPLIANT) == 3.0
    assert rule_risk("high", S.ERROR) is None


def test_risk_score_ignores_errors():
    items = [("high", S.COMPLIANT), ("medium", S.MISSING), ("low", S.UNCERTAIN), ("high", S.ERROR)]
    assert risk_score(items) == pytest.approx(41.7)


def test_risk_score_bounds():
    assert risk_score([("low", S.COMPLIANT)]) == 0.0
    assert risk_score([("low", S.NON_COMPLIANT), ("high", S.MISSING)]) == 100.0
    assert risk_score([("high", S.ERROR)]) is None
    assert risk_score([]) is None
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.audit.scoring'`

- [ ] **Step 3: Puanlamayı yaz**

`src/auditor/audit/scoring.py`:

```python
from enum import StrEnum


class Status(StrEnum):
    COMPLIANT = "uyumlu"
    NON_COMPLIANT = "uyumsuz"
    MISSING = "eksik"
    UNCERTAIN = "belirsiz"
    ERROR = "hata"


SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3}
STATUS_MULTIPLIER = {
    Status.COMPLIANT: 0.0,
    Status.UNCERTAIN: 0.5,
    Status.NON_COMPLIANT: 1.0,
    Status.MISSING: 1.0,
}


def status_for(rule_type: str, clause_found: bool, matches_criteria: bool) -> Status:
    if rule_type == "must_not_exist":
        return Status.NON_COMPLIANT if clause_found and matches_criteria else Status.COMPLIANT
    if not clause_found:
        return Status.MISSING
    return Status.COMPLIANT if matches_criteria else Status.NON_COMPLIANT


def is_absence_verdict(rule_type: str, status: Status | None) -> bool:
    if status is Status.MISSING:
        return True
    return rule_type == "must_not_exist" and status is Status.COMPLIANT


def rule_risk(severity: str, status: Status) -> float | None:
    if status is Status.ERROR:
        return None
    return SEVERITY_WEIGHT[severity] * STATUS_MULTIPLIER[status]


def risk_score(items: list[tuple[str, Status]]) -> float | None:
    counted = [(SEVERITY_WEIGHT[severity], STATUS_MULTIPLIER[status])
               for severity, status in items if status is not Status.ERROR]
    if not counted:
        return None
    total_weight = sum(weight for weight, _ in counted)
    return round(100 * sum(weight * mult for weight, mult in counted) / total_weight, 1)
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_scoring.py -v`
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/audit/scoring.py tests/test_scoring.py
git commit -m "feat: status table and risk score

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: SQLite kayıt deposu

**Files:**
- Create: `src/auditor/storage/db.py`, `tests/test_audit_db.py`

**Interfaces:**
- Consumes: — (rapor sözlüğünün `audit_id`, `document_id`, `playbook`, `provider`, `model`, `created_at`, `errors`, `findings[].rule_id` alanları)
- Produces:
  - `DECISIONS = ("accepted", "rejected")`
  - `class AuditNotFound(KeyError)`, `class FindingNotFound(KeyError)`
  - `AuditStore(path)`:
    - `save_audit(report: dict, trace: list[dict], cache_key: str) -> None`
    - `get_report(audit_id) -> dict | None` (bulgulara `review` eklenmiş)
    - `find_cached(cache_key) -> dict | None` (hatasız en yeni kayıt, `review` eklenmiş)
    - `get_trace(audit_id) -> list[dict] | None`
    - `set_review(audit_id, rule_id, decision, note="") -> dict` (`{"decision", "note", "updated_at"}`)
    - `list_audits(document_id: str | None = None) -> list[dict]` (`audit_id`, `document_id`, `playbook`, `provider`, `model`, `created_at`, `risk_score`; en yeni önce)

Bağlantı her işlemde açılıp kapanır; bu sayede farklı thread'lerden (Plan 3'teki API) güvenle kullanılır.

- [ ] **Step 1: Testi yaz**

`tests/test_audit_db.py`:

```python
import pytest

from auditor.storage.db import AuditNotFound, AuditStore, FindingNotFound


def _report(audit_id="a1", errors=None, created_at="2026-10-14T10:00:00+00:00", document_id="doc1"):
    return {
        "audit_id": audit_id,
        "document_id": document_id,
        "playbook": "pb",
        "provider": "fake",
        "model": "m",
        "created_at": created_at,
        "risk_score": 40.0,
        "cached": False,
        "findings": [
            {"rule_id": "r1", "status": "uyumlu", "review": None},
            {"rule_id": "r2", "status": "eksik", "review": None},
        ],
        "errors": errors or [],
        "totals": {},
    }


@pytest.fixture
def db(tmp_path):
    return AuditStore(tmp_path / "sub" / "auditor.db")


def test_save_and_get(db):
    db.save_audit(_report(), [{"node": "search"}], "key1")
    report = db.get_report("a1")
    assert report["risk_score"] == 40.0
    assert [f["review"] for f in report["findings"]] == [None, None]
    assert db.get_trace("a1") == [{"node": "search"}]
    assert db.get_report("missing") is None
    assert db.get_trace("missing") is None


def test_data_survives_a_new_store_instance(db, tmp_path):
    db.save_audit(_report(), [], "key1")
    assert AuditStore(tmp_path / "sub" / "auditor.db").get_report("a1")["audit_id"] == "a1"


def test_review_is_saved_updated_and_merged(db):
    db.save_audit(_report(), [], "key1")
    first = db.set_review("a1", "r2", "accepted", "looks right")
    assert first["decision"] == "accepted"
    db.set_review("a1", "r2", "rejected", "clause is in annex")
    findings = {f["rule_id"]: f for f in db.get_report("a1")["findings"]}
    assert findings["r1"]["review"] is None
    assert findings["r2"]["review"]["decision"] == "rejected"
    assert findings["r2"]["review"]["note"] == "clause is in annex"


def test_review_errors(db):
    db.save_audit(_report(), [], "key1")
    with pytest.raises(AuditNotFound):
        db.set_review("nope", "r1", "accepted")
    with pytest.raises(FindingNotFound):
        db.set_review("a1", "r9", "accepted")
    with pytest.raises(ValueError, match="accepted or rejected"):
        db.set_review("a1", "r1", "maybe")


def test_find_cached_returns_newest_clean_run(db):
    db.save_audit(_report("old", created_at="2026-10-14T09:00:00+00:00"), [], "key1")
    db.save_audit(_report("new", created_at="2026-10-14T10:00:00+00:00"), [], "key1")
    db.save_audit(_report("broken", errors=[{"rule_id": "r1", "message": "x"}],
                          created_at="2026-10-14T11:00:00+00:00"), [], "key1")
    assert db.find_cached("key1")["audit_id"] == "new"
    assert db.find_cached("other") is None


def test_cached_report_carries_reviews(db):
    db.save_audit(_report(), [], "key1")
    db.set_review("a1", "r1", "accepted")
    assert db.find_cached("key1")["findings"][0]["review"]["decision"] == "accepted"


def test_list_audits(db):
    db.save_audit(_report("a1", created_at="2026-10-14T09:00:00+00:00"), [], "k")
    db.save_audit(_report("a2", created_at="2026-10-14T10:00:00+00:00", document_id="doc2"), [], "k2")
    assert [a["audit_id"] for a in db.list_audits()] == ["a2", "a1"]
    [only] = db.list_audits("doc2")
    assert only["audit_id"] == "a2"
    assert only["risk_score"] == 40.0
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_audit_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.storage.db'`

- [ ] **Step 3: Depoyu yaz**

`src/auditor/storage/db.py`:

```python
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DECISIONS = ("accepted", "rejected")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    audit_id    TEXT PRIMARY KEY,
    cache_key   TEXT NOT NULL,
    document_id TEXT NOT NULL,
    playbook    TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    has_errors  INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    report      TEXT NOT NULL,
    trace       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audits_cache_key ON audits (cache_key);
CREATE INDEX IF NOT EXISTS audits_document ON audits (document_id);
CREATE TABLE IF NOT EXISTS reviews (
    audit_id   TEXT NOT NULL REFERENCES audits (audit_id),
    rule_id    TEXT NOT NULL,
    decision   TEXT NOT NULL,
    note       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (audit_id, rule_id)
);
"""


class AuditNotFound(KeyError):
    pass


class FindingNotFound(KeyError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditStore:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _with_reviews(self, conn: sqlite3.Connection, report: dict) -> dict:
        rows = conn.execute(
            "SELECT rule_id, decision, note, updated_at FROM reviews WHERE audit_id = ?",
            (report["audit_id"],),
        ).fetchall()
        reviews = {row["rule_id"]: {"decision": row["decision"], "note": row["note"],
                                    "updated_at": row["updated_at"]} for row in rows}
        for finding in report["findings"]:
            finding["review"] = reviews.get(finding["rule_id"])
        return report

    def save_audit(self, report: dict, trace: list[dict], cache_key: str) -> None:
        with self._db() as conn:
            conn.execute(
                "INSERT INTO audits (audit_id, cache_key, document_id, playbook, provider, model,"
                " has_errors, created_at, report, trace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report["audit_id"], cache_key, report["document_id"], report["playbook"],
                    report["provider"], report["model"], int(bool(report["errors"])),
                    report["created_at"], json.dumps(report, ensure_ascii=False),
                    json.dumps(trace, ensure_ascii=False),
                ),
            )

    def get_report(self, audit_id: str) -> dict | None:
        with self._db() as conn:
            row = conn.execute("SELECT report FROM audits WHERE audit_id = ?", (audit_id,)).fetchone()
            return self._with_reviews(conn, json.loads(row["report"])) if row else None

    def find_cached(self, cache_key: str) -> dict | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT report FROM audits WHERE cache_key = ? AND has_errors = 0"
                " ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (cache_key,),
            ).fetchone()
            return self._with_reviews(conn, json.loads(row["report"])) if row else None

    def get_trace(self, audit_id: str) -> list[dict] | None:
        with self._db() as conn:
            row = conn.execute("SELECT trace FROM audits WHERE audit_id = ?", (audit_id,)).fetchone()
            return json.loads(row["trace"]) if row else None

    def set_review(self, audit_id: str, rule_id: str, decision: str, note: str = "") -> dict:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be accepted or rejected, got {decision!r}")
        updated_at = _now()
        with self._db() as conn:
            row = conn.execute("SELECT report FROM audits WHERE audit_id = ?", (audit_id,)).fetchone()
            if row is None:
                raise AuditNotFound(audit_id)
            if rule_id not in {f["rule_id"] for f in json.loads(row["report"])["findings"]}:
                raise FindingNotFound(rule_id)
            conn.execute(
                "INSERT INTO reviews (audit_id, rule_id, decision, note, updated_at)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT (audit_id, rule_id) DO UPDATE SET"
                " decision = excluded.decision, note = excluded.note, updated_at = excluded.updated_at",
                (audit_id, rule_id, decision, note, updated_at),
            )
        return {"decision": decision, "note": note, "updated_at": updated_at}

    def list_audits(self, document_id: str | None = None) -> list[dict]:
        query = ("SELECT audit_id, document_id, playbook, provider, model, created_at,"
                 " json_extract(report, '$.risk_score') AS risk_score FROM audits")
        params: tuple = ()
        if document_id:
            query += " WHERE document_id = ?"
            params = (document_id,)
        query += " ORDER BY created_at DESC, rowid DESC"
        with self._db() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_audit_db.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/storage/db.py tests/test_audit_db.py
git commit -m "feat: SQLite store for audits, traces and reviews

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: İz kaydı ve prompt'lar

**Files:**
- Create: `src/auditor/audit/trace.py`, `src/auditor/audit/prompts.py`, `tests/test_trace_prompts.py`

**Interfaces:**
- Consumes: `LLMResult`, `Usage` (Task 1); `Rule` (Task 5); `ParentPassage`
- Produces:
  - `@dataclass TraceEvent(rule_id, node, started_at: str, duration_s: float, input: str, output: str, models: list[str], input_tokens: int, output_tokens: int, cost_usd: float)`
  - `NodeSpan` (`input`, `output`, `usage`, `models`; `add(result: LLMResult)`)
  - `TraceRecorder`: `node(rule_id, node, input_summary)` context manager → `NodeSpan`; `events() -> list[TraceEvent]`; `to_dicts() -> list[dict]`; `totals() -> Usage`
  - `PROMPT_VERSION = "1"`
  - Şemalar: `Evaluation(clause_found: bool, matches_criteria: bool, reasoning: str, quotes: list[str])`, `RewrittenQueries(queries: list[str])`, `Relevance(relevant: bool)`
  - `EVALUATE_SYSTEM`, `REWRITE_SYSTEM`, `RELEVANCE_SYSTEM`
  - `format_sections(passages) -> str`, `rule_block(rule) -> str` (ilk satır `Rule: <title>`), `evaluate_prompt(rule, passages)`, `rewrite_prompt(rule, tried: list[str])`, `relevance_prompt(rule, passage)`

Şema alanlarında varsayılan değer yok: OpenAI strict structured outputs her alanı zorunlu ister.

- [ ] **Step 1: Testi yaz**

`tests/test_trace_prompts.py`:

```python
import threading

import pytest

from auditor.audit.playbook import Rule
from auditor.audit.prompts import evaluate_prompt, relevance_prompt, rewrite_prompt
from auditor.audit.trace import TraceRecorder
from auditor.llm.base import LLMResult, Usage
from auditor.retrieval.pipeline import ParentPassage

RULE = Rule(id="unlimited_liability", title="Unlimited liability", type="must_not_exist",
            severity="high", queries=["unlimited liability"], criteria="Liability is uncapped.")
PASSAGE = ParentPassage("p1", "d1", "3.1 The total liability shall not exceed the fees.", 0, 50, "3 > 3.1", [])


def test_recorder_captures_node_usage_and_output():
    recorder = TraceRecorder()
    with recorder.node("r1", "evaluate", "2 sections") as span:
        span.add(LLMResult(None, "m-eval", Usage(100, 20, 0.01)))
        span.add(LLMResult(None, "m-eval", Usage(50, 5, 0.02)))
        span.output = "found"
    [event] = recorder.events()
    assert (event.rule_id, event.node, event.input, event.output) == ("r1", "evaluate", "2 sections", "found")
    assert event.models == ["m-eval"]
    assert (event.input_tokens, event.output_tokens) == (150, 25)
    assert event.cost_usd == pytest.approx(0.03)
    assert event.duration_s >= 0
    assert event.started_at.endswith("+00:00")
    assert recorder.to_dicts()[0]["node"] == "evaluate"


def test_recorder_keeps_failed_nodes():
    recorder = TraceRecorder()
    with pytest.raises(RuntimeError):
        with recorder.node("r1", "search", "q"):
            raise RuntimeError("store down")
    [event] = recorder.events()
    assert event.output == "error: store down"


def test_recorder_totals_across_threads():
    recorder = TraceRecorder()

    def work(i):
        with recorder.node(f"r{i}", "evaluate", "") as span:
            span.add(LLMResult(None, "m", Usage(10, 1, 0.001)))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    totals = recorder.totals()
    assert len(recorder.events()) == 20
    assert (totals.input_tokens, totals.output_tokens) == (200, 20)
    assert totals.cost_usd == pytest.approx(0.02)


def test_evaluate_prompt_carries_rule_and_sections():
    prompt = evaluate_prompt(RULE, [PASSAGE])
    assert prompt.startswith("Rule: Unlimited liability\n")
    assert "must NOT contain" in prompt
    assert "Criteria: Liability is uncapped." in prompt
    assert "[Section 1: 3 > 3.1]" in prompt
    assert "shall not exceed the fees" in prompt


def test_rewrite_and_relevance_prompts():
    assert "- unlimited liability\n- uncapped damages" in rewrite_prompt(RULE, ["unlimited liability", "uncapped damages"])
    prompt = relevance_prompt(RULE, PASSAGE)
    assert prompt.startswith("Rule: Unlimited liability\n")
    assert "[Section 1: 3 > 3.1]" in prompt
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_trace_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.audit.trace'`

- [ ] **Step 3: İz kaydını yaz**

`src/auditor/audit/trace.py`:

```python
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
```

- [ ] **Step 4: Prompt'ları yaz**

`src/auditor/audit/prompts.py`:

```python
from pydantic import BaseModel

from auditor.audit.playbook import Rule
from auditor.retrieval.pipeline import ParentPassage

# Bump on any change to the prompt text or the schemas: it is part of the audit cache key.
PROMPT_VERSION = "1"


class Evaluation(BaseModel):
    clause_found: bool
    matches_criteria: bool
    reasoning: str
    quotes: list[str]


class RewrittenQueries(BaseModel):
    queries: list[str]


class Relevance(BaseModel):
    relevant: bool


RULE_KIND = {
    "must_exist": "The contract must contain this clause.",
    "must_not_exist": "The contract must NOT contain this clause; it is prohibited.",
    "condition": "If the contract has this clause, the clause must meet the criteria.",
}

EVALUATE_SYSTEM = (
    "You review contracts against compliance rules. You receive one rule and numbered sections "
    "from a single contract. Set clause_found to true if the sections contain a clause on the "
    "rule's topic. Set matches_criteria to true if that clause matches the rule's criteria. When "
    "the rule says the clause is prohibited, the criteria describe the prohibited clause, and "
    "matches_criteria means the text is that prohibited clause. Copy the decisive sentences into "
    "quotes word for word from the sections, without changing, joining or shortening them. If "
    "clause_found is false, return no quotes and set matches_criteria to false. Explain the "
    "decision in reasoning in two or three sentences."
)

REWRITE_SYSTEM = (
    "You write search queries for finding a clause in a contract. Return two or three short "
    "queries worded differently from the queries that already failed, using synonyms and the "
    "terms contracts commonly use for this clause."
)

RELEVANCE_SYSTEM = (
    "You check whether one contract section is relevant to a compliance rule. Set relevant to "
    "true only if the section contains a clause on the rule's topic, whether or not the clause "
    "meets the criteria."
)


def format_sections(passages: list[ParentPassage]) -> str:
    return "\n\n".join(
        f"[Section {i}: {p.section_path or 'untitled'}]\n{p.text}"
        for i, p in enumerate(passages, start=1)
    )


def rule_block(rule: Rule) -> str:
    return f"Rule: {rule.title}\nKind: {RULE_KIND[rule.type]}\nCriteria: {rule.criteria}"


def evaluate_prompt(rule: Rule, passages: list[ParentPassage]) -> str:
    return f"{rule_block(rule)}\n\nSections:\n\n{format_sections(passages)}"


def rewrite_prompt(rule: Rule, tried: list[str]) -> str:
    tried_lines = "\n".join(f"- {query}" for query in tried)
    return f"{rule_block(rule)}\n\nQueries that found nothing relevant:\n{tried_lines}"


def relevance_prompt(rule: Rule, passage: ParentPassage) -> str:
    return f"{rule_block(rule)}\n\n{format_sections([passage])}"
```

- [ ] **Step 5: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_trace_prompts.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/auditor/audit/trace.py src/auditor/audit/prompts.py tests/test_trace_prompts.py
git commit -m "feat: trace recorder, audit prompts and output schemas

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Kural grafı

**Files:**
- Create: `src/auditor/audit/nodes.py`, `src/auditor/audit/graph.py`, `tests/test_rule_graph.py`

**Interfaces:**
- Consumes: `Retriever.search(query, config, flt) -> RetrievalResult` (`.parents`, `.insufficient_evidence`); `DocumentStore.load`; `SearchFilter`; `RetrievalConfig`; `complete_with_retry`, `LLMError` (Task 1); `verify_quotes`, `Citation` (Task 4); `Rule` (Task 5); `Status`, `status_for`, `is_absence_verdict` (Task 6); `TraceRecorder` (Task 8); şemalar ve prompt'lar (Task 8)
- Produces:
  - `@dataclass(frozen=True) AuditConfig(retrieval: RetrievalConfig = RetrievalConfig(), max_rewrites: int = 2, max_sections: int = 6, wide_scan_k: int = 15, concurrency: int = 4)`
  - `RuleState` TypedDict: `rule`, `queries`, `tried: list[str]`, `rewrites`, `insufficient`, `passages`, `examined: list[str]` (parent id'leri), `evaluation`, `eval_attempts`, `citations`, `needs_retry`, `wide_scan_done`, `status: Status | None`, `error: str | None`
  - `initial_state(rule) -> RuleState`
  - `RuleNodes(retriever, docstore, provider, recorder, document_id, config, lock)` — metotlar: `search`, `rewrite`, `evaluate`, `verify`, `wide_scan`
  - `build_rule_graph(nodes: RuleNodes, max_rewrites: int)` → derlenmiş LangGraph (`invoke(state)`, `batch(states, config=...)`)

Akış:

```
START → search ─┬─ insufficient ve rewrites < max ─→ rewrite → search
                └─ aksi ─→ evaluate → verify ─┬─ alıntısız "bulundu", ilk deneme ─→ evaluate
                                              ├─ yokluk hükmü, geniş tarama yapılmadı ─→ wide_scan ─┬─ ilgili bölüm var ─→ evaluate
                                              │                                                      └─ yok ─→ END
                                              └─ aksi ─→ END
Her düğümde LLM hatası → error alanı → END
```

Notlar:
- `search`: her sorgunun parent'larını sırayla birer birer harmanlar (round-robin), tekilleştirir; yeni bulunanlar önce, önceki pasajlar sonra, en fazla `max_sections`. Tüm sorgular `insufficient_evidence` ise `insufficient=True`. Boş sorgu listesi önceki pasajları korur.
- `rewrite`: daha önce denenen sorguları eler, en fazla 3 yeni sorgu.
- `evaluate`: pasaj yoksa LLM çağrılmaz, "bulunamadı" kabul edilir.
- `verify`: `clause_found` ve doğrulanmış alıntı yoksa ilk denemede `needs_retry`, ikincide `belirsiz`. `clause_found=False` ise alıntılar atılır.
- `wide_scan`: denenen tüm sorgularla `final_k=wide_scan_k` arama, ilk `wide_scan_k` aday bölüm, her biri için küçük modelle `Relevance`. İlgili bölüm varsa `evaluation`, `status` sıfırlanır, `eval_attempts=0`.
- Retriever ve docstore çağrıları `lock` altında yapılır (bellek içi Qdrant ve GPU modelleri thread-safe değil); LLM çağrıları paralel kalır.

- [ ] **Step 1: Testi yaz**

`tests/test_rule_graph.py`:

```python
import threading

import pytest
from fakes import FakeEmbedder, FakeLLM, FakeReranker, FakeSparseEncoder, sequence

from auditor.audit.graph import build_rule_graph
from auditor.audit.nodes import AuditConfig, RuleNodes, initial_state
from auditor.audit.playbook import Rule
from auditor.audit.prompts import Evaluation, Relevance, RewrittenQueries
from auditor.audit.scoring import Status
from auditor.audit.trace import TraceRecorder
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.llm.base import LLMError
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore

LIABILITY_QUOTE = ("The total aggregate liability of either party shall not exceed the fees "
                   "paid in the twelve months preceding the claim.")
FOUND = Evaluation(clause_found=True, matches_criteria=True, reasoning="Capped at fees.",
                   quotes=[LIABILITY_QUOTE])
NOT_FOUND = Evaluation(clause_found=False, matches_criteria=False, reasoning="No clause.", quotes=[])
INVENTED = Evaluation(clause_found=True, matches_criteria=True, reasoning="Invented.",
                      quotes=["Liability is unlimited for all claims of any kind."])


@pytest.fixture
def env(tmp_path, sample_contract):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    doc_id = Indexer(store, embedder, sparse, docstore).ingest_text(sample_contract, "msa.txt").document_id
    return Retriever(store, embedder, sparse, FakeReranker(), docstore), docstore, doc_id


def _rule(rule_type="must_exist", queries=("total aggregate liability",)):
    return Rule(id="liability_cap", title="Liability cap", type=rule_type, severity="high",
                queries=list(queries), criteria="Total liability is capped.")


def _run(env, rule, llm, config=AuditConfig()):
    retriever, docstore, doc_id = env
    recorder = TraceRecorder()
    nodes = RuleNodes(retriever, docstore, llm, recorder, doc_id, config, threading.Lock())
    final = build_rule_graph(nodes, config.max_rewrites).invoke(initial_state(rule))
    return final, [event.node for event in recorder.events()]


def test_found_clause_with_verified_quote_is_compliant(env):
    llm = FakeLLM({"Evaluation": FOUND})
    final, nodes = _run(env, _rule(), llm)
    assert final["status"] is Status.COMPLIANT
    assert nodes == ["search", "evaluate", "verify"]
    [citation] = final["citations"]
    assert citation.quote.startswith("The total aggregate liability")
    assert citation.section_path.startswith("3")
    assert final["tried"] == ["total aggregate liability"]
    assert len(final["examined"]) >= 1
    assert llm.calls[0][1] == "eval"
    assert "Rule: Liability cap" in llm.calls[0][2]


def test_invented_quote_twice_is_uncertain(env):
    llm = FakeLLM({"Evaluation": INVENTED})
    final, nodes = _run(env, _rule(), llm)
    assert final["status"] is Status.UNCERTAIN
    assert final["citations"] == []
    assert llm.count("Evaluation") == 2
    assert nodes == ["search", "evaluate", "verify", "evaluate", "verify"]


def test_invented_quote_then_real_quote_is_compliant(env):
    llm = FakeLLM({"Evaluation": sequence(INVENTED, FOUND)})
    final, _ = _run(env, _rule(), llm)
    assert final["status"] is Status.COMPLIANT
    assert len(final["citations"]) == 1


def test_missing_clause_triggers_wide_scan(env):
    llm = FakeLLM({"Evaluation": NOT_FOUND, "Relevance": Relevance(relevant=False)})
    final, nodes = _run(env, _rule(), llm)
    assert final["status"] is Status.MISSING
    assert nodes == ["search", "evaluate", "verify", "wide_scan"]
    assert llm.count("Relevance") >= 1
    assert all(tier == "small" for name, tier, _ in llm.calls if name == "Relevance")
    assert len(final["examined"]) >= llm.count("Relevance")


def test_wide_scan_finding_relevant_section_reevaluates(env):
    relevant = lambda user: Relevance(relevant="aggregate liability" in user)
    llm = FakeLLM({"Evaluation": sequence(NOT_FOUND, FOUND), "Relevance": relevant})
    final, nodes = _run(env, _rule(), llm)
    assert final["status"] is Status.COMPLIANT
    assert nodes == ["search", "evaluate", "verify", "wide_scan", "evaluate", "verify"]
    second_prompt = [user for name, _, user in llm.calls if name == "Evaluation"][1]
    assert "aggregate liability" in second_prompt


def test_insufficient_evidence_rewrites_twice_then_evaluates(env):
    llm = FakeLLM({
        "RewrittenQueries": sequence(RewrittenQueries(queries=["zebra galaxy"]),
                                     RewrittenQueries(queries=["zebra nebula", "zebra galaxy"])),
        "Evaluation": NOT_FOUND,
        "Relevance": Relevance(relevant=False),
    })
    final, nodes = _run(env, _rule(queries=["zebra quantum"]), llm)
    assert llm.count("RewrittenQueries") == 2
    assert final["tried"] == ["zebra quantum", "zebra galaxy", "zebra nebula"]
    assert nodes[:6] == ["search", "rewrite", "search", "rewrite", "search", "evaluate"]
    assert final["status"] is Status.MISSING
    assert "- zebra quantum\n- zebra galaxy" in [u for n, _, u in llm.calls if n == "RewrittenQueries"][1]


def test_rewrite_that_finds_evidence_stops_rewriting(env):
    llm = FakeLLM({
        "RewrittenQueries": RewrittenQueries(queries=["total aggregate liability fees paid"]),
        "Evaluation": FOUND,
    })
    final, nodes = _run(env, _rule(queries=["zebra quantum"]), llm)
    assert llm.count("RewrittenQueries") == 1
    assert nodes == ["search", "rewrite", "search", "evaluate", "verify"]
    assert final["status"] is Status.COMPLIANT


def test_llm_failure_sets_error_after_retry(env):
    llm = FakeLLM({"Evaluation": LLMError("timeout")})
    final, nodes = _run(env, _rule(), llm)
    assert "evaluation failed" in final["error"]
    assert final["status"] is None
    assert llm.count("Evaluation") == 2
    assert nodes == ["search", "evaluate"]


def test_prohibited_clause_absent_is_compliant_after_wide_scan(env):
    llm = FakeLLM({"Evaluation": NOT_FOUND, "Relevance": Relevance(relevant=False)})
    final, nodes = _run(env, _rule("must_not_exist"), llm)
    assert final["status"] is Status.COMPLIANT
    assert nodes[-1] == "wide_scan"


def test_prohibited_clause_present_is_non_compliant_without_wide_scan(env):
    llm = FakeLLM({"Evaluation": FOUND})
    final, nodes = _run(env, _rule("must_not_exist"), llm)
    assert final["status"] is Status.NON_COMPLIANT
    assert "wide_scan" not in nodes


def test_section_cap_limits_evaluated_passages(env):
    llm = FakeLLM({"Evaluation": FOUND})
    final, _ = _run(env, _rule(queries=["agreement", "party", "liability"]), llm,
                    AuditConfig(max_sections=2))
    assert len(final["passages"]) <= 2
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_rule_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.audit.graph'`

- [ ] **Step 3: Düğümleri yaz**

`src/auditor/audit/nodes.py`:

```python
import threading
from dataclasses import dataclass, field, replace
from typing import TypedDict

from auditor.audit.citations import Citation, verify_quotes
from auditor.audit.playbook import Rule
from auditor.audit.prompts import (
    EVALUATE_SYSTEM,
    RELEVANCE_SYSTEM,
    REWRITE_SYSTEM,
    Evaluation,
    Relevance,
    RewrittenQueries,
    evaluate_prompt,
    relevance_prompt,
    rewrite_prompt,
)
from auditor.audit.scoring import Status, status_for
from auditor.audit.trace import TraceRecorder
from auditor.index.store import SearchFilter
from auditor.llm.base import LLMError, LLMProvider, complete_with_retry
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.pipeline import ParentPassage, RetrievalResult, Retriever
from auditor.storage.docstore import DocumentStore

MAX_NEW_QUERIES = 3


@dataclass(frozen=True)
class AuditConfig:
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    max_rewrites: int = 2
    max_sections: int = 6
    wide_scan_k: int = 15
    concurrency: int = 4


class RuleState(TypedDict, total=False):
    rule: Rule
    queries: list[str]
    tried: list[str]
    rewrites: int
    insufficient: bool
    passages: list[ParentPassage]
    examined: list[str]
    evaluation: Evaluation | None
    eval_attempts: int
    citations: list[Citation]
    needs_retry: bool
    wide_scan_done: bool
    status: Status | None
    error: str | None


def initial_state(rule: Rule) -> RuleState:
    return RuleState(
        rule=rule, queries=list(rule.queries), tried=[], rewrites=0, insufficient=False,
        passages=[], examined=[], evaluation=None, eval_attempts=0, citations=[],
        needs_retry=False, wide_scan_done=False, status=None, error=None,
    )


def _round_robin(results: list[RetrievalResult], limit: int) -> list[ParentPassage]:
    """Take each query's best section in turn so one query cannot crowd out the others."""
    merged: dict[str, ParentPassage] = {}
    depth = max((len(r.parents) for r in results), default=0)
    for i in range(depth):
        for result in results:
            if i < len(result.parents):
                merged.setdefault(result.parents[i].parent_id, result.parents[i])
    return list(merged.values())[:limit]


def _add_examined(examined: list[str], passages: list[ParentPassage]) -> list[str]:
    added = [p.parent_id for p in passages if p.parent_id not in examined]
    return examined + list(dict.fromkeys(added))


class RuleNodes:
    def __init__(self, retriever: Retriever, docstore: DocumentStore, provider: LLMProvider,
                 recorder: TraceRecorder, document_id: str, config: AuditConfig,
                 lock: threading.Lock):
        self._retriever = retriever
        self._docstore = docstore
        self._provider = provider
        self._recorder = recorder
        self._document_id = document_id
        self._config = config
        self._lock = lock
        self._filter = SearchFilter(document_ids=[document_id])

    def _search(self, query: str, config: RetrievalConfig) -> RetrievalResult:
        with self._lock:
            return self._retriever.search(query, config, self._filter)

    def search(self, state: RuleState) -> dict:
        rule, queries = state["rule"], state["queries"]
        with self._recorder.node(rule.id, "search", "; ".join(queries)) as span:
            results = [self._search(query, self._config.retrieval) for query in queries]
            found = _round_robin(results, self._config.max_sections)
            combined: dict[str, ParentPassage] = {}
            for passage in [*found, *state["passages"]]:
                combined.setdefault(passage.parent_id, passage)
            passages = list(combined.values())[: self._config.max_sections]
            insufficient = all(result.insufficient_evidence for result in results)
            span.output = f"{len(found)} new sections, insufficient={insufficient}"
        return {
            "passages": passages,
            "tried": state["tried"] + [q for q in queries if q not in state["tried"]],
            "insufficient": insufficient,
        }

    def rewrite(self, state: RuleState) -> dict:
        rule = state["rule"]
        with self._recorder.node(rule.id, "rewrite", "; ".join(state["tried"])) as span:
            try:
                result = complete_with_retry(self._provider, REWRITE_SYSTEM,
                                             rewrite_prompt(rule, state["tried"]),
                                             RewrittenQueries, "small")
            except LLMError as exc:
                span.output = f"error: {exc}"
                return {"error": f"query rewrite failed: {exc}", "rewrites": state["rewrites"] + 1}
            span.add(result)
            fresh = [q.strip() for q in result.value.queries if q.strip()]
            queries = [q for q in dict.fromkeys(fresh) if q not in state["tried"]][:MAX_NEW_QUERIES]
            span.output = "; ".join(queries) or "no new queries"
        return {"queries": queries, "rewrites": state["rewrites"] + 1}

    def evaluate(self, state: RuleState) -> dict:
        rule, passages = state["rule"], state["passages"]
        examined = _add_examined(state["examined"], passages)
        attempts = state["eval_attempts"] + 1
        with self._recorder.node(rule.id, "evaluate", f"{len(passages)} sections") as span:
            if not passages:
                span.output = "no sections retrieved"
                evaluation = Evaluation(clause_found=False, matches_criteria=False, quotes=[],
                                        reasoning="No candidate sections were retrieved for this rule.")
                return {"evaluation": evaluation, "eval_attempts": attempts, "examined": examined}
            try:
                result = complete_with_retry(self._provider, EVALUATE_SYSTEM,
                                             evaluate_prompt(rule, passages), Evaluation, "eval")
            except LLMError as exc:
                span.output = f"error: {exc}"
                return {"error": f"evaluation failed: {exc}", "examined": examined}
            span.add(result)
            evaluation = result.value
            span.output = (f"found={evaluation.clause_found} matches={evaluation.matches_criteria} "
                           f"quotes={len(evaluation.quotes)}")
        return {"evaluation": evaluation, "eval_attempts": attempts, "examined": examined}

    def verify(self, state: RuleState) -> dict:
        rule, evaluation = state["rule"], state["evaluation"]
        with self._recorder.node(rule.id, "verify", f"{len(evaluation.quotes)} quotes") as span:
            if not evaluation.clause_found:
                status = status_for(rule.type, False, False)
                span.output = f"no clause claimed, status={status}"
                return {"citations": [], "needs_retry": False, "status": status}
            with self._lock:
                doc = self._docstore.load(self._document_id)
            citations = verify_quotes(doc, evaluation.quotes, state["passages"])
            if not citations:
                if state["eval_attempts"] < 2:
                    span.output = "no verified quote, evaluating again"
                    return {"citations": [], "needs_retry": True}
                span.output = "no verified quote after retry"
                return {"citations": [], "needs_retry": False, "status": Status.UNCERTAIN}
            status = status_for(rule.type, True, evaluation.matches_criteria)
            span.output = f"{len(citations)} verified, status={status}"
        return {"citations": citations, "needs_retry": False, "status": status}

    def wide_scan(self, state: RuleState) -> dict:
        rule = state["rule"]
        k = self._config.wide_scan_k
        config = replace(self._config.retrieval, final_k=k)
        with self._recorder.node(rule.id, "wide_scan", f"top {k} sections") as span:
            candidates = _round_robin([self._search(q, config) for q in state["tried"]], k)
            relevant: list[ParentPassage] = []
            try:
                for passage in candidates:
                    result = complete_with_retry(self._provider, RELEVANCE_SYSTEM,
                                                 relevance_prompt(rule, passage), Relevance, "small")
                    span.add(result)
                    if result.value.relevant:
                        relevant.append(passage)
            except LLMError as exc:
                span.output = f"error: {exc}"
                return {"error": f"wide scan failed: {exc}", "wide_scan_done": True}
            span.output = f"{len(relevant)} of {len(candidates)} sections relevant"
        update: dict = {"wide_scan_done": True,
                        "examined": _add_examined(state["examined"], candidates)}
        if relevant:
            update.update(passages=relevant[: self._config.max_sections], evaluation=None,
                          eval_attempts=0, status=None, citations=[])
        return update
```

- [ ] **Step 4: Grafı yaz**

`src/auditor/audit/graph.py`:

```python
from langgraph.graph import END, START, StateGraph

from auditor.audit.nodes import RuleNodes, RuleState
from auditor.audit.scoring import is_absence_verdict


def after_search(state: RuleState, max_rewrites: int) -> str:
    if state["insufficient"] and state["rewrites"] < max_rewrites:
        return "rewrite"
    return "evaluate"


def after_rewrite(state: RuleState) -> str:
    return END if state.get("error") else "search"


def after_evaluate(state: RuleState) -> str:
    return END if state.get("error") else "verify"


def after_verify(state: RuleState) -> str:
    if state["needs_retry"]:
        return "evaluate"
    if is_absence_verdict(state["rule"].type, state["status"]) and not state["wide_scan_done"]:
        return "wide_scan"
    return END


def after_wide_scan(state: RuleState) -> str:
    if state.get("error") or state["status"] is not None:
        return END
    return "evaluate"


def build_rule_graph(nodes: RuleNodes, max_rewrites: int):
    graph = StateGraph(RuleState)
    graph.add_node("search", nodes.search)
    graph.add_node("rewrite", nodes.rewrite)
    graph.add_node("evaluate", nodes.evaluate)
    graph.add_node("verify", nodes.verify)
    graph.add_node("wide_scan", nodes.wide_scan)
    graph.add_edge(START, "search")
    graph.add_conditional_edges("search", lambda s: after_search(s, max_rewrites),
                                ["rewrite", "evaluate"])
    graph.add_conditional_edges("rewrite", after_rewrite, ["search", END])
    graph.add_conditional_edges("evaluate", after_evaluate, ["verify", END])
    graph.add_conditional_edges("verify", after_verify, ["evaluate", "wide_scan", END])
    graph.add_conditional_edges("wide_scan", after_wide_scan, ["evaluate", END])
    return graph.compile()
```

- [ ] **Step 5: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_rule_graph.py -v`
Expected: 11 passed

Kanıt yeterliliğine bağlı bir test başarısız olursa önce sahte reranker'ın skorunu kontrol et: `FakeReranker` sorgu kelimelerinin chunk'ta geçme oranını verir; `zebra ...` sorguları 0 alır ve `min_rerank_score=0.3` altında kalır.

- [ ] **Step 6: Commit**

```bash
git add src/auditor/audit/nodes.py src/auditor/audit/graph.py tests/test_rule_graph.py
git commit -m "feat: per-rule LangGraph with rewrite loop, quote check and wide scan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Denetim çalıştırıcı, rapor ve önbellek

**Files:**
- Create: `src/auditor/audit/report.py`, `src/auditor/audit/runner.py`, `tests/test_auditor.py`
- Modify: `tests/fakes.py`

**Interfaces:**
- Consumes: Task 4–9 tümü; `AuditStore` (Task 7); `DocumentStore.exists`, `DocumentNotFound`; `models_label` (Task 1); `playbooks_dir` fixture (Task 5)
- Produces:
  - `build_finding(rule: Rule, outcome: RuleState | Exception) -> dict` — anahtarlar: `rule_id`, `title`, `type`, `status`, `severity`, `risk`, `reasoning`, `citations`, `evidence {queries_tried, sections_examined}`, `error`, `review`
  - `build_report(*, audit_id, document_id, playbook_key, provider, findings, duration_s, usage) -> dict` — anahtarlar: `audit_id`, `document_id`, `playbook`, `provider`, `model`, `created_at`, `risk_score`, `cached`, `findings`, `errors [{rule_id, message}]`, `totals {duration_s, input_tokens, output_tokens, cost_usd}`
  - `cache_key(document_id, playbook_sha256, provider_name, model_label, prompt_version=PROMPT_VERSION) -> str`
  - `Auditor(retriever, docstore, audits, playbooks_dir, provider_factory: Callable[[str], LLMProvider], config: AuditConfig = AuditConfig())`, `Auditor.run(document_id, playbook_key, provider_name, *, force=False) -> dict`
  - `tests/fakes.py`: `CONTRACT_PAGES`, `LIABILITY_LINE`, `by_rule(responses: dict[str, object])`, `audit_llm(**overrides) -> FakeLLM`

Rapor, spec'teki örnekten iki noktada ayrılır: bulguda `bboxes` her kutunun sayfasını taşır (`[{"page", "bbox"}]`, çok sayfalı alıntılar için) ve hata ayrıntısı bulgunun `error` alanında da durur.

- [ ] **Step 1: Sahte yardımcıları ekle**

`tests/fakes.py` sonuna ekle:

```python
CONTRACT_PAGES = [
    [("1. Definitions", 11),
     ("Services means the consulting services described in Exhibit A.", 11)],
    [("2. Liability", 11),
     ("The total liability shall not exceed the fees paid in twelve months.", 11)],
]
LIABILITY_LINE = "The total liability shall not exceed the fees paid in twelve months."


def by_rule(responses: dict):
    """Handler choosing the response by the rule title in the prompt."""
    def handler(user):
        for title, value in responses.items():
            if f"Rule: {title}\n" in user:
                return value
        raise AssertionError(f"no fake response for prompt: {user[:80]!r}")
    return handler


def audit_llm(**overrides) -> FakeLLM:
    """Responses for the test playbook in conftest: liability found, confidentiality missing."""
    from auditor.audit.prompts import Evaluation, Relevance, RewrittenQueries

    handlers = {
        "Evaluation": by_rule({
            "Liability cap": Evaluation(clause_found=True, matches_criteria=True,
                                        reasoning="Liability is capped at fees paid.",
                                        quotes=[LIABILITY_LINE]),
            "Confidentiality": Evaluation(clause_found=False, matches_criteria=False,
                                          reasoning="No confidentiality clause.", quotes=[]),
        }),
        "Relevance": Relevance(relevant=False),
        "RewrittenQueries": RewrittenQueries(queries=["secret information"]),
    }
    handlers.update(overrides)
    return FakeLLM(handlers)
```

- [ ] **Step 2: Testi yaz**

`tests/test_auditor.py`:

```python
from types import SimpleNamespace

import pytest
from fakes import (
    CONTRACT_PAGES,
    FakeEmbedder,
    FakeLLM,
    FakeReranker,
    FakeSparseEncoder,
    audit_llm,
    by_rule,
)

from auditor.audit.nodes import AuditConfig
from auditor.audit.playbook import PlaybookNotFound
from auditor.audit.prompts import Evaluation
from auditor.audit.runner import Auditor, cache_key
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.llm.base import ProviderUnavailableError
from auditor.retrieval.pipeline import Retriever
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentNotFound, DocumentStore


@pytest.fixture
def env(tmp_path, make_pdf, playbooks_dir):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    pdf = make_pdf(tmp_path / "contract.pdf", CONTRACT_PAGES)
    doc_id = Indexer(store, embedder, sparse, docstore).ingest_pdf(pdf).document_id
    return SimpleNamespace(
        retriever=Retriever(store, embedder, sparse, FakeReranker(), docstore),
        docstore=docstore,
        audits=AuditStore(tmp_path / "auditor.db"),
        playbooks=playbooks_dir,
        doc_id=doc_id,
    )


def _auditor(env, llm):
    return Auditor(env.retriever, env.docstore, env.audits, env.playbooks, lambda name: llm,
                   AuditConfig(concurrency=2))


def test_full_audit_report(env):
    report = _auditor(env, audit_llm()).run(env.doc_id, "test_pb", "openai")
    assert report["document_id"] == env.doc_id
    assert (report["playbook"], report["provider"], report["model"]) == ("test_pb", "fake", "fake-eval+fake-small")
    assert report["cached"] is False
    assert report["risk_score"] == 40.0
    assert report["errors"] == []
    findings = {f["rule_id"]: f for f in report["findings"]}

    liability = findings["liability_cap"]
    assert (liability["status"], liability["risk"], liability["severity"]) == ("uyumlu", 0.0, "high")
    [citation] = liability["citations"]
    assert citation["page"] == 2
    assert citation["bboxes"][0]["page"] == 2
    assert citation["quote"].startswith("The total liability")
    assert liability["evidence"]["queries_tried"] == 1
    assert liability["review"] is None

    confidentiality = findings["confidentiality"]
    assert (confidentiality["status"], confidentiality["risk"]) == ("eksik", 2.0)
    assert confidentiality["citations"] == []
    assert confidentiality["evidence"]["queries_tried"] == 2
    assert confidentiality["evidence"]["sections_examined"] >= 1

    totals = report["totals"]
    assert totals["input_tokens"] > 0 and totals["cost_usd"] > 0 and totals["duration_s"] >= 0


def test_report_and_trace_are_stored(env):
    report = _auditor(env, audit_llm()).run(env.doc_id, "test_pb", "openai")
    assert env.audits.get_report(report["audit_id"])["risk_score"] == 40.0
    trace = env.audits.get_trace(report["audit_id"])
    assert {event["rule_id"] for event in trace} == {"liability_cap", "confidentiality"}
    assert any(e["node"] == "wide_scan" and e["rule_id"] == "confidentiality" for e in trace)


def test_second_run_is_served_from_cache_with_reviews(env):
    llm = audit_llm()
    auditor = _auditor(env, llm)
    first = auditor.run(env.doc_id, "test_pb", "openai")
    calls = len(llm.calls)
    env.audits.set_review(first["audit_id"], "confidentiality", "accepted", "checked")

    second = auditor.run(env.doc_id, "test_pb", "openai")
    assert second["cached"] is True
    assert second["audit_id"] == first["audit_id"]
    assert len(llm.calls) == calls
    review = {f["rule_id"]: f["review"] for f in second["findings"]}["confidentiality"]
    assert review["decision"] == "accepted"

    forced = auditor.run(env.doc_id, "test_pb", "openai", force=True)
    assert forced["cached"] is False
    assert forced["audit_id"] != first["audit_id"]
    assert len(llm.calls) > calls
    assert len(env.audits.list_audits(env.doc_id)) == 2


def test_unexpected_rule_failure_is_isolated_and_not_cached(env):
    llm = audit_llm(Evaluation=by_rule({
        "Liability cap": Evaluation(clause_found=True, matches_criteria=True, reasoning="ok",
                                    quotes=["The total liability shall not exceed the fees paid in twelve months."]),
        "Confidentiality": RuntimeError("disk on fire"),
    }))
    auditor = _auditor(env, llm)
    report = auditor.run(env.doc_id, "test_pb", "openai")
    findings = {f["rule_id"]: f for f in report["findings"]}
    assert findings["confidentiality"]["status"] == "hata"
    assert findings["confidentiality"]["risk"] is None
    assert "disk on fire" in findings["confidentiality"]["error"]
    assert findings["liability_cap"]["status"] == "uyumlu"
    assert report["errors"] == [{"rule_id": "confidentiality",
                                 "message": findings["confidentiality"]["error"]}]
    assert report["risk_score"] == 0.0

    again = auditor.run(env.doc_id, "test_pb", "openai")
    assert again["cached"] is False
    assert again["audit_id"] != report["audit_id"]


def test_llm_error_marks_rule_as_error(env):
    from auditor.llm.base import LLMError
    llm = audit_llm(Evaluation=LLMError("schema mismatch"))
    report = _auditor(env, llm).run(env.doc_id, "test_pb", "openai")
    assert {f["status"] for f in report["findings"]} == {"hata"}
    assert report["risk_score"] is None
    assert len(report["errors"]) == 2


def test_bad_requests_fail_before_any_llm_call(env):
    llm = audit_llm()
    auditor = _auditor(env, llm)
    with pytest.raises(DocumentNotFound):
        auditor.run("0" * 64, "test_pb", "openai")
    with pytest.raises(PlaybookNotFound, match="available: test_pb"):
        auditor.run(env.doc_id, "nope", "openai")
    down = FakeLLM(unavailable="Ollama is not reachable at http://localhost:11434")
    with pytest.raises(ProviderUnavailableError, match="not reachable"):
        _auditor(env, down).run(env.doc_id, "test_pb", "ollama")
    assert llm.calls == [] and down.calls == []
    assert env.audits.list_audits() == []


def test_cache_key_changes_with_each_part():
    base = cache_key("doc", "pb", "openai", "m1")
    assert len(base) == 64
    assert base == cache_key("doc", "pb", "openai", "m1")
    others = {
        cache_key("doc2", "pb", "openai", "m1"),
        cache_key("doc", "pb2", "openai", "m1"),
        cache_key("doc", "pb", "ollama", "m1"),
        cache_key("doc", "pb", "openai", "m2"),
        cache_key("doc", "pb", "openai", "m1", prompt_version="999"),
    }
    assert base not in others and len(others) == 5
```

- [ ] **Step 3: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_auditor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.audit.runner'`

- [ ] **Step 4: Raporu yaz**

`src/auditor/audit/report.py`:

```python
from datetime import datetime, timezone

from auditor.audit.nodes import RuleState
from auditor.audit.playbook import Rule
from auditor.audit.scoring import Status, risk_score, rule_risk
from auditor.llm.base import LLMProvider, Usage, models_label


def build_finding(rule: Rule, outcome: RuleState | BaseException) -> dict:
    if isinstance(outcome, BaseException):
        error: str | None = f"{type(outcome).__name__}: {outcome}"
        status, reasoning, citations, tried, examined = Status.ERROR, "", [], [], []
    else:
        error = outcome.get("error")
        evaluation = outcome.get("evaluation")
        status = Status.ERROR if error else outcome["status"]
        reasoning = evaluation.reasoning if evaluation is not None and not error else ""
        citations = [] if error else outcome["citations"]
        tried, examined = outcome["tried"], outcome["examined"]
    return {
        "rule_id": rule.id,
        "title": rule.title,
        "type": rule.type,
        "status": status.value,
        "severity": rule.severity,
        "risk": rule_risk(rule.severity, status),
        "reasoning": reasoning,
        "citations": [citation.to_dict() for citation in citations],
        "evidence": {"queries_tried": len(tried), "sections_examined": len(examined)},
        "error": error,
        "review": None,
    }


def build_report(*, audit_id: str, document_id: str, playbook_key: str, provider: LLMProvider,
                 findings: list[dict], duration_s: float, usage: Usage) -> dict:
    return {
        "audit_id": audit_id,
        "document_id": document_id,
        "playbook": playbook_key,
        "provider": provider.name,
        "model": models_label(provider),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "risk_score": risk_score([(f["severity"], Status(f["status"])) for f in findings]),
        "cached": False,
        "findings": findings,
        "errors": [{"rule_id": f["rule_id"], "message": f["error"]}
                   for f in findings if f["status"] == Status.ERROR],
        "totals": {
            "duration_s": round(duration_s, 1),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(usage.cost_usd, 4),
        },
    }
```

- [ ] **Step 5: Çalıştırıcıyı yaz**

`src/auditor/audit/runner.py`:

```python
import hashlib
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from auditor.audit.graph import build_rule_graph
from auditor.audit.nodes import AuditConfig, RuleNodes, initial_state
from auditor.audit.playbook import find_playbook
from auditor.audit.prompts import PROMPT_VERSION
from auditor.audit.report import build_finding, build_report
from auditor.audit.trace import TraceRecorder
from auditor.llm.base import LLMProvider, models_label
from auditor.retrieval.pipeline import Retriever
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentNotFound, DocumentStore


def cache_key(document_id: str, playbook_sha256: str, provider_name: str, model_label: str,
              prompt_version: str = PROMPT_VERSION) -> str:
    raw = "\n".join([document_id, playbook_sha256, provider_name, model_label, prompt_version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Auditor:
    def __init__(self, retriever: Retriever, docstore: DocumentStore, audits: AuditStore,
                 playbooks_dir: str | Path, provider_factory: Callable[[str], LLMProvider],
                 config: AuditConfig = AuditConfig()):
        self._retriever = retriever
        self._docstore = docstore
        self._audits = audits
        self._playbooks_dir = Path(playbooks_dir)
        self._providers = provider_factory
        self._config = config
        # Retrieval touches the vector store and GPU models, which are not thread-safe.
        self._lock = threading.Lock()

    def run(self, document_id: str, playbook_key: str, provider_name: str, *,
            force: bool = False) -> dict:
        if not self._docstore.exists(document_id):
            raise DocumentNotFound(document_id)
        loaded = find_playbook(self._playbooks_dir, playbook_key)
        provider = self._providers(provider_name)
        provider.check_available()

        key = cache_key(document_id, loaded.sha256, provider.name, models_label(provider))
        if not force:
            cached = self._audits.find_cached(key)
            if cached is not None:
                return {**cached, "cached": True}

        recorder = TraceRecorder()
        nodes = RuleNodes(self._retriever, self._docstore, provider, recorder, document_id,
                          self._config, self._lock)
        graph = build_rule_graph(nodes, self._config.max_rewrites)
        rules = loaded.playbook.rules
        started = time.perf_counter()
        outcomes = graph.batch(
            [initial_state(rule) for rule in rules],
            config={"max_concurrency": self._config.concurrency},
            return_exceptions=True,
        )
        findings = [build_finding(rule, outcome) for rule, outcome in zip(rules, outcomes, strict=True)]
        report = build_report(
            audit_id=uuid.uuid4().hex,
            document_id=document_id,
            playbook_key=loaded.key,
            provider=provider,
            findings=findings,
            duration_s=time.perf_counter() - started,
            usage=recorder.totals(),
        )
        self._audits.save_audit(report, recorder.to_dicts(), key)
        return report
```

- [ ] **Step 6: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_auditor.py -v`
Expected: 7 passed

- [ ] **Step 7: Tüm hızlı testleri çalıştır**

Run: `.venv/Scripts/python -m pytest -v`
Expected: tüm testler geçer.

- [ ] **Step 8: Commit**

```bash
git add src/auditor/audit/report.py src/auditor/audit/runner.py tests/test_auditor.py tests/fakes.py
git commit -m "feat: audit runner with parallel rules, report, cache and stored trace

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Belgeye sor

**Files:**
- Create: `src/auditor/qa/__init__.py`, `src/auditor/qa/answer.py`, `tests/test_qa.py`

**Interfaces:**
- Consumes: `Retriever.search`; `DocumentStore.load`; `SearchFilter`; `RetrievalConfig`; `complete_with_retry`, `Usage` (Task 1); `verify_quotes`, `Citation` (Task 4); `format_sections` (Task 8)
- Produces:
  - `NOT_FOUND_MESSAGE = "I could not find a statement about this in these documents."`
  - `QAOutput(answer: str, quotes: list[str])`
  - `@dataclass Answer(question, found: bool, answer: str | None, message: str | None, citations: list[Citation], passages: list[ParentPassage], model: str | None, usage: Usage)`
  - `QuestionAnswerer(retriever, docstore, provider, config: RetrievalConfig | None = None)`, `ask(question, flt: SearchFilter | None = None) -> Answer`

`LLMError` yukarı fırlatılır; çağıran (CLI, Plan 3'te API) kullanıcıya hata olarak gösterir.

- [ ] **Step 1: Testi yaz**

`tests/test_qa.py`:

```python
import pytest
from fakes import FakeEmbedder, FakeLLM, FakeReranker, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import Indexer
from auditor.llm.base import LLMError
from auditor.qa.answer import NOT_FOUND_MESSAGE, QAOutput, QuestionAnswerer
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore

OTHER = """1. Confidentiality
1.1 Each party shall keep the other party's information confidential for five years.

2. Liability
2.1 The aggregate liability of the vendor is limited to the fees paid."""

QUOTE = ("The total aggregate liability of either party shall not exceed the fees paid in the "
         "twelve months preceding the claim.")


@pytest.fixture
def env(tmp_path, sample_contract):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    indexer = Indexer(store, embedder, sparse, docstore)
    msa = indexer.ingest_text(sample_contract, "msa.txt").document_id
    nda = indexer.ingest_text(OTHER, "nda.txt").document_id
    return Retriever(store, embedder, sparse, FakeReranker(), docstore), docstore, msa, nda


def _ask(env, llm, question, flt=None):
    retriever, docstore, _, _ = env
    return QuestionAnswerer(retriever, docstore, llm).ask(question, flt)


def test_answer_with_verified_quote(env):
    llm = FakeLLM({"QAOutput": QAOutput(answer=" Liability is capped at twelve months of fees. ", quotes=[QUOTE])})
    answer = _ask(env, llm, "total aggregate liability fees paid")
    assert answer.found is True
    assert answer.answer == "Liability is capped at twelve months of fees."
    assert answer.message is None
    [citation] = answer.citations
    assert citation.document_id == env[2]
    assert answer.model == "fake-small"
    assert answer.usage.input_tokens == 100
    assert llm.calls[0][1] == "small"
    assert "Question: total aggregate liability fees paid" in llm.calls[0][2]


def test_no_evidence_skips_the_llm(env):
    llm = FakeLLM()
    answer = _ask(env, llm, "zebra quantum")
    assert llm.calls == []
    assert answer.found is False
    assert answer.answer is None
    assert answer.message == NOT_FOUND_MESSAGE
    assert answer.passages


def test_unverified_quote_hides_the_answer(env):
    llm = FakeLLM({"QAOutput": QAOutput(answer="Unlimited.", quotes=["Liability is unlimited for every claim."])})
    answer = _ask(env, llm, "total aggregate liability fees paid")
    assert answer.found is False
    assert answer.answer is None
    assert answer.message == NOT_FOUND_MESSAGE
    assert answer.model == "fake-small"


def test_empty_answer_is_not_found(env):
    llm = FakeLLM({"QAOutput": QAOutput(answer="", quotes=[])})
    assert _ask(env, llm, "total aggregate liability fees paid").found is False


def test_filter_limits_passages_and_citations(env):
    _, _, _, nda = env
    quote = "The aggregate liability of the vendor is limited to the fees paid."
    llm = FakeLLM({"QAOutput": QAOutput(answer="Limited to fees.", quotes=[quote, QUOTE])})
    answer = _ask(env, llm, "aggregate liability fees paid", SearchFilter(document_ids=[nda]))
    assert {p.document_id for p in answer.passages} == {nda}
    assert [c.document_id for c in answer.citations] == [nda]


def test_llm_failure_propagates(env):
    llm = FakeLLM({"QAOutput": LLMError("down")})
    with pytest.raises(LLMError):
        _ask(env, llm, "total aggregate liability fees paid")
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_qa.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.qa'`

- [ ] **Step 3: Belgeye sor'u yaz**

`src/auditor/qa/__init__.py` boş dosya.

`src/auditor/qa/answer.py`:

```python
from dataclasses import dataclass

from pydantic import BaseModel

from auditor.audit.citations import Citation, verify_quotes
from auditor.audit.prompts import format_sections
from auditor.index.store import SearchFilter
from auditor.llm.base import LLMProvider, Usage, complete_with_retry
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.pipeline import ParentPassage, Retriever
from auditor.storage.docstore import DocumentStore

NOT_FOUND_MESSAGE = "I could not find a statement about this in these documents."

QA_SYSTEM = (
    "You answer questions about contracts using only the numbered sections you receive. "
    "Answer in one to three sentences. Copy the sentences that support the answer into quotes "
    "word for word, without changing, joining or shortening them. If the sections do not answer "
    "the question, return an empty answer and no quotes."
)


class QAOutput(BaseModel):
    answer: str
    quotes: list[str]


@dataclass
class Answer:
    question: str
    found: bool
    answer: str | None
    message: str | None
    citations: list[Citation]
    passages: list[ParentPassage]
    model: str | None
    usage: Usage


def qa_prompt(question: str, passages: list[ParentPassage]) -> str:
    return f"Question: {question}\n\nSections:\n\n{format_sections(passages)}"


class QuestionAnswerer:
    def __init__(self, retriever: Retriever, docstore: DocumentStore, provider: LLMProvider,
                 config: RetrievalConfig | None = None):
        self._retriever = retriever
        self._docstore = docstore
        self._provider = provider
        self._config = config or RetrievalConfig()

    def ask(self, question: str, flt: SearchFilter | None = None) -> Answer:
        result = self._retriever.search(question, self._config, flt)
        if result.insufficient_evidence:
            return Answer(question, False, None, NOT_FOUND_MESSAGE, [], result.parents, None, Usage())

        llm = complete_with_retry(self._provider, QA_SYSTEM, qa_prompt(question, result.parents),
                                  QAOutput, "small")
        citations: list[Citation] = []
        for document_id in dict.fromkeys(p.document_id for p in result.parents):
            doc = self._docstore.load(document_id)
            citations.extend(verify_quotes(doc, llm.value.quotes, result.parents))
        text = llm.value.answer.strip()
        if not text or not citations:
            return Answer(question, False, None, NOT_FOUND_MESSAGE, [], result.parents,
                          llm.model, llm.usage)
        return Answer(question, True, text, None, citations, result.parents, llm.model, llm.usage)
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_qa.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/qa tests/test_qa.py
git commit -m "feat: ask-the-document with verified quotes and no-evidence short circuit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Belge metadata çıkarma

**Files:**
- Create: `src/auditor/ingestion/metadata.py`, `tests/test_metadata.py`
- Modify: `src/auditor/ingestion/indexer.py`

**Interfaces:**
- Consumes: `ParsedDocument`; `date_to_int`, `InvalidDateError` (`auditor.index.store`); `complete_with_retry`, `LLMError` (Task 1)
- Produces:
  - `DocumentMetadata(doc_type: str | None, date: str | None, parties: list[str], jurisdiction: str | None)`
  - `first_pages_text(doc, max_pages=2, max_chars=8000) -> str`
  - `MetadataExtractor(provider)`, `__call__(doc) -> dict` — yalnızca dolu alanlar; hata olursa `{}`
  - `Indexer.ingest_pdf(path, metadata=None, *, extract_metadata=None)`, `Indexer.ingest_text(text, filename, metadata=None, *, extract_metadata=None)`; `MetadataFn = Callable[[ParsedDocument], dict]`. Öncelik: varsayılanlar < çıkarılan < kullanıcının verdiği.

- [ ] **Step 1: Testi yaz**

`tests/test_metadata.py`:

```python
from fakes import FakeEmbedder, FakeLLM, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import Indexer
from auditor.ingestion.metadata import DocumentMetadata, MetadataExtractor
from auditor.ingestion.parser import parse_pdf, parse_text
from auditor.llm.base import LLMError
from auditor.storage.docstore import DocumentStore


def test_extracted_values_are_cleaned(sample_contract):
    llm = FakeLLM({"DocumentMetadata": DocumentMetadata(
        doc_type="  Master Services Agreement ", date="March 1st, 2024",
        parties=["Acme Corp", " Acme Corp ", "", "Beta LLC"], jurisdiction="  ")})
    meta = MetadataExtractor(llm)(parse_text(sample_contract, "msa.txt"))
    assert meta == {"doc_type": "Master Services Agreement", "parties": ["Acme Corp", "Beta LLC"]}
    assert llm.calls[0][1] == "small"
    assert "MASTER SERVICES AGREEMENT" in llm.calls[0][2]


def test_iso_date_is_kept(sample_contract):
    llm = FakeLLM({"DocumentMetadata": DocumentMetadata(
        doc_type=None, date="2024-03-01", parties=[], jurisdiction="New York")})
    assert MetadataExtractor(llm)(parse_text(sample_contract, "msa.txt")) == {
        "date": "2024-03-01", "jurisdiction": "New York"}


def test_llm_failure_gives_empty_metadata(sample_contract):
    llm = FakeLLM({"DocumentMetadata": LLMError("down")})
    assert MetadataExtractor(llm)(parse_text(sample_contract, "msa.txt")) == {}


def test_only_first_two_pages_are_sent(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "c.pdf", [
        [("MASTER SERVICES AGREEMENT between Acme and Beta", 11)],
        [("1. Term", 11), ("This agreement lasts two years from signing.", 11)],
        [("SECRET PAGE THREE text that must not be sent", 11)],
    ])
    llm = FakeLLM({"DocumentMetadata": DocumentMetadata(doc_type=None, date=None, parties=[], jurisdiction=None)})
    MetadataExtractor(llm)(parse_pdf(path))
    prompt = llm.calls[0][2]
    assert "MASTER SERVICES AGREEMENT" in prompt and "two years" in prompt
    assert "SECRET PAGE THREE" not in prompt


def test_indexer_merges_extracted_under_user_metadata(tmp_path, sample_contract):
    store, docstore = QdrantStore.in_memory(), DocumentStore(tmp_path / "docs")
    indexer = Indexer(store, FakeEmbedder(), FakeSparseEncoder(), docstore)
    calls = []

    def extract(doc):
        calls.append(doc.document_id)
        return {"doc_type": "MSA", "jurisdiction": "New York"}

    result = indexer.ingest_text(sample_contract, "msa.txt", {"jurisdiction": "Delaware"},
                                 extract_metadata=extract)
    meta = docstore.metadata(result.document_id)
    assert (meta["doc_type"], meta["jurisdiction"], meta["filename"]) == ("MSA", "Delaware", "msa.txt")
    hits = store.search_dense(FakeEmbedder().embed_query("liability"), 5, SearchFilter(doc_types=["MSA"]))
    assert hits

    again = indexer.ingest_text(sample_contract, "msa.txt", extract_metadata=extract)
    assert again.already_indexed is True
    assert calls == [result.document_id]
```

- [ ] **Step 2: Testin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_metadata.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auditor.ingestion.metadata'`

- [ ] **Step 3: Çıkarıcıyı yaz**

`src/auditor/ingestion/metadata.py`:

```python
import logging

from pydantic import BaseModel

from auditor.index.store import InvalidDateError, date_to_int
from auditor.ingestion.parser import ParsedDocument
from auditor.llm.base import LLMError, LLMProvider, complete_with_retry

log = logging.getLogger(__name__)

MAX_PAGES = 2
MAX_CHARS = 8000

METADATA_SYSTEM = (
    "You extract metadata from the first pages of a contract. doc_type is a short contract type "
    "in English, such as 'Master Services Agreement' or 'Non-Disclosure Agreement'. date is the "
    "effective or signing date as YYYY-MM-DD. parties are the legal names of the contracting "
    "parties. jurisdiction is the governing law, such as 'New York' or 'England and Wales'. "
    "Use null, or an empty list for parties, when the text does not state a value."
)


class DocumentMetadata(BaseModel):
    doc_type: str | None
    date: str | None
    parties: list[str]
    jurisdiction: str | None


def first_pages_text(doc: ParsedDocument, max_pages: int = MAX_PAGES,
                     max_chars: int = MAX_CHARS) -> str:
    if doc.page_count:
        text = "\n".join(line.text for line in doc.lines
                         if line.page is not None and line.page <= max_pages)
    else:
        text = doc.text
    return text[:max_chars]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _iso_date(value: str | None) -> str | None:
    try:
        return value if date_to_int(value) is not None else None
    except InvalidDateError:
        return None


class MetadataExtractor:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    def __call__(self, doc: ParsedDocument) -> dict:
        text = first_pages_text(doc)
        if not text.strip():
            return {}
        try:
            result = complete_with_retry(self._provider, METADATA_SYSTEM, text,
                                         DocumentMetadata, "small")
        except LLMError as exc:
            log.warning("metadata extraction failed for %s: %s", doc.filename, exc)
            return {}
        meta = result.value
        values = {
            "doc_type": _clean(meta.doc_type),
            "date": _iso_date(_clean(meta.date)),
            "jurisdiction": _clean(meta.jurisdiction),
            "parties": list(dict.fromkeys(p.strip() for p in meta.parties if p.strip())),
        }
        return {key: value for key, value in values.items() if value}
```

- [ ] **Step 4: Indexer'a kancayı ekle**

`src/auditor/ingestion/indexer.py` içinde `Contextualizer` tanımının altına ekle:

```python
MetadataFn = Callable[[ParsedDocument], dict]
```

`ingest_pdf`, `ingest_text` ve `_index` metotlarını şununla değiştir:

```python
    def ingest_pdf(self, path: str | Path, metadata: dict | None = None, *,
                   extract_metadata: MetadataFn | None = None) -> IngestResult:
        doc = parse_pdf(path)
        return self._index(doc, metadata, Path(path).read_bytes(), extract_metadata)

    def ingest_text(self, text: str, filename: str, metadata: dict | None = None, *,
                    extract_metadata: MetadataFn | None = None) -> IngestResult:
        return self._index(parse_text(text, filename), metadata, None, extract_metadata)

    def _index(self, doc: ParsedDocument, metadata: dict | None, source_pdf: bytes | None,
               extract_metadata: MetadataFn | None) -> IngestResult:
        if self._docstore.exists(doc.document_id) and self._store.has_document(doc.document_id):
            return IngestResult(doc.document_id, 0, True)

        chunks = build_chunks(
            doc, detect_sections(doc.lines), self._max_child_tokens, self._max_parent_tokens
        )
        if not chunks:
            raise EmptyDocumentError(f"{doc.filename}: document has no text to index")

        meta = {
            "filename": doc.filename,
            "doc_type": None,
            "date": None,
            "parties": [],
            "jurisdiction": None,
            **(extract_metadata(doc) if extract_metadata else {}),
            **(metadata or {}),
        }
        if self._contextualizer:
            for chunk in chunks:
                chunk.context_prefix = self._contextualizer(doc, chunk)
        texts = [
            f"{chunk.context_prefix}\n\n{chunk.text}" if chunk.context_prefix else chunk.text
            for chunk in chunks
        ]

        # Save the text before the vectors: a search hit must always have a
        # document behind it. A failed upsert is retried by the next ingest.
        self._docstore.save(doc, meta, source_pdf)
        self._store.ensure_collection(self._embedder.dim)
        self._store.delete_document(doc.document_id)
        self._store.upsert(
            chunks,
            self._embedder.embed_documents(texts),
            self._sparse.encode_documents(texts),
            meta,
        )
        return IngestResult(doc.document_id, len(chunks), False)
```

- [ ] **Step 5: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_metadata.py tests/test_indexer.py -v`
Expected: tümü geçer (`test_metadata.py` 5 passed, `test_indexer.py` değişmeden geçer).

- [ ] **Step 6: Commit**

```bash
git add src/auditor/ingestion/metadata.py src/auditor/ingestion/indexer.py tests/test_metadata.py
git commit -m "feat: document metadata extraction at ingest

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Servis bağlantısı ve CLI (ask, audit)

**Files:**
- Modify: `src/auditor/services.py`, `src/auditor/cli.py`, `tests/test_cli.py`, `tests/fakes.py`
- Create: `.env.example`

**Interfaces:**
- Consumes: hepsi
- Produces:
  - `Services(indexer, retriever, docstore, store, audits: AuditStore, auditor: Auditor, provider: Callable[[str], LLMProvider], default_provider: str = "openai")`
  - CLI: `ingest PATH [--provider P] [--no-metadata]`, `search ...` (değişmedi), `ask QUESTION [--document ID ...] [--provider P]`, `audit DOCUMENT_ID PLAYBOOK [--provider P] [--force] [--json]`
  - `main()` ortamdan çalışırken önce `.env` dosyasını yükler.
  - `tests/fakes.py` `audit_llm` artık `QAOutput` ve `DocumentMetadata` yanıtlarını da içerir.

- [ ] **Step 1: Sahte LLM yanıtlarını genişlet**

`tests/fakes.py` içindeki `audit_llm` fonksiyonunu şununla değiştir:

```python
def audit_llm(**overrides) -> FakeLLM:
    """Responses for the test playbook in conftest: liability found, confidentiality missing."""
    from auditor.audit.prompts import Evaluation, Relevance, RewrittenQueries
    from auditor.ingestion.metadata import DocumentMetadata
    from auditor.qa.answer import QAOutput

    handlers = {
        "Evaluation": by_rule({
            "Liability cap": Evaluation(clause_found=True, matches_criteria=True,
                                        reasoning="Liability is capped at fees paid.",
                                        quotes=[LIABILITY_LINE]),
            "Confidentiality": Evaluation(clause_found=False, matches_criteria=False,
                                          reasoning="No confidentiality clause.", quotes=[]),
        }),
        "Relevance": Relevance(relevant=False),
        "RewrittenQueries": RewrittenQueries(queries=["secret information"]),
        "QAOutput": QAOutput(answer="Liability is capped at the fees paid in twelve months.",
                             quotes=[LIABILITY_LINE]),
        "DocumentMetadata": DocumentMetadata(doc_type="Services Agreement", date="2024-03-01",
                                             parties=["Acme Corp"], jurisdiction=None),
    }
    handlers.update(overrides)
    return FakeLLM(handlers)
```

- [ ] **Step 2: CLI testlerini güncelle**

`tests/test_cli.py` dosyasının başını (import'lar, `PAGES` ve `services` fixture'ı) şununla değiştir; mevcut test fonksiyonları aynen kalır:

```python
import json

import pytest
from fakes import CONTRACT_PAGES, FakeEmbedder, FakeLLM, FakeReranker, FakeSparseEncoder, audit_llm

from auditor.audit.runner import Auditor
from auditor.cli import main
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.retrieval.pipeline import Retriever
from auditor.services import Services
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentStore

PAGES = CONTRACT_PAGES


def _services(tmp_path, playbooks_dir, llm):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    retriever = Retriever(store, embedder, sparse, FakeReranker(), docstore)
    audits = AuditStore(tmp_path / "auditor.db")
    provider = lambda name: llm
    return Services(
        indexer=Indexer(store, embedder, sparse, docstore),
        retriever=retriever,
        docstore=docstore,
        store=store,
        audits=audits,
        auditor=Auditor(retriever, docstore, audits, playbooks_dir, provider),
        provider=provider,
        default_provider="openai",
    )


@pytest.fixture
def llm():
    return audit_llm()


@pytest.fixture
def services(tmp_path, playbooks_dir, llm):
    return _services(tmp_path, playbooks_dir, llm)


def _ingest(services, make_pdf, tmp_path, capsys) -> str:
    assert main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES))], services) == 0
    out = capsys.readouterr().out
    return out.strip().rsplit(" ", 1)[-1]
```

Dosyanın sonuna ekle:

```python
def test_ingest_extracts_metadata(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert services.docstore.metadata(doc_id)["doc_type"] == "Services Agreement"


def test_ingest_without_provider_still_indexes(tmp_path, playbooks_dir, make_pdf, capsys):
    down = _services(tmp_path, playbooks_dir, FakeLLM(unavailable="OPENAI_API_KEY is not set"))
    assert main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES))], down) == 0
    captured = capsys.readouterr()
    assert "metadata extraction skipped: OPENAI_API_KEY is not set" in captured.err
    assert "indexed 2 chunks" in captured.out


def test_ingest_no_metadata_skips_llm(services, llm, make_pdf, tmp_path):
    assert main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES)), "--no-metadata"], services) == 0
    assert llm.calls == []


def test_ask_prints_answer_and_citation(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["ask", "total liability fees paid", "--document", doc_id], services) == 0
    out = capsys.readouterr().out
    assert "Liability is capped at the fees paid in twelve months." in out
    assert '"The total liability shall not exceed' in out
    assert "(p2, " in out


def test_ask_without_evidence(services, make_pdf, tmp_path, capsys):
    _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["ask", "zebra quantum"], services) == 0
    assert "I could not find a statement" in capsys.readouterr().out


def test_audit_prints_findings_then_uses_cache(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["audit", doc_id, "test_pb"], services) == 0
    out = capsys.readouterr().out
    assert "risk 40.0" in out
    assert "uyumlu    high   liability_cap" in out
    assert "eksik     medium confidentiality" in out
    assert "(cached)" not in out

    assert main(["audit", doc_id, "test_pb"], services) == 0
    assert "(cached)" in capsys.readouterr().out


def test_audit_json_output(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["audit", doc_id, "test_pb", "--json"], services) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["risk_score"] == 40.0


def test_audit_errors_exit_with_1(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["audit", "0" * 64, "test_pb"], services) == 1
    assert "is not indexed" in capsys.readouterr().err
    assert main(["audit", doc_id, "missing"], services) == 1
    assert "available: test_pb" in capsys.readouterr().err
```

- [ ] **Step 3: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: FAIL — `TypeError: Services.__init__() got an unexpected keyword argument 'audits'`

- [ ] **Step 4: Servisleri bağla**

`src/auditor/services.py`:

```python
from dataclasses import dataclass
from typing import Callable

from auditor.audit.nodes import AuditConfig
from auditor.audit.runner import Auditor
from auditor.config import Settings
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.llm.base import LLMProvider
from auditor.llm.factory import cached_provider_factory
from auditor.retrieval.pipeline import Retriever
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentStore


@dataclass
class Services:
    indexer: Indexer
    retriever: Retriever
    docstore: DocumentStore
    store: QdrantStore
    audits: AuditStore
    auditor: Auditor
    provider: Callable[[str], LLMProvider]
    default_provider: str = "openai"


def build_services(settings: Settings) -> Services:
    from qdrant_client import QdrantClient

    from auditor.index.embedder import BgeM3Embedder, Bm25SparseEncoder
    from auditor.retrieval.reranker import BgeReranker

    if settings.qdrant_url:
        client = QdrantClient(url=settings.qdrant_url, timeout=60)
    else:
        qdrant_dir = settings.data_dir / "qdrant"
        qdrant_dir.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(qdrant_dir))

    store = QdrantStore(client, settings.collection)
    docstore = DocumentStore(settings.data_dir / "documents")
    embedder = BgeM3Embedder(settings.embed_model, settings.device)
    sparse = Bm25SparseEncoder()
    reranker = BgeReranker(settings.rerank_model, settings.device)
    retriever = Retriever(store, embedder, sparse, reranker, docstore)
    audits = AuditStore(settings.db_path)
    provider = cached_provider_factory(settings)
    auditor = Auditor(retriever, docstore, audits, settings.playbooks_dir, provider,
                      AuditConfig(concurrency=settings.audit_concurrency))
    return Services(
        indexer=Indexer(store, embedder, sparse, docstore),
        retriever=retriever,
        docstore=docstore,
        store=store,
        audits=audits,
        auditor=auditor,
        provider=provider,
        default_provider=settings.provider,
    )
```

- [ ] **Step 5: CLI'ı yaz**

`src/auditor/cli.py`:

```python
import argparse
import json
import sys
from dataclasses import replace

from dotenv import load_dotenv

from auditor.audit.playbook import PlaybookError
from auditor.config import Settings
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import EmptyDocumentError
from auditor.ingestion.metadata import MetadataExtractor
from auditor.ingestion.parser import InvalidPdfError, ScannedPdfError
from auditor.llm.base import LLMError, LLMProvider, ProviderUnavailableError
from auditor.llm.factory import PROVIDERS
from auditor.qa.answer import QuestionAnswerer
from auditor.retrieval.config import RetrievalConfig
from auditor.services import Services, build_services
from auditor.storage.docstore import DocumentNotFound


def _rank(rank: int | None) -> str:
    return f"#{rank}" if rank is not None else "-"


def _score(score: float | None) -> str:
    return f"{score:.3f}" if score is not None else "-"


def _provider(services: Services, name: str | None) -> LLMProvider:
    provider = services.provider(name or services.default_provider)
    provider.check_available()
    return provider


def _citation_line(citation: dict) -> str:
    page = f"p{citation['page']}" if citation["page"] is not None else "p-"
    return f'   "{citation["quote"][:160]}" ({page}, {citation["section_path"] or "-"})'


def _ingest(services: Services, args: argparse.Namespace) -> int:
    extractor = None
    if not args.no_metadata:
        try:
            extractor = MetadataExtractor(_provider(services, args.provider))
        except (ProviderUnavailableError, ValueError) as exc:
            print(f"warning: metadata extraction skipped: {exc}", file=sys.stderr)
    try:
        result = services.indexer.ingest_pdf(args.path, extract_metadata=extractor)
    except (InvalidPdfError, ScannedPdfError, EmptyDocumentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result.already_indexed:
        print(f"already indexed: {result.document_id}")
    else:
        print(f"indexed {result.chunk_count} chunks: {result.document_id}")
    return 0


def _search(services: Services, args: argparse.Namespace) -> int:
    config = RetrievalConfig(mode=args.mode, rerank=not args.no_rerank)
    if args.top:
        config = replace(config, final_k=args.top)
    result = services.retriever.search(args.query, config)
    if result.insufficient_evidence:
        print("no sufficient evidence")
    for chunk in result.chunks:
        s = chunk.scores
        print(
            f"{s.final_rank}. [{chunk.section_path}] p{chunk.pages} "
            f"bm25={_rank(s.bm25_rank)} dense={_rank(s.dense_rank)} "
            f"rrf={_score(s.rrf_score)} rerank={_score(s.rerank_score)} "
            f"change={s.rank_change:+d}"
        )
        print(f"   {chunk.text[:200]}")
    for parent in result.parents:
        print(f"parent [{parent.section_path}] chars {parent.char_start}-{parent.char_end}")
    return 0


def _ask(services: Services, args: argparse.Namespace) -> int:
    flt = SearchFilter(document_ids=args.document) if args.document else None
    try:
        answerer = QuestionAnswerer(services.retriever, services.docstore,
                                    _provider(services, args.provider))
        answer = answerer.ask(args.question, flt)
    except (ProviderUnavailableError, LLMError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not answer.found:
        print(answer.message)
        for passage in answer.passages:
            print(f"   nearest: [{passage.section_path}] {passage.text[:120]}")
        return 0
    print(answer.answer)
    for citation in answer.citations:
        print(_citation_line(citation.to_dict()))
    return 0


def _audit(services: Services, args: argparse.Namespace) -> int:
    try:
        report = services.auditor.run(args.document_id, args.playbook,
                                      args.provider or services.default_provider, force=args.force)
    except DocumentNotFound:
        print(f"error: document {args.document_id} is not indexed", file=sys.stderr)
        return 1
    except (PlaybookError, ProviderUnavailableError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    risk = "-" if report["risk_score"] is None else f"{report['risk_score']:.1f}"
    cached = " (cached)" if report["cached"] else ""
    print(f"audit {report['audit_id']}  risk {risk}  model {report['model']}{cached}")
    for finding in report["findings"]:
        evidence = finding["evidence"]
        print(f"{finding['status']:<9} {finding['severity']:<6} {finding['rule_id']}  "
              f"citations={len(finding['citations'])} queries={evidence['queries_tried']} "
              f"sections={evidence['sections_examined']}")
        if finding["error"]:
            print(f"   error: {finding['error']}")
        for citation in finding["citations"][:2]:
            print(_citation_line(citation))
    totals = report["totals"]
    print(f"duration {totals['duration_s']}s  tokens {totals['input_tokens']}/"
          f"{totals['output_tokens']}  cost ${totals['cost_usd']:.4f}")
    return 0


def main(argv: list[str] | None = None, services: Services | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auditor")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="index a PDF")
    ingest.add_argument("path")
    ingest.add_argument("--provider", choices=PROVIDERS)
    ingest.add_argument("--no-metadata", action="store_true")

    search = sub.add_parser("search", help="search indexed documents")
    search.add_argument("query")
    search.add_argument("--mode", choices=["bm25", "dense", "hybrid"], default="hybrid")
    search.add_argument("--no-rerank", action="store_true")
    search.add_argument("--top", type=int, default=0)

    ask = sub.add_parser("ask", help="answer a question with quotes")
    ask.add_argument("question")
    ask.add_argument("--document", action="append")
    ask.add_argument("--provider", choices=PROVIDERS)

    audit = sub.add_parser("audit", help="audit a document against a playbook")
    audit.add_argument("document_id")
    audit.add_argument("playbook")
    audit.add_argument("--provider", choices=PROVIDERS)
    audit.add_argument("--force", action="store_true")
    audit.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if services is None:
        load_dotenv()
        services = build_services(Settings.from_env())
    handlers = {"ingest": _ingest, "search": _search, "ask": _ask, "audit": _audit}
    return handlers[args.command](services, args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Ortam değişkeni örneğini ekle**

`.env.example`:

```
# Copy to .env and fill in. .env is git-ignored.
OPENAI_API_KEY=
# Optional: pin models; otherwise the newest gpt-N.N and gpt-N.N-mini in the account are used.
# OPENAI_EVAL_MODEL=gpt-5.5
# OPENAI_SMALL_MODEL=gpt-5.4-mini
# USD per 1M input/output tokens, for cost reporting: model=in/out,model=in/out
# OPENAI_PRICES=
AUDITOR_PROVIDER=openai
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
# AUDIT_CONCURRENCY=4
```

- [ ] **Step 7: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: 12 passed

- [ ] **Step 8: Tüm hızlı testleri çalıştır**

Run: `.venv/Scripts/python -m pytest -v`
Expected: tüm testler geçer; yalnız slow testler deselected.

- [ ] **Step 9: Commit**

```bash
git add src/auditor/services.py src/auditor/cli.py tests/test_cli.py tests/fakes.py .env.example
git commit -m "feat: CLI ask and audit commands, metadata on ingest, .env loading

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Gerçek OpenAI ile uçtan uca doğrulama

**Files:**
- Değişiklik beklenmez. Bir sorun çıkarsa düzeltme ilgili modülde yapılır, test eklenir ve ayrı commit atılır.

**Interfaces:**
- Consumes: CLI (Task 13), `.env` içindeki `OPENAI_API_KEY`
- Produces: kullanıcıya gözlem raporu

- [ ] **Step 1: Fiyatları kullanıcıya sor**

Maliyet raporu `OPENAI_PRICES` olmadan 0 gösterir. Kullanıcıya `gpt-5.5` ve `gpt-5.4-mini` için 1M token başına giriş/çıkış fiyatını sor veya openai.com/api/pricing sayfasından bulup öner. Kullanıcı onaylarsa `.env` dosyasına şu biçimde bir satır eklemesini iste (dosyayı kendin düzenleme, anahtarı okuma):

```
OPENAI_PRICES=gpt-5.5=<in>/<out>,gpt-5.4-mini=<in>/<out>
```

- [ ] **Step 2: Temiz bir veri dizininde indeksle**

Plan 1'deki `data/` dizinindeki örnek belge metadata'sız indekslendi; tekrar yüklemede atlanır. Ayrı dizin kullan:

```bash
export AUDITOR_DATA_DIR=data/plan2
.venv/Scripts/python -m auditor.cli ingest data/sample.pdf
```

Expected: `indexed 12 chunks: <id>` ve uyarı yok. Ardından metadata'yı kontrol et:

```bash
.venv/Scripts/python -c "
from auditor.storage.docstore import DocumentStore
s = DocumentStore('data/plan2/documents'); [print(s.metadata(i)) for i in s.list_ids()]"
```

Expected: `doc_type` "Master Services Agreement" benzeri, `parties` içinde `Acme Corp` ve `Beta LLC`, `jurisdiction` "New York" benzeri, `date` `None` (örnek metinde tarih yok).

- [ ] **Step 3: Belgeye sor**

```bash
.venv/Scripts/python -m auditor.cli ask "What is the cap on liability?"
.venv/Scripts/python -m auditor.cli ask "What is the warranty period for hardware?"
```

Expected: ilk soru alıntılı cevap verir ve alıntı `3.1` maddesindendir. İkinci soru "I could not find a statement…" yazar. İkinci soru cevap üretirse alıntısını ve `rerank` eşiğini not et (Plan 4 eşik ayarına girdi).

- [ ] **Step 4: Denetle**

```bash
.venv/Scripts/python -m auditor.cli audit <id> commercial_contract
.venv/Scripts/python -m auditor.cli audit <id> commercial_contract
```

Expected ilk çalıştırma:
- Başlık satırında `model gpt-5.5+gpt-5.4-mini`.
- `liability_cap` uyumlu (alıntı 3.1), `termination_notice` uyumlu (2.2, otuz gün), `governing_law` uyumlu (4.1), `confidentiality` eksik (`queries` ≥ 2, `sections` ≥ 1), `unlimited_liability` uyumlu.
- Risk `100 × 2 / 11 = 18.2` (ağırlıklar 3 + 2 + 1 + 2 + 3; yalnız `confidentiality` medium eksik).

İkinci çalıştırma `(cached)` gösterir ve anında döner.

Farklı bir durum çıkarsa `--json` çıktısındaki `reasoning` alanını ve `data/plan2/auditor.db` içindeki izi incele; gözlemi raporla. Model hatasından kaynaklanan sapma (ör. termination_notice'ın uyumsuz sayılması) başarısızlık sayılmaz; kod hatası (şema hatası, alıntının doğrulanamaması) düzeltilir.

- [ ] **Step 5: Kullanıcıya raporla**

Durumlar, risk puanı, süre, token ve maliyet; metadata değerleri; belgeye sor cevapları. Değişiklik yapıldıysa commit et.

---

### Task 15: Varsayılan Ollama modelini seçme

**Files:**
- Modify: `src/auditor/config.py`, `tests/test_config.py`, `.env.example` (yalnız seçilen model `qwen3:8b` değilse)

**Interfaces:**
- Consumes: CLI, `playbooks/commercial_contract.yaml`, Task 14'teki OpenAI denetim sonucu (referans)
- Produces: `OLLAMA_MODEL` varsayılanı

Bu task kullanıcının makinesinde Ollama gerektirir; şu an kurulu değil. Kullanıcı kurmak istemezse task'i atla, `qwen3:8b` geçici varsayılan olarak kalır ve seçim Plan 4 benchmark'ına ertelenir. Bunu kullanıcıya sor.

- [ ] **Step 1: Ollama'yı kur ve adayları indir (kullanıcı)**

Kullanıcıdan Ollama'yı ollama.com/download adresinden kurmasını iste, sonra:

```bash
ollama pull qwen3:8b
ollama pull llama3.1:8b
ollama pull granite3.3:8b
```

- [ ] **Step 2: Her adayla aynı denetimi çalıştır**

```bash
export AUDITOR_DATA_DIR=data/plan2
for m in qwen3:8b llama3.1:8b granite3.3:8b; do
  OLLAMA_MODEL=$m .venv/Scripts/python -m auditor.cli audit <id> commercial_contract --provider ollama --json > data/plan2/ollama_$m.json
done
```

Her dosya için şunları çıkar: `hata` sayısı (şema uyumsuzluğu), `belirsiz` sayısı (doğrulanamayan alıntı), Task 14'teki OpenAI durumlarıyla kaç kuralda aynı olduğu, `totals.duration_s`.

- [ ] **Step 3: Seç ve varsayılanı güncelle**

Sıralama: önce en az `hata`, sonra en az `belirsiz`, sonra OpenAI ile en çok eşleşme, sonra en kısa süre. Seçilen model `qwen3:8b` değilse `config.py` içindeki `OLLAMA_MODEL` varsayılanını, `tests/test_config.py` içindeki beklentiyi ve `.env.example` satırını değiştir.

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 4: Commit**

Karşılaştırma tablosunu commit mesajına yaz:

```bash
git add src/auditor/config.py tests/test_config.py .env.example
git commit -m "chore: pick default Ollama model from 5-rule comparison

<model | hata | belirsiz | OpenAI ile eşleşme | süre tablosu>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Bitiş

Tüm task'ler bitince:

```bash
.venv/Scripts/python -m pytest -v
git checkout master
git merge --no-ff plan-2-llm-audit-qa -m "Merge plan 2: LLM providers, audit agent, ask"
git push origin master
```
