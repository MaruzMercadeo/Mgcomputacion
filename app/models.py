from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import secrets

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="client")  # admin | client
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | approved | rejected | disabled
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)

    approved_by = db.relationship("User", remote_side=[id], uselist=False)
    company = db.relationship("Company", foreign_keys=[company_id], back_populates="users")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Company(TimestampMixin, db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(180), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    company_email = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    users = db.relationship("User", back_populates="company", lazy="select")
    categories = db.relationship("Category", back_populates="company", lazy="dynamic", cascade="all, delete-orphan")
    products = db.relationship("Product", back_populates="company", lazy="dynamic", cascade="all, delete-orphan")
    agent_settings = db.relationship("AgentSetting", back_populates="company", uselist=False, cascade="all, delete-orphan")
    pdf_uploads = db.relationship("PdfUpload", back_populates="company", lazy="dynamic", cascade="all, delete-orphan")
    api_keys = db.relationship("ApiKey", back_populates="company", lazy="dynamic", cascade="all, delete-orphan")
    audit_logs = db.relationship("AuditLog", back_populates="company", lazy="dynamic", cascade="all, delete-orphan")
    import_jobs = db.relationship("ImportJob", back_populates="company", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company {self.company_name}>"


class Category(TimestampMixin, db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    company = db.relationship("Company", back_populates="categories")
    parent = db.relationship("Category", remote_side=[id], backref=db.backref("children", lazy="dynamic"))
    products_primary = db.relationship("Product", foreign_keys="Product.category_id", back_populates="primary_category")
    products_secondary = db.relationship("Product", foreign_keys="Product.subcategory_id", back_populates="secondary_category")

    def __repr__(self) -> str:
        return f"<Category {self.name}>"


class Product(TimestampMixin, db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    subcategory_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    name = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    image_path = db.Column(db.String(255), nullable=True)
    sku = db.Column(db.String(80), nullable=True)
    stock = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    company = db.relationship("Company", back_populates="products")
    primary_category = db.relationship("Category", foreign_keys=[category_id], back_populates="products_primary")
    secondary_category = db.relationship("Category", foreign_keys=[subcategory_id], back_populates="products_secondary")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "name": self.name,
            "description": self.description,
            "price": float(self.price or 0),
            "image_path": self.image_path,
            "sku": self.sku,
            "stock": self.stock,
            "is_active": self.is_active,
            "category": self.primary_category.name if self.primary_category else None,
            "subcategory": self.secondary_category.name if self.secondary_category else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Product {self.name}>"


class AgentSetting(TimestampMixin, db.Model):
    __tablename__ = "agent_settings"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, unique=True, index=True)
    agent_name = db.Column(db.String(120), nullable=True)
    tone = db.Column(db.String(80), nullable=True)
    system_instructions = db.Column(db.Text, nullable=True)
    sales_behavior = db.Column(db.Text, nullable=True)
    support_rules = db.Column(db.Text, nullable=True)
    business_context = db.Column(db.Text, nullable=True)
    response_style = db.Column(db.Text, nullable=True)

    company = db.relationship("Company", back_populates="agent_settings")

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "tone": self.tone,
            "system_instructions": self.system_instructions,
            "sales_behavior": self.sales_behavior,
            "support_rules": self.support_rules,
            "business_context": self.business_context,
            "response_style": self.response_style,
            "updated_at": self.updated_at.isoformat(),
        }


class PdfUpload(TimestampMixin, db.Model):
    __tablename__ = "pdf_uploads"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="uploaded")  # uploaded | processed | imported | failed
    extracted_preview = db.Column(db.Text, nullable=True)
    processed_at = db.Column(db.DateTime, nullable=True)
    imported_items_count = db.Column(db.Integer, nullable=False, default=0)

    company = db.relationship("Company", back_populates="pdf_uploads")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_filename": self.original_filename,
            "status": self.status,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "preview": self.extracted_preview,
            "imported_items_count": self.imported_items_count,
        }


class ApiKey(TimestampMixin, db.Model):
    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    label = db.Column(db.String(120), nullable=False)
    key_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    last_four = db.Column(db.String(4), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    company = db.relationship("Company", back_populates="api_keys")

    @staticmethod
    def generate_plain_key() -> str:
        return f"mg_{secrets.token_urlsafe(32)}"

    @staticmethod
    def hash_key(plain_key: str) -> str:
        return sha256(plain_key.encode("utf-8")).hexdigest()

    @classmethod
    def create_key(cls, company_id: int, label: str) -> tuple["ApiKey", str]:
        plain = cls.generate_plain_key()
        api_key = cls(
            company_id=company_id,
            label=label,
            key_hash=cls.hash_key(plain),
            last_four=plain[-4:],
            is_active=True,
        )
        return api_key, plain

    def matches(self, plain_key: str) -> bool:
        return self.key_hash == self.hash_key(plain_key)


class ImportJob(TimestampMixin, db.Model):
    __tablename__ = "import_jobs"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    source = db.Column(db.String(20), nullable=False)  # pdf | csv | image
    status = db.Column(db.String(20), nullable=False, default="processing")  # processing | ready | committed | failed
    original_filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text, nullable=True)

    company = db.relationship("Company", back_populates="import_jobs")
    user = db.relationship("User", foreign_keys=[user_id])
    items = db.relationship("ImportItem", back_populates="job", lazy="dynamic", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "status": self.status,
            "original_filename": self.original_filename,
            "stored_path": self.stored_path,
            "summary": self.summary,
            "items_count": self.items.count(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ImportItem(TimestampMixin, db.Model):
    __tablename__ = "import_items"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("import_jobs.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft | committed | skipped
    payload = db.Column(db.Text, nullable=False)  # JSON serialized
    reason = db.Column(db.String(255), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)

    job = db.relationship("ImportJob", back_populates="items")
    product = db.relationship("Product", foreign_keys=[product_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "status": self.status,
            "payload": self.payload,
            "reason": self.reason,
            "product_id": self.product_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    action = db.Column(db.String(120), nullable=False)
    entity_type = db.Column(db.String(120), nullable=True)
    entity_id = db.Column(db.String(64), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    company = db.relationship("Company", back_populates="audit_logs")
    user = db.relationship("User", lazy="joined")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
