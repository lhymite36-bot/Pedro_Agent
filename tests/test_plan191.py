"""1.9.1 Ped Bot Pro plan: gates, simulate, test-mode keys, signature check."""
import hashlib, hmac, importlib

import pytest


@pytest.fixture()
def plan(tmp_path, monkeypatch):
    monkeypatch.setenv("PEDRO_AGENT_STORAGE", str(tmp_path))
    for k in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "PEDBOT_FORCE_PLAN", "PEDBOT_DEV_SIMULATE"):
        monkeypatch.delenv(k, raising=False)
    import agent_config, plan191
    monkeypatch.setattr(agent_config, "storage_dir", lambda: tmp_path)
    return importlib.reload(plan191)


def test_free_by_default_and_gates(plan):
    assert plan.status()["plan"] == "free"
    assert plan.gate("lab")["code"] == "pro_required"
    assert plan.theme_ok({"preset": "aurora"}) is None
    assert plan.theme_ok({"preset": "neon"})["feature"] == "themes"


def test_simulate_unlocks_and_downgrade(plan):
    r = plan.simulate("year")
    assert r["ok"] and r["isPro"] and r["period"] == "year"
    assert plan.gate("avatar3d") is None and plan.theme_ok({"preset": "neon"}) is None
    assert not plan.downgrade()["isPro"]


def test_live_key_refused(plan, monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_abc")
    c = plan.config()
    assert c["keyId"] == "" and not c["checkout"] and "Live" in c["note"]
    assert "secret" not in str(c).lower() or "RAZORPAY_KEY_SECRET" not in str(c)


def test_signature_checked(plan, monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "s3cret")
    bad = plan.verify({"period": "month", "razorpay_payment_id": "pay_1", "razorpay_order_id": "order_1", "razorpay_signature": "x"})
    assert not bad["ok"]
    sig = hmac.new(b"s3cret", b"order_1|pay_1", hashlib.sha256).hexdigest()
    ok = plan.verify({"period": "month", "razorpay_payment_id": "pay_1", "razorpay_order_id": "order_1", "razorpay_signature": sig})
    assert ok["ok"] and ok["isPro"]
    assert "s3cret" not in str(plan.config())


def test_bot_limit(plan, monkeypatch):
    import bots
    monkeypatch.setattr(bots, "list_bots", lambda: [{}, {}])
    assert plan.can_add_bot()["feature"] == "bots"
    plan.simulate("month")
    assert plan.can_add_bot() is None


def test_save_bot_enforces_limit_for_every_path(plan, monkeypatch):
    import bots
    monkeypatch.setattr(bots, "list_bots", lambda: [{}, {}])
    monkeypatch.setattr(bots, "get_bot", lambda _x: None)
    with pytest.raises(ValueError):
        bots.save_bot({"name": "third"})


def test_routine_limit(plan, monkeypatch):
    import routines
    monkeypatch.setattr(routines, "_load", lambda: {"routines": [{"id": "a"}], "feed": []})
    r = routines.create_routine("Two", "say hi", "every day at 9 AM")
    assert r.get("code") == "pro_required"
    plan.simulate("month")
    monkeypatch.setattr(routines, "_put", lambda r: None)
    monkeypatch.setattr(routines, "find", lambda n: None)
    assert routines.create_routine("Two", "say hi", "every day at 9 AM").get("ok")
