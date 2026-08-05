from uuid import UUID

from pydantic import BaseModel


class RecommendationItem(BaseModel):
    entry_id: UUID
    description: str
    confidence: float | None
    recommendation: str
    recommendation_confidence: float
    rationale: str
    evidence: dict
    historical: dict


class RecommendationQueueResponse(BaseModel):
    items: list[RecommendationItem]
