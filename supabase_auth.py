"""Supabase Auth + profiles for Ped Bot.

The browser talks to GoTrue (email/password and optional OAuth) with the
anon key. This module verifies the JWT on each /api call, keeps a row in
public.profiles, lists users for the admin page, and publishes the phone
tunnel URL to public.pc_presence so the Android app can skip the paste-link.

Secrets stay in the environment. Nothing here logs tokens or keys.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

_TIMEOUT = 12
_ADMIN_ROLES = {"admin"}
_STATUSES = {"free", "trial", "paid"}


def _builtin(name: str) -> str:
    """1.7.1: public project URL + anon key baked into the installer build
    (supabase_public.py, generated at build time, git-ignored). The anon key is
    public by design. The service role key is never baked in."""
    try:
        import supabase_public  # type: ignore
    except Exception:
        return ""
    return str(getattr(supabase_public, name, "") or "").strip()


def _url() -> str:
    return ((os.environ.get("SUPABASE_URL") or "").strip() or _builtin("SUPABASE_URL")).rstrip("/")


def _anon() -> str:
    return (os.environ.get("SUPABASE_ANON_KEY") or "").strip() or _builtin("SUPABASE_ANON_KEY")


def has_service() -> bool:
    """Admin-only extras (Users page, profile rows, phone link publish)."""
    return bool(_service())


def _service() -> str:
    return (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def _admin_email() -> str:
    return (os.environ.get("ADMIN_EMAIL") or "").strip().casefold()


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def missing_env() -> list[str]:
    needed = []
    if not _url() or not _url().startswith("https://"):
        needed.append("SUPABASE_URL")
    if not _anon():
        needed.append("SUPABASE_ANON_KEY")
    # 1.7.1: the service role key is optional; sign-in works without it.
    return needed


def configured() -> bool:
    return not missing_env()


def local_bypass_allowed() -> bool:
    """1.5.10 H6: single-user PC may run without Supabase until keys are set.

    On by default when nothing is configured (desktop setup). Set
    PEDBOT_LOCAL_BYPASS=0 to force the setup screen. Remote phone always
    needs a cookie or JWT and never uses this bypass.
    """
    raw = (os.environ.get("PEDBOT_LOCAL_BYPASS") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    # Auto: bypass only while Supabase is incomplete.
    return not configured()


def public_config(origin: str | None = None) -> dict[str, Any]:
    """Safe for the login page. Anon key is designed to be public."""
    miss = missing_env()
    redirect = "http://127.0.0.1:8765/"
    if origin and origin_allowed(origin):
        redirect = origin.rstrip("/") + "/"
    elif origin:
        # Phone / tunnel HTTPS origin for OAuth return (M8).
        host = urlparse(origin).hostname or ""
        scheme = urlparse(origin).scheme or ""
        if scheme == "https" and host.endswith(".trycloudflare.com"):
            redirect = origin.rstrip("/") + "/"
    return {
        "configured": not miss,
        "adminTools": has_service(),
        "url": _url() if not miss else "",
        "anonKey": _anon() if not miss else "",
        "oauthGoogle": _flag("SUPABASE_OAUTH_GOOGLE"),
        "oauthGithub": _flag("SUPABASE_OAUTH_GITHUB"),
        "missing": miss,
        "redirect": redirect,
        "bypass": local_bypass_allowed() and bool(miss),
    }


def _headers(key: str, bearer: str | None = None) -> dict[str, str]:
    token = bearer or key
    return {
        "apikey": key,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _bearer_from(handler: Any) -> str:
    raw = (handler.headers.get("Authorization") or "").strip()
    if raw.lower().startswith("bearer "):
        return raw.split(" ", 1)[1].strip()
    return ""


def _gotrue_user(access_token: str) -> dict[str, Any] | None:
    if not access_token or not configured():
        return None
    try:
        res = requests.get(
            f"{_url()}/auth/v1/user",
            headers=_headers(_anon(), access_token),
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        return None
    if res.status_code != 200:
        return None
    try:
        data = res.json()
    except ValueError:
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return data


def _rest(method: str, path: str, *, json: Any = None, params: dict[str, str] | None = None) -> Any:
    if not _service():
        return None
    try:
      res = requests.request(
        method,
        f"{_url()}/rest/v1/{path.lstrip('/')}",
        headers={
            **_headers(_service()),
            "Prefer": "return=representation,resolution=merge-duplicates",
        },
        params=params,
        json=json,
        timeout=_TIMEOUT,
      )
    except requests.RequestException:
        return None
    if res.status_code >= 400:
        return None
    if not res.content:
        return []
    try:
        return res.json()
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_profile(auth_user: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a free profile if the signup trigger has not run yet."""
    uid = str(auth_user.get("id") or "")
    email = str(auth_user.get("email") or "").strip()
    if not uid or not email:
        return None
    meta = auth_user.get("user_metadata") if isinstance(auth_user.get("user_metadata"), dict) else {}
    full_name = str((meta or {}).get("full_name") or (meta or {}).get("name") or "").strip() or None
    rows = _rest("GET", "profiles", params={"id": f"eq.{uid}", "select": "*"})
    if isinstance(rows, list) and rows:
        row = rows[0]
        if _admin_email() and email.casefold() == _admin_email() and row.get("role") != "admin":
            patched = _rest(
                "PATCH",
                "profiles",
                params={"id": f"eq.{uid}"},
                json={"role": "admin", "email": email},
            )
            if isinstance(patched, list) and patched:
                return patched[0]
        return row
    created = _rest(
        "POST",
        "profiles",
        json={
            "id": uid,
            "email": email,
            "full_name": full_name,
            "subscription_status": "free",
            "stripe_customer_id": None,
            "role": "admin" if _admin_email() and email.casefold() == _admin_email() else "user",
        },
    )
    if isinstance(created, list) and created:
        return created[0]
    if isinstance(created, dict) and created.get("id"):
        return created
    return None


