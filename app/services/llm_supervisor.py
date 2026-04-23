from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from flask import current_app

from .product_importer import ProductCandidate


@dataclass(frozen=True)
class SupervisionRequest:
    ocr_text: str
    heuristic_candidates: list[ProductCandidate]
    image_path: str | None
    hints: dict


@dataclass(frozen=True)
class SupervisionResult:
    candidates: list[ProductCandidate]
    provider: str
    notes: str = ""


class LLMSupervisor(Protocol):
    def review(self, request: SupervisionRequest) -> SupervisionResult: ...


class NullSupervisor:
    """Default no-op supervisor: returns the heuristic candidates untouched.

    Allows the rest of the pipeline to call .review() without conditionals
    and keeps the system working when no LLM provider is configured.
    """

    name = "null"

    def review(self, request: SupervisionRequest) -> SupervisionResult:
        return SupervisionResult(
            candidates=list(request.heuristic_candidates),
            provider=self.name,
            notes="LLM supervisor disabled",
        )


def get_supervisor() -> LLMSupervisor:
    """Factory: returns a configured supervisor or NullSupervisor.

    To wire a real provider later, create a class that implements
    LLMSupervisor and dispatch from this factory based on
    config["LLM_SUPERVISOR_PROVIDER"]. No call site needs to change.
    """
    if not current_app.config.get("LLM_SUPERVISOR_ENABLED"):
        return NullSupervisor()

    provider = (current_app.config.get("LLM_SUPERVISOR_PROVIDER") or "").lower()
    model = current_app.config.get("LLM_SUPERVISOR_MODEL") or ""
    api_key = current_app.config.get("LLM_SUPERVISOR_API_KEY") or ""
    if not provider or not model or not api_key:
        return NullSupervisor()

    if provider == "anthropic":
        from .providers.anthropic_supervisor import AnthropicSupervisor
        return AnthropicSupervisor(model=model, api_key=api_key)

    if provider == "openai":
        from .providers.openai_supervisor import OpenAISupervisor
        return OpenAISupervisor(model=model, api_key=api_key)

    # Unknown provider — keep the heuristic pipeline safe.
    return NullSupervisor()


def needs_supervision(
    candidates: list[ProductCandidate],
    ocr_text: str,
    mode: str | None,
    min_chars: int,
) -> bool:
    """Centralized escalation rules. Keep cheap and explicit."""
    if mode and mode.lower() in ("advanced", "supervised"):
        return True
    if len(ocr_text.strip()) < min_chars:
        return True
    if not candidates:
        return True
    if len(candidates) == 1:
        only = candidates[0]
        if only.price <= 0:
            return True
        name_letters = sum(1 for c in only.name if c.isalpha())
        if len(only.name) < 5 or name_letters < 3:
            return True
    return False


def _candidate_needs_review(candidate: ProductCandidate, mode: str | None) -> bool:
    """Per-candidate gate used to decide whether to spend an LLM call on it."""
    if mode and mode.lower() in ("advanced", "supervised"):
        return True
    if "needs_review" in candidate.warnings or "text_not_paired" in candidate.warnings:
        return True
    if candidate.price <= 0:
        return True
    if candidate.confidence is not None and candidate.confidence < 0.5:
        return True
    name = candidate.name or ""
    name_letters = sum(1 for c in name if c.isalpha())
    if len(name) < 5 or name_letters < 3:
        return True
    return False


def refine_candidates_with_supervisor(
    candidates: list[ProductCandidate],
    mode: str | None,
    ocr_text: str = "",
    max_calls: int | None = None,
) -> tuple[list[ProductCandidate], dict]:
    """Run each low-confidence candidate through the active supervisor.

    Returns (refined_candidates, stats). Never raises — errors are tagged
    as warnings on the offending candidate so the import flow keeps going.
    """
    stats = {"calls": 0, "skipped": 0, "provider": "null", "cap": 0}
    supervisor = get_supervisor()
    provider_name = getattr(supervisor, "name", supervisor.__class__.__name__.lower())
    stats["provider"] = provider_name

    if isinstance(supervisor, NullSupervisor) or not candidates:
        return list(candidates), stats

    if max_calls is None:
        max_calls = current_app.config.get("LLM_MAX_CALLS_PER_JOB", 40)
    stats["cap"] = max_calls

    refined: list[ProductCandidate] = []
    for candidate in candidates:
        if not _candidate_needs_review(candidate, mode):
            refined.append(candidate)
            continue
        if stats["calls"] >= max_calls:
            stats["skipped"] += 1
            refined.append(candidate)
            continue

        request = SupervisionRequest(
            ocr_text=ocr_text or (candidate.description or "") or candidate.name,
            heuristic_candidates=[candidate],
            image_path=candidate.image_path,
            hints={"mode": mode or "standard"},
        )
        result = supervisor.review(request)
        refined.extend(result.candidates or [candidate])
        stats["calls"] += 1

    return refined, stats
