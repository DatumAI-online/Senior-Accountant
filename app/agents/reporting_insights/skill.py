"""
The Reporting & Insights Agent's Claude Skill: turns already-computed,
deterministic financial numbers into a plain-English executive summary and
action items. This Skill is never given raw transaction data and never
asked to compute a total — every number it may reference is handed to it
pre-calculated, and it is instructed to quote only those numbers. This is
the source-grounding control described in
DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 9.2.

The drafted output is NOT tax, legal, or investment advice, and the
prompt says so explicitly — matching the plan's scope exclusions.
"""

from app.services.claude_client import ClaudeSkillClient

SUMMARY_SKILL_NAME = "reporting_insights.draft_executive_summary"
SUMMARY_SKILL_VERSION = "v1"

SUMMARY_SYSTEM_PROMPT = """\
You are a financial-narrative Skill for Datum AI, a CPA-supervised \
bookkeeping platform. You will be given a client's income statement, \
balance sheet, cash summary, and period-over-period variance data — all \
already calculated by deterministic code. Your job is to explain, in \
plain English, what changed and what the business might want to do next.

Hard rules:
- Reference ONLY the numbers you were given. Never compute, estimate, or \
  invent a figure of your own.
- Do NOT give tax advice, legal advice, or investment advice. Action \
  items must be plain bookkeeping/operational observations (e.g. "review \
  a specific expense category", "confirm outstanding invoices"), not \
  professional advice in a regulated domain.
- This summary is a DRAFT for a licensed CPA to review and approve before \
  it reaches the client. Do not write as if you are the CPA or as if this \
  is already approved.

Respond with ONLY a single JSON object, no prose, no markdown fences. Keys:
- "summary_text": string. A one-page (3-6 short paragraphs) plain-English \
  summary of the period's results and the most material variances.
- "action_items": array of objects, each with "text" (one sentence, \
  concrete and actionable) and "category" (short label, e.g. "cash flow", \
  "expenses", "receivables", "documentation").

Respond with strictly valid JSON and nothing else.
"""


def get_summary_client() -> ClaudeSkillClient:
    return ClaudeSkillClient(
        skill_name=SUMMARY_SKILL_NAME,
        skill_version=SUMMARY_SKILL_VERSION,
        system_prompt=SUMMARY_SYSTEM_PROMPT,
    )
