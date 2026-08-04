"""
Integration tests for the CPA review/approval HTTP surface, and for the
full pending_review -> needs_revision -> pending_review -> approved cycle
described in DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 7.1.
"""

from unittest.mock import patch

from app.agents.intake_bookkeeper.agent import run_intake_pipeline
from app.models.enums import DocumentType, EntryStatus
from app.services.claude_client import ClaudeSkillResult


def _seed_pending_entry(ai_db, seeded_client):
    extraction = ClaudeSkillResult(
        data={
            "vendor": "Notion Labs",
            "amount": 24.00,
            "currency": "USD",
            "document_date": "2026-07-03",
            "description": "Notion software subscription",
            "doc_type_guess": "receipt",
        },
        raw_text="{}",
        model="claude-sonnet-4-6",
        skill_name="intake_bookkeeper.extract_document_data",
        skill_version="v1",
        duration_ms=100,
    )
    classification = ClaudeSkillResult(
        data={"gl_account_code": "6100", "confidence": 0.93, "rationale": "SaaS subscription."},
        raw_text="{}",
        model="claude-sonnet-4-6",
        skill_name="intake_bookkeeper.classify_transaction",
        skill_version="v1",
        duration_ms=80,
    )
    with patch("app.agents.intake_bookkeeper.tools.get_extraction_client") as mock_extract, patch(
        "app.agents.intake_bookkeeper.tools.get_classification_client"
    ) as mock_classify:
        mock_extract.return_value.call.return_value = extraction
        mock_classify.return_value.call.return_value = classification
        result = run_intake_pipeline(
            ai_db,
            client_id=seeded_client["client"].id,
            period_id=seeded_client["period"].id,
            uploaded_by=seeded_client["intake_user"].id,
            doc_type=DocumentType.RECEIPT,
            original_filename="receipt.txt",
            mime_type="text/plain",
            raw_text="Notion receipt $24.00",
        )
    return result.entry


def test_review_queue_lists_pending_entry(api_client, ai_db, seeded_client, cpa_token):
    entry = _seed_pending_entry(ai_db, seeded_client)

    resp = api_client.get(
        "/api/v1/cpa/review-queue",
        params={"client_id": str(seeded_client["client"].id)},
        headers={"Authorization": f"Bearer {cpa_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(entry.id)
    assert body[0]["status"] == "pending_review"
    assert len(body[0]["lines"]) == 2


def test_cpa_can_approve_entry_end_to_end(api_client, ai_db, admin_db, seeded_client, cpa_token):
    from sqlalchemy import select

    from app.models.review_decision import ReviewDecision

    entry = _seed_pending_entry(ai_db, seeded_client)

    resp = api_client.post(
        f"/api/v1/cpa/entries/{entry.id}/approve",
        json={"rationale": "Evidence checked, matches receipt."},
        headers={"Authorization": f"Bearer {cpa_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["new_status"] == "approved"

    decisions = admin_db.scalars(select(ReviewDecision).where(ReviewDecision.entry_id == entry.id)).all()
    assert len(decisions) == 1
    assert decisions[0].decision.value == "approved"
    assert decisions[0].rationale == "Evidence checked, matches receipt."

    from app.models.journal_entry import ProposedJournalEntry

    refreshed = admin_db.get(ProposedJournalEntry, entry.id)
    assert refreshed.status == EntryStatus.APPROVED


def test_ai_intake_token_cannot_call_approve(api_client, ai_db, seeded_client, intake_token):
    entry = _seed_pending_entry(ai_db, seeded_client)

    resp = api_client.post(
        f"/api/v1/cpa/entries/{entry.id}/approve",
        json={"rationale": "self-approved"},
        headers={"Authorization": f"Bearer {intake_token}"},
    )
    assert resp.status_code == 403


def test_full_revision_cycle(api_client, ai_db, admin_db, seeded_client, cpa_token):
    from sqlalchemy import select

    from app.models.journal_entry import ProposedJournalEntry
    from app.models.review_decision import ReviewDecision
    from app.services.accounting.entry_state_machine import assert_transition_allowed

    entry = _seed_pending_entry(ai_db, seeded_client)

    # CPA requests a revision instead of approving outright.
    resp = api_client.post(
        f"/api/v1/cpa/entries/{entry.id}/request-revision",
        json={"rationale": "Please confirm this wasn't a personal expense."},
        headers={"Authorization": f"Bearer {cpa_token}"},
    )
    assert resp.status_code == 200
    refreshed = admin_db.get(ProposedJournalEntry, entry.id)
    assert refreshed.status == EntryStatus.NEEDS_REVISION

    # Intake Bookkeeper re-proposes (needs_revision -> pending_review is AI-only).
    assert_transition_allowed(
        from_status=EntryStatus.NEEDS_REVISION,
        to_status=EntryStatus.PENDING_REVIEW,
        actor_role=seeded_client["intake_user"].role,
    )
    refreshed.status = EntryStatus.PENDING_REVIEW
    admin_db.commit()

    # CPA now approves the re-proposed entry.
    resp = api_client.post(
        f"/api/v1/cpa/entries/{entry.id}/approve",
        json={"rationale": "Confirmed business expense on second look."},
        headers={"Authorization": f"Bearer {cpa_token}"},
    )
    assert resp.status_code == 200
    admin_db.expire_all()
    refreshed = admin_db.get(ProposedJournalEntry, entry.id)
    assert refreshed.status == EntryStatus.APPROVED

    decisions = admin_db.scalars(
        select(ReviewDecision).where(ReviewDecision.entry_id == entry.id).order_by(ReviewDecision.decided_at)
    ).all()
    assert [d.decision.value for d in decisions] == ["revision_required", "approved"]


def test_reject_records_decision_and_does_not_approve(api_client, ai_db, admin_db, seeded_client, cpa_token):
    entry = _seed_pending_entry(ai_db, seeded_client)

    resp = api_client.post(
        f"/api/v1/cpa/entries/{entry.id}/reject",
        json={"rationale": "Not a valid business expense."},
        headers={"Authorization": f"Bearer {cpa_token}"},
    )
    assert resp.status_code == 200
    from app.models.journal_entry import ProposedJournalEntry

    refreshed = admin_db.get(ProposedJournalEntry, entry.id)
    assert refreshed.status == EntryStatus.REJECTED


def test_cannot_approve_an_already_approved_entry_twice(api_client, ai_db, admin_db, seeded_client, cpa_token):
    entry = _seed_pending_entry(ai_db, seeded_client)

    first = api_client.post(
        f"/api/v1/cpa/entries/{entry.id}/approve",
        json={"rationale": "Approved."},
        headers={"Authorization": f"Bearer {cpa_token}"},
    )
    assert first.status_code == 200

    second = api_client.post(
        f"/api/v1/cpa/entries/{entry.id}/approve",
        json={"rationale": "Approved again?"},
        headers={"Authorization": f"Bearer {cpa_token}"},
    )
    assert second.status_code == 409
