from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import current_app, g, jsonify, request

from ...decorators import api_key_required
from ...extensions import db
from ...models import AgentSetting, Category, ImportItem, ImportJob, PdfUpload, Product
from ...services.csv_parser import parse_products_from_csv
from ...services.image_importer import build_candidates_from_image
from ...services.pdf_parser import extract_pdf_text
from ...services.product_importer import (
    commit_drafts,
    import_products_from_text,
    parse_products_from_text,
    stage_candidates_as_drafts,
)
from ...utils import allowed_file, log_action, relative_pdf_path, relative_product_image_path, save_upload
from . import bp


def _company():
    return g.api_company


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "mgcomputacion-api"})


@bp.get("/company")
@api_key_required
def get_company():
    company = _company()
    return jsonify({
        "id": company.id,
        "company_name": company.company_name,
        "address": company.address,
        "phone": company.phone,
        "company_email": company.company_email,
        "description": company.description,
        "website": company.website,
    })


@bp.put("/company")
@api_key_required
def update_company():
    company = _company()
    data = request.get_json(force=True, silent=True) or {}

    company.company_name = data.get("company_name", company.company_name)
    company.address = data.get("address", company.address)
    company.phone = data.get("phone", company.phone)
    company.company_email = data.get("company_email", company.company_email)
    company.description = data.get("description", company.description)
    company.website = data.get("website", company.website)

    db.session.commit()
    log_action("api_update_company", entity_type="company", entity_id=company.id, company_id=company.id)
    return jsonify({"message": "Empresa actualizada"})


@bp.get("/agent-settings")
@api_key_required
def get_agent_settings():
    settings = _company().agent_settings
    if not settings:
        return jsonify({"error": "No hay configuración del agente"}), 404
    return jsonify(settings.to_dict())


@bp.put("/agent-settings")
@api_key_required
def update_agent_settings():
    company = _company()
    data = request.get_json(force=True, silent=True) or {}
    settings = company.agent_settings or AgentSetting(company_id=company.id)

    settings.agent_name = data.get("agent_name", settings.agent_name)
    settings.tone = data.get("tone", settings.tone)
    settings.system_instructions = data.get("system_instructions", settings.system_instructions)
    settings.sales_behavior = data.get("sales_behavior", settings.sales_behavior)
    settings.support_rules = data.get("support_rules", settings.support_rules)
    settings.business_context = data.get("business_context", settings.business_context)
    settings.response_style = data.get("response_style", settings.response_style)

    if not settings.id:
        db.session.add(settings)
    db.session.commit()
    log_action("api_update_agent_settings", entity_type="agent_settings", entity_id=settings.id, company_id=company.id)
    return jsonify({"message": "Agent settings actualizados"})


@bp.get("/categories")
@api_key_required
def list_categories():
    company = _company()
    categories = Category.query.filter_by(company_id=company.id).order_by(Category.name.asc()).all()
    return jsonify([
        {
            "id": c.id,
            "name": c.name,
            "parent_id": c.parent_id,
            "is_active": c.is_active,
        }
        for c in categories
    ])


@bp.post("/categories")
@api_key_required
def create_category():
    company = _company()
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    parent_id = data.get("parent_id")

    if not name:
        return jsonify({"error": "name es obligatorio"}), 400

    category = Category(company_id=company.id, name=name, parent_id=parent_id)
    db.session.add(category)
    db.session.commit()
    log_action("api_create_category", entity_type="category", entity_id=category.id, company_id=company.id)
    return jsonify({"message": "Categoría creada", "id": category.id}), 201


@bp.get("/products")
@api_key_required
def list_products():
    company = _company()
    products = Product.query.filter_by(company_id=company.id).order_by(Product.created_at.desc()).all()
    return jsonify([product.to_dict() for product in products])


@bp.get("/products/<int:product_id>")
@api_key_required
def get_product(product_id):
    company = _company()
    product = Product.query.get_or_404(product_id)
    if product.company_id != company.id:
        return jsonify({"error": "No autorizado"}), 403
    return jsonify(product.to_dict())


