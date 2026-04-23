from __future__ import annotations

import click
from flask.cli import with_appcontext
from sqlalchemy import inspect

from .extensions import db
from .models import User, Company, AgentSetting, ApiKey


BASELINE_REVISION = "bb0ccbd48cf3"


@click.command("init-db")
@with_appcontext
def init_db_command():
    db.create_all()
    click.echo("Base de datos creada.")


@click.command("upgrade-db")
@with_appcontext
def upgrade_db_command():
    """Idempotent: stamps baseline on pre-migration DBs, then upgrades to head.

    Safe to run on empty, existing-but-unmigrated, or already-migrated DBs.
    """
    from flask_migrate import stamp, upgrade

    tables = set(inspect(db.engine).get_table_names())

    if "alembic_version" not in tables:
        if "users" in tables and "import_jobs" not in tables:
            click.echo("DB con esquema baseline detectada: marcando baseline...")
            stamp(revision=BASELINE_REVISION)
        elif "import_jobs" in tables:
            click.echo("DB ya al día manualmente: marcando head...")
            stamp(revision="head")
        else:
            click.echo("DB vacía: se creará todo con el upgrade.")

    click.echo("Aplicando migraciones pendientes...")
    upgrade()
    click.echo("Listo.")


@click.command("llm-ping")
@with_appcontext
def llm_ping_command():
    """Hace una llamada mínima al supervisor LLM activo y muestra el resultado."""
    from decimal import Decimal

    from flask import current_app

    from .services.llm_supervisor import NullSupervisor, SupervisionRequest, get_supervisor
    from .services.product_importer import ProductCandidate

    active = (
        __import__("os").environ.get("LLM_SUPERVISOR_ACTIVE")
        or current_app.config.get("LLM_SUPERVISOR_ACTIVE")
        or "off"
    )
    provider = current_app.config.get("LLM_SUPERVISOR_PROVIDER") or "(vacío)"
    model = current_app.config.get("LLM_SUPERVISOR_MODEL") or "(vacío)"
    api_key = current_app.config.get("LLM_SUPERVISOR_API_KEY") or ""

    click.echo("=== Config actual ===")
    click.echo(f"  LLM_SUPERVISOR_ACTIVE: {active}")
    click.echo(f"  provider:              {provider}")
    click.echo(f"  model:                 {model}")
    click.echo(f"  api_key:               {'***' + api_key[-6:] if api_key else '(vacío)'}")

    sup = get_supervisor()
    if isinstance(sup, NullSupervisor):
        click.echo("\nSupervisor activo: NullSupervisor (no se hace llamada real).")
        click.echo("Motivos posibles: ACTIVE=off, PROVIDER/MODEL/API_KEY vacíos, o provider no soportado.")
        return

    click.echo(f"\nSupervisor activo: {sup.__class__.__name__}")
    click.echo("Enviando prompt de prueba...\n")

    request = SupervisionRequest(
        ocr_text="Producto de prueba TEST-001, precio 10.00",
        heuristic_candidates=[
            ProductCandidate(name="TEST-001", price=Decimal("0"), sku=None, stock=0)
        ],
        image_path=None,
        hints={"mode": "advanced"},
    )
    result = sup.review(request)

    click.echo(f"  notes: {result.notes}")
    for c in result.candidates:
        click.echo(
            f"  → name={c.name!r}  sku={c.sku!r}  price={c.price}  "
            f"conf={c.confidence}  warnings={list(c.warnings)}"
        )

    if result.notes.startswith("fallback:"):
        click.echo("\n✗ La llamada FALLÓ. Revisá API key, modelo y conexión.")
    else:
        click.echo("\n✓ El supervisor respondió correctamente.")


@click.command("seed-admin")
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--name", prompt=True)
@with_appcontext
def seed_admin_command(email, password, name):
    existing = User.query.filter_by(email=email.lower().strip()).first()
    if existing:
        click.echo("Ya existe un usuario con ese email.")
        return

    company = Company(company_name="MGComputacion Admin")
    db.session.add(company)
    db.session.flush()

    user = User(
        name=name.strip(),
        email=email.lower().strip(),
        role="admin",
        status="approved",
        company_id=company.id,
    )
    user.set_password(password)
    db.session.add(user)

    settings = AgentSetting(company_id=company.id, agent_name="Admin Agent", tone="profesional")
    db.session.add(settings)
    db.session.commit()
    click.echo(f"Admin creado: {email}")


@click.command("generate-api-key")
@click.option("--company-id", type=int, prompt=True)
@click.option("--label", prompt=True)
@with_appcontext
def generate_api_key_command(company_id, label):
    company = Company.query.get(company_id)
    if not company:
        click.echo("Empresa no encontrada.")
        return

    api_key, plain = ApiKey.create_key(company_id=company_id, label=label)
    db.session.add(api_key)
    db.session.commit()
    click.echo("Guarda esta API key; no se mostrará otra vez:")
    click.echo(plain)


def register_commands(app):
    app.cli.add_command(init_db_command)
    app.cli.add_command(upgrade_db_command)
    app.cli.add_command(llm_ping_command)
    app.cli.add_command(seed_admin_command)
    app.cli.add_command(generate_api_key_command)
