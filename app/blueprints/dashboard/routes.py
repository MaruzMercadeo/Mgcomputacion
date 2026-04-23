from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ...decorators import approved_required
from ...extensions import db
from ...models import AgentSetting, ApiKey, Category, ImportItem, ImportJob, PdfUpload, Product
from ...services.csv_parser import parse_products_from_csv
from ...services.image_importer import build_candidates_from_image
from ...services.pdf_blocks import PDFBlocksUnavailable, extract_product_blocks_from_pdf
from ...services.pdf_parser import extract_pdf_text
from ...services.product_importer import (
    candidates_from_blocks,
    commit_drafts,
    import_products_from_text,
    parse_products_from_text,
    stage_candidates_as_drafts,
)
from ...utils import allowed_file, log_action, relative_pdf_path, relative_product_image_path, save_upload
from . import bp


def _company():
    return current_user.company


@bp.route("/panel")
@approved_required
def index():
    company = _company()
    stats = {
        "products": company.products.count(),
        "categories": company.categories.count(),
        "pdfs": company.pdf_uploads.count(),
        "api_keys": company.api_keys.count(),
    }
    latest_products = company.products.order_by(Product.created_at.desc()).limit(5).all()
    return render_template("dashboard/index.html", company=company, stats=stats, latest_products=latest_products)


@bp.route("/panel/company", methods=["GET", "POST"])
@approved_required
def company():
    company = _company()
    if request.method == "POST":
        company.company_name = request.form.get("company_name", "").strip()
        company.address = request.form.get("address", "").strip()
        company.phone = request.form.get("phone", "").strip()
        company.company_email = request.form.get("company_email", "").strip()
        company.website = request.form.get("website", "").strip()
        company.description = request.form.get("description", "").strip()

        if not company.company_name:
            flash("El nombre de la compañía es obligatorio.", "danger")
            return render_template("dashboard/company.html", company=company)

        db.session.commit()
        log_action("update_company", entity_type="company", entity_id=company.id, company_id=company.id, user_id=current_user.id)
        flash("Datos de empresa actualizados.", "success")
        return redirect(url_for("dashboard.company"))

    return render_template("dashboard/company.html", company=company)


@bp.route("/panel/categories", methods=["GET", "POST"])
@approved_required
def categories():
    company = _company()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        parent_id = request.form.get("parent_id") or None

        if not name:
            flash("El nombre de la categoría es obligatorio.", "danger")
            return redirect(url_for("dashboard.categories"))

        category = Category(company_id=company.id, name=name, parent_id=int(parent_id) if parent_id else None)
        db.session.add(category)
        db.session.commit()
        log_action("create_category", entity_type="category", entity_id=category.id, company_id=company.id, user_id=current_user.id)
        flash("Categoría creada.", "success")
        return redirect(url_for("dashboard.categories"))

    primary_categories = company.categories.filter_by(parent_id=None).order_by(Category.name.asc()).all()
    all_categories = company.categories.order_by(Category.created_at.desc()).all()
    return render_template("dashboard/categories.html", primary_categories=primary_categories, all_categories=all_categories)


@bp.route("/panel/categories/<int:category_id>/delete", methods=["POST"])
@approved_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    company = _company()

    if category.company_id != company.id:
        flash("No tienes permiso para eliminar esta categoría.", "danger")
        return redirect(url_for("dashboard.categories"))

    if category.children.count() > 0:
        flash("No puedes eliminar una categoría que tiene subcategorías.", "warning")
        return redirect(url_for("dashboard.categories"))

    linked_products = Product.query.filter((Product.category_id == category.id) | (Product.subcategory_id == category.id)).count()
    if linked_products:
        flash("No puedes eliminar una categoría usada por productos.", "warning")
        return redirect(url_for("dashboard.categories"))

    db.session.delete(category)
    db.session.commit()
    log_action("delete_category", entity_type="category", entity_id=category.id, company_id=company.id, user_id=current_user.id)
    flash("Categoría eliminada.", "info")
    return redirect(url_for("dashboard.categories"))


@bp.route("/panel/products")
@approved_required
def products():
    company = _company()
    products = company.products.order_by(Product.created_at.desc()).all()
    return render_template("dashboard/products.html", products=products)


