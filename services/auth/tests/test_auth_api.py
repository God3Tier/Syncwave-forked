from argon2 import PasswordHasher
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from auth_service.db import UserRecord

from .conftest import TEST_DB


def test_signup_normalizes_username_hashes_password_and_sets_jwt_cookie(client):
    response = client.post(
        "/signup",
        json={"username": "  MiXeD_User ", "password": "a-strong-password"},
    )

    assert response.status_code == 201
    assert response.json()["username"] == "mixed_user"
    cookie = response.cookies.get("syncwave_session")
    assert cookie
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]

    engine = create_engine(f"sqlite:///{TEST_DB.as_posix()}")
    with Session(engine) as session:
        user = session.scalar(select(UserRecord))
        assert user is not None
        assert user.password_hash != "a-strong-password"
        assert PasswordHasher().verify(user.password_hash, "a-strong-password")
    engine.dispose()


def test_usernames_are_unique_without_case_distinctions(client):
    first = client.post("/signup", json={"username": "WaveFriend", "password": "a-strong-password"})
    duplicate = client.post(
        "/signup", json={"username": "wavefriend", "password": "another-password"}
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409


def test_login_and_me_return_the_account(client):
    client.post("/signup", json={"username": "night_listen", "password": "a-strong-password"})
    client.post("/logout")

    login = client.post(
        "/login", json={"username": "NIGHT_LISTEN", "password": "a-strong-password"}
    )

    assert login.status_code == 200
    assert client.get("/me").json() == login.json()


def test_login_does_not_reveal_whether_username_exists(client):
    client.post("/signup", json={"username": "known_user", "password": "a-strong-password"})

    wrong_password = client.post(
        "/login", json={"username": "known_user", "password": "wrong-password"}
    )
    unknown_user = client.post(
        "/login", json={"username": "other_user", "password": "wrong-password"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_logout_clears_the_cookie_and_me_requires_a_session(client):
    client.post("/signup", json={"username": "wave_user", "password": "a-strong-password"})

    assert client.post("/logout").status_code == 204
    assert client.get("/me").status_code == 401


def test_jwks_contains_the_public_signing_key(client):
    response = client.get("/.well-known/jwks.json")

    assert response.status_code == 200
    key = response.json()["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert "d" not in key


def test_rejects_invalid_usernames_and_short_passwords(client):
    assert (
        client.post("/signup", json={"username": "x", "password": "a-strong-password"}).status_code
        == 422
    )
    assert (
        client.post("/signup", json={"username": "good_user", "password": "short"}).status_code
        == 422
    )


def test_rejects_cross_origin_cookie_writes(client):
    response = client.post(
        "/signup",
        headers={"Origin": "https://evil.example"},
        json={"username": "wave_user", "password": "a-strong-password"},
    )

    assert response.status_code == 403
