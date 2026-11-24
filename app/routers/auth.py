import logging
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from psycopg2.errors import UniqueViolation
from psycopg2.extensions import connection as PgConnection

from app.database import get_raw_db as get_db
from app.schemas import AvatarUploadRequest, LoginRequest, ProfileUpdate, RegisterRequest, UserCreate, UserUpdate
from app.uploads import remove_local_upload, save_local_image
from app.security import (
    OAUTH_CONFIG,
    OAUTH_COOKIE_SECURE,
    OAUTH_HANDOFF_COOKIE,
    OAUTH_HANDOFF_TTL,
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_TTL,
    build_oauth_authorize_url,
    create_access_token,
    create_oauth_handoff,
    create_oauth_state,
    fetch_oauth_profile,
    get_current_user,
    hash_password,
    oauth_state_is_browser,
    require_role,
    verify_oauth_handoff,
    verify_oauth_state,
    verify_password,
)

router = APIRouter(tags=["Auth & Users"])
logger = logging.getLogger(__name__)


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: PgConnection = Depends(get_db)):
    pw_hash = hash_password(body.password)
    try:
        with db, db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, username, password_hash, full_name, role, is_active)
                VALUES (%s, %s, %s, %s, 'cashier', FALSE)
                """,
                (body.email, body.username, pw_hash, body.full_name),
            )
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="Email or username already registered")
    return {"status": "pending", "message": "Account created. Please wait for admin activation before signing in."}


@router.post("/auth/login")
def login(body: LoginRequest, db: PgConnection = Depends(get_db)):
    # Legacy email-like usernames must use their actual email instead.
    column = "email" if "@" in body.identifier else "username"
    with db.cursor() as cur:
        cur.execute(
            f"SELECT id, password_hash, role, is_active FROM users WHERE {column} = %s",
            (body.identifier,),
        )
        user = cur.fetchone()
    if not user or not user["password_hash"] or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account inactive")
    return _private_response(JSONResponse({
        "access_token": create_access_token(user["id"], user["role"]), "token_type": "bearer",
    }))


def _private_response(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _oauth_cookie(response: Response, request: Request, name: str, value: str = "", *, clear: bool = False):
    handoff = name == OAUTH_HANDOFF_COOKIE
    options = {
        "path": "/auth/oauth/session" if handoff else "/auth/oauth",
        "httponly": True,
        "samesite": "strict" if handoff else "lax",
        "secure": OAUTH_COOKIE_SECURE or request.url.scheme == "https",
    }
    if clear:
        response.delete_cookie(name, **options)
    else:
        response.set_cookie(
            name, value, max_age=OAUTH_HANDOFF_TTL if handoff else OAUTH_STATE_TTL, **options,
        )


def _browser_oauth_result(request: Request, outcome: str, user_id: int | None = None):
    response = _private_response(RedirectResponse(f"/pos?oauth={outcome}", status_code=303))
    _oauth_cookie(response, request, OAUTH_STATE_COOKIE, clear=True)
    if user_id is None:
        _oauth_cookie(response, request, OAUTH_HANDOFF_COOKIE, clear=True)
    else:
        _oauth_cookie(response, request, OAUTH_HANDOFF_COOKIE, create_oauth_handoff(user_id))
    return response


# Keep the static session endpoint before the dynamic provider routes.
@router.post("/auth/oauth/session")
def oauth_session(request: Request, db: PgConnection = Depends(get_db)):
    def reply(content: dict[str, Any], status_code: int = 200):
        response = _private_response(JSONResponse(content, status_code=status_code))
        _oauth_cookie(response, request, OAUTH_HANDOFF_COOKIE, clear=True)
        return response

    origin = request.headers.get("origin")
    if (
        request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
        or (origin is not None and origin != str(request.base_url).rstrip("/"))
    ):
        return reply({"detail": "Same-origin request required"}, 403)
    try:
        user_id = verify_oauth_handoff(request.cookies.get(OAUTH_HANDOFF_COOKIE, ""))
    except HTTPException:
        return reply({"detail": "Invalid or expired OAuth session"}, 401)
    with db.cursor() as cur:
        cur.execute("SELECT id, role, is_active FROM users WHERE id = %s", (user_id,))
        user = cast(dict[str, Any] | None, cur.fetchone())
    if not user or not user["is_active"]:
        return reply({"detail": "Account inactive or not found"}, 403)
    return reply({"access_token": create_access_token(user["id"], user["role"]), "token_type": "bearer"})


@router.get("/auth/oauth/{provider}")
def oauth_redirect(
    request: Request,
    provider: Literal["google", "discord"],
    mode: Literal["redirect", "json"] = "redirect",
    flow: Literal["api", "browser"] = "api",
):
    cfg = OAUTH_CONFIG[provider]
    if not cfg["client_id"] or (flow == "browser" and not cfg["client_secret"]):
        detail = (
            f"{provider.title()} OAuth is not configured. Contact the administrator."
            if flow == "browser" else f"{provider} OAuth not configured"
        )
        raise HTTPException(status_code=501, detail=detail)
    state = create_oauth_state(provider, flow=flow)
    url = build_oauth_authorize_url(provider, state)
    response = JSONResponse({"authorize_url": url}) if mode == "json" else RedirectResponse(url)
    _private_response(response)
    if flow == "browser":
        _oauth_cookie(response, request, OAUTH_STATE_COOKIE, state)
        _oauth_cookie(response, request, OAUTH_HANDOFF_COOKIE, clear=True)
    return response


@router.get("/auth/oauth/{provider}/callback")
def oauth_callback(
    request: Request,
    provider: Literal["google", "discord"],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: PgConnection = Depends(get_db),
):
    browser_cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    browser = browser_cookie is not None or oauth_state_is_browser(provider, state or "")
    try:
        cfg = OAUTH_CONFIG[provider]
        if not cfg["client_id"] or (browser and not cfg["client_secret"]):
            raise HTTPException(status_code=501, detail=f"{provider} OAuth not configured")
        if not state:
            raise HTTPException(status_code=400, detail="Missing OAuth state")
        verify_oauth_state(provider, state, browser_cookie=browser_cookie)
        if error:
            if browser:
                return _browser_oauth_result(request, "cancelled" if error == "access_denied" else "error")
            raise HTTPException(status_code=400, detail="OAuth authorization was not completed")
        if not code:
            raise HTTPException(status_code=400, detail="Missing OAuth code")
        user = _oauth_user(provider, code, db)
        if not user["is_active"]:
            if browser:
                return _browser_oauth_result(request, "pending")
            raise HTTPException(status_code=403, detail="Account pending admin activation")
        if browser:
            return _browser_oauth_result(request, "success", user["id"])
        return _private_response(JSONResponse({
            "access_token": create_access_token(user["id"], user["role"]), "token_type": "bearer",
        }))
    except Exception as exc:
        if not browser:
            raise
        # Never include provider messages, codes, or tokens in browser feedback.
        logger.warning("Browser OAuth callback failed (%s)", type(exc).__name__)
        return _browser_oauth_result(request, "error")


def _oauth_user(provider: str, code: str, db: PgConnection) -> dict[str, Any]:
    profile = fetch_oauth_profile(provider, code)
    email = profile["email"]
    if not email or len(email) > 150:
        raise HTTPException(status_code=400, detail="Provider account must expose a valid verified email")
    full_name = (profile["full_name"] or email)[:100]
    avatar_url = profile["avatar_url"][:255] if profile["avatar_url"] else None

    with db, db.cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.role, u.is_active
            FROM user_oauth_accounts o
            JOIN users u ON u.id = o.user_id
            WHERE o.provider = %s AND o.provider_user_id = %s
            """,
            (provider, profile["provider_user_id"]),
        )
        user = cast(dict[str, Any] | None, cur.fetchone())

        if not user:
            cur.execute(
                "SELECT id, role, is_active, password_hash FROM users WHERE email = %s FOR UPDATE",
                (email,),
            )
            user = cast(dict[str, Any] | None, cur.fetchone())
            # A verified provider email does not authenticate existing password credentials.
            if user and user["password_hash"] is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This email belongs to a password account. Sign in with your password. "
                        "If you did not create the account or cannot sign in, contact an "
                        "administrator to verify ownership. Social account linking is not available."
                    ),
                )
            if not user:
                cur.execute(
                    """
                    INSERT INTO users (email, full_name, avatar_url, role, is_active)
                    VALUES (%s, %s, %s, 'cashier', FALSE)
                    RETURNING id, role, is_active
                    """,
                    (email, full_name, avatar_url),
                )
                user = cast(dict[str, Any], cur.fetchone())

            cur.execute(
                """
                INSERT INTO user_oauth_accounts (user_id, provider, provider_user_id, provider_email)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (provider, provider_user_id) DO NOTHING
                """,
                (user["id"], provider, profile["provider_user_id"], email),
            )

    return user


