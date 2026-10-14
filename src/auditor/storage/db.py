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
