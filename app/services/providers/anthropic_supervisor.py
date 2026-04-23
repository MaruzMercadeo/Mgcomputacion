from __future__ import annotations

import base64
import json
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib import request as urlrequest

from flask import current_app

from ..llm_supervisor import SupervisionRequest, SupervisionResult
from ..product_importer import ProductCandidate


API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 30
MAX_TOKENS = 512


_SYSTEM_PROMPT = (
    "Eres un extractor de datos de productos desde catálogos comerciales. "
    "Recibes texto OCR y/o una imagen recortada de un producto. "
    "Devuelve SIEMPRE un JSON válido con este esquema exacto: "
    '{"name": string, "sku": string|null, "price": number|null, '
    '"description": string|null, "category": string|null, "subcategory": string|null, '
    '"confidence": number entre 0 y 1, "warnings": [string]}. '
    "Reglas: no inventes SKU ni precio si no los ves claros (poné null). "
    "No uses el SKU como nombre. No incluyas texto fuera del JSON."
)


class AnthropicSupervisor:
    name = "anthropic"

    def __init__(self, model: str, api_key: str, timeout: int = DEFAULT_TIMEOUT):
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def review(self, request: SupervisionRequest) -> SupervisionResult:
        existing = list(request.heuristic_candidates)

        # If we already got multiple reasonable candidates, the supervisor would
        # need per-block context we don't have yet — leave them as-is with a tag.
        if len(existing) > 1:
            return SupervisionResult(
                candidates=[_tag(c, ("llm_review_skipped_multi",)) for c in existing],
                provider=self.name,
                notes="skipped: multiple candidates",
            )

        try:
            data = self._call(request)
        except Exception as exc:  # noqa: BLE001
            fallback = existing or [_empty_candidate(request.image_path)]
            return SupervisionResult(
                candidates=[_tag(c, ("llm_error",)) for c in fallback],
                provider=self.name,
                notes=f"fallback: {exc}",
            )

        refined = _merge(data, existing, request.image_path)
        return SupervisionResult(candidates=refined, provider=self.name, notes="ok")

    def _call(self, request: SupervisionRequest) -> dict:
        content = self._build_content(request)
        body = json.dumps({
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content}],
        }).encode("utf-8")

        req = urlrequest.Request(
            API_URL,
            data=body,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")

        payload = json.loads(raw)
        text = ""
        for block in payload.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        return _extract_json(text)

    def _build_content(self, request: SupervisionRequest) -> list:
        content: list[dict] = []
        if request.image_path:
            image_block = _image_block(request.image_path)
            if image_block:
                content.append(image_block)

        hints = request.hints or {}
        parts: list[str] = []

        if hints.get("profile_instructions"):
            parts.append(f"Instrucciones del perfil:\n{hints['profile_instructions']}")
        if hints.get("mode") == "advanced":
            parts.append("Modo avanzado: validá cada campo con especial cuidado.")
        if request.ocr_text:
            parts.append(f"Texto OCR:\n{request.ocr_text[:2000]}")
        if request.heuristic_candidates:
            heur = request.heuristic_candidates[0]
            parts.append(
                "Extracción heurística (puede estar mal, mejorala si hace falta):\n"
                f"- name: {heur.name!r}\n- sku: {heur.sku!r}\n- price: {heur.price}"
            )
        if not parts:
            parts.append("Extraé los datos del producto de la imagen adjunta.")

        parts.append(
            "\nDevolvé SOLO el JSON. No incluyas markdown ni prosa antes o después."
        )
        content.append({"type": "text", "text": "\n\n".join(parts)})
        return content


def _image_block(relative_path: str) -> dict | None:
    try:
        root = Path(current_app.root_path) / "static"
        full = root / relative_path
        if not full.exists():
            return None
        raw = full.read_bytes()
    except Exception:  # noqa: BLE001
        return None

    ext = full.suffix.lower().lstrip(".")
    media_type = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.b64encode(raw).decode("ascii"),
        },
    }


def _extract_json(text: str) -> dict:
    if "```" in text:
        fenced_start = text.find("{", text.find("```"))
        fenced_end = text.rfind("}")
        if fenced_start != -1 and fenced_end > fenced_start:
            return json.loads(text[fenced_start:fenced_end + 1])

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("respuesta sin JSON")
    return json.loads(text[start:end + 1])


def _merge(data: dict, existing: list[ProductCandidate], fallback_image: str | None) -> list[ProductCandidate]:
    raw_price = data.get("price")
    if raw_price is None or raw_price == "":
        price = existing[0].price if existing else Decimal("0")
    else:
        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, TypeError):
            price = existing[0].price if existing else Decimal("0")

    name = (data.get("name") or "").strip()
    if not name and existing:
        name = existing[0].name
    name = name[:180] or "Producto sin nombre"

    sku_raw = data.get("sku")
    sku = str(sku_raw)[:80] if sku_raw else (existing[0].sku if existing else None)

    confidence_raw = data.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else None
    except (TypeError, ValueError):
        confidence = None

    warnings = data.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    image_path = fallback_image
    if existing and existing[0].image_path:
        image_path = existing[0].image_path

    return [ProductCandidate(
        name=name,
        price=price,
        description=((data.get("description") or "") or (existing[0].description if existing else ""))[:1000],
        sku=sku,
        stock=existing[0].stock if existing else 0,
        image_path=image_path,
        category=data.get("category"),
        subcategory=data.get("subcategory"),
        page_number=existing[0].page_number if existing else None,
        confidence=confidence,
        warnings=tuple(str(w) for w in warnings),
    )]


def _empty_candidate(image_path: str | None) -> ProductCandidate:
    return ProductCandidate(
        name="Producto sin nombre",
        price=Decimal("0"),
        image_path=image_path,
    )


def _tag(candidate: ProductCandidate, extra_warnings: tuple[str, ...]) -> ProductCandidate:
    seen = set(candidate.warnings)
    combined = candidate.warnings + tuple(w for w in extra_warnings if w not in seen)
    return replace(candidate, warnings=combined)
