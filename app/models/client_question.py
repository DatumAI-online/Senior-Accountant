import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ClientQuestionStatus
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class ClientQuestion(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """A question or missing-document request generated from an Exception.
    drafted -> approved_for_sending requires a CPA (or CPA-delegated
    reviewer) action even in MVP, where 'sent' just means visible in-app —
    no outbound email yet. See Section 7.3's state diagram."""

    __tablename__ = "client_questions"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    exception_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exception_records.id"), nullable=True
    )
    status: Mapped[ClientQuestionStatus] = mapped_column(
        pg_enum(ClientQuestionStatus, "client_question_status"),
        default=ClientQuestionStatus.DRAFTED,
        nullable=False,
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    drafted_by: Mapped[str] = mapped_column(String(64), nullable=False)  # agent_type value
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