def _update_product_from_json(product, data, company_id: int):
    name = (data.get("name") or product.name or "").strip()
    if not name:
        raise ValueError("name es obligatorio")

    product.company_id = company_id
    product.name = name
    product.description = data.get("description", product.description)
    product.sku = data.get("sku", product.sku)
    product.stock = int(data.get("stock", product.stock or 0))
    product.is_active = bool(data.get("is_active", product.is_active))
    product.category_id = data.get("category_id", product.category_id)
    product.subcategory_id = data.get("subcategory_id", product.subcategory_id)

    price_raw = data.get("price", product.price or 0)
    try:
        product.price = Decimal(str(price_raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("price debe ser numérico") from exc

    return product


@bp.post("/products")
@api_key_required
def create_product():
    company = _company()
    data = request.get_json(force=True, silent=True) or {}
    product = Product()
    try:
        _update_product_from_json(product, data, company.id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    db.session.add(product)
    db.session.commit()
    log_action("api_create_product", entity_type="product", entity_id=product.id, company_id=company.id)
    return jsonify({"message": "Producto creado", "product": product.to_dict()}), 201


@bp.put("/products/<int:product_id>")
@api_key_required
def update_product(product_id):
    company = _company()
    data = request.get_json(force=True, silent=True) or {}
    product = Product.query.get_or_404(product_id)
    if product.company_id != company.id:
        return jsonify({"error": "No autorizado"}), 403

    try:
        _update_product_from_json(product, data, company.id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    db.session.commit()
    log_action("api_update_product", entity_type="product", entity_id=product.id, company_id=company.id)
    return jsonify({"message": "Producto actualizado", "product": product.to_dict()})


@bp.delete("/products/<int:product_id>")
@api_key_required
def delete_product(product_id):
    company = _company()
    product = Product.query.get_or_404(product_id)
    if product.company_id != company.id:
        return jsonify({"error": "No autorizado"}), 403

    db.session.delete(product)
    db.session.commit()
    log_action("api_delete_product", entity_type="product", entity_id=product.id, company_id=company.id)
    return jsonify({"message": "Producto eliminado"})


@bp.post("/pdf/upload")
@api_key_required
def upload_pdf():
    company = _company()
    pdf = request.files.get("pdf")
    if not pdf or not pdf.filename:
        return jsonify({"error": "Debes adjuntar un PDF en el campo 'pdf'"}), 400

    if not allowed_file(pdf.filename, current_app.config["ALLOWED_PDF_EXTENSIONS"]):
        return jsonify({"error": "Formato no permitido"}), 400

    filename = save_upload(pdf, Path(current_app.config["PDF_UPLOAD_FOLDER"]))
    relative = relative_pdf_path(filename)
    full_path = Path(current_app.root_path) / "static" / relative

    extracted = ""
    status = "processed"
    import_result = {"created_count": 0, "detected_count": 0, "skipped_count": 0}
    try:
        extracted = extract_pdf_text(full_path)
        import_result = import_products_from_text(company.id, extracted)
        if import_result["created_count"] > 0:
            status = "imported"
    except Exception:
        db.session.rollback()
        status = "failed"
        extracted = "No se pudo procesar el PDF."

    upload = PdfUpload(
        company_id=company.id,
        original_filename=pdf.filename,
        stored_path=relative,
        status=status,
        extracted_preview=extracted,
        processed_at=datetime.utcnow() if status in {"processed", "imported"} else None,
        imported_items_count=import_result["created_count"],
    )
    db.session.add(upload)
    db.session.commit()
    log_action("api_upload_pdf", entity_type="pdf_upload", entity_id=upload.id, company_id=company.id)

    return jsonify({
        "message": "PDF cargado",
        "pdf": upload.to_dict(),
        "import_result": import_result,
    }), 201


def _detect_source(filename: str) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in current_app.config["ALLOWED_PDF_EXTENSIONS"]:
        return "pdf"
    if ext in current_app.config["ALLOWED_CSV_EXTENSIONS"]:
        return "csv"
    if ext in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        return "image"
    return None


def _serialize_items(items):
    serialized = []
    for item in items:
        data = item.to_dict()
        try:
            data["payload"] = json.loads(data["payload"])
        except (TypeError, json.JSONDecodeError):
            pass
        serialized.append(data)
    return serialized


@bp.post("/imports/upload")
@api_key_required
def upload_import():
    company = _company()
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Debes adjuntar un archivo en el campo 'file'"}), 400

    if not allowed_file(upload.filename, current_app.config["ALLOWED_IMPORT_EXTENSIONS"]):
        return jsonify({"error": "Formato no permitido"}), 400

    source = _detect_source(upload.filename)
    if not source:
        return jsonify({"error": "Formato no permitido"}), 400

    if source == "image":
        target_folder = Path(current_app.config["PRODUCT_UPLOAD_FOLDER"])
    elif source == "pdf":
        target_folder = Path(current_app.config["PDF_UPLOAD_FOLDER"])
    else:
        target_folder = Path(current_app.config["IMPORT_UPLOAD_FOLDER"])

    stored_filename = save_upload(upload, target_folder)
    stored_path = str((target_folder / stored_filename).relative_to(Path(current_app.root_path)))
    full_path = target_folder / stored_filename

    mode = (request.form.get("mode") or "").strip().lower() or None

    job = ImportJob(
        company_id=company.id,
        source=source,
        status="processing",
        original_filename=upload.filename,
        stored_path=stored_path,
    )
    db.session.add(job)
    db.session.flush()

    summary: dict = {}
    try:
        if source == "pdf":
            text = extract_pdf_text(full_path)
            candidates = parse_products_from_text(text)
        elif source == "csv":
            candidates = parse_products_from_csv(full_path)
        else:
            outcome = build_candidates_from_image(stored_filename, upload.filename, full_path, mode=mode)
            candidates = outcome.candidates
            summary.update({
                "ocr_chars": outcome.ocr_chars,
                "supervisor": outcome.supervisor,
                "used_supervisor": outcome.used_supervisor,
                "fallback_reason": outcome.fallback_reason,
            })

        items = stage_candidates_as_drafts(job, candidates)
        job.status = "ready"
        summary["detected"] = len(items)
        if mode:
            summary["mode"] = mode
        job.summary = json.dumps(summary)
        db.session.commit()
    except Exception as error:  # noqa: BLE001
        db.session.rollback()
        job.status = "failed"
        job.summary = json.dumps({"error": str(error)[:240]})
        db.session.add(job)
        db.session.commit()
        log_action("api_import_upload_failed", entity_type="import_job", entity_id=job.id, company_id=company.id)
        return jsonify({"error": "No se pudo procesar el archivo", "import_job": job.to_dict()}), 422

    log_action("api_import_upload", entity_type="import_job", entity_id=job.id, company_id=company.id)
    return jsonify({
        "message": "Archivo importado",
        "import_job": job.to_dict(),
        "items": _serialize_items(job.items.all()),
    }), 201


@bp.get("/imports/<int:job_id>")
@api_key_required
def get_import(job_id):
    company = _company()
    job = ImportJob.query.get_or_404(job_id)
    if job.company_id != company.id:
        return jsonify({"error": "No autorizado"}), 403
    return jsonify({
        "import_job": job.to_dict(),
        "items": _serialize_items(job.items.order_by(ImportItem.id.asc()).all()),
    })


@bp.post("/imports/<int:job_id>/commit")
@api_key_required
def commit_import(job_id):
    company = _company()
    job = ImportJob.query.get_or_404(job_id)
    if job.company_id != company.id:
        return jsonify({"error": "No autorizado"}), 403
    if job.status == "failed":
        return jsonify({"error": "El job está en estado failed"}), 409

    data = request.get_json(force=True, silent=True) or {}
    item_ids = data.get("item_ids")
    if item_ids is not None and not isinstance(item_ids, list):
        return jsonify({"error": "item_ids debe ser una lista"}), 400

    try:
        result = commit_drafts(job, item_ids=item_ids)
        remaining = job.items.filter_by(status="draft").count()
        job.status = "committed" if remaining == 0 else "ready"
        db.session.commit()
    except Exception as error:  # noqa: BLE001
        db.session.rollback()
        return jsonify({"error": f"Commit falló: {error}"}), 500

    log_action("api_import_commit", entity_type="import_job", entity_id=job.id, company_id=company.id,
               details=json.dumps(result))
    return jsonify({
        "message": "Commit procesado",
        "import_job": job.to_dict(),
        **result,
    })
