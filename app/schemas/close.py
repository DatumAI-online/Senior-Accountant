from uuid import UUID

from pydantic import BaseModel, Field


class ClosePeriodActionRequest(BaseModel):
    rationale: str = Field(min_length=1)


class ClosePeriodActionResponse(BaseModel):
    period_id: UUID
    close_status: str


class DeliverableApprovalResponse(BaseModel):
    period_id: UUID
    close_status: str
    approved_report_ids: list[UUID]
    approved_summary_id: UUID | None
