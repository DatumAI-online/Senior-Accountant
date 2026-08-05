"""Reporting & Insights Agent's HTTP surface. role=ai_reporting only.
Refuses to run unless the CPA has already approved the period's close
(app/agents/reporting_insights/agent.py enforces this); nothing here can
mark a report or summary as approved/deliverable — see
app/api/routes_cpa_review.py."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.reporting_insights.agent import ClosePeriodNotApprovedError, generate_financial_package
from app.api.deps import get_ai_db, require_role
from app.core.security import TokenPayload
from app.models.enums import UserRole
from app.schemas.reporting import RecommendedActionSummary, ReportingRunResponse

router = APIRouter(prefix="/agent/reporting", tags=["agent:reporting-insights"])

require_reporting_agent = require_role(UserRole.AI_REPORTING)


@router.post("/generate", response_model=ReportingRunResponse)
def generate_report_package(
    client_id: str,
    period_id: str,
    token: TokenPayload = Depends(require_reporting_agent),
    db: Session = Depends(get_ai_db),
) -> ReportingRunResponse:
    try:
        result = generate_financial_package(
            db,
            client_id=uuid.UUID(client_id),
            period_id=uuid.UUID(period_id),
            actor_user_id=uuid.UUID(token.sub),
        )
    except ClosePeriodNotApprovedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ReportingRunResponse(
        workflow_run_id=result.workflow_run.id,
        income_statement_id=result.income_statement.id,
        balance_sheet_id=result.balance_sheet.id,
        cash_summary_id=result.cash_summary.id,
        executive_summary_id=result.executive_summary.id,
        executive_summary_text=result.executive_summary.content,
        action_items=[
            RecommendedActionSummary(id=a.id, text=a.text, category=a.category) for a in result.action_items
        ],
        variance=result.variance,
    )
