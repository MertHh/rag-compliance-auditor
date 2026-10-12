# Plan 1: Ingestion ve Arama Hattı — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PDF veya düz metin sözleşmeyi yapısına göre parçalayıp Qdrant'a indeksleyen ve hybrid + rerank arama ile aşama skorlarını döndüren, komut satırından kullanılabilir bir çekirdek kütüphane.

**Architecture:** `src/auditor` altında saf Python kütüphanesi. Ingestion (parser → yapı tespiti → chunker) ve arama (filtre → BM25 + dense → RRF → rerank → parent genişletme) birbirinden bağımsız modüller; modeller ve vektör deposu küçük arayüzlerin arkasında, testler sahte modellerle ve bellek içi Qdrant ile çalışır.

**Tech Stack:** Python 3.11+, PyMuPDF, qdrant-client, fastembed (BM25), sentence-transformers (BGE-M3, BGE reranker), pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-rag-compliance-auditor-design.md` (bölüm 2, 3, 4)

## Plan dizisi

Spec dört plana bölündü. Bu doküman ilki.

1. **Ingestion ve arama hattı** (bu plan)
2. LLM sağlayıcıları, denetim ajanı, belgeye sor, SQLite kayıt deposu, belge metadata çıkarma
3. FastAPI ve Streamlit arayüzü
4. Benchmark, playbook'lar, Docker Compose, README

## Global Constraints

- Python `>=3.11`. Geliştirme ortamı Windows 11; komutlar `.venv/Scripts/python` ile çalıştırılır.
- Child chunk en fazla 400 token, parent en fazla 2000 token.
- Token tanımı: `\w+|[^\w\s]` regex eşleşmelerinin sayısı (`auditor.tokens.count_tokens`). Model tokenizer'ı kullanılmaz.
- `RetrievalConfig` varsayılanları: `mode="hybrid"`, `rerank=True`, `candidate_k=30`, `final_k=5`.
- Dense model `BAAI/bge-m3`, reranker `BAAI/bge-reranker-v2-m3`, sparse `Qdrant/bm25`.
- Varsayılan test koşusu ağ erişimi ve model indirme gerektirmez. Gerçek model kullanan testler `@pytest.mark.slow` ile işaretlenir.
- Arama kodu Qdrant'a doğrudan bağlanmaz; `VectorStore` arayüzünü kullanır.
- Kod, tanımlayıcılar ve hata mesajları İngilizce.
- Her commit mesajı şu satırla biter: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

Spec'in söylemediği ama kullanıcının karşılaşacağı durumlar. Her birinin testi ilgili task'e eklendi.

1. **Bozuk veya PDF olmayan dosya yüklenir** → traceback yerine `InvalidPdfError` (Task 2).
2. **Şifreli PDF yüklenir** → `InvalidPdfError`, mesajda "password" geçer (Task 2).
3. **Gövdede numaralı liste, "30 days…" gibi sayıyla başlayan satır, sayfa altlığı var** → yanlış başlık tespiti olsa bile metnin hiçbir karakteri kaybolmaz veya iki chunk'a girmez (Task 4).
4. **Boş veya yalnız boşluk içeren sorgu** → hata yerine boş sonuç ve `insufficient_evidence=True` (Task 10).
5. **Hiç belge indekslenmeden veya hiçbir şeyle eşleşmeyen filtreyle arama** → boş sonuç ve `insufficient_evidence=True` (Task 6, Task 10).

## File Structure

```
pyproject.toml
.gitignore
src/auditor/
  __init__.py
  tokens.py              count_tokens
  config.py              Settings (ortam değişkenleri)
  services.py            build_services: gerçek bileşenleri birbirine bağlar
  cli.py                 ingest / search komutları
  ingestion/
    __init__.py
    parser.py            PDF/metin → ParsedDocument (satırlar, ofsetler, bbox)
    structure.py         satırlar → Section listesi
    chunker.py           Section'lar → Chunk listesi (parent-child)
    indexer.py           Indexer: parse → chunk → embed → depo
  index/
    __init__.py
    store.py             VectorStore arayüzü, SparseVec, SearchFilter, Hit
    qdrant_store.py      QdrantStore
    embedder.py          Embedder, SparseEncoder arayüzleri ve gerçek sarmalayıcılar
  retrieval/
    __init__.py
    config.py            RetrievalConfig
    fusion.py            rrf_fuse
    reranker.py          Reranker arayüzü ve BgeReranker
    pipeline.py          Retriever ve sonuç tipleri
  storage/
    __init__.py
    docstore.py          DocumentStore: belge metni, satırlar, metadata, PDF dosyası
tests/
  conftest.py            make_pdf, sample_contract
  fakes.py               FakeEmbedder, FakeSparseEncoder, FakeReranker
  test_*.py
```

`storage/docstore.py` spec'in proje yapısında yok. Parent metinleri Qdrant'ta tekrar tekrar saklamak yerine belge metni bir kez diskte tutulur; parent, `(parent_start, parent_end)` aralığıyla bu metinden kesilir.

---

### Task 1: Proje iskeleti, token sayacı, ayarlar

**Files:**
- Create: `pyproject.toml`, `.gitignore`
- Create: `src/auditor/__init__.py`, `src/auditor/tokens.py`, `src/auditor/config.py`
- Create: `src/auditor/ingestion/__init__.py`, `src/auditor/index/__init__.py`, `src/auditor/retrieval/__init__.py`, `src/auditor/storage/__init__.py` (hepsi boş)
- Test: `tests/test_tokens.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: yok
- Produces:
  - `auditor.tokens.count_tokens(text: str) -> int`
  - `auditor.config.Settings` (frozen dataclass): `data_dir: Path`, `qdrant_url: str | None`, `collection: str`, `embed_model: str`, `rerank_model: str`, `device: str | None`; `Settings.from_env() -> Settings`

- [ ] **Step 1: Python sürümünü doğrula**

Run: `python --version`
Expected: `Python 3.11.x` veya üstü. Altındaysa dur ve kullanıcıya bildir.

- [ ] **Step 2: `pyproject.toml` ve `.gitignore` yaz**

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "auditor"
version = "0.1.0"
description = "Hybrid RAG compliance auditor"
requires-python = ">=3.11"
dependencies = [
    "pymupdf>=1.24",
    "qdrant-client>=1.12",
    "fastembed>=0.4",
    "sentence-transformers>=4.0",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.hatch.build.targets.wheel]
packages = ["src/auditor"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: downloads and runs real models"]
addopts = "-m 'not slow'"
```

`.gitignore`:

```
.venv/
data/
__pycache__/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 3: Sanal ortamı kur**

Windows'ta `pip install torch` varsayılan olarak CPU sürümünü kurar; CUDA sürümü önce ve ayrı kurulur.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cu124
mkdir -p src/auditor/ingestion src/auditor/index src/auditor/retrieval src/auditor/storage tests
touch src/auditor/__init__.py src/auditor/ingestion/__init__.py src/auditor/index/__init__.py src/auditor/retrieval/__init__.py src/auditor/storage/__init__.py
.venv/Scripts/python -m pip install -e ".[dev]"
```

Run: `.venv/Scripts/python -c "import torch; print(torch.cuda.is_available())"`
Expected: `True`. `False` çıkarsa veya `cu124` indeksi bu Python sürümü için paket bulamazsa, pytorch.org "Start Locally" seçicisinden (Windows, Pip, CUDA) güncel `--index-url` değerini al ve torch'u onunla yeniden kur.

- [ ] **Step 4: Başarısız testleri yaz**

`tests/test_tokens.py`:

```python
from auditor.tokens import count_tokens


def test_counts_words_and_punctuation_separately():
    assert count_tokens("Hello, world.") == 4


def test_numbered_clause_prefix():
    assert count_tokens("8.2 The Supplier") == 5


def test_empty_and_whitespace():
    assert count_tokens("") == 0
    assert count_tokens("  \n\t ") == 0


def test_turkish_letters_stay_in_one_token():
    assert count_tokens("İşbu sözleşme") == 2
```

`tests/test_config.py`:

```python
from pathlib import Path

from auditor.config import Settings


def test_defaults(monkeypatch):
    for name in ("AUDITOR_DATA_DIR", "QDRANT_URL", "AUDITOR_COLLECTION",
                 "EMBED_MODEL", "RERANK_MODEL", "AUDITOR_DEVICE"):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert s.data_dir == Path("data")
    assert s.qdrant_url is None
    assert s.collection == "chunks"
    assert s.embed_model == "BAAI/bge-m3"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert s.device is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("AUDITOR_DATA_DIR", "D:/x")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("AUDITOR_DEVICE", "cpu")
    s = Settings.from_env()
    assert s.data_dir == Path("D:/x")
    assert s.qdrant_url == "http://localhost:6333"
    assert s.device == "cpu"
```

- [ ] **Step 5: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_tokens.py tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.tokens'`

- [ ] **Step 6: Uygulamayı yaz**

`src/auditor/tokens.py`:

```python
import re

TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def count_tokens(text: str) -> int:
    return len(TOKEN_RE.findall(text))
```

`src/auditor/config.py`:

```python
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    qdrant_url: str | None
    collection: str
    embed_model: str
    rerank_model: str
    device: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("AUDITOR_DATA_DIR", "data")),
            qdrant_url=os.environ.get("QDRANT_URL") or None,
            collection=os.environ.get("AUDITOR_COLLECTION", "chunks"),
            embed_model=os.environ.get("EMBED_MODEL", "BAAI/bge-m3"),
            rerank_model=os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
            device=os.environ.get("AUDITOR_DEVICE") or None,
        )
```

- [ ] **Step 7: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_tokens.py tests/test_config.py -v`
Expected: 6 passed

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore src tests
git commit -m "feat: project scaffold, token counter, settings"
```

---

### Task 2: Parser

**Files:**
- Create: `src/auditor/ingestion/parser.py`
- Create: `tests/conftest.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: yok
- Produces:
  - `Line` (dataclass): `text: str`, `page: int | None`, `bbox: tuple[float, float, float, float] | None`, `font_size: float | None`, `char_start: int`, `char_end: int`
  - `ParsedDocument` (dataclass): `document_id: str`, `filename: str`, `text: str`, `lines: list[Line]`, `page_count: int`
  - `parse_pdf(path: str | Path) -> ParsedDocument`
  - `parse_text(text: str, filename: str) -> ParsedDocument`
  - `InvalidPdfError`, `ScannedPdfError` (ikisi de `Exception`)
  - Değişmez: `doc.text == "\n".join(l.text for l in doc.lines)` ve her satır için `doc.text[l.char_start:l.char_end] == l.text`. PDF'te bloklar arasına boş bir satır (`text=""`, `page=None`, `bbox=None`) eklenir. Sayfa numaraları 1'den başlar.
  - Test fixture'ları: `make_pdf(path, pages, password=None) -> Path` (`pages`: sayfa başına `(metin, yazı_boyutu)` listesi), `sample_contract: str`

- [ ] **Step 1: Fixture'ları yaz**

`tests/conftest.py`:

```python
from pathlib import Path

import fitz
import pytest

SAMPLE_CONTRACT = """MASTER SERVICES AGREEMENT

This Agreement is entered into between Acme Corp and Beta LLC.

1. Definitions
1.1 "Services" means the consulting services described in Exhibit A.
1.2 "Fees" means the amounts payable under Section 4.

2. Term and Termination
2.1 This Agreement commences on the Effective Date and continues for two years.
2.2 Either party may terminate this Agreement upon thirty (30) days written notice.

3. Limitation of Liability
3.1 The total aggregate liability of either party shall not exceed the fees paid in the twelve months preceding the claim.
3.2 Neither party shall be liable for indirect or consequential damages.

4. Governing Law
4.1 This Agreement is governed by the laws of the State of New York."""


@pytest.fixture
def sample_contract() -> str:
    return SAMPLE_CONTRACT


def _make_pdf(path, pages, password=None) -> Path:
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        y = 72.0
        for text, size in lines:
            page.insert_text((72, y), text, fontsize=size)
            y += size * 1.6
    if password:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256,
                 user_pw=password, owner_pw=password + "-owner")
    else:
        doc.save(str(path))
    doc.close()
    return Path(path)


@pytest.fixture
def make_pdf():
    return _make_pdf
```

- [ ] **Step 2: Başarısız testleri yaz**

`tests/test_parser.py`:

```python
import pytest

from auditor.ingestion.parser import (
    InvalidPdfError,
    ScannedPdfError,
    parse_pdf,
    parse_text,
)

