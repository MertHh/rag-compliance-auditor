# Video shot list (about 3 minutes)

1. **Hook (10 s)** — README top: "Audits a contract PDF against a playbook and ties every finding to the exact text."
2. **Upload (20 s)** — Documents page: drop a CUAD contract PDF; metadata appears (type, date, parties, law).
3. **Search (25 s)** — Search "limitation of liability": stage scores table (BM25 rank, dense rank, RRF, rerank, rank change); pick a result, the PDF highlights it.
4. **Ask (20 s)** — Ask "What is the cap on liability?": answer with a verified quote; then ask about something absent: "I could not find…" with nearest passages.
5. **Audit (45 s)** — Audit page: commercial playbook, run; risk score, findings table with status labels; open a missing clause (queries tried, sections examined) and a compliant one (quote highlighted in the PDF); accept one finding with a note; download the PDF report and show the highlighted contract pages.
6. **Agent trace (20 s)** — timeline per rule: search, rewrite, evaluate, verify, wide scan; tokens and cost per step.
7. **Second domain (20 s)** — switch to the GDPR DPA playbook on the EU standard clauses; same engine, new rules.
8. **Local mode (15 s)** — provider "ollama": the same audit with no data leaving the machine.
9. **Benchmarks (20 s)** — Benchmarks page and README tables: retrieval modes, presence from retrieval vs the LLM agent, local vs cloud cost per audit.
10. **Close (5 s)** — `docker compose up` and the repository link.
