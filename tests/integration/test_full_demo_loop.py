"""
The Phase 1 demonstration loop, end to end, exactly as described in
DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 16 ("Phase 1 — Demonstration
MVP"): a client uploads an invoice and a bank transaction, the Intake
Bookkeeper proposes an entry, the Reconciliation & Close Agent reconciles
the account and marks the period ready for CPA review, the CPA Review
Copilot drafts a recommendation, a human CPA approves the entry and the
close, the Reporting & Insights Agent generates statements and a summary,
and the CPA approves the client deliverable.

Every HTTP call in this test goes through the real FastAPI app (TestClient)
and the real Postgres roles (ai_service / cpa_service) — only the Claude
API calls are mocked. This is the single test that proves the whole
pipeline holds together, not just each agent in isolation.
"""

from unittest.mock import patch

from app.services.claude_client import ClaudeSkillResult


def _extraction_result():
    return ClaudeSkillResult(
        data={
            "vendor": "Notion Labs",
            "amount": 24.00,
            "currency": "USD",
            "document_date": "2026-07-03",
            "description": "Notion software subscription for July 2026",
            "doc_type_guess": "receipt",
        },
        raw_text="{}",
        model="claude-sonnet-4-6",
        skill_name="intake_bookkeeper.extract_document_data",
        skill_version="v1",
        duration_ms=100,
    )


def _classification_result():
    return ClaudeSkillResult(
        data={"gl_account_code": "6100", "confidence": 0.93, "rationale": "SaaS subscription expense."},
        raw_text="{}",
        model="claude-sonnet-4-6",
        skill_name="intake_bookkeeper.classify_transaction",
        skill_version="v1",
        duration_ms=80,
    )


def _recommendation_result():
    return ClaudeSkillResult(
        data={
            "recommendation": "approve",
            "confidence": 0.9,
            "rationale": "Evidence complete, matches historical software-subscription pattern.",
        },
        raw_text="{}",
        model="claude-sonnet-4-6",
        skill_name="cpa_review_copilot.recommend_review_decision",
        skill_version="v1",
        duration_ms=70,
    )


def _executive_summary_result():
    return ClaudeSkillResult(
        data={
            "summary_text": (
                "Riverside Consulting LLC recorded modest software spend this period. "
                "No material variances were identified against the prior period."
            ),
            "action_items": [
                {"text": "Review software subscriptions for unused seats.", "category": "expenses"},
            ],
        },
        raw_text="{}",
        model="claude-sonnet-4-6",
        skill_name="reporting_insights.draft_executive_summary",
        skill_version="v1",
        duration_ms=150,
    )