PAGES = [
    [("MASTER SERVICES AGREEMENT", 16),
     ("1. Definitions and interpretation of this agreement", 11)],
    [("2. Term and termination of the services agreement here", 11)],
]


def test_parse_text_keeps_lines_and_offsets():
    doc = parse_text("First line\n\nSecond line", "a.txt")
    assert doc.text == "First line\n\nSecond line"
    assert [l.text for l in doc.lines] == ["First line", "", "Second line"]
    for line in doc.lines:
        assert doc.text[line.char_start:line.char_end] == line.text
        assert line.page is None and line.bbox is None
    assert doc.page_count == 0
    assert len(doc.document_id) == 64
    assert doc.filename == "a.txt"


def test_parse_text_normalizes_windows_newlines():
    assert parse_text("a\r\nb", "a.txt").text == "a\nb"


def test_parse_text_id_depends_on_content():
    assert parse_text("a", "x.txt").document_id == parse_text("a", "y.txt").document_id
    assert parse_text("a", "x.txt").document_id != parse_text("b", "x.txt").document_id


def test_parse_pdf_lines_carry_page_bbox_and_font(make_pdf, tmp_path):
    doc = parse_pdf(make_pdf(tmp_path / "c.pdf", PAGES))
    lines = [l for l in doc.lines if l.text]
    assert [l.text for l in lines] == [
        "MASTER SERVICES AGREEMENT",
        "1. Definitions and interpretation of this agreement",
        "2. Term and termination of the services agreement here",
    ]
    assert [l.page for l in lines] == [1, 1, 2]
    assert lines[0].font_size == pytest.approx(16, abs=0.1)
    assert lines[1].font_size == pytest.approx(11, abs=0.1)
    assert all(len(l.bbox) == 4 for l in lines)
    assert doc.page_count == 2
    assert doc.filename == "c.pdf"


def test_parse_pdf_text_matches_line_offsets(make_pdf, tmp_path):
    doc = parse_pdf(make_pdf(tmp_path / "c.pdf", PAGES))
    assert doc.text == "\n".join(l.text for l in doc.lines)
    for line in doc.lines:
        assert doc.text[line.char_start:line.char_end] == line.text


def test_parse_pdf_id_is_stable_across_filenames(make_pdf, tmp_path):
    first = make_pdf(tmp_path / "a.pdf", PAGES)
    second = tmp_path / "b.pdf"
    second.write_bytes(first.read_bytes())
    assert parse_pdf(first).document_id == parse_pdf(second).document_id


