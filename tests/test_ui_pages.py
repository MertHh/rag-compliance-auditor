from pathlib import Path

import pdfview
import pytest
import shared
from apiclient import ApiError
from fake_api import DOC_ID, FakeApi
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


def run_screen(name: str, **state) -> AppTest:
    at = AppTest.from_file(str(UI / "screens" / f"{name}.py"), default_timeout=10)
    for key, value in state.items():
        at.session_state[key] = value
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
