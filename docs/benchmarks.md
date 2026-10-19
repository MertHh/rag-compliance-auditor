# Benchmarks

What is measured, on what, and what came out. The data is [CUAD v1](https://www.atticusprojectai.org/cuad) by The Atticus Project (CC BY 4.0): 510 commercial contracts in which lawyers marked the text of 41 clause types, so both "did search find the right passage?" and "is the clause really missing?" have a known answer. The audit benchmark uses a fixed 50-contract subset (`benchmarks/subset.json`).

What precision, recall, F1, citation accuracy, recall@5 and MRR mean, worked out on one contract: [how it works, part 4](how-it-works.md#part-4-what-the-benchmark-scores-mean).

## Models compared

| model | missing F1 | citation accuracy | seconds per audit | USD per audit |
|---|---|---|---|---|
| qwen3:14b (local) | 0.877 | 0.781 | 1584 | 0 |
| qwen3:8b (local, default) | 0.825 | 0.727 | 389 | 0 |
| gpt-5.4-mini | 0.752 | 0.659 | 151 | 0.117 |

_Same first 15 contracts of the 50-contract subset, 17 rules each; full tables [below](#all-tables)._

## Findings

- **Hybrid search wins; lexical beats dense on contracts.** On 867 queries over 100 CUAD contracts, BM25 + dense fused with RRF reaches recall@5 0.820 and MRR 0.672, ahead of BM25 alone (0.802) and dense alone (0.739). Contract wording is formulaic, so exact terms matter.
- **The reranker does not improve ranking here.** Hybrid + rerank scores recall@5 0.796 and MRR 0.658, slightly below plain hybrid. It stays in the pipeline because its score is the evidence-sufficiency signal: below `min_rerank_score` the agent rewrites the query and, if still nothing, reports the clause missing. The threshold (0.005) is set from data so that 95% of clauses that are present stay above it.
- **Semantic chunking and an LLM context prefix bring nothing measurable.** Semantic chunks: recall@5 0.792 vs 0.796 for structural chunks, which also keep clause numbers for citations. A one-sentence context prefix per chunk (qwen3:8b): 0.808 with and without it on the 50-contract subset, so it stays off and uploads need no LLM call per chunk.
- **The LLM is what makes the verdict reliable.** On the same 850 contract–rule pairs (50 contracts × 17 rules), deciding "missing" from the retrieval score alone, with the threshold tuned on the other 98 contracts, gives F1 0.834 at precision 0.746. The qwen3:8b agent reaches F1 0.875 at precision 0.950, and 78% of its quotes overlap a span the lawyers marked.
- **A local 8B model is usable.** qwen3:8b (thinking off) audits a contract in about 6 minutes on an RTX 3060 with zero schema errors and $0 cost. llama3.1:8b and granite3.3:8b were clearly weaker on the first five contracts (F1 0.545 and 0.293, with schema errors). On the same first 15 contracts, qwen3:14b reached F1 0.877 against 0.825 for qwen3:8b, with citation accuracy 0.781 against 0.727, but it took about 26 minutes per contract instead of 6.5 minutes, because on a 12 GB card it only fits with the reranker moved to the CPU. The 8B model stays the default; 14B is worth it on a larger GPU.
- **The GDPR playbook works on a real DPA.** On the European Commission's Art. 28 standard contractual clauses (Decision 2021/915 annex, 16 pages), qwen3:8b marks 11 of 12 rules compliant with verified quotes in under 3 minutes; the twelfth (processor using data for its own purposes) comes out uncertain because the model claimed a clause without quoting it. This demo also exposed words hyphenated at PDF line breaks ("con-" / "troller"), which quote matching now ignores. The CUAD rows above were measured before that fix; CUAD text has almost no such breaks.
- **The local model beats the OpenAI models on this task.** On the same first 15 contracts, gpt-5.4-mini reaches F1 0.752 (precision 0.951, recall 0.622, citation accuracy 0.659) at $0.117 and about 2.5 minutes per audit, below qwen3:8b (0.825). It rarely calls a clause missing, so it misses absent clauses. On the first 5 contracts, gpt-5.5 as the judge reaches F1 0.867 against 0.800 for mini, but its citation accuracy is lower (0.594 against 0.698) and it costs $0.68 per audit; qwen3:8b scores 0.895 and qwen3:14b 0.914 on those 5. Five contracts are only a rough check. gpt-5.4-mini stays the OpenAI default for its cost; the free local model is the recommended default.

## All tables

The tables between the markers are written by `python -m benchmarks.make_readme_table` from `benchmarks/results/*.json`; no number is typed by hand.

<!-- BENCHMARKS:START -->

### Retrieval on CUAD (100 contracts)

| config | recall@5 | recall@30 | MRR | queries |
| --- | --- | --- | --- | --- |
| bm25 | 0.802 | 0.958 | 0.661 | 867 |
| dense | 0.739 | 0.948 | 0.585 | 867 |
| hybrid | 0.82 | 0.972 | 0.672 | 867 |
| hybrid + rerank | 0.796 | 0.972 | 0.658 | 867 |

- Each query searches one contract; a hit is the first chunk overlapping a span the lawyers marked. Structural chunking, no context prefix.

_Source: retrieval.json; measured 2026-10-15._

### Chunking (hybrid + rerank)

| config | recall@5 | recall@30 | MRR | queries |
| --- | --- | --- | --- | --- |
| structural | 0.796 | 0.972 | 0.658 | 867 |
| semantic | 0.792 | 0.983 | 0.667 | 867 |

- Semantic chunks break where adjacent sentence embeddings drift furthest (90th percentile), at most 400 tokens; structural chunks follow clause numbering.

_Source: chunking.json; measured 2026-10-15._

### Context prefix (50-contract subset, hybrid + rerank)

| config | context model | recall@5 | recall@30 | MRR | queries |
| --- | --- | --- | --- | --- | --- |
| off | - | 0.808 | 0.995 | 0.685 | 365 |
| on | ollama qwen3:8b | 0.808 | 0.992 | 0.684 | 365 |

- One LLM sentence per chunk, prepended before embedding. Cost $0.00; 0 chunks without a prefix.

_Source: context_prefix.json; measured 2026-10-16._

### Clause presence from retrieval alone (hybrid + rerank)

| threshold rule | threshold | missing precision | missing recall | missing F1 |
| --- | --- | --- | --- | --- |
| provisional default | 0.05 | 0.877 | 0.786 | 0.829 |
| best F1 | 0.3193 | 0.811 | 0.966 | 0.882 |
| keeps 95% of present clauses | 0.005 | 0.948 | 0.284 | 0.437 |

- Positive class: clause missing. 3600 contract-category pairs. Recommended min_rerank_score: 0.0050 (keeps 95% of present clauses above it).

_Source: presence.json; measured 2026-10-15._

### Audit on the CUAD subset

#### 50 contracts

| provider | models | rules | missing precision | missing recall | missing F1 | citation accuracy | undecided % | errors | seconds per audit | USD per audit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ollama | qwen3:8b | 17 | 0.95 | 0.811 | 0.875 | 0.782 | 5.9 | 0 | 370.5 | 0 |

- 50 of 50 subset contracts; positive class: clause missing; citation accuracy counts quotes overlapping a marked span; undecided % includes errors.

#### 15 contracts

| provider | models | rules | missing precision | missing recall | missing F1 | citation accuracy | undecided % | errors | seconds per audit | USD per audit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ollama | qwen3:14b | 17 | 0.934 | 0.826 | 0.877 | 0.781 | 4.3 | 0 | 1584.2 | 0 |
| ollama | qwen3:8b | 17 | 0.925 | 0.745 | 0.825 | 0.727 | 7.8 | 0 | 389 | 0 |
| openai | gpt-5.4-mini | 17 | 0.951 | 0.622 | 0.752 | 0.659 | 2.7 | 0 | 151 | 0.1174 |

- 15 of the first 15 of 50 subset contracts; positive class: clause missing; citation accuracy counts quotes overlapping a marked span; undecided % includes errors.

#### 5 contracts

| provider | models | rules | missing precision | missing recall | missing F1 | citation accuracy | undecided % | errors | seconds per audit | USD per audit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ollama | llama3.1:8b | 17 | 0.72 | 0.439 | 0.545 | 0.476 | 27.1 | 4 | 523.3 | 0 |
| ollama | qwen3:14b | 17 | 0.93 | 0.898 | 0.914 | 0.704 | 2.4 | 0 | 1773.3 | 0 |
| ollama | qwen3:8b | 17 | 0.911 | 0.879 | 0.895 | 0.682 | 4.7 | 0 | 461.8 | 0 |
| openai | gpt-5.4-mini | 17 | 0.933 | 0.7 | 0.8 | 0.698 | 0 | 0 | 156.4 | 0.1322 |
| openai | gpt-5.5+gpt-5.4-mini | 17 | 0.925 | 0.817 | 0.867 | 0.594 | 0 | 0 | 223 | 0.6823 |

- 5 of the first 5 of 50 subset contracts; positive class: clause missing; citation accuracy counts quotes overlapping a marked span; undecided % includes errors.

#### 4 contracts

| provider | models | rules | missing precision | missing recall | missing F1 | citation accuracy | undecided % | errors | seconds per audit | USD per audit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ollama | granite3.3:8b | 17 | 1 | 0.171 | 0.293 | 0.526 | 26.5 | 8 | 882.2 | 0 |

- 4 of the first 5 of 50 subset contracts (the fifth audit did not finish); positive class: clause missing; citation accuracy counts quotes overlapping a marked span; undecided % includes errors.

_Source: audit-ollama-granite3-3-8b-first5.json, audit-ollama-llama3-1-8b-first5.json, audit-ollama-qwen3-14b-first15.json, audit-ollama-qwen3-14b-first5.json, audit-ollama-qwen3-8b-first15.json, audit-ollama-qwen3-8b-first5.json, audit-ollama-qwen3-8b.json, audit-openai-gpt-5-4-mini-first15.json, audit-openai-gpt-5-4-mini-first5.json, audit-openai-gpt-5-5-gpt-5-4-mini-first5.json; measured 2026-10-15, 2026-10-16._

<!-- BENCHMARKS:END -->

## Reproduce

```bash
python -m benchmarks.get_cuad
python -m benchmarks.retrieval_bench --contracts 100 --part modes --part chunking   # LLM-free; omit --contracts for all 510
python -m benchmarks.retrieval_bench --part prefix --provider ollama
python -m benchmarks.audit_bench --provider ollama --ollama-model qwen3:8b
python -m benchmarks.audit_bench --provider openai --max-cost 3        # paid; stops at the cap
python -m benchmarks.make_readme_table
```
