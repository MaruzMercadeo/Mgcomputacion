from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import func

from ..extensions import db
from ..models import Category, ImportItem, ImportJob, Product


PRICE_RE = re.compile(
    r"(?i)(?:precio|price|usd|us\$|\$|bs\.?|bs)\s*[:\-]?\s*"
    r"([0-9][0-9.,]*)"
)
TRAILING_PRICE_RE = re.compile(
    r"(?<!\w)([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})|[0-9]+[.,][0-9]{2})(?!\w)\s*$"
)
SKU_RE = re.compile(r"(?i)\b(?:sku|codigo|cod|ref|referencia)\s*[:#\-]?\s*([A-Za-z0-9._/-]+)")
STOCK_RE = re.compile(r"(?i)\b(?:stock|cantidad|qty|existencia|disponible)\s*[:#\-]?\s*(\d+)")
HEADER_RE = re.compile(r"(?i)^(producto|nombre|descripcion|precio|stock|sku|codigo|catalogo)\b")


@dataclass(frozen=True)
class ProductCandidate:
    name: str
    price: Decimal
    description: str = ""
    sku: str | None = None
    stock: int = 0
    image_path: str | None = None
    category: str | None = None
    subcategory: str | None = None


def parse_products_from_text(text: str) -> list[ProductCandidate]:
    """Detect product rows from plain text extracted from a PDF catalog."""
    candidates: list[ProductCandidate] = []
    seen_keys: set[tuple[str, str | None, str]] = set()

    for raw_line in text.splitlines():
        line = _normalize_line(raw_line)
        if not _looks_like_product_line(line):
            continue

        candidate = _parse_product_line(line)
        if not candidate:
            continue

        key = (candidate.name.lower(), candidate.sku.lower() if candidate.sku else None, str(candidate.price))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(candidate)

    return candidates


def import_products_from_text(company_id: int, text: str) -> dict[str, Any]:
    """
    Create Product records from extracted PDF text.

    The function adds products to the active SQLAlchemy session but leaves the
    commit to the caller so PDF upload and product import stay atomic.
    """
    candidates = parse_products_from_text(text)
    result: dict[str, Any] = {
        "detected_count": len(candidates),
        "created_count": 0,
        "skipped_count": 0,
        "created_products": [],
        "skipped_products": [],
    }

    for candidate in candidates:
        exists_reason = _duplicate_reason(company_id, candidate)
        if exists_reason:
            result["skipped_count"] += 1
            result["skipped_products"].append({
                "name": candidate.name,
                "sku": candidate.sku,
                "reason": exists_reason,
            })
            continue

        product = Product(
            company_id=company_id,
            name=candidate.name,
            description=candidate.description,
            sku=candidate.sku,
            price=candidate.price,
            stock=candidate.stock,
            is_active=True,
        )
        db.session.add(product)
        result["created_count"] += 1
        result["created_products"].append({
            "name": candidate.name,
            "sku": candidate.sku,
            "price": float(candidate.price),
            "stock": candidate.stock,
        })

    return result


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("\t", " ")).strip(" -|")


def _looks_like_product_line(line: str) -> bool:
    if len(line) < 5:
        return False
    if HEADER_RE.match(line) and not (PRICE_RE.search(line) or TRAILING_PRICE_RE.search(line)):
        return False
    return bool(PRICE_RE.search(line) or TRAILING_PRICE_RE.search(line))


def _parse_product_line(line: str) -> ProductCandidate | None:
    price_match = PRICE_RE.search(line) or TRAILING_PRICE_RE.search(line)
    if not price_match:
        return None

    price = _parse_decimal(price_match.group(1))
    if price is None:
        return None

    sku_match = SKU_RE.search(line)
    stock_match = STOCK_RE.search(line)
    sku = sku_match.group(1).strip() if sku_match else None
    stock = int(stock_match.group(1)) if stock_match else 0

    name = _clean_product_name(line, price_match, sku_match, stock_match)
    if len(name) < 3:
        return None

    return ProductCandidate(
        name=name[:180],
        description=line[:1000],
        sku=sku[:80] if sku else None,
        price=price,
        stock=stock,
    )


