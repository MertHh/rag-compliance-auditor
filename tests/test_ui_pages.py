from pathlib import Path

import fake_api
import pdfview
import pytest
import shared
from apiclient import ApiError
from fake_api import AUDIT_ID, DOC_ID, FakeApi
from streamlit.testing.v1 import AppTest

UI = Path(__file__).resolve().parents[1] / "ui"


@pytest.fixture
def fake(monkeypatch):
    api = FakeApi()
    api.shown = []
    shared._pdf_bytes.clear()
    monkeypatch.setattr(shared, "get_client", lambda: api)
    monkeypatch.setattr(pdfview, "show_pdf",
                        lambda data, annotations, key: api.shown.append((key, annotations)))
    return api


def run_screen(name: str, params: dict | None = None, **state) -> AppTest:
    at = AppTest.from_file(str(UI / "screens" / f"{name}.py"), default_timeout=10)
    for key, value in state.items():
        at.session_state[key] = value
    for key, value in (params or {}).items():
        at.query_params[key] = value
    return at.run()


def texts(elements) -> list[str]:
    return [element.value for element in elements]


def test_app_opens_on_documents(fake):
    at = AppTest.from_file(str(UI / "app.py"), default_timeout=10).run()
    assert not at.exception
    assert at.title[0].value == "Documents"


def test_documents_lists_metadata(fake):
    at = run_screen("documents")
    assert not at.exception
    table = at.dataframe[0].value
    assert table["File"].tolist() == ["contract.pdf"]
    assert table["Jurisdiction"].tolist() == ["New York"]


def test_documents_empty_and_api_down(fake):
    fake.docs = []
    at = run_screen("documents")
    assert any("No documents yet" in text for text in texts(at.info))

    fake.fail = ApiError(0, "API unreachable at http://localhost:8000: refused")
    at = run_screen("documents")
    assert not at.exception
    assert texts(at.error) == ["API unreachable at http://localhost:8000: refused"]


def test_search_shows_stage_scores_and_highlights(fake):
    at = run_screen("search")
    at.text_input(key="search_query").input("liability cap").run()
    assert not at.exception
    table = at.dataframe[0].value
    assert table["Rerank"].tolist() == ["0.900"] and table["BM25"].tolist() == ["#1"]
    searches = [call for call in fake.calls if call[0] == "search"]
    assert searches == [("search", "liability cap", "hybrid", True, 5, {})]
    key, annotations = fake.shown[-1]
    assert key == "search_pdf"
    assert annotations == [{"page": 2, "x": 72.0, "y": 90.0, "width": 348.0, "height": 14.0,
                            "color": "#2a78d6"}]


def test_search_error_is_shown(fake):
    at = run_screen("search")
    fake.fail = ApiError(422, "query: String should have at least 1 character")
    at.text_input(key="search_query").input("x").run()
    assert not at.exception
    assert "query: String should have at least 1 character" in texts(at.error)


def test_ask_found_shows_answer_and_quote(fake):
    at = run_screen("ask")
    at.text_input[0].input("What is the cap?")
    at.button[0].click().run()
    assert not at.exception
    assert any("Liability is capped" in text for text in texts(at.markdown))
    assert fake.shown[-1][0] == "ask_pdf"


def test_ask_dollar_amounts_are_not_math(fake):
    original = fake.ask

    def ask(question, filters=None, provider=None):
        result = original(question, filters, provider)
        quote = "Liability shall not exceed $500,000 or $1,000,000."
        return {**result, "answer": "The cap is $500,000.",
                "citations": [{**result["citations"][0], "quote": quote}]}

    fake.ask = ask
    at = run_screen("ask")
    at.text_input[0].input("What is the cap?")
    at.button[0].click().run()
    assert not at.exception
    shown = texts(at.markdown)
    assert any(r"The cap is \$500,000." in text for text in shown)
    assert any(r"\$500,000 or \$1,000,000" in text for text in shown)


