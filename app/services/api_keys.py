from __future__ import annotations

from datetime import datetime

from ..extensions import db
from ..models import ApiKey


def create_api_key_for_company(company_id: int, label: str) -> str:
    api_key, plain = ApiKey.create_key(company_id=company_id, label=label)
    db.session.add(api_key)
    db.session.commit()
    return plain


def resolve_company_from_api_key(plain_key: str):
    if not plain_key:
        return None
    hashed = ApiKey.hash_key(plain_key)
    api_key = ApiKey.query.filter_by(key_hash=hashed, is_active=True).first()
    if not api_key:
        return None
    api_key.last_used_at = datetime.utcnow()
    db.session.commit()
    return api_key.company
