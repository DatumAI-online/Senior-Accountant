import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DocumentType
from app.models.mixins import UUIDPrimaryKeyMixin, pg_enum


class SourceDocument(Base, UUIDPrimaryKeyMixin):
    """An uploaded invoice/receipt/statement/payroll report. file_ref points
    at the storage backend key, not the raw bytes — MVP uses local/dev
    storage behind this same interface so swapping in S3 later is additive.
    content_hash powers deterministic (not LLM-judged) duplicate detection."""

    __tablename__ = "source_documents"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(pg_enum(DocumentType, "document_type"), nullable=False)
    file_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExtractedDocumentData(Base, UUIDPrimaryKeyMixin):
    """Structured Claude-extraction output for a SourceDocument. `fields` is
    the raw structured extraction; confidence and skill_version make the
    output auditable and traceable per Section 15's traceability chain."""

    __tablename__ = "extracted_document_data"

    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.id"), nullable=False, index=True
    )
    fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    skill_name: Mapped[str] = mapped_column(String(128), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
