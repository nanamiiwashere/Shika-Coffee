import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.config import JWT_SECRET
from app.database import get_db
from app.models import User

JWT_ALG = "HS256"
PASSWORD_HASHER = PasswordHash.recommended()
BEARER = HTTPBearer()
OAUTH_STATE_COOKIE = "shika_oauth_state"
OAUTH_HANDOFF_COOKIE = "shika_oauth_handoff"
OAUTH_STATE_TTL = 600
OAUTH_HANDOFF_TTL = 60
OAUTH_COOKIE_SECURE = os.getenv("OAUTH_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}

OAUTH_CONFIG: dict[str, dict[str, str]] = {
    "google": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/oauth/google/callback"),
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "discord": {
        "client_id": os.getenv("DISCORD_CLIENT_ID", ""),
        "client_secret": os.getenv("DISCORD_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/oauth/discord/callback"),
        "auth_url": "https://discord.com/api/oauth2/authorize",
        "token_url": "https://discord.com/api/oauth2/token",
        "userinfo_url": "https://discord.com/api/users/@me",
        "scope": "identify email",
    },
}


def hash_password(plain: str) -> str:
    return PASSWORD_HASHER.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return PASSWORD_HASHER.verify(plain, hashed)


def create_access_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(BEARER),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
        # State and handoff JWTs share the signing key, but are never access tokens.
        if payload.get("purpose") is not None:
            raise ValueError("Not an access token")
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account inactive or not found")

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "is_active": user.is_active,
    }


def require_role(*allowed_roles: str):
    def _guard(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user["role"] not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _guard


def create_oauth_state(provider: str, *, flow: str = "api") -> str:
    payload = {
        "provider": provider,
        "purpose": "oauth_state",
        "flow": flow,
        "nonce": secrets.token_urlsafe(16),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=OAUTH_STATE_TTL),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def oauth_state_is_browser(provider: str, state: str) -> bool:
    """Recognize even expired browser states for feedback only, never authorization."""
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALG], options={"verify_exp": False})
    except jwt.PyJWTError:
        return False
    return (
        payload.get("purpose") == "oauth_state"
        and payload.get("provider") == provider
        and payload.get("flow") == "browser"
    )


def verify_oauth_state(provider: str, state: str, *, browser_cookie: str | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            state, JWT_SECRET, algorithms=[JWT_ALG],
            options={"require": ["exp", "purpose", "provider", "nonce"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state")
    if payload.get("purpose") != "oauth_state" or payload.get("provider") != provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    if payload.get("flow") == "browser" or browser_cookie is not None:
        if (
            payload.get("flow") != "browser"
            or not browser_cookie
            or not secrets.compare_digest(state, browser_cookie)
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth browser state mismatch")
    return payload


def create_oauth_handoff(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "purpose": "oauth_handoff",
        "nonce": secrets.token_urlsafe(16),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=OAUTH_HANDOFF_TTL),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def verify_oauth_handoff(token: str) -> int:
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALG],
            options={"require": ["exp", "sub", "purpose", "nonce"]},
        )
        if payload["purpose"] != "oauth_handoff":
            raise ValueError("Not an OAuth handoff")
        user_id = int(payload["sub"])
        if user_id <= 0:
            raise ValueError("Invalid user ID")
        return user_id
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OAuth session")


def build_oauth_authorize_url(provider: str, state: str | None = None) -> str:
    cfg = OAUTH_CONFIG[provider]
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state or create_oauth_state(provider),
    }
    return f"{cfg['auth_url']}?{urlencode(params)}"


def fetch_oauth_profile(provider: str, code: str) -> dict[str, str | None]:
    cfg = OAUTH_CONFIG[provider]
    try:
        with httpx.Client(timeout=10.0) as client:
            token_res = client.post(
                cfg["token_url"],
                data={
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": cfg["redirect_uri"],
                },
                headers={"Accept": "application/json"},
            )
            token_res.raise_for_status()
            access_token = token_res.json()["access_token"]

            profile_res = client.get(
                cfg["userinfo_url"],
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile_res.raise_for_status()
            raw = profile_res.json()

        if provider == "google":
            provider_user_id = str(raw["sub"])
            is_verified = raw.get("email_verified") is True
            full_name = raw.get("name") or raw.get("email") or "Google User"
            avatar_url = raw.get("picture")
        else:
            discord_id = str(raw["id"])
            provider_user_id = discord_id
            is_verified = raw.get("verified") is True
            avatar_hash = raw.get("avatar")
            avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png" if avatar_hash else None
            full_name = raw.get("global_name") or raw.get("username") or "Discord User"
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth provider communication failed",
        )

    email = raw.get("email")
    if not is_verified or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider account must expose a verified email",
        )

    return {
        "provider_user_id": provider_user_id,
        "email": email,
        "full_name": full_name,
        "avatar_url": avatar_url,
    }