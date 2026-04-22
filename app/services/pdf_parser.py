from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_pdf_text(pdf_path: str | Path, max_chars: int = 5000) -> str:
    """
    Extracción simple para MVP.
    Más adelante puede reemplazarse por una canalización más avanzada
    con OCR, detección de tablas o parsing estructurado.
    """
    path = Path(pdf_path)
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text:
            parts.append(text.strip())
        joined = "\n\n".join(parts)
        if len(joined) >= max_chars:
            return joined[:max_chars]
    return "\n\n".join(parts)[:max_chars]
