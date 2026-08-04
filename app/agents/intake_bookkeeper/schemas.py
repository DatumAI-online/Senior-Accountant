from pydantic import BaseModel, Field


class ExtractedFields(BaseModel):
    """Output of the extract_document_data tool. Deliberately narrow —
    MVP scope covers single-vendor expense documents (invoice/receipt),
    not multi-line itemized statements."""

    vendor: str | None = None
    amount: float = Field(gt=0)
    currency: str = "USD"
    document_date: str | None = None  # ISO 8601 date, best-effort
    description: str
    doc_type_guess: str = "receipt"


class ClassificationResult(BaseModel):
    """Output of the classify_transaction tool. gl_account_code MUST be one
    of the codes offered in the prompt (the client's actual chart of
    accounts) — this is what lets propose_journal_entry deterministically
    validate the account reference instead of fuzzy-matching free text."""

    gl_account_code: str
    confidence: float = Field(ge=0, le=1)
    rationale: str
