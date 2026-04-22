from __future__ import annotations

from functools import wraps

from flask import abort, g, jsonify, request
from flask_login import current_user, login_required

from .services.api_keys import resolve_company_from_api_key


def approved_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.is_admin:
            return view(*args, **kwargs)
        if current_user.status != "approved":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def api_key_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        plain_key = request.headers.get("X-API-Key", "").strip()
        company = resolve_company_from_api_key(plain_key)
        if not company:
            return jsonify({"error": "API key inválida o inactiva"}), 401
        g.api_company = company
        return view(*args, **kwargs)
    return wrapped
