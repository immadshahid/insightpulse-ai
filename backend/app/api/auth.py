"""POST /auth/register, POST /auth/login, POST /auth/firebase (Google sign-in)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.firebase import FirebaseTokenError, verify_firebase_token
from app.core.ratelimit import AttemptLimiter, TooManyAttemptsError
from app.core.security import AuthError, AuthProvider, password_problem
from app.db import get_db
from app.deps import get_auth
from app.schemas import FirebaseLoginIn, LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# 10 wrong passwords per account, or 30 failed sign-ins from one address, per 15 minutes.
LOGIN_FAILURES = AttemptLimiter(limit=10, window=15 * 60)
IP_FAILURES = AttemptLimiter(limit=30, window=15 * 60)
# At most 10 new accounts from one address per hour.
SIGNUPS = AttemptLimiter(limit=10, window=60 * 60)


def _ip(request: Request) -> str:
    return f"ip:{request.client.host if request.client else 'unknown'}"


def _too_many(exc: TooManyAttemptsError) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        exc.message,
        headers={"Retry-After": str(int(exc.retry_after) + 1)},
    )


def _token(auth: AuthProvider, user) -> TokenOut:
    return TokenOut(access_token=auth.issue_token(user), user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthProvider = Depends(get_auth),
) -> TokenOut:
    """Create an account and return an access token."""
    problem = password_problem(body.password, body.email)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    try:
        SIGNUPS.check(_ip(request))
        user = auth.register(db, body.email, body.password)
    except TooManyAttemptsError as exc:
        raise _too_many(exc) from exc
    except AuthError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    SIGNUPS.fail(_ip(request))  # counts every new account, not only failures
    return _token(auth, user)


@router.post("/login", response_model=TokenOut)
def login(
    body: LoginIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthProvider = Depends(get_auth),
) -> TokenOut:
    """Exchange email + password for an access token."""
    account, ip = f"email:{body.email.strip().lower()}", _ip(request)
    try:
        LOGIN_FAILURES.check(account)
        IP_FAILURES.check(ip)
        user = auth.authenticate(db, body.email, body.password)
    except TooManyAttemptsError as exc:
        raise _too_many(exc) from exc
    except AuthError as exc:
        LOGIN_FAILURES.fail(account)
        IP_FAILURES.fail(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    LOGIN_FAILURES.reset(account)
    return _token(auth, user)


@router.post("/firebase", response_model=TokenOut)
def firebase_login(
    body: FirebaseLoginIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthProvider = Depends(get_auth),
) -> TokenOut:
    """Sign in (or sign up) with a Firebase ID token from Google sign-in."""
    project_id = get_settings().firebase_project_id
    if not project_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Google sign-in isn't set up on this server yet."
        )
    ip = _ip(request)
    try:
        IP_FAILURES.check(ip)
        identity = verify_firebase_token(body.id_token, project_id)
    except TooManyAttemptsError as exc:
        raise _too_many(exc) from exc
    except FirebaseTokenError as exc:
        IP_FAILURES.fail(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return _token(auth, auth.user_for_verified_email(db, identity.email))
