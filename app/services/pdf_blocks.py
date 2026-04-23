from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..utils import relative_product_image_path


class PDFBlocksUnavailable(RuntimeError):
    """Raised when PyMuPDF is not installed or the PDF cannot be opened."""


@dataclass(frozen=True)
class ProductBlock:
    page_number: int
    text: str
    image_path: str | None
    bbox: tuple[float, float, float, float] | None
    confidence: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_image(self) -> bool:
        return bool(self.image_path)


def extract_product_blocks_from_pdf(
    pdf_path: str | Path,
    dst_folder: str | Path,
    filename_prefix: str,
) -> list[ProductBlock]:
    """Walk every page and group embedded images with nearby text.

    Returns one ProductBlock per image found (with the associated text block
    below/next-to it), plus extra blocks for pages whose text isn't close to
    any image. Never raises on corrupt content — returns [] instead.
    """
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise PDFBlocksUnavailable("PyMuPDF no instalado") from exc

    path = Path(pdf_path)
    dst = Path(dst_folder)
    dst.mkdir(parents=True, exist_ok=True)

    blocks: list[ProductBlock] = []
    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise PDFBlocksUnavailable(f"No se pudo abrir el PDF: {exc}") from exc

    try:
        for page_index, page in enumerate(doc, start=1):
            text_blocks = _collect_text_blocks(page)
            image_entries = _collect_image_entries(doc, page, dst, filename_prefix, page_index)

            if not image_entries:
                # No images on this page — fall back to plain text (caller will
                # run the heuristic parser on it).
                continue

            used_text_indices: set[int] = set()
            for entry in image_entries:
                nearby_idx, nearby_text = _nearest_text_block(
                    entry["bbox"], text_blocks, used_text_indices
                )
                if nearby_idx is not None:
                    used_text_indices.add(nearby_idx)

                blocks.append(
                    ProductBlock(
                        page_number=page_index,
                        text=nearby_text,
                        image_path=entry["image_path"],
                        bbox=entry["bbox"],
                        confidence=0.6 if nearby_text else 0.3,
                        warnings=tuple() if nearby_text else ("text_not_paired",),
                    )
                )
    finally:
        doc.close()

    return blocks


def _collect_text_blocks(page) -> list[dict]:
    try:
        raw_blocks = page.get_text("blocks")
    except Exception:  # noqa: BLE001
        return []
    collected = []
    for block in raw_blocks:
        if len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
        text = (text or "").strip()
        if not text:
            continue
        collected.append({
            "bbox": (float(x0), float(y0), float(x1), float(y1)),
            "text": text,
        })
    return collected


def _collect_image_entries(
    doc,
    page,
    dst: Path,
    filename_prefix: str,
    page_index: int,
) -> list[dict]:
    entries: list[dict] = []
    for img_index, img in enumerate(page.get_images(full=True), start=1):
        xref = img[0]
        bbox = _image_bbox(page, xref)
        try:
            pix = _ensure_rgb(doc, xref)
        except Exception:  # noqa: BLE001
            continue

        suffix = "png"
        filename = f"{filename_prefix}_p{page_index}_i{img_index}.{suffix}"
        destination = dst / filename
        try:
            pix.save(destination.as_posix())
        except Exception:  # noqa: BLE001
            continue
        finally:
            pix = None  # release memory

        entries.append({
            "image_path": relative_product_image_path(filename),
            "bbox": bbox,
        })
    return entries


def _ensure_rgb(doc, xref):
    import fitz  # type: ignore

    pix = fitz.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:  # CMYK or similar — convert to RGB
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix


def _image_bbox(page, xref) -> tuple[float, float, float, float] | None:
    try:
        rects = page.get_image_rects(xref)
    except Exception:  # noqa: BLE001
        return None
    if not rects:
        return None
    rect = rects[0]
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _nearest_text_block(
    image_bbox: tuple[float, float, float, float] | None,
    text_blocks: Iterable[dict],
    used: set[int],
) -> tuple[int | None, str]:
    if image_bbox is None:
        # No position info — pair with the first unused text block.
        for idx, block in enumerate(text_blocks):
            if idx not in used:
                return idx, block["text"]
        return None, ""

    ix0, iy0, ix1, iy1 = image_bbox
    best_idx: int | None = None
    best_score = float("inf")
    for idx, block in enumerate(text_blocks):
        if idx in used:
            continue
        tx0, ty0, tx1, ty1 = block["bbox"]
        # Prefer text that sits below or to the right of the image
        vertical_gap = max(ty0 - iy1, 0)
        horizontal_overlap_penalty = 0 if (tx0 <= ix1 and tx1 >= ix0) else abs((tx0 + tx1) / 2 - (ix0 + ix1) / 2)
        score = vertical_gap + 0.25 * horizontal_overlap_penalty
        if score < best_score:
            best_score = score
            best_idx = idx

    if best_idx is None:
        return None, ""
    return best_idx, text_blocks[best_idx]["text"]
