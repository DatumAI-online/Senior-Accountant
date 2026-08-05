from uuid import UUID

from pydantic import BaseModel


class RecommendedActionSummary(BaseModel):
    id: UUID
    text: str
    category: str


class ReportingRunResponse(BaseModel):
    workflow_run_id: UUID
    income_statement_id: UUID
    balance_sheet_id: UUID
    cash_summary_id: UUID
    executive_summary_id: UUID
    executive_summary_text: str
    action_items: list[RecommendedActionSummary]
    variance: dict
