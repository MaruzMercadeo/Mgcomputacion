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
    if not provider:
        return NullSupervisor()

    # Future providers register here. Until a real implementation exists,
    # we fall back to NullSupervisor so misconfiguration never breaks imports.
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