def test_corrupt_file_raises_invalid_pdf(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not a pdf")
    with pytest.raises(InvalidPdfError):
        parse_pdf(path)


def test_missing_file_raises_invalid_pdf(tmp_path):
    with pytest.raises(InvalidPdfError):
        parse_pdf(tmp_path / "nope.pdf")


def test_encrypted_pdf_raises_invalid_pdf(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "locked.pdf", PAGES, password="secret")
    with pytest.raises(InvalidPdfError, match="password"):
        parse_pdf(path)


def test_pdf_without_text_layer_raises_scanned(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "scan.pdf", [[], []])
    with pytest.raises(ScannedPdfError):
        parse_pdf(path)
```

- [ ] **Step 3: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_parser.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.ingestion.parser'`

- [ ] **Step 4: Uygulamayı yaz**

`src/auditor/ingestion/parser.py`:

```python
import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz

MIN_CHARS_PER_PAGE = 50

BBox = tuple[float, float, float, float]


class InvalidPdfError(Exception):
    pass


class ScannedPdfError(Exception):
    pass


@dataclass
class Line:
    text: str
    page: int | None
    bbox: BBox | None
    font_size: float | None
    char_start: int
    char_end: int


@dataclass
class ParsedDocument:
    document_id: str
    filename: str
    text: str
    lines: list[Line]
    page_count: int


def _assemble(raw: list[tuple[str, int | None, BBox | None, float | None]]) -> tuple[str, list[Line]]:
    lines, pos = [], 0
    for text, page, bbox, size in raw:
        lines.append(Line(text, page, bbox, size, pos, pos + len(text)))
        pos += len(text) + 1
    return "\n".join(line.text for line in lines), lines


def parse_text(text: str, filename: str) -> ParsedDocument:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    document_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    full, lines = _assemble([(t, None, None, None) for t in normalized.split("\n")])
    return ParsedDocument(document_id, filename, full, lines, 0)


def parse_pdf(path: str | Path) -> ParsedDocument:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InvalidPdfError(f"{path.name}: cannot read file") from exc
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InvalidPdfError(f"{path.name}: not a valid PDF") from exc
    with pdf:
        if pdf.needs_pass:
            raise InvalidPdfError(f"{path.name}: PDF is password protected")
        if pdf.page_count == 0:
            raise InvalidPdfError(f"{path.name}: PDF has no pages")
        raw: list[tuple[str, int | None, BBox | None, float | None]] = []
        for page_index, page in enumerate(pdf):
            for block in page.get_text("dict", sort=True)["blocks"]:
                if block.get("type") != 0:
                    continue
                block_lines = []
                for line in block["lines"]:
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    if not text:
                        continue
                    size = max(span["size"] for span in line["spans"])
                    bbox = tuple(round(v, 2) for v in line["bbox"])
                    block_lines.append((text, page_index + 1, bbox, round(size, 2)))
                if block_lines:
                    if raw:
                        raw.append(("", None, None, None))
                    raw.extend(block_lines)
        page_count = pdf.page_count
    text, lines = _assemble(raw)
    if len(text.strip()) < MIN_CHARS_PER_PAGE * page_count:
        raise ScannedPdfError(f"{path.name}: document is scanned, no text layer")
    return ParsedDocument(hashlib.sha256(data).hexdigest(), path.name, text, lines, page_count)
```

- [ ] **Step 5: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_parser.py -v`
Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add src/auditor/ingestion/parser.py tests/conftest.py tests/test_parser.py
git commit -m "feat: PDF and text parser with line offsets and bboxes"
```

---

### Task 3: Yapı tespiti

**Files:**
- Create: `src/auditor/ingestion/structure.py`
- Test: `tests/test_structure.py`

**Interfaces:**
- Consumes: `Line`, `parse_text` (`auditor.ingestion.parser`)
- Produces:
  - `Section` (dataclass): `number: str | None`, `title: str`, `level: int`, `path: str`, `line_start: int`, `line_end: int` (hariç)
  - `detect_sections(lines: list[Line]) -> list[Section]`
  - Değişmez: dönen section'lar belge sırasındadır, `sections[0].line_start == 0`, `sections[-1].line_end == len(lines)` ve her biri bir öncekinin bittiği satırda başlar. Başlık yoksa tek section döner (`title="Document"`, `path="Document"`).
  - `path`: üst başlıkların etiketleri ` > ` ile birleştirilir; etiket, varsa `number`, yoksa `title` (örn. `8 > 8.2`).

Başlık kuralları:

- `ARTICLE|Article|SECTION|Section|MADDE|Madde` + Roma rakamı veya sayı → seviye 1. Sayıdan sonra `.rakam` geliyorsa (`Section 5.2 of…`) başlık değildir.
- `N.` veya `N.N…` ile başlayan satır → seviye = sayı bileşeni adedi. Tek bileşenli sayıda nokta zorunludur (`30 days` başlık değildir).
- İki kuralda da numaradan sonraki metin küçük harfle başlıyorsa başlık değildir.
- Belgede Article/Section/Madde başlığı varsa numaralı başlıkların seviyesi 1 artar.
- Yazı boyutu gövde medyanının en az 1.15 katı olan, 100 karakterden kısa, harf içeren satır → seviye 1, numarasız başlık.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_structure.py`:

```python
from auditor.ingestion.parser import Line, parse_text
from auditor.ingestion.structure import detect_sections


def _sections(text):
    return detect_sections(parse_text(text, "t.txt").lines)


def test_numbered_hierarchy_builds_paths(sample_contract):
    sections = _sections(sample_contract)
    assert [s.path for s in sections] == [
        "Preamble",
        "1", "1 > 1.1", "1 > 1.2",
        "2", "2 > 2.1", "2 > 2.2",
        "3", "3 > 3.1", "3 > 3.2",
        "4", "4 > 4.1",
    ]
    liability = sections[7]
    assert liability.number == "3"
    assert liability.title == "Limitation of Liability"
    assert liability.level == 1
    assert sections[8].level == 2


def test_sections_are_contiguous_and_cover_all_lines(sample_contract):
    lines = parse_text(sample_contract, "t.txt").lines
    sections = detect_sections(lines)
    assert sections[0].line_start == 0
    assert sections[-1].line_end == len(lines)
    for prev, cur in zip(sections, sections[1:]):
        assert prev.line_end == cur.line_start


def test_no_headings_gives_single_section():
    sections = _sections("just some text\nwithout any structure")
    assert len(sections) == 1
    assert (sections[0].title, sections[0].path) == ("Document", "Document")
    assert (sections[0].line_start, sections[0].line_end) == (0, 2)


def test_first_heading_at_top_has_no_preamble():
    sections = _sections("\n1. Scope\nText here")
    assert [s.path for s in sections] == ["1"]
    assert sections[0].line_start == 0


def test_lines_starting_with_numbers_are_not_headings():
    text = "1. Payment\nPayment is due within\n30 days after the invoice date and\n2 copies of each invoice are required."
    assert [s.path for s in _sections(text)] == ["1"]


def test_lowercase_after_number_is_not_a_heading():
    assert [s.path for s in _sections("1. Scope\n2. the parties agree")] == ["1"]


def test_cross_reference_at_line_start_is_not_a_heading():
    text = "1. Scope\nSection 5.2 of this Agreement applies.\nSection 7 of this Agreement also applies."
    assert [s.path for s in _sections(text)] == ["1"]


def test_article_headings_push_numbered_clauses_down():
    text = "ARTICLE IV - PAYMENT\n4.1 Fees are due monthly.\nARTICLE V\n5.1 Term is one year."
    sections = _sections(text)
    assert [s.path for s in sections] == ["IV", "IV > 4.1", "V", "V > 5.1"]
    assert sections[0].title == "PAYMENT"
    assert sections[2].title == "ARTICLE V"


def test_turkish_madde_heading():
    sections = _sections("Madde 5 - Fesih\nTaraflar otuz gün önceden bildirerek feshedebilir.")
    assert sections[0].number == "5"
    assert sections[0].title == "Fesih"


def test_title_is_cut_at_first_sentence_and_80_chars():
    sections = _sections("1. Fees. The Customer shall pay.\n2. " + "A" * 200)
    assert sections[0].title == "Fees"
    assert len(sections[1].title) == 80


def test_large_font_line_is_a_heading():
    def line(text, size, pos):
        return Line(text, 1, (0.0, 0.0, 1.0, 1.0), size, pos, pos + len(text))

    lines = [
        line("Confidentiality", 16.0, 0),
        line("Each party keeps the other party's information secret.", 11.0, 16),
        line("The obligation survives termination of the agreement.", 11.0, 71),
    ]
    sections = detect_sections(lines)
    assert [s.path for s in sections] == ["Confidentiality"]
    assert sections[0].number is None
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_structure.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.ingestion.structure'`

- [ ] **Step 3: Uygulamayı yaz**

`src/auditor/ingestion/structure.py`:

```python
import re
import statistics
from dataclasses import dataclass

from auditor.ingestion.parser import Line

_ARTICLE = re.compile(
    r"^(ARTICLE|Article|SECTION|Section|MADDE|Madde)\s+([IVXLCDM]+|\d{1,3})(?!\.\d)\b"
    r"\s*[.:\-–—]?\s*(.*)$"
)
_NUMBERED = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)(\.?)\s+(\S.*)$")
_TITLE_END = re.compile(r"(?<=[.:;])\s")

FONT_HEADING_RATIO = 1.15
FONT_HEADING_MAX_CHARS = 100
TITLE_MAX_CHARS = 80


@dataclass
class Section:
    number: str | None
    title: str
    level: int
    path: str
    line_start: int
    line_end: int


def _titleish(rest: str) -> bool:
    return rest == "" or not rest[0].islower()


def _title(rest: str) -> str:
    return _TITLE_END.split(rest, maxsplit=1)[0].strip(" .:;-–—")[:TITLE_MAX_CHARS]


def _classify(text: str) -> tuple[str, str, str] | None:
    m = _ARTICLE.match(text)
    if m and _titleish(m.group(3)):
        return "article", m.group(2), _title(m.group(3)) or f"{m.group(1)} {m.group(2)}"
    m = _NUMBERED.match(text)
    if m:
        number, dot, rest = m.groups()
        if ("." in number or dot) and _titleish(rest):
            return "numbered", number, _title(rest)
    return None


def detect_sections(lines: list[Line]) -> list[Section]:
    classified = [_classify(line.text.strip()) for line in lines]
    offset = 1 if any(c and c[0] == "article" for c in classified) else 0
    sizes = [l.font_size for l in lines if l.font_size and l.text.strip()]
    body_size = statistics.median(sizes) if sizes else None

    heads: list[tuple[int, str | None, str, int]] = []
    for i, (line, c) in enumerate(zip(lines, classified)):
        text = line.text.strip()
        if c:
            kind, number, title = c
            level = 1 if kind == "article" else number.count(".") + 1 + offset
            heads.append((i, number, title, level))
        elif (
            body_size
            and line.font_size
            and line.font_size >= body_size * FONT_HEADING_RATIO
            and len(text) <= FONT_HEADING_MAX_CHARS
            and any(ch.isalpha() for ch in text)
        ):
            heads.append((i, None, text[:TITLE_MAX_CHARS], 1))

    if not heads:
        return [Section(None, "Document", 1, "Document", 0, len(lines))]

    sections: list[Section] = []
    first = heads[0][0]
    has_preamble = any(line.text.strip() for line in lines[:first])
    if has_preamble:
        sections.append(Section(None, "Preamble", 1, "Preamble", 0, first))

    stack: list[tuple[int, str]] = []
    for n, (i, number, title, level) in enumerate(heads):
        start = i if (n > 0 or has_preamble) else 0
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        label = number or title
        while stack and stack[-1][0] >= level:
            stack.pop()
        path = " > ".join([s[1] for s in stack] + [label])
        stack.append((level, label))
        sections.append(Section(number, title, level, path, start, end))
    return sections
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_structure.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/ingestion/structure.py tests/test_structure.py
git commit -m "feat: section detection from numbering and font size"
```

---

### Task 4: Chunker

**Files:**
- Create: `src/auditor/ingestion/chunker.py`
- Test: `tests/test_chunker.py`

**Interfaces:**
- Consumes: `ParsedDocument`, `parse_text`, `parse_pdf` (`auditor.ingestion.parser`); `Section`, `detect_sections` (`auditor.ingestion.structure`); `count_tokens`, `TOKEN_RE` (`auditor.tokens`)
- Produces:
  - `PageBox` (frozen dataclass): `page: int`, `bbox: tuple[float, float, float, float]`
  - `Chunk` (dataclass): `chunk_id: str`, `document_id: str`, `text: str`, `char_start: int`, `char_end: int`, `pages: list[int]`, `bboxes: list[PageBox]`, `section_title: str`, `section_path: str`, `parent_id: str`, `parent_start: int`, `parent_end: int`, `parent_section_path: str`, `context_prefix: str = ""`
  - `split_span(text: str, start: int, end: int, max_tokens: int) -> list[tuple[int, int]]`
  - `locate(doc: ParsedDocument, start: int, end: int) -> list[PageBox]` (aralıkla kesişen satırların kutuları; düz metinde boş liste)
  - `build_chunks(doc: ParsedDocument, sections: list[Section], max_child_tokens: int = 400, max_parent_tokens: int = 2000) -> list[Chunk]`
  - `chunk_id` bir UUID dizgisidir: `uuid5(NAMESPACE_URL, f"{document_id}:{char_start}-{char_end}")`. `parent_id == f"{document_id}:{parent_start}-{parent_end}"`.
  - Değişmez: `chunk.text == doc.text[chunk.char_start:chunk.char_end]`.

Parent seçimi: child'ın section'ından en üst ataya kadar olan zincirde, yukarıdan aşağıya, alt ağacı `max_parent_tokens` sınırına sığan ilk section parent olur. Hiçbiri sığmazsa parent child'ın kendisidir.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_chunker.py`:

```python
from auditor.ingestion.chunker import build_chunks, locate
from auditor.ingestion.parser import parse_pdf, parse_text
from auditor.ingestion.structure import detect_sections
from auditor.tokens import count_tokens


def _chunks(text, **kwargs):
    doc = parse_text(text, "t.txt")
    return doc, build_chunks(doc, detect_sections(doc.lines), **kwargs)


def test_child_carries_section_metadata_and_parent(sample_contract):
    doc, chunks = _chunks(sample_contract)
    chunk = next(c for c in chunks if c.section_path == "3 > 3.1")
    assert chunk.text.startswith("3.1 The total aggregate liability")
    assert doc.text[chunk.char_start:chunk.char_end] == chunk.text
    parent = doc.text[chunk.parent_start:chunk.parent_end]
    assert parent.startswith("3. Limitation of Liability")
    assert "3.2 Neither party" in parent
    assert "4. Governing Law" not in parent
    assert chunk.parent_section_path == "3"
    assert chunk.parent_id == f"{doc.document_id}:{chunk.parent_start}-{chunk.parent_end}"
    assert chunk.document_id == doc.document_id
    assert chunk.context_prefix == ""


def test_chunks_in_one_small_section_share_a_parent(sample_contract):
    _, chunks = _chunks(sample_contract)
    parents = {c.parent_id for c in chunks if c.section_path.split(" > ")[0] == "3"}
    assert len(parents) == 1


def test_chunk_ids_are_unique_and_stable(sample_contract):
    _, first = _chunks(sample_contract)
    _, second = _chunks(sample_contract)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert len({c.chunk_id for c in first}) == len(first)


def test_parent_falls_back_to_subsection_when_top_section_is_too_large():
    body = " ".join(["word"] * 30) + "."
    doc, chunks = _chunks(f"1. Big\n1.1 Alpha {body}\n1.2 Beta {body}", max_parent_tokens=40)
    chunk = next(c for c in chunks if c.section_path == "1 > 1.1")
    assert chunk.parent_section_path == "1 > 1.1"
    assert count_tokens(doc.text[chunk.parent_start:chunk.parent_end]) <= 40


def test_parent_is_the_child_itself_when_nothing_fits():
    doc, chunks = _chunks(" ".join(["tok"] * 300), max_child_tokens=100, max_parent_tokens=50)
    for chunk in chunks:
        assert (chunk.parent_start, chunk.parent_end) == (chunk.char_start, chunk.char_end)


def test_long_section_is_split_at_sentences_within_limit():
    sentences = " ".join(f"Sentence number {i} has several words in it." for i in range(60))
    _, chunks = _chunks("1. Long\n" + sentences, max_child_tokens=50)
    assert len(chunks) > 1
    assert all(count_tokens(c.text) <= 50 for c in chunks)
    assert all(c.text.endswith(".") or c.text.endswith("Long") for c in chunks)


def test_text_without_punctuation_is_hard_split():
    _, chunks = _chunks(" ".join(["tok"] * 500), max_child_tokens=100)
    assert len(chunks) == 5
    assert all(count_tokens(c.text) == 100 for c in chunks)


def test_every_non_whitespace_char_is_in_exactly_one_chunk(sample_contract):
    noisy = (
        sample_contract
        + "\n\nThe supplier shall deliver:\n1. apples\n2. Oranges and pears\n"
        + "30 days after delivery\nPage 3 of 12\n4.2 Late Delivery. Penalties apply.\n"
    )
    doc, chunks = _chunks(noisy, max_child_tokens=30)
    covered = [0] * len(doc.text)
    for chunk in chunks:
        for i in range(chunk.char_start, chunk.char_end):
            covered[i] += 1
    assert max(covered) == 1
    for i, ch in enumerate(doc.text):
        if not ch.isspace():
            assert covered[i] == 1, f"char {i!r} {ch!r} not covered"


def test_empty_document_gives_no_chunks():
    _, chunks = _chunks("   \n\n  ")
    assert chunks == []


def test_pdf_chunks_have_pages_and_bboxes(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "c.pdf", [
        [("1. Definitions", 11),
         ("Services means the consulting services described in Exhibit A.", 11)],
        [("2. Liability", 11),
         ("The total liability shall not exceed the fees paid in twelve months.", 11)],
    ])
    doc = parse_pdf(path)
    chunks = build_chunks(doc, detect_sections(doc.lines))
    by_path = {c.section_path: c for c in chunks}
    assert by_path["1"].pages == [1]
    assert by_path["2"].pages == [2]
    assert len(by_path["2"].bboxes) == 2
    assert all(len(box.bbox) == 4 and box.page == 2 for box in by_path["2"].bboxes)


def test_locate_returns_only_lines_overlapping_the_span(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "c.pdf", [
        [("1. Definitions and the interpretation of all terms", 11),
         ("Services means the consulting services in Exhibit A.", 11)],
    ])
    doc = parse_pdf(path)
    start = doc.text.index("consulting")
    boxes = locate(doc, start, start + len("consulting"))
    assert len(boxes) == 1
    assert boxes[0].page == 1
    assert locate(parse_text("plain", "t.txt"), 0, 5) == []
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_chunker.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.ingestion.chunker'`

- [ ] **Step 3: Uygulamayı yaz**

`src/auditor/ingestion/chunker.py`:

```python
import re
import uuid
from dataclasses import dataclass

from auditor.ingestion.parser import ParsedDocument
from auditor.ingestion.structure import Section
from auditor.tokens import TOKEN_RE, count_tokens

_PARA_SEP = re.compile(r"\n\s*\n")
_SENT_SEP = re.compile(r"(?<=[.;:!?])\s+")

Span = tuple[int, int]


@dataclass(frozen=True)
class PageBox:
    page: int
    bbox: tuple[float, float, float, float]


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    char_start: int
    char_end: int
    pages: list[int]
    bboxes: list[PageBox]
    section_title: str
    section_path: str
    parent_id: str
    parent_start: int
    parent_end: int
    parent_section_path: str
    context_prefix: str = ""


def _trim(text: str, start: int, end: int) -> Span:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_on(text: str, start: int, end: int, sep: re.Pattern) -> list[Span]:
    spans, pos = [], start
    for m in sep.finditer(text, start, end):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < end:
        spans.append((pos, end))
    return spans


def _hard_split(text: str, start: int, end: int, max_tokens: int) -> list[Span]:
    tokens = list(TOKEN_RE.finditer(text, start, end))
    return [
        (tokens[i].start(), tokens[min(i + max_tokens, len(tokens)) - 1].end())
        for i in range(0, len(tokens), max_tokens)
    ]


def _pack(text: str, units: list[Span], max_tokens: int) -> list[Span]:
    out: list[Span] = []
    current: Span | None = None
    for start, end in units:
        if current is None:
            current = (start, end)
        elif count_tokens(text[current[0]:end]) <= max_tokens:
            current = (current[0], end)
        else:
            out.append(current)
            current = (start, end)
    if current is not None:
        out.append(current)
    return out


def split_span(text: str, start: int, end: int, max_tokens: int) -> list[Span]:
    if count_tokens(text[start:end]) <= max_tokens:
        return [(start, end)]
    units: list[Span] = []
    for p_start, p_end in _split_on(text, start, end, _PARA_SEP):
        if count_tokens(text[p_start:p_end]) <= max_tokens:
            units.append((p_start, p_end))
            continue
        for s_start, s_end in _split_on(text, p_start, p_end, _SENT_SEP):
            if count_tokens(text[s_start:s_end]) <= max_tokens:
                units.append((s_start, s_end))
            else:
                units.extend(_hard_split(text, s_start, s_end, max_tokens))
    return _pack(text, units, max_tokens)


def locate(doc: ParsedDocument, start: int, end: int) -> list[PageBox]:
    return [
        PageBox(line.page, line.bbox)
        for line in doc.lines
        if line.bbox is not None and line.char_start < end and line.char_end > start
    ]


def _line_span(doc: ParsedDocument, line_start: int, line_end: int) -> Span:
    return doc.lines[line_start].char_start, doc.lines[line_end - 1].char_end


def _subtree_end(sections: list[Section], i: int) -> int:
    for j in range(i + 1, len(sections)):
        if sections[j].level <= sections[i].level:
            return sections[j].line_start
    return sections[-1].line_end


def _ancestors(sections: list[Section], i: int) -> list[int]:
    chain, level = [], sections[i].level
    for j in range(i - 1, -1, -1):
        if sections[j].level < level:
            chain.append(j)
            level = sections[j].level
    return list(reversed(chain))


def _pick_parent(
    doc: ParsedDocument, sections: list[Section], i: int, max_tokens: int
) -> tuple[int, int, str] | None:
    for idx in _ancestors(sections, i) + [i]:
        raw = _line_span(doc, sections[idx].line_start, _subtree_end(sections, idx))
        start, end = _trim(doc.text, *raw)
        if start < end and count_tokens(doc.text[start:end]) <= max_tokens:
            return start, end, sections[idx].path
    return None


def build_chunks(
    doc: ParsedDocument,
    sections: list[Section],
    max_child_tokens: int = 400,
    max_parent_tokens: int = 2000,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, section in enumerate(sections):
        if section.line_start >= section.line_end:
            continue
        start, end = _trim(doc.text, *_line_span(doc, section.line_start, section.line_end))
        if start >= end:
            continue
        parent = _pick_parent(doc, sections, i, max_parent_tokens)
        for raw_start, raw_end in split_span(doc.text, start, end, max_child_tokens):
            c_start, c_end = _trim(doc.text, raw_start, raw_end)
            if c_start >= c_end:
                continue
            p_start, p_end, p_path = parent or (c_start, c_end, section.path)
            boxes = locate(doc, c_start, c_end)
            chunks.append(Chunk(
                chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc.document_id}:{c_start}-{c_end}")),
                document_id=doc.document_id,
                text=doc.text[c_start:c_end],
                char_start=c_start,
                char_end=c_end,
                pages=sorted({box.page for box in boxes}),
                bboxes=boxes,
                section_title=section.title,
                section_path=section.path,
                parent_id=f"{doc.document_id}:{p_start}-{p_end}",
                parent_start=p_start,
                parent_end=p_end,
                parent_section_path=p_path,
            ))
    return chunks
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_chunker.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/ingestion/chunker.py tests/test_chunker.py
git commit -m "feat: structure-aware parent-child chunker"
```

---

### Task 5: Belge deposu

**Files:**
- Create: `src/auditor/storage/docstore.py`
- Test: `tests/test_docstore.py`

**Interfaces:**
- Consumes: `ParsedDocument`, `Line`, `parse_text` (`auditor.ingestion.parser`)
- Produces:
  - `DocumentNotFound(KeyError)`
  - `DocumentStore(root: str | Path)`:
    - `save(doc: ParsedDocument, metadata: dict, source_pdf: bytes | None = None) -> None`
    - `exists(document_id: str) -> bool`
    - `load(document_id: str) -> ParsedDocument`
    - `metadata(document_id: str) -> dict`
    - `update_metadata(document_id: str, updates: dict) -> dict` (birleştirilmiş metadata'yı döner)
    - `list_ids() -> list[str]` (sıralı)
    - `pdf_path(document_id: str) -> Path | None`
  - Diskte `{root}/{document_id}.json` ve varsa `{root}/{document_id}.pdf`.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_docstore.py`:

```python
import pytest

from auditor.ingestion.parser import Line, ParsedDocument, parse_text
from auditor.storage.docstore import DocumentNotFound, DocumentStore


def test_save_and_load_roundtrip_from_disk(tmp_path):
    doc = ParsedDocument(
        document_id="abc",
        filename="c.pdf",
        text="Hello\nİşbu sözleşme",
        lines=[Line("Hello", 1, (1.0, 2.0, 3.0, 4.0), 11.0, 0, 5),
               Line("İşbu sözleşme", 2, (5.0, 6.0, 7.0, 8.0), 11.0, 6, 19)],
        page_count=2,
    )
    DocumentStore(tmp_path).save(doc, {"filename": "c.pdf"})
    loaded = DocumentStore(tmp_path).load("abc")
    assert loaded == doc
    assert isinstance(loaded.lines[0].bbox, tuple)


def test_exists_and_list_ids(tmp_path):
    store = DocumentStore(tmp_path)
    assert store.exists("x") is False
    assert store.list_ids() == []
    b = parse_text("b", "b.txt")
    a = parse_text("a", "a.txt")
    store.save(b, {})
    store.save(a, {})
    assert store.exists(a.document_id)
    assert store.list_ids() == sorted([a.document_id, b.document_id])


def test_load_missing_raises(tmp_path):
    store = DocumentStore(tmp_path)
    with pytest.raises(DocumentNotFound):
        store.load("missing")
    with pytest.raises(DocumentNotFound):
        store.metadata("missing")


def test_metadata_update_merges_and_persists(tmp_path):
    doc = parse_text("a", "a.txt")
    DocumentStore(tmp_path).save(doc, {"filename": "a.txt", "doc_type": None})
    merged = DocumentStore(tmp_path).update_metadata(doc.document_id, {"doc_type": "NDA"})
    assert merged == {"filename": "a.txt", "doc_type": "NDA"}
    assert DocumentStore(tmp_path).metadata(doc.document_id) == merged


def test_pdf_bytes_are_kept(tmp_path):
    store = DocumentStore(tmp_path)
    with_pdf = parse_text("a", "a.pdf")
    without_pdf = parse_text("b", "b.txt")
    store.save(with_pdf, {}, source_pdf=b"%PDF-bytes")
    store.save(without_pdf, {})
    assert store.pdf_path(with_pdf.document_id).read_bytes() == b"%PDF-bytes"
    assert store.pdf_path(without_pdf.document_id) is None


def test_root_directory_is_created(tmp_path):
    root = tmp_path / "nested" / "docs"
    DocumentStore(root)
    assert root.is_dir()
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_docstore.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.storage.docstore'`

- [ ] **Step 3: Uygulamayı yaz**

`src/auditor/storage/docstore.py`:

```python
import json
from dataclasses import asdict
from pathlib import Path

from auditor.ingestion.parser import Line, ParsedDocument


class DocumentNotFound(KeyError):
    pass


class DocumentStore:
    def __init__(self, root: str | Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, ParsedDocument] = {}

    def _json_path(self, document_id: str) -> Path:
        return self._root / f"{document_id}.json"

    def _read(self, document_id: str) -> dict:
        path = self._json_path(document_id)
        if not path.exists():
            raise DocumentNotFound(document_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, document_id: str, payload: dict) -> None:
        self._json_path(document_id).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def save(self, doc: ParsedDocument, metadata: dict, source_pdf: bytes | None = None) -> None:
        self._write(doc.document_id, {"document": asdict(doc), "metadata": metadata})
        if source_pdf is not None:
            (self._root / f"{doc.document_id}.pdf").write_bytes(source_pdf)
        self._cache[doc.document_id] = doc

    def exists(self, document_id: str) -> bool:
        return self._json_path(document_id).exists()

    def load(self, document_id: str) -> ParsedDocument:
        if document_id in self._cache:
            return self._cache[document_id]
        raw = self._read(document_id)["document"]
        lines = [
            Line(
                text=line["text"],
                page=line["page"],
                bbox=tuple(line["bbox"]) if line["bbox"] else None,
                font_size=line["font_size"],
                char_start=line["char_start"],
                char_end=line["char_end"],
            )
            for line in raw["lines"]
        ]
        doc = ParsedDocument(raw["document_id"], raw["filename"], raw["text"], lines, raw["page_count"])
        self._cache[document_id] = doc
        return doc

    def metadata(self, document_id: str) -> dict:
        return self._read(document_id)["metadata"]

    def update_metadata(self, document_id: str, updates: dict) -> dict:
        payload = self._read(document_id)
        payload["metadata"] = {**payload["metadata"], **updates}
        self._write(document_id, payload)
        return payload["metadata"]

    def list_ids(self) -> list[str]:
        return sorted(path.stem for path in self._root.glob("*.json"))

    def pdf_path(self, document_id: str) -> Path | None:
        path = self._root / f"{document_id}.pdf"
        return path if path.exists() else None
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_docstore.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/storage/docstore.py tests/test_docstore.py
git commit -m "feat: on-disk document store for text, lines and metadata"
```

---

### Task 6: Vektör deposu arayüzü ve Qdrant uygulaması

**Files:**
- Create: `src/auditor/index/store.py`, `src/auditor/index/qdrant_store.py`
- Test: `tests/test_qdrant_store.py`

**Interfaces:**
- Consumes: `Chunk`, `PageBox` (`auditor.ingestion.chunker`)
- Produces (`auditor.index.store`):
  - `SparseVec` (dataclass): `indices: list[int]`, `values: list[float]`
  - `SearchFilter` (dataclass, hepsi varsayılan `None`): `document_ids: list[str] | None`, `doc_types: list[str] | None`, `jurisdictions: list[str] | None`, `date_from: str | None`, `date_to: str | None` (tarihler `YYYY-MM-DD`, iki uç dahil)
  - `Hit` (dataclass): `chunk_id: str`, `score: float`, `payload: dict`
  - `VectorStore` (Protocol):
    - `ensure_collection(dense_dim: int) -> None`
    - `upsert(chunks: list[Chunk], dense: list[list[float]], sparse: list[SparseVec], doc_meta: dict) -> None`
    - `search_dense(vector: list[float], limit: int, flt: SearchFilter | None = None) -> list[Hit]`
    - `search_sparse(vector: SparseVec, limit: int, flt: SearchFilter | None = None) -> list[Hit]`
    - `has_document(document_id: str) -> bool`
    - `delete_document(document_id: str) -> None`
    - `set_document_metadata(document_id: str, doc_meta: dict) -> None`
  - `date_to_int(value: str | None) -> int | None` (`"2023-05-01"` → `20230501`)
- Produces (`auditor.index.qdrant_store`):
  - `QdrantStore(client: QdrantClient, collection: str = "chunks")`, `QdrantStore.in_memory(collection: str = "chunks") -> QdrantStore`
  - Payload anahtarları: `document_id`, `text`, `char_start`, `char_end`, `pages`, `bboxes` (`[{"page": int, "bbox": [x0, y0, x1, y1]}]`), `section_title`, `section_path`, `parent_id`, `parent_start`, `parent_end`, `parent_section_path`, `context_prefix`, `doc_type`, `jurisdiction`, `date`, `date_int`
  - Koleksiyon yokken `search_*` boş liste, `has_document` `False` döner, `delete_document` ve `set_document_metadata` hiçbir şey yapmaz.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_qdrant_store.py`:

```python
import uuid

import pytest

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter, SparseVec, date_to_int
from auditor.ingestion.chunker import Chunk, PageBox


def _chunk(document_id: str, n: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{n}")),
        document_id=document_id,
        text=text,
        char_start=n * 10,
        char_end=n * 10 + len(text),
        pages=[1],
        bboxes=[PageBox(1, (1.0, 2.0, 3.0, 4.0))],
        section_title="Title",
        section_path=f"{n}",
        parent_id=f"{document_id}:0-100",
        parent_start=0,
        parent_end=100,
        parent_section_path="1",
        context_prefix="ctx",
    )


@pytest.fixture
def store():
    s = QdrantStore.in_memory()
    s.ensure_collection(4)
    s.upsert(
        [_chunk("docA", 0, "alpha"), _chunk("docA", 1, "beta")],
        [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
        [SparseVec([1], [1.0]), SparseVec([2], [1.0])],
        {"doc_type": "NDA", "jurisdiction": "NY", "date": "2023-05-01"},
    )
    s.upsert(
        [_chunk("docB", 0, "gamma")],
        [[0.9, 0.1, 0.0, 0.0]],
        [SparseVec([1, 3], [0.5, 1.0])],
        {"doc_type": "MSA", "jurisdiction": "CA", "date": "2024-02-10"},
    )
    return s


def test_date_to_int():
    assert date_to_int("2023-05-01") == 20230501
    assert date_to_int(None) is None
    assert date_to_int("") is None


def test_dense_search_orders_by_similarity(store):
    hits = store.search_dense([1.0, 0.0, 0.0, 0.0], limit=3)
    assert [h.payload["text"] for h in hits] == ["alpha", "gamma", "beta"]
    assert hits[0].score >= hits[1].score >= hits[2].score


def test_sparse_search_returns_only_matching_terms(store):
    hits = store.search_sparse(SparseVec([3], [1.0]), limit=5)
    assert [h.payload["text"] for h in hits] == ["gamma"]


def test_payload_roundtrip(store):
    hit = store.search_dense([1.0, 0.0, 0.0, 0.0], limit=1)[0]
    p = hit.payload
    assert hit.chunk_id == str(uuid.uuid5(uuid.NAMESPACE_URL, "docA:0"))
    assert p["document_id"] == "docA"
    assert p["bboxes"] == [{"page": 1, "bbox": [1.0, 2.0, 3.0, 4.0]}]
    assert p["pages"] == [1]
    assert (p["parent_id"], p["parent_start"], p["parent_end"]) == ("docA:0-100", 0, 100)
    assert p["parent_section_path"] == "1"
    assert p["context_prefix"] == "ctx"
    assert (p["doc_type"], p["jurisdiction"], p["date"], p["date_int"]) == ("NDA", "NY", "2023-05-01", 20230501)


def test_limit_is_respected(store):
    assert len(store.search_dense([1.0, 0.0, 0.0, 0.0], limit=2)) == 2


@pytest.mark.parametrize("flt,expected", [
    (SearchFilter(document_ids=["docB"]), {"gamma"}),
    (SearchFilter(doc_types=["NDA"]), {"alpha", "beta"}),
    (SearchFilter(jurisdictions=["CA", "TX"]), {"gamma"}),
    (SearchFilter(date_from="2024-01-01"), {"gamma"}),
    (SearchFilter(date_to="2023-12-31"), {"alpha", "beta"}),
    (SearchFilter(date_from="2023-05-01", date_to="2023-05-01"), {"alpha", "beta"}),
    (SearchFilter(doc_types=["NDA"], document_ids=["docB"]), set()),
    (SearchFilter(document_ids=["nope"]), set()),
])
def test_filters(store, flt, expected):
    dense = store.search_dense([1.0, 1.0, 0.0, 0.0], limit=10, flt=flt)
    assert {h.payload["text"] for h in dense} == expected
    sparse = store.search_sparse(SparseVec([1, 2, 3], [1.0, 1.0, 1.0]), limit=10, flt=flt)
    assert {h.payload["text"] for h in sparse} == expected


def test_has_and_delete_document(store):
    assert store.has_document("docA") is True
    store.delete_document("docA")
    assert store.has_document("docA") is False
    assert {h.payload["text"] for h in store.search_dense([1.0, 1.0, 0.0, 0.0], limit=10)} == {"gamma"}


def test_set_document_metadata_updates_filter_fields(store):
    store.set_document_metadata("docA", {"doc_type": "DPA", "jurisdiction": "DE", "date": "2025-01-15"})
    hits = store.search_dense([1.0, 1.0, 0.0, 0.0], limit=10, flt=SearchFilter(doc_types=["DPA"]))
    assert {h.payload["text"] for h in hits} == {"alpha", "beta"}
    assert hits[0].payload["date_int"] == 20250115
    assert hits[0].payload["text"] in {"alpha", "beta"}


def test_empty_sparse_query_returns_nothing(store):
    assert store.search_sparse(SparseVec([], []), limit=5) == []


def test_ensure_collection_is_idempotent(store):
    store.ensure_collection(4)
    assert store.has_document("docA")


def test_missing_collection_behaves_as_empty():
    s = QdrantStore.in_memory()
    assert s.search_dense([1.0, 0.0, 0.0, 0.0], limit=5) == []
    assert s.search_sparse(SparseVec([1], [1.0]), limit=5) == []
    assert s.has_document("docA") is False
    s.delete_document("docA")
    s.set_document_metadata("docA", {"doc_type": "NDA"})
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_qdrant_store.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.index.qdrant_store'`

- [ ] **Step 3: Arayüzü yaz**

`src/auditor/index/store.py`:

```python
from dataclasses import dataclass
from typing import Protocol

from auditor.ingestion.chunker import Chunk


@dataclass
class SparseVec:
    indices: list[int]
    values: list[float]


@dataclass
class SearchFilter:
    document_ids: list[str] | None = None
    doc_types: list[str] | None = None
    jurisdictions: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class Hit:
    chunk_id: str
    score: float
    payload: dict


def date_to_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value.replace("-", ""))


class VectorStore(Protocol):
    def ensure_collection(self, dense_dim: int) -> None: ...

    def upsert(self, chunks: list[Chunk], dense: list[list[float]],
               sparse: list[SparseVec], doc_meta: dict) -> None: ...

    def search_dense(self, vector: list[float], limit: int,
                     flt: SearchFilter | None = None) -> list[Hit]: ...

    def search_sparse(self, vector: SparseVec, limit: int,
                      flt: SearchFilter | None = None) -> list[Hit]: ...

    def has_document(self, document_id: str) -> bool: ...

    def delete_document(self, document_id: str) -> None: ...

    def set_document_metadata(self, document_id: str, doc_meta: dict) -> None: ...
```

- [ ] **Step 4: Qdrant uygulamasını yaz**

`src/auditor/index/qdrant_store.py`:

```python
from qdrant_client import QdrantClient, models

from auditor.index.store import Hit, SearchFilter, SparseVec, date_to_int
from auditor.ingestion.chunker import Chunk

DENSE = "dense"
SPARSE = "sparse"


def _meta_payload(doc_meta: dict) -> dict:
    return {
        "doc_type": doc_meta.get("doc_type"),
        "jurisdiction": doc_meta.get("jurisdiction"),
        "date": doc_meta.get("date"),
        "date_int": date_to_int(doc_meta.get("date")),
    }


def _chunk_payload(chunk: Chunk, doc_meta: dict) -> dict:
    return {
        "document_id": chunk.document_id,
        "text": chunk.text,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "pages": chunk.pages,
        "bboxes": [{"page": box.page, "bbox": list(box.bbox)} for box in chunk.bboxes],
        "section_title": chunk.section_title,
        "section_path": chunk.section_path,
        "parent_id": chunk.parent_id,
        "parent_start": chunk.parent_start,
        "parent_end": chunk.parent_end,
        "parent_section_path": chunk.parent_section_path,
        "context_prefix": chunk.context_prefix,
        **_meta_payload(doc_meta),
    }


def _document_filter(document_id: str) -> models.Filter:
    return models.Filter(must=[
        models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))
    ])


def _to_filter(flt: SearchFilter | None) -> models.Filter | None:
    if flt is None:
        return None
    must = []
    if flt.document_ids:
        must.append(models.FieldCondition(key="document_id", match=models.MatchAny(any=flt.document_ids)))
    if flt.doc_types:
        must.append(models.FieldCondition(key="doc_type", match=models.MatchAny(any=flt.doc_types)))
    if flt.jurisdictions:
        must.append(models.FieldCondition(key="jurisdiction", match=models.MatchAny(any=flt.jurisdictions)))
    if flt.date_from or flt.date_to:
        must.append(models.FieldCondition(
            key="date_int",
            range=models.Range(gte=date_to_int(flt.date_from), lte=date_to_int(flt.date_to)),
        ))
    return models.Filter(must=must) if must else None


class QdrantStore:
    def __init__(self, client: QdrantClient, collection: str = "chunks"):
        self._client = client
        self._collection = collection

    @classmethod
    def in_memory(cls, collection: str = "chunks") -> "QdrantStore":
        return cls(QdrantClient(":memory:"), collection)

    def _exists(self) -> bool:
        return self._client.collection_exists(self._collection)

    def ensure_collection(self, dense_dim: int) -> None:
        if self._exists():
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config={DENSE: models.VectorParams(size=dense_dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        for field in ("document_id", "doc_type", "jurisdiction"):
            self._client.create_payload_index(
                self._collection, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
            )
        self._client.create_payload_index(
            self._collection, field_name="date_int", field_schema=models.PayloadSchemaType.INTEGER
        )

    def upsert(self, chunks: list[Chunk], dense: list[list[float]],
               sparse: list[SparseVec], doc_meta: dict) -> None:
        points = [
            models.PointStruct(
                id=chunk.chunk_id,
                vector={
                    DENSE: dense_vec,
                    SPARSE: models.SparseVector(indices=sparse_vec.indices, values=sparse_vec.values),
                },
                payload=_chunk_payload(chunk, doc_meta),
            )
            for chunk, dense_vec, sparse_vec in zip(chunks, dense, sparse, strict=True)
        ]
        self._client.upsert(self._collection, points=points)

    def _query(self, query, using: str, limit: int, flt: SearchFilter | None) -> list[Hit]:
        if not self._exists():
            return []
        result = self._client.query_points(
            self._collection,
            query=query,
            using=using,
            query_filter=_to_filter(flt),
            limit=limit,
            with_payload=True,
        )
        return [Hit(str(p.id), float(p.score), p.payload or {}) for p in result.points]

    def search_dense(self, vector: list[float], limit: int,
                     flt: SearchFilter | None = None) -> list[Hit]:
        return self._query(vector, DENSE, limit, flt)

    def search_sparse(self, vector: SparseVec, limit: int,
                      flt: SearchFilter | None = None) -> list[Hit]:
        if not vector.indices:
            return []
        query = models.SparseVector(indices=vector.indices, values=vector.values)
        return self._query(query, SPARSE, limit, flt)

    def has_document(self, document_id: str) -> bool:
        if not self._exists():
            return False
        result = self._client.count(
            self._collection, count_filter=_document_filter(document_id), exact=True
        )
        return result.count > 0

    def delete_document(self, document_id: str) -> None:
        if not self._exists():
            return
        self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(filter=_document_filter(document_id)),
        )

    def set_document_metadata(self, document_id: str, doc_meta: dict) -> None:
        if not self._exists():
            return
        self._client.set_payload(
            self._collection, payload=_meta_payload(doc_meta), points=_document_filter(document_id)
        )
```

- [ ] **Step 5: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_qdrant_store.py -v`
Expected: 18 passed

Bellek içi Qdrant `Modifier.IDF` için hata verirse (spec bölüm 13'teki doğrulama kalemi): `ensure_collection` içinde `sparse_vectors_config={SPARSE: models.SparseVectorParams()}` kullan, testleri tekrar çalıştır ve bu sapmayı commit mesajında belirt. Bu durumda BM25'in IDF ağırlığı uygulanmaz; Task 8'deki `Bm25SparseEncoder` yerine `rank_bm25` tabanlı kodlayıcıya geçiş Plan 4'ün benchmark aşamasında değerlendirilir.

- [ ] **Step 6: Commit**

```bash
git add src/auditor/index/store.py src/auditor/index/qdrant_store.py tests/test_qdrant_store.py
git commit -m "feat: vector store interface and Qdrant implementation"
```

---

### Task 7: RRF birleştirme

**Files:**
- Create: `src/auditor/retrieval/fusion.py`
- Test: `tests/test_fusion.py`

**Interfaces:**
- Consumes: yok
- Produces: `rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]`. Skor = Σ `1 / (k + sıra)`, sıra 1'den başlar. Azalan skora göre sıralı; eşit skorlarda ilk görülen önce gelir.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_fusion.py`:

```python
import pytest

from auditor.retrieval.fusion import rrf_fuse


def test_item_in_both_lists_beats_items_in_one():
    fused = rrf_fuse([["a", "b", "c"], ["b", "d"]], k=60)
    assert [item for item, _ in fused] == ["b", "a", "d", "c"]
    assert dict(fused)["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert dict(fused)["a"] == pytest.approx(1 / 61)


def test_ties_keep_first_seen_order():
    fused = rrf_fuse([["a"], ["b"]], k=60)
    assert [item for item, _ in fused] == ["a", "b"]


def test_single_list_keeps_its_order():
    assert [item for item, _ in rrf_fuse([["x", "y", "z"]])] == ["x", "y", "z"]


def test_empty_inputs():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_fusion.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.retrieval.fusion'`

- [ ] **Step 3: Uygulamayı yaz**

`src/auditor/retrieval/fusion.py`:

```python
def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: -pair[1])
```

`dict` ekleme sırasını korur ve `sorted` kararlıdır; eşit skorlar ilk görülme sırasında kalır.

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_fusion.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/retrieval/fusion.py tests/test_fusion.py
git commit -m "feat: reciprocal rank fusion"
```

---

### Task 8: Model arayüzleri, gerçek sarmalayıcılar, test sahteleri

**Files:**
- Create: `src/auditor/index/embedder.py`, `src/auditor/retrieval/reranker.py`
- Create: `tests/fakes.py`
- Test: `tests/test_fakes.py`, `tests/test_models_slow.py`

**Interfaces:**
- Consumes: `SparseVec` (`auditor.index.store`)
- Produces (`auditor.index.embedder`):
  - `Embedder` (Protocol): `dim: int`, `embed_documents(texts: list[str]) -> list[list[float]]`, `embed_query(text: str) -> list[float]`
  - `SparseEncoder` (Protocol): `encode_documents(texts: list[str]) -> list[SparseVec]`, `encode_query(text: str) -> SparseVec`
  - `BgeM3Embedder(model_name: str = "BAAI/bge-m3", device: str | None = None, batch_size: int = 16)`
  - `Bm25SparseEncoder(model_name: str = "Qdrant/bm25")`
- Produces (`auditor.retrieval.reranker`):
  - `Reranker` (Protocol): `score(query: str, texts: list[str]) -> list[float]` (her skor 0–1 aralığında, girdi sırasıyla)
  - `BgeReranker(model_name: str = "BAAI/bge-reranker-v2-m3", device: str | None = None, max_length: int = 512)`
- Produces (`tests/fakes.py`, testlerde `from fakes import ...`):
  - `FakeEmbedder` (`dim = 64`), `FakeSparseEncoder`, `FakeReranker`. `FakeReranker.score`: sorgu kelimelerinin metinde geçen oranı.

Gerçek modeller ilk kullanımda indirilir (toplam yaklaşık 5 GB). Sarmalayıcılar kütüphaneleri kurucu içinde içe aktarır; böylece varsayılan testler torch yüklemez.

- [ ] **Step 1: Sahteler için başarısız testleri yaz**

`tests/test_fakes.py`:

```python
import math

from fakes import FakeEmbedder, FakeReranker, FakeSparseEncoder


def test_fake_embedder_is_deterministic_and_normalized():
    e = FakeEmbedder()
    v = e.embed_query("liability cap")
    assert len(v) == e.dim == 64
    assert math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-6)
    assert e.embed_documents(["liability cap"]) == [v]


def test_fake_embedder_similar_texts_are_closer():
    e = FakeEmbedder()
    q = e.embed_query("liability cap")
    near = e.embed_query("the liability cap applies")
    far = e.embed_query("governing law of new york")
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert dot(q, near) > dot(q, far)


def test_fake_sparse_encoder_shares_indices_for_shared_words():
    s = FakeSparseEncoder()
    q = s.encode_query("liability")
    d = s.encode_documents(["liability liability cap"])[0]
    assert set(q.indices) <= set(d.indices)
    assert max(d.values) == 2.0
    assert s.encode_query("   ").indices == []


def test_fake_reranker_scores_query_word_overlap():
    r = FakeReranker()
    assert r.score("aggregate liability fees", ["aggregate liability of fees", "liability", "nothing"]) == [1.0, 1 / 3, 0.0]
    assert r.score("x", []) == []
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_fakes.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'fakes'`

- [ ] **Step 3: Sahteleri yaz**

`tests/fakes.py`:

```python
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
```

- [ ] **Step 4: Sahte testlerinin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_fakes.py -v`
Expected: 4 passed

- [ ] **Step 5: Gerçek modeller için yavaş testleri yaz**

`tests/test_models_slow.py`:

```python
import pytest

pytestmark = pytest.mark.slow


def test_bge_m3_embedder_dimensions_and_similarity():
    from auditor.index.embedder import BgeM3Embedder

    e = BgeM3Embedder()
    assert e.dim == 1024
    q = e.embed_query("limitation of liability")
    docs = e.embed_documents([
        "The total aggregate liability of either party shall not exceed the fees paid.",
        "This Agreement is governed by the laws of the State of New York.",
    ])
    assert len(q) == 1024 and len(docs) == 2
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert dot(q, docs[0]) > dot(q, docs[1])


def test_bm25_sparse_encoder_matches_shared_terms():
    from auditor.index.embedder import Bm25SparseEncoder

    s = Bm25SparseEncoder()
    docs = s.encode_documents(["liability cap applies", "governing law"])
    q = s.encode_query("liability")
    assert len(docs) == 2
    assert set(q.indices) & set(docs[0].indices)
    assert not set(q.indices) & set(docs[1].indices)
    assert all(isinstance(i, int) for i in q.indices)
    assert all(isinstance(v, float) for v in docs[0].values)


def test_bge_reranker_scores_are_probabilities_in_input_order():
    from auditor.retrieval.reranker import BgeReranker

    r = BgeReranker()
    scores = r.score("What is the liability cap?", [
        "This Agreement is governed by the laws of the State of New York.",
        "The total aggregate liability of either party shall not exceed the fees paid.",
    ])
    assert len(scores) == 2
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[1] > scores[0]
    assert r.score("anything", []) == []
```

- [ ] **Step 6: Yavaş testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_models_slow.py -m slow -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.index.embedder'`

- [ ] **Step 7: Gerçek sarmalayıcıları yaz**

`src/auditor/index/embedder.py`:

```python
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
        self.dim = self._model.get_sentence_embedding_dimension()

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
```

`src/auditor/retrieval/reranker.py`:

```python
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
```

- [ ] **Step 8: Yavaş testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_models_slow.py -m slow -v`
Expected: 3 passed (ilk koşuda model indirme nedeniyle birkaç dakika sürebilir)

`predict()` `activation_fn` argümanını tanımıyorsa (`TypeError`), kurulu sentence-transformers sürümü `>=4.0` değildir: `.venv/Scripts/python -m pip install -U "sentence-transformers>=4.0"` çalıştır ve testi tekrarla.

- [ ] **Step 9: Varsayılan koşunun yavaş testleri atladığını doğrula**

Run: `.venv/Scripts/python -m pytest -v`
Expected: tüm hızlı testler geçer, çıktıda `3 deselected` görünür.

- [ ] **Step 10: Commit**

```bash
git add src/auditor/index/embedder.py src/auditor/retrieval/reranker.py tests/fakes.py tests/test_fakes.py tests/test_models_slow.py
git commit -m "feat: embedder, sparse encoder and reranker wrappers with test fakes"
```

---

### Task 9: Indexer

**Files:**
- Create: `src/auditor/ingestion/indexer.py`
- Test: `tests/test_indexer.py`

**Interfaces:**
- Consumes:
  - `parse_pdf`, `parse_text`, `ParsedDocument` (`auditor.ingestion.parser`)
  - `detect_sections` (`auditor.ingestion.structure`)
  - `build_chunks`, `Chunk` (`auditor.ingestion.chunker`)
  - `VectorStore` (`auditor.index.store`), `Embedder`, `SparseEncoder` (`auditor.index.embedder`)
  - `DocumentStore` (`auditor.storage.docstore`)
- Produces:
  - `EmptyDocumentError(Exception)`
  - `IngestResult` (dataclass): `document_id: str`, `chunk_count: int`, `already_indexed: bool`
  - `Contextualizer = Callable[[ParsedDocument, Chunk], str]`
  - `Indexer(store, embedder, sparse_encoder, docstore, *, max_child_tokens: int = 400, max_parent_tokens: int = 2000, contextualizer: Contextualizer | None = None)`
    - `ingest_pdf(path: str | Path, metadata: dict | None = None) -> IngestResult`
    - `ingest_text(text: str, filename: str, metadata: dict | None = None) -> IngestResult`
  - Saklanan metadata anahtarları: `filename`, `doc_type`, `date`, `parties`, `jurisdiction`. Verilmeyenler `None`, `parties` için `[]`.
  - Zaten indeksli belge için `already_indexed=True`, `chunk_count=0` döner ve hiçbir şey yazılmaz.
  - `contextualizer` verilirse embedding metni `f"{prefix}\n\n{chunk.text}"` olur; `chunk.text` değişmez, önek `context_prefix` alanında saklanır.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_indexer.py`:

```python
import pytest
from fakes import FakeEmbedder, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import EmptyDocumentError, Indexer
from auditor.storage.docstore import DocumentStore


class RecordingEmbedder(FakeEmbedder):
    def __init__(self):
        self.seen: list[str] = []

    def embed_documents(self, texts):
        self.seen.extend(texts)
        return super().embed_documents(texts)


@pytest.fixture
def parts(tmp_path):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder = RecordingEmbedder()
    return store, docstore, embedder


def _indexer(parts, **kwargs):
    store, docstore, embedder = parts
    return Indexer(store, embedder, FakeSparseEncoder(), docstore, **kwargs)


def test_ingest_text_indexes_chunks_and_saves_document(parts, sample_contract):
    store, docstore, embedder = parts
    result = _indexer(parts).ingest_text(sample_contract, "msa.txt")
    assert result.already_indexed is False
    assert result.chunk_count == 12
    assert store.has_document(result.document_id)
    assert docstore.load(result.document_id).text == sample_contract
    assert docstore.metadata(result.document_id) == {
        "filename": "msa.txt", "doc_type": None, "date": None,
        "parties": [], "jurisdiction": None,
    }
    hits = store.search_dense(embedder.embed_query("aggregate liability"), limit=30)
    assert len(hits) == 12


def test_reingesting_same_content_is_a_no_op(parts, sample_contract):
    store, _, embedder = parts
    indexer = _indexer(parts)
    first = indexer.ingest_text(sample_contract, "msa.txt")
    seen = len(embedder.seen)
    second = indexer.ingest_text(sample_contract, "renamed.txt")
    assert second.document_id == first.document_id
    assert second.already_indexed is True
    assert second.chunk_count == 0
    assert len(embedder.seen) == seen
    assert len(store.search_dense(embedder.embed_query("liability"), limit=100)) == 12


def test_metadata_is_stored_and_filterable(parts, sample_contract):
    store, docstore, embedder = parts
    meta = {"doc_type": "MSA", "jurisdiction": "NY", "date": "2023-05-01", "parties": ["Acme", "Beta"]}
    result = _indexer(parts).ingest_text(sample_contract, "msa.txt", metadata=meta)
    assert docstore.metadata(result.document_id) == {"filename": "msa.txt", **meta}
    query = embedder.embed_query("liability")
    assert store.search_dense(query, limit=5, flt=SearchFilter(doc_types=["MSA"]))
    assert store.search_dense(query, limit=5, flt=SearchFilter(doc_types=["NDA"])) == []


def test_ingest_pdf_keeps_the_pdf_and_page_numbers(parts, make_pdf, tmp_path):
    store, docstore, embedder = parts
    path = make_pdf(tmp_path / "c.pdf", [
        [("1. Definitions", 11),
         ("Services means the consulting services described in Exhibit A.", 11)],
        [("2. Liability", 11),
         ("The total liability shall not exceed the fees paid in twelve months.", 11)],
    ])
    result = _indexer(parts).ingest_pdf(path)
    assert result.chunk_count == 2
    assert docstore.pdf_path(result.document_id).read_bytes() == path.read_bytes()
    hit = store.search_dense(embedder.embed_query("total liability fees"), limit=1)[0]
    assert hit.payload["pages"] == [2]
    assert hit.payload["bboxes"][0]["page"] == 2


def test_contextualizer_prefixes_embedding_text_only(parts, sample_contract):
    store, _, embedder = parts
    indexer = _indexer(parts, contextualizer=lambda doc, chunk: f"From {doc.filename}.")
    indexer.ingest_text(sample_contract, "msa.txt")
    assert all(text.startswith("From msa.txt.\n\n") for text in embedder.seen)
    hit = store.search_dense(embedder.embed_query("liability"), limit=1)[0]
    assert hit.payload["context_prefix"] == "From msa.txt."
    assert not hit.payload["text"].startswith("From msa.txt.")


def test_chunk_limits_are_passed_through(parts):
    result = _indexer(parts, max_child_tokens=100).ingest_text(" ".join(["tok"] * 500), "t.txt")
    assert result.chunk_count == 5


def test_empty_document_raises_and_stores_nothing(parts):
    store, docstore, _ = parts
    with pytest.raises(EmptyDocumentError):
        _indexer(parts).ingest_text("  \n \n", "empty.txt")
    assert docstore.list_ids() == []
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_indexer.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.ingestion.indexer'`

- [ ] **Step 3: Uygulamayı yaz**

`src/auditor/ingestion/indexer.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from auditor.index.embedder import Embedder, SparseEncoder
from auditor.index.store import VectorStore
from auditor.ingestion.chunker import Chunk, build_chunks
from auditor.ingestion.parser import ParsedDocument, parse_pdf, parse_text
from auditor.ingestion.structure import detect_sections
from auditor.storage.docstore import DocumentStore

Contextualizer = Callable[[ParsedDocument, Chunk], str]


class EmptyDocumentError(Exception):
    pass


@dataclass
class IngestResult:
    document_id: str
    chunk_count: int
    already_indexed: bool


class Indexer:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        sparse_encoder: SparseEncoder,
        docstore: DocumentStore,
        *,
        max_child_tokens: int = 400,
        max_parent_tokens: int = 2000,
        contextualizer: Contextualizer | None = None,
    ):
        self._store = store
        self._embedder = embedder
        self._sparse = sparse_encoder
        self._docstore = docstore
        self._max_child_tokens = max_child_tokens
        self._max_parent_tokens = max_parent_tokens
        self._contextualizer = contextualizer

    def ingest_pdf(self, path: str | Path, metadata: dict | None = None) -> IngestResult:
        doc = parse_pdf(path)
        return self._index(doc, metadata, Path(path).read_bytes())

    def ingest_text(self, text: str, filename: str, metadata: dict | None = None) -> IngestResult:
        return self._index(parse_text(text, filename), metadata, None)

    def _index(self, doc: ParsedDocument, metadata: dict | None,
               source_pdf: bytes | None) -> IngestResult:
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
            **(metadata or {}),
        }
        if self._contextualizer:
            for chunk in chunks:
                chunk.context_prefix = self._contextualizer(doc, chunk)
        texts = [
            f"{chunk.context_prefix}\n\n{chunk.text}" if chunk.context_prefix else chunk.text
            for chunk in chunks
        ]

        self._store.ensure_collection(self._embedder.dim)
        self._store.delete_document(doc.document_id)
        self._store.upsert(
            chunks,
            self._embedder.embed_documents(texts),
            self._sparse.encode_documents(texts),
            meta,
        )
        self._docstore.save(doc, meta, source_pdf)
        return IngestResult(doc.document_id, len(chunks), False)
```

`delete_document` çağrısı, yarıda kalmış bir önceki indekslemeden kalan noktaları temizler. Belge deposuna kayıt en son yapılır; böylece `exists and has_document` yalnızca tamamlanmış indeksleme için doğru olur.

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_indexer.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/auditor/ingestion/indexer.py tests/test_indexer.py
git commit -m "feat: indexer wiring parse, chunk, embed and store"
```

---

### Task 10: Arama hattı

**Files:**
- Create: `src/auditor/retrieval/config.py`, `src/auditor/retrieval/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes:
  - `VectorStore`, `SearchFilter`, `Hit` (`auditor.index.store`)
  - `Embedder`, `SparseEncoder` (`auditor.index.embedder`), `Reranker` (`auditor.retrieval.reranker`)
  - `rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]`
  - `DocumentStore.load(document_id).text`
  - `PageBox` (`auditor.ingestion.chunker`)
- Produces (`auditor.retrieval.config`):
  - `RetrievalConfig` (frozen dataclass): `mode: Literal["bm25", "dense", "hybrid"] = "hybrid"`, `rerank: bool = True`, `candidate_k: int = 30`, `final_k: int = 5`, `rrf_k: int = 60`, `min_rerank_score: float = 0.3`
- Produces (`auditor.retrieval.pipeline`):
  - `StageScores` (dataclass): `bm25_rank: int | None`, `bm25_score: float | None`, `dense_rank: int | None`, `dense_score: float | None`, `rrf_score: float | None`, `fused_rank: int`, `rerank_score: float | None`, `final_rank: int`, `rank_change: int` (`fused_rank - final_rank`; pozitif değer rerank'in yukarı taşıdığını gösterir)
  - `RetrievedChunk` (dataclass): `chunk_id`, `document_id`, `text`, `section_title`, `section_path`, `pages: list[int]`, `bboxes: list[PageBox]`, `char_start`, `char_end`, `parent_id`, `scores: StageScores`
  - `ParentPassage` (dataclass): `parent_id`, `document_id`, `text`, `char_start`, `char_end`, `section_path`, `chunk_ids: list[str]`
  - `RetrievalResult` (dataclass): `query: str`, `config: RetrievalConfig`, `chunks: list[RetrievedChunk]`, `parents: list[ParentPassage]`, `insufficient_evidence: bool`
  - `Retriever(store, embedder, sparse_encoder, reranker, docstore)`; `search(query: str, config: RetrievalConfig | None = None, flt: SearchFilter | None = None) -> RetrievalResult`

Kurallar:

- Sıralar 1'den başlar. `fused_rank`: hybrid modda RRF listesindeki, tek modda o modun listesindeki sıra. `rrf_score` yalnız hybrid modda doludur.
- `rerank=False` iken `rerank_score` `None`, `final_rank == fused_rank`.
- `insufficient_evidence`: sonuç yoksa `True`. `rerank=True` ise en iyi `rerank_score < min_rerank_score` olduğunda `True`. `rerank=False` ve sonuç varsa `False` (rerank'siz modda ayarlanmış bir güven sinyali yok).
- `min_rerank_score` varsayılanı 0.3 geçicidir; Plan 4'te benchmark verisinden ayarlanır.
- `parents` ilk görülme sırasındadır; aynı `parent_id`'ye düşen chunk'lar tek girişte toplanır.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_pipeline.py`:

```python
import pytest
from fakes import FakeEmbedder, FakeReranker, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import Indexer
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore

OTHER_CONTRACT = """1. Confidentiality
1.1 Each party shall keep the other party's information confidential for five years.

2. Liability
2.1 The aggregate liability of the vendor is limited to the fees paid."""


class CountingReranker(FakeReranker):
    def __init__(self):
        self.calls = 0

    def score(self, query, texts):
        self.calls += 1
        return super().score(query, texts)


@pytest.fixture
def env(tmp_path, sample_contract):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse, reranker = FakeEmbedder(), FakeSparseEncoder(), CountingReranker()
    indexer = Indexer(store, embedder, sparse, docstore)
    first = indexer.ingest_text(sample_contract, "msa.txt", {"doc_type": "MSA"})
    second = indexer.ingest_text(OTHER_CONTRACT, "nda.txt", {"doc_type": "NDA"})
    retriever = Retriever(store, embedder, sparse, reranker, docstore)
    return retriever, first.document_id, second.document_id, reranker


def test_defaults():
    c = RetrievalConfig()
    assert (c.mode, c.rerank, c.candidate_k, c.final_k) == ("hybrid", True, 30, 5)


def test_hybrid_rerank_puts_best_match_first_with_all_stage_scores(env):
    retriever, msa, _, _ = env
    result = retriever.search("total aggregate liability twelve months", flt=SearchFilter(document_ids=[msa]))
    assert result.insufficient_evidence is False
    assert len(result.chunks) == 5
    top = result.chunks[0]
    assert top.section_path == "3 > 3.1"
    assert top.document_id == msa
    s = top.scores
    assert s.final_rank == 1
    assert s.bm25_rank is not None and s.bm25_score is not None
    assert s.dense_rank is not None and s.dense_score is not None
    assert s.rrf_score is not None
    assert s.rerank_score == 1.0
    assert [c.scores.final_rank for c in result.chunks] == [1, 2, 3, 4, 5]
    for chunk in result.chunks:
        assert chunk.scores.rank_change == chunk.scores.fused_rank - chunk.scores.final_rank
    scores = [c.scores.rerank_score for c in result.chunks]
    assert scores == sorted(scores, reverse=True)


def test_bm25_mode_has_no_dense_or_rrf_scores(env):
    retriever, _, _, _ = env
    result = retriever.search("aggregate liability", RetrievalConfig(mode="bm25", rerank=False))
    assert result.chunks
    for chunk in result.chunks:
        s = chunk.scores
        assert s.bm25_rank == s.fused_rank == s.final_rank
        assert s.dense_rank is None and s.dense_score is None and s.rrf_score is None
        assert s.rerank_score is None and s.rank_change == 0


def test_dense_mode_has_no_bm25_scores(env):
    retriever, _, _, _ = env
    result = retriever.search("aggregate liability", RetrievalConfig(mode="dense", rerank=False))
    assert result.chunks
    assert all(c.scores.bm25_rank is None and c.scores.dense_rank == c.scores.fused_rank
               for c in result.chunks)


def test_rerank_off_skips_reranker_and_never_flags_non_empty_results(env):
    retriever, _, _, reranker = env
    result = retriever.search("zebra giraffe", RetrievalConfig(mode="dense", rerank=False))
    assert reranker.calls == 0
    assert result.chunks
    assert result.insufficient_evidence is False


def test_final_k_and_candidate_k_are_respected(env):
    retriever, _, _, _ = env
    result = retriever.search("liability", RetrievalConfig(candidate_k=4, final_k=2))
    assert len(result.chunks) == 2
    assert all(c.scores.fused_rank <= 4 for c in result.chunks)


def test_low_rerank_score_flags_insufficient_evidence(env):
    retriever, _, _, _ = env
    result = retriever.search("zebra giraffe")
    assert result.insufficient_evidence is True
    result = retriever.search("zebra giraffe", RetrievalConfig(min_rerank_score=0.0))
    assert result.insufficient_evidence is False


def test_filter_limits_results_to_matching_documents(env):
    retriever, _, nda, _ = env
    result = retriever.search("aggregate liability fees", flt=SearchFilter(doc_types=["NDA"]))
    assert result.chunks
    assert {c.document_id for c in result.chunks} == {nda}


def test_parents_are_expanded_and_deduplicated(env):
    retriever, msa, _, _ = env
    result = retriever.search("liability damages", flt=SearchFilter(document_ids=[msa]))
    parent_ids = [p.parent_id for p in result.parents]
    assert len(parent_ids) == len(set(parent_ids))
    assert {c.chunk_id for c in result.chunks} == {cid for p in result.parents for cid in p.chunk_ids}
    liability = next(p for p in result.parents if p.section_path == "3")
    assert liability.text.startswith("3. Limitation of Liability")
    assert "3.1 The total aggregate liability" in liability.text
    assert "3.2 Neither party" in liability.text
    assert len(liability.chunk_ids) >= 2
    assert result.parents[0].parent_id == result.chunks[0].parent_id


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_blank_query_returns_empty_result_without_calling_models(env, query):
    retriever, _, _, reranker = env
    result = retriever.search(query)
    assert result.chunks == [] and result.parents == []
    assert result.insufficient_evidence is True
    assert reranker.calls == 0


def test_filter_matching_nothing_returns_empty_result(env):
    retriever, _, _, _ = env
    result = retriever.search("liability", flt=SearchFilter(document_ids=["no-such-document"]))
    assert result.chunks == [] and result.parents == []
    assert result.insufficient_evidence is True


def test_search_before_anything_is_indexed(tmp_path):
    retriever = Retriever(QdrantStore.in_memory(), FakeEmbedder(), FakeSparseEncoder(),
                          FakeReranker(), DocumentStore(tmp_path / "docs"))
    result = retriever.search("liability")
    assert result.chunks == []
    assert result.insufficient_evidence is True
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.retrieval.config'`

- [ ] **Step 3: Ayar nesnesini yaz**

`src/auditor/retrieval/config.py`:

```python
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
```

- [ ] **Step 4: Arama hattını yaz**

`src/auditor/retrieval/pipeline.py`:

```python
from dataclasses import dataclass

from auditor.index.embedder import Embedder, SparseEncoder
from auditor.index.store import Hit, SearchFilter, VectorStore
from auditor.ingestion.chunker import PageBox
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.fusion import rrf_fuse
from auditor.retrieval.reranker import Reranker
from auditor.storage.docstore import DocumentStore


@dataclass
class StageScores:
    bm25_rank: int | None
    bm25_score: float | None
    dense_rank: int | None
    dense_score: float | None
    rrf_score: float | None
    fused_rank: int
    rerank_score: float | None
    final_rank: int
    rank_change: int


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    text: str
    section_title: str
    section_path: str
    pages: list[int]
    bboxes: list[PageBox]
    char_start: int
    char_end: int
    parent_id: str
    scores: StageScores


@dataclass
class ParentPassage:
    parent_id: str
    document_id: str
    text: str
    char_start: int
    char_end: int
    section_path: str
    chunk_ids: list[str]


@dataclass
class RetrievalResult:
    query: str
    config: RetrievalConfig
    chunks: list[RetrievedChunk]
    parents: list[ParentPassage]
    insufficient_evidence: bool


def _positions(hits: list[Hit]) -> dict[str, tuple[int, float]]:
    return {hit.chunk_id: (rank, hit.score) for rank, hit in enumerate(hits, start=1)}


class Retriever:
    def __init__(self, store: VectorStore, embedder: Embedder, sparse_encoder: SparseEncoder,
                 reranker: Reranker, docstore: DocumentStore):
        self._store = store
        self._embedder = embedder
        self._sparse = sparse_encoder
        self._reranker = reranker
        self._docstore = docstore

    def search(self, query: str, config: RetrievalConfig | None = None,
               flt: SearchFilter | None = None) -> RetrievalResult:
        config = config or RetrievalConfig()
        if not query.strip():
            return RetrievalResult(query, config, [], [], True)

        bm25: list[Hit] = []
        dense: list[Hit] = []
        if config.mode in ("bm25", "hybrid"):
            bm25 = self._store.search_sparse(
                self._sparse.encode_query(query), config.candidate_k, flt
            )
        if config.mode in ("dense", "hybrid"):
            dense = self._store.search_dense(
                self._embedder.embed_query(query), config.candidate_k, flt
            )

        payloads = {hit.chunk_id: hit.payload for hit in [*bm25, *dense]}
        bm25_pos, dense_pos = _positions(bm25), _positions(dense)

        rrf: dict[str, float] = {}
        if config.mode == "hybrid":
            fused = rrf_fuse(
                [[h.chunk_id for h in bm25], [h.chunk_id for h in dense]], k=config.rrf_k
            )[:config.candidate_k]
            rrf = dict(fused)
            candidate_ids = [chunk_id for chunk_id, _ in fused]
        else:
            candidate_ids = [h.chunk_id for h in (bm25 if config.mode == "bm25" else dense)]
        fused_rank = {chunk_id: rank for rank, chunk_id in enumerate(candidate_ids, start=1)}

        rerank: dict[str, float] = {}
        ordered = candidate_ids
        if config.rerank and candidate_ids:
            scores = self._reranker.score(query, [payloads[c]["text"] for c in candidate_ids])
            rerank = dict(zip(candidate_ids, scores, strict=True))
            ordered = sorted(candidate_ids, key=lambda c: -rerank[c])
        final_ids = ordered[:config.final_k]

        chunks = []
        for final_rank, chunk_id in enumerate(final_ids, start=1):
            payload = payloads[chunk_id]
            bm25_rank, bm25_score = bm25_pos.get(chunk_id, (None, None))
            dense_rank, dense_score = dense_pos.get(chunk_id, (None, None))
            chunks.append(RetrievedChunk(
                chunk_id=chunk_id,
                document_id=payload["document_id"],
                text=payload["text"],
                section_title=payload["section_title"],
                section_path=payload["section_path"],
                pages=payload["pages"],
                bboxes=[PageBox(b["page"], tuple(b["bbox"])) for b in payload["bboxes"]],
                char_start=payload["char_start"],
                char_end=payload["char_end"],
                parent_id=payload["parent_id"],
                scores=StageScores(
                    bm25_rank=bm25_rank,
                    bm25_score=bm25_score,
                    dense_rank=dense_rank,
                    dense_score=dense_score,
                    rrf_score=rrf.get(chunk_id),
                    fused_rank=fused_rank[chunk_id],
                    rerank_score=rerank.get(chunk_id),
                    final_rank=final_rank,
                    rank_change=fused_rank[chunk_id] - final_rank,
                ),
            ))

        insufficient = not chunks or (
            config.rerank and chunks[0].scores.rerank_score < config.min_rerank_score
        )
        return RetrievalResult(query, config, chunks, self._expand(chunks, payloads), bool(insufficient))

    def _expand(self, chunks: list[RetrievedChunk], payloads: dict[str, dict]) -> list[ParentPassage]:
        parents: dict[str, ParentPassage] = {}
        for chunk in chunks:
            payload = payloads[chunk.chunk_id]
            parent = parents.get(chunk.parent_id)
            if parent is None:
                start, end = payload["parent_start"], payload["parent_end"]
                text = self._docstore.load(chunk.document_id).text[start:end]
                parent = ParentPassage(
                    parent_id=chunk.parent_id,
                    document_id=chunk.document_id,
                    text=text,
                    char_start=start,
                    char_end=end,
                    section_path=payload["parent_section_path"],
                    chunk_ids=[],
                )
                parents[chunk.parent_id] = parent
            parent.chunk_ids.append(chunk.chunk_id)
        return list(parents.values())
```

`sorted` kararlı olduğu için eşit rerank skorlarında birleşik sıra korunur.

- [ ] **Step 5: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_pipeline.py -v`
Expected: 14 passed

- [ ] **Step 6: Commit**

```bash
git add src/auditor/retrieval/config.py src/auditor/retrieval/pipeline.py tests/test_pipeline.py
git commit -m "feat: hybrid retrieval pipeline with stage scores and parent expansion"
```

---

### Task 11: Servis kurulumu, CLI, gerçek modellerle uçtan uca doğrulama

**Files:**
- Create: `src/auditor/services.py`, `src/auditor/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `Settings` (`auditor.config`)
  - `QdrantStore`, `DocumentStore`, `Indexer`, `Retriever`, `RetrievalConfig`
  - `BgeM3Embedder`, `Bm25SparseEncoder`, `BgeReranker`
  - `InvalidPdfError`, `ScannedPdfError`, `EmptyDocumentError`
- Produces:
  - `auditor.services.Services` (dataclass): `indexer: Indexer`, `retriever: Retriever`, `docstore: DocumentStore`, `store: QdrantStore`
  - `auditor.services.build_services(settings: Settings) -> Services`. `settings.qdrant_url` doluysa sunucuya, boşsa `{data_dir}/qdrant` altında gömülü Qdrant'a bağlanır; belgeler `{data_dir}/documents` altındadır.
  - `auditor.cli.main(argv: list[str] | None = None, services: Services | None = None) -> int`
    - `ingest <path>`: başarıda 0, okunamayan/taranmış/boş belgede `stderr`'e `error: …` yazıp 1 döner.
    - `search <query> [--mode bm25|dense|hybrid] [--no-rerank] [--top N]`: sonuçları ve parent başlıklarını yazar, 0 döner.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_cli.py`:

```python
import pytest
from fakes import FakeEmbedder, FakeReranker, FakeSparseEncoder

from auditor.cli import main
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.retrieval.pipeline import Retriever
from auditor.services import Services
from auditor.storage.docstore import DocumentStore

PAGES = [
    [("1. Definitions", 11),
     ("Services means the consulting services described in Exhibit A.", 11)],
    [("2. Liability", 11),
     ("The total liability shall not exceed the fees paid in twelve months.", 11)],
]


@pytest.fixture
def services(tmp_path):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    return Services(
        indexer=Indexer(store, embedder, sparse, docstore),
        retriever=Retriever(store, embedder, sparse, FakeReranker(), docstore),
        docstore=docstore,
        store=store,
    )


def test_ingest_then_search(services, make_pdf, tmp_path, capsys):
    path = make_pdf(tmp_path / "c.pdf", PAGES)
    assert main(["ingest", str(path)], services) == 0
    out = capsys.readouterr().out
    assert "indexed 2 chunks" in out

    assert main(["ingest", str(path)], services) == 0
    assert "already indexed" in capsys.readouterr().out

    assert main(["search", "total liability fees", "--top", "1"], services) == 0
    out = capsys.readouterr().out
    assert "1. [2]" in out
    assert "p[2]" in out
    assert "rerank=" in out
    assert "The total liability shall not exceed" in out


def test_search_modes_and_no_rerank(services, make_pdf, tmp_path, capsys):
    main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES))], services)
    capsys.readouterr()
    assert main(["search", "liability", "--mode", "bm25", "--no-rerank"], services) == 0
    out = capsys.readouterr().out
    assert "bm25=#1" in out
    assert "dense=-" in out
    assert "rerank=-" in out


