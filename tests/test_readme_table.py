import json

import pytest

import benchmarks.make_readme_table as table


def _write(directory, name, payload):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(payload if isinstance(payload, str) else json.dumps(payload),
                                  encoding="utf-8")


def _results(tmp_path):
    results = tmp_path / "results"
    _write(results, "audit-ollama-qwen3-8b.json", {"title": "Audit on the CUAD subset", "created_at": "2026-10-20",
           "rows": [{"provider": "ollama", "missing F1": 0.81234, "USD per audit": 0.0}], "notes": "50 of 50"})
    _write(results, "audit-openai-mini.json", {"title": "Audit on the CUAD subset", "created_at": "2026-10-21",
           "rows": [{"provider": "openai", "missing F1": 0.9, "USD per audit": 0.0412, "citation accuracy": None}],
           "notes": ""})
    _write(results, "retrieval.json", {"title": "Retrieval", "rows": [{"config": "a|b", "recall@5": 0.5}]})
    _write(results, "presence.json", "{broken")
    return results


def test_render_orders_merges_and_flags_broken_files(tmp_path):
    from auditor.benchmark_results import load_results

    text = table.render(load_results(_results(tmp_path)))
    assert text.index("### Retrieval") < text.index("### presence") < text.index("### Audit on the CUAD subset")
    assert text.count("### Audit on the CUAD subset") == 1
    assert "| provider | missing F1 | USD per audit | citation accuracy |" in text
    assert "| ollama | 0.8123 | 0 | – |" in text
    assert "| openai | 0.9 | 0.0412 | – |" in text
    assert "| a\\|b | 0.5 |" in text
    assert "> presence.json: unreadable result file" in text
    assert "measured 2026-10-20, 2026-10-21" in text


def test_update_requires_markers():
    with pytest.raises(ValueError, match="markers"):
        table.update_readme("# Title\n", "x")
    updated = table.update_readme(f"a\n{table.START}\nold\n{table.END}\nb\n", "NEW")
    assert updated == f"a\n{table.START}\n\nNEW\n\n{table.END}\nb\n"


def test_main_writes_and_checks(tmp_path, capsys):
    results = _results(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(f"# X\n{table.START}\n{table.END}\n", encoding="utf-8")
    args = ["--readme", str(readme), "--results", str(results)]
    assert table.main([*args, "--check"]) == 1
    assert table.main(args) == 0
    assert "### Retrieval" in readme.read_text(encoding="utf-8")
    assert table.main([*args, "--check"]) == 0


def test_main_leaves_readme_without_markers_untouched(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# No markers\n", encoding="utf-8")
    assert table.main(["--readme", str(readme), "--results", str(tmp_path / "none")]) == 1
    assert readme.read_text(encoding="utf-8") == "# No markers\n"