def _build_me_profile(user_id: int, db: PgConnection) -> dict[str, Any]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, username, full_name, avatar_url, role, is_active,
                   (password_hash IS NOT NULL) AS has_password
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cast(dict[str, Any] | None, cur.fetchone())
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        cur.execute(
            """
            SELECT provider, provider_email, created_at
            FROM user_oauth_accounts
            WHERE user_id = %s
            ORDER BY provider ASC
            """,
            (user_id,),
        )
        oauth_rows = [dict(r) for r in cur.fetchall()]

    profile = dict(row)
    methods: list[str] = []
    if profile["has_password"]:
        methods.append("password")
    for oa in oauth_rows:
        if oa["provider"] not in methods:
            methods.append(oa["provider"])
    profile["oauth_accounts"] = oauth_rows
    profile["auth_methods"] = methods
    profile["available_oauth_providers"] = [
        p for p, cfg in OAUTH_CONFIG.items() if cfg.get("client_id") and cfg.get("client_secret")
    ]
    return profile


@router.get("/auth/me")
def me(user: dict[str, Any] = Depends(get_current_user), db: PgConnection = Depends(get_db)):
    return _build_me_profile(user["id"], db)


@router.patch("/auth/me")
def update_me(
    body: ProfileUpdate,
    user: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    payload = body.model_dump(exclude_unset=True)
    updates: dict[str, Any] = {}
    old_avatar_to_clean: str | None = None

    if "full_name" in payload and payload["full_name"] is not None:
        updates["full_name"] = payload["full_name"]

    if "email" in payload and payload["email"] is not None:
        updates["email"] = str(payload["email"]).strip().lower()

    if "username" in payload and payload["username"] is not None:
        updates["username"] = payload["username"]

    if "avatar_url" in payload:
        raw_avatar = payload["avatar_url"] or ""
        if raw_avatar == "":
            updates["avatar_url"] = None
            old_avatar_to_clean = user.get("avatar_url")
        elif raw_avatar.startswith("/") or raw_avatar.startswith(("http://", "https://")):
            updates["avatar_url"] = raw_avatar
            if user.get("avatar_url") and user.get("avatar_url") != raw_avatar:
                old_avatar_to_clean = user.get("avatar_url")
        else:
            raise HTTPException(
                status_code=422,
                detail="Avatar URL must start with /, http://, or https://",
            )

    if payload.get("new_password"):
        with db.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s", (user["id"],))
            row = cast(dict[str, Any] | None, cur.fetchone())
        existing_hash = row["password_hash"] if row else None
        if existing_hash:
            current_pw = payload.get("current_password") or ""
            if not current_pw or not verify_password(current_pw, existing_hash):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
        updates["password_hash"] = hash_password(payload["new_password"])

    if not updates:
        raise HTTPException(status_code=400, detail="No profile fields to update")

    set_clause = ", ".join(f"{col} = %s" for col in updates)
    try:
        with db, db.cursor() as cur:
            cur.execute(
                f"""
                UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id
                """,
                (*updates.values(), user["id"]),
            )
            updated = cur.fetchone()
    except UniqueViolation as exc:
        err_text = str(exc).lower()
        if "email" in err_text:
            raise HTTPException(status_code=409, detail="Email is already registered")
        raise HTTPException(status_code=409, detail="Username is already taken")

    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    if old_avatar_to_clean:
        remove_local_upload(old_avatar_to_clean, "avatars")
    return _build_me_profile(user["id"], db)


@router.post("/auth/me/avatar")
def upload_my_avatar(
    body: AvatarUploadRequest,
    user: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    new_url = save_local_image(body.image_data, "avatars", f"user_{user['id']}")

    old_avatar = user.get("avatar_url")
    with db, db.cursor() as cur:
        cur.execute(
            "UPDATE users SET avatar_url = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (new_url, user["id"]),
        )
    remove_local_upload(old_avatar, "avatars")
    return _build_me_profile(user["id"], db)


@router.delete("/auth/me/password")
def remove_my_password(
    user: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    profile = _build_me_profile(user["id"], db)
    if not profile["has_password"]:
        raise HTTPException(status_code=400, detail="Password sign-in is not enabled on this account")
    if len(profile["oauth_accounts"]) == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove password without another connected sign-in method",
        )
    with db, db.cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (user["id"],),
        )
    return _build_me_profile(user["id"], db)


@router.delete("/auth/me/oauth/{provider}")
def unlink_my_oauth(
    provider: Literal["google", "discord"],
    user: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    profile = _build_me_profile(user["id"], db)
    linked = [oa["provider"] for oa in profile["oauth_accounts"]]
    if provider not in linked:
        raise HTTPException(status_code=404, detail=f"{provider.title()} is not connected to your account")
    remaining_methods = (1 if profile["has_password"] else 0) + (len(linked) - 1)
    if remaining_methods < 1:
        raise HTTPException(
            status_code=400,
            detail="Set a password or connect another provider before disconnecting your only sign-in method",
        )
    with db, db.cursor() as cur:
        cur.execute(
            "DELETE FROM user_oauth_accounts WHERE user_id = %s AND provider = %s",
            (user["id"], provider),
        )
    return _build_me_profile(user["id"], db)


@router.get("/users", dependencies=[Depends(require_role("admin"))])
def list_users(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT id, email, username, full_name, avatar_url, role, is_active, created_at FROM users ORDER BY id")
        return cur.fetchall()


@router.get("/users/{user_id}", dependencies=[Depends(require_role("admin"))])
def get_user(user_id: int, db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, email, username, full_name, avatar_url, role, is_active, created_at FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.post("/users", status_code=201, dependencies=[Depends(require_role("admin"))])
def create_user(body: UserCreate, db: PgConnection = Depends(get_db)):
    pw_hash = hash_password(body.password) if body.password else None
    with db, db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, email, username, full_name, role, is_active, created_at
            """,
            (body.email, body.username, pw_hash, body.full_name, body.role, body.is_active),
        )
        return cur.fetchone()


@router.patch("/users/{user_id}", dependencies=[Depends(require_role("admin"))])
def update_user(user_id: int, body: UserUpdate, db: PgConnection = Depends(get_db)):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "password" in fields:
        fields["password_hash"] = hash_password(fields.pop("password"))
    set_clause = ", ".join(f"{col} = %s" for col in fields)
    with db, db.cursor() as cur:
        cur.execute(
            f"""
            UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, email, username, full_name, role, is_active
            """,
            (*fields.values(), user_id),
        )
        updated = cur.fetchone()
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@router.delete("/users/{user_id}", dependencies=[Depends(require_role("admin"))])
def deactivate_user(user_id: int, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute(
            """
            UPDATE users SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, email, full_name, role, is_active
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row