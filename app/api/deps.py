"""
FastAPI dependencies that tie a request's authenticated role to *which
Postgres role its database session connects as*.

This is the application-level half of the Section 10 control; the
database-level half (the actual GRANT/REVOKE state and the approval-guard
trigger) lives in alembic/versions/0002_security_roles_and_grants.py and
does not depend on this file being correct. get_ai_db() and get_cpa_db()
are deliberately separate dependencies rather than one parameterized
function, so a route's required role is visible from its signature alone
and greppable by tests/security/test_api_surface.py.
"""

from collections.abc import Generator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import TokenPayload, decode_access_token
from app.db.session import AiServiceSessionLocal, CpaServiceSessionLocal
from app.models.enums import UserRole

_bearer_scheme = HTTPBearer(auto_error=True)

AI_AGENT_ROLES = (
    UserRole.AI_INTAKE,
    UserRole.AI_RECONCILIATION,
    UserRole.AI_COPILOT,
    UserRole.AI_REPORTING,
)


def get_current_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> TokenPayload:
    try:
        return decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def require_role(*roles: UserRole):
    """Dependency factory: 403s unless the token's role is in `roles`."""

    def _dependency(token: TokenPayload = Depends(get_current_token)) -> TokenPayload:
        if token.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires role in {[r.value for r in roles]}",
            )
        return token

    return _dependency


require_ai_agent = require_role(*AI_AGENT_ROLES)
require_cpa = require_role(UserRole.CPA)


def get_ai_db(
    token: TokenPayload = Depends(require_ai_agent),
) -> Generator[Session, None, None]:
    """Yields a session bound to the datumai_ai_service Postgres role. Only
    reachable by a token whose role is one of the four AI agent roles."""
    db = AiServiceSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_cpa_db(
    token: TokenPayload = Depends(require_cpa),
) -> Generator[Session, None, None]:
    """Yields a session bound to the datumai_cpa_service Postgres role. Only
    reachable by a token whose role is exactly 'cpa' — this is the only
    dependency in the codebase that yields a session capable of writing an
    approved/rejected/posted ReviewDecision."""
    db = CpaServiceSessionLocal()
    try:
        yield db
    finally:
        db.close()
