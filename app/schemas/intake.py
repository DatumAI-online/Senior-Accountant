from uuid import UUID

from pydantic import BaseModel


class ExceptionSummary(BaseModel):
    id: UUID
    type: str
    severity: str
    description: str


class ProposedEntrySummary(BaseModel):
    id: UUID
    status: str
    description: str
    confidence: float | None


class IntakeRunResponse(BaseModel):
    workflow_run_id: UUID
    workflow_status: str
    source_document_id: UUID
    entry: ProposedEntrySummary | None
    exceptions: list[ExceptionSummary]
