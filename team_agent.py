"""Multi-agent team: a planner splits a goal into sub-tasks for coder,
browser, files and research agents. They run in threads, each limited to its
own tool set, then a reviewer checks the combined result and can send a
sub-task back once. Every tool call still goes through invoke_tool, so
rules.yaml (blocked tools, paths, confirm categories) applies to all agents.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import threading
from typing import Any, Callable

import llm
import rules

DEFAULTS = {"max_parallel": 2, "max_subtasks": 6, "review": True, "review_rounds": 1}

ROLES: dict[str, dict[str, Any]] = {
    "coder": {
        "brief": "You write and fix code, build programs and run tests.",
        "tools": r"build_local_program|self_heal|git_manager|code_engineer|file|folder|read_|write_|list_|run_tests|local_build",
    },
    "browser": {
        "brief": "You operate web pages: open sites, click, fill forms, download.",
        "tools": r"browser|open_website|page|playwright|search_youtube|download",
    },
    "files": {
        "brief": "You find, read, organise, copy and move local files.",
        "tools": r"file|folder|director|copy|move|delete|search_local|search_files|rag|excel|clipboard",
    },
    "research": {
        "brief": "You search the web and summarise facts with sources.",
        "tools": r"search|fetch|web|news|recall_memory|rag",
    },
}
ALWAYS = {"recall_memory", "remember_fact"}

# Tests replace this: runner(role, task, tools) -> str
runner: Callable[[str, str, set[str]], str] | None = None


LIVE_EMIT: Callable[[dict[str, Any]], None] | None = None


def settings() -> dict[str, Any]:
    return rules.section("team", DEFAULTS)


def tools_for(role: str) -> set[str]:
    import agent_core

    pattern = re.compile(ROLES[role]["tools"], re.I)
    names = {name for name in agent_core.TOOLS if pattern.search(name)} | (ALWAYS & set(agent_core.TOOLS))
    names.discard("run_team")  # no recursion
    return {name for name in names if rules.tool_block_reason(name) is None}


def plan(goal: str) -> list[dict[str, str]]:
    cap = int(settings()["max_subtasks"]) or 6
    prompt = (
        "You are the planner of a small agent team on a Windows PC. Split the goal "
        f"into at most {cap} independent sub-tasks. Roles: "
        + "; ".join(f"{name}: {info['brief']}" for name, info in ROLES.items())
        + ". Reply with JSON only: [{\"role\": \"coder|browser|files|research\", \"task\": \"...\"}].\n\n"
        f"GOAL: {goal}"
    )
    try:
        data = llm.json_from(llm.text(prompt))
    except ValueError:
        data = []
    steps = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().casefold()
        task = " ".join(str(item.get("task", "")).split())
        if role in ROLES and task:
            steps.append({"role": role, "task": task})
    return steps[:cap] or [{"role": "research", "task": goal}]


def _default_runner(role: str, task: str, tools: set[str]) -> str:
    import agent_core

    prompt = (
        f"[Team member: {role}] {ROLES[role]['brief']} Only use these tools: "
        f"{', '.join(sorted(tools)) or 'none'}. Do this sub-task and report the result briefly.\n\n{task}"
    )
    agent_core.set_tool_scope(tools)
    try:
        return agent_core.run_agent(prompt, [], os.environ.get("GEMINI_MODEL", agent_core.DEFAULT_MODEL))
    finally:
        agent_core.set_tool_scope(None)


def _run_step(step: dict[str, str], cancel: threading.Event | None) -> dict[str, Any]:
    live = LIVE_EMIT
    if live is not None:
        try:
            live({"event": "step", "label": f"{step['role'].capitalize()} agent: {str(step['task'])[:60]}", "name": "team"})
        except Exception:
            pass
    if cancel is not None and cancel.is_set():
        return {**step, "ok": False, "result": "cancelled"}
    tools = tools_for(step["role"])
    try:
        result = (runner or _default_runner)(step["role"], step["task"], tools)
        return {**step, "ok": True, "result": str(result or "")[:4000]}
    except Exception as exc:
        return {**step, "ok": False, "result": f"failed: {exc}"[:2000]}


def review(goal: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    joined = "\n\n".join(f"#{i} [{r['role']}] {r['task']}\n{r['result']}" for i, r in enumerate(results))
    prompt = (
        "You are the reviewer. Check whether the team's results meet the goal. "
        "Reply with JSON only: {\"ok\": true|false, \"summary\": \"answer for the user\", "
        "\"redo\": [{\"index\": n, \"task\": \"corrected sub-task\"}]}.\n\n"
        f"GOAL: {goal}\n\nRESULTS:\n{joined}"
    )
    try:
        data = llm.json_from(llm.text(prompt))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "ok": bool(data.get("ok", True)),
        "summary": str(data.get("summary") or joined)[:6000],
        "redo": [r for r in data.get("redo") or [] if isinstance(r, dict)],
    }


def run_team(goal: str, cancel_event: threading.Event | None = None,
             on_event: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    import agent_core

    goal = " ".join((goal or "").split())
    if not goal:
        return agent_core._err("A goal is required.")
    cfg = settings()
    emit = on_event or LIVE_EMIT or (lambda _e: None)
    steps = plan(goal)
    emit({"event": "team_plan", "steps": steps})
    workers = max(1, int(cfg["max_parallel"] or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="team") as pool:
        results = list(pool.map(lambda s: _run_step(s, cancel_event), steps))
    for r in results:
        emit({"event": "team_result", "role": r["role"], "ok": r["ok"]})
    verdict = {"ok": all(r["ok"] for r in results), "summary": "\n".join(r["result"] for r in results), "redo": []}
    if cfg.get("review", True):
        rounds = int(cfg.get("review_rounds", 1) or 0)
        verdict = review(goal, results)
        while not verdict["ok"] and verdict["redo"] and rounds > 0:
            rounds -= 1
            for item in verdict["redo"]:
                try:
                    index = int(item.get("index"))
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(results):
                    task = " ".join(str(item.get("task") or results[index]["task"]).split())
                    results[index] = _run_step({"role": results[index]["role"], "task": task}, cancel_event)
            verdict = review(goal, results)
        emit({"event": "team_review", "ok": verdict["ok"]})
    return agent_core._ok(
        verdict["summary"],
        reviewed=bool(cfg.get("review", True)),
        approved=verdict["ok"],
        steps=[{"role": r["role"], "task": r["task"], "ok": r["ok"], "result": r["result"][:1500]} for r in results],
    )


DECLARATIONS = [
    {
        "name": "run_team",
        "description": (
            "Hand a bigger goal to the agent team: a planner splits it into sub-tasks for "
            "coder, browser, files and research agents that work in parallel, then a reviewer "
            "checks the result. Use for multi-part jobs, not single actions."
        ),
        "parameters": {
            "type": "object",
            "properties": {"goal": {"type": "string", "description": "What the team should get done."}},
            "required": ["goal"],
        },
    }
]
TOOLS = {"run_team": run_team}