def test_search_with_no_results_says_so(services, capsys):
    assert main(["search", "liability"], services) == 0
    assert "no sufficient evidence" in capsys.readouterr().out


def test_ingest_errors_exit_with_1_and_message(services, tmp_path, capsys):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert main(["ingest", str(broken)], services) == 1
    assert "error:" in capsys.readouterr().err
    assert main(["ingest", str(tmp_path / "missing.pdf")], services) == 1
    assert "error:" in capsys.readouterr().err
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'auditor.cli'`

- [ ] **Step 3: Servis kurulumunu yaz**

`src/auditor/services.py`:

```python
from dataclasses import dataclass

from auditor.config import Settings
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore


@dataclass
class Services:
    indexer: Indexer
    retriever: Retriever
    docstore: DocumentStore
    store: QdrantStore


def build_services(settings: Settings) -> Services:
    from qdrant_client import QdrantClient

    from auditor.index.embedder import BgeM3Embedder, Bm25SparseEncoder
    from auditor.retrieval.reranker import BgeReranker

    if settings.qdrant_url:
        client = QdrantClient(url=settings.qdrant_url)
    else:
        qdrant_dir = settings.data_dir / "qdrant"
        qdrant_dir.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(qdrant_dir))

    store = QdrantStore(client, settings.collection)
    docstore = DocumentStore(settings.data_dir / "documents")
    embedder = BgeM3Embedder(settings.embed_model, settings.device)
    sparse = Bm25SparseEncoder()
    reranker = BgeReranker(settings.rerank_model, settings.device)
    return Services(
        indexer=Indexer(store, embedder, sparse, docstore),
        retriever=Retriever(store, embedder, sparse, reranker, docstore),
        docstore=docstore,
        store=store,
    )
