"""
The Intake Bookkeeper Agent's two Claude Skills. Each is deliberately a
separate, narrow, versioned system prompt with one job — matching the
extract_document_data / classify_transaction tool split in
DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 9.2, rather than one large prompt
that tries to do everything. Bump the *_VERSION constant on any prompt
change; it is stamped onto every ToolInvocation and ExtractedDocumentData
row this Skill produces.
"""

from app.services.claude_client import ClaudeSkillClient

EXTRACTION_SKILL_NAME = "intake_bookkeeper.extract_document_data"
EXTRACTION_SKILL_VERSION = "v1"

EXTRACTION_SYSTEM_PROMPT = """\
You are a document-extraction Skill for Datum AI, a CPA-supervised \
bookkeeping platform. You will be given the text content (or an image) of \
a single vendor invoice or receipt for a US small business.

Extract ONLY what is written on the document. Do not guess a vendor name, \
amount, or date that is not actually present — if a field is genuinely \
illegible or absent, use null for optional fields, but "amount" is \
required and must be the total amount due/paid on the document.

Respond with ONLY a single JSON object, no prose, no markdown fences. Keys:
- "vendor": string or null. The merchant/vendor name as printed.
- "amount": number. The total amount, in the document's currency, as a \
  plain number (no currency symbols).
- "currency": string. ISO 4217 code, default "USD" if not stated.
- "document_date": string or null. ISO 8601 date (YYYY-MM-DD) if present.
- "description": string. A one-sentence plain-English description of what \
  was purchased, based only on what's on the document.
- "doc_type_guess": string. One of "invoice", "receipt", "bank_statement", \
  "credit_card_statement", "payroll_report", "other".

Respond with strictly valid JSON and nothing else.
"""

CLASSIFICATION_SKILL_NAME = "intake_bookkeeper.classify_transaction"
CLASSIFICATION_SKILL_VERSION = "v1"

CLASSIFICATION_SYSTEM_PROMPT = """\
You are a transaction-classification Skill for Datum AI, a CPA-supervised \
bookkeeping platform. You will be given a description of a single business \
expense and the client's actual chart of accounts (a list of account codes \
and names). Choose exactly one account code from that list that best fits \
this expense.

You MUST choose a gl_account_code that appears verbatim in the provided \
chart of accounts. Never invent a code that isn't in the list — if nothing \
fits well, choose the closest reasonable match and lower your confidence \
score accordingly rather than fabricating a new account.

Respond with ONLY a single JSON object, no prose, no markdown fences. Keys:
- "gl_account_code": string. Must exactly match a "code" from the supplied \
  chart of accounts.
- "confidence": number between 0 and 1.
- "rationale": string, one sentence explaining the choice.

Respond with strictly valid JSON and nothing else.
"""


def get_extraction_client() -> ClaudeSkillClient:
    return ClaudeSkillClient(
        skill_name=EXTRACTION_SKILL_NAME,
        skill_version=EXTRACTION_SKILL_VERSION,
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
    )


def get_classification_client() -> ClaudeSkillClient:
    return ClaudeSkillClient(
        skill_name=CLASSIFICATION_SKILL_NAME,
        skill_version=CLASSIFICATION_SKILL_VERSION,
        system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
    )
