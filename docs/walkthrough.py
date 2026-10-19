"""Writes docs/how-it-works.md: one question and one audit rule followed through every stage on
a real contract, with the values each stage actually produced. Nothing in that page is typed
by hand; rerun this script to regenerate it.

Needs the contract uploaded and audited with the commercial_contract playbook (docs/demo.md),
the models available (first run downloads ~4 GB), Ollama or OpenAI for the one LLM call, and
no API running on the same data directory (the local vector store allows one process).

Run: AUDITOR_DATA_DIR=data/demo python docs/walkthrough.py
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auditor.audit.citations import verify_quotes  # noqa: E402
from auditor.audit.playbook import find_playbook  # noqa: E402
from auditor.audit.prompts import Wording, evaluate_prompt  # noqa: E402
from auditor.audit.scoring import SEVERITY_WEIGHT, STATUS_MULTIPLIER, Status  # noqa: E402
from auditor.bench.cuad import load_cuad  # noqa: E402
from auditor.config import Settings  # noqa: E402
from auditor.index.store import SearchFilter  # noqa: E402
from auditor.ingestion.chunker import build_chunks  # noqa: E402
from auditor.ingestion.structure import detect_sections  # noqa: E402
from auditor.llm.base import complete_with_retry  # noqa: E402
from auditor.qa.answer import QA_SYSTEM, QAOutput, qa_prompt  # noqa: E402
from auditor.retrieval.config import RetrievalConfig  # noqa: E402
from auditor.services import build_services  # noqa: E402
from auditor.tokens import count_tokens  # noqa: E402
from benchmarks.audit_bench import CUAD_CATEGORY_BY_RULE, presence  # noqa: E402

OUT = ROOT / "docs" / "how-it-works.md"
IMAGES = ROOT / "docs" / "images"
STATUS_TEXT = {"uyumlu": "compliant", "uyumsuz": "non-compliant", "eksik": "missing",
               "belirsiz": "uncertain", "hata": "error"}


def flat(text: str, limit: int | None = None) -> str:
    """One line for a table cell: no-break spaces and runs of whitespace become one space."""
    text = " ".join(text.replace("\xa0", " ").split()).replace("|", "\\|")
    return text if limit is None or len(text) <= limit else text[:limit].rstrip() + "…"


def block(text: str) -> str:
    return "```text\n" + text.replace("\xa0", " ").strip() + "\n```"


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines += ["| " + " | ".join("–" if cell is None else str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def rank(value) -> str:
    return "–" if value is None else f"#{value}"


def render_highlight(pdf: Path, boxes: list, out: Path, color=(0.05, 0.64, 0.05)) -> None:
    """The cited lines boxed on their page, cropped to the passage and rendered at 3x."""
    doc = pymupdf.open(pdf)
    page_no = boxes[0].page
    page = doc[page_no - 1]
    rects = [pymupdf.Rect(*box.bbox) for box in boxes if box.page == page_no]
    for rect in rects:
        page.draw_rect(rect + (-1.5, -1, 1.5, 1), color=color, width=1.2)
    union = rects[0]
    for rect in rects[1:]:
        union |= rect
    clip = pymupdf.Rect(page.rect.x0 + 20, max(union.y0 - 70, 0), page.rect.x1 - 20,
                        min(union.y1 + 70, page.rect.y1))
    page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=clip).save(out)


def latest_audit(db_path: Path, document_id: str, playbook: str) -> tuple[dict, list[dict]]:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT report, trace FROM audits WHERE document_id = ? AND playbook = ?"
                       " AND has_errors = 0 ORDER BY created_at DESC LIMIT 1",
                       (document_id, playbook)).fetchone()
    if row is None:
        raise SystemExit(f"no {playbook} audit of this document in {db_path}; run it first (docs/demo.md)")
    return json.loads(row[0]), json.loads(row[1])


def english_status(text: str) -> str:
    """Trace outputs carry the stored status codes; the page shows their English names."""
    return re.sub(r"status=(\w+)", lambda m: f"status={STATUS_TEXT.get(m.group(1), m.group(1))}", text)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def overlaps_gold(quote: str, gold_texts: list[str], window: int = 8) -> bool:
    """CUAD marks spans in its own text file, whose offsets differ from the PDF's; a quote counts
    as overlapping when any run of `window` consecutive words appears in a marked span."""
    q = words(quote)
    golds = [" ".join(words(g)) for g in gold_texts]
    runs = [" ".join(q[i:i + window]) for i in range(max(len(q) - window + 1, 1))]
    return any(run and run in gold for run in runs for gold in golds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="walkthrough")
    parser.add_argument("--document", default="cuad-cooperation-agreement.pdf")
    parser.add_argument("--cuad-title", default="TUNIUCORP_03_06_2014-EX-10-COOPERATION AGREEMENT")
    parser.add_argument("--question", default="Can a party transfer this agreement to another company "
                                              "without the other party's consent?")
    parser.add_argument("--rule", default="anti_assignment")
    parser.add_argument("--cuad", default=str(ROOT / "data" / "cuad" / "CUAD_v1.json"))
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    services = build_services(settings)
    docstore, retriever = services.docstore, services.retriever
    matches = [i for i in docstore.list_ids() if docstore.load(i).filename == args.document]
    if not matches:
        raise SystemExit(f"{args.document} is not uploaded in {settings.data_dir}")
    doc = docstore.load(matches[0])
    pdf_path = settings.data_dir / "documents" / f"{doc.document_id}.pdf"
    out: list[str] = []
    add = out.append

    # ---------------------------------------------------------------- 1. parsing
    sections = detect_sections(doc.lines)
    chunks = build_chunks(doc, sections)
    parents = {c.parent_id: c for c in chunks}
    page_lines = [line for line in doc.lines if line.page is not None]

    # ---------------------------------------------------------------- 2. search
    config = RetrievalConfig()
    flt = SearchFilter(document_ids=[doc.document_id])
    question = args.question
    bm25 = services.store.search_sparse(retriever._sparse.encode_query(question), config.candidate_k, flt)
    dense_vector = retriever._embedder.embed_query(question)
    dense = services.store.search_dense(dense_vector, config.candidate_k, flt)
    retriever.search(question, config, flt)  # loads the reranker, so the timing below is a warm search
    started = time.perf_counter()
    result = retriever.search(question, config, flt)
    search_s = time.perf_counter() - started

    # ---------------------------------------------------------------- 3. answer
    provider = services.provider(settings.provider)
    prompt = qa_prompt(question, result.parents)
    started = time.perf_counter()
    llm = complete_with_retry(provider, QA_SYSTEM, prompt, QAOutput, "small")
    llm_s = time.perf_counter() - started
    citations = verify_quotes(doc, llm.value.quotes, result.parents)

    # ---------------------------------------------------------------- 4. audit
    loaded = find_playbook(settings.playbooks_dir, "commercial_contract")
    playbook = loaded.playbook
    rule = next(r for r in playbook.rules if r.id == args.rule)
    report, trace = latest_audit(settings.db_path, doc.document_id, "commercial_contract")
    finding = next(f for f in report["findings"] if f["rule_id"] == rule.id)
    steps = [s for s in trace if s["rule_id"] == rule.id]
    contracts, _ = load_cuad(args.cuad)
    cuad = next((c for c in contracts if c.title.strip() == args.cuad_title), None)

    # ================================================================= page
    add("# How it works: one question, start to finish")
    add("")
    add("This page follows one question through every stage of the system on a real contract, then "
        "one audit rule, then explains the benchmark scores. Every number, ranking, prompt and model "
        "answer below was produced by the code, not typed by hand: "
        "[`docs/walkthrough.py`](walkthrough.py) runs the pipeline and writes this page.")
    add("")
    add(f"- **Document:** `{args.cuad_title}` from [CUAD](https://www.atticusprojectai.org/cuad) "
        f"(CC BY 4.0), a {doc.page_count}-page cooperation agreement between two companies, one of "
        "the 50 contracts in the audit benchmark. Lawyers marked its clauses, so every verdict can "
        "be checked.")
    add(f"- **Question:** *{question}*")
    add(f"- **Models:** BAAI/bge-m3 (dense vectors), BM25 (word matching), BAAI/bge-reranker-v2-m3 "
        f"(reranking), {llm.model} (answer).")
    add("")
    add("```mermaid\nflowchart LR\n  A[PDF] --> B[1 Lines with page boxes] --> C[2 Sections] --> D[3 Chunks]\n"
        "  D --> E[4 Two indexes: BM25 + dense]\n  Q[Question] --> F[5 Search both] --> G[6 Fuse RRF] --> H[7 Rerank]\n"
        "  E --> F\n  H --> I[8 Expand to sections] --> J[9 LLM answers with quotes] --> K[10 Verify quotes] --> L[Answer + highlight]\n```")
    add("")

    add("## Part 1: Reading the PDF (done once, at upload)")
    add("")
    add("### Step 1. Text lines with their position on the page")
    add("")
    add(f"PyMuPDF reads the text layer: **{doc.page_count} pages, {len(page_lines)} lines, "
        f"{len(doc.text):,} characters**. Each line keeps its page, its box on the page (x0, y0, x1, y1 "
        "in PDF points) and where it sits in the full text (character offsets). The boxes are what "
        "lets the system draw a highlight later; the offsets tie a quote back to an exact place.")
    add("")
    sample = [line for line in page_lines if len(line.text.strip()) > 30][:4]
    add(table(["text", "page", "box on page", "font size", "characters"],
              [[flat(line.text, 70), line.page, tuple(round(v) for v in line.bbox),
                round(line.font_size, 1) if line.font_size else None,
                f"{line.char_start}–{line.char_end}"] for line in sample]))
    add("")
    add("### Step 2. Sections")
    add("")
    add(f"Headings are found from numbering (`1.`, `2.1`, `Article 3`) and from lines set in a larger "
        f"font. This contract gives **{len(sections)} sections**; the path shows nesting, so `2 > 2.1` "
        "is clause 2.1 inside clause 2. Citations carry this path.")
    add("")
    add(table(["section path", "title", "lines"],
              [[s.path, flat(s.title, 50) or "–", f"{s.line_start}–{s.line_end}"] for s in sections[:12]]))
    add("")
    add("### Step 3. Chunks: small for search, large for reading")
    add("")
    child_tokens = [count_tokens(c.text) for c in chunks]
    add(f"Each section is split into **child chunks** of at most 400 tokens; this contract gives "
        f"**{len(chunks)} chunks** (median {sorted(child_tokens)[len(child_tokens) // 2]} tokens). Small "
        "chunks keep search precise: a match is about one clause, not a whole page. Each chunk also "
        f"points to a **parent**: its enclosing section, up to 2,000 tokens ({len(parents)} parents "
        "here). Search finds children; the LLM later reads parents, so it sees the whole clause "
        "around a match.")
    add("")
    add("### Step 4. Two indexes")
    add("")
    add(f"Every chunk is stored twice in Qdrant: as a **dense vector** ({len(dense_vector)} numbers from "
        "bge-m3, which encode meaning: *transfer* and *assign* land close together) and as a "
        "**sparse BM25 vector** (which words occur and how rare they are: exact terms such as "
        "*assign* or *consent* score high). The two catch different things, so both are searched.")
    add("")

    add("## Part 2: Answering the question")
    add("")
    add("### Step 5. Search both indexes")
    add("")
    add(f"The question is encoded both ways and each index returns its own top {config.candidate_k} "
        "chunks of this document. The top five of each:")
    add("")
    add(table(["rank", "BM25 (words)", "score", "dense (meaning)", "score"],
              [[i + 1,
                flat(f"{bm25[i].payload['section_path']} · {bm25[i].payload['text']}", 60) if i < len(bm25) else None,
                round(bm25[i].score, 2) if i < len(bm25) else None,
                flat(f"{dense[i].payload['section_path']} · {dense[i].payload['text']}", 60) if i < len(dense) else None,
                round(dense[i].score, 3) if i < len(dense) else None] for i in range(5)]))
    add("")
    add("### Step 6. Fuse the two rankings (RRF)")
    add("")
    add(f"Scores from BM25 and from vectors are on different scales, so only ranks are combined. "
        f"Reciprocal Rank Fusion gives each chunk `1/({config.rrf_k} + rank)` from each list it appears "
        "in and adds them. A chunk ranked well by both beats one ranked first by only one.")
    add("")
    top = result.chunks[0]
    s = top.scores
    parts = [f"1/({config.rrf_k} + {r})" for r in (s.bm25_rank, s.dense_rank) if r is not None]
    add(f"For the chunk that ends up first: BM25 rank {rank(s.bm25_rank)}, dense rank "
        f"{rank(s.dense_rank)} → RRF = {' + '.join(parts)} = **{s.rrf_score:.4f}**, fused rank "
        f"#{s.fused_rank}.")
    add("")
    add("### Step 7. Rerank")
    add("")
    add(f"The {config.candidate_k} fused candidates go to a cross-encoder (bge-reranker-v2-m3), which "
        "reads the question and each chunk together and scores how well the chunk answers it, from 0 "
        f"to 1. It is slower than vector search, so it only sees these candidates. The top "
        f"{config.final_k} after reranking (the whole search, with models loaded, took {search_s:.1f} s):")
    add("")
    add(table(["final", "section", "BM25", "dense", "RRF", "fused", "rerank", "text"],
              [[c.scores.final_rank, c.section_path, rank(c.scores.bm25_rank), rank(c.scores.dense_rank),
                f"{c.scores.rrf_score:.4f}", f"#{c.scores.fused_rank}", f"{c.scores.rerank_score:.3f}",
                flat(c.text, 70)] for c in result.chunks]))
    add("")
    add(f"The rerank score is also the evidence check: if the best one were below "
        f"{config.min_rerank_score} (a threshold set from the benchmark), the system would answer "
        f"\"not found\" instead of asking the LLM. Here the best is {top.scores.rerank_score:.3f}"
        f"{', so it goes on' if not result.insufficient_evidence else ', so it stops'}.")
    add("")
    add("### Step 8. Expand to whole sections")
    add("")
    add(f"The {len(result.chunks)} chunks belong to **{len(result.parents)} parent sections**; those are "
        "what the LLM reads, so it never judges a clause from a fragment:")
    add("")
    add(table(["section", "characters", "tokens", "from chunks"],
              [[p.section_path, f"{p.char_start}–{p.char_end}", count_tokens(p.text),
                ", ".join(f"#{next(c.scores.final_rank for c in result.chunks if c.chunk_id == cid)}"
                          for cid in p.chunk_ids)] for p in result.parents]))
    add("")
    add("### Step 9. The LLM answers, with quotes")
    add("")
    add("The model gets a fixed instruction and the numbered sections, and must reply in a JSON "
        "schema: an answer and the sentences it relies on, copied word for word. The instruction:")
    add("")
    add(block(QA_SYSTEM))
    add("")
    add(f"<details><summary>The full prompt ({count_tokens(prompt)} tokens)</summary>\n\n{block(prompt)}\n\n</details>")
    add("")
    add(f"The raw reply ({llm.model}, {llm.usage.input_tokens} tokens in, {llm.usage.output_tokens} out, "
        f"{llm_s:.1f} s, ${llm.usage.cost_usd:.4f}):")
    add("")
    add("```json\n" + json.dumps(llm.value.model_dump(), indent=2, ensure_ascii=False).replace("\xa0", " ") + "\n```")
    add("")
    add("### Step 10. Verify every quote")
    add("")
    add("A model can paraphrase or invent a sentence, so its quotes are not trusted. Each one is "
        "searched for in the document text (quote marks, spacing and words hyphenated at a line end "
        "are normalized; nothing else). A quote found gets its exact character range, page and line "
        "boxes; a quote not found is dropped and never shown. If no quote survives, the answer is "
        "\"not found\".")
    add("")
    rows = []
    for quote in llm.value.quotes:
        match = next((c for c in citations if flat(c.quote)[:40] == flat(quote)[:40]), None)
        rows.append([flat(quote, 80), "verified" if match else "dropped",
                     f"{match.char_start}–{match.char_end}" if match else None,
                     match.page if match else None, len(match.bboxes) if match else None,
                     match.section_path if match else None])
    add(table(["quote from the model", "check", "characters", "page", "line boxes", "section"], rows))
    add("")
    if citations:
        first = citations[0]
        source = next((c for c in result.chunks if c.char_start <= first.char_start < c.char_end), None)
        if source is None or source.scores.final_rank != 1:
            where = (f"chunk #{source.scores.final_rank} (section {source.section_path})" if source
                     else "a part of a parent section that no top chunk covered")
            add(f"Note that the quote is not from the top-ranked chunk #1 (section "
                f"{result.chunks[0].section_path}) but from {where}. Ranking is not perfect; the "
                "answer survives because the LLM reads whole parent sections (step 8) and picks the "
                "sentence that actually answers, and because that sentence must then pass this check.")
            add("")
        image = IMAGES / "walkthrough-answer.png"
        render_highlight(pdf_path, citations[0].bboxes, image)
        add("### Result")
        add("")
        add(f"> **{flat(llm.value.answer)}**")
        add("")
        add(f"![The verified quote boxed on page {citations[0].page} of the contract](images/{image.name})")
        add(f"*The boxes are drawn from the line coordinates found in step 10, on page {citations[0].page}.*")
        add("")

    # ---------------------------------------------------------------- audit part
    add("## Part 3: One audit rule")
    add("")
    add(f"An audit runs the same machinery once per rule of a playbook. The rule here, from "
        f"`playbooks/commercial_contract.yaml`:")
    add("")
    add("```yaml\n" + "\n".join([f"id: {rule.id}", f"title: {rule.title}", f"type: {rule.type}",
                                 f"severity: {rule.severity}", f"queries: {json.dumps(rule.queries)}",
                                 f"criteria: \"{rule.criteria}\""]) + "\n```")
    add("")
    add("An agent (a small LangGraph state machine) handles each rule: **search** with the rule's "
        "queries → if the best rerank score is too weak, **rewrite** the queries and search again (at "
        "most twice) → **evaluate**: the LLM gets the sections and the rule and answers *is the clause "
        "there, and does it meet the criteria?* with quotes → **verify** the quotes as in step 10 → if "
        "it says the clause is missing, a **wide scan** checks the top 15 sections one by one before "
        "accepting that. The prompt starts like this:")
    add("")
    add(block(Wording(playbook.document, playbook.item).evaluate_system()))
    add("")
    add(f"<details><summary>The rule part of the evaluation prompt</summary>\n\n"
        f"{block(evaluate_prompt(rule, [], Wording(playbook.document, playbook.item)).split('Sections:')[0])}\n\n</details>")
    add("")
    add(f"What the agent did for this rule in the saved audit ({report['created_at'][:16].replace('T', ' ')} UTC, "
        f"{report['model']}):")
    add("")
    add(table(["step", "input", "output", "seconds", "tokens"],
              [[st["node"], flat(st["input"], 60), flat(english_status(st["output"]), 60), round(st["duration_s"], 1),
                st["input_tokens"] + st["output_tokens"]] for st in steps]))
    add("")
    add(f"**Verdict: {STATUS_TEXT[finding['status']]}.** {flat(finding['reasoning'] or '')}")
    add("")
    for citation in finding["citations"]:
        add(f"> {flat(citation['quote'])}  \n> — page {citation['page']}, section {citation['section_path']}")
        add("")
    add("The status comes from two yes/no answers of the model and the rule type, by a fixed table:")
    add("")
    add(table(["type", "found, meets criteria", "found, does not", "not found"],
              [["must_exist", "compliant", "non-compliant", "missing"],
               ["condition", "compliant", "non-compliant", "missing"],
               ["must_not_exist", "non-compliant", "compliant", "compliant"]]))
    add("")
    add("The **risk score** of the whole audit is computed by code, not by the model: each rule weighs "
        f"by severity ({', '.join(f'{k} {v}' for k, v in SEVERITY_WEIGHT.items())}) times a status factor "
        f"(compliant {STATUS_MULTIPLIER[Status.COMPLIANT]}, uncertain {STATUS_MULTIPLIER[Status.UNCERTAIN]}, "
        f"non-compliant and missing {STATUS_MULTIPLIER[Status.MISSING]}); the products are summed, divided by "
        f"the largest possible sum and shown as a percentage: 0 means every rule passed, 100 means every rule failed. This audit: "
        f"**{report['risk_score']}** over {len(report['findings'])} rules.")
    add("")

    # ---------------------------------------------------------------- scores
    add("## Part 4: What the benchmark scores mean")
    add("")
    add("The README reports scores measured on CUAD, where lawyers marked which clauses each "
        "contract contains. Here is what each one means, worked out on this contract's audit.")
    add("")
    add("### Audit: finding missing clauses")
    add("")
    add("For every contract × rule pair there are two answers: the system's (present or missing) and "
        "the lawyers'. The risky mistake in an audit is to overlook a missing clause, so the class "
        "being detected is **missing**:")
    add("")
    add(table(["", "lawyers: missing", "lawyers: present"],
              [["**system: missing**", "TP, a correct catch", "FP, a false alarm"],
               ["**system: present**", "FN, a missed gap", "correct, not counted here"]]))
    add("")
    add("- **Precision** = TP / (TP + FP): when the system says *missing*, how often it is right.")
    add("- **Recall** = TP / (TP + FN): of the clauses that really are missing, how many it found.")
    add("- **F1** = 2 · precision · recall / (precision + recall): one number that is high only when "
        "both are. Calling every clause missing gives recall 1.0 but poor precision, and a low F1.")
    add("- **Citation accuracy:** when both say *present*, the share of the system's quotes that "
        "overlap the text the lawyers marked. A quote that misses can still be a relevant sentence "
        "the lawyers did not mark, so this is a lower bound.")
    add("- **Undecided %:** findings left uncertain or failed. They are left out of precision and "
        "recall, so they are reported on their own; otherwise answering *uncertain* would hide errors.")
    add("")
    if cuad is not None:
        tp = fp = fn = 0
        cited = hits = 0
        rows = []
        for f in report["findings"]:
            category = CUAD_CATEGORY_BY_RULE.get(f["rule_id"])
            predicted = presence(f["type"], f["status"])
            gold_spans = cuad.spans.get(category, []) if category else []
            gold = bool(gold_spans) if category else None
            if category is None:
                outcome = "no CUAD label"
            elif predicted is None:
                outcome = "undecided"
            elif not predicted and not gold:
                tp += 1
                outcome = "TP"
            elif not predicted:
                fp += 1
                outcome = "FP"
            elif not gold:
                fn += 1
                outcome = "FN"
            else:
                outcome = "both present"
                gold_texts = [cuad.text[a:b] for a, b in gold_spans]
                for c in f["citations"]:
                    cited += 1
                    hits += overlaps_gold(c["quote"], gold_texts)
            rows.append([f["rule_id"], STATUS_TEXT[f["status"]],
                         "–" if predicted is None else ("present" if predicted else "missing"),
                         "–" if gold is None else ("present" if gold else "missing"), outcome])
        add(f"This contract, the audit above against the lawyers' labels:")
        add("")
        add(table(["rule", "verdict", "system says", "lawyers say", "counts as"], rows))
        add("")
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        add(f"TP {tp}, FP {fp}, FN {fn} → precision {tp}/{tp + fp} = **{precision:.3f}**, recall "
            f"{tp}/{tp + fn} = **{recall:.3f}**, F1 **{f1:.3f}**. Citation accuracy: {hits} of {cited} "
            f"quotes overlap a marked span{f' = **{hits / cited:.3f}**' if cited else ''}. The README "
            "numbers are the same counts summed over 50 contracts. (Here overlap is checked by words, "
            "because CUAD's offsets refer to its own text file; the benchmark itself compares offsets.)")
        add("")
    add("### Search: is the right passage near the top?")
    add("")
    add("For each CUAD question the lawyers' passage is known; the score looks at the rank of the "
        "first result that touches it.")
    add("")
    add("- **recall@5:** the share of questions where that passage is in the top 5 (recall@30: top 30).")
    add("- **MRR** (mean reciprocal rank): the average of 1 / rank of the first correct result: rank 1 "
        "counts 1, rank 2 counts 0.5, rank 5 counts 0.2, not found counts 0. An MRR of 0.67 means the "
        "right passage is usually first or second.")
    add("")
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