def touch_login(user: dict[str, Any] | None) -> None:
    if not user or not user.get("id"):
        return
    try:
        _rest(
            "PATCH",
            "profiles",
            params={"id": f"eq.{user['id']}"},
            json={"last_login": _now()},
        )
    except requests.RequestException:
        return


def user_from_token(access_token: str) -> dict[str, Any] | None:
    auth_user = _gotrue_user(access_token)
    if not auth_user:
        return None
    profile = ensure_profile(auth_user) or {}
    email = str(profile.get("email") or auth_user.get("email") or "")
    role = str(profile.get("role") or "user")
    if _admin_email() and email.casefold() == _admin_email():
        role = "admin"
    status = str(profile.get("subscription_status") or "free")
    if status not in _STATUSES:
        status = "free"
    return {
        "id": str(auth_user.get("id") or profile.get("id") or ""),
        "email": email,
        "full_name": profile.get("full_name") or None,
        "created_at": profile.get("created_at"),
        "last_login": profile.get("last_login"),
        "subscription_status": status,
        "stripe_customer_id": profile.get("stripe_customer_id"),
        "stripe_subscription_id": profile.get("stripe_subscription_id"),
        "plan": profile.get("plan"),
        "role": role,
        "is_admin": role in _ADMIN_ROLES,
    }


def user_from_request(handler: Any) -> dict[str, Any] | None:
    token = _bearer_from(handler)
    if not token:
        return None
    return user_from_token(token)


def publish_pc_url(url: str) -> bool:
    """Upsert the current phone tunnel URL. Never stores the remote token."""
    if not configured():
        return False
    clean = (url or "").strip().rstrip("/")
    if not clean.startswith("https://"):
        return False
    rows = _rest(
        "POST",
        "pc_presence",
        params={"on_conflict": "id"},
        json={"id": "default", "url": clean, "updated_at": _now()},
    )
    return rows is not None


def is_admin(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    if user.get("is_admin") or user.get("role") in _ADMIN_ROLES:
        return True
    email = str(user.get("email") or "").casefold()
    return bool(_admin_email() and email == _admin_email())


def public_user(user: dict[str, Any] | None) -> dict[str, Any]:
    if not user:
        return {"ok": False, "error": "Please sign in.", "code": "auth_required"}
    return {
        "ok": True,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "full_name": user.get("full_name"),
            "created_at": user.get("created_at"),
            "last_login": user.get("last_login"),
            "subscription_status": user.get("subscription_status") or "free",
            "stripe_customer_id": user.get("stripe_customer_id"),
            "role": user.get("role") or "user",
            "is_admin": is_admin(user),
        },
    }


def _row_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "full_name": row.get("full_name") or "",
        "created_at": row.get("created_at"),
        "last_login": row.get("last_login"),
        "subscription_status": row.get("subscription_status") or "free",
        "stripe_customer_id": row.get("stripe_customer_id"),
        "role": row.get("role") or "user",
    }


def list_profiles() -> dict[str, Any]:
    if not _service():
        return {"ok": False, "error": "The Users page needs SUPABASE_SERVICE_ROLE_KEY in this PC's .env.", "code": "no_service_key", "count": 0, "users": []}
    rows = _rest(
        "GET",
        "profiles",
        params={
            "select": "id,email,full_name,created_at,last_login,subscription_status,stripe_customer_id,role",
            "order": "created_at.desc",
        },
    )
    if not isinstance(rows, list):
        return {"ok": False, "error": "Could not read users from the database.", "count": 0, "users": []}
    users = [_row_public(r) for r in rows if isinstance(r, dict)]
    return {"ok": True, "count": len(users), "users": users}


def origin_allowed(origin: str | None) -> bool:
    """OAuth redirect stays on this PC or the current phone tunnel."""
    if not origin:
        return True
    host = (urlparse(origin).hostname or "").casefold()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return True
    # Phone quick tunnel (Cloudflare). Still HTTPS-only via callers.
    return host.endswith(".trycloudflare.com")
