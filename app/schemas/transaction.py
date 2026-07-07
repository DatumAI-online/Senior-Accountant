"""
Pydantic schemas for the transaction classification endpoint.
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class TransactionIn(BaseModel):
    """A single financial transaction submitted for classification."""

    description: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Raw transaction description, e.g. 'UBER TRIP 04-12 SAN FRANCISCO'",
        examples=["AWS SERVICES INVOICE #4471"],
    )
    amount: float = Field(
        ...,
        description="Transaction amount. Positive for expenses/charges, negative for refunds/credits.",
        examples=[249.99],
    )
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code.",
    )
    merchant: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Merchant or vendor name, if known separately from the description.",
    )
    transaction_date: Optional[date] = Field(
        default=None,
        description="Date the transaction occurred (ISO 8601).",
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Any additional context supplied by the user (e.g. business purpose).",
    )

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:
        return v.upper()


class TransactionClassification(BaseModel):
    """Structured classification result returned by the Skill Brain."""

    category: str = Field(
        ...,
        description="Best-fit accounting category, e.g. 'Software & Subscriptions'.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence in the classification, from 0.0 to 1.0.",
    )
    tax_deductible: bool = Field(
        ...,
        description="Whether the transaction is likely tax-deductible as a business expense.",
    )
    reason: str = Field(
        ...,
        description="Short human-readable explanation for the category and deductibility decision.",
    )


class ClassifyResponse(BaseModel):
    """Top-level API response envelope."""

    transaction: TransactionIn
    classification: TransactionClassification
    model: str = Field(..., description="Claude model used for classification.")
