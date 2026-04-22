from __future__ import annotations

import click
from flask.cli import with_appcontext

from .extensions import db
from .models import User, Company, AgentSetting, ApiKey


@click.command("init-db")
@with_appcontext
def init_db_command():
    db.create_all()
    click.echo("Base de datos creada.")


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
    app.cli.add_command(seed_admin_command)
    app.cli.add_command(generate_api_key_command)
