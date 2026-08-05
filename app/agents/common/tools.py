"""
Tool helpers shared by every agent: exception flagging, tool-invocation
logging, and audit-event logging. None of these can move any entity into
an approved/rejected/posted/reversed/delivered state — that capability
exists nowhere under app/agents/, only in app/api/routes_cpa_review.py.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.enums import ActorType, ExceptionSeverity, ExceptionStatus, ExceptionType
from app.models.exception_record import ExceptionRecord
from app.models.workflow import ToolInvocation


def flag_exception(
    db: Session,
    *,
    client_id: UUID,
    period_id: UUID | None,
    related_entry_id: UUID | None,
    exception_type: ExceptionType,
    severity: ExceptionSeverity,
    description: str,
    detected_by: str,
) -> ExceptionRecord:
    record = ExceptionRecord(
        client_id=client_id,
        period_id=period_id,
        related_entry_id=related_entry_id,
        type=exception_type,
        severity=severity,
        status=ExceptionStatus.OPEN,
        description=description,
        detected_by=detected_by,
    )
    db.add(record)
    db.flush()
    return record


def log_tool_invocation(
    db: Session,
    *,
    workflow_run_id: UUID,
    tool_name: str,
    input_json: dict,
    output_json: dict,
    model: str | None,
    skill_version: str | None,
    duration_ms: int,
) -> ToolInvocation:
    invocation = ToolInvocation(
        workflow_run_id=workflow_run_id,
        tool_name=tool_name,
        input_json=input_json,
        output_json=output_json,
        model=model,
        skill_version=skill_version,
        duration_ms=duration_ms,
    )
    db.add(invocation)
    db.flush()
    return invocation


def log_audit_event(
    db: Session,
    *,
    client_id: UUID | None,
    event_type: str,
    actor_id: UUID | None,
    actor_type: ActorType,
    entity_type: str,
    entity_id: UUID,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        client_id=client_id,
        event_type=event_type,
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=before,
        after_json=after,
    )
    db.add(event)
    db.flush()
    return event


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