@bp.route("/panel/catalog")
@approved_required
def catalog():
    company = _company()
    products = (
        company.products
        .filter_by(is_active=True)
        .order_by(Product.created_at.desc())
        .all()
    )
    return render_template("dashboard/catalog.html", products=products)


def _parse_product_form(product: Product | None = None):
    company = _company()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    sku = request.form.get("sku", "").strip()
    stock_raw = request.form.get("stock", "0").strip()
    price_raw = request.form.get("price", "0").strip()
    category_id = request.form.get("category_id") or None
    subcategory_id = request.form.get("subcategory_id") or None
    is_active = bool(request.form.get("is_active"))

    if not name:
        raise ValueError("El nombre del producto es obligatorio.")

    try:
        price = Decimal(price_raw)
    except InvalidOperation as exc:
        raise ValueError("El precio debe ser numérico.") from exc

    try:
        stock = int(stock_raw)
    except ValueError as exc:
        raise ValueError("El stock debe ser entero.") from exc

    if product is None:
        product = Product(company_id=company.id)

    product.name = name
    product.description = description
    product.sku = sku
    product.price = price
    product.stock = stock
    product.category_id = int(category_id) if category_id else None
    product.subcategory_id = int(subcategory_id) if subcategory_id else None
    product.is_active = is_active

    image = request.files.get("image")
    if image and image.filename:
        if not allowed_file(image.filename, current_app.config["ALLOWED_IMAGE_EXTENSIONS"]):
            raise ValueError("Formato de imagen no permitido.")
        filename = save_upload(image, Path(current_app.config["PRODUCT_UPLOAD_FOLDER"]))
        product.image_path = relative_product_image_path(filename)

    return product


@bp.route("/panel/products/new", methods=["GET", "POST"])
@approved_required
def product_create():
    company = _company()
    if request.method == "POST":
        try:
            product = _parse_product_form()
            db.session.add(product)
            db.session.commit()
            log_action("create_product", entity_type="product", entity_id=product.id, company_id=company.id, user_id=current_user.id)
            flash("Producto creado.", "success")
            return redirect(url_for("dashboard.products"))
        except ValueError as error:
            flash(str(error), "danger")

    primary_categories = company.categories.filter_by(parent_id=None).order_by(Category.name.asc()).all()
    secondary_categories = company.categories.filter(Category.parent_id.isnot(None)).order_by(Category.name.asc()).all()
    return render_template("dashboard/product_form.html", product=None, primary_categories=primary_categories, secondary_categories=secondary_categories)


@bp.route("/panel/products/<int:product_id>/edit", methods=["GET", "POST"])
@approved_required
def product_edit(product_id):
    company = _company()
    product = Product.query.get_or_404(product_id)
    if product.company_id != company.id:
        flash("No tienes permiso para editar este producto.", "danger")
        return redirect(url_for("dashboard.products"))

    if request.method == "POST":
        try:
            product = _parse_product_form(product)
            db.session.commit()
            log_action("update_product", entity_type="product", entity_id=product.id, company_id=company.id, user_id=current_user.id)
            flash("Producto actualizado.", "success")
            return redirect(url_for("dashboard.products"))
        except ValueError as error:
            flash(str(error), "danger")

    primary_categories = company.categories.filter_by(parent_id=None).order_by(Category.name.asc()).all()
    secondary_categories = company.categories.filter(Category.parent_id.isnot(None)).order_by(Category.name.asc()).all()
    return render_template("dashboard/product_form.html", product=product, primary_categories=primary_categories, secondary_categories=secondary_categories)


@bp.route("/panel/products/<int:product_id>/delete", methods=["POST"])
@approved_required
def product_delete(product_id):
    company = _company()
    product = Product.query.get_or_404(product_id)
    if product.company_id != company.id:
        flash("No tienes permiso para eliminar este producto.", "danger")
        return redirect(url_for("dashboard.products"))

    db.session.delete(product)
    db.session.commit()
    log_action("delete_product", entity_type="product", entity_id=product.id, company_id=company.id, user_id=current_user.id)
    flash("Producto eliminado.", "info")
    return redirect(url_for("dashboard.products"))


