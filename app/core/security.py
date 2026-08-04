"""
JWT issuance/verification and password hashing.

Two token lifetimes by design: human CPA sessions expire quickly (default
60 min, forcing re-login), while AI service-account tokens are minted once
by the bootstrap seed script with a long expiry, since they represent a
process credential (an agent worker), not an interactive session. In a real
deployment these would be rotated via a secrets manager — see
DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 10.1's "Secrets management" note.

This module intentionally does NOT decide *authorization* (what a role may
do) — see app/api/deps.py for that. It only proves *who is asking* and
signs/verifies that claim. Authorization is layered on top by FastAPI
dependencies and, ultimately, by the Postgres grants in
alembic/versions/0002_security_roles_and_grants.py — a bug here can make a
request get rejected incorrectly, but it cannot forge the database-level
guarantee that AI credentials can't approve anything.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.core.config import get_settings
from app.models.enums import UserRole

settings = get_settings()
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# AI service-account tokens live much longer than human sessions — they are
# a rotated process credential, not something re-issued on every request.
SERVICE_ACCOUNT_TOKEN_MINUTES = 60 * 24 * 30  # 30 days


class TokenPayload(BaseModel):
    sub: str
    email: str
    role: UserRole
    is_service_account: bool


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(password, hashed_password)


def create_access_token(
    *,
    user_id: uuid.UUID,
    email: str,
    role: UserRole,
    is_service_account: bool,
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    default_minutes = SERVICE_ACCOUNT_TOKEN_MINUTES if is_service_account else settings.jwt_expire_minutes
    expire = now + timedelta(minutes=expires_minutes or default_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role.value,
        "is_service_account": is_service_account,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenPayload:
    """Raises jwt.PyJWTError (expired/invalid signature/malformed) — callers
    must catch that and turn it into a 401, never a silent pass-through."""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return TokenPayload(
        sub=payload["sub"],
        email=payload["email"],
        role=UserRole(payload["role"]),
        is_service_account=payload["is_service_account"],
    )