def test_full_phase1_demo_loop(api_client, seeded_client, intake_token, reconciliation_token, copilot_token, cpa_token, reporting_token):
    client_id = str(seeded_client["client"].id)
    period_id = str(seeded_client["period"].id)
    financial_account_id = str(seeded_client["financial_account"].id)

    # --- 1. Client uploads an invoice; Intake Bookkeeper proposes an entry ---
    with patch("app.agents.intake_bookkeeper.tools.get_extraction_client") as mock_extract, patch(
        "app.agents.intake_bookkeeper.tools.get_classification_client"
    ) as mock_classify:
        mock_extract.return_value.call.return_value = _extraction_result()
        mock_classify.return_value.call.return_value = _classification_result()

        resp = api_client.post(
            "/api/v1/agent/intake/documents",
            headers={"Authorization": f"Bearer {intake_token}"},
            data={
                "client_id": client_id,
                "period_id": period_id,
                "doc_type": "receipt",
                "raw_text": "Notion Labs receipt for $24.00 dated 2026-07-03",
            },
        )
    assert resp.status_code == 200, resp.text
    intake_body = resp.json()
    assert intake_body["entry"]["status"] == "pending_review"
    entry_id = intake_body["entry"]["id"]

    # --- 2. Client's bank feed is imported (matching the entry's amount) ---
    resp = api_client.post(
        "/api/v1/agent/reconciliation/transactions/import",
        headers={"Authorization": f"Bearer {reconciliation_token}"},
        json={
            "financial_account_id": financial_account_id,
            "csv_text": "date,amount,description\n2026-07-03,-24.00,NOTION LABS SUBSCRIPTION\n",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported_count"] == 1

    # --- 3. Reconciliation & Close Agent reconciles and marks the period ready ---
    resp = api_client.post(
        "/api/v1/agent/reconciliation/run",
        headers={"Authorization": f"Bearer {reconciliation_token}"},
        params={"client_id": client_id, "period_id": period_id},
    )
    assert resp.status_code == 200, resp.text
    recon_body = resp.json()
    assert recon_body["checklist"]["ready"] is True
    assert recon_body["close_status"] == "ready_for_cpa_review"

    # --- 4. CPA Review Copilot drafts a recommendation (advisory only) ---
    with patch("app.agents.cpa_review_copilot.tools.get_recommendation_client") as mock_rec:
        mock_rec.return_value.call.return_value = _recommendation_result()
        resp = api_client.get(
            "/api/v1/agent/copilot/recommendations",
            headers={"Authorization": f"Bearer {copilot_token}"},
            params={"client_id": client_id, "period_id": period_id},
        )
    assert resp.status_code == 200, resp.text
    recs = resp.json()["items"]
    assert len(recs) == 1
    assert recs[0]["recommendation"] == "approve"

    # --- 5. Human CPA approves the entry ---
    resp = api_client.post(
        f"/api/v1/cpa/entries/{entry_id}/approve",
        headers={"Authorization": f"Bearer {cpa_token}"},
        json={"rationale": "Evidence checked; matches Copilot recommendation."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_status"] == "approved"

    # --- 6. CPA opens the review queue and approves the close ---
    resp = api_client.post(
        f"/api/v1/cpa/periods/{period_id}/start-review",
        headers={"Authorization": f"Bearer {cpa_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["close_status"] == "under_cpa_review"

    resp = api_client.post(
        f"/api/v1/cpa/periods/{period_id}/approve-close",
        headers={"Authorization": f"Bearer {cpa_token}"},
        json={"rationale": "All entries reviewed, reconciliation clean."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["close_status"] == "approved"

    # --- 7. Reporting & Insights Agent generates statements + summary ---
    with patch("app.agents.reporting_insights.agent.get_summary_client") as mock_get_summary_client:
        mock_get_summary_client.return_value.call.return_value = _executive_summary_result()
        resp = api_client.post(
            "/api/v1/agent/reporting/generate",
            headers={"Authorization": f"Bearer {reporting_token}"},
            params={"client_id": client_id, "period_id": period_id},
        )
    assert resp.status_code == 200, resp.text
    report_body = resp.json()
    assert report_body["executive_summary_text"] == _executive_summary_result().data["summary_text"]
    assert len(report_body["action_items"]) == 1

    # --- 8. CPA approves the client-facing deliverable ---
    resp = api_client.post(
        f"/api/v1/cpa/periods/{period_id}/approve-deliverable",
        headers={"Authorization": f"Bearer {cpa_token}"},
        json={"rationale": "Reviewed statements and summary; approved for delivery."},
    )
    assert resp.status_code == 200, resp.text
    deliverable_body = resp.json()
    assert deliverable_body["close_status"] == "delivered"
    assert len(deliverable_body["approved_report_ids"]) == 3
    assert deliverable_body["approved_summary_id"] is not None


def test_reporting_agent_refuses_to_run_before_close_is_approved(
    api_client, seeded_client, reporting_token
):
    """The Reporting Agent must hard-refuse if the CPA hasn't approved the
    close yet — even if entries exist, even if called directly."""
    resp = api_client.post(
        "/api/v1/agent/reporting/generate",
        headers={"Authorization": f"Bearer {reporting_token}"},
        params={"client_id": str(seeded_client["client"].id), "period_id": str(seeded_client["period"].id)},
    )
    assert resp.status_code == 409
