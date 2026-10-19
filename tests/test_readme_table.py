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
    assert table.main(args) == 1  # presence.json is broken: README is written, exit is 1
    assert "### Retrieval" in readme.read_text(encoding="utf-8")
    assert "unreadable result files: presence.json" in capsys.readouterr().err
    assert table.main([*args, "--check"]) == 1


def test_main_exits_zero_when_every_file_is_readable(tmp_path):
    results = _results(tmp_path)
    (results / "presence.json").unlink()
    readme = tmp_path / "README.md"
    readme.write_text(f"# X\n{table.START}\n{table.END}\n", encoding="utf-8")
    args = ["--readme", str(readme), "--results", str(results)]
    assert table.main(args) == 0
    assert table.main([*args, "--check"]) == 0


def test_multiline_error_renders_on_one_quoted_line():
    result = {"file": "bad.json", "title": "bad", "created_at": None, "rows": [], "notes": "",
              "error": "unreadable result file: 2 validation errors\nrows.0.x\n  Input should be a valid number"}
    text = table.render([result])
    quoted = [line for line in text.splitlines() if line.startswith("> ")]
    assert quoted == ["> bad.json: unreadable result file: 2 validation errors rows.0.x Input should be a valid number"]
    assert "Input should" not in [line.strip() for line in text.splitlines() if not line.startswith("> ")]


def test_long_error_is_cut_to_200_characters():
    result = {"file": "bad.json", "title": "bad", "created_at": None, "rows": [], "notes": "",
              "error": "x" * 500}
    quoted = table.render([result]).splitlines()[-3]
    assert quoted == "> bad.json: " + "x" * 200 + "…"


def test_newlines_and_pipes_in_cells_headers_and_titles_stay_inline():
    result = {"file": "a.json", "title": "Retr\nieval | x", "created_at": None, "notes": "two\nlines",
              "rows": [{"con\nfig|": "a\nb|c", "recall@5": 0.5}], "error": None}
    text = table.render([result])
    assert "### Retr ieval \\| x" in text
    assert "| con fig\\| | recall@5 |" in text
    assert "| a b\\|c | 0.5 |" in text
    assert "- two lines" in text


def test_small_floats_keep_their_magnitude():
    result = {"file": "a.json", "title": "T", "created_at": None, "notes": "",
              "rows": [{"config": "c", "p": 1e-05, "q": 0.25}], "error": None}
    assert "| c | 1e-05 | 0.25 |" in table.render([result])


def test_main_leaves_readme_without_markers_untouched(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# No markers\n", encoding="utf-8")
    assert table.main(["--readme", str(readme), "--results", str(tmp_path / "none")]) == 1
    assert readme.read_text(encoding="utf-8") == "# No markers\n"


def test_rows_on_different_contract_counts_get_their_own_tables():
    def audit(name, contracts, f1):
        note = f"{contracts} of {contracts} contracts; positive class: clause missing"
        return {"file": name, "title": "Audit", "created_at": None, "error": None, "notes": note,
                "rows": [{"model": name, "contracts": contracts, "missing F1": f1}]}

    text = table.render([audit("a.json", 5, 0.8), audit("b.json", 50, 0.9), audit("c.json", 5, 0.7)])
    assert text.count("### Audit") == 1
    assert text.index("#### 50 contracts") < text.index("#### 5 contracts")
    five = text[text.index("#### 5 contracts"):]
    assert "| model | missing F1 |" in five
    assert five.index("| a.json | 0.8 |") < five.index("| c.json | 0.7 |")
    assert five.count("- 5 of 5 contracts; positive class: clause missing") == 1
    assert "_Source: a.json, b.json, c.json._" in text
