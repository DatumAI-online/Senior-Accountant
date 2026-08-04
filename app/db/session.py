"""
Three separate SQLAlchemy engines, one per Postgres role.

This is the load-bearing piece of the "AI can never approve its own work"
control: a request handled under the AI-service session literally cannot
open a connection with the grants needed to write an approved/rejected/
posted status, independent of anything the application code does. See
DATUM_AI_BOOKKEEPING_TEAM_PLAN.md, Section 10.

- admin engine: used only by Alembic migrations and the seed script.
  Never imported by request-handling code.
- ai_service engine: used by all four agent routes/services.
- cpa_service engine: used only by CPA-facing review/approval routes.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

admin_engine = create_engine(settings.admin_database_url, pool_pre_ping=True)
ai_service_engine = create_engine(settings.ai_service_database_url, pool_pre_ping=True)
cpa_service_engine = create_engine(settings.cpa_service_database_url, pool_pre_ping=True)

AdminSessionLocal = sessionmaker(bind=admin_engine, autoflush=False, expire_on_commit=False)
AiServiceSessionLocal = sessionmaker(bind=ai_service_engine, autoflush=False, expire_on_commit=False)
CpaServiceSessionLocal = sessionmaker(bind=cpa_service_engine, autoflush=False, expire_on_commit=False)


def get_ai_db() -> Generator[Session, None, None]:
    db = AiServiceSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_cpa_db() -> Generator[Session, None, None]:
    db = CpaServiceSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_admin_db() -> Generator[Session, None, None]:
    """Only for bootstrap/seed scripts — never wire this into a FastAPI route."""
    db = AdminSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_auth_db() -> Generator[Session, None, None]:
    """Used only by the unauthenticated /auth/login endpoint to look up a
    user by email before a role is known. Bound to the cpa_service engine,
    which holds read-only SELECT on `users` — sufficient for a login lookup
    and nothing more; login never writes anything."""
    db = CpaServiceSessionLocal()
    try:
        yield db
    finally:
        db.close()
