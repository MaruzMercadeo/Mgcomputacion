from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ..utils import relative_product_image_path
from .product_importer import ProductCandidate


def build_candidate_from_image(
    saved_filename: str,
    original_filename: str,
) -> ProductCandidate:
    """Wrap a stored image file as a draft product candidate.

    OCR/AI extraction is a future hook; for now we produce a placeholder
    name from the filename and zero price so the user can edit before commit.
    """
    stem = Path(original_filename).stem.replace("_", " ").replace("-", " ").strip()
    name = (stem or "Producto sin nombre")[:180]
    return ProductCandidate(
        name=name,
        price=Decimal("0"),
        description="",
        sku=None,
        stock=0,
        image_path=relative_product_image_path(saved_filename),
    )
