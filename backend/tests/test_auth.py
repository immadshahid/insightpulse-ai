"""Sign-up and sign-in validation, lockout, and Google (Firebase) sign-in."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core import firebase
from app.core.firebase import FirebaseTokenError, verify_firebase_token
from app.core.ratelimit import AttemptLimiter, TooManyAttemptsError
from app.core.security import password_problem

API = "/api/v1/auth"


@pytest.mark.parametrize(
    ("password", "problem"),
    [
        ("short1", "at least 8"),
        ("abcdefgh", "letter and one number"),
        ("12345678", "letter and one number"),
        (" padded-pass1", "space"),
        ("é" * 37 + "1", "too long"),  # 75 bytes in UTF-8
        ("me1@example.com", "same as your email"),
    ],
)
def test_weak_passwords_are_explained(password: str, problem: str) -> None:
    assert problem in (password_problem(password, "me1@example.com") or "")


def test_good_password_passes() -> None:
    assert password_problem("blue-river-42", "me@example.com") is None


def test_register_gives_plain_messages(client: TestClient) -> None:
    r = client.post(f"{API}/register", json={"email": "plain@example.com", "password": "abcdefgh"})
    assert r.status_code == 422 and r.json()["detail"].startswith("Use at least one letter")
    bad_email = client.post(f"{API}/register", json={"email": "nope", "password": "abcd1234"})
    assert bad_email.status_code == 422


def test_duplicate_email_ignores_case_and_spaces(client: TestClient) -> None:
    ok = client.post(f"{API}/register", json={"email": "dup@example.com", "password": "abcd1234"})
    assert ok.status_code == 201
    again = client.post(
        f"{API}/register", json={"email": "  DUP@example.com ", "password": "abcd1234"}
    )
    assert again.status_code == 409 and "already exists" in again.json()["detail"]


def test_wrong_and_unknown_emails_get_the_same_answer(client: TestClient) -> None:
    client.post(f"{API}/register", json={"email": "same@example.com", "password": "abcd1234"})
    wrong = client.post(f"{API}/login", json={"email": "same@example.com", "password": "x1x1x1x1"})
    unknown = client.post(f"{API}/login", json={"email": "ghost@example.com", "password": "x1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "Incorrect email or password."


def test_repeated_wrong_passwords_lock_the_account(client: TestClient) -> None:
    client.post(f"{API}/register", json={"email": "lock@example.com", "password": "abcd1234"})
    for _ in range(10):
        r = client.post(f"{API}/login", json={"email": "lock@example.com", "password": "nope1234"})
        assert r.status_code == 401
    locked = client.post(f"{API}/login", json={"email": "lock@example.com", "password": "abcd1234"})
    assert locked.status_code == 429 and "Too many attempts" in locked.json()["detail"]
    assert int(locked.headers["Retry-After"]) > 0


def test_success_clears_earlier_failures(client: TestClient) -> None:
    client.post(f"{API}/register", json={"email": "reset@example.com", "password": "abcd1234"})
    for _ in range(9):
        client.post(f"{API}/login", json={"email": "reset@example.com", "password": "nope1234"})
    good = {"email": "reset@example.com", "password": "abcd1234"}
    assert client.post(f"{API}/login", json=good).status_code == 200
    for _ in range(9):
        client.post(f"{API}/login", json={"email": "reset@example.com", "password": "nope1234"})
    assert client.post(f"{API}/login", json=good).status_code == 200


def test_limiter_window_expires() -> None:
    now = [0.0]
    limiter = AttemptLimiter(limit=2, window=60, clock=lambda: now[0])
    limiter.fail("k")
    limiter.fail("k")
    with pytest.raises(TooManyAttemptsError) as exc:
        limiter.check("k")
    assert exc.value.message == "Too many attempts. Please wait 1 minute and try again."
    now[0] = 61
    limiter.check("k")


# ---------------------------------------------------------------- Google / Firebase


def claims(**over):
    base = {
        "iss": "https://securetoken.google.com/demo-project",
        "aud": "demo-project",
        "sub": "uid-1",
        "email": "Owner@Gmail.com",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"},
    }
    return {**base, **over}


def test_verified_token_gives_identity(monkeypatch) -> None:
    monkeypatch.setattr(firebase, "_verify_signature", lambda token, project: claims())
    who = verify_firebase_token("x" * 30, "demo-project")
    assert who.email == "owner@gmail.com" and who.provider == "google.com"


@pytest.mark.parametrize(
    "bad",
    [
        claims(iss="https://securetoken.google.com/someone-else"),
        claims(email_verified=False),
        claims(email=""),
    ],
)
def test_untrustworthy_tokens_are_refused(monkeypatch, bad) -> None:
    monkeypatch.setattr(firebase, "_verify_signature", lambda token, project: bad)
    with pytest.raises(FirebaseTokenError):
        verify_firebase_token("x" * 30, "demo-project")


def test_bad_signature_is_refused(monkeypatch) -> None:
    def boom(token, project):
        raise ValueError("Could not verify token signature.")

    monkeypatch.setattr(firebase, "_verify_signature", boom)
    with pytest.raises(FirebaseTokenError):
        verify_firebase_token("x" * 30, "demo-project")


def test_firebase_endpoint_is_off_until_configured(client: TestClient) -> None:
    r = client.post(f"{API}/firebase", json={"id_token": "x" * 30})
    assert r.status_code == 503 and "isn't set up" in r.json()["detail"]


def test_google_sign_in_creates_then_reuses_the_account(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "firebase_project_id", "demo-project")
    monkeypatch.setattr(firebase, "_verify_signature", lambda token, project: claims())
    first = client.post(f"{API}/firebase", json={"id_token": "x" * 30})
    assert first.status_code == 200 and first.json()["user"]["email"] == "owner@gmail.com"
    second = client.post(f"{API}/firebase", json={"id_token": "y" * 30})
    assert second.json()["user"]["id"] == first.json()["user"]["id"]
    token = second.json()["access_token"]
    datasets = client.get("/api/v1/datasets", headers={"Authorization": f"Bearer {token}"})
    assert datasets.status_code == 200


def test_google_sign_in_joins_an_existing_email_account(client: TestClient, monkeypatch) -> None:
    made = client.post(
        f"{API}/register", json={"email": "both@gmail.com", "password": "abcd1234"}
    ).json()
    monkeypatch.setattr(get_settings(), "firebase_project_id", "demo-project")
    monkeypatch.setattr(
        firebase, "_verify_signature", lambda token, project: claims(email="both@gmail.com")
    )
    r = client.post(f"{API}/firebase", json={"id_token": "x" * 30})
    assert r.json()["user"]["id"] == made["user"]["id"]


def test_rejected_google_token_is_401(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "firebase_project_id", "demo-project")
    monkeypatch.setattr(
        firebase, "_verify_signature", lambda token, project: claims(email_verified=False)
    )
    r = client.post(f"{API}/firebase", json={"id_token": "x" * 30})
    assert r.status_code == 401 and "verified email" in r.json()["detail"]
