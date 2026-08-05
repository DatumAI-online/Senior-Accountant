"""
The Reconciliation & Close Agent's tools. Every function here is plain
deterministic Python — matching, balance aggregation, and the close-
readiness gate are never delegated to Claude (Section 9's deterministic-
math rule). This agent may prepare the close package but nothing in this
module can move AccountingPeriod.close_status to 'approved' or 'delivered'
— see app/api/routes_cpa_review.py for the only code path that can.
"""

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accounting_period import AccountingPeriod
from app.models.accounting_profile import Engagement
from app.models.enums import (
    CloseStatus,
    EntryStatus,
    ExceptionSeverity,
    ExceptionType,
    ReconciliationItemStatus,
    ReconciliationStatus,
    TransactionMatchMethod,
)
from app.models.journal_entry import JournalEntryLine, ProposedJournalEntry
from app.models.reconciliation import (
    FinancialAccount,
    ImportedTransaction,
    Reconciliation,
    ReconciliationItem,
    TransactionMatch,
)

MATCH_DATE_TOLERANCE_DAYS = 3

# Entries in these statuses are still "real" for balance/matching purposes;
# only rejected/reversed entries are excluded.
BALANCE_INCLUDED_STATUSES = {
    EntryStatus.DRAFT,
    EntryStatus.PENDING_REVIEW,
    EntryStatus.NEEDS_CLIENT_INFORMATION,
    EntryStatus.NEEDS_REVISION,
    EntryStatus.APPROVED,
    EntryStatus.POSTED,
}


class CsvParseError(Exception):
    """Raised when an uploaded transaction CSV is malformed — a data
    problem, not a Claude/model problem, so it's handled entirely here."""


def parse_transaction_csv(raw_csv: str) -> list[dict]:
    """Expects columns: date, amount, description, [reference].
    Deterministic parsing only — no model call anywhere in this path."""
    reader = csv.DictReader(io.StringIO(raw_csv))
    required = {"date", "amount", "description"}
    if reader.fieldnames is None or not required.issubset({f.strip().lower() for f in reader.fieldnames}):
        raise CsvParseError(f"CSV must have columns: {sorted(required)} (got {reader.fieldnames})")

    rows = []
    for i, row in enumerate(reader):
        row = {k.strip().lower(): v for k, v in row.items()}
        try:
            txn_date = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
            amount = Decimal(row["amount"].strip())
        except (ValueError, KeyError, AttributeError, TypeError, InvalidOperation) as exc:
            raise CsvParseError(f"Row {i}: could not parse date/amount ({exc})") from exc
        rows.append(
            {
                "date": txn_date,
                "amount": amount,
                "description": row["description"].strip(),
                "reference": row.get("reference", "").strip() or None,
            }
        )
    return rows


def import_transactions(
    db: Session, *, financial_account_id: UUID, rows: list[dict]
) -> list[ImportedTransaction]:
    imported = []
    for row in rows:
        txn = ImportedTransaction(
            financial_account_id=financial_account_id,
            transaction_date=row["date"],
            amount=row["amount"],
            description=row["description"],
            raw_ref=row["reference"],
        )
        db.add(txn)
        imported.append(txn)
    db.flush()
    return imported


def _candidate_entry_lines(
    db: Session, *, gl_account_id: UUID, period_id: UUID
) -> list[tuple[ProposedJournalEntry, JournalEntryLine]]:
    rows = db.execute(
        select(ProposedJournalEntry, JournalEntryLine)
        .join(JournalEntryLine, JournalEntryLine.entry_id == ProposedJournalEntry.id)
        .where(
            ProposedJournalEntry.period_id == period_id,
            JournalEntryLine.gl_account_id == gl_account_id,
            ProposedJournalEntry.status.in_(BALANCE_INCLUDED_STATUSES),
        )
    ).all()
    return list(rows)


def match_transactions_to_entries(
    db: Session, *, financial_account: FinancialAccount, period_id: UUID
) -> tuple[list[TransactionMatch], list[ImportedTransaction]]:
    """Deterministic matching: an imported transaction matches a candidate
    entry line if the line's net amount against this GL account equals the
    transaction's absolute amount, within a date tolerance window, and that
    line hasn't already been matched. First-fit, not fuzzy — exactly one
    rule, always explainable."""
    candidates = _candidate_entry_lines(
        db, gl_account_id=financial_account.gl_account_id, period_id=period_id
    )
    already_matched_entry_ids = {
        m.entry_id
        for m in db.scalars(
            select(TransactionMatch).where(
                TransactionMatch.entry_id.in_([entry.id for entry, _ in candidates] or [None])
            )
        ).all()
        if m.entry_id is not None
    }

    imported_txns = list(
        db.scalars(
            select(ImportedTransaction).where(
                ImportedTransaction.financial_account_id == financial_account.id
            )
        ).all()
    )
    already_matched_txn_ids = {
        m.imported_transaction_id
        for m in db.scalars(
            select(TransactionMatch).where(
                TransactionMatch.imported_transaction_id.in_([t.id for t in imported_txns] or [None])
            )
        ).all()
    }

    matches: list[TransactionMatch] = []
    unmatched: list[ImportedTransaction] = []

    for txn in imported_txns:
        if txn.id in already_matched_txn_ids:
            continue

        txn_amount = abs(Decimal(str(txn.amount)))
        found = None
        for entry, line in candidates:
            if entry.id in already_matched_entry_ids:
                continue
            line_amount = Decimal(str(line.debit)) if Decimal(str(line.debit)) > 0 else Decimal(
                str(line.credit)
            )
            if line_amount != txn_amount:
                continue
            # entry_date is the business/transaction date (e.g. from the
            # source document); only fall back to created_at (row-insertion
            # time) when no document date was extractable — see the
            # ProposedJournalEntry.entry_date column docstring.
            comparison_date = entry.entry_date or entry.created_at.date()
            if abs((comparison_date - txn.transaction_date).days) > MATCH_DATE_TOLERANCE_DAYS:
                continue
            found = entry
            break

        if found is not None:
            match = TransactionMatch(
                imported_transaction_id=txn.id,
                entry_id=found.id,
                match_method=TransactionMatchMethod.EXACT_AMOUNT_DATE,
            )
            db.add(match)
            matches.append(match)
            already_matched_entry_ids.add(found.id)
        else:
            unmatched.append(txn)

    db.flush()
    return matches, unmatched


