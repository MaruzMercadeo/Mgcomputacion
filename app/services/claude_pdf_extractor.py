from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib import request as urlrequest

from ..utils import relative_product_image_path
from .product_importer import ProductCandidate


API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 180
MAX_TOKENS = 8192
MAX_PDF_BYTES = 30 * 1024 * 1024  # Anthropic accepts up to 32 MB


class ClaudePDFUnavailable(RuntimeError):
    """Raised when the Claude PDF extractor cannot run (no key, no model, bad PDF, HTTP error)."""


_SYSTEM_PROMPT = """Eres un extractor de productos desde catálogos PDF comerciales.

Tu tarea: identificar CADA producto real del catálogo y devolverlo como JSON.

Estructura típica de una tarjeta de producto:
- SKU arriba a la derecha (ej: RMG-4000, RMG-4011, RMG-6205)
- imagen del producto en el centro
- NOMBRE en mayúsculas en la franja de color (ej: "ANILLOS (MOTOR GASOLINA 18 HP)")
- precio abajo a la izquierda con formato "$ X.XX" o "$X.XX" (ej: "$ 0.90", "$ 4.62", "$ 121.80")
- leyenda "Min. Venta N Unidades" al lado del precio (IGNORAR esa parte)

Reglas estrictas:
- El PRECIO casi siempre está visible en cada tarjeta. Leelo de la etiqueta "$ X.XX" y devolvelo como NÚMERO JSON sin el símbolo $ ni el texto "Min. Venta". Ejemplos correctos: 0.90, 4.62, 121.80. Solo devolvé null si realmente no hay precio en la tarjeta.
- El NOMBRE es el texto descriptivo en mayúsculas (ej: "AISLANTE CARBURADOR (MOTOR GASOLINA 18 HP)"), NO el SKU. Jamás uses un código tipo "RMG-4000" como nombre.
- El SKU es el código alfanumérico con guión (ej: RMG-4000, RMG-6205). Devolvelo como string.
- NO cuentes como producto: títulos de sección ("MOTOR GASOLINA 18HP • 198F"), logos de marca (MAG, MAG Tools, Guerra Motor's), encabezados/pies de página, publicidades.
- Un producto requiere al menos nombre + (precio O SKU). Sin eso, omitilo.

Devolvé SIEMPRE un JSON válido con este esquema EXACTO, sin texto antes ni después, sin envolver en bloques de código:
{
  "products": [
    {
      "name": string,
      "sku": string | null,
      "price": number | null,
      "description": string | null,
      "category": string | null,
      "subcategory": string | null,
      "page": number,
      "bbox": [x0, y0, x1, y1] | null,
      "confidence": number entre 0 y 1
    }
  ]
}

Las coordenadas bbox son las del PDF en puntos (points, no pixels), delimitando la tarjeta entera del producto. Si no podés ubicarlas con precisión, poné null."""


