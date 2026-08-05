"""Reconciliation & Close Agent's HTTP surface. role=ai_reconciliation
only, get_ai_db session only. Nothing here can reach close_status
'approved'/'delivered' — see app/api/routes_cpa_review.py."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.reconciliation_close.agent import run_reconciliation_and_close
from app.agents.reconciliation_close.tools import CsvParseError, import_transactions, parse_transaction_csv
from app.api.deps import get_ai_db, require_role
from app.core.security import TokenPayload
from app.models.enums import UserRole
from app.schemas.reconciliation import (
    ReconciliationRunResponse,
    ReconciliationSummary,
    TransactionImportRequest,
    TransactionImportResponse,
)

router = APIRouter(prefix="/agent/reconciliation", tags=["agent:reconciliation-close"])

require_reconciliation_agent = require_role(UserRole.AI_RECONCILIATION)


@router.post("/transactions/import", response_model=TransactionImportResponse)
def import_bank_transactions(
    payload: TransactionImportRequest,
    token: TokenPayload = Depends(require_reconciliation_agent),
    db: Session = Depends(get_ai_db),
) -> TransactionImportResponse:
    try:
        rows = parse_transaction_csv(payload.csv_text)
    except CsvParseError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    imported = import_transactions(db, financial_account_id=payload.financial_account_id, rows=rows)
    db.commit()
    return TransactionImportResponse(imported_count=len(imported))


@router.post("/run", response_model=ReconciliationRunResponse)
def run_reconciliation(
    client_id: str,
    period_id: str,
    token: TokenPayload = Depends(require_reconciliation_agent),
    db: Session = Depends(get_ai_db),
) -> ReconciliationRunResponse:
    result = run_reconciliation_and_close(
        db,
        client_id=uuid.UUID(client_id),
        period_id=uuid.UUID(period_id),
        actor_user_id=uuid.UUID(token.sub),
    )
    return ReconciliationRunResponse(
        workflow_run_id=result.workflow_run.id,
        reconciliations=[
            ReconciliationSummary(
                id=r.id,
                financial_account_id=r.financial_account_id,
                status=r.status.value,
                gl_balance=float(r.gl_balance),
                statement_balance=float(r.statement_balance) if r.statement_balance is not None else None,
                difference=float(r.difference),
            )
            for r in result.reconciliations
        ],
        checklist=result.checklist,
        close_status=result.close_status.value,
        exception_count=len(result.exceptions),
    )