def test_audit_reasoning_and_quote_keep_dollar_amounts(fake):
    finding = {**fake_api.REPORT["findings"][0], "reasoning": "Cap is $500,000 or $1,000,000.",
               "citations": [{**fake_api.CITATION, "quote": "not exceed $500,000"}]}
    fake.audit = lambda audit_id: ("done", {**fake_api.REPORT, "findings": [finding]})
    at = run_screen("audit", audit_id=AUDIT_ID, audit_saved=True)
    assert not at.exception
    shown = texts(at.markdown)
    assert r"Cap is \$500,000 or \$1,000,000." in shown
    assert any(r"not exceed \$500,000" in text for text in shown)


def test_ask_not_found_shows_message_and_nearest(fake):
    fake.ask_found = False
    at = run_screen("ask")
    at.text_input[0].input("zebra?")
    at.button[0].click().run()
    assert not at.exception
    assert texts(at.info) == ["I could not find a statement about this in these documents."]
    assert fake.shown == []


def test_ask_error_drops_previous_answer(fake):
    at = run_screen("ask")
    at.text_input[0].input("What is the cap?")
    at.button[0].click().run()
    assert any("Liability is capped" in text for text in texts(at.markdown))

    def failing_ask(question, filters=None, provider=None):
        raise ApiError(503, "Ollama is not reachable")

    fake.ask = failing_ask  # only ask fails, so the page still loads the documents
    at.text_input[0].input("And the term?")
    at.button[0].click().run()
    assert not at.exception
    assert "Ollama is not reachable" in texts(at.error)
    assert not any("Liability is capped" in text for text in texts(at.markdown))


def test_audit_shows_saved_report(fake):
    at = run_screen("audit", audit_id=AUDIT_ID, audit_saved=True)
    assert not at.exception
    assert at.metric[0].value == "40.0"
    assert any(text.startswith("Saved run · 2026-10-14 09:30 UTC") for text in texts(at.caption))
    table = at.dataframe[0].value
    assert table["Status"].tolist() == ["✅ Compliant", "🟠 Missing"]
    assert any("broken.yaml: bad" in text for text in texts(at.warning))
    key, annotations = fake.shown[-1]
    assert key == "audit_pdf" and annotations[0]["color"] == "#0ca30c"


def test_run_audit_shows_running_state(fake):
    fake.audit_state = "running"
    at = run_screen("audit")
    at.button(key="run_audit").click().run()
    assert not at.exception
    assert ("start_audit", DOC_ID, "test_pb", "openai", False) in fake.calls
    assert any("Audit running" in text for text in texts(at.info))


def test_cached_start_is_labelled_saved(fake):
    at = run_screen("audit")
    at.button(key="run_audit").click().run()
    assert not at.exception
    assert any(text.startswith("Saved run") for text in texts(at.caption))


def test_review_is_sent(fake):
    at = run_screen("audit", audit_id=AUDIT_ID, audit_saved=True)
    at.radio[0].set_value("rejected")
    at.text_area[0].input("Cap excludes IP claims")
    next(button for button in at.button if button.label == "Save review").click().run()
    assert not at.exception
    assert ("review", AUDIT_ID, "liability_cap", "rejected", "Cap excludes IP claims") in fake.calls


def test_report_for_another_document_is_not_shown(fake):
    at = run_screen("audit", audit_id=AUDIT_ID, document_id=DOC_ID)
    fake.docs = [{**fake.docs[0], "document_id": "ef" * 32}]
    at.run()
    assert not at.exception
    assert len(at.metric) == 0


def test_trace_shows_totals(fake):
    at = run_screen("trace", audit_id=AUDIT_ID)
    assert not at.exception
    totals = at.dataframe[0].value
    assert totals["Rule"].tolist() == ["liability_cap"]
    assert totals["Steps"].tolist() == [2]


def test_benchmarks_show_table_and_notes(fake):
    at = run_screen("benchmarks")
    assert not at.exception
    assert at.dataframe[0].value["recall@5"].tolist() == [0.61, 0.78]
    assert "50 contracts" in texts(at.caption)


def test_benchmarks_empty(fake):
    fake.benchmarks = lambda: []
    at = run_screen("benchmarks")
    assert any("No benchmark results yet" in text for text in texts(at.info))


