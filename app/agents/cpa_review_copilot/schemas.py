from pydantic import BaseModel, Field


class RecommendationResult(BaseModel):
    """Output of the recommend_review_decision tool. `recommendation` is
    advisory vocabulary only — 'approve'/'reject'/'revise'/'escalate' — and
    is never itself written as an EntryStatus or ReviewDecisionType. Only a
    human CPA's actual action (via routes_cpa_review.py) produces those."""

    recommendation: str = Field(pattern="^(approve|reject|revise|escalate)$")
    confidence: float = Field(ge=0, le=1)
    rationale: str
