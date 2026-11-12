"""Verify Firebase ID tokens (Google sign-in) without a service-account key.

Firebase signs ID tokens with Google's public keys; checking the signature, expiry,
audience (our project id) and issuer is enough to trust the email inside. Only a
verified email is accepted, because accounts are matched by email.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

_REQUEST = google_requests.Request()


class FirebaseTokenError(Exception):
    """The token can't be trusted; the message is safe to show."""


@dataclass(frozen=True)
class FirebaseIdentity:
    """Who a verified token belongs to."""

    uid: str
    email: str
    provider: str


def _verify_signature(token: str, project_id: str) -> dict[str, Any]:
    return id_token.verify_firebase_token(token, _REQUEST, audience=project_id)


def verify_firebase_token(token: str, project_id: str) -> FirebaseIdentity:
    """Return the verified identity, or raise FirebaseTokenError."""
    try:
        claims = _verify_signature(token, project_id)
    except Exception as exc:  # google-auth raises several error types for bad tokens
        raise FirebaseTokenError("Google sign-in could not be verified. Try again.") from exc
    if not claims or claims.get("iss") != f"https://securetoken.google.com/{project_id}":
        raise FirebaseTokenError("Google sign-in could not be verified. Try again.")
    email = str(claims.get("email") or "").strip().lower()
    if not email or not claims.get("email_verified"):
        raise FirebaseTokenError("Your Google account has no verified email address.")
    provider = str((claims.get("firebase") or {}).get("sign_in_provider") or "")
    return FirebaseIdentity(uid=str(claims.get("sub") or ""), email=email, provider=provider)
