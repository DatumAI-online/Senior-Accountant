"""
Reporting & Insights Agent orchestration.

generate_financial_package() only runs once a period's close has been
CPA-approved (AccountingPeriod.close_status == APPROVED) — it refuses to
run otherwise, and every aggregation it calls is hard-filtered to
APPROVED/POSTED entries regardless. Nothing in this file can set
FinancialReport.approved_by, ExecutiveSummary.approved_by, or move
close_status to DELIVERED — see app/api/routes_cpa_review.py for the only
code path that can (and note neither AI service Postgres role even has an
UPDATE grant on financial_reports/executive_summaries — see
0004_reconciliation_reporting_grants.py).
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.common.tools import log_audit_event, log_tool_invocation, utcnow
from app.agents.reporting_insights.schemas import ExecutiveSummaryDraft
from app.agents.reporting_insights.skill import get_summary_client
from app.agents.reporting_insights.tools import (
    compute_variance,
    generate_balance_sheet,
    generate_cash_summary,
    generate_income_statement,
)
from app.models.accounting_period import AccountingPeriod, GLAccount
from app.models.accounting_profile import ClientAccountingProfile, Engagement
from app.models.enums import ActorType, AgentType, CloseStatus, FinancialReportType, WorkflowRunStatus
from app.models.reporting import ExecutiveSummary, FinancialReport, RecommendedAction
from app.models.workflow import WorkflowRun

DEFAULT_CASH_ACCOUNT_CODE = "1000"


class ClosePeriodNotApprovedError(Exception):
    """Raised when reporting is attempted before the CPA has approved the
    period's close. This is a hard stop, not a warning."""


@dataclass
class ReportingRunResult:
    workflow_run: WorkflowRun
    income_statement: FinancialReport
    balance_sheet: FinancialReport
    cash_summary: FinancialReport
    executive_summary: ExecutiveSummary
    action_items: list[RecommendedAction]
    variance: dict


def _find_prior_period(db: Session, *, engagement_id: UUID, current_period: str) -> AccountingPeriod | None:
    return db.scalar(
        select(AccountingPeriod)
        .where(AccountingPeriod.engagement_id == engagement_id, AccountingPeriod.period < current_period)
        .order_by(AccountingPeriod.period.desc())
    )


