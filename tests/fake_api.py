"""A stand-in for ApiClient with canned responses, for Streamlit page tests."""

DOC_ID = "ab" * 32
AUDIT_ID = "c" * 32
LIABILITY = "The total liability shall not exceed the fees paid in twelve months."
BOX = {"page": 2, "bbox": [72.0, 90.0, 420.0, 104.0]}

DOC = {"document_id": DOC_ID, "filename": "contract.pdf", "doc_type": "Services Agreement",
       "date": "2024-03-01", "parties": ["Acme Corp"], "jurisdiction": "New York",
       "has_pdf": True, "indexed": True}
CHUNK = {"chunk_id": "c1", "document_id": DOC_ID, "text": LIABILITY, "section_title": "Liability",
         "section_path": "2", "pages": [2], "bboxes": [BOX], "char_start": 90, "char_end": 158,
         "parent_id": "p1",
         "scores": {"bm25_rank": 1, "bm25_score": 2.1, "dense_rank": 2, "dense_score": 0.8,
                    "rrf_score": 0.0325, "fused_rank": 1, "rerank_score": 0.9, "final_rank": 1,
                    "rank_change": 0}}
CITATION = {"quote": LIABILITY, "document_id": DOC_ID, "page": 2, "section_path": "2",
            "char_start": 90, "char_end": 158, "bboxes": [BOX]}
REPORT = {
    "audit_id": AUDIT_ID, "document_id": DOC_ID, "playbook": "test_pb", "provider": "openai",
    "model": "gpt-5.5+gpt-5.4-mini", "created_at": "2026-10-14T09:30:00+00:00",
    "risk_score": 40.0, "cached": False,
    "findings": [
        {"rule_id": "liability_cap", "title": "Liability cap", "type": "must_exist",
         "status": "uyumlu", "severity": "high", "risk": 0.0, "reasoning": "Capped at fees.",
         "citations": [CITATION], "evidence": {"queries_tried": 1, "sections_examined": 2},
         "error": None, "review": None},
        {"rule_id": "confidentiality", "title": "Confidentiality", "type": "must_exist",
         "status": "eksik", "severity": "medium", "risk": 2.0, "reasoning": "Not found.",
         "citations": [], "evidence": {"queries_tried": 3, "sections_examined": 5},
         "error": None, "review": None},
    ],
    "errors": [],
    "totals": {"duration_s": 38.2, "input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.055},
}
TRACE = [
    {"rule_id": "liability_cap", "node": "search", "started_at": "2026-10-14T09:30:00.000+00:00",
     "duration_s": 0.4, "input": "liability", "output": "2 sections", "models": [],
     "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    {"rule_id": "liability_cap", "node": "evaluate", "started_at": "2026-10-14T09:30:00.400+00:00",
     "duration_s": 3.1, "input": "2 sections", "output": "found", "models": ["gpt-5.5"],
     "input_tokens": 900, "output_tokens": 150, "cost_usd": 0.05},
]
BENCHMARK = {"file": "retrieval.json", "title": "Retrieval", "created_at": "2026-10-20",
             "rows": [{"config": "bm25", "recall@5": 0.61}, {"config": "hybrid", "recall@5": 0.78}],
             "notes": "50 contracts", "error": None}
PROVIDERS = {"default": "openai", "providers": [
    {"name": "openai", "available": True, "models": "gpt-5.5+gpt-5.4-mini", "error": None},
    {"name": "ollama", "available": False, "models": None, "error": "Ollama is not reachable"}]}


class FakeApi:
    def __init__(self):
        self.fail = None          # an ApiError to raise from every call
        self.docs = [DOC]
        self.ask_found = True
        self.audit_state = "done"
        self.calls: list[tuple] = []

    def _call(self, name, *args, result):
        self.calls.append((name, *args))
        if self.fail is not None:
            raise self.fail
        return result

    def documents(self):
        return self._call("documents", result=list(self.docs))

    def document_file(self, document_id):
        return self._call("document_file", document_id, result=b"%PDF-1.4 fake")

    def upload(self, filename, data, metadata, extract_metadata=True, provider=None):
        return self._call("upload", filename, metadata, extract_metadata, result={
            "document_id": DOC_ID, "chunk_count": 2, "already_indexed": False, "warnings": [],
            "document": DOC})

    def search(self, query, mode="hybrid", rerank=True, final_k=5, filters=None):
        return self._call("search", query, mode, rerank, final_k, filters, result={
            "query": query, "config": {}, "insufficient_evidence": False,
            "chunks": [CHUNK], "parents": []})

    def ask(self, question, filters=None, provider=None):
        if self.ask_found:
            result = {"question": question, "found": True,
                      "answer": "Liability is capped at the fees paid in twelve months.",
                      "message": None, "citations": [CITATION], "passages": [],
                      "model": "gpt-5.4-mini",
                      "usage": {"input_tokens": 500, "output_tokens": 40, "cost_usd": 0.001}}
        else:
            result = {"question": question, "found": False, "answer": None,
                      "message": "I could not find a statement about this in these documents.",
                      "citations": [], "passages": [{"section_path": "1", "text": "Definitions"}],
                      "model": None, "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}}
        return self._call("ask", question, filters, provider, result=result)

    def playbooks(self):
        return self._call("playbooks", result=[
            {"key": "test_pb", "name": "Test playbook", "rule_count": 2, "error": None},
            {"key": "broken", "name": "broken", "rule_count": 0, "error": "broken.yaml: bad"}])

    def providers(self):
        return self._call("providers", result=PROVIDERS)

    def start_audit(self, document_id, playbook, provider=None, force=False):
        job = {"audit_id": AUDIT_ID, "document_id": document_id, "playbook": playbook,
               "provider": provider, "status": "running", "started_at": "2026-10-14T09:30:00+00:00",
               "error": None}
        result = ("running", job) if self.audit_state == "running" else ("done", {**REPORT, "cached": True})
        return self._call("start_audit", document_id, playbook, provider, force, result=result)

    def audit(self, audit_id):
        if self.audit_state == "running":
            result = ("running", {"audit_id": audit_id, "document_id": DOC_ID, "status": "running",
                                  "started_at": "2026-10-14T09:30:00+00:00"})
        else:
            result = ("done", REPORT)
        return self._call("audit", audit_id, result=result)

    def audits(self, document_id=None):
        return self._call("audits", document_id, result=[
            {"audit_id": AUDIT_ID, "document_id": DOC_ID, "playbook": "test_pb",
             "provider": "openai", "model": "gpt-5.5+gpt-5.4-mini",
             "created_at": "2026-10-14T09:30:00+00:00", "risk_score": 40.0}])

    def trace(self, audit_id):
        return self._call("trace", audit_id, result=TRACE)

    def review(self, audit_id, rule_id, decision, note=""):
        return self._call("review", audit_id, rule_id, decision, note,
                          result={"decision": decision, "note": note, "updated_at": "now"})

    def export(self, audit_id, fmt):
        return self._call("export", audit_id, fmt, result=b"%PDF-1.4 report")

    def benchmarks(self):
        return self._call("benchmarks", result=[BENCHMARK])
