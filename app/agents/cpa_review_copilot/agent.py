"""
CPA Review Copilot orchestration.

generate_recommendations() produces a prioritized, evidence-annotated,
Claude-drafted-recommendation view of a client's pending_review queue for
a human CPA to read. It is advisory-only end to end: no function reachable
from this module can create a ReviewDecision or change a
ProposedJournalEntry's status. See
DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 5.4.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.common.tools import log_tool_invocation, utcnow
from app.agents.cpa_review_copilot.schemas import RecommendationResult
from app.agents.cpa_review_copilot.tools import (
    check_evidence_completeness,
    compare_to_historical_treatment,
    prioritize_review_queue,
    recommend_review_decision,
)
from app.models.enums import AgentType, EntryStatus, WorkflowRunStatus
from app.models.journal_entry import ProposedJournalEntry
from app.models.workflow import WorkflowRun


@dataclass
class QueueRecommendation:
    entry: ProposedJournalEntry
    evidence: dict
    historical: dict
    recommendation: RecommendationResult


def generate_recommendations(
    db: Session, *, client_id: UUID, period_id: UUID | None = None
) -> list[QueueRecommendation]:
    workflow_run = WorkflowRun(
        client_id=client_id,
        agent_type=AgentType.CPA_REVIEW_COPILOT,
        trigger=f"review_queue_requested:{client_id}",
        status=WorkflowRunStatus.RUNNING,
        started_at=utcnow(),
    )
    db.add(workflow_run)
    db.flush()

    query = select(ProposedJournalEntry).where(
        ProposedJournalEntry.client_id == client_id,
        ProposedJournalEntry.status == EntryStatus.PENDING_REVIEW,
    )
    if period_id is not None:
        query = query.where(ProposedJournalEntry.period_id == period_id)
    entries = list(db.scalars(query).all())

    prioritized = prioritize_review_queue(db, entries)

    results: list[QueueRecommendation] = []
    for entry in prioritized:
        evidence = check_evidence_completeness(entry)
        historical = compare_to_historical_treatment(db, client_id=client_id, entry_id=entry.id)
        recommendation, invocation_meta = recommend_review_decision(
            db, entry=entry, evidence=evidence, historical=historical
        )
        log_tool_invocation(
            db,
            workflow_run_id=workflow_run.id,
            tool_name=invocation_meta["tool_name"],
            input_json={"entry_id": str(entry.id), "evidence": evidence, "historical": historical},
            output_json=invocation_meta["output_json"],
            model=invocation_meta["model"],
            skill_version=invocation_meta["skill_version"],
            duration_ms=invocation_meta["duration_ms"],
        )
        results.append(
            QueueRecommendation(
                entry=entry, evidence=evidence, historical=historical, recommendation=recommendation
            )
        )

    workflow_run.status = WorkflowRunStatus.COMPLETED
    workflow_run.ended_at = utcnow()
    db.commit()
    return results
