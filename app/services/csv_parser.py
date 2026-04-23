from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

from .product_importer import ProductCandidate


NAME_COLS = {"nombre", "name", "producto", "product", "titulo", "title"}
PRICE_COLS = {"precio", "price", "valor", "importe"}
DESC_COLS = {"descripcion", "description", "detalle", "detalles"}
SKU_COLS = {"sku", "codigo", "cod", "ref", "referencia"}
STOCK_COLS = {"stock", "cantidad", "qty", "existencia", "disponible"}
CATEGORY_COLS = {"categoria", "category"}
SUBCATEGORY_COLS = {"subcategoria", "subcategory", "sub-categoria"}
IMAGE_COLS = {"imagen", "image", "foto", "picture", "img"}


def parse_products_from_csv(csv_path: str | Path) -> list[ProductCandidate]:
    path = Path(csv_path)
    raw = path.read_bytes()
    text = _decode_bytes(raw)
    return parse_products_from_csv_text(text)


def parse_products_from_csv_text(text: str) -> list[ProductCandidate]:
    if not text.strip():
        return []

    dialect = _sniff_dialect(text)
    reader = csv.DictReader(StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return []

    mapping = _map_columns(reader.fieldnames)
    if "name" not in mapping or "price" not in mapping:
        return []

    candidates: list[ProductCandidate] = []
    seen: set[tuple[str, str | None, str]] = set()

    for row in reader:
        name = (row.get(mapping["name"]) or "").strip()
        if not name:
            continue

        price = _to_decimal(row.get(mapping["price"]))
        if price is None:
            continue

        sku = (row.get(mapping["sku"]) or "").strip() if "sku" in mapping else None
        sku = sku or None

        key = (name.lower(), sku.lower() if sku else None, str(price))
        if key in seen:
            continue
        seen.add(key)

        candidates.append(
            ProductCandidate(
                name=name[:180],
                price=price,
                description=(row.get(mapping["description"]) or "").strip()[:1000] if "description" in mapping else "",
                sku=sku[:80] if sku else None,
                stock=_to_int(row.get(mapping["stock"])) if "stock" in mapping else 0,
                image_path=(row.get(mapping["image"]) or "").strip() or None if "image" in mapping else None,
                category=(row.get(mapping["category"]) or "").strip() or None if "category" in mapping else None,
                subcategory=(row.get(mapping["subcategory"]) or "").strip() or None if "subcategory" in mapping else None,
            )
        )

    return candidates


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _sniff_dialect(text: str) -> csv.Dialect:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _map_columns(fieldnames) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw in fieldnames:
        if not raw:
            continue
        normalized = raw.strip().lower()
        if normalized in NAME_COLS and "name" not in mapping:
            mapping["name"] = raw
        elif normalized in PRICE_COLS and "price" not in mapping:
            mapping["price"] = raw
        elif normalized in DESC_COLS and "description" not in mapping:
            mapping["description"] = raw
        elif normalized in SKU_COLS and "sku" not in mapping:
            mapping["sku"] = raw
        elif normalized in STOCK_COLS and "stock" not in mapping:
            mapping["stock"] = raw
        elif normalized in CATEGORY_COLS and "category" not in mapping:
            mapping["category"] = raw
        elif normalized in SUBCATEGORY_COLS and "subcategory" not in mapping:
            mapping["subcategory"] = raw
        elif normalized in IMAGE_COLS and "image" not in mapping:
            mapping["image"] = raw
    return mapping


def _to_decimal(raw) -> Decimal | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    value = value.replace(" ", "").replace("$", "").replace("usd", "", 1).replace("USD", "", 1)
    if "," in value and "." in value:
        decimal_sep = "," if value.rfind(",") > value.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        value = value.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in value:
        parts = value.split(",")
        value = "".join(parts) if len(parts[-1]) == 3 else value.replace(",", ".")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed >= 0 else None


def _to_int(raw) -> int:
    if raw is None:
        return 0
    try:
        return int(str(raw).strip() or 0)
    except ValueError:
        return 0
