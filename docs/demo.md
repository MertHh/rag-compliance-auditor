# Demo document and screenshots

The README screenshots come from one public research paper audited with the `research_paper`
playbook. Nothing in it is legal text: the engine is the same one the contract benchmarks measure.

| | |
|---|---|
| Paper | Federer LM, Belter CW, Joubert DJ, et al. *Data sharing in PLOS ONE: An analysis of Data Availability Statements.* PLOS ONE 13(5): e0194768, 2018. [doi:10.1371/journal.pone.0194768](https://doi.org/10.1371/journal.pone.0194768) |
| License | Creative Commons CC0 public domain dedication, as stated on its first page |
| Playbook | `playbooks/research_paper.yaml`, 14 reporting rules for an empirical paper |
| Model | qwen3:8b through Ollama, thinking off, 8k context |

## Rebuild

```bash
curl -L -o data/demo/plos-one-data-availability.pdf \
  "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0194768&type=printable"
export AUDITOR_DATA_DIR=data/demo AUDITOR_PROVIDER=ollama OLLAMA_THINK=0 OLLAMA_NUM_CTX=8192
python -m auditor.cli ingest data/demo/plos-one-data-availability.pdf
python -m auditor.cli audit <document_id> research_paper
```

Then start the API and the UI on the same data directory and take the shots:

```bash
python -m uvicorn --factory auditor.api.main:create_app --port 8000
python -m streamlit run ui/app.py
pip install -e ".[docs]" && python -m playwright install chromium
python docs/screenshots.py
```

`docs/screenshots.py` lists every shot: page, document, playbook, the finding or rules it opens,
and where it scrolls. Pages read `?document=`, `?audit=`, `?rule=`, `?rules=` and `?q=` from the
URL, so a shot is one link and no clicking.
