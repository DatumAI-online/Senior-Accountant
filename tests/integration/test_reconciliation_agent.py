"""Integration tests for the Reconciliation & Close Agent in isolation
(not through the full demo loop) — unmatched transactions, discrepancies,
and the close checklist's blocking-item reporting."""

from datetime import date

from app.agents.reconciliation_close.agent import run_reconciliation_and_close
from app.agents.reconciliation_close.tools import import_transactions, run_close_checklist
from app.models.enums import CloseStatus, ExceptionType, ReconciliationStatus


def test_checklist_blocks_when_account_has_no_reconciliation(ai_db, seeded_client):
    result = run_close_checklist(ai_db, period_id=seeded_client["period"].id)
    assert result["ready"] is False
    assert any("not yet reconciled" in item for item in result["blocking_items"])


def test_unmatched_transaction_flags_exception(ai_db, admin_db, seeded_client):
    from app.models.accounting_period import AccountingPeriod

    period = admin_db.get(AccountingPeriod, seeded_client["period"].id)
    period.close_status = CloseStatus.PROCESSING
    admin_db.commit()

    fa = seeded_client["financial_account"]
    import_transactions(
        ai_db,
        financial_account_id=fa.id,
        rows=[{"date": date(2026, 7, 5), "amount": -500.00, "description": "UNKNOWN WIRE", "reference": None}],
    )
    ai_db.commit()

    result = run_reconciliation_and_close(
        ai_db,
        client_id=seeded_client["client"].id,
        period_id=seeded_client["period"].id,
        actor_user_id=seeded_client["reconciliation_user"].id,
    )

    assert result.reconciliations[0].status == ReconciliationStatus.DISCREPANCY
    assert any(e.type == ExceptionType.UNMATCHED_TRANSACTION for e in result.exceptions)
    assert result.checklist["ready"] is False
    assert result.close_status.value != "ready_for_cpa_review"


def test_reconciliation_with_no_transactions_at_all_is_reconciled(ai_db, admin_db, seeded_client):
    """No imported transactions and no GL activity nets to a zero
    difference — a legitimately reconciled (if uneventful) account."""
    from app.models.accounting_period import AccountingPeriod

    period = admin_db.get(AccountingPeriod, seeded_client["period"].id)
    period.close_status = CloseStatus.PROCESSING
    admin_db.commit()

    result = run_reconciliation_and_close(
        ai_db,
        client_id=seeded_client["client"].id,
        period_id=seeded_client["period"].id,
        actor_user_id=seeded_client["reconciliation_user"].id,
    )
    assert result.reconciliations[0].status == ReconciliationStatus.RECONCILED
    assert result.checklist["ready"] is True
    assert result.close_status == CloseStatus.READY_FOR_CPA_REVIEW