def extract_products_with_claude(
    pdf_path: str | Path,
    model: str,
    api_key: str,
    dst_folder: str | Path | None = None,
    filename_prefix: str = "job",
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[list[ProductCandidate], dict]:
    """Send the PDF to Claude Messages API, one page at a time, and get products.

    Processing per page keeps each response under 8K output tokens so we never
    truncate, regardless of catalog size. The original PDF is used for image
    cropping at the end.

    Returns (candidates, stats). Raises ClaudePDFUnavailable on any hard
    failure so the caller can fall back to the heuristic pipeline.
    """
    if not model or not api_key:
        raise ClaudePDFUnavailable("model o api_key vacíos")

    path = Path(pdf_path)
    if not path.exists():
        raise ClaudePDFUnavailable(f"PDF no encontrado: {path}")

    try:
        file_size = path.stat().st_size
    except Exception as exc:  # noqa: BLE001
        raise ClaudePDFUnavailable(f"No se pudo leer el PDF: {exc}") from exc
    if file_size > MAX_PDF_BYTES:
        raise ClaudePDFUnavailable(f"PDF demasiado grande ({file_size} bytes)")

    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise ClaudePDFUnavailable(f"PyMuPDF no instalado: {exc}") from exc

    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ClaudePDFUnavailable(f"No se pudo abrir el PDF: {exc}") from exc

    total_pages = doc.page_count
    all_products: list[dict] = []
    input_total = 0
    output_total = 0
    truncated_pages = 0
    failed_pages: list[int] = []
    last_error: str = ""

    try:
        for page_num in range(1, total_pages + 1):
            try:
                page_bytes = _single_page_pdf_bytes(doc, page_num - 1)
                products, call_stats = _call_claude_for_pdf(
                    page_bytes, model, api_key, timeout
                )
            except Exception as exc:  # noqa: BLE001
                failed_pages.append(page_num)
                last_error = str(exc)[:200]
                continue

            for product in products:
                if isinstance(product, dict):
                    product["page"] = page_num  # override: each sub-PDF looks like page 1 to Claude
            all_products.extend(p for p in products if isinstance(p, dict))

            input_total += call_stats.get("input_tokens", 0)
            output_total += call_stats.get("output_tokens", 0)
            if call_stats.get("truncated"):
                truncated_pages += 1
    finally:
        doc.close()

    # If every page failed, surface the error so the caller falls back.
    if total_pages > 0 and len(failed_pages) == total_pages:
        raise ClaudePDFUnavailable(f"Todas las páginas fallaron. Último error: {last_error}")

    candidates = _build_candidates(all_products, path, dst_folder, filename_prefix)

    stats = {
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
    return candidates, stats


def _single_page_pdf_bytes(doc, page_index: int) -> bytes:
    """Serialize a single page of an open fitz doc as a standalone PDF byte string."""
    import fitz  # type: ignore

    out = fitz.open()
    try:
        out.insert_pdf(doc, from_page=page_index, to_page=page_index)
        return out.tobytes()
    finally:
        out.close()


def _call_claude_for_pdf(
    pdf_bytes: bytes,
    model: str,
    api_key: str,
    timeout: int,
) -> tuple[list, dict]:
    """POST a PDF (whole or single page) to Claude and return raw product dicts + stats."""
    body = json.dumps({
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": _SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(pdf_bytes).decode("ascii"),
                    },
                },
                {
                    "type": "text",
                    "text": "Extraé todos los productos de esta página siguiendo el esquema JSON indicado. Respondé SOLO con el JSON.",
                },
            ],
        }],
    }).encode("utf-8")

    req = urlrequest.Request(
        API_URL,
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )

    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")

    payload = json.loads(raw)
    text = ""
    for block in payload.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

    stop_reason = payload.get("stop_reason", "")
    was_truncated = stop_reason == "max_tokens"

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
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "stop_reason": stop_reason,
        "truncated": was_truncated,
    }


