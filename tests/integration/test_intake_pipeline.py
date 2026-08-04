"""
Integration tests for the Intake Bookkeeper pipeline: document -> proposed
entry, run against the real database through the real ai_service Postgres
role, with only the Claude API calls mocked — per
DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 14.2 ("Document intake to
proposed entry (full pipeline, mocked Claude)").
"""

from unittest.mock import patch

import pytest

from app.agents.intake_bookkeeper.agent import run_intake_pipeline
from app.models.enums import DocumentType, EntryStatus, WorkflowRunStatus
from app.services.claude_client import ClaudeSkillResult


def _extraction_result(**overrides) -> ClaudeSkillResult:
    data = {
        "vendor": "Notion Labs",
        "amount": 24.00,
        "currency": "USD",
        "document_date": "2026-07-03",
        "description": "Notion software subscription for July 2026",
        "doc_type_guess": "receipt",
    }
    data.update(overrides)
    return ClaudeSkillResult(
        data=data,
        raw_text="{}",
        model="claude-sonnet-4-6",
        skill_name="intake_bookkeeper.extract_document_data",
        skill_version="v1",
        duration_ms=100,
    )


def _classification_result(**overrides) -> ClaudeSkillResult:
    data = {"gl_account_code": "6100", "confidence": 0.93, "rationale": "SaaS subscription."}
    data.update(overrides)
    return ClaudeSkillResult(
        data=data,
        raw_text="{}",
        model="claude-sonnet-4-6",
        skill_name="intake_bookkeeper.classify_transaction",
        skill_version="v1",
        duration_ms=80,
    )


@pytest.fixture
def mocked_claude():
    with patch("app.agents.intake_bookkeeper.tools.get_extraction_client") as mock_extract, patch(
        "app.agents.intake_bookkeeper.tools.get_classification_client"
    ) as mock_classify:
        yield mock_extract, mock_classify


def _run(ai_db, seeded_client, raw_text="Notion receipt, $24.00, dated 2026-07-03"):
    return run_intake_pipeline(
        ai_db,
        client_id=seeded_client["client"].id,
        period_id=seeded_client["period"].id,
        uploaded_by=seeded_client["intake_user"].id,
        doc_type=DocumentType.RECEIPT,
        original_filename="receipt.txt",
        mime_type="text/plain",
        raw_text=raw_text,
    )


def test_happy_path_creates_pending_review_entry_with_evidence(mocked_claude, ai_db, seeded_client):
    mock_extract, mock_classify = mocked_claude
    mock_extract.return_value.call.return_value = _extraction_result()
    mock_classify.return_value.call.return_value = _classification_result()

    result = _run(ai_db, seeded_client)

    assert result.workflow_run.status == WorkflowRunStatus.COMPLETED
    assert result.entry is not None
    assert result.entry.status == EntryStatus.PENDING_REVIEW
    assert result.entry.confidence == pytest.approx(0.93)
    assert result.entry.source_document_id == result.source_document.id
    assert result.exceptions == []


def test_entry_lines_balance_and_reference_correct_accounts(mocked_claude, ai_db, seeded_client):
    from sqlalchemy import select

    from app.models.journal_entry import JournalEntryLine

    mock_extract, mock_classify = mocked_claude
    mock_extract.return_value.call.return_value = _extraction_result(amount=42.50)
    mock_classify.return_value.call.return_value = _classification_result()

    result = _run(ai_db, seeded_client)

    lines = ai_db.scalars(
        select(JournalEntryLine).where(JournalEntryLine.entry_id == result.entry.id)
    ).all()
    assert len(lines) == 2
    total_debit = sum(float(line.debit) for line in lines)
    total_credit = sum(float(line.credit) for line in lines)
    assert total_debit == total_credit == 42.50

    expense_account_id = seeded_client["gl_accounts"]["6100"].id
    cash_account_id = seeded_client["gl_accounts"]["1000"].id
    account_ids = {line.gl_account_id for line in lines}
    assert account_ids == {expense_account_id, cash_account_id}