```

- [ ] **Step 4: CLI'yi yaz**

`src/auditor/cli.py`:

```python
import argparse
import sys
from dataclasses import replace

from auditor.config import Settings
from auditor.ingestion.indexer import EmptyDocumentError
from auditor.ingestion.parser import InvalidPdfError, ScannedPdfError
from auditor.retrieval.config import RetrievalConfig
from auditor.services import Services, build_services


def _rank(rank: int | None) -> str:
    return f"#{rank}" if rank is not None else "-"


def _score(score: float | None) -> str:
    return f"{score:.3f}" if score is not None else "-"


def _ingest(services: Services, path: str) -> int:
    try:
        result = services.indexer.ingest_pdf(path)
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


def main(argv: list[str] | None = None, services: Services | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auditor")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="index a PDF")
    ingest.add_argument("path")
    search = sub.add_parser("search", help="search indexed documents")
    search.add_argument("query")
    search.add_argument("--mode", choices=["bm25", "dense", "hybrid"], default="hybrid")
    search.add_argument("--no-rerank", action="store_true")
    search.add_argument("--top", type=int, default=0)
    args = parser.parse_args(argv)

    services = services or build_services(Settings.from_env())
    if args.command == "ingest":
        return _ingest(services, args.path)
    return _search(services, args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Testlerin geçtiğini gör**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: 4 passed

- [ ] **Step 6: Tüm hızlı testleri çalıştır**

Run: `.venv/Scripts/python -m pytest -v`
Expected: tüm testler geçer, `3 deselected`.

- [ ] **Step 7: Gerçek modellerle uçtan uca doğrula**

Gerçek bir sözleşme PDF'i üret ve gerçek modellerle indeksle. Aşağıdaki betik `tests/conftest.py` içindeki örnek metni PDF'e çevirir:

```bash
mkdir -p data
.venv/Scripts/python -c "
import fitz, sys
sys.path.insert(0, 'tests')
from conftest import SAMPLE_CONTRACT
doc = fitz.open(); page = doc.new_page(); y = 72
for line in SAMPLE_CONTRACT.split('\n'):
    if line: page.insert_text((60, y), line, fontsize=9)
    y += 14
doc.save('data/sample.pdf')
"
.venv/Scripts/python -m auditor.cli ingest data/sample.pdf
.venv/Scripts/python -m auditor.cli search "What is the cap on liability?"
.venv/Scripts/python -m auditor.cli search "How much notice is needed to end the contract?"
.venv/Scripts/python -m auditor.cli search "limitation of liability" --mode bm25 --no-rerank
.venv/Scripts/python -m auditor.cli search "What is the warranty period for hardware?"
```

Expected:

- `ingest`: `indexed 12 chunks: <64 karakterlik id>`.
- İlk sorgu: 1. sırada `[3 > 3.1]` veya `[3]`, `rerank` skoru 0.3'ün üstünde, "no sufficient evidence" yok.
- İkinci sorgu: 1. sırada `[2 > 2.2]`. Sorguda "terminate" veya "thirty" kelimesi geçmediği için bu, dense aramanın ve reranker'ın anlamsal eşleşme yaptığını gösterir.
- Üçüncü sorgu: 1. sırada `[3]` (başlık satırı) veya `[3 > 3.1]`, `dense=-`, `rerank=-`.
- Dördüncü sorgu: belgede garanti maddesi yok. `no sufficient evidence` yazılması beklenir. Yazılmazsa en iyi `rerank` skorunu not et: 0.3 eşiğinin bu model için düşük kaldığını gösterir ve Plan 4'teki eşik ayarına girdi olur. Bu adımı başarısız sayma.

Gözlenen çıktıları (sıralar ve skorlar) kullanıcıya raporla.

- [ ] **Step 8: Commit**

```bash
git add src/auditor/services.py src/auditor/cli.py tests/test_cli.py
git commit -m "feat: service wiring and CLI for ingest and search"
```