def test_failed_start_hides_previous_report(fake):
    at = run_screen("audit", audit_id=AUDIT_ID, audit_saved=True)
    assert len(at.metric) > 0

    def failing_start(document_id, playbook, provider=None, force=False):
        raise ApiError(503, "OpenAI is not reachable")

    fake.start_audit = failing_start
    at.button(key="run_audit").click().run()
    assert not at.exception
    assert "OpenAI is not reachable" in texts(at.error)
    assert len(at.metric) == 0
    assert not any(text.startswith("Saved run") for text in texts(at.caption))


def test_running_audit_for_another_document_is_not_shown(fake):
    fake.audit_state = "running"
    at = run_screen("audit", audit_id=AUDIT_ID, document_id=DOC_ID)
    assert any("Audit running" in text for text in texts(at.info))
    fake.docs = [{**fake.docs[0], "document_id": "ef" * 32}]
    at.run()
    assert not at.exception
    assert not any("Audit running" in text for text in texts(at.info))
    assert "audit_id" not in at.session_state


def test_lost_audit_shows_error_without_polling(fake):
    def missing_audit(audit_id):
        raise ApiError(404, "audit x not found")

    fake.audit = missing_audit
    at = run_screen("audit", audit_id=AUDIT_ID)
    assert not at.exception
    assert "audit x not found" in texts(at.error)
    assert not any("Audit running" in text for text in texts(at.info))
    assert "audit_id" not in at.session_state


def test_viewer_key_changes_with_the_boxes():
    boxes = [{"page": 2, "x": 72.0, "y": 90.0, "width": 348.0, "height": 14.0, "color": "#2a78d6"}]
    same = [dict(reversed(list(boxes[0].items())))]
    assert pdfview.viewer_key("ask_pdf", boxes) == pdfview.viewer_key("ask_pdf", same)
    assert pdfview.viewer_key("ask_pdf", boxes).startswith("ask_pdf_")
    assert pdfview.viewer_key("ask_pdf", boxes) != pdfview.viewer_key("ask_pdf", [])
    moved = [{**boxes[0], "page": 3}]
    assert pdfview.viewer_key("ask_pdf", boxes) != pdfview.viewer_key("ask_pdf", moved)
    assert pdfview.viewer_key("ask_pdf", boxes) != pdfview.viewer_key("audit_pdf", boxes)


def test_link_opens_a_saved_audit_on_one_finding(fake):
    at = run_screen("audit", {"document": DOC_ID, "audit": AUDIT_ID, "rule": "confidentiality"})
    assert not at.exception
    assert at.metric[0].value == "40.0"
    finding = at.selectbox(key=f"finding_{AUDIT_ID}")
    assert finding.value == "confidentiality"
    finding.set_value("liability_cap").run()
    assert at.selectbox(key=f"finding_{AUDIT_ID}").value == "liability_cap"


def test_link_picks_the_trace_audit_and_rules(fake, monkeypatch):
    other = {**fake_api.TRACE[0], "rule_id": "confidentiality"}
    monkeypatch.setattr(fake_api, "TRACE", [*fake_api.TRACE, other])
    at = run_screen("trace", {"audit": AUDIT_ID, "rules": "liability_cap,unknown"})
    assert not at.exception
    assert at.multiselect[0].value == ["liability_cap"]


def test_link_fills_the_search_query(fake):
    at = run_screen("search", {"q": "liability cap"})
    assert not at.exception
    assert at.text_input(key="search_query").value == "liability cap"
    assert [call[1] for call in fake.calls if call[0] == "search"] == ["liability cap"]


def test_link_asks_the_question_on_one_document(fake):
    at = run_screen("ask", {"q": "What is the cap?", "document": DOC_ID})
    assert not at.exception
    assert at.text_input[0].value == "What is the cap?"
    assert at.multiselect[0].value == [DOC_ID]
    assert ("ask", "What is the cap?", {"document_ids": [DOC_ID]}) in [call[:3] for call in fake.calls]
    assert any("Liability is capped" in text for text in texts(at.markdown))
    at.run()
    assert [call[0] for call in fake.calls].count("ask") == 1