def generate_financial_package(
    db: Session, *, client_id: UUID, period_id: UUID, actor_user_id: UUID
) -> ReportingRunResult:
    period = db.get(AccountingPeriod, period_id)
    if period.close_status != CloseStatus.APPROVED:
        raise ClosePeriodNotApprovedError(
            f"Period {period_id} has close_status={period.close_status.value}; reporting requires "
            f"the CPA to have approved the close first."
        )

    workflow_run = WorkflowRun(
        client_id=client_id,
        agent_type=AgentType.REPORTING_INSIGHTS,
        trigger=f"reporting_requested:{period_id}",
        status=WorkflowRunStatus.RUNNING,
        started_at=utcnow(),
    )
    db.add(workflow_run)
    db.flush()

    cash_account = db.scalar(
        select(GLAccount).where(GLAccount.client_id == client_id, GLAccount.code == DEFAULT_CASH_ACCOUNT_CODE)
    )

    income_statement_data = generate_income_statement(db, client_id=client_id, period_id=period_id)
    balance_sheet_data = generate_balance_sheet(db, client_id=client_id, period_id=period_id)
    cash_summary_data = generate_cash_summary(
        db, client_id=client_id, period_id=period_id, cash_gl_account_id=cash_account.id
    )

    for tool_name, output in (
        ("generate_income_statement", income_statement_data),
        ("generate_balance_sheet", balance_sheet_data),
        ("generate_cash_summary", cash_summary_data),
    ):
        log_tool_invocation(
            db,
            workflow_run_id=workflow_run.id,
            tool_name=tool_name,
            input_json={"client_id": str(client_id), "period_id": str(period_id)},
            output_json=output,
            model=None,
            skill_version=None,
            duration_ms=0,
        )

    engagement = db.get(Engagement, period.engagement_id)
    prior_period = _find_prior_period(db, engagement_id=engagement.id, current_period=period.period)
    prior_income_statement = None
    if prior_period is not None:
        prior_report = db.scalar(
            select(FinancialReport).where(
                FinancialReport.period_id == prior_period.id,
                FinancialReport.report_type == FinancialReportType.INCOME_STATEMENT,
            )
        )
        if prior_report is not None:
            prior_income_statement = prior_report.data

    profile = db.scalar(
        select(ClientAccountingProfile).where(ClientAccountingProfile.client_id == client_id)
    )
    materiality_threshold = Decimal(str(profile.materiality_threshold)) if profile else Decimal("500.00")

    variance = compute_variance(
        current=income_statement_data, prior=prior_income_statement, materiality_threshold=materiality_threshold
    )
    log_tool_invocation(
        db,
        workflow_run_id=workflow_run.id,
        tool_name="compute_variance",
        input_json={"period_id": str(period_id)},
        output_json=variance,
        model=None,
        skill_version=None,
        duration_ms=0,
    )

    income_statement = FinancialReport(
        client_id=client_id,
        period_id=period_id,
        report_type=FinancialReportType.INCOME_STATEMENT,
        data=income_statement_data,
        generated_by=AgentType.REPORTING_INSIGHTS.value,
    )
    balance_sheet = FinancialReport(
        client_id=client_id,
        period_id=period_id,
        report_type=FinancialReportType.BALANCE_SHEET,
        data=balance_sheet_data,
        generated_by=AgentType.REPORTING_INSIGHTS.value,
    )
    cash_summary = FinancialReport(
        client_id=client_id,
        period_id=period_id,
        report_type=FinancialReportType.CASH_SUMMARY,
        data=cash_summary_data,
        generated_by=AgentType.REPORTING_INSIGHTS.value,
    )
    db.add_all([income_statement, balance_sheet, cash_summary])
    db.flush()

    for report in (income_statement, balance_sheet, cash_summary):
        log_audit_event(
            db,
            client_id=client_id,
            event_type="report.generated",
            actor_id=actor_user_id,
            actor_type=ActorType.AI_SERVICE,
            entity_type="financial_report",
            entity_id=report.id,
            after={"report_type": report.report_type.value},
        )

    summary_payload = {
        "income_statement": income_statement_data,
        "balance_sheet": balance_sheet_data,
        "cash_summary": cash_summary_data,
        "variance": variance,
    }
    content_blocks = [{"type": "text", "text": f"Financial data (JSON):\n{summary_payload}"}]
    client = get_summary_client()
    result = client.call(content_blocks)
    draft = ExecutiveSummaryDraft.model_validate(result.data)

    log_tool_invocation(
        db,
        workflow_run_id=workflow_run.id,
        tool_name="draft_executive_summary",
        input_json=summary_payload,
        output_json=result.data,
        model=result.model,
        skill_version=result.skill_version,
        duration_ms=result.duration_ms,
    )

    executive_summary = ExecutiveSummary(
        client_id=client_id,
        period_id=period_id,
        content=draft.summary_text,
        skill_version=result.skill_version,
        model=result.model,
    )
    db.add(executive_summary)
    db.flush()

    action_items = []
    for item in draft.action_items:
        action = RecommendedAction(summary_id=executive_summary.id, text=item.text, category=item.category)
        db.add(action)
        action_items.append(action)
    db.flush()

    log_audit_event(
        db,
        client_id=client_id,
        event_type="summary.generated",
        actor_id=actor_user_id,
        actor_type=ActorType.AI_SERVICE,
        entity_type="executive_summary",
        entity_id=executive_summary.id,
        after={"action_item_count": len(action_items)},
    )

    workflow_run.status = WorkflowRunStatus.COMPLETED
    workflow_run.ended_at = utcnow()
    db.commit()

    return ReportingRunResult(
        workflow_run=workflow_run,
        income_statement=income_statement,
        balance_sheet=balance_sheet,
        cash_summary=cash_summary,
        executive_summary=executive_summary,
        action_items=action_items,
        variance=variance,
    )
