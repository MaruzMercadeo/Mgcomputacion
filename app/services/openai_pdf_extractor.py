from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib import request as urlrequest

from .claude_pdf_extractor import (
    _SYSTEM_PROMPT,
    _build_candidates,
    _extract_json,
    _recover_truncated_products,
)
from .product_importer import ProductCandidate


API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_TIMEOUT = 180
MAX_TOKENS = 8192
MAX_PDF_BYTES = 30 * 1024 * 1024
PAGE_RENDER_SCALE = 2  # 2x zoom when rasterizing → ~150 DPI, decent for OCR


class OpenAIPDFUnavailable(RuntimeError):
    """Raised when the OpenAI PDF extractor cannot run."""


def extract_products_with_openai(
    pdf_path: str | Path,
    model: str,
    api_key: str,
    dst_folder: str | Path | None = None,
    filename_prefix: str = "job",
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[list[ProductCandidate], dict]:
    """Send each PDF page as a rasterized image to OpenAI Chat Completions.

    GPT-4o does not accept PDF documents natively (Anthropic's advantage),
    so we render each page as a PNG with PyMuPDF and send it as an image.
    Otherwise the schema and image-cropping strategy match the Claude path.
    """
    if not model or not api_key:
        raise OpenAIPDFUnavailable("model o api_key vacíos")

    path = Path(pdf_path)
    if not path.exists():
        raise OpenAIPDFUnavailable(f"PDF no encontrado: {path}")

    try:
        file_size = path.stat().st_size
    except Exception as exc:  # noqa: BLE001
        raise OpenAIPDFUnavailable(f"No se pudo leer el PDF: {exc}") from exc
    if file_size > MAX_PDF_BYTES:
        raise OpenAIPDFUnavailable(f"PDF demasiado grande ({file_size} bytes)")

    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise OpenAIPDFUnavailable(f"PyMuPDF no instalado: {exc}") from exc

    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise OpenAIPDFUnavailable(f"No se pudo abrir el PDF: {exc}") from exc

    total_pages = doc.page_count
    all_products: list[dict] = []
    input_total = 0
    output_total = 0
    truncated_pages = 0
    failed_pages: list[int] = []
    last_error = ""

    try:
        for page_num in range(1, total_pages + 1):
            try:
                page = doc[page_num - 1]
                pix = page.get_pixmap(matrix=fitz.Matrix(PAGE_RENDER_SCALE, PAGE_RENDER_SCALE))
                png_bytes = pix.tobytes("png")
                pix = None
                products, call_stats = _call_openai_for_image(
                    png_bytes, model, api_key, timeout
                )
            except Exception as exc:  # noqa: BLE001
                failed_pages.append(page_num)
                last_error = str(exc)[:200]
                continue

            for product in products:
                if isinstance(product, dict):
                    product["page"] = page_num
            all_products.extend(p for p in products if isinstance(p, dict))

            input_total += call_stats.get("input_tokens", 0)
            output_total += call_stats.get("output_tokens", 0)
            if call_stats.get("truncated"):
                truncated_pages += 1
    finally:
        doc.close()

    if total_pages > 0 and len(failed_pages) == total_pages:
        raise OpenAIPDFUnavailable(f"Todas las páginas fallaron. Último error: {last_error}")

    candidates = _build_candidates(all_products, path, dst_folder, filename_prefix)

    return candidates, {
        "input_tokens": input_total,
        "output_tokens": output_total,
        "detected": len(candidates),
        "raw_products": len(all_products),
        "pages_processed": total_pages,
        "pages_failed": len(failed_pages),
        "truncated_pages": truncated_pages,
        "truncated": truncated_pages > 0,
        "stop_reason": "ok" if truncated_pages == 0 else "partial_truncation",
    }


def _call_openai_for_image(
    png_bytes: bytes,
    model: str,
    api_key: str,
    timeout: int,
) -> tuple[list, dict]:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    body = json.dumps({
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extraé todos los productos de esta página siguiendo el esquema JSON indicado. Respondé SOLO con el JSON.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            },
        ],
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urlrequest.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")

    payload = json.loads(raw)

    text = ""
    finish_reason = ""
    for choice in payload.get("choices", []) or []:
        message = choice.get("message", {}) or {}
        content = message.get("content")
        if isinstance(content, str):
            text += content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text += part.get("text", "")
        finish_reason = choice.get("finish_reason", "")

    was_truncated = finish_reason == "length"

    try:
        data = _extract_json(text)
    except ValueError:
        recovered = _recover_truncated_products(text)
        data = {"products": recovered or []}

    products = data.get("products") or []
    if not isinstance(products, list):
        products = []

    usage = payload.get("usage", {}) or {}
    return products, {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
        "stop_reason": finish_reason,
        "truncated": was_truncated,
    }
