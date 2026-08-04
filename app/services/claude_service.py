"""
Transaction classification, now implemented on top of the shared
ClaudeSkillClient (app/services/claude_client.py) instead of calling the
Anthropic SDK directly. Public interface (ClaudeClassificationService,
ClaudeServiceError, get_claude_service) is unchanged so the existing
/api/v1/classify route keeps working as-is.

This is the first Skill in the codebase, versioned as "transaction_
classification" v1 — the reference pattern the Intake Bookkeeper agent's
own Skills (app/agents/intake_bookkeeper/skill.py) follow.
"""

import json
import logging

from app.core.config import get_settings
from app.schemas.transaction import TransactionClassification, TransactionIn
from app.services.claude_client import ClaudeSkillClient, ClaudeSkillError

logger = logging.getLogger(__name__)

SKILL_NAME = "transaction_classification"
SKILL_VERSION = "v1"

SYSTEM_PROMPT = """\
You are an expert bookkeeper and tax accountant AI embedded in an accounting \
platform called Datum. Your job is to classify a single financial transaction \
for small-business bookkeeping purposes.

You must respond with ONLY a single JSON object, no prose, no markdown code \
fences, and no explanation outside the JSON. The JSON object must have \
exactly these keys:

- "category": string. A concise accounting category (e.g. "Software & \
  Subscriptions", "Meals & Entertainment", "Travel", "Office Supplies", \
  "Professional Services", "Payroll", "Rent & Utilities", "Bank Fees", \
  "Marketing & Advertising", "Equipment", "Income", "Personal / Non-business", \
  "Other").
- "confidence": number between 0 and 1 representing how confident you are.
- "tax_deductible": boolean. Whether this is likely a deductible business \
  expense under general US small-business tax rules. Use false for personal, \
  income, or clearly non-deductible items.
- "reason": string, one or two sentences explaining the category and \
  deductibility decision in plain language.

Respond with strictly valid JSON and nothing else.
"""


class ClaudeServiceError(Exception):
    """Raised when the Claude API call fails or returns unusable output."""


class ClaudeClassificationService:
    """Encapsulates all interaction with Claude for transaction classification."""

    def __init__(self) -> None:
        settings = get_settings()
        self._skill = ClaudeSkillClient(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            system_prompt=SYSTEM_PROMPT,
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
        )

    @staticmethod
    def _build_user_prompt(transaction: TransactionIn) -> str:
        fields = {
            "description": transaction.description,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "merchant": transaction.merchant,
            "transaction_date": (
                transaction.transaction_date.isoformat()
                if transaction.transaction_date
                else None
            ),
            "notes": transaction.notes,
        }
        return (
            "Classify the following transaction. Transaction data (JSON):\n"
            f"{json.dumps(fields, indent=2)}"
        )

    def classify(self, transaction: TransactionIn) -> TransactionClassification:
        """Call Claude to classify a transaction and return a validated result."""
        content_blocks = [{"type": "text", "text": self._build_user_prompt(transaction)}]
        try:
            result = self._skill.call(content_blocks)
        except ClaudeSkillError as exc:
            raise ClaudeServiceError(str(exc)) from exc

        try:
            return TransactionClassification.model_validate(result.data)
        except Exception as exc:  # pydantic ValidationError, etc.
            raise ClaudeServiceError(
                f"Claude response did not match expected schema: {exc}"
            ) from exc


def get_claude_service() -> ClaudeClassificationService:
    """FastAPI dependency factory for the Claude service."""
    return ClaudeClassificationService()
