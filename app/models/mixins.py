import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """SQLAlchemy's Enum() stores Python enum *member names* by default
    (e.g. 'APPROVED'), not the lowercase string .value ('approved') that
    the rest of the app — Pydantic schemas, the trigger in
    0002_security_roles_and_grants.py, API JSON — actually uses. Every
    model's Enum column must go through this helper so the DB, the ORM,
    and the security trigger all agree on the same literal values."""
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [member.value for member in e])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
