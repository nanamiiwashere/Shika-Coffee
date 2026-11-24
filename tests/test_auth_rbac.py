import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import RealDictCursor

from app.main import app
from app.security import create_access_token, hash_password

client = TestClient(app)


def test_sqlalchemy_login_and_me(seeded_db):
    res = client.post("/auth/login", json={"identifier": "cashier@shika.test", "password": "password123"})
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["pragma"] == "no-cache"
    token = res.json()["access_token"]

    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "cashier@shika.test"


def test_legacy_username_cannot_shadow_another_accounts_email(seeded_db):
    legacy_password = "legacy-private-password"
    real_password = "real-private-password"
    with seeded_db, seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
        # Insert the historical collision directly: new-user endpoints must reject it.
        cursor.execute(
            """
            INSERT INTO users (email, username, password_hash, full_name, role, is_active)
            VALUES ('legacy@example.com', 'real@example.com', %s, 'Legacy Staff', 'cashier', TRUE)
            RETURNING id
            """,
            (hash_password(legacy_password),),
        )
        legacy_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO users (email, username, password_hash, full_name, role, is_active)
            VALUES ('real@example.com', 'real-staff', %s, 'Real Staff', 'cashier', TRUE)
            RETURNING id
            """,
            (hash_password(real_password),),
        )
        real_id = cursor.fetchone()["id"]

    for identifier, password, expected_id in (
        ("real@example.com", real_password, real_id),
        ("real-staff", real_password, real_id),
        ("legacy@example.com", legacy_password, legacy_id),
    ):
        response = client.post("/auth/login", json={"identifier": identifier, "password": password})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"})
        assert me.status_code == 200 and me.json()["id"] == expected_id
    # Never fall back to the legacy username after an email password mismatch.
    assert client.post("/auth/login", json={
        "identifier": "real@example.com", "password": legacy_password,
    }).status_code == 401


@pytest.mark.parametrize("username", [
    "email@example.com", "two words", " leading", "trailing ",
    "tab\tname", "line\nname", "nonbreaking\u00a0space", "wide\u3000space",
])
def test_new_username_namespace_is_enforced_for_public_and_admin_creation(seeded_db, admin_headers, username):
    body = {
        "email": "new@example.com", "username": username,
        "full_name": "New Staff", "password": "password123",
    }
    assert client.post("/auth/register", json=body).status_code == 422
    assert client.post("/users", json=body, headers=admin_headers).status_code == 422
    with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT COUNT(*) AS count FROM users")
        assert cursor.fetchone()["count"] == 3


def test_unicode_usernames_can_register_and_login_after_activation(seeded_db, admin_headers):
    username = "バリスタ_珈琲é"
    body = {
        "email": "unicode@example.com", "username": username,
        "full_name": "Unicode Staff", "password": "password123",
    }
    assert client.post("/auth/register", json=body).status_code == 201
    with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT id, username FROM users WHERE email = %s", (body["email"],))
        user = cursor.fetchone()
    assert user["username"] == username
    assert client.patch(f"/users/{user['id']}", json={"is_active": True}, headers=admin_headers).status_code == 200
    assert client.post("/auth/login", json={"identifier": username, "password": body["password"]}).status_code == 200
    created = client.post("/users", json={**body, "email": "admin-created@example.com", "username": "珈琲係"}, headers=admin_headers)
    assert created.status_code == 201 and created.json()["username"] == "珈琲係"


@pytest.mark.parametrize("user_id", [1, 2])
def test_non_admin_cannot_activate_or_promote_users_even_with_admin_role_claim(seeded_db, user_id):
    headers = {"Authorization": f"Bearer {create_access_token(user_id, 'admin')}"}
    assert client.get("/users", headers=headers).status_code == 403
    assert client.patch("/users/1", json={"role": "admin", "is_active": True}, headers=headers).status_code == 403
    with seeded_db.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT role FROM users WHERE id = 1")
        assert cursor.fetchone()["role"] == "cashier"