from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from flask import current_app

from ..utils import relative_product_image_path
from .llm_supervisor import SupervisionRequest, get_supervisor, needs_supervision
from .ocr import OCRUnavailable, extract_text_from_image
from .product_importer import ProductCandidate, parse_products_from_text


@dataclass(frozen=True)
class ImageImportOutcome:
    candidates: list[ProductCandidate]
    ocr_text: str
    ocr_chars: int
    supervisor: str
    used_supervisor: bool
    fallback_reason: str | None  # set when OCR was unavailable or yielded nothing


def build_candidates_from_image(
    saved_filename: str,
    original_filename: str,
    full_path: str | Path,
    mode: str | None = None,
) -> ImageImportOutcome:
    """Run the layered pipeline: preprocess → OCR → heuristics → optional LLM.

    Falls back to a single placeholder draft (current behavior) when OCR is
    disabled, missing, or returns nothing useful — so the import flow always
    produces at least one reviewable item.
    """
    config = current_app.config
    relative_image = relative_product_image_path(saved_filename)

    if not config.get("OCR_ENABLED", True):
        return _placeholder_outcome(original_filename, relative_image, "ocr_disabled")

    try:
        ocr = extract_text_from_image(
            full_path,
            languages=config.get("OCR_LANGUAGES", "spa+eng"),
            max_dimension=config.get("OCR_MAX_IMAGE_DIMENSION", 2000),
        )
    except OCRUnavailable as exc:
        return _placeholder_outcome(original_filename, relative_image, f"ocr_unavailable:{exc}")

    candidates = parse_products_from_text(ocr.text) if ocr.text else []
    candidates = [_attach_image(c, relative_image) for c in candidates]
    if len(candidates) > 1:
        candidates = [_tag_uncropped(c) for c in candidates]

    supervisor = get_supervisor()
    used_supervisor = False
    if needs_supervision(candidates, ocr.text, mode, config.get("OCR_MIN_CHARS", 20)):
        result = supervisor.review(
            SupervisionRequest(
                ocr_text=ocr.text,
                heuristic_candidates=candidates,
                image_path=relative_image,
                hints={"mode": mode, "original_filename": original_filename},
            )
        )
        candidates = [_attach_image(c, relative_image) for c in result.candidates]
        used_supervisor = result.provider != "null"

    if not candidates:
        return _placeholder_outcome(
            original_filename,
            relative_image,
            "no_candidates",
            ocr_text=ocr.text,
            ocr_chars=ocr.chars,
            supervisor=supervisor.__class__.__name__,
            used_supervisor=used_supervisor,
        )

    return ImageImportOutcome(
        candidates=candidates,
        ocr_text=ocr.text,
        ocr_chars=ocr.chars,
        supervisor=supervisor.__class__.__name__,
        used_supervisor=used_supervisor,
        fallback_reason=None,
    )


def _attach_image(candidate: ProductCandidate, relative_image: str) -> ProductCandidate:
    data = dict(page_number=candidate.page_number or 1)
    if not candidate.image_path:
        data["image_path"] = relative_image
    return replace(candidate, **data)


def _tag_uncropped(candidate: ProductCandidate) -> ProductCandidate:
    if "image_not_cropped" in candidate.warnings:
        return candidate
    return replace(candidate, warnings=candidate.warnings + ("image_not_cropped",))


def _placeholder_outcome(
    original_filename: str,
    relative_image: str,
    reason: str,
    ocr_text: str = "",
    ocr_chars: int = 0,
    supervisor: str = "NullSupervisor",
    used_supervisor: bool = False,
) -> ImageImportOutcome:
    stem = Path(original_filename).stem.replace("_", " ").replace("-", " ").strip()
    name = (stem or "Producto sin nombre")[:180]
    placeholder = ProductCandidate(
        name=name,
        price=Decimal("0"),
        description="",
        sku=None,
        stock=0,
        image_path=relative_image,
    )
    return ImageImportOutcome(
        candidates=[placeholder],
        ocr_text=ocr_text,
        ocr_chars=ocr_chars,
        supervisor=supervisor,
        used_supervisor=used_supervisor,
        fallback_reason=reason,
    )
