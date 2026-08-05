"""
The Reporting & Insights Agent's tools. Every aggregation is a plain SQL
query filtered to APPROVED/POSTED entries only — that filter lives in the
query itself, not in a prompt instruction, so there is no way for a model
to "decide" to include unapproved data. Only the narrative drafting call
touches Claude, and it is only ever given numbers this module already
computed — it never computes its own.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accounting_period import GLAccount
from app.models.enums import EntryStatus, GLAccountType
from app.models.journal_entry import JournalEntryLine, ProposedJournalEntry

# The only two statuses that represent CPA-approved accounting data.
REPORTABLE_STATUSES = {EntryStatus.APPROVED, EntryStatus.POSTED}


def _approved_lines(db: Session, *, client_id: UUID, period_id: UUID) -> list[tuple]:
    return list(
        db.execute(
            select(JournalEntryLine, GLAccount)
            .join(ProposedJournalEntry, ProposedJournalEntry.id == JournalEntryLine.entry_id)
            .join(GLAccount, GLAccount.id == JournalEntryLine.gl_account_id)
            .where(
                ProposedJournalEntry.client_id == client_id,
                ProposedJournalEntry.period_id == period_id,
                ProposedJournalEntry.status.in_(REPORTABLE_STATUSES),
            )
        ).all()
    )


def generate_income_statement(db: Session, *, client_id: UUID, period_id: UUID) -> dict:
    lines = _approved_lines(db, client_id=client_id, period_id=period_id)
    revenue: dict[str, Decimal] = {}
    expenses: dict[str, Decimal] = {}

    for line, account in lines:
        net = Decimal(str(line.credit)) - Decimal(str(line.debit))
        if account.account_type == GLAccountType.REVENUE:
            revenue[account.name] = revenue.get(account.name, Decimal("0")) + net
        elif account.account_type == GLAccountType.EXPENSE:
            expenses[account.name] = expenses.get(account.name, Decimal("0")) + (-net)

    total_revenue = sum(revenue.values(), Decimal("0"))
    total_expenses = sum(expenses.values(), Decimal("0"))
    return {
        "revenue": {k: float(v) for k, v in revenue.items()},
        "total_revenue": float(total_revenue),
        "expenses": {k: float(v) for k, v in expenses.items()},
        "total_expenses": float(total_expenses),
        "net_income": float(total_revenue - total_expenses),
    }


def generate_balance_sheet(db: Session, *, client_id: UUID, period_id: UUID) -> dict:
    lines = _approved_lines(db, client_id=client_id, period_id=period_id)
    assets: dict[str, Decimal] = {}
    liabilities: dict[str, Decimal] = {}
    equity: dict[str, Decimal] = {}

    for line, account in lines:
        net_debit = Decimal(str(line.debit)) - Decimal(str(line.credit))
        if account.account_type == GLAccountType.ASSET:
            assets[account.name] = assets.get(account.name, Decimal("0")) + net_debit
        elif account.account_type == GLAccountType.LIABILITY:
            liabilities[account.name] = liabilities.get(account.name, Decimal("0")) + (-net_debit)
        elif account.account_type == GLAccountType.EQUITY:
            equity[account.name] = equity.get(account.name, Decimal("0")) + (-net_debit)

    total_assets = sum(assets.values(), Decimal("0"))
    total_liabilities = sum(liabilities.values(), Decimal("0"))
    total_equity = sum(equity.values(), Decimal("0"))
    return {
        "assets": {k: float(v) for k, v in assets.items()},
        "total_assets": float(total_assets),
        "liabilities": {k: float(v) for k, v in liabilities.items()},
        "total_liabilities": float(total_liabilities),
        "equity": {k: float(v) for k, v in equity.items()},
        "total_equity": float(total_equity),
    }


def generate_cash_summary(db: Session, *, client_id: UUID, period_id: UUID, cash_gl_account_id: UUID) -> dict:
    lines = _approved_lines(db, client_id=client_id, period_id=period_id)
    net_change = Decimal("0")
    for line, account in lines:
        if account.id == cash_gl_account_id:
            net_change += Decimal(str(line.debit)) - Decimal(str(line.credit))
    return {"net_change_in_cash": float(net_change)}


def compute_variance(*, current: dict, prior: dict | None, materiality_threshold: Decimal) -> dict:
    """Deterministic period-over-period delta. `current`/`prior` are
    generate_income_statement()-shaped dicts. No model call."""
    if prior is None:
        return {"has_prior_period": False, "line_deltas": [], "material_flags": []}

    line_deltas = []
    material_flags = []
    all_keys = set(current.get("revenue", {})) | set(prior.get("revenue", {}))
    all_keys |= set(current.get("expenses", {})) | set(prior.get("expenses", {}))

    for key in sorted(all_keys):
        cur_val = Decimal(str(current.get("revenue", {}).get(key, current.get("expenses", {}).get(key, 0))))
        prior_val = Decimal(str(prior.get("revenue", {}).get(key, prior.get("expenses", {}).get(key, 0))))
        delta = cur_val - prior_val
        line_deltas.append({"line": key, "current": float(cur_val), "prior": float(prior_val), "delta": float(delta)})
        if abs(delta) >= materiality_threshold:
            material_flags.append(key)

    net_income_delta = Decimal(str(current.get("net_income", 0))) - Decimal(str(prior.get("net_income", 0)))
    return {
        "has_prior_period": True,
        "line_deltas": line_deltas,
        "material_flags": material_flags,
        "net_income_delta": float(net_income_delta),
    }