def _recover_truncated_products(text: str) -> list | None:
    """Salvage as many complete product objects as possible from a truncated JSON.

    When Anthropic cuts the output at max_tokens, the JSON usually breaks in
    the middle of the last product. We parse incrementally, one `{...}` at a
    time, inside the `products` array, and return the ones that were complete.
    """
    if not text:
        return None

    start = text.find("[")
    if start == -1:
        return None

    # Scan forward tracking brace depth; keep every object that closes cleanly.
    products: list = []
    depth = 0
    obj_start = -1
    in_string = False
    escape = False

    for i in range(start + 1, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start != -1:
                candidate_text = text[obj_start:i + 1]
                try:
                    products.append(json.loads(candidate_text))
                except json.JSONDecodeError:
                    # Skip — likely malformed due to truncation nearby
                    pass
                obj_start = -1
            elif depth < 0:
                # Out of the products array
                break

    return products or None


def _build_candidates(
    products: list,
    pdf_path: Path,
    dst_folder: str | Path | None,
    filename_prefix: str,
) -> list[ProductCandidate]:
    out: list[ProductCandidate] = []
    for idx, product in enumerate(products, start=1):
        if not isinstance(product, dict):
            continue

        name = (product.get("name") or "").strip()
        if len(name) < 2:
            continue

        price = _to_decimal(product.get("price"))
        sku = product.get("sku")
        if sku is not None:
            sku = str(sku).strip() or None

        page = product.get("page")
        try:
            page_num = int(page) if page is not None else None
        except (TypeError, ValueError):
            page_num = None

        bbox = _parse_bbox(product.get("bbox"))
        image_path = None
        if dst_folder and bbox and page_num:
            image_path = _crop_and_save(
                pdf_path, page_num, bbox, Path(dst_folder), f"{filename_prefix}_p{page_num}_i{idx}"
            )

        confidence = product.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None

        warnings: list[str] = []
        if price is None:
            warnings.append("price_missing")
        if not sku:
            warnings.append("sku_missing")

        out.append(ProductCandidate(
            name=name[:180],
            price=price if price is not None else Decimal("0"),
            description=(product.get("description") or "")[:1000],
            sku=sku[:80] if sku else None,
            stock=0,
            image_path=image_path,
            category=product.get("category") or None,
            subcategory=product.get("subcategory") or None,
            page_number=page_num,
            confidence=confidence,
            warnings=tuple(warnings),
        ))
    return out


def _to_decimal(raw) -> Decimal | None:
    """Accept numbers or strings that may carry currency symbols or thousands separators."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):  # bool is subclass of int — guard explicitly
        return None
    if isinstance(raw, (int, float)):
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            return None
        return value if value >= 0 else None

    cleaned = str(raw).strip()
    if not cleaned:
        return None

    # Strip currency symbols / common noise
    for token in ("$", "€", "USD", "usd", "Bs", "bs", "S/.", "Gs", "COP", "MXN", "ARS"):
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.replace(" ", "").replace(" ", "")
    if not cleaned:
        return None

    # Normalize decimal/thousands separators
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            # European: "1.234,56" -> "1234.56"
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US with thousands: "1,234.56" -> "1234.56"
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Heuristic: 3-digit group after comma is thousands, else decimal
        parts = cleaned.split(",")
        if len(parts[-1]) == 3 and all(p.isdigit() for p in parts):
            cleaned = "".join(parts)
        else:
            cleaned = cleaned.replace(",", ".")

    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def _parse_bbox(raw) -> tuple[float, float, float, float] | None:
    if not raw or not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    except (TypeError, ValueError):
        return None


def _crop_and_save(
    pdf_path: Path,
    page_num: int,
    bbox: tuple[float, float, float, float],
    dst: Path,
    filename_stem: str,
) -> str | None:
    try:
        import fitz  # type: ignore
    except ImportError:
        return None

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:  # noqa: BLE001
        return None

    try:
        if page_num < 1 or page_num > doc.page_count:
            return None
        page = doc[page_num - 1]
        x0, y0, x1, y1 = bbox
        # Clamp to page
        rect = fitz.Rect(x0, y0, x1, y1) & page.rect
        if rect.is_empty:
            return None
        try:
            pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(2, 2))
        except Exception:  # noqa: BLE001
            return None

        dst.mkdir(parents=True, exist_ok=True)
        filename = f"{filename_stem}.png"
        destination = dst / filename
        try:
            pix.save(destination.as_posix())
        except Exception:  # noqa: BLE001
            return None
        return relative_product_image_path(filename)
    finally:
        doc.close()


def _extract_json(text: str) -> dict:
    # Strip code fences
    stripped = text.strip()
    if stripped.startswith("```"):
        # Remove opening fence and optional language tag
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    stripped = stripped.strip()

    # Direct parse
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Fallback: grab between first { and last }
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(stripped[start:end + 1])