def compute_gl_account_balance(db: Session, *, gl_account_id: UUID, period_id: UUID) -> Decimal:
    """Deterministic net balance (debit - credit) for a GL account within a
    period, across every non-rejected/non-reversed entry."""
    rows = _candidate_entry_lines(db, gl_account_id=gl_account_id, period_id=period_id)
    total = Decimal("0")
    for _entry, line in rows:
        total += Decimal(str(line.debit)) - Decimal(str(line.credit))
    return total


def run_bank_reconciliation(
    db: Session,
    *,
    financial_account: FinancialAccount,
    period_id: UUID,
    statement_balance: Decimal | None = None,
    materiality_threshold: Decimal = Decimal("1.00"),
) -> Reconciliation:
    matches, unmatched = match_transactions_to_entries(
        db, financial_account=financial_account, period_id=period_id
    )
    gl_balance = compute_gl_account_balance(
        db, gl_account_id=financial_account.gl_account_id, period_id=period_id
    )

    if statement_balance is not None:
        difference = abs(Decimal(str(statement_balance)) - gl_balance)
    else:
        difference = Decimal("0") if not unmatched else Decimal(
            str(sum(abs(Decimal(str(t.amount))) for t in unmatched))
        )

    status = (
        ReconciliationStatus.RECONCILED
        if not unmatched and difference <= materiality_threshold
        else ReconciliationStatus.DISCREPANCY
    )

    reconciliation = Reconciliation(
        financial_account_id=financial_account.id,
        period_id=period_id,
        status=status,
        statement_balance=statement_balance,
        gl_balance=gl_balance,
        difference=difference,
        completed_at=None if status == ReconciliationStatus.DISCREPANCY else _now(),
    )
    db.add(reconciliation)
    db.flush()

    for match in matches:
        db.add(
            ReconciliationItem(
                reconciliation_id=reconciliation.id,
                imported_transaction_id=match.imported_transaction_id,
                status=ReconciliationItemStatus.MATCHED,
            )
        )
    for txn in unmatched:
        db.add(
            ReconciliationItem(
                reconciliation_id=reconciliation.id,
                imported_transaction_id=txn.id,
                status=ReconciliationItemStatus.UNMATCHED,
            )
        )
    db.flush()
    return reconciliation


def run_close_checklist(db: Session, *, period_id: UUID) -> dict:
    """Deterministic close-readiness gate. Returns {"ready": bool,
    "blocking_items": [...]}. Readiness means every active FinancialAccount
    for this client has a RECONCILED Reconciliation row for this period —
    nothing more, nothing less. Unresolved exceptions on entries are NOT
    blockers here; flagging those for CPA attention is the review queue's
    job, not the close checklist's."""
    period = db.get(AccountingPeriod, period_id)
    engagement_row = db.get(Engagement, period.engagement_id)
    client_id = engagement_row.client_id

    active_accounts = list(
        db.scalars(
            select(FinancialAccount).where(
                FinancialAccount.client_id == client_id, FinancialAccount.is_active == True  # noqa: E712
            )
        ).all()
    )

    blocking_items = []
    if not active_accounts:
        blocking_items.append("No active financial accounts configured for this client.")

    for account in active_accounts:
        reconciliation = db.scalar(
            select(Reconciliation)
            .where(
                Reconciliation.financial_account_id == account.id,
                Reconciliation.period_id == period_id,
            )
            .order_by(Reconciliation.created_at.desc())
        )
        if reconciliation is None:
            blocking_items.append(f"{account.institution} ...{account.mask}: not yet reconciled.")
        elif reconciliation.status != ReconciliationStatus.RECONCILED:
            blocking_items.append(
                f"{account.institution} ...{account.mask}: reconciliation shows a "
                f"{reconciliation.difference} difference."
            )

    return {"ready": not blocking_items, "blocking_items": blocking_items}


def unmatched_transaction_exception_type() -> ExceptionType:
    return ExceptionType.UNMATCHED_TRANSACTION


def reconciliation_difference_exception_severity(difference: Decimal, materiality: Decimal) -> ExceptionSeverity:
    if difference > materiality * 10:
        return ExceptionSeverity.HIGH
    return ExceptionSeverity.MEDIUM


def _now():
    from app.agents.common.tools import utcnow

    return utcnow()
