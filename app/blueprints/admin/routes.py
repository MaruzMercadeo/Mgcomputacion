from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from ...decorators import admin_required
from ...extensions import db
from ...models import Company, Product, User
from ...utils import log_action
from . import bp


@bp.route("/admin")
@admin_required
def dashboard():
    stats = {
        "users_total": User.query.count(),
        "users_pending": User.query.filter_by(status="pending").count(),
        "companies_total": Company.query.count(),
        "products_total": Product.query.count(),
    }
    recent_users = User.query.order_by(User.created_at.desc()).limit(8).all()
    return render_template("admin/dashboard.html", stats=stats, recent_users=recent_users)


@bp.route("/admin/users")
@admin_required
def users():
    status = request.args.get("status", "").strip()
    query = User.query.order_by(User.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    users = query.all()
    return render_template("admin/users.html", users=users, current_status=status)


@bp.route("/admin/users/<int:user_id>/approve", methods=["POST"])
@admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash("No puedes modificar el estado de otro admin desde aquí.", "warning")
        return redirect(url_for("admin.users"))

    user.status = "approved"
    user.approved_at = datetime.utcnow()
    user.approved_by_id = current_user.id
    db.session.commit()
    log_action("approve_user", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=current_user.id)
    flash(f"Usuario {user.email} aprobado.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/admin/users/<int:user_id>/reject", methods=["POST"])
@admin_required
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash("No puedes rechazar un admin.", "warning")
        return redirect(url_for("admin.users"))

    user.status = "rejected"
    db.session.commit()
    log_action("reject_user", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=current_user.id)
    flash(f"Usuario {user.email} rechazado.", "info")
    return redirect(url_for("admin.users"))


@bp.route("/admin/users/<int:user_id>/disable", methods=["POST"])
@admin_required
def disable_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash("No puedes deshabilitar un admin.", "warning")
        return redirect(url_for("admin.users"))

    user.status = "disabled"
    db.session.commit()
    log_action("disable_user", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=current_user.id)
    flash(f"Usuario {user.email} deshabilitado.", "warning")
    return redirect(url_for("admin.users"))