@bp.route("/panel/agent-settings", methods=["GET", "POST"])
@approved_required
def agent_settings():
    company = _company()
    settings = company.agent_settings or AgentSetting(company_id=company.id)

    if request.method == "POST":
        settings.agent_name = request.form.get("agent_name", "").strip()
        settings.tone = request.form.get("tone", "").strip()
        settings.system_instructions = request.form.get("system_instructions", "").strip()
        settings.sales_behavior = request.form.get("sales_behavior", "").strip()
        settings.support_rules = request.form.get("support_rules", "").strip()
        settings.business_context = request.form.get("business_context", "").strip()
        settings.response_style = request.form.get("response_style", "").strip()

        if not settings.id:
            db.session.add(settings)

        db.session.commit()
        log_action("update_agent_settings", entity_type="agent_settings", entity_id=settings.id, company_id=company.id, user_id=current_user.id)
        flash("Configuración del agente actualizada.", "success")
        return redirect(url_for("dashboard.agent_settings"))

    return render_template("dashboard/agent_settings.html", settings=settings)


@bp.route("/panel/pdfs", methods=["GET", "POST"])
@approved_required
def pdf_uploads():
    company = _company()

    if request.method == "POST":
        pdf = request.files.get("pdf")
        if not pdf or not pdf.filename:
            flash("Debes seleccionar un PDF.", "danger")
            return redirect(url_for("dashboard.pdf_uploads"))

        if not allowed_file(pdf.filename, current_app.config["ALLOWED_PDF_EXTENSIONS"]):
            flash("Solo se permiten archivos PDF.", "danger")
            return redirect(url_for("dashboard.pdf_uploads"))

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
            extracted = "No se pudo procesar el PDF. Revisa el archivo y el parser."

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

        log_action("upload_pdf", entity_type="pdf_upload", entity_id=upload.id, company_id=company.id, user_id=current_user.id)
        if status == "imported":
            flash(f"PDF procesado. Productos importados: {import_result['created_count']}.", "success")
        elif status == "processed":
            flash("PDF procesado, pero no se detectaron productos nuevos.", "warning")
        else:
            flash("No se pudo procesar el PDF.", "warning")
        return redirect(url_for("dashboard.pdf_uploads"))

    uploads = company.pdf_uploads.order_by(PdfUpload.created_at.desc()).all()
    return render_template("dashboard/pdf_uploads.html", uploads=uploads)


@bp.route("/panel/imports", methods=["GET", "POST"])
@approved_required
def imports():
    company = _company()

    if request.method == "POST":
        action = (request.form.get("action") or "upload").lower()

        if action == "commit":
            try:
                job_id = int(request.form.get("job_id") or 0)
            except ValueError:
                job_id = 0
            job = ImportJob.query.get(job_id) if job_id else None
            if not job or job.company_id != company.id:
                flash("Trabajo de importación no encontrado.", "danger")
                return redirect(url_for("dashboard.imports"))
            try:
                result = commit_drafts(job)
                remaining = job.items.filter_by(status="draft").count()
                job.status = "committed" if remaining == 0 else "ready"
                db.session.commit()
                log_action("commit_image_import", entity_type="import_job", entity_id=job.id,
                           company_id=company.id, user_id=current_user.id,
                           details=json.dumps(result))
                flash(f"Importados {result['committed']} productos. {result['skipped']} omitidos.", "success")
            except Exception:  # noqa: BLE001
                db.session.rollback()
                flash("No se pudo confirmar la importación.", "danger")
            return redirect(url_for("dashboard.imports"))

        upload = request.files.get("file") or request.files.get("image")
        if not upload or not upload.filename:
            flash("Selecciona o captura un archivo.", "danger")
            return redirect(url_for("dashboard.imports"))
        if not allowed_file(upload.filename, current_app.config["ALLOWED_IMPORT_EXTENSIONS"]):
            flash("Formato no permitido. Usa PDF, CSV o imagen.", "danger")
            return redirect(url_for("dashboard.imports"))

        source = _detect_source(upload.filename)
        if not source:
            flash("Formato no permitido.", "danger")
            return redirect(url_for("dashboard.imports"))

        target_folder = _target_folder_for(source)
        stored_filename = save_upload(upload, target_folder)
        full_path = target_folder / stored_filename
        stored_path = str(full_path.relative_to(Path(current_app.root_path)))
        mode = (request.form.get("mode") or "").strip().lower() or None

        job = ImportJob(
            company_id=company.id,
            user_id=current_user.id,
            source=source,
            status="processing",
            original_filename=upload.filename,
            stored_path=stored_path,
        )
        db.session.add(job)
        db.session.flush()

        summary: dict = {"mode": mode}
        try:
            if source == "pdf":
                candidates = _pdf_candidates_panel(full_path, job.id, summary)
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

            stage_candidates_as_drafts(job, candidates)
            job.status = "ready"
            summary["detected"] = len(candidates)
            summary["source"] = source
            job.summary = json.dumps(summary)
            db.session.commit()
            log_action("upload_import", entity_type="import_job", entity_id=job.id,
                       company_id=company.id, user_id=current_user.id)
            flash(f"{source.upper()} procesado. Detectados {len(candidates)} borrador(es).", "success")
        except Exception:  # noqa: BLE001
            db.session.rollback()
            job.status = "failed"
            job.summary = json.dumps({"error": "exception", "source": source})
            db.session.add(job)
            db.session.commit()
            flash("No se pudo procesar el archivo.", "danger")

        return redirect(url_for("dashboard.imports"))

    jobs = (
        ImportJob.query
        .filter_by(company_id=company.id)
        .order_by(ImportJob.created_at.desc())
        .limit(25)
        .all()
    )
    items_by_job = {
        job.id: ImportItem.query.filter_by(job_id=job.id).order_by(ImportItem.id.asc()).all()
        for job in jobs
    }
    return render_template("dashboard/imports.html", jobs=jobs, items_by_job=items_by_job)


