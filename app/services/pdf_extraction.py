from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .product_importer import ProductCandidate


class LLMExtractorUnavailable(RuntimeError):
    """Raised when no configured LLM provider can process the PDF."""


def extract_products_via_llm(
    pdf_path: str | Path,
    provider: str,
    model: str,
    api_key: str,
    dst_folder: str | Path | None = None,
    filename_prefix: str = "job",
    timeout: int | None = None,
) -> tuple[list[ProductCandidate], dict]:
    """Unified entry point: dispatch PDF extraction to the configured provider.

    Adding a new provider only requires one more branch here; call sites stay
    untouched.
    """
    normalized = (provider or "").strip().lower()

    if normalized == "anthropic":
        from .claude_pdf_extractor import ClaudePDFUnavailable, extract_products_with_claude

        kwargs = {
            "model": model,
            "api_key": api_key,
            "dst_folder": dst_folder,
            "filename_prefix": filename_prefix,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            return extract_products_with_claude(pdf_path, **kwargs)
        except ClaudePDFUnavailable as exc:
            raise LLMExtractorUnavailable(str(exc)) from exc

    if normalized == "openai":
        from .openai_pdf_extractor import OpenAIPDFUnavailable, extract_products_with_openai

        kwargs = {
            "model": model,
            "api_key": api_key,
            "dst_folder": dst_folder,
            "filename_prefix": filename_prefix,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            return extract_products_with_openai(pdf_path, **kwargs)
        except OpenAIPDFUnavailable as exc:
            raise LLMExtractorUnavailable(str(exc)) from exc

    raise LLMExtractorUnavailable(f"Provider no soportado: {provider!r}")


def try_llm_extraction(
    pdf_path: str | Path,
    job_id: int,
    config: Mapping,
    dst_folder: str | Path,
) -> tuple[list[ProductCandidate] | None, dict]:
    """Try LLM extraction based on the app config. Never raises.

    Returns (candidates_or_None, summary_partial). Summary always carries
    extractor/error context so the caller can surface it in the job record.
    """
    if not config.get("LLM_SUPERVISOR_ENABLED"):
        return None, {}

    provider = (config.get("LLM_SUPERVISOR_PROVIDER") or "").strip().lower()
    model = (config.get("LLM_SUPERVISOR_MODEL") or "").strip()
    api_key = (config.get("LLM_SUPERVISOR_API_KEY") or "").strip()
    if not provider or not model or not api_key:
        return None, {}

    prefix = f"job{job_id}"
    summary: dict = {"extractor": provider}
    try:
        candidates, stats = extract_products_via_llm(
            pdf_path,
            provider=provider,
            model=model,
            api_key=api_key,
            dst_folder=dst_folder,
            filename_prefix=prefix,
        )
        summary.update({f"{provider}_{k}": v for k, v in stats.items()})
        return candidates, summary
    except LLMExtractorUnavailable as exc:
        summary["llm_error"] = str(exc)[:240]
        return None, summary
