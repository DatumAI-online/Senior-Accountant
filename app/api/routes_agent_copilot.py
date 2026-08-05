"""CPA Review Copilot's HTTP surface. role=ai_copilot only. Every route
here is read-only from the accounting-state point of view — it returns
recommendations, never writes a ReviewDecision or changes an entry's
status. See app/agents/cpa_review_copilot/agent.py's module docstring."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents.cpa_review_copilot.agent import generate_recommendations
from app.api.deps import get_ai_db, require_role
from app.core.security import TokenPayload
from app.models.enums import UserRole
from app.schemas.copilot import RecommendationItem, RecommendationQueueResponse

router = APIRouter(prefix="/agent/copilot", tags=["agent:cpa-review-copilot"])

require_copilot_agent = require_role(UserRole.AI_COPILOT)


@router.get("/recommendations", response_model=RecommendationQueueResponse)
def get_recommendations(
    client_id: str,
    period_id: str | None = None,
    token: TokenPayload = Depends(require_copilot_agent),
    db: Session = Depends(get_ai_db),
) -> RecommendationQueueResponse:
    results = generate_recommendations(
        db,
        client_id=uuid.UUID(client_id),
        period_id=uuid.UUID(period_id) if period_id else None,
    )
    return RecommendationQueueResponse(
        items=[
            RecommendationItem(
                entry_id=r.entry.id,
                description=r.entry.description,
                confidence=r.entry.confidence,
                recommendation=r.recommendation.recommendation,
                recommendation_confidence=r.recommendation.confidence,
                rationale=r.recommendation.rationale,
                evidence=r.evidence,
                historical=r.historical,
            )
            for r in results
        ]
    )
