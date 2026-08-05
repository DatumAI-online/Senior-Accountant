from uuid import UUID

from pydantic import BaseModel


class TransactionImportRequest(BaseModel):
    financial_account_id: UUID
    csv_text: str


class TransactionImportResponse(BaseModel):
    imported_count: int


class ReconciliationSummary(BaseModel):
    id: UUID
    financial_account_id: UUID
    status: str
    gl_balance: float
    statement_balance: float | None
    difference: float


class ReconciliationRunResponse(BaseModel):
    workflow_run_id: UUID
    reconciliations: list[ReconciliationSummary]
    checklist: dict
    close_status: str
    exception_count: int
