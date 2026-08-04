from uuid import UUID

from pydantic import BaseModel, Field


class ReviewQueueLine(BaseModel):
    gl_account_code: str
    gl_account_name: str
    debit: float
    credit: float


class ReviewQueueException(BaseModel):
    id: UUID
    type: str
    severity: str
    description: str


class ReviewQueueEntry(BaseModel):
    id: UUID
    client_id: UUID
    period_id: UUID
    status: str
    description: str
    confidence: float | None
    source_document_id: UUID | None
    created_at: str
    lines: list[ReviewQueueLine]
    exceptions: list[ReviewQueueException]


class ReviewDecisionRequest(BaseModel):
    rationale: str = Field(min_length=1)


class ReviewDecisionResponse(BaseModel):
    decision_id: UUID
    entry_id: UUID
    decision: str
    new_status: str
