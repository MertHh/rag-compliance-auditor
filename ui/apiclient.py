"""HTTP client for the auditor API. The UI reaches the backend only through this class."""

import os

import httpx

DEFAULT_URL = "http://localhost:8000"


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status  # 0 when the API could not be reached
        self.detail = detail


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):  # FastAPI request validation errors
        return "; ".join(
            f"{'.'.join(str(part) for part in error.get('loc', [])[1:])}: {error.get('msg')}"
            for error in detail
        )
    return str(detail if detail is not None else body)


class ApiClient:
    def __init__(self, http: httpx.Client):
        self._http = http

    @classmethod
    def from_env(cls) -> "ApiClient":
        url = os.environ.get("AUDITOR_API_URL", DEFAULT_URL)
        # Uploads embed a whole contract, so reads may be slow; a down API fails fast.
        return cls(httpx.Client(base_url=url, timeout=httpx.Timeout(300.0, connect=5.0)))

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ApiError(0, f"API did not answer within the time limit ({self._http.base_url}); "
                              "it may still be working") from exc
        except httpx.TransportError as exc:
            raise ApiError(0, f"API unreachable at {self._http.base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(response.status_code, _detail(response))
        return response

    @staticmethod
    def _state(response: httpx.Response) -> tuple[str, dict]:
        return ("running" if response.status_code == 202 else "done"), response.json()

    def health(self) -> dict:
        return self._request("GET", "/health").json()

    def documents(self) -> list[dict]:
        return self._request("GET", "/documents").json()

    def document_file(self, document_id: str) -> bytes:
        return self._request("GET", f"/documents/{document_id}/file").content

    def upload(self, filename: str, data: bytes, metadata: dict, extract_metadata: bool = True,
               provider: str | None = None) -> dict:
        form: dict = {key: value for key, value in metadata.items() if value}
        form["extract_metadata"] = "true" if extract_metadata else "false"
        if provider:
            form["provider"] = provider
        files = {"file": (filename, data, "application/pdf")}
        return self._request("POST", "/documents", files=files, data=form).json()

    def search(self, query: str, mode: str = "hybrid", rerank: bool = True, final_k: int = 5,
               filters: dict | None = None) -> dict:
        body = {"query": query, "mode": mode, "rerank": rerank, "final_k": final_k,
                "filters": filters or {}}
        return self._request("POST", "/search", json=body).json()

    def ask(self, question: str, filters: dict | None = None, provider: str | None = None) -> dict:
        body = {"question": question, "filters": filters or {}, "provider": provider}
        return self._request("POST", "/ask", json=body).json()

    def playbooks(self) -> list[dict]:
        return self._request("GET", "/playbooks").json()

    def providers(self) -> dict:
        return self._request("GET", "/providers").json()

    def start_audit(self, document_id: str, playbook: str, provider: str | None = None,
                    force: bool = False) -> tuple[str, dict]:
        body = {"document_id": document_id, "playbook": playbook, "provider": provider,
                "force": force}
        return self._state(self._request("POST", "/audits", json=body))

    def audit(self, audit_id: str) -> tuple[str, dict]:
        return self._state(self._request("GET", f"/audits/{audit_id}"))

    def audits(self, document_id: str | None = None) -> list[dict]:
        params = {"document_id": document_id} if document_id else None
        return self._request("GET", "/audits", params=params).json()

    def trace(self, audit_id: str) -> list[dict]:
        return self._request("GET", f"/audits/{audit_id}/trace").json()

    def review(self, audit_id: str, rule_id: str, decision: str, note: str = "") -> dict:
        body = {"decision": decision, "note": note}
        return self._request("POST", f"/audits/{audit_id}/findings/{rule_id}/review", json=body).json()

    def export(self, audit_id: str, fmt: str) -> bytes:
        return self._request("GET", f"/audits/{audit_id}/export", params={"format": fmt}).content

    def benchmarks(self) -> list[dict]:
        return self._request("GET", "/benchmarks").json()