def test_low_confidence_flags_exception_but_still_creates_entry(mocked_claude, ai_db, seeded_client):
    from app.models.enums import ExceptionType

    mock_extract, mock_classify = mocked_claude
    mock_extract.return_value.call.return_value = _extraction_result()
    mock_classify.return_value.call.return_value = _classification_result(confidence=0.4)

    result = _run(ai_db, seeded_client)

    assert result.entry is not None
    assert result.entry.status == EntryStatus.PENDING_REVIEW
    assert len(result.exceptions) == 1
    assert result.exceptions[0].type == ExceptionType.LOW_CONFIDENCE_CLASSIFICATION


def test_duplicate_document_is_flagged_and_no_second_entry_created(mocked_claude, ai_db, seeded_client):
    from app.models.enums import ExceptionType

    mock_extract, mock_classify = mocked_claude
    mock_extract.return_value.call.return_value = _extraction_result()
    mock_classify.return_value.call.return_value = _classification_result()

    first = _run(ai_db, seeded_client, raw_text="identical content")
    assert first.entry is not None

    second = _run(ai_db, seeded_client, raw_text="identical content")
    assert second.entry is None
    assert len(second.exceptions) == 1
    assert second.exceptions[0].type == ExceptionType.DUPLICATE_INVOICE


def test_unknown_gl_account_code_fails_without_creating_a_broken_entry(
    mocked_claude, ai_db, seeded_client
):
    mock_extract, mock_classify = mocked_claude
    mock_extract.return_value.call.return_value = _extraction_result()
    mock_classify.return_value.call.return_value = _classification_result(gl_account_code="9999-NOT-REAL")

    result = _run(ai_db, seeded_client)

    assert result.entry is None
    assert result.workflow_run.status == WorkflowRunStatus.FAILED
    assert "does not exist" in result.workflow_run.error_message


def test_unreadable_document_flags_exception(mocked_claude, ai_db, seeded_client):
    from app.models.enums import ExceptionType

    result = run_intake_pipeline(
        ai_db,
        client_id=seeded_client["client"].id,
        period_id=seeded_client["period"].id,
        uploaded_by=seeded_client["intake_user"].id,
        doc_type=DocumentType.RECEIPT,
        original_filename="corrupt.pdf",
        mime_type="application/pdf",
        file_bytes=b"not a real pdf",
    )

    assert result.entry is None
    assert result.workflow_run.status == WorkflowRunStatus.FAILED
    assert result.exceptions[0].type == ExceptionType.UNREADABLE_DOCUMENT


def test_claude_api_failure_degrades_gracefully(mocked_claude, ai_db, seeded_client):
    from app.services.claude_client import ClaudeSkillError

    mock_extract, _mock_classify = mocked_claude
    mock_extract.return_value.call.side_effect = ClaudeSkillError("Claude API request timed out.")

    result = _run(ai_db, seeded_client)

    assert result.entry is None
    assert result.workflow_run.status == WorkflowRunStatus.FAILED
    assert result.exceptions[0].description.startswith("Document extraction failed")


def test_audit_trail_is_recorded_for_a_successful_run(mocked_claude, ai_db, seeded_client):
    from sqlalchemy import select

    from app.models.audit_event import AuditEvent
    from app.models.workflow import ToolInvocation

    mock_extract, mock_classify = mocked_claude
    mock_extract.return_value.call.return_value = _extraction_result()
    mock_classify.return_value.call.return_value = _classification_result()

    result = _run(ai_db, seeded_client)

    events = ai_db.scalars(
        select(AuditEvent).where(AuditEvent.client_id == seeded_client["client"].id)
    ).all()
    event_types = {e.event_type for e in events}
    assert "document.uploaded" in event_types
    assert "entry.proposed" in event_types

    invocations = ai_db.scalars(
        select(ToolInvocation).where(ToolInvocation.workflow_run_id == result.workflow_run.id)
    ).all()
    tool_names = {i.tool_name for i in invocations}
    assert tool_names == {"extract_document_data", "classify_transaction"}
    for invocation in invocations:
        assert invocation.skill_version == "v1"
        assert invocation.model == "claude-sonnet-4-6"
