"""Integration tests for the Reporting & Insights Agent's deterministic
aggregation — the actual arithmetic must be exactly right, and must never
include anything but APPROVED/POSTED entries."""

from uuid import uuid4

from app.agents.reporting_insights.tools import generate_balance_sheet, generate_income_statement
from app.models.enums import EntryStatus
from app.models.journal_entry import JournalEntryLine, ProposedJournalEntry


def _make_entry(admin_db, seeded_client, *, status: EntryStatus, gl_code: str, debit: float, credit: float):
    entry = ProposedJournalEntry(
        client_id=seeded_client["client"].id,
        period_id=seeded_client["period"].id,
        status=status,
        description=f"test entry {uuid4()}",
        created_by_user_id=seeded_client["intake_user"].id,
    )
    admin_db.add(entry)
    admin_db.flush()
    admin_db.add(
        JournalEntryLine(
            entry_id=entry.id,
            gl_account_id=seeded_client["gl_accounts"][gl_code].id,
            debit=debit,
            credit=credit,
        )
    )
    admin_db.flush()
    return entry


def test_income_statement_only_includes_approved_and_posted(admin_db, seeded_client):
    # Approved: $1000 revenue (credit)
    _make_entry(admin_db, seeded_client, status=EntryStatus.APPROVED, gl_code="4000", debit=0, credit=1000)
    # Posted: $200 expense (debit)
    _make_entry(admin_db, seeded_client, status=EntryStatus.POSTED, gl_code="6100", debit=200, credit=0)
    # Pending review: should NOT be included
    _make_entry(admin_db, seeded_client, status=EntryStatus.PENDING_REVIEW, gl_code="6300", debit=5000, credit=0)
    # Rejected: should NOT be included
    _make_entry(admin_db, seeded_client, status=EntryStatus.REJECTED, gl_code="6100", debit=9999, credit=0)
    admin_db.commit()

    statement = generate_income_statement(
        admin_db, client_id=seeded_client["client"].id, period_id=seeded_client["period"].id
    )

    assert statement["total_revenue"] == 1000.0
    assert statement["total_expenses"] == 200.0
    assert statement["net_income"] == 800.0
    # The pending/rejected entries' huge amounts must not leak in anywhere.
    assert statement["total_expenses"] != 5000.0
    assert statement["total_expenses"] != 5199.0


def test_balance_sheet_asset_and_equity_signs(admin_db, seeded_client):
    # Cash increases with a debit (asset).
    _make_entry(admin_db, seeded_client, status=EntryStatus.APPROVED, gl_code="1000", debit=500, credit=0)
    admin_db.commit()

    balance_sheet = generate_balance_sheet(
        admin_db, client_id=seeded_client["client"].id, period_id=seeded_client["period"].id
    )
    assert balance_sheet["assets"]["Operating Cash"] == 500.0
    assert balance_sheet["total_assets"] == 500.0
