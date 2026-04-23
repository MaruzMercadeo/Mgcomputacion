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
