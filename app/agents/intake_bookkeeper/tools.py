"""
The Intake Bookkeeper Agent's tools. Each function here corresponds to one
row in the tool table in DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 9.2.
Everything that touches the database or does arithmetic is plain
deterministic Python; only extract_document_data and classify_transaction
call Claude, and their output is validated (schema, then business rules)
before anything is persisted.

None of these functions can move a ProposedJournalEntry into an approved,
rejected, posted, or reversed state — that verb does not exist in this
module. See app/api/routes_cpa_review.py for the only code path that can.
"""

import base64
import io
from uuid import UUID

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.common.tools import flag_exception, log_audit_event, log_tool_invocation, utcnow
from app.agents.intake_bookkeeper.schemas import ClassificationResult, ExtractedFields
from app.agents.intake_bookkeeper.skill import get_classification_client, get_extraction_client
from app.models.accounting_period import GLAccount
from app.services.claude_client import ClaudeSkillError

__all__ = [
    "DocumentTextExtractionError",
    "build_document_content_blocks",
    "extract_document_data",
    "classify_transaction",
    "resolve_gl_account",
    "flag_exception",
    "log_audit_event",
    "log_tool_invocation",
    "utcnow",
]


class DocumentTextExtractionError(Exception):
    """Raised when the raw file content can't even be turned into text/
    image content blocks — distinct from a Claude extraction failure."""


def build_document_content_blocks(
    *, raw_text: str | None, file_bytes: bytes | None, mime_type: str | None
) -> list[dict]:
    """Text documents are sent as-is. PDFs are converted to text locally
    (deterministic, no dependency on a specific Claude model's PDF support).
    Images are sent as native Claude vision content blocks."""
    if raw_text is not None:
        return [{"type": "text", "text": raw_text}]

    if file_bytes is None or mime_type is None:
        raise DocumentTextExtractionError("No document content provided.")

    if mime_type == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except Exception as exc:  # pypdf raises various exceptions for corrupt PDFs
            raise DocumentTextExtractionError(f"Could not read PDF: {exc}") from exc
        if not text:
            raise DocumentTextExtractionError("PDF contained no extractable text.")
        return [{"type": "text", "text": text}]

    if mime_type.startswith("image/"):
        b64 = base64.b64encode(file_bytes).decode("ascii")
        return [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": mime_type, "data": b64},
            }
        ]

    raise DocumentTextExtractionError(f"Unsupported document mime type: {mime_type}")


def extract_document_data(content_blocks: list[dict]) -> tuple[ExtractedFields, dict]:
    """Returns (validated fields, tool-invocation metadata dict)."""
    client = get_extraction_client()
    try:
        result = client.call(content_blocks)
    except ClaudeSkillError as exc:
        raise
    fields = ExtractedFields.model_validate(result.data)
    invocation_meta = {
        "tool_name": "extract_document_data",
        "output_json": result.data,
        "model": result.model,
        "skill_version": result.skill_version,
        "duration_ms": result.duration_ms,
    }
    return fields, invocation_meta


def classify_transaction(
    *, description: str, chart_of_accounts: list[GLAccount]
) -> tuple[ClassificationResult, dict]:
    coa_payload = [
        {"code": acct.code, "name": acct.name, "type": acct.account_type.value}
        for acct in chart_of_accounts
        if acct.is_active
    ]
    content_blocks = [
        {
            "type": "text",
            "text": (
                f"Expense description: {description}\n\n"
                f"Chart of accounts (JSON):\n{coa_payload}"
            ),
        }
    ]
    client = get_classification_client()
    result = client.call(content_blocks)
    classification = ClassificationResult.model_validate(result.data)
    invocation_meta = {
        "tool_name": "classify_transaction",
        "output_json": result.data,
        "model": result.model,
        "skill_version": result.skill_version,
        "duration_ms": result.duration_ms,
    }
    return classification, invocation_meta


def resolve_gl_account(db: Session, *, client_id: UUID, code: str) -> GLAccount | None:
    return db.scalar(
        select(GLAccount).where(
            GLAccount.client_id == client_id, GLAccount.code == code, GLAccount.is_active == True  # noqa: E712
        )
    )
