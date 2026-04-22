from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from flask import has_request_context, request
from werkzeug.utils import secure_filename

from .extensions import db
from .models import AuditLog


def allowed_file(filename: str, allowed_extensions: Iterable[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


def save_upload(file_storage, target_folder: Path) -> str:
    target_folder.mkdir(parents=True, exist_ok=True)
    original_name = secure_filename(file_storage.filename or "file")
    suffix = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
    filename = f"{unique_name}.{suffix}" if suffix else unique_name
    destination = target_folder / filename
    file_storage.save(destination)
    return filename


def log_action(action: str, entity_type: str | None = None, entity_id: str | int | None = None, details: str | None = None,
               company_id: int | None = None, user_id: int | None = None) -> None:
    log = AuditLog(
        company_id=company_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
        ip_address=(request.headers.get("X-Forwarded-For", request.remote_addr) if has_request_context() else None),
    )
    db.session.add(log)
    db.session.commit()


def relative_product_image_path(filename: str) -> str:
    return f"uploads/products/{filename}"


def relative_pdf_path(filename: str) -> str:
    return f"uploads/pdfs/{filename}"