@bp.route("/panel/api-keys", methods=["GET", "POST"])
@approved_required
def api_keys():
    company = _company()
    plain_key = None

    if request.method == "POST":
        label = request.form.get("label", "").strip()
        if not label:
            flash("La etiqueta es obligatoria.", "danger")
            return redirect(url_for("dashboard.api_keys"))

        api_key, plain = ApiKey.create_key(company_id=company.id, label=label)
        db.session.add(api_key)
        db.session.commit()
        plain_key = plain
        log_action("create_api_key", entity_type="api_key", entity_id=api_key.id, company_id=company.id, user_id=current_user.id)
        flash("API key creada. Cópiala ahora, luego solo verás los últimos 4 caracteres.", "success")

    keys = company.api_keys.order_by(ApiKey.created_at.desc()).all()
    return render_template("dashboard/api_keys.html", keys=keys, plain_key=plain_key)


@bp.route("/panel/api-keys/<int:key_id>/revoke", methods=["POST"])
@approved_required
def revoke_api_key(key_id):
    company = _company()
    api_key = ApiKey.query.get_or_404(key_id)
    if api_key.company_id != company.id:
        flash("No tienes permiso para revocar esta clave.", "danger")
        return redirect(url_for("dashboard.api_keys"))

    api_key.is_active = False
    db.session.commit()
    log_action("revoke_api_key", entity_type="api_key", entity_id=api_key.id, company_id=company.id, user_id=current_user.id)
    flash("API key revocada.", "info")
    return redirect(url_for("dashboard.api_keys"))


def _detect_source(filename: str) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in current_app.config["ALLOWED_PDF_EXTENSIONS"]:
        return "pdf"
    if ext in current_app.config["ALLOWED_CSV_EXTENSIONS"]:
        return "csv"
    if ext in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        return "image"
    return None


def _target_folder_for(source: str) -> Path:
    if source == "image":
        return Path(current_app.config["PRODUCT_UPLOAD_FOLDER"])
    if source == "pdf":
        return Path(current_app.config["PDF_UPLOAD_FOLDER"])
    return Path(current_app.config["IMPORT_UPLOAD_FOLDER"])


def _pdf_candidates_panel(full_path, job_id: int, summary: dict):
    """Same strategy as the API: blocks first, text fallback."""
    dst = Path(current_app.config["PRODUCT_UPLOAD_FOLDER"])
    prefix = f"job{job_id}"
    try:
        blocks = extract_product_blocks_from_pdf(full_path, dst, prefix)
    except PDFBlocksUnavailable as exc:
        summary["pdf_blocks_error"] = str(exc)
        blocks = []

    if blocks:
        summary["pdf_blocks"] = len(blocks)
        candidates = candidates_from_blocks(blocks)
        if candidates:
            return candidates

    text = extract_pdf_text(full_path)
    summary["pdf_text_chars"] = len(text or "")
    return parse_products_from_text(text or "")