def _clean_product_name(line: str, price_match, sku_match, stock_match) -> str:
    cleaned = line
    for match in (price_match, sku_match, stock_match):
        if match:
            cleaned = cleaned.replace(match.group(0), " ")

    cleaned = re.sub(r"(?i)\b(producto|nombre|descripcion|precio|stock|sku|codigo|cod|ref|referencia)\b", " ", cleaned)
    cleaned = re.sub(r"[\|;,:#]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned


def _parse_decimal(raw: str) -> Decimal | None:
    value = raw.strip()
    if "," in value and "." in value:
        decimal_separator = "," if value.rfind(",") > value.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        value = value.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in value:
        parts = value.split(",")
        value = "".join(parts) if len(parts[-1]) == 3 else value.replace(".", "").replace(",", ".")
    elif "." in value:
        parts = value.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            value = "".join(parts)
    else:
        value = value.replace(",", "")

    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None

    return parsed if parsed >= 0 else None


def _duplicate_reason(company_id: int, candidate: ProductCandidate) -> str | None:
    if candidate.sku:
        sku_exists = Product.query.filter_by(company_id=company_id, sku=candidate.sku).first()
        if sku_exists:
            return "sku duplicado"

    name_exists = Product.query.filter(
        Product.company_id == company_id,
        func.lower(Product.name) == candidate.name.lower(),
        Product.price == candidate.price,
    ).first()
    if name_exists:
        return "nombre y precio duplicados"

    return None


def _candidate_payload(candidate: ProductCandidate) -> str:
    data = asdict(candidate)
    data["price"] = str(candidate.price)
    return json.dumps(data, ensure_ascii=False)


def stage_candidates_as_drafts(job: ImportJob, candidates: Iterable[ProductCandidate]) -> list[ImportItem]:
    """Persist candidates as draft ImportItem rows tied to the job.

    Caller is responsible for db.session.commit().
    """
    items: list[ImportItem] = []
    for candidate in candidates:
        item = ImportItem(
            job_id=job.id,
            status="draft",
            payload=_candidate_payload(candidate),
        )
        db.session.add(item)
        items.append(item)
    return items


def _resolve_category_id(company_id: int, name: str | None) -> int | None:
    if not name:
        return None
    normalized = name.strip()
    if not normalized:
        return None
    existing = Category.query.filter(
        Category.company_id == company_id,
        func.lower(Category.name) == normalized.lower(),
    ).first()
    if existing:
        return existing.id
    category = Category(company_id=company_id, name=normalized[:120], is_active=True)
    db.session.add(category)
    db.session.flush()
    return category.id


def commit_drafts(job: ImportJob, item_ids: list[int] | None = None) -> dict[str, Any]:
    """Convert draft ImportItems into Products.

    item_ids: optional subset to commit. If None, commits all drafts.
    Caller is responsible for db.session.commit().
    """
    query = ImportItem.query.filter_by(job_id=job.id, status="draft")
    if item_ids:
        query = query.filter(ImportItem.id.in_(item_ids))
    drafts = query.all()

    committed = 0
    skipped = 0
    product_ids: list[int] = []

    for item in drafts:
        try:
            data = json.loads(item.payload)
        except json.JSONDecodeError:
            item.status = "skipped"
            item.reason = "payload inválido"
            skipped += 1
            continue

        try:
            price = Decimal(str(data.get("price", "0")))
        except InvalidOperation:
            item.status = "skipped"
            item.reason = "price inválido"
            skipped += 1
            continue

        candidate = ProductCandidate(
            name=(data.get("name") or "").strip(),
            price=price,
            description=data.get("description") or "",
            sku=data.get("sku"),
            stock=int(data.get("stock") or 0),
            image_path=data.get("image_path"),
            category=data.get("category"),
            subcategory=data.get("subcategory"),
        )

        if not candidate.name:
            item.status = "skipped"
            item.reason = "nombre vacío"
            skipped += 1
            continue

        reason = _duplicate_reason(job.company_id, candidate)
        if reason:
            item.status = "skipped"
            item.reason = reason
            skipped += 1
            continue

        product = Product(
            company_id=job.company_id,
            name=candidate.name,
            description=candidate.description,
            sku=candidate.sku,
            price=candidate.price,
            stock=candidate.stock,
            image_path=candidate.image_path,
            category_id=_resolve_category_id(job.company_id, candidate.category),
            subcategory_id=_resolve_category_id(job.company_id, candidate.subcategory),
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()

        item.status = "committed"
        item.product_id = product.id
        item.reason = None
        committed += 1
        product_ids.append(product.id)

    return {
        "committed": committed,
        "skipped": skipped,
        "products": product_ids,
    }
