"""Authentication behind a provider interface (local JWT now, Firebase later)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User


class AuthError(Exception):
    """Invalid credentials or token."""


class AuthProvider(Protocol):
    """What the API needs from an auth backend."""

    def register(self, db: Session, email: str, password: str) -> User: ...
    def authenticate(self, db: Session, email: str, password: str) -> User: ...
    def user_for_verified_email(self, db: Session, email: str) -> User: ...
    def issue_token(self, user: User) -> str: ...
    def user_id_from_token(self, token: str) -> str: ...


MAX_PASSWORD_BYTES = 72  # bcrypt ignores anything longer, so longer passwords are refused


def password_problem(password: str, email: str = "") -> str | None:
    """Why a new password is not acceptable, or None if it is fine."""
    if len(password) < 8:
        return "Use at least 8 characters for your password."
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return "That password is too long. Use up to 64 characters."
    if password.strip() != password or not password.strip():
        return "Your password can't start or end with a space."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Use at least one letter and one number in your password."
    if email and password.lower() == email.strip().lower():
        return "Your password can't be the same as your email."
    return None


def hash_password(password: str) -> str:
    """bcrypt hash of a password of at most 72 bytes."""
    return bcrypt.hashpw(password.encode()[:MAX_PASSWORD_BYTES], bcrypt.gensalt()).decode()


# Checked when an email has no account, so a miss takes as long as a wrong password.
_DUMMY_HASH = hash_password("timing-equaliser-1")


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
            raise AuthError("An account with this email already exists. Try signing in.")
        return self._create(db, email, hash_password(password))

    def _create(self, db: Session, email: str, password_hash: str) -> User:
        user = User(email=email, password_hash=password_hash)
        db.add(user)
        try:
            db.commit()
        except IntegrityError as exc:  # two sign-ups for the same email at the same moment
            db.rollback()
            raise AuthError("An account with this email already exists. Try signing in.") from exc
        return user

    def authenticate(self, db: Session, email: str, password: str) -> User:
        """Return the user for valid credentials; raises AuthError otherwise."""
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        stored = user.password_hash if user else _DUMMY_HASH
        if not verify_password(password, stored) or user is None:
            raise AuthError("Incorrect email or password.")
        return user

    def user_for_verified_email(self, db: Session, email: str) -> User:
        """The account for an email a trusted provider (Google) verified, created if new.

        A new account gets a random password nobody knows; it signs in with Google.
        """
        email = email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            return user
        try:
            return self._create(db, email, hash_password(secrets.token_urlsafe(32)))
        except AuthError:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                raise
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
