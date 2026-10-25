import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.security import AnyUser, create_access_token, verify_password

logger = logging.getLogger("orderflow")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> TokenResponse:
    settings: Settings = request.app.state.settings
    user = session.scalars(select(User).where(User.email == body.email.lower())).one_or_none()
    # An unknown email is still checked against a real hash, so it takes about
    # as long as a wrong password and returns the same message.
    stored_hash = user.password_hash if user else request.app.state.dummy_password_hash
    password_ok = verify_password(body.password, stored_hash)
    if user is None or not password_ok or not user.is_active:
        logger.info(
            "Login rejected request_id=%s", getattr(request.state, "request_id", "-")
        )
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return TokenResponse(
        access_token=create_access_token(user, settings),
        expires_in=settings.access_token_minutes * 60,
    )


@router.get("/me", response_model=UserOut)
def who_am_i(user: AnyUser) -> User:
    return user
