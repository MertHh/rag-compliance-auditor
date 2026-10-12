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
