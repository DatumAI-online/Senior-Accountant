"""
Section 10.2, test #1: prove — at the database level, bypassing the FastAPI
app entirely — that no credential authenticated as datumai_ai_service can
ever write an approved/rejected/posted/reversed status or create a
ReviewDecision, and that DELETE is unavailable to either application role
on any table. This is the load-bearing test in the whole test suite: if it
ever goes red, the core control principle
("the AI may prepare work but never approve its own work") is broken at
the database, not just in application code.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from app.core.config import get_settings


def _connect(url: str):
    engine = create_engine(url)
    conn = engine.connect()
    return engine, conn


@pytest.fixture
def seeded_entry(seeded_client, admin_db):
    """Insert one pending_review entry directly via the admin connection,
    independent of application code, so these tests exercise ONLY the
    database grants/trigger, not app/services/accounting logic."""
    from app.models.enums import EntryStatus
    from app.models.journal_entry import ProposedJournalEntry

    entry = ProposedJournalEntry(
        client_id=seeded_client["client"].id,
        period_id=seeded_client["period"].id,
        status=EntryStatus.PENDING_REVIEW,
        description="Security test entry",
        created_by_user_id=seeded_client["intake_user"].id,
    )
    admin_db.add(entry)
    admin_db.commit()
    return entry


def test_ai_service_cannot_approve_entry(seeded_entry):
    settings = get_settings()
    engine, conn = _connect(settings.ai_service_database_url)
    try:
        with pytest.raises(ProgrammingError, match="datumai_ai_service may not set"):
            conn.execute(
                text("UPDATE proposed_journal_entries SET status = 'approved' WHERE id = :id"),
                {"id": seeded_entry.id},
            )
    finally:
        conn.rollback()
        conn.close()
        engine.dispose()


@pytest.mark.parametrize("target_status", ["approved", "rejected", "posted", "reversed"])
def test_ai_service_cannot_reach_any_terminal_status(seeded_entry, target_status):
    settings = get_settings()
    engine, conn = _connect(settings.ai_service_database_url)
    try:
        with pytest.raises(ProgrammingError, match="datumai_ai_service may not set"):
            conn.execute(
                text("UPDATE proposed_journal_entries SET status = :s WHERE id = :id"),
                {"s": target_status, "id": seeded_entry.id},
            )
    finally:
        conn.rollback()
        conn.close()
        engine.dispose()


def test_ai_service_cannot_insert_review_decision(seeded_entry, seeded_client):
    settings = get_settings()
    engine, conn = _connect(settings.ai_service_database_url)
    try:
        with pytest.raises(ProgrammingError, match="permission denied for table review_decisions"):
            conn.execute(
                text(
                    "INSERT INTO review_decisions "
                    "(id, entry_id, cpa_user_id, decision, rationale, mfa_verified, decided_at) "
                    "VALUES (:id, :entry_id, :cpa_id, 'approved', 'self-approved', false, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "entry_id": seeded_entry.id,
                    "cpa_id": seeded_client["cpa_user"].id,
                    "now": datetime.now(timezone.utc),
                },
            )
    finally:
        conn.rollback()
        conn.close()
        engine.dispose()


@pytest.mark.parametrize(
    "table",
    [
        "proposed_journal_entries",
        "journal_entry_lines",
        "review_decisions",
        "audit_events",
        "source_documents",
        "clients",
        "users",
    ],
)
def test_ai_service_has_no_delete_grant_anywhere(table):
    settings = get_settings()
    engine, conn = _connect(settings.ai_service_database_url)
    try:
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text(f"DELETE FROM {table} WHERE 1=0"))
    finally:
        conn.rollback()
        conn.close()
        engine.dispose()


@pytest.mark.parametrize(
    "table",
    [
        "proposed_journal_entries",
        "journal_entry_lines",
        "review_decisions",
        "audit_events",
        "source_documents",
        "clients",
        "users",
    ],
)
def test_cpa_service_has_no_delete_grant_anywhere(table):
    settings = get_settings()
    engine, conn = _connect(settings.cpa_service_database_url)
    try:
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text(f"DELETE FROM {table} WHERE 1=0"))
    finally:
        conn.rollback()
        conn.close()
        engine.dispose()


def test_cpa_service_can_approve_and_record_decision(seeded_entry, seeded_client):
    settings = get_settings()
    engine, conn = _connect(settings.cpa_service_database_url)
    try:
        conn.execute(
            text("UPDATE proposed_journal_entries SET status = 'approved' WHERE id = :id"),
            {"id": seeded_entry.id},
        )
        conn.execute(
            text(
                "INSERT INTO review_decisions "
                "(id, entry_id, cpa_user_id, decision, rationale, mfa_verified, decided_at) "
                "VALUES (:id, :entry_id, :cpa_id, 'approved', 'Evidence checked.', false, :now)"
            ),
            {
                "id": uuid.uuid4(),
                "entry_id": seeded_entry.id,
                "cpa_id": seeded_client["cpa_user"].id,
                "now": datetime.now(timezone.utc),
            },
        )
        conn.commit()

        status = conn.execute(
            text("SELECT status FROM proposed_journal_entries WHERE id = :id"), {"id": seeded_entry.id}
        ).scalar_one()
        assert status == "approved"
    finally:
        conn.close()
        engine.dispose()


def test_review_decisions_are_append_only_even_for_cpa_service(seeded_entry, seeded_client):
    settings = get_settings()
    engine, conn = _connect(settings.cpa_service_database_url)
    decision_id = uuid.uuid4()
    try:
        conn.execute(
            text(
                "INSERT INTO review_decisions "
                "(id, entry_id, cpa_user_id, decision, rationale, mfa_verified, decided_at) "
                "VALUES (:id, :entry_id, :cpa_id, 'approved', 'Original rationale.', false, :now)"
            ),
            {
                "id": decision_id,
                "entry_id": seeded_entry.id,
                "cpa_id": seeded_client["cpa_user"].id,
                "now": datetime.now(timezone.utc),
            },
        )
        conn.commit()

        with pytest.raises(ProgrammingError, match="permission denied for table review_decisions"):
            conn.execute(
                text("UPDATE review_decisions SET rationale = 'changed my mind' WHERE id = :id"),
                {"id": decision_id},
            )
    finally:
        conn.rollback()
        conn.close()
        engine.dispose()


def test_review_decisions_are_append_only_even_for_admin(seeded_entry, seeded_client, admin_db):
    """The append-only trigger blocks UPDATE/DELETE regardless of role —
    not just the two limited application roles."""
    from sqlalchemy.exc import InternalError

    from app.models.enums import ReviewDecisionType
    from app.models.review_decision import ReviewDecision

    decision = ReviewDecision(
        entry_id=seeded_entry.id,
        cpa_user_id=seeded_client["cpa_user"].id,
        decision=ReviewDecisionType.APPROVED,
        rationale="Original.",
        decided_at=datetime.now(timezone.utc),
    )
    admin_db.add(decision)
    admin_db.commit()

    with pytest.raises((ProgrammingError, InternalError), match="append-only"):
        admin_db.execute(text("DELETE FROM review_decisions WHERE id = :id"), {"id": decision.id})
    admin_db.rollback()


def test_ai_service_can_perform_its_own_allowed_transition(seeded_entry):
    """Sanity check the negative tests above aren't just a mis-set DSN: the
    AI role legitimately CAN write a non-terminal status."""
    settings = get_settings()
    engine, conn = _connect(settings.ai_service_database_url)
    try:
        conn.execute(
            text(
                "UPDATE proposed_journal_entries SET status = 'needs_client_information' "
                "WHERE id = :id"
            ),
            {"id": seeded_entry.id},
        )
        conn.commit()
        status = conn.execute(
            text("SELECT status FROM proposed_journal_entries WHERE id = :id"), {"id": seeded_entry.id}
        ).scalar_one()
        assert status == "needs_client_information"
    finally:
        conn.close()
        engine.dispose()


@pytest.mark.parametrize("target_close_status", ["approved", "delivered"])
def test_ai_service_cannot_write_terminal_close_status(seeded_client, target_close_status):
    settings = get_settings()
    engine, conn = _connect(settings.ai_service_database_url)
    try:
        with pytest.raises(ProgrammingError, match="datumai_ai_service may not set"):
            conn.execute(
                text("UPDATE accounting_periods SET close_status = :s WHERE id = :id"),
                {"s": target_close_status, "id": seeded_client["period"].id},
            )
    finally:
        conn.rollback()
        conn.close()
        engine.dispose()


def test_ai_service_can_write_non_terminal_close_status(seeded_client):
    settings = get_settings()
    engine, conn = _connect(settings.ai_service_database_url)
    try:
        conn.execute(
            text("UPDATE accounting_periods SET close_status = 'reconciling' WHERE id = :id"),
            {"id": seeded_client["period"].id},
        )
        conn.commit()
        status = conn.execute(
            text("SELECT close_status FROM accounting_periods WHERE id = :id"),
            {"id": seeded_client["period"].id},
        ).scalar_one()
        assert status == "reconciling"
    finally:
        conn.close()
        engine.dispose()


def test_cpa_service_can_approve_close(seeded_client):
    settings = get_settings()
    engine, conn = _connect(settings.cpa_service_database_url)
    try:
        conn.execute(
            text("UPDATE accounting_periods SET close_status = 'approved' WHERE id = :id"),
            {"id": seeded_client["period"].id},
        )
        conn.commit()
        status = conn.execute(
            text("SELECT close_status FROM accounting_periods WHERE id = :id"),
            {"id": seeded_client["period"].id},
        ).scalar_one()
        assert status == "approved"
    finally:
        conn.close()
        engine.dispose()


@pytest.fixture
def seeded_financial_report(seeded_client, admin_db):
    from app.models.enums import FinancialReportType
    from app.models.reporting import FinancialReport

    report = FinancialReport(
        client_id=seeded_client["client"].id,
        period_id=seeded_client["period"].id,
        report_type=FinancialReportType.INCOME_STATEMENT,
        data={"net_income": 100.0},
        generated_by="reporting_insights",
    )
    admin_db.add(report)
    admin_db.commit()
    return report


def test_ai_service_has_no_update_grant_on_financial_reports(seeded_financial_report):
    """No column-level nuance needed here — the AI service role simply has
    no UPDATE grant on this table at all (0004_reconciliation_reporting_
    grants.py), so it structurally cannot set approved_by."""
    settings = get_settings()
    engine, conn = _connect(settings.ai_service_database_url)
    try:
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(
                text("UPDATE financial_reports SET approved_by = NULL WHERE id = :id"),
                {"id": seeded_financial_report.id},
            )
    finally:
        conn.rollback()
        conn.close()
        engine.dispose()


def test_cpa_service_can_update_financial_reports(seeded_financial_report, seeded_client):
    settings = get_settings()
    engine, conn = _connect(settings.cpa_service_database_url)
    try:
        conn.execute(
            text("UPDATE financial_reports SET approved_by = :cpa_id WHERE id = :id"),
            {"cpa_id": seeded_client["cpa_user"].id, "id": seeded_financial_report.id},
        )
        conn.commit()
    finally:
        conn.close()
        engine.dispose()
