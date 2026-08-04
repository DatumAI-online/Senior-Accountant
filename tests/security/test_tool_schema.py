"""
Section 10.2, test #3: prove that no tool exposed to the Intake Bookkeeper
Skill's toolset — or referenced anywhere in its system prompts — is an
approval/rejection/posting action. If a future change ever adds an
`approve_entry`-shaped tool to an agent, this test fails before it ships.
"""

from app.agents.intake_bookkeeper import skill as intake_skill
from app.agents.intake_bookkeeper import tools as intake_tools

FORBIDDEN_TOOL_NAMES = {
    "approve_entry",
    "reject_entry",
    "approve_close",
    "approve_deliverable",
    "post_entry",
    "post_journal_entry",
    "request_revision",
    "record_review_decision",
}

# The Intake Bookkeeper's actual tool surface — every function in
# app/agents/intake_bookkeeper/tools.py that performs a distinct, named
# action. Kept as an explicit manifest (rather than introspecting the
# module) so this test documents intent, not just implementation.
INTAKE_BOOKKEEPER_TOOL_NAMES = {
    "extract_document_data",
    "classify_transaction",
    "flag_exception",
    "resolve_gl_account",
}


def test_intake_bookkeeper_tool_manifest_excludes_approval_actions():
    assert INTAKE_BOOKKEEPER_TOOL_NAMES.isdisjoint(FORBIDDEN_TOOL_NAMES)


def test_intake_bookkeeper_tools_module_defines_no_forbidden_functions():
    defined_functions = {
        name
        for name, obj in vars(intake_tools).items()
        if callable(obj) and getattr(obj, "__module__", None) == intake_tools.__name__
    }
    assert defined_functions.isdisjoint(FORBIDDEN_TOOL_NAMES)


def test_intake_bookkeeper_system_prompts_never_mention_approval_tools():
    prompts = [intake_skill.EXTRACTION_SYSTEM_PROMPT, intake_skill.CLASSIFICATION_SYSTEM_PROMPT]
    for prompt in prompts:
        for forbidden in FORBIDDEN_TOOL_NAMES:
            assert forbidden not in prompt.lower().replace(" ", "_")


def test_agent_pipeline_never_imports_review_decision_model():
    import app.agents.intake_bookkeeper.agent as agent_module

    assert not hasattr(agent_module, "ReviewDecision")
