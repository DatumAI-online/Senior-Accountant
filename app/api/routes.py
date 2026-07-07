"""
API routes for the Skill Brain service.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.transaction import ClassifyResponse, TransactionIn
from app.services.claude_service import (
    ClaudeClassificationService,
    ClaudeServiceError,
    get_claude_service,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", tags=["system"], summary="Health check")
def health_check() -> dict:
    """Simple liveness/readiness probe."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.post(
    "/classify",
    response_model=ClassifyResponse,
    tags=["skill-brain"],
    summary="Classify a financial transaction",
)
def classify_transaction(
    transaction: TransactionIn,
    claude_service: ClaudeClassificationService = Depends(get_claude_service),
) -> ClassifyResponse:
    """
    Classify a single financial transaction using Claude.

    Returns the transaction category, confidence score, tax-deductibility
    verdict, and a short human-readable reason.
    """
    settings = get_settings()

    try:
        classification = claude_service.classify(transaction)
    except ClaudeServiceError as exc:
        logger.error("Claude classification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Classification failed: {exc}",
        ) from exc

    return ClassifyResponse(
        transaction=transaction,
        classification=classification,
        model=settings.claude_model,
    )
