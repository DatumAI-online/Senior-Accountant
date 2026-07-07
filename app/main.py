"""
Application entrypoint.

Run locally with:
    uvicorn app.main:app --reload
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Datum Skill Brain — an AI accounting API that classifies financial "
        "transactions using Claude, returning category, confidence, "
        "tax-deductibility, and reasoning."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/", tags=["system"], summary="Root")
def root() -> dict:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
    }
