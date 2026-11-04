"""1.9.3: project creation (Free limit), App factory waits for the real build, /builds serving, busy retries."""
import threading
import time

import pytest


def test_free_plan_allows_one_project(monkeypatch):
    import plan191, groups
    monkeypatch.setattr(plan191, "is_pro", lambda: False)
    monkeypatch.setattr(groups, "list_groups", lambda: [])
    assert plan191.can_add_group() is None                     # first project is free
    monkeypatch.setattr(groups, "list_groups", lambda: [{"id": "g1"}])
    r = plan191.can_add_group()
    assert r and "project" in r["error"].lower()                # second one asks for Pro
    monkeypatch.setattr(plan191, "is_pro", lambda: True)
    assert plan191.can_add_group() is None


def test_build_file_stays_inside_build(tmp_path, monkeypatch):
    import app_builder, studio182
    monkeypatch.setattr(app_builder, "builds_root", lambda: tmp_path)
    (tmp_path / "tip-calc").mkdir(); (tmp_path / "tip-calc" / "index.html").write_text("<h1>hi</h1>")
    (tmp_path / "secret.txt").write_text("x")
    assert studio182.build_file("tip-calc", "index.html").read_text() == "<h1>hi</h1>"
    assert studio182.build_file("tip-calc", "") is not None
    for name, rel in [("tip-calc", "../secret.txt"), ("..", "secret.txt"), ("tip-calc", "/etc/passwd"),
                      ("Tip Calc", "index.html"), ("tip-calc", "missing.html")]:
        assert studio182.build_file(name, rel) is None


def test_app_factory_waits_for_real_result(monkeypatch):
    import app_builder, studio182
    job = {"status": "running", "log": ["12:00:00 Writing files"]}
    monkeypatch.setattr(app_builder, "build_app", lambda goal: (app_builder._JOBS.__setitem__("demo-app", job), {"ok": True, "name": "demo-app", "project": "/p"})[1])
    monkeypatch.setattr(app_builder, "final_message", lambda out: "Built it.")
    real_sleep = time.sleep
    monkeypatch.setattr(studio182.time, "sleep", lambda s: real_sleep(0.01))
    jid = studio182.app_factory("a tip calculator")["job"]
    real_sleep(0.2)
    assert studio182.app_job(jid)["status"] == "building"        # not "done, 0 files" straight away
    job.update(status="done", result={"project": "/p", "files": ["index.html", "app.js"]})
    for _ in range(100):
        if studio182.app_job(jid)["status"] != "building":
            break
        real_sleep(0.02)
    j = studio182.app_job(jid)
    assert j["status"] == "done" and j["files"] == ["index.html", "app.js"]
    assert j["preview"] == "/builds/demo-app/index.html" and j["message"] == "Built it."


def test_retry_busy_then_success_clears_partial_text(monkeypatch):
    import chat_app
    monkeypatch.setattr(chat_app, "BUSY_WAITS", (0, 0, 0))
    replies = iter(["Gemini is busy right now. Try again.", "PONG"])
    history = [{"role": "user", "text": "ping"}]
    events = []

    def run():
        history.append({"role": "model", "text": "partial"})
        return next(replies)
    out = chat_app._retry_busy(run, history, events.append, threading.Event())
    assert out == "PONG"
    assert [e["event"] for e in events].count("reset_text") == 1
    assert len(history) == 2                                     # failed attempt removed


def test_retry_busy_gives_up_and_passes_other_errors(monkeypatch):
    import chat_app
    monkeypatch.setattr(chat_app, "BUSY_WAITS", (0, 0))
    calls = []
    out = chat_app._retry_busy(lambda: calls.append(1) or "All Gemini models are busy.", [], lambda e: None, threading.Event())
    assert out.startswith("All Gemini") and len(calls) == 3
    with pytest.raises(RuntimeError):
        chat_app._retry_busy(lambda: (_ for _ in ()).throw(RuntimeError("bad key")), [], lambda e: None, None)
    n = []
    def boom():
        n.append(1)
        if len(n) < 2:
            raise RuntimeError("503 UNAVAILABLE high demand")
        return "ok"
    assert chat_app._retry_busy(boom, [], lambda e: None, None) == "ok"
