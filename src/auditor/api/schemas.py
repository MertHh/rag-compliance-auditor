from typing import Literal

from pydantic import BaseModel, field_validator

from auditor.index.store import SearchFilter, date_to_int

ProviderName = Literal["openai", "ollama"]


class Filters(BaseModel):
    document_ids: list[str] | None = None
    doc_types: list[str] | None = None
    jurisdictions: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None

    @field_validator("date_from", "date_to")
    @classmethod
    def _iso_date(cls, value: str | None) -> str | None:
        # The store parses dates only when it has a collection; check them up front.
        date_to_int(value)  # raises InvalidDateError, a ValueError, for anything but YYYY-MM-DD
        return value or None

    def to_filter(self) -> SearchFilter | None:
        values = {key: value or None for key, value in self.model_dump().items()}
        return SearchFilter(**values) if any(values.values()) else None
