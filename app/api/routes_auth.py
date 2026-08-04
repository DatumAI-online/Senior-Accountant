"""Human login only. AI service accounts never authenticate through this
router — they hold a long-lived token minted once by scripts/seed_dev.py.
This is a deliberate asymmetry: see app/core/security.py."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.db.session import get_auth_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_auth_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))

    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
    )

    if user is None or user.is_service_account or not user.is_active:
        raise invalid_credentials
    if not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise invalid_credentials

    token = create_access_token(
        user_id=user.id, email=user.email, role=user.role, is_service_account=False
    )
    return TokenResponse(access_token=token, role=user.role.value)
