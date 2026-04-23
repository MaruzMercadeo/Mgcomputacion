from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Flask, render_template
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import Config
from .cli import register_commands
from .extensions import db, login_manager, migrate


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Reduce 'database is locked' errors on Windows by enabling WAL + generous timeout."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    if not app.config.get("SECRET_KEY"):
        if os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes"):
            app.config["SECRET_KEY"] = "dev-secret-change-me"
        else:
            raise RuntimeError(
                "SECRET_KEY env var is required when FLASK_DEBUG is not enabled. "
                "Generate one with: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )

    Path(app.config["PRODUCT_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["PDF_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["IMPORT_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Inicia sesión para continuar."
    login_manager.login_message_category = "info"

    from .blueprints.main import bp as main_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.api import bp as api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix="/api/v1")

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    register_commands(app)
    return app
