"""
Reconciliation & Close Agent orchestration.

run_reconciliation_and_close() reconciles every active financial account
for a client/period and determines whether the period is ready for CPA
review — a deterministic gate (app/agents/reconciliation_close/tools.py's
run_close_checklist), not a judgment call. This agent may drive
close_status through every state except 'approved'/'delivered' — those
two values don't appear anywhere in this file, and the database trigger in
0004_reconciliation_reporting_grants.py blocks them independent of that.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.common.tools import flag_exception, log_audit_event, log_tool_invocation, utcnow
from app.agents.reconciliation_close.tools import run_bank_reconciliation, run_close_checklist
from app.models.accounting_period import AccountingPeriod
from app.models.accounting_profile import ClientAccountingProfile
from app.models.enums import (
    ActorType,
    AgentType,
    CloseStatus,
    ExceptionSeverity,
    ExceptionType,
    ReconciliationItemStatus,
    ReconciliationStatus,
    UserRole,
    WorkflowRunStatus,
)
from app.models.reconciliation import FinancialAccount, ReconciliationItem
from app.models.workflow import WorkflowRun
from app.services.accounting.close_state_machine import assert_close_transition_allowed


@dataclass
class ReconciliationRunResult:
    workflow_run: WorkflowRun
    reconciliations: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)
    checklist: dict | None = None
    close_status: CloseStatus | None = None


def run_reconciliation_and_close(
    db: Session, *, client_id: UUID, period_id: UUID, actor_user_id: UUID
) -> ReconciliationRunResult:
    workflow_run = WorkflowRun(
        client_id=client_id,
        agent_type=AgentType.RECONCILIATION_CLOSE,
        trigger=f"reconciliation_requested:{period_id}",
        status=WorkflowRunStatus.RUNNING,
        started_at=utcnow(),
    )
    db.add(workflow_run)
    db.flush()
    result = ReconciliationRunResult(workflow_run=workflow_run)

    period = db.get(AccountingPeriod, period_id)
    profile = db.scalar(
        select(ClientAccountingProfile).where(ClientAccountingProfile.client_id == client_id)
    )
    materiality_threshold = Decimal(str(profile.materiality_threshold)) if profile else Decimal("1.00")

    if period.close_status == CloseStatus.PROCESSING:
        assert_close_transition_allowed(
            from_status=CloseStatus.PROCESSING,
            to_status=CloseStatus.RECONCILING,
            actor_role=UserRole.AI_RECONCILIATION,
        )
        period.close_status = CloseStatus.RECONCILING
        db.flush()
        log_audit_event(
            db,
            client_id=client_id,
            event_type="close.reconciling",
            actor_id=actor_user_id,
            actor_type=ActorType.AI_SERVICE,
            entity_type="accounting_period",
            entity_id=period.id,
            after={"close_status": period.close_status.value},
        )

    accounts = list(
        db.scalars(
            select(FinancialAccount).where(
                FinancialAccount.client_id == client_id, FinancialAccount.is_active == True  # noqa: E712
            )
        ).all()
    )

    for account in accounts:
        reconciliation = run_bank_reconciliation(
            db,
            financial_account=account,
            period_id=period_id,
            materiality_threshold=materiality_threshold,
        )
        log_tool_invocation(
            db,
            workflow_run_id=workflow_run.id,
            tool_name="run_bank_reconciliation",
            input_json={"financial_account_id": str(account.id), "period_id": str(period_id)},
            output_json={
                "status": reconciliation.status.value,
                "gl_balance": float(reconciliation.gl_balance),
                "difference": float(reconciliation.difference),
            },
            model=None,
            skill_version=None,
            duration_ms=0,
        )
        result.reconciliations.append(reconciliation)

        unmatched_items = db.scalars(
            select(ReconciliationItem).where(
                ReconciliationItem.reconciliation_id == reconciliation.id,
                ReconciliationItem.status == ReconciliationItemStatus.UNMATCHED,
            )
        ).all()
        for item in unmatched_items:
            severity = (
                ExceptionSeverity.HIGH
                if reconciliation.difference > materiality_threshold * 10
                else ExceptionSeverity.MEDIUM
            )
            exc = flag_exception(
                db,
                client_id=client_id,
                period_id=period_id,
                related_entry_id=None,
                exception_type=ExceptionType.UNMATCHED_TRANSACTION,
                severity=severity,
                description=(
                    f"Imported transaction on {account.institution} ...{account.mask} has no "
                    f"matching proposed entry."
                ),
                detected_by=AgentType.RECONCILIATION_CLOSE.value,
            )
            result.exceptions.append(exc)

        if reconciliation.status == ReconciliationStatus.DISCREPANCY and not unmatched_items:
            exc = flag_exception(
                db,
                client_id=client_id,
                period_id=period_id,
                related_entry_id=None,
                exception_type=ExceptionType.RECONCILIATION_DIFFERENCE,
                severity=ExceptionSeverity.HIGH,
                description=(
                    f"{account.institution} ...{account.mask}: GL balance "
                    f"{reconciliation.gl_balance} differs from statement balance "
                    f"{reconciliation.statement_balance} by {reconciliation.difference}."
                ),
                detected_by=AgentType.RECONCILIATION_CLOSE.value,
            )
            result.exceptions.append(exc)

    checklist = run_close_checklist(db, period_id=period_id)
    log_tool_invocation(
        db,
        workflow_run_id=workflow_run.id,
        tool_name="run_close_checklist",
        input_json={"period_id": str(period_id)},
        output_json=checklist,
        model=None,
        skill_version=None,
        duration_ms=0,
    )
    result.checklist = checklist

    if checklist["ready"] and period.close_status == CloseStatus.RECONCILING:
        assert_close_transition_allowed(
            from_status=CloseStatus.RECONCILING,
            to_status=CloseStatus.READY_FOR_CPA_REVIEW,
            actor_role=UserRole.AI_RECONCILIATION,
        )
        period.close_status = CloseStatus.READY_FOR_CPA_REVIEW
        db.flush()
        log_audit_event(
            db,
            client_id=client_id,
            event_type="close.ready_for_review",
            actor_id=actor_user_id,
            actor_type=ActorType.AI_SERVICE,
            entity_type="accounting_period",
            entity_id=period.id,
            after={"close_status": period.close_status.value},
        )

    result.close_status = period.close_status
    workflow_run.status = WorkflowRunStatus.COMPLETED
    workflow_run.ended_at = utcnow()
    db.commit()
    return result
