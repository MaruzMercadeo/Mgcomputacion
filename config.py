import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

DEFAULT_DB_PATH = INSTANCE_DIR / "app.db"

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
    PRODUCT_UPLOAD_FOLDER = BASE_DIR / "app" / "static" / "uploads" / "products"
    PDF_UPLOAD_FOLDER = BASE_DIR / "app" / "static" / "uploads" / "pdfs"
    IMPORT_UPLOAD_FOLDER = BASE_DIR / "app" / "static" / "uploads" / "imports"
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    ALLOWED_PDF_EXTENSIONS = {"pdf"}
    ALLOWED_CSV_EXTENSIONS = {"csv"}
    ALLOWED_IMPORT_EXTENSIONS = ALLOWED_PDF_EXTENSIONS | ALLOWED_CSV_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS

    # OCR local (requires Tesseract binary installed on host)
    OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() in ("1", "true", "yes")
    OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "spa+eng")
    OCR_MIN_CHARS = int(os.getenv("OCR_MIN_CHARS", "20"))
    OCR_MAX_IMAGE_DIMENSION = int(os.getenv("OCR_MAX_IMAGE_DIMENSION", "2000"))

    # LLM supervisor — supports multiple saved presets.
    # Switch with LLM_SUPERVISOR_ACTIVE=1 | 2 | 3 | off (default: off).
    # Each preset lives in its own set of LLM_SUPERVISOR<N>_* vars.
    _active = (os.getenv("LLM_SUPERVISOR_ACTIVE", "") or "").strip().lower()
    _suffix = "" if _active in ("", "off", "none", "0") else _active

    LLM_SUPERVISOR_ENABLED = (
        _active not in ("off", "none", "0")
        and os.getenv(f"LLM_SUPERVISOR{_suffix}_ENABLED", "false").lower() in ("1", "true", "yes")
    )
    LLM_SUPERVISOR_PROVIDER = os.getenv(f"LLM_SUPERVISOR{_suffix}_PROVIDER", "")
    LLM_SUPERVISOR_MODEL = os.getenv(f"LLM_SUPERVISOR{_suffix}_MODEL", "")
    LLM_SUPERVISOR_API_KEY = os.getenv(f"LLM_SUPERVISOR{_suffix}_API_KEY", "")
