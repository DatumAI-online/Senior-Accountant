"""
Section 10.2, test #3: prove that no tool exposed to any agent's Skill
toolset — or referenced anywhere in any agent's system prompts — is an
approval/rejection/posting action. If a future change ever adds an
`approve_entry`-shaped tool to an agent, this test fails before it ships.
"""

import inspect

from app.agents.cpa_review_copilot import skill as copilot_skill
from app.agents.cpa_review_copilot import tools as copilot_tools
from app.agents.intake_bookkeeper import skill as intake_skill
from app.agents.intake_bookkeeper import tools as intake_tools
from app.agents.reconciliation_close import tools as reconciliation_tools
from app.agents.reporting_insights import skill as reporting_skill
from app.agents.reporting_insights import tools as reporting_tools

FORBIDDEN_TOOL_NAMES = {
    "approve_entry",
    "reject_entry",
    "approve_close",
    "approve_deliverable",
    "post_entry",
    "post_journal_entry",
    "request_revision",
    "record_review_decision",
    "start_period_review",
}

# Every agent's actual tool surface — kept as an explicit manifest (rather
# than introspecting the module) so this test documents intent, not just
# implementation.
AGENT_TOOL_MANIFESTS = {
    "intake_bookkeeper": {
        "extract_document_data",
        "classify_transaction",
        "flag_exception",
        "resolve_gl_account",
    },
    "reconciliation_close": {
        "parse_transaction_csv",
        "import_transactions",
        "match_transactions_to_entries",
        "compute_gl_account_balance",
        "run_bank_reconciliation",
        "run_close_checklist",
    },
    "cpa_review_copilot": {
        "prioritize_review_queue",
        "check_evidence_completeness",
        "compare_to_historical_treatment",
        "recommend_review_decision",
    },
    "reporting_insights": {
        "generate_income_statement",
        "generate_balance_sheet",
        "generate_cash_summary",
        "compute_variance",
    },
}

AGENT_TOOL_MODULES = {
    "intake_bookkeeper": intake_tools,
    "reconciliation_close": reconciliation_tools,
    "cpa_review_copilot": copilot_tools,
    "reporting_insights": reporting_tools,
}

AGENT_SYSTEM_PROMPTS = [
    intake_skill.EXTRACTION_SYSTEM_PROMPT,
    intake_skill.CLASSIFICATION_SYSTEM_PROMPT,
    copilot_skill.RECOMMENDATION_SYSTEM_PROMPT,
    reporting_skill.SUMMARY_SYSTEM_PROMPT,
]


def test_every_agent_tool_manifest_excludes_approval_actions():
    for agent_name, manifest in AGENT_TOOL_MANIFESTS.items():
        assert manifest.isdisjoint(FORBIDDEN_TOOL_NAMES), agent_name


def test_every_agent_tools_module_defines_no_forbidden_functions():
    for agent_name, module in AGENT_TOOL_MODULES.items():
        defined_functions = {
            name
            for name, obj in vars(module).items()
            if inspect.isfunction(obj) and obj.__module__ == module.__name__
        }
        assert defined_functions.isdisjoint(FORBIDDEN_TOOL_NAMES), agent_name


def test_agent_system_prompts_never_mention_approval_tools():
    for prompt in AGENT_SYSTEM_PROMPTS:
        for forbidden in FORBIDDEN_TOOL_NAMES:
            assert forbidden not in prompt.lower().replace(" ", "_")


def test_no_agent_pipeline_imports_review_decision_model():
    import app.agents.cpa_review_copilot.agent as copilot_agent
    import app.agents.intake_bookkeeper.agent as intake_agent
    import app.agents.reconciliation_close.agent as reconciliation_agent
    import app.agents.reporting_insights.agent as reporting_agent

    for agent_module in (intake_agent, reconciliation_agent, copilot_agent, reporting_agent):
        assert not hasattr(agent_module, "ReviewDecision"), agent_module.__name__


def test_copilot_recommendation_vocabulary_is_advisory_only():
    """The Copilot's recommendation field is validated against a fixed,
    non-executable vocabulary — confirms recommend/approve/reject text can
    never be mistaken for (or coerced into) an actual state transition."""
    from app.agents.cpa_review_copilot.schemas import RecommendationResult

    schema = RecommendationResult.model_json_schema()
    pattern = schema["properties"]["recommendation"]["pattern"]
    assert pattern == "^(approve|reject|revise|escalate)$"
