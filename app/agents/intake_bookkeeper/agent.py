"""
Intake Bookkeeper Agent orchestration.

run_intake_pipeline() is the one entry point: given a single uploaded
document, it extracts structured data, classifies the expense against the
client's actual chart of accounts, and — if everything validates — proposes
a journal entry directly in `pending_review`. It never creates anything in
`approved`/`rejected`/`posted`/`reversed`; those enum values don't even
appear in this file. See DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 5.2 for
the agent's full responsibility/prohibition table.

Known MVP simplification (documented, not hidden): every proposed entry is
booked as debit <classified expense account> / credit a fixed "Operating
Cash" account (GL code 1000). Real documents may have been paid by credit
card, on account (A/P), or not yet paid at all — determining the correct
credit side in general is Reconciliation & Close Agent territory (not yet
built) and is flagged as follow-up work, not silently assumed correct.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.intake_bookkeeper.tools import (
    DocumentTextExtractionError,
    build_document_content_blocks,
    classify_transaction,
    extract_document_data,
    flag_exception,
    log_audit_event,
    log_tool_invocation,
    resolve_gl_account,
    utcnow,
)
from app.models.accounting_period import AccountingPeriod, GLAccount
from app.models.document import ExtractedDocumentData, SourceDocument
from app.models.enums import (
    ActorType,
    AgentType,
    CloseStatus,
    DocumentType,
    EntryStatus,
    ExceptionSeverity,
    ExceptionType,
    UserRole,
    WorkflowRunStatus,
)
from app.models.exception_record import ExceptionRecord
from app.models.journal_entry import JournalEntryLine, ProposedJournalEntry
from app.models.workflow import WorkflowRun
from app.services.accounting.close_state_machine import assert_close_transition_allowed
from app.services.accounting.entry_state_machine import assert_transition_allowed
from app.services.accounting.validation import (
    AccountingValidationError,
    validate_debit_equals_credit,
    validate_gl_accounts_exist,
)
CONFIDENCE_THRESHOLD = 0.75
DEFAULT_CASH_ACCOUNT_CODE = "1000"


@dataclass
class IntakeRunResult:
    workflow_run: WorkflowRun
    source_document: SourceDocument
    entry: ProposedJournalEntry | None = None
    exceptions: list[ExceptionRecord] = field(default_factory=list)


def _content_hash(*, raw_text: str | None, file_bytes: bytes | None) -> str:
    payload = raw_text.encode("utf-8") if raw_text is not None else file_bytes
    return hashlib.sha256(payload).hexdigest()


def _parse_document_date(document_date: str | None) -> date | None:
    """Best-effort ISO-8601 date parse of Claude's extracted document_date.
    Returns None (not today's date) on anything unparseable — callers fall
    back to created_at.date(), which is a more honest "we don't know"
    signal than silently substituting today's date."""
    if not document_date:
        return None
    try:
        return date.fromisoformat(document_date.strip())
    except (ValueError, AttributeError):
        return None


def _advance_period_to_processing(db: Session, *, period_id: UUID) -> None:
    """Bumps AccountingPeriod.close_status forward to PROCESSING the first
    time a document is handled for a period — not_started ->
    collecting_documents -> processing, both AI_INTAKE-only transitions.
    A no-op once the period is already past PROCESSING (e.g. a later
    document arriving mid-reconciliation shouldn't rewind the close)."""
    period = db.get(AccountingPeriod, period_id)
    if period.close_status == CloseStatus.NOT_STARTED:
        assert_close_transition_allowed(
            from_status=CloseStatus.NOT_STARTED,
            to_status=CloseStatus.COLLECTING_DOCUMENTS,
            actor_role=UserRole.AI_INTAKE,
        )
        period.close_status = CloseStatus.COLLECTING_DOCUMENTS
        db.flush()
    if period.close_status == CloseStatus.COLLECTING_DOCUMENTS:
        assert_close_transition_allowed(
            from_status=CloseStatus.COLLECTING_DOCUMENTS,
            to_status=CloseStatus.PROCESSING,
            actor_role=UserRole.AI_INTAKE,
        )
        period.close_status = CloseStatus.PROCESSING
        db.flush()


def run_intake_pipeline(
    db: Session,
    *,
    client_id: UUID,
    period_id: UUID,
    uploaded_by: UUID,
    doc_type: DocumentType,
    original_filename: str,
    mime_type: str,
    raw_text: str | None = None,
    file_bytes: bytes | None = None,
) -> IntakeRunResult:
    _advance_period_to_processing(db, period_id=period_id)

    content_hash = _content_hash(raw_text=raw_text, file_bytes=file_bytes)

    duplicate = db.scalar(
        select(SourceDocument).where(
            SourceDocument.client_id == client_id, SourceDocument.content_hash == content_hash
        )
    )

    source_document = SourceDocument(
        client_id=client_id,
        uploaded_by=uploaded_by,
        doc_type=doc_type,
        file_ref=f"dev-local://{content_hash}",
        original_filename=original_filename,
        mime_type=mime_type,
        content_hash=content_hash,
        uploaded_at=utcnow(),
    )
    db.add(source_document)
    db.flush()

    log_audit_event(
        db,
        client_id=client_id,
        event_type="document.uploaded",
        actor_id=uploaded_by,
        actor_type=ActorType.AI_SERVICE,
        entity_type="source_document",
        entity_id=source_document.id,
        after={"content_hash": content_hash, "doc_type": doc_type.value},
    )

    workflow_run = WorkflowRun(
        client_id=client_id,
        agent_type=AgentType.INTAKE_BOOKKEEPER,
        trigger=f"document_uploaded:{source_document.id}",
        status=WorkflowRunStatus.RUNNING,
        started_at=utcnow(),
    )
    db.add(workflow_run)
    db.flush()

    result = IntakeRunResult(workflow_run=workflow_run, source_document=source_document)

    if duplicate is not None:
        exc = flag_exception(
            db,
            client_id=client_id,
            period_id=period_id,
            related_entry_id=None,
            exception_type=ExceptionType.DUPLICATE_INVOICE,
            severity=ExceptionSeverity.MEDIUM,
            description=(
                f"Document content matches a previously uploaded document "
                f"({duplicate.id}, uploaded {duplicate.uploaded_at.isoformat()})."
            ),
            detected_by="rule:content_hash_match",
        )
        result.exceptions.append(exc)
        workflow_run.status = WorkflowRunStatus.COMPLETED
        workflow_run.ended_at = utcnow()
        db.commit()
        return result

    def _fail(message: str, exception_type: ExceptionType | None = None) -> IntakeRunResult:
        workflow_run.status = WorkflowRunStatus.FAILED
        workflow_run.ended_at = utcnow()
        workflow_run.error_message = message[:2048]
        if exception_type is not None:
            exc = flag_exception(
                db,
                client_id=client_id,
                period_id=period_id,
                related_entry_id=None,
                exception_type=exception_type,
                severity=ExceptionSeverity.MEDIUM,
                description=message,
                detected_by=AgentType.INTAKE_BOOKKEEPER.value,
            )
            result.exceptions.append(exc)
        db.commit()
        return result

    # --- Step 1: extract structured fields ---
    try:
        content_blocks = build_document_content_blocks(
            raw_text=raw_text, file_bytes=file_bytes, mime_type=mime_type
        )
    except DocumentTextExtractionError as exc:
        return _fail(f"Could not read document content: {exc}", ExceptionType.UNREADABLE_DOCUMENT)

    try:
        extracted, invocation_meta = extract_document_data(content_blocks)
    except Exception as exc:  # ClaudeSkillError or a Pydantic validation error — both are handled the same: fail the run, flag an exception, no partial state persisted.
        return _fail(f"Document extraction failed: {exc}", ExceptionType.UNREADABLE_DOCUMENT)

    log_tool_invocation(
        db,
        workflow_run_id=workflow_run.id,
        tool_name=invocation_meta["tool_name"],
        input_json={"mime_type": mime_type, "original_filename": original_filename},
        output_json=invocation_meta["output_json"],
        model=invocation_meta["model"],
        skill_version=invocation_meta["skill_version"],
        duration_ms=invocation_meta["duration_ms"],
    )
    db.add(
        ExtractedDocumentData(
            source_document_id=source_document.id,
            fields=extracted.model_dump(),
            confidence=1.0,  # extraction has no separate confidence field in this schema version
            skill_name=invocation_meta["tool_name"],
            skill_version=invocation_meta["skill_version"],
            model=invocation_meta["model"],
            extracted_at=utcnow(),
        )
    )

    # --- Step 2: classify against this client's actual chart of accounts ---
    chart_of_accounts = list(db.scalars(select(GLAccount).where(GLAccount.client_id == client_id)))
    if not chart_of_accounts:
        return _fail(f"Client {client_id} has no chart of accounts configured.")

    try:
        classification, classify_meta = classify_transaction(
            description=extracted.description, chart_of_accounts=chart_of_accounts
        )
    except Exception as exc:
        return _fail(
            f"Transaction classification failed: {exc}", ExceptionType.LOW_CONFIDENCE_CLASSIFICATION
        )

    log_tool_invocation(
        db,
        workflow_run_id=workflow_run.id,
        tool_name=classify_meta["tool_name"],
        input_json={"description": extracted.description},
        output_json=classify_meta["output_json"],
        model=classify_meta["model"],
        skill_version=classify_meta["skill_version"],
        duration_ms=classify_meta["duration_ms"],
    )

    expense_account = resolve_gl_account(db, client_id=client_id, code=classification.gl_account_code)
    if expense_account is None:
        return _fail(
            f"Claude chose GL account code '{classification.gl_account_code}', which does not "
            f"exist in this client's chart of accounts.",
            ExceptionType.LOW_CONFIDENCE_CLASSIFICATION,
        )

    cash_account = resolve_gl_account(db, client_id=client_id, code=DEFAULT_CASH_ACCOUNT_CODE)
    if cash_account is None:
        return _fail(
            f"Client {client_id} has no default cash account (GL code {DEFAULT_CASH_ACCOUNT_CODE})."
        )

    # --- Step 3: deterministic validation, never trust the model's arithmetic ---
    line_inputs = [
        {"debit": extracted.amount, "credit": 0},
        {"debit": 0, "credit": extracted.amount},
    ]
    try:
        validate_debit_equals_credit(line_inputs)
        validate_gl_accounts_exist(
            db, client_id=client_id, gl_account_ids=[expense_account.id, cash_account.id]
        )
    except AccountingValidationError as exc:
        return _fail(f"Proposed entry failed deterministic validation: {exc}")

    # --- Step 4: propose the entry, directly in pending_review ---
    assert_transition_allowed(
        from_status=EntryStatus.DRAFT, to_status=EntryStatus.PENDING_REVIEW, actor_role=UserRole.AI_INTAKE
    )

    entry = ProposedJournalEntry(
        client_id=client_id,
        period_id=period_id,
        status=EntryStatus.PENDING_REVIEW,
        description=extracted.description,
        confidence=classification.confidence,
        entry_date=_parse_document_date(extracted.document_date),
        source_document_id=source_document.id,
        created_by_user_id=uploaded_by,
    )
    db.add(entry)
    db.flush()

    db.add(
        JournalEntryLine(
            entry_id=entry.id, gl_account_id=expense_account.id, debit=extracted.amount, credit=0
        )
    )
    db.add(
        JournalEntryLine(
            entry_id=entry.id, gl_account_id=cash_account.id, debit=0, credit=extracted.amount
        )
    )
    db.flush()
    result.entry = entry

    log_audit_event(
        db,
        client_id=client_id,
        event_type="entry.proposed",
        actor_id=uploaded_by,
        actor_type=ActorType.AI_SERVICE,
        entity_type="proposed_journal_entry",
        entity_id=entry.id,
        after={
            "status": entry.status.value,
            "confidence": entry.confidence,
            "gl_account_code": expense_account.code,
            "amount": extracted.amount,
        },
    )

    if classification.confidence < CONFIDENCE_THRESHOLD:
        exc = flag_exception(
            db,
            client_id=client_id,
            period_id=period_id,
            related_entry_id=entry.id,
            exception_type=ExceptionType.LOW_CONFIDENCE_CLASSIFICATION,
            severity=ExceptionSeverity.LOW,
            description=(
                f"Classification confidence {classification.confidence:.2f} is below the "
                f"{CONFIDENCE_THRESHOLD:.2f} threshold. Rationale: {classification.rationale}"
            ),
            detected_by=AgentType.INTAKE_BOOKKEEPER.value,
        )
        result.exceptions.append(exc)

    workflow_run.status = WorkflowRunStatus.COMPLETED
    workflow_run.ended_at = utcnow()
    db.commit()
    return result
