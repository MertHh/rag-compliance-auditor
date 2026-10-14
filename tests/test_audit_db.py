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


def test_find_latest_includes_errored_runs(db):
    db.save_audit(_report("clean", created_at="2026-10-14T09:00:00+00:00"), [], "key1")
    db.save_audit(_report("broken", errors=[{"rule_id": "r1", "message": "x"}],
                          created_at="2026-10-14T11:00:00+00:00"), [], "key1")
    assert db.find_latest("key1")["audit_id"] == "broken"
    assert db.find_latest("other") is None


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
