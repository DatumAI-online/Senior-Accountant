"""
The Intake Bookkeeper Agent's HTTP surface. Every route here requires an
ai_intake-scoped bearer token AND runs on the get_ai_db session (the
datumai_ai_service Postgres role). There is no route in this file, and
there never should be, that can move a ProposedJournalEntry into
approved/rejected/posted/reversed — that capability lives only in
app/api/routes_cpa_review.py, under a completely different role
requirement and a completely different DB session.
"""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.agents.intake_bookkeeper.agent import run_intake_pipeline
from app.api.deps import get_ai_db, require_role
from app.core.security import TokenPayload
from app.models.enums import DocumentType, UserRole
from app.schemas.intake import ExceptionSummary, IntakeRunResponse, ProposedEntrySummary

router = APIRouter(prefix="/agent/intake", tags=["agent:intake-bookkeeper"])

require_intake_agent = require_role(UserRole.AI_INTAKE)


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field_name}: {value}"
        ) from exc


@router.post("/documents", response_model=IntakeRunResponse)
async def submit_document(
    client_id: str = Form(...),
    period_id: str = Form(...),
    doc_type: DocumentType = Form(...),
    raw_text: str | None = Form(default=None),
    file: UploadFile | None = None,
    token: TokenPayload = Depends(require_intake_agent),
    db: Session = Depends(get_ai_db),
) -> IntakeRunResponse:
    if (raw_text is None) == (file is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide exactly one of `raw_text` or `file`.",
        )

    file_bytes: bytes | None = None
    mime_type = "text/plain"
    original_filename = "pasted-text.txt"
    if file is not None:
        file_bytes = await file.read()
        mime_type = file.content_type or "application/octet-stream"
        original_filename = file.filename or "upload"

    result = run_intake_pipeline(
        db,
        client_id=_parse_uuid(client_id, "client_id"),
        period_id=_parse_uuid(period_id, "period_id"),
        uploaded_by=uuid.UUID(token.sub),
        doc_type=doc_type,
        original_filename=original_filename,
        mime_type=mime_type,
        raw_text=raw_text,
        file_bytes=file_bytes,
    )

    return IntakeRunResponse(
        workflow_run_id=result.workflow_run.id,
        workflow_status=result.workflow_run.status.value,
        source_document_id=result.source_document.id,
        entry=(
            ProposedEntrySummary(
                id=result.entry.id,
                status=result.entry.status.value,
                description=result.entry.description,
                confidence=result.entry.confidence,
            )
            if result.entry
            else None
        ),
        exceptions=[
            ExceptionSummary(
                id=exc.id, type=exc.type.value, severity=exc.severity.value, description=exc.description
            )
            for exc in result.exceptions
        ],
    )
