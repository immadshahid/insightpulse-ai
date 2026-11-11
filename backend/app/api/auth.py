"""POST /auth/register, POST /auth/login."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import AuthError, AuthProvider
from app.db import get_db
from app.deps import get_auth
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterIn, db: Session = Depends(get_db), auth: AuthProvider = Depends(get_auth)
) -> TokenOut:
    """Create an account and return an access token."""
    try:
        user = auth.register(db, body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return TokenOut(access_token=auth.issue_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(
    body: LoginIn, db: Session = Depends(get_db), auth: AuthProvider = Depends(get_auth)
) -> TokenOut:
    """Exchange email + password for an access token."""
    try:
        user = auth.authenticate(db, body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return TokenOut(access_token=auth.issue_token(user), user=UserOut.model_validate(user))
