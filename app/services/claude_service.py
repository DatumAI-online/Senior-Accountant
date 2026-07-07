"""
Thin wrapper around the Anthropic Claude API.

Responsible for:
- Building the classification prompt
- Calling the Messages API with a forced-JSON instruction
- Parsing and validating Claude's response into our schema
- Raising clean, typed exceptions the API layer can translate to HTTP errors
"""

import json
import logging
import re

import anthropic
from anthropic import APIConnectionError, APIStatusError, APITimeoutError

from app.core.config import get_settings
from app.schemas.transaction import TransactionClassification, TransactionIn

logger = logging.getLogger(__name__)

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
    """Encapsulates all interaction with the Anthropic API for classification."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            logger.warning(
                "ANTHROPIC_API_KEY is not set. Requests to Claude will fail."
            )
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_model
        self._max_tokens = settings.claude_max_tokens

    def _build_user_prompt(self, transaction: TransactionIn) -> str:
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

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """
        Extract a JSON object from Claude's raw text output.

        Claude is instructed to return pure JSON, but this defensively strips
        markdown code fences if the model adds them anyway.
        """
        text = raw_text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            # Fall back to grabbing the first {...} block in the text.
            brace_match = re.search(r"\{.*\}", text, re.DOTALL)
            if brace_match:
                try:
                    return json.loads(brace_match.group(0))
                except json.JSONDecodeError:
                    pass
            raise ClaudeServiceError(
                f"Could not parse JSON from Claude response: {exc}"
            ) from exc

    def classify(self, transaction: TransactionIn) -> TransactionClassification:
        """Call Claude to classify a transaction and return a validated result."""
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": self._build_user_prompt(transaction)}
                ],
            )
        except APITimeoutError as exc:
            raise ClaudeServiceError("Claude API request timed out.") from exc
        except APIConnectionError as exc:
            raise ClaudeServiceError("Could not connect to Claude API.") from exc
        except APIStatusError as exc:
            raise ClaudeServiceError(
                f"Claude API returned an error status {exc.status_code}: {exc.message}"
            ) from exc

        text_blocks = [
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ]
        raw_text = "".join(text_blocks).strip()
        if not raw_text:
            raise ClaudeServiceError("Claude returned an empty response.")

        parsed = self._extract_json(raw_text)

        try:
            return TransactionClassification.model_validate(parsed)
        except Exception as exc:  # pydantic ValidationError, etc.
            raise ClaudeServiceError(
                f"Claude response did not match expected schema: {exc}"
            ) from exc


def get_claude_service() -> ClaudeClassificationService:
    """FastAPI dependency factory for the Claude service."""
    return ClaudeClassificationService()
