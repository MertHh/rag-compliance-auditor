import json

from auditor.benchmark_results import BenchmarkFile, load_results


def _write(directory, name, payload):
    directory.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (directory / name).write_text(text, encoding="utf-8")


def test_missing_directory_is_empty(tmp_path):
    assert load_results(tmp_path / "nope") == []


def test_reads_valid_and_reports_broken_files(tmp_path):
    good = BenchmarkFile(title="Retrieval on CUAD", created_at="2026-10-20",
                         rows=[{"config": "bm25", "recall@5": 0.61, "mrr": 0.52},
                               {"config": "hybrid+rerank", "recall@5": 0.78, "mrr": 0.66}])
    _write(tmp_path, "b_retrieval.json", good.model_dump())
    _write(tmp_path, "a_broken.json", "{not json")
    _write(tmp_path, "c_wrong.json", {"title": "x", "rows": "not a list"})
    _write(tmp_path, "notes.txt", "ignored")

    broken, retrieval, wrong = load_results(tmp_path)
    assert broken["file"] == "a_broken.json" and broken["rows"] == []
    assert broken["error"].startswith("unreadable result file")
    assert retrieval == {"file": "b_retrieval.json", "title": "Retrieval on CUAD",
                         "created_at": "2026-10-20", "rows": good.rows, "notes": "", "error": None}
    assert wrong["error"].startswith("unreadable result file")


def test_endpoint(api, api_services):
    _write(api_services.benchmarks_dir, "audit.json",
           {"title": "Audit", "rows": [{"provider": "openai", "f1": 0.8}]})
    [result] = api.get("/benchmarks").json()
    assert result["title"] == "Audit" and result["rows"] == [{"provider": "openai", "f1": 0.8}]
