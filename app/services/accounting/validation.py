"""
Deterministic accounting math. Nothing in this module calls Claude or any
other model — per DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 9, arithmetic,
balance checks, and account-existence checks must never be delegated to an
LLM. Every proposed entry is re-validated here server-side regardless of
what a Claude tool call claims about its own correctness.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accounting_period import GLAccount

TWO_PLACES = Decimal("0.01")


class AccountingValidationError(ValueError):
    """Raised when a proposed entry fails a deterministic accounting check.
    Callers must not persist the entry if this is raised."""


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def validate_debit_equals_credit(lines: list[dict]) -> None:
    """lines: [{"debit": Decimal|float|str, "credit": Decimal|float|str}, ...]

    Raises AccountingValidationError if the entry does not balance, has
    fewer than two lines, or any line has both a debit and a credit (or
    neither) set to a nonzero amount.
    """
    if len(lines) < 2:
        raise AccountingValidationError("A journal entry needs at least two lines.")

    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for i, line in enumerate(lines):
        debit = _round(Decimal(str(line.get("debit", 0))))
        credit = _round(Decimal(str(line.get("credit", 0))))

        if debit < 0 or credit < 0:
            raise AccountingValidationError(f"Line {i}: debit/credit cannot be negative.")
        if debit > 0 and credit > 0:
            raise AccountingValidationError(
                f"Line {i}: a single line cannot have both a debit and a credit."
            )
        if debit == 0 and credit == 0:
            raise AccountingValidationError(f"Line {i}: must have a nonzero debit or credit.")

        total_debit += debit
        total_credit += credit

    if total_debit != total_credit:
        raise AccountingValidationError(
            f"Entry does not balance: total debits {total_debit} != total credits {total_credit}."
        )


def validate_gl_accounts_exist(db: Session, *, client_id, gl_account_ids: list) -> None:
    """Every referenced GL account must belong to this client and be active.
    Cross-client account references would be a tenant-isolation breach, not
    just a data error, so this is checked explicitly rather than trusted
    from model output."""
    if not gl_account_ids:
        raise AccountingValidationError("Entry has no GL account references.")

    unique_ids = set(gl_account_ids)
    rows = db.scalars(
        select(GLAccount).where(GLAccount.id.in_(unique_ids), GLAccount.client_id == client_id)
    ).all()
    found_ids = {row.id for row in rows}
    missing = unique_ids - found_ids
    if missing:
        raise AccountingValidationError(
            f"GL account(s) not found for this client: {sorted(str(m) for m in missing)}"
        )
    inactive = [row.code for row in rows if not row.is_active]
    if inactive:
        raise AccountingValidationError(f"GL account(s) are inactive: {inactive}")
