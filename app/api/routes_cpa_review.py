"""
CPA-only review and approval surface. This is the ONLY file in the codebase
that can write a ReviewDecision or move a ProposedJournalEntry into
approved/rejected/needs_revision — enforced three independent ways:

  1. Every route requires require_role(UserRole.CPA) (app-level).
  2. Every route uses get_cpa_db, bound to the datumai_cpa_service Postgres
     role, which is the only role granted INSERT on review_decisions.
  3. Even if (1) and (2) both had bugs, the database trigger in
     0002_security_roles_and_grants.py independently blocks any connection
     authenticated as datumai_ai_service from writing an approved/rejected/
     posted/reversed status, full stop.

tests/security/test_api_surface.py statically asserts no approval-capable
route exists anywhere outside this router.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_cpa_db, require_role
from app.core.security import TokenPayload
from app.models.accounting_period import GLAccount
from app.models.audit_event import AuditEvent
from app.models.enums import ActorType, EntryStatus, ExceptionStatus, ReviewDecisionType, UserRole
from app.models.exception_record import ExceptionRecord
from app.models.journal_entry import JournalEntryLine, ProposedJournalEntry
from app.models.review_decision import ReviewDecision
from app.schemas.review import (
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueueEntry,
    ReviewQueueException,
    ReviewQueueLine,
)
from app.services.accounting.entry_state_machine import InvalidEntryTransition, assert_transition_allowed

router = APIRouter(prefix="/cpa", tags=["cpa-review"])

require_cpa = require_role(UserRole.CPA)


def _get_entry_or_404(db: Session, entry_id: uuid.UUID) -> ProposedJournalEntry:
    entry = db.get(ProposedJournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    return entry


def _serialize_entry(db: Session, entry: ProposedJournalEntry) -> ReviewQueueEntry:
    lines = db.scalars(select(JournalEntryLine).where(JournalEntryLine.entry_id == entry.id)).all()
    gl_accounts = {a.id: a for a in db.scalars(select(GLAccount)).all()}
    exceptions = db.scalars(
        select(ExceptionRecord).where(
            ExceptionRecord.related_entry_id == entry.id, ExceptionRecord.status == ExceptionStatus.OPEN
        )
    ).all()

    return ReviewQueueEntry(
        id=entry.id,
        client_id=entry.client_id,
        period_id=entry.period_id,
        status=entry.status.value,
        description=entry.description,
        confidence=entry.confidence,
        source_document_id=entry.source_document_id,
        created_at=entry.created_at.isoformat(),
        lines=[
            ReviewQueueLine(
                gl_account_code=gl_accounts[line.gl_account_id].code,
                gl_account_name=gl_accounts[line.gl_account_id].name,
                debit=float(line.debit),
                credit=float(line.credit),
            )
            for line in lines
        ],
        exceptions=[
            ReviewQueueException(
                id=exc.id, type=exc.type.value, severity=exc.severity.value, description=exc.description
            )
            for exc in exceptions
        ],
    )


@router.get("/review-queue", response_model=list[ReviewQueueEntry])
def get_review_queue(
    client_id: uuid.UUID | None = None,
    token: TokenPayload = Depends(require_cpa),
    db: Session = Depends(get_cpa_db),
) -> list[ReviewQueueEntry]:
    query = select(ProposedJournalEntry).where(ProposedJournalEntry.status == EntryStatus.PENDING_REVIEW)
    if client_id is not None:
        query = query.where(ProposedJournalEntry.client_id == client_id)
    query = query.order_by(ProposedJournalEntry.created_at.asc())

    entries = db.scalars(query).all()
    return [_serialize_entry(db, entry) for entry in entries]


def _decide(
    *,
    db: Session,
    token: TokenPayload,
    entry_id: uuid.UUID,
    payload: ReviewDecisionRequest,
    to_status: EntryStatus,
    decision_type: ReviewDecisionType,
) -> ReviewDecisionResponse:
    entry = _get_entry_or_404(db, entry_id)

    try:
        assert_transition_allowed(from_status=entry.status, to_status=to_status, actor_role=token.role)
    except InvalidEntryTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    cpa_user_id = uuid.UUID(token.sub)
    before_status = entry.status.value

    entry.status = to_status
    db.flush()

    decision = ReviewDecision(
        entry_id=entry.id,
        cpa_user_id=cpa_user_id,
        decision=decision_type,
        rationale=payload.rationale,
        mfa_verified=False,  # MFA hardware flow is a Phase 2 requirement — see plan Section 10.1
        decided_at=datetime.now(timezone.utc),
    )
    db.add(decision)
    db.flush()

    db.add(
        AuditEvent(
            client_id=entry.client_id,
            event_type=f"entry.{decision_type.value}",
            actor_id=cpa_user_id,
            actor_type=ActorType.HUMAN,
            entity_type="proposed_journal_entry",
            entity_id=entry.id,
            before_json={"status": before_status},
            after_json={"status": to_status.value, "review_decision_id": str(decision.id)},
        )
    )

    db.commit()

    return ReviewDecisionResponse(
        decision_id=decision.id, entry_id=entry.id, decision=decision_type.value, new_status=to_status.value
    )


@router.post("/entries/{entry_id}/approve", response_model=ReviewDecisionResponse)
def approve_entry(
    entry_id: uuid.UUID,
    payload: ReviewDecisionRequest,
    token: TokenPayload = Depends(require_cpa),
    db: Session = Depends(get_cpa_db),
) -> ReviewDecisionResponse:
    return _decide(
        db=db,
        token=token,
        entry_id=entry_id,
        payload=payload,
        to_status=EntryStatus.APPROVED,
        decision_type=ReviewDecisionType.APPROVED,
    )


@router.post("/entries/{entry_id}/reject", response_model=ReviewDecisionResponse)
def reject_entry(
    entry_id: uuid.UUID,
    payload: ReviewDecisionRequest,
    token: TokenPayload = Depends(require_cpa),
    db: Session = Depends(get_cpa_db),
) -> ReviewDecisionResponse:
    return _decide(
        db=db,
        token=token,
        entry_id=entry_id,
        payload=payload,
        to_status=EntryStatus.REJECTED,
        decision_type=ReviewDecisionType.REJECTED,
    )


@router.post("/entries/{entry_id}/request-revision", response_model=ReviewDecisionResponse)
def request_revision(
    entry_id: uuid.UUID,
    payload: ReviewDecisionRequest,
    token: TokenPayload = Depends(require_cpa),
    db: Session = Depends(get_cpa_db),
) -> ReviewDecisionResponse:
    return _decide(
        db=db,
        token=token,
        entry_id=entry_id,
        payload=payload,
        to_status=EntryStatus.NEEDS_REVISION,
        decision_type=ReviewDecisionType.REVISION_REQUIRED,
    )
