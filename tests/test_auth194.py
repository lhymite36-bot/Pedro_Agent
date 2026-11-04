"""1.9.4: a slow / offline / 5xx Supabase must never look like "signed out"."""
import base64
import json
import time

import pytest
import requests


def _jwt(exp):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return b({"alg": "HS256"}) + "." + b({"sub": "u1", "exp": exp}) + ".sig"


class _Res:
    def __init__(self, code, data=None):
        self.status_code = code; self._d = data or {}
    def json(self):
        return self._d


@pytest.fixture
def sa(monkeypatch):
    import supabase_auth as sa
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test")
    monkeypatch.setattr(sa, "ensure_profile", lambda u: {"email": u.get("email")})
    monkeypatch.setattr(sa.time, "sleep", lambda s: None)
    sa._cache.clear()
    return sa


def _mode(monkeypatch, sa, fn):
    calls = []
    def get(url, headers=None, timeout=None):
        calls.append(timeout)
        return fn()
    monkeypatch.setattr(sa.requests, "get", get)
    return calls


def test_timeout_is_not_signed_out(monkeypatch, sa):
    def boom():
        raise requests.Timeout("slow")
    calls = _mode(monkeypatch, sa, boom)
    with pytest.raises(sa.AuthUnavailable):
        sa.user_from_token(_jwt(time.time() + 3600))
    assert len(calls) == 2 and calls[0][1] >= 20        # retried, long read timeout


@pytest.mark.parametrize("code", [500, 502, 503, 504, 429])
def test_5xx_is_unavailable(monkeypatch, sa, code):
    _mode(monkeypatch, sa, lambda: _Res(code))
    with pytest.raises(sa.AuthUnavailable):
        sa.user_from_token(_jwt(time.time() + 3600))


@pytest.mark.parametrize("code", [401, 403])
def test_definite_rejection_is_none(monkeypatch, sa, code):
    _mode(monkeypatch, sa, lambda: _Res(code, {"msg": "invalid JWT"}))
    assert sa.user_from_token(_jwt(time.time() + 3600)) is None


def test_verified_user_survives_outage(monkeypatch, sa):
    tok = _jwt(time.time() + 3600)
    _mode(monkeypatch, sa, lambda: _Res(200, {"id": "u1", "email": "p@x.com"}))
    assert sa.user_from_token(tok)["email"] == "p@x.com"
    def down():
        raise requests.ConnectionError("offline")
    _mode(monkeypatch, sa, down)
    monkeypatch.setattr(sa, "_FRESH_SECONDS", 0)
    assert sa.user_from_token(tok)["email"] == "p@x.com"   # cached, still signed in


def test_expired_token_local_grace_only(monkeypatch, sa):
    tok = _jwt(time.time() - 600)
    _mode(monkeypatch, sa, lambda: _Res(200, {"id": "u1", "email": "p@x.com"}))
    sa.user_from_token(tok)
    monkeypatch.setattr(sa, "_FRESH_SECONDS", 0)
    _mode(monkeypatch, sa, lambda: _Res(503))
    assert sa.user_from_token(tok, local=True)["id"] == "u1"   # this PC stays signed in offline
    with pytest.raises(sa.AuthUnavailable):
        sa.user_from_token(tok, local=False)                   # the phone link does not


def test_rejection_clears_cache(monkeypatch, sa):
    tok = _jwt(time.time() + 3600)
    _mode(monkeypatch, sa, lambda: _Res(200, {"id": "u1", "email": "p@x.com"}))
    sa.user_from_token(tok)
    monkeypatch.setattr(sa, "_FRESH_SECONDS", 0)
    _mode(monkeypatch, sa, lambda: _Res(401))
    assert sa.user_from_token(tok) is None
    _mode(monkeypatch, sa, lambda: _Res(503))
    with pytest.raises(sa.AuthUnavailable):
        sa.user_from_token(tok)


def test_plan_restore_keeps_pro_on_5xx(monkeypatch, tmp_path):
    import plan191
    monkeypatch.setattr(plan191, "_path", lambda: tmp_path / "plan.json")
    plan191._save({"plan": "pro", "period": "month", "until": time.time() + 86400, "source": "test"})
    monkeypatch.setattr(plan191, "_sb", lambda: ("https://x.supabase.co", "anon"))
    monkeypatch.setattr(plan191.requests, "get", lambda *a, **k: _Res(503))
    r = plan191.restore("tok", {"id": "u1"})
    assert r["isPro"] and "unchanged" in r["error"]
    def boom(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(plan191.requests, "get", boom)
    assert plan191.restore("tok", {"id": "u1"})["isPro"]
    assert plan191.status()["isPro"]
