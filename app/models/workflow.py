import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AgentType, WorkflowRunStatus
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class WorkflowRun(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One execution of an agent workflow. Every ToolInvocation belongs to
    exactly one WorkflowRun, and every WorkflowRun belongs to exactly one
    client — this is part of the traceability chain in Section 15."""

    __tablename__ = "workflow_runs"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    agent_type: Mapped[AgentType] = mapped_column(pg_enum(AgentType, "agent_type"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[WorkflowRunStatus] = mapped_column(
        pg_enum(WorkflowRunStatus, "workflow_run_status"),
        default=WorkflowRunStatus.RUNNING,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class ToolInvocation(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "tool_invocations"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    skill_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
