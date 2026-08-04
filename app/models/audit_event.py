import uuid

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ActorType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class AuditEvent(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Append-only system of record for every state change. No application
    role (including datumai_cpa_service) has UPDATE or DELETE grant on this
    table in the migration — only INSERT. This is the load-bearing table for
    the "complete audit trail" requirement and for Section 15's traceability
    chain."""

    __tablename__ = "audit_events"

    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    actor_type: Mapped[ActorType] = mapped_column(pg_enum(ActorType, "actor_type"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
