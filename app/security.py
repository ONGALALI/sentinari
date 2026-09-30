from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _env_flag(name: str, fallback: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return fallback
    return raw in {"0", "false", "no", "off"}


def get_admin_auth_settings(settings: dict[str, Any]) -> dict[str, Any]:
    security = settings.get("security", {})
    if not isinstance(security, dict):
        security = {}
    admin_auth = security.get("admin_auth", {})
    if not isinstance(admin_auth, dict):
        admin_auth = {}

    enabled = _env_flag("SMI_ADMIN_AUTH_ENABLED", bool(admin_auth.get("disabled", False)))
    username = (os.environ.get("SENTINARI_ADMIN_USERNAME") or os.environ.get("SMI_ADMIN_USERNAME") or str(admin_auth.get("username") or "smi")).strip() or "smi"
    password_env = str(admin_auth.get("password_env") or "SENTINARI_ADMIN_PASSWORD").strip() or "SENTINARI_ADMIN_PASSWORD"
    configured_password = (
        os.environ.get(password_env)
        or os.environ.get("SENTINARI_ADMIN_PASSWORD")
        or os.environ.get("SMI_ADMIN_PASSWORD")
        or str(admin_auth.get("password") or "").strip()
    )
    session_cookie_name = (
        os.environ.get("SENTINARI_ADMIN_SESSION_COOKIE")
        or os.environ.get("SMI_ADMIN_SESSION_COOKIE")
        or str(admin_auth.get("session_cookie_name") or "smi_admin_session").strip()
        or "smi_admin_session"
    )
    ttl_hours = int(admin_auth.get("session_ttl_hours") or 12)
    ttl_hours = max(1, min(168, ttl_hours))

    explicit_secret = (os.environ.get("SENTINARI_ADMIN_SESSION_SECRET") or os.environ.get("SMI_ADMIN_SESSION_SECRET") or "").strip()
    if explicit_secret:
        secret = explicit_secret
    else:
        # Stable fallback for local environments when no explicit secret is provided.
        material = f"{username}|{configured_password}|SMI_ADMIN_SESSION"
        secret = hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()

    return {
        "enabled": enabled,
        "username": username,
        "password": configured_password,
        "password_env": password_env,
        "configured": bool(configured_password),
        "session_cookie_name": session_cookie_name,
        "session_ttl_hours": ttl_hours,
        "session_secret": secret,
    }


def verify_admin_credentials(username: str, password: str, auth: dict[str, Any]) -> bool:
    expected_user = str(auth.get("username") or "").strip()
    expected_password = str(auth.get("password") or "").strip()
    if not expected_user or not expected_password:
        return False
    return hmac.compare_digest(username or "", expected_user) and hmac.compare_digest(password or "", expected_password)


def create_admin_session_token(auth: dict[str, Any]) -> tuple[str, int]:
    ttl_hours = int(auth.get("session_ttl_hours") or 12)
    ttl_seconds = max(1, ttl_hours * 3600)
    expires_at = int(time.time()) + ttl_seconds
    payload = {"u": str(auth.get("username") or ""), "exp": expires_at}
    body = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    sig = _sign_text(body, str(auth.get("session_secret") or ""))
    return f"{body}.{sig}", expires_at


def validate_admin_session_token(token: str | None, auth: dict[str, Any]) -> bool:
    raw = (token or "").strip()
    if not raw or "." not in raw:
        return False
    body, sig = raw.split(".", 1)
    expected_sig = _sign_text(body, str(auth.get("session_secret") or ""))
    if not hmac.compare_digest(sig, expected_sig):
        return False
    payload = _decode_payload(body)
    if not payload:
        return False
    username = str(payload.get("u") or "").strip()
    expires_at = int(payload.get("exp") or 0)
    if username != str(auth.get("username") or "").strip():
        return False
    if expires_at <= int(time.time()):
        return False
    return True


def parse_basic_auth_header(header_value: str | None) -> tuple[str, str] | None:
    raw = (header_value or "").strip()
    if not raw.lower().startswith("basic "):
        return None
    encoded = raw[6:].strip()
    if not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
    except Exception:
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return username, password


def _decode_payload(body: str) -> dict[str, Any] | None:
    try:
        decoded = _b64url_decode(body)
        payload = json.loads(decoded.decode("utf-8", errors="ignore"))
        if not isinstance(payload, dict):
            return None
        return payload
    except Exception:
        return None


def _sign_text(text: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode(text + padding)
