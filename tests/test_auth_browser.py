"""Run only TestAuthMocked without PostgreSQL; TestAuthDatabase uses seeded_db."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor

from app import security
from app.routers import auth

REGISTER_BODY = {
    "full_name": "New Barista",
    "email": "new.barista@example.com",
    "username": "newbarista",
    "password": "password123",
}
ACTIVE_USER = {"id": 7, "role": "cashier", "is_active": True}
PROFILE = {
    "provider_user_id": "provider-user-7",
    "email": "new.barista@example.com",
    "full_name": "New Barista",
    "avatar_url": None,
}


def signed_payload(**overrides):
    payload = {
        "sub": "7", "purpose": "oauth_handoff", "nonce": "random-nonce",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=60),
    }
    payload.update(overrides)
    return jwt.encode(payload, security.JWT_SECRET, algorithm=security.JWT_ALG)


def kickoff(client, provider="google", flow="browser"):
    response = client.get(f"/auth/oauth/{provider}", params={"mode": "json", "flow": flow})
    assert response.status_code == 200
    return parse_qs(urlparse(response.json()["authorize_url"]).query)["state"][0]


def assert_token_response(response):
    assert response.status_code == 200
    assert response.json()["access_token"]
    assert response.json()["token_type"] == "bearer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def assert_feedback(response, outcome):
    assert response.status_code == 303
    assert response.headers["location"] == f"/pos?oauth={outcome}"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.content == b""


@pytest.fixture
def configured_oauth(monkeypatch):
    for provider in ("google", "discord"):
        monkeypatch.setitem(security.OAUTH_CONFIG[provider], "client_id", "test-client-id")
        monkeypatch.setitem(security.OAUTH_CONFIG[provider], "client_secret", "test-client-secret")


@pytest.fixture
def mock_api(configured_oauth, monkeypatch):
    app = FastAPI()
    app.include_router(auth.router)
    db = MagicMock()
    cursor = db.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = dict(ACTIVE_USER)
    app.dependency_overrides[auth.get_db] = lambda: db
    profile = MagicMock(return_value=dict(PROFILE))
    monkeypatch.setattr(auth, "fetch_oauth_profile", profile)
    # A missed dependency override must fail instead of touching a real database.
    monkeypatch.setattr("app.database.engine.raw_connection", MagicMock(side_effect=AssertionError("Unexpected database access")))
    with TestClient(app) as client:
        yield client, cursor, profile


class TestAuthMocked:
    def test_register_inactive_cashier_with_hash(self, mock_api):
        client, cursor, _ = mock_api
        response = client.post("/auth/register", json={
            **REGISTER_BODY, "full_name": "  New Barista  ",
        })
        assert response.status_code == 201
        assert response.json()["status"] == "pending"
        assert "admin activation" in response.json()["message"]
        assert "access_token" not in response.json()
        sql, values = cursor.execute.call_args.args
        assert "'cashier', FALSE" in sql
        assert values[0:2] == (REGISTER_BODY["email"], REGISTER_BODY["username"])
        assert values[3] == "New Barista"
        assert values[2] != REGISTER_BODY["password"]
        assert security.verify_password(REGISTER_BODY["password"], values[2])

    @pytest.mark.parametrize("changes", [
        {"role": "admin"}, {"is_active": True}, {"other": "ignored?"},
        {"password": "short"}, {"password": "x" * 129},
        {"full_name": "  "}, {"full_name": "x" * 101},
        {"username": "  "}, {"username": "x" * 51},
        {"email": "not-an-email"}, {"username": None},
        {"username": "email@example.com"}, {"username": "two words"},
        {"username": " leading"}, {"username": "trailing "},
        {"username": "tab\tname"}, {"username": "line\nname"},
        {"username": "nonbreaking\u00a0space"}, {"username": "wide\u3000space"},
    ])
    def test_register_rejects_invalid_or_privileged_fields(self, mock_api, changes):
        client, cursor, _ = mock_api
        assert client.post("/auth/register", json={**REGISTER_BODY, **changes}).status_code == 422
        cursor.execute.assert_not_called()

    def test_register_preserves_unicode_username(self, mock_api):
        client, cursor, _ = mock_api
        username = "バリスタ_珈琲é"
        response = client.post("/auth/register", json={**REGISTER_BODY, "username": username})
        assert response.status_code == 201
        assert cursor.execute.call_args.args[1][1] == username

    @pytest.mark.parametrize("field", list(REGISTER_BODY))
    def test_register_requires_all_fields(self, mock_api, field):
        client, cursor, _ = mock_api
        body = {key: value for key, value in REGISTER_BODY.items() if key != field}
        assert client.post("/auth/register", json=body).status_code == 422
        cursor.execute.assert_not_called()

    def test_register_duplicate_has_clear_409(self, mock_api):
        client, cursor, _ = mock_api
        cursor.execute.side_effect = UniqueViolation("private SQL details")
        response = client.post("/auth/register", json=REGISTER_BODY)
        assert response.status_code == 409
        assert response.json() == {"detail": "Email or username already registered"}

    @pytest.mark.parametrize("provider", ["google", "discord"])
    def test_kickoff_binds_signed_browser_state(self, mock_api, provider):
        client, cursor, _ = mock_api
        state = kickoff(client, provider)
        assert client.cookies.get(security.OAUTH_STATE_COOKIE) == state
        claims = security.verify_oauth_state(provider, state, browser_cookie=state)
        assert claims["flow"] == "browser"
        with pytest.raises(HTTPException):
            security.verify_oauth_state(provider, state)
        response = client.get(f"/auth/oauth/{provider}?mode=json&flow=browser")
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=600" in cookie
        assert response.headers["cache-control"] == "no-store"
        cursor.execute.assert_not_called()

    @pytest.mark.parametrize("field", ["client_id", "client_secret"])
    def test_browser_kickoff_requires_both_credentials(self, mock_api, monkeypatch, field):
        client, _, _ = mock_api
        monkeypatch.setitem(security.OAUTH_CONFIG["google"], field, "")
        response = client.get("/auth/oauth/google?mode=json&flow=browser")
        assert response.status_code == 501
        assert "not configured" in response.json()["detail"]

    def test_legacy_kickoff_still_needs_only_client_id(self, mock_api, monkeypatch):
        client, _, _ = mock_api
        monkeypatch.setitem(security.OAUTH_CONFIG["google"], "client_secret", "")
        state = kickoff(client, flow="api")
        assert security.verify_oauth_state("google", state)["flow"] == "api"
        assert security.OAUTH_STATE_COOKIE not in client.cookies
        response = client.get("/auth/oauth/google", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"].startswith("https://accounts.google.com/")

    def test_secure_cookie_on_https(self, mock_api):
        client, _, _ = mock_api
        with TestClient(client.app, base_url="https://testserver") as https_client:
            response = https_client.get("/auth/oauth/google?mode=json&flow=browser")
            assert "Secure" in response.headers["set-cookie"]

    @pytest.mark.parametrize("provider", ["google", "discord"])
    def test_browser_success_exchange_and_cookie_consumption(self, mock_api, provider):
        client, cursor, _ = mock_api
        state = kickoff(client, provider)
        response = client.get(f"/auth/oauth/{provider}/callback", params={"state": state, "code": "code"}, follow_redirects=False)
        assert_feedback(response, "success")
        assert security.OAUTH_STATE_COOKIE not in client.cookies
        cookie = response.headers["set-cookie"]
        assert "SameSite=strict" in cookie and "Max-Age=60" in cookie and "HttpOnly" in cookie
        handoff = client.cookies.get(security.OAUTH_HANDOFF_COOKIE)
        assert security.verify_oauth_handoff(handoff) == 7
        # Role is re-read at exchange, not trusted from the callback or handoff.
        cursor.fetchone.return_value = {**ACTIVE_USER, "role": "manager"}
        exchange = client.post("/auth/oauth/session", headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
        assert_token_response(exchange)
        token = jwt.decode(exchange.json()["access_token"], security.JWT_SECRET, algorithms=[security.JWT_ALG])
        assert token["sub"] == "7" and token["role"] == "manager"
        assert exchange.headers["cache-control"] == "no-store"
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
        count = cursor.execute.call_count
        assert client.post("/auth/oauth/session").status_code == 401
        assert cursor.execute.call_count == count

    def test_new_browser_oauth_user_stays_inactive(self, mock_api):
        client, cursor, _ = mock_api
        cursor.fetchone.side_effect = [None, None, {**ACTIVE_USER, "is_active": False}]
        state = kickoff(client)
        response = client.get("/auth/oauth/google/callback", params={"state": state, "code": "code"}, follow_redirects=False)
        assert_feedback(response, "pending")
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
        assert any("'cashier', FALSE" in call.args[0] for call in cursor.execute.call_args_list)

    def test_existing_inactive_user_gets_no_handoff(self, mock_api):
        client, cursor, _ = mock_api
        cursor.fetchone.return_value = {**ACTIVE_USER, "is_active": False}
        state = kickoff(client)
        response = client.get("/auth/oauth/google/callback", params={"state": state, "code": "code"}, follow_redirects=False)
        assert_feedback(response, "pending")
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies

    @pytest.mark.parametrize("flow", ["api", "browser"])
    @pytest.mark.parametrize("password_hash", ["existing-password-hash", ""])
    def test_unlinked_provider_cannot_merge_into_password_account(self, mock_api, flow, password_hash):
        client, cursor, _ = mock_api
        cursor.fetchone.side_effect = [None, {**ACTIVE_USER, "password_hash": password_hash}]
        state = kickoff(client, flow=flow)
        response = client.get("/auth/oauth/google/callback", params={"state": state, "code": "code"}, follow_redirects=False)
        if flow == "browser":
            assert_feedback(response, "error")
            assert security.OAUTH_STATE_COOKIE not in client.cookies
        else:
            assert response.status_code == 409
            assert "Sign in with your password" in response.json()["detail"]
            assert "administrator" in response.json()["detail"]
            assert "linking is not available" in response.json()["detail"]
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
        assert cursor.execute.call_count == 2
        assert not any("INSERT" in call.args[0] for call in cursor.execute.call_args_list)

    def test_stolen_browser_state_without_cookie_cannot_login(self, mock_api):
        client, cursor, profile = mock_api
        state = kickoff(client)
        with TestClient(client.app) as other_browser:
            response = other_browser.get("/auth/oauth/google/callback", params={"state": state, "code": "attacker-code"}, follow_redirects=False)
            assert_feedback(response, "error")
            assert security.OAUTH_HANDOFF_COOKIE not in other_browser.cookies
        profile.assert_not_called()
        cursor.execute.assert_not_called()

    @pytest.mark.parametrize("kind", ["mismatch", "tampered", "missing", "wrong-provider", "api-downgrade", "expired", "missing-expiry"])
    def test_browser_bad_state_never_calls_provider(self, mock_api, kind):
        client, cursor, profile = mock_api
        state = kickoff(client)
        if kind == "mismatch":
            state = security.create_oauth_state("google", flow="browser")
        elif kind == "tampered":
            state = "tampered-state"
        elif kind == "missing":
            state = None
        elif kind == "wrong-provider":
            state = security.create_oauth_state("discord", flow="browser")
        elif kind == "api-downgrade":
            state = security.create_oauth_state("google")
        elif kind == "expired":
            state = signed_payload(purpose="oauth_state", provider="google", flow="browser", exp=1)
            client.cookies.clear()  # Expired states still yield browser feedback without a cookie.
        elif kind == "missing-expiry":
            state = jwt.encode({
                "purpose": "oauth_state", "provider": "google", "flow": "browser", "nonce": "n",
            }, security.JWT_SECRET, algorithm=security.JWT_ALG)
            client.cookies.clear()
        params = {"code": "attacker-code"}
        if state is not None:
            params["state"] = state
        response = client.get("/auth/oauth/google/callback", params=params, follow_redirects=False)
        assert_feedback(response, "error")
        assert security.OAUTH_STATE_COOKIE not in client.cookies
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
        profile.assert_not_called()
        cursor.execute.assert_not_called()

    @pytest.mark.parametrize("error,outcome", [("access_denied", "cancelled"), ("server_error", "error")])
    def test_provider_denial_is_safe_feedback(self, mock_api, error, outcome):
        client, cursor, profile = mock_api
        state = kickoff(client)
        response = client.get("/auth/oauth/google/callback", params={
            "state": state, "error": error, "error_description": "private-provider-details",
        }, follow_redirects=False)
        assert_feedback(response, outcome)
        assert security.OAUTH_STATE_COOKIE not in client.cookies
        profile.assert_not_called()
        cursor.execute.assert_not_called()

    def test_denial_requires_valid_state(self, mock_api):
        client, _, _ = mock_api
        kickoff(client)
        response = client.get("/auth/oauth/google/callback?error=access_denied&state=bad", follow_redirects=False)
        assert_feedback(response, "error")

    def test_missing_code_is_browser_error(self, mock_api):
        client, _, profile = mock_api
        state = kickoff(client)
        response = client.get("/auth/oauth/google/callback", params={"state": state}, follow_redirects=False)
        assert_feedback(response, "error")
        profile.assert_not_called()

    @pytest.mark.parametrize("failure", [HTTPException(502, "private-provider-error"), RuntimeError("private-error")])
    def test_browser_failures_never_leak_provider_details(self, mock_api, failure):
        client, _, profile = mock_api
        profile.side_effect = failure
        state = kickoff(client)
        response = client.get("/auth/oauth/google/callback", params={"state": state, "code": "private-code"}, follow_redirects=False)
        assert_feedback(response, "error")
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies

    @pytest.mark.parametrize("active,status_code", [(True, 200), (False, 403)])
    def test_default_api_callback_json_compatibility(self, mock_api, active, status_code):
        client, cursor, _ = mock_api
        cursor.fetchone.return_value = {**ACTIVE_USER, "is_active": active}
        state = kickoff(client, flow="api")
        response = client.get("/auth/oauth/google/callback", params={"state": state, "code": "code"})
        assert response.status_code == status_code
        assert "location" not in response.headers
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
        if active:
            assert set(response.json()) == {"access_token", "token_type"}
            assert_token_response(response)
        else:
            assert "pending admin activation" in response.json()["detail"]

    def test_default_api_invalid_state_and_unconfigured_statuses(self, mock_api, monkeypatch):
        client, _, profile = mock_api
        assert client.get("/auth/oauth/google/callback?code=x&state=bad").status_code == 400
        monkeypatch.setitem(security.OAUTH_CONFIG["google"], "client_id", "")
        assert client.get("/auth/oauth/google/callback?code=x&state=bad").status_code == 501
        profile.assert_not_called()

    @pytest.mark.parametrize("token", [
        None, "not-a-jwt", "expired", "access", "state", "wrong-purpose", "missing-expiry", "invalid-user",
    ])
    def test_exchange_rejects_invalid_tokens_and_clears_cookie(self, mock_api, token):
        client, cursor, _ = mock_api
        tokens = {
            "expired": signed_payload(exp=1),
            "access": security.create_access_token(7, "admin"),
            "state": security.create_oauth_state("google"),
            "wrong-purpose": signed_payload(purpose="access"),
            "missing-expiry": jwt.encode({"sub": "7", "purpose": "oauth_handoff", "nonce": "n"}, security.JWT_SECRET, algorithm=security.JWT_ALG),
            "invalid-user": signed_payload(sub="-1"),
        }
        if token is not None:
            client.cookies.set(security.OAUTH_HANDOFF_COOKIE, tokens.get(token, token), domain="testserver.local", path="/auth/oauth/session")
        response = client.post("/auth/oauth/session")
        assert response.status_code == 401
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
        cursor.execute.assert_not_called()

    @pytest.mark.parametrize("headers", [
        {"Origin": "https://attacker.example"}, {"Origin": "null"},
        {"Origin": "http://testserver:9999"},
        {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
    ])
    def test_exchange_rejects_cross_origin_requests(self, mock_api, headers):
        client, cursor, _ = mock_api
        client.cookies.set(security.OAUTH_HANDOFF_COOKIE, security.create_oauth_handoff(7), domain="testserver.local", path="/auth/oauth/session")
        response = client.post("/auth/oauth/session", headers=headers)
        assert response.status_code == 403
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
        cursor.execute.assert_not_called()

    @pytest.mark.parametrize("user", [None, {**ACTIVE_USER, "is_active": False}])
    def test_exchange_rechecks_account_activation(self, mock_api, user):
        client, cursor, _ = mock_api
        cursor.fetchone.return_value = user
        client.cookies.set(security.OAUTH_HANDOFF_COOKIE, security.create_oauth_handoff(7), domain="testserver.local", path="/auth/oauth/session")
        response = client.post("/auth/oauth/session")
        assert response.status_code == 403
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies

    def test_handoff_is_never_a_bearer_access_token(self):
        db = MagicMock()
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=security.create_oauth_handoff(7))
        with pytest.raises(HTTPException) as exc:
            security.get_current_user(credentials, db)
        assert exc.value.status_code == 401
        db.query.assert_not_called()


@pytest.fixture
def database_client():
    from app.main import app

    with TestClient(app) as client:
        yield client


class TestAuthDatabase:
    def test_registration_requires_admin_activation(self, seeded_db, database_client, admin_headers):
        client = database_client
        response = client.post("/auth/register", json=REGISTER_BODY)
        assert response.status_code == 201 and response.json()["status"] == "pending"
        with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (REGISTER_BODY["username"],))
            user = cursor.fetchone()
        assert user["role"] == "cashier" and user["is_active"] is False
        assert security.verify_password(REGISTER_BODY["password"], user["password_hash"])
        login_body = {"identifier": REGISTER_BODY["username"], "password": REGISTER_BODY["password"]}
        assert client.post("/auth/login", json=login_body).status_code == 403
        assert client.patch(f"/users/{user['id']}", json={"is_active": True}, headers=admin_headers).status_code == 200
        login = client.post("/auth/login", json=login_body)
        assert_token_response(login)
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).status_code == 200

    def test_duplicate_registration_and_no_public_privileges(self, seeded_db, database_client):
        client = database_client
        assert client.post("/auth/register", json=REGISTER_BODY).status_code == 201
        for changes in ({"username": "another"}, {"email": "another@example.com"}):
            response = client.post("/auth/register", json={**REGISTER_BODY, **changes})
            assert response.status_code == 409
            assert "Email or username" in response.json()["detail"]
        response = client.post("/auth/register", json={
            **REGISTER_BODY, "email": "injected@example.com", "username": "injected",
            "role": "admin", "is_active": True,
        })
        assert response.status_code == 422
        with seeded_db.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE username = 'injected'")
            assert cursor.fetchone() is None

    @pytest.mark.parametrize("provider", ["google", "discord"])
    @pytest.mark.parametrize("flow", ["api", "browser"])
    def test_new_oauth_accounts_stay_pending_until_activated(
        self, seeded_db, database_client, admin_headers, configured_oauth, monkeypatch, provider, flow,
    ):
        client = database_client
        monkeypatch.setattr(auth, "fetch_oauth_profile", lambda provider, code: dict(PROFILE))
        state = kickoff(client, provider, flow)
        response = client.get(f"/auth/oauth/{provider}/callback", params={"state": state, "code": "code"}, follow_redirects=False)
        if flow == "browser":
            assert_feedback(response, "pending")
        else:
            assert response.status_code == 403
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
        with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s", (PROFILE["email"],))
            user = cursor.fetchone()
            cursor.execute("SELECT user_id FROM user_oauth_accounts WHERE provider = %s", (provider,))
            assert cursor.fetchone()["user_id"] == user["id"]
        assert user["role"] == "cashier" and user["is_active"] is False
        assert user["password_hash"] is None
        assert client.patch(f"/users/{user['id']}", json={"is_active": True}, headers=admin_headers).status_code == 200
        state = kickoff(client, provider, flow)
        response = client.get(f"/auth/oauth/{provider}/callback", params={"state": state, "code": "code"}, follow_redirects=False)
        if flow == "browser":
            assert_feedback(response, "success")
            response = client.post("/auth/oauth/session")
        assert_token_response(response)

    @pytest.mark.parametrize("provider", ["google", "discord"])
    @pytest.mark.parametrize("flow", ["api", "browser"])
    def test_pre_registered_password_account_never_acquires_oauth_identity(
        self, seeded_db, database_client, admin_headers, configured_oauth, monkeypatch, provider, flow,
    ):
        client = database_client
        assert client.post("/auth/register", json=REGISTER_BODY).status_code == 201
        monkeypatch.setattr(auth, "fetch_oauth_profile", lambda provider, code: dict(PROFILE))
        with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s", (REGISTER_BODY["email"],))
            original = cursor.fetchone()

        for active in (False, True):
            if active:
                assert client.patch(
                    f"/users/{original['id']}", json={"is_active": True}, headers=admin_headers,
                ).status_code == 200
            state = kickoff(client, provider, flow)
            response = client.get(
                f"/auth/oauth/{provider}/callback", params={"state": state, "code": "code"}, follow_redirects=False,
            )
            if flow == "browser":
                assert_feedback(response, "error")
                assert security.OAUTH_STATE_COOKIE not in client.cookies
            else:
                assert response.status_code == 409
                detail = response.json()["detail"]
                assert "Sign in with your password" in detail and "administrator" in detail
                assert "linking is not available" in detail
            assert "access_token" not in response.text
            assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
            assert client.post("/auth/oauth/session").status_code == 401
            with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM users WHERE id = %s", (original["id"],))
                current = cursor.fetchone()
                assert current["password_hash"] == original["password_hash"]
                assert current["role"] == "cashier" and current["is_active"] is active
                cursor.execute("SELECT COUNT(*) AS count FROM user_oauth_accounts")
                assert cursor.fetchone()["count"] == 0
            password_login = client.post("/auth/login", json={
                "identifier": REGISTER_BODY["email"], "password": REGISTER_BODY["password"],
            })
            if active:
                # Activation permits only the original password identity, never a silent OAuth merge.
                assert_token_response(password_login)
            else:
                assert password_login.status_code == 403

    @pytest.mark.parametrize("first_provider", ["google", "discord"])
    @pytest.mark.parametrize("flow", ["api", "browser"])
    @pytest.mark.parametrize("active", [False, True])
    def test_verified_same_email_providers_link_only_to_oauth_only_account(
        self, seeded_db, database_client, admin_headers, configured_oauth, monkeypatch, first_provider, flow, active,
    ):
        client = database_client
        monkeypatch.setattr(auth, "fetch_oauth_profile", lambda provider, code: {
            **PROFILE, "provider_user_id": f"{provider}-user-7",
        })
        state = kickoff(client, first_provider, flow)
        response = client.get(
            f"/auth/oauth/{first_provider}/callback", params={"state": state, "code": "first-code"}, follow_redirects=False,
        )
        if flow == "browser":
            assert_feedback(response, "pending")
        else:
            assert response.status_code == 403
        with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s", (PROFILE["email"],))
            original = cursor.fetchone()
        assert original["password_hash"] is None
        assert original["role"] == "cashier" and original["is_active"] is False
        if active:
            assert client.patch(
                f"/users/{original['id']}", json={"is_active": True, "role": "manager"}, headers=admin_headers,
            ).status_code == 200

        second_provider = "discord" if first_provider == "google" else "google"
        for code in ("second-provider-first-login", "second-provider-returning-login"):
            state = kickoff(client, second_provider, flow)
            response = client.get(
                f"/auth/oauth/{second_provider}/callback", params={"state": state, "code": code}, follow_redirects=False,
            )
            if active:
                if flow == "browser":
                    assert_feedback(response, "success")
                    response = client.post("/auth/oauth/session")
                assert_token_response(response)
                claims = jwt.decode(response.json()["access_token"], security.JWT_SECRET, algorithms=[security.JWT_ALG])
                assert claims["sub"] == str(original["id"]) and claims["role"] == "manager"
            else:
                if flow == "browser":
                    assert_feedback(response, "pending")
                else:
                    assert response.status_code == 403
                assert "access_token" not in response.text
            assert security.OAUTH_HANDOFF_COOKIE not in client.cookies

        with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s", (PROFILE["email"],))
            users = cursor.fetchall()
            assert len(users) == 1 and users[0]["id"] == original["id"]
            assert users[0]["password_hash"] is None and users[0]["is_active"] is active
            assert users[0]["role"] == ("manager" if active else "cashier")
            cursor.execute("SELECT user_id, provider FROM user_oauth_accounts ORDER BY provider")
            links = cursor.fetchall()
            assert len(links) == 2
            assert {link["provider"] for link in links} == {"google", "discord"}
            assert all(link["user_id"] == original["id"] for link in links)

    def test_deactivated_user_cannot_exchange_handoff(
        self, seeded_db, database_client, admin_headers, configured_oauth, monkeypatch,
    ):
        client = database_client
        # This is a returning, already-linked identity, not a new email-based merge.
        with seeded_db, seeded_db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_oauth_accounts (user_id, provider, provider_user_id, provider_email)
                VALUES (1, 'google', %s, 'cashier@shika.test')
                """,
                (PROFILE["provider_user_id"],),
            )
        monkeypatch.setattr(auth, "fetch_oauth_profile", lambda provider, code: {**PROFILE, "email": "cashier@shika.test"})
        state = kickoff(client)
        response = client.get("/auth/oauth/google/callback", params={"state": state, "code": "code"}, follow_redirects=False)
        assert_feedback(response, "success")
        assert client.patch("/users/1", json={"is_active": False}, headers=admin_headers).status_code == 200
        response = client.post("/auth/oauth/session")
        assert response.status_code == 403
        assert security.OAUTH_HANDOFF_COOKIE not in client.cookies
