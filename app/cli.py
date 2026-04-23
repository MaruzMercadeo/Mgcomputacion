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
    app.cli.add_command(pdf_probe_command)
    app.cli.add_command(seed_admin_command)
    app.cli.add_command(generate_api_key_command)


@click.command("pdf-probe")
@click.argument("pdf_path")
@with_appcontext
def pdf_probe_command(pdf_path):
    """Envía un PDF al supervisor Claude activo y muestra el JSON crudo que devuelve.

    Uso: flask --app run.py pdf-probe ruta\\al\\catalogo.pdf
    """
    from pathlib import Path

    from flask import current_app

    from .services.claude_pdf_extractor import ClaudePDFUnavailable, extract_products_with_claude

    provider = (current_app.config.get("LLM_SUPERVISOR_PROVIDER") or "").lower()
    model = current_app.config.get("LLM_SUPERVISOR_MODEL") or ""
    api_key = current_app.config.get("LLM_SUPERVISOR_API_KEY") or ""
    active = current_app.config.get("LLM_SUPERVISOR_ACTIVE") or "(vacío)"

    click.echo("=== Config ===")
    click.echo(f"  ACTIVE:   {active}")
    click.echo(f"  provider: {provider!r}")
    click.echo(f"  model:    {model!r}")
    click.echo(f"  api_key:  {'***' + api_key[-6:] if api_key else '(vacío)'}")

    if provider != "anthropic":
        click.echo(f"\n✗ El supervisor activo no es anthropic. Poné LLM_SUPERVISOR_ACTIVE=1 (Haiku) en .env.")
        return
    if not model or not api_key:
        click.echo("\n✗ Falta model o api_key. Revisá el preset activo en .env.")
        return

    path = Path(pdf_path)
    if not path.exists():
        click.echo(f"\n✗ No existe el archivo: {path}")
        return

    size_mb = path.stat().st_size / 1024 / 1024
    click.echo(f"\nPDF: {path}  ({size_mb:.2f} MB)")
    click.echo("Enviando a Claude... (puede tardar 10-60s)")

    try:
        candidates, stats = extract_products_with_claude(
            path, model=model, api_key=api_key,
            dst_folder=None, filename_prefix="probe",
        )
    except ClaudePDFUnavailable as exc:
        click.echo(f"\n✗ FALLÓ la llamada a Claude: {exc}")
        click.echo("\nCausas típicas:")
        click.echo("  - API key inválida o sin saldo (HTTP 401/402)")
        click.echo("  - PDF demasiado grande (>30 MB)")
        click.echo("  - Rate limit (HTTP 429) — esperá unos segundos")
        click.echo("  - Sin conexión a internet")
        return

    click.echo(f"\n✓ Claude respondió.")
    click.echo(f"  pages_processed:  {stats.get('pages_processed', '?')}")
    click.echo(f"  pages_failed:     {stats.get('pages_failed', 0)}")
    click.echo(f"  truncated_pages:  {stats.get('truncated_pages', 0)}")
    click.echo(f"  input_tokens:     {stats.get('input_tokens', 0)}")
    click.echo(f"  output_tokens:    {stats.get('output_tokens', 0)}")
    click.echo(f"  productos detectados: {stats.get('detected', 0)}")
    cost = stats.get("input_tokens", 0) / 1_000_000 + stats.get("output_tokens", 0) * 5 / 1_000_000
    click.echo(f"  costo aprox:      ${cost:.4f}")
    if stats.get("pages_failed"):
        click.echo(f"\n⚠ {stats['pages_failed']} página(s) fallaron (rate limit/timeout). Probá de nuevo dentro de un minuto.")
    if stats.get("truncated_pages"):
        click.echo(f"\n⚠ {stats['truncated_pages']} página(s) tuvieron respuestas truncadas. Algunos productos pueden faltar.")

    if not candidates:
        click.echo("\n⚠ Claude respondió pero no detectó ningún producto en este PDF.")
        return

    with_price = sum(1 for c in candidates if c.price > 0)
    without_price = len(candidates) - with_price
    click.echo(f"\nResumen: {with_price} con precio, {without_price} con precio 0/null")

    click.echo("\n--- Primeros 15 productos ---")
    for idx, c in enumerate(candidates[:15], start=1):
        click.echo(
            f"  [{idx}] name={c.name!r}"
        )
        click.echo(
            f"       sku={c.sku!r}  price={c.price}  page={c.page_number}  "
            f"conf={c.confidence}  warnings={list(c.warnings)}"
        )
    if len(candidates) > 15:
        click.echo(f"  ... y {len(candidates) - 15} más")
