import hashlib
import shutil
import urllib.request
import zipfile

import pytest
from cuad_fixture import CAP, CONTRACTS, LAW, write_cuad

import benchmarks.get_cuad as get_cuad
from auditor.bench.cuad import (
    CUAD_CATEGORIES,
    METADATA_CATEGORIES,
    clause_categories,
    download_cuad,
    load_cuad,
    load_subset,
    query_for,
    save_subset,
    select_subset,
)


def test_categories_constant():
    assert len(CUAD_CATEGORIES) == 41
    assert METADATA_CATEGORIES <= set(CUAD_CATEGORIES)
    assert len(METADATA_CATEGORIES) == 5


def test_load_cuad_spans_and_details(tmp_path):
    contracts, details = load_cuad(write_cuad(tmp_path / "cuad.json"))
    by_title = {c.title: c for c in contracts}
    assert set(by_title) == set(CONTRACTS)
    alpha = by_title["ALPHA-SUPPLY"]
    start = alpha.text.index(CAP)
    assert alpha.spans["Cap On Liability"] == [(start, start + len(CAP))]
    assert alpha.text[slice(*alpha.spans["Governing Law"][0])] == LAW
    assert by_title["BETA-SERVICES"].spans["Cap On Liability"] == []
    assert details["Cap On Liability"] == ("Does the contract include a cap on liability upon the breach "
                                           "of a party’s obligation?")


def test_clause_categories_and_query(tmp_path):
    _, details = load_cuad(write_cuad(tmp_path / "cuad.json"))
    assert clause_categories(details) == ["Cap On Liability", "Governing Law"]
    assert query_for("Governing Law", details) == (
        "Governing Law: Which state/country's law governs the interpretation of the contract?")


def test_subset_is_deterministic_sorted_and_round_trips(tmp_path):
    contracts, _ = load_cuad(write_cuad(tmp_path / "cuad.json"))
    first = select_subset(contracts, 2)
    assert first == select_subset(contracts, 2) == sorted(first)
    assert len(first) == 2
    with pytest.raises(ValueError):
        select_subset(contracts, 4)
    save_subset(tmp_path / "subset.json", first)
    assert load_subset(tmp_path / "subset.json") == first


def _zip_with(tmp_path, json_path):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(json_path, "CUAD_v1/CUAD_v1.json")
    return archive


def _digest(path, algorithm):
    return hashlib.new(algorithm, path.read_bytes()).hexdigest()


def test_download_verifies_and_extracts(tmp_path, monkeypatch):
    json_path = write_cuad(tmp_path / "real.json")
    archive = _zip_with(tmp_path, json_path)
    calls = []
    monkeypatch.setattr(urllib.request, "urlretrieve",
                        lambda url, target: calls.append(url) or shutil.copy(archive, target))
    sums = {"zip_md5": _digest(archive, "md5"), "json_sha256": _digest(json_path, "sha256")}

    target = download_cuad(tmp_path / "dest", url="https://example.test/cuad.zip", **sums)
    assert target.read_bytes() == json_path.read_bytes()
    assert not (tmp_path / "dest" / "CUAD_v1.zip").exists()
    download_cuad(tmp_path / "dest", url="https://example.test/cuad.zip", **sums)
    assert calls == ["https://example.test/cuad.zip"]


def test_download_rejects_wrong_checksum(tmp_path, monkeypatch):
    archive = _zip_with(tmp_path, write_cuad(tmp_path / "real.json"))
    monkeypatch.setattr(urllib.request, "urlretrieve", lambda url, target: shutil.copy(archive, target))
    with pytest.raises(ValueError, match="checksum"):
        download_cuad(tmp_path / "dest", zip_md5="0" * 32, json_sha256="0" * 64)
    assert not (tmp_path / "dest" / "CUAD_v1.json").exists()


def test_get_cuad_writes_subset_once(tmp_path, monkeypatch, capsys):
    json_path = write_cuad(tmp_path / "cuad.json")
    monkeypatch.setattr(get_cuad, "download_cuad", lambda dest: json_path)
    monkeypatch.setattr(get_cuad, "SUBSET_FILE", tmp_path / "subset.json")
    assert get_cuad.main(["--subset-size", "2"]) == 0
    assert len(load_subset(tmp_path / "subset.json")) == 2
    assert get_cuad.main(["--subset-size", "3"]) == 0
    assert len(load_subset(tmp_path / "subset.json")) == 2
    assert "subset kept" in capsys.readouterr().out
