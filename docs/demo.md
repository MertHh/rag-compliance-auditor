# Demo documents and screenshots

The README screenshots and [how-it-works.md](how-it-works.md) come from two public documents,
audited locally with qwen3:8b through Ollama (thinking off, 8k context).

| | Contract | Research paper |
|---|---|---|
| Document | `TUNIUCORP_03_06_2014-EX-10-COOPERATION AGREEMENT`, 9 pages, one of the 50 contracts in `benchmarks/subset.json` | Federer LM, Belter CW, Joubert DJ, et al. *Data sharing in PLOS ONE: An analysis of Data Availability Statements.* PLOS ONE 13(5): e0194768, 2018. [doi:10.1371/journal.pone.0194768](https://doi.org/10.1371/journal.pone.0194768) |
| Source | the PDF in the [CUAD v1](https://zenodo.org/records/4595826) archive, `full_contract_pdf/Part_II/Collaboration/` | PLOS ONE |
| License | CC BY 4.0 (CUAD, The Atticus Project) | Creative Commons CC0 public domain dedication, as stated on its first page |
| Playbook | `commercial_contract` (18 rules) | `research_paper` (14 rules) |

## Rebuild

```bash
export AUDITOR_DATA_DIR=data/demo AUDITOR_PROVIDER=ollama OLLAMA_THINK=0 OLLAMA_NUM_CTX=8192

curl -L -o data/cuad-pdf/CUAD_v1.zip https://zenodo.org/records/4595826/files/CUAD_v1.zip
unzip -j data/cuad-pdf/CUAD_v1.zip "*TUNIUCORP_03_06_2014-EX-10-COOPERATION AGREEMENT.PDF" -d data/cuad-pdf
cp "data/cuad-pdf/TUNIUCORP_03_06_2014-EX-10-COOPERATION AGREEMENT.PDF" data/demo/cuad-cooperation-agreement.pdf
curl -L -o data/demo/plos-one-data-availability.pdf \
  "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0194768&type=printable"

python -m auditor.cli ingest data/demo/cuad-cooperation-agreement.pdf
python -m auditor.cli audit <document_id> commercial_contract
python -m auditor.cli ingest data/demo/plos-one-data-availability.pdf
python -m auditor.cli audit <document_id> research_paper
```

The walkthrough runs the pipeline in-process, so stop the API on this data directory first:

```bash
python -m benchmarks.get_cuad          # the lawyers' labels, for part 4
python docs/walkthrough.py             # writes docs/how-it-works.md and docs/images/walkthrough-answer.png
```

Screenshots need the API and the UI on the same data directory:

```bash
python -m uvicorn --factory auditor.api.main:create_app --port 8000
python -m streamlit run ui/app.py
pip install -e ".[docs]" && python -m playwright install chromium
python docs/screenshots.py
```

`docs/screenshots.py` lists every shot: page, document, playbook, the finding or rules it opens,
and where it scrolls. Pages read `?document=`, `?audit=`, `?rule=`, `?rules=` and `?q=` from the
URL, so a shot is one link and no clicking.
