from fastapi import APIRouter

from auditor.api.routes.deps import ServicesDep
from auditor.audit.playbook import PlaybookError, find_playbook, list_playbooks
from auditor.llm.base import ProviderUnavailableError, models_label
from auditor.llm.factory import PROVIDERS

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/playbooks")
def playbooks(services: ServicesDep) -> list[dict]:
    items = []
    for key in list_playbooks(services.playbooks_dir):
        try:
            loaded = find_playbook(services.playbooks_dir, key)
        except PlaybookError as exc:
            # One broken file must not hide the others.
            items.append({"key": key, "name": key, "rule_count": 0, "error": str(exc)})
            continue
        items.append({"key": key, "name": loaded.playbook.name,
                      "rule_count": len(loaded.playbook.rules), "error": None})
    return items


@router.get("/providers")
def providers(services: ServicesDep) -> dict:
    items = []
    for name in PROVIDERS:
        try:
            provider = services.provider(name)
            provider.check_available()
        except (ProviderUnavailableError, ValueError) as exc:
            items.append({"name": name, "available": False, "models": None, "error": str(exc)})
            continue
        items.append({"name": name, "available": True, "models": models_label(provider),
                      "error": None})
    return {"default": services.default_provider, "providers": items}
