"""Authentication behind a provider interface (local JWT now, Firebase later)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User


class AuthError(Exception):
    """Invalid credentials or token."""


class AuthProvider(Protocol):
    """What the API needs from an auth backend."""

    def register(self, db: Session, email: str, password: str) -> User: ...
    def authenticate(self, db: Session, email: str, password: str) -> User: ...
    def issue_token(self, user: User) -> str: ...
    def user_id_from_token(self, token: str) -> str: ...


def hash_password(password: str) -> str:
    """bcrypt hash (passwords are truncated to bcrypt's 72-byte limit)."""
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time bcrypt check."""
    try:
        return bcrypt.checkpw(password.encode()[:72], password_hash.encode())
    except ValueError:
        return False


class LocalJWTAuth:
    """Email/password accounts in our DB, HS256 JWT access tokens."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def register(self, db: Session, email: str, password: str) -> User:
        """Create an account; raises AuthError if the email is taken."""
        email = email.strip().lower()
        if db.scalar(select(User).where(User.email == email)):
            raise AuthError("An account with this email already exists.")
        user = User(email=email, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        return user

    def authenticate(self, db: Session, email: str, password: str) -> User:
        """Return the user for valid credentials; raises AuthError otherwise."""
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None or not verify_password(password, user.password_hash):
            raise AuthError("Incorrect email or password.")
        return user

    def issue_token(self, user: User) -> str:
        """Signed access token with ``sub`` = user id."""
        now = datetime.now(UTC)
        claims = {
            "sub": user.id,
            "iat": now,
            "exp": now + timedelta(minutes=self.settings.jwt_expire_minutes),
        }
        return jwt.encode(claims, self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm)

    def user_id_from_token(self, token: str) -> str:
        """Validate a token and return its subject; raises AuthError."""
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
                options={"require": ["sub", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid or expired token.") from exc
        return str(claims["sub"])
