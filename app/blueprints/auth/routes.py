from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from ...extensions import db
from ...models import AgentSetting, Company, User
from ...utils import log_action
from . import bp


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        if current_user.status == "approved":
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.pending"))

    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "").strip()
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Credenciales inválidas.", "danger")
            return render_template("auth/login.html")

        if user.status == "pending":
            flash("Tu cuenta sigue pendiente de aprobación.", "warning")
            return redirect(url_for("auth.pending"))

        if user.status in {"rejected", "disabled"}:
            flash("Tu cuenta no tiene acceso en este momento. Contacta al administrador.", "danger")
            return render_template("auth/login.html")

        user.last_login_at = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=remember)
        log_action("login", entity_type="user", entity_id=user.id, company_id=user.company_id, user_id=user.id)
        flash("Sesión iniciada correctamente.", "success")

        if user.is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index" if not current_user.is_admin else "admin.dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        company_name = request.form.get("company_name", "").strip()
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([name, company_name, email, password, confirm_password]):
            flash("Todos los campos son obligatorios.", "danger")
            return render_template("auth/register.html")

        if password != confirm_password:
            flash("Las contraseñas no coinciden.", "danger")
            return render_template("auth/register.html")

        if len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "danger")
            return render_template("auth/register.html")

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("Ya existe una cuenta con ese correo.", "danger")
            return render_template("auth/register.html")

        company = Company(company_name=company_name, company_email=email)
        db.session.add(company)
        db.session.flush()

        user = User(
            name=name,
            email=email,
            role="client",
            status="pending",
            company_id=company.id,
        )
        user.set_password(password)
        db.session.add(user)

        agent_settings = AgentSetting(
            company_id=company.id,
            agent_name=f"Asistente de {company_name}",
            tone="profesional",
            system_instructions="Responde con precisión usando solo la información registrada en el sistema.",
        )
        db.session.add(agent_settings)
        db.session.commit()

        log_action("register", entity_type="user", entity_id=user.id, company_id=company.id, user_id=user.id)
        flash("Cuenta creada. Queda pendiente de aprobación por el administrador.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@bp.route("/pending")
def pending():
    return render_template("auth/pending.html")


@bp.route("/logout", methods=["POST"])
def logout():
    if current_user.is_authenticated:
        log_action("logout", entity_type="user", entity_id=current_user.id, company_id=current_user.company_id, user_id=current_user.id)
        logout_user()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))
