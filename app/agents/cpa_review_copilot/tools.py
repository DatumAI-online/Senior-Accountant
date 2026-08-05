"""
The CPA Review Copilot's tools. Prioritization, evidence completeness, and
historical-treatment stats are deterministic Python — only the final
recommendation text is Claude-generated, and even that is validated
against a fixed vocabulary (app/agents/cpa_review_copilot/schemas.py)
before being returned. Nothing here can write a ReviewDecision or change
an entry's status.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.cpa_review_copilot.schemas import RecommendationResult
from app.agents.cpa_review_copilot.skill import get_recommendation_client
from app.models.accounting_period import GLAccount
from app.models.enums import ExceptionSeverity, ExceptionStatus, ReviewDecisionType
from app.models.exception_record import ExceptionRecord
from app.models.journal_entry import JournalEntryLine, ProposedJournalEntry
from app.models.review_decision import ReviewDecision

_SEVERITY_WEIGHT = {
    ExceptionSeverity.CRITICAL: 4,
    ExceptionSeverity.HIGH: 3,
    ExceptionSeverity.MEDIUM: 2,
    ExceptionSeverity.LOW: 1,
}


def prioritize_review_queue(
    db: Session, entries: list[ProposedJournalEntry]
) -> list[ProposedJournalEntry]:
    """Deterministic priority score: open-exception severity first (higher
    wins), then lower confidence, then older first. No model call."""

    def score(entry: ProposedJournalEntry) -> tuple:
        exceptions = db.scalars(
            select(ExceptionRecord).where(
                ExceptionRecord.related_entry_id == entry.id,
                ExceptionRecord.status == ExceptionStatus.OPEN,
            )
        ).all()
        max_severity = max((_SEVERITY_WEIGHT[e.severity] for e in exceptions), default=0)
        confidence = entry.confidence if entry.confidence is not None else 1.0
        return (-max_severity, confidence, entry.created_at)

    return sorted(entries, key=score)


def check_evidence_completeness(entry: ProposedJournalEntry) -> dict:
    return {
        "has_source_document": entry.source_document_id is not None,
        "has_confidence_score": entry.confidence is not None,
    }


def compare_to_historical_treatment(db: Session, *, client_id: UUID, entry_id: UUID) -> dict:
    """Deterministic stats: how has this CPA treated past entries touching
    the same GL account(s) as this one? Read-only — never writes a
    ReviewDecision, only reads existing ones."""
    gl_account_ids = db.scalars(
        select(JournalEntryLine.gl_account_id).where(JournalEntryLine.entry_id == entry_id)
    ).all()
    if not gl_account_ids:
        return {"sample_size": 0, "approval_rate": None}

    rows = db.execute(
        select(ReviewDecision.decision, func.count())
        .join(ProposedJournalEntry, ProposedJournalEntry.id == ReviewDecision.entry_id)
        .join(JournalEntryLine, JournalEntryLine.entry_id == ProposedJournalEntry.id)
        .where(
            ProposedJournalEntry.client_id == client_id,
            JournalEntryLine.gl_account_id.in_(gl_account_ids),
            ProposedJournalEntry.id != entry_id,
        )
        .group_by(ReviewDecision.decision)
    ).all()

    counts = {decision.value: count for decision, count in rows}
    total = sum(counts.values())
    approved = counts.get(ReviewDecisionType.APPROVED.value, 0)
    return {
        "sample_size": total,
        "approval_rate": (approved / total) if total else None,
        "counts": counts,
    }


def recommend_review_decision(
    db: Session,
    *,
    entry: ProposedJournalEntry,
    evidence: dict,
    historical: dict,
) -> tuple[RecommendationResult, dict]:
    lines = db.scalars(
        select(JournalEntryLine).where(JournalEntryLine.entry_id == entry.id)
    ).all()
    gl_accounts = {a.id: a for a in db.scalars(select(GLAccount)).all()}
    open_exceptions = db.scalars(
        select(ExceptionRecord).where(
            ExceptionRecord.related_entry_id == entry.id, ExceptionRecord.status == ExceptionStatus.OPEN
        )
    ).all()

    payload = {
        "description": entry.description,
        "confidence": entry.confidence,
        "lines": [
            {
                "gl_account_code": gl_accounts[line.gl_account_id].code,
                "gl_account_name": gl_accounts[line.gl_account_id].name,
                "debit": float(line.debit),
                "credit": float(line.credit),
            }
            for line in lines
        ],
        "open_exceptions": [
            {"type": e.type.value, "severity": e.severity.value, "description": e.description}
            for e in open_exceptions
        ],
        "evidence_completeness": evidence,
        "historical_treatment": historical,
    }

    content_blocks = [{"type": "text", "text": f"Review context (JSON):\n{payload}"}]
    client = get_recommendation_client()
    result = client.call(content_blocks)
    recommendation = RecommendationResult.model_validate(result.data)

    invocation_meta = {
        "tool_name": "recommend_review_decision",
        "output_json": result.data,
        "model": result.model,
        "skill_version": result.skill_version,
        "duration_ms": result.duration_ms,
    }
    return recommendation, invocation_meta
