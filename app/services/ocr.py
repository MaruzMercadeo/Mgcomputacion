from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class OCRUnavailable(RuntimeError):
    """Raised when Pillow or Tesseract are not installed/usable."""


@dataclass(frozen=True)
class OCRResult:
    text: str
    chars: int
    languages: str

    @property
    def has_meaningful_text(self) -> bool:
        return self.chars >= 20 and any(c.isalpha() for c in self.text)


def extract_text_from_image(
    image_path: str | Path,
    languages: str = "spa+eng",
    max_dimension: int = 2000,
) -> OCRResult:
    """Run local OCR over an image, falling back gracefully if deps are missing.

    The caller decides what to do with an empty/short result; this function
    never crashes the import flow — it raises OCRUnavailable only if the
    runtime stack itself is missing.
    """
    try:
        from PIL import Image, ImageOps  # type: ignore
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OCRUnavailable(f"Falta dependencia: {exc.name}") from exc

    path = Path(image_path)
    if not path.exists():
        raise OCRUnavailable(f"Archivo no encontrado: {path}")

    try:
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw)
            image = image.convert("L")  # grayscale; cheap noise reduction
            image.thumbnail((max_dimension, max_dimension))
            text = _run_tesseract(pytesseract, image, languages)
    except OCRUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — corrupt image, missing binary, etc.
        raise OCRUnavailable(str(exc)) from exc

    cleaned = (text or "").strip()
    return OCRResult(text=cleaned, chars=len(cleaned), languages=languages)


def _run_tesseract(pytesseract, image, languages: str) -> str:
    try:
        return pytesseract.image_to_string(image, lang=languages)
    except pytesseract.TesseractNotFoundError as exc:  # type: ignore[attr-defined]
        raise OCRUnavailable("Tesseract no está instalado en el host") from exc
    except Exception:
        # Try again with English-only as fallback when language packs are missing
        if languages != "eng":
            return pytesseract.image_to_string(image, lang="eng")
        raise
