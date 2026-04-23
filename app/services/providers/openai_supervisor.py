from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib import request as urlrequest

from flask import current_app

from ..llm_supervisor import SupervisionRequest, SupervisionResult
from ..product_importer import ProductCandidate
from .anthropic_supervisor import _empty_candidate, _merge, _tag


API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_TIMEOUT = 30
MAX_TOKENS = 512


_SYSTEM_PROMPT = (
    "Eres un extractor de datos de productos. Recibes texto OCR y/o una imagen "
    "recortada del producto y debés devolver SIEMPRE un JSON válido con este "
    "esquema: "
    '{"name": string, "sku": string|null, "price": number|null, '
    '"description": string|null, "category": string|null, "subcategory": string|null, '
    '"confidence": number entre 0 y 1, "warnings": [string]}. '
    "No inventes SKU ni precio. No uses el SKU como nombre. "
    "Respondé SOLO con el JSON."
)


class OpenAISupervisor:
    name = "openai"

    def __init__(self, model: str, api_key: str, timeout: int = DEFAULT_TIMEOUT):
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def review(self, request: SupervisionRequest) -> SupervisionResult:
        existing = list(request.heuristic_candidates)

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
        content: list[dict] = [{"type": "text", "text": self._build_prompt(request)}]
        if request.image_path:
            image_block = _image_block_for_openai(request.image_path)
            if image_block:
                content.append(image_block)

        body = json.dumps({
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        req = urlrequest.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urlrequest.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")

        payload = json.loads(raw)

        text = ""
        for choice in payload.get("choices", []) or []:
            message = choice.get("message", {}) or {}
            content_value = message.get("content")
            if isinstance(content_value, str):
                text += content_value
            elif isinstance(content_value, list):
                for part in content_value:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text += part.get("text", "")

        return _extract_json(text)

    def _build_prompt(self, request: SupervisionRequest) -> str:
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

        return "\n\n".join(parts)


def _image_block_for_openai(relative_path: str) -> dict | None:
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

    b64 = base64.b64encode(raw).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64}"},
    }


def _extract_json(text: str) -> dict:
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("respuesta vacía")

    # Clean fenced blocks
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    stripped = stripped.strip()

    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON en respuesta")
    return json.loads(stripped[start:end + 1])
