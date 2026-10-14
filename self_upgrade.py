"""Self-upgrade from failures in logs/agent.jsonl.

1. failure_report(): groups tool_error / failed tool events by tool.
2. propose_upgrade(tool): asks Gemini for a fixed version of the module that
   holds that tool, writes it into a COPY of the project, runs the test suite
   there, and saves the proposal (diff + test output) under
   storage/upgrades/<id>/. Nothing in the live project changes.
3. apply_upgrade(id, confirm): only with confirm="yes" (from you), and only
   for a proposal whose tests passed. The current file is backed up first;
   rollback_upgrade(id) restores it.
"""

from __future__ import annotations

import collections
import difflib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import llm
import rules

DEFAULTS = {"test_command": "python -m pytest -q -x", "test_timeout_seconds": 600, "max_log_lines": 20000}
COPY_SKIP = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "workspace", "storage", "logs", "node_modules", "bots"}

# Tests replace: test_runner(cmd, cwd, timeout) -> (code, output)
test_runner: Callable[[list[str], Path, int], tuple[int, str]] | None = None


def settings() -> dict[str, Any]:
    return rules.section("upgrade", DEFAULTS)


def app_dir() -> Path:
    env = os.environ.get("UPGRADE_APP_DIR", "").strip()
    if env:
        return Path(env)
    import agent_config

    return agent_config.APP_DIR


def _storage() -> Path:
    import agent_config

    return agent_config.storage_dir()


def log_path() -> Path:
    return _storage() / "logs" / "agent.jsonl"


def upgrades_dir() -> Path:
    return _storage() / "upgrades"


def failure_report(limit: int = 10) -> dict[str, Any]:
    path = log_path()
    counts: collections.Counter[str] = collections.Counter()
    samples: dict[str, list[str]] = collections.defaultdict(list)
    if path.is_file():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-int(settings()["max_log_lines"]):]
        for line in lines:
            try:
                rec = json.loads(line[line.find("{"):])
            except (ValueError, json.JSONDecodeError):
                continue
            tool = rec.get("tool")
            failed = rec.get("event") == "tool_error" or (rec.get("event") == "tool" and rec.get("ok") is False)
            if tool and failed:
                counts[tool] += 1
                if rec.get("error") and len(samples[tool]) < 5 and rec["error"] not in samples[tool]:
                    samples[tool].append(str(rec["error"])[:400])
    rows = [{"tool": t, "failures": n, "errors": samples.get(t, [])} for t, n in counts.most_common(limit)]
    return {"ok": True, "message": f"{len(rows)} tools with failures." if rows else "No tool failures logged.",
            "failures": rows}


def _module_file(tool: str) -> Path:
    import gta5_agent

    function = gta5_agent.TOOLS.get(tool)
    if function is None:
        raise ValueError(f"Unknown tool {tool}.")
    path = Path(inspect.getsourcefile(inspect.unwrap(function)) or "").resolve()
    root = app_dir().resolve()
    if root not in path.parents:
        raise ValueError("That tool's code is not inside the agent folder.")
    return path


def _copy_project(dest: Path) -> None:
    root = app_dir()
    for item in root.iterdir():
        if item.name in COPY_SKIP or item.name.startswith(".env"):
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(*COPY_SKIP, "*.pyc"))
        else:
            shutil.copy2(item, target)


def _run_tests(cwd: Path) -> tuple[int, str]:
    import shlex

    cmd = shlex.split(str(settings()["test_command"]), posix=(os.name != "nt"))
    if cmd and cmd[0] in {"python", "python3", "py"}:
        cmd[0] = sys.executable
    timeout = int(settings()["test_timeout_seconds"])
    if test_runner is not None:
        return test_runner(cmd, cwd, timeout)
    env = {**os.environ, "PEDRO_AGENT_NO_FILE_LOG": "1"}
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False, env=env)
    except subprocess.TimeoutExpired:
        return 124, "Tests timed out."
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def propose_upgrade(tool: str = "") -> dict[str, Any]:
    report = failure_report()["failures"]
    if not tool:
        if not report:
            return {"ok": False, "error": "No logged failures to fix."}
        tool = report[0]["tool"]
    errors = next((r["errors"] for r in report if r["tool"] == tool), [])
    try:
        source_path = _module_file(tool)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    rel = source_path.relative_to(app_dir().resolve()).as_posix()
    old = source_path.read_text(encoding="utf-8")
    if len(old) > 120_000:
        return {"ok": False, "error": f"{rel} is too large for a whole-file proposal."}
    prompt = (
        f"The tool `{tool}` in {rel} keeps failing with these errors:\n" + "\n".join(errors or ["(no message)"]) +
        "\n\nReturn the COMPLETE corrected file only, in one ```python block. Keep every public function, "
        "behaviour and safety check; change only what fixes the failures.\n\n"
        f"```python\n{old}\n```"
    )
    new = llm.strip_fence(llm.text(prompt))
    if not new.strip() or new.strip() == old.strip():
        return {"ok": False, "error": "No change was proposed."}
    if not new.endswith("\n"):
        new += "\n"
    up_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    folder = upgrades_dir() / up_id
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pedro-upgrade-") as tmp:
        copy = Path(tmp) / "app"
        copy.mkdir()
        _copy_project(copy)
        (copy / rel).write_text(new, encoding="utf-8")
        code, output = _run_tests(copy)
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
    (folder / "new_file.py").write_text(new, encoding="utf-8")
    (folder / "patch.diff").write_text(diff, encoding="utf-8")
    meta = {"id": up_id, "tool": tool, "file": rel, "tests_passed": code == 0, "status": "proposed",
            "created": time.time(), "test_output": output[-4000:]}
    (folder / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    verdict = "Tests pass in a copy" if code == 0 else "Tests FAILED in a copy, so it cannot be applied"
    return {"ok": True, "message": f"Proposal {up_id} for {rel}: {verdict}. Reply yes to apply it." if code == 0
            else f"Proposal {up_id} for {rel}: {verdict}.", "id": up_id, "tests_passed": code == 0,
            "diff": diff[:6000]}


def _meta(up_id: str) -> tuple[Path, dict[str, Any]]:
    folder = upgrades_dir() / Path(up_id).name
    meta_file = folder / "meta.json"
    if not meta_file.is_file():
        raise ValueError(f"No upgrade proposal {up_id}.")
    return folder, json.loads(meta_file.read_text(encoding="utf-8"))


def apply_upgrade(upgrade_id: str, confirm: str = "") -> dict[str, Any]:
    try:
        folder, meta = _meta(upgrade_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if str(confirm).strip().casefold() not in {"yes", "y"}:
        return {"ok": False, "error": "Applying an upgrade needs your yes.", "needs_confirmation": True}
    if not meta.get("tests_passed"):
        return {"ok": False, "error": "This proposal failed its tests and cannot be applied."}
    if meta.get("status") == "applied":
        return {"ok": False, "error": "Already applied."}
    target = (app_dir() / meta["file"]).resolve()
    if app_dir().resolve() not in target.parents:
        return {"ok": False, "error": "Bad target path."}
    backup = folder / "backup.py"
    shutil.copy2(target, backup)
    shutil.copy2(folder / "new_file.py", target)
    meta.update(status="applied", applied=time.time(), backup=str(backup))
    (folder / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return {"ok": True, "message": f"Applied {upgrade_id} to {meta['file']}. Backup kept; restart the agent to load it.",
            "backup": str(backup)}


def rollback_upgrade(upgrade_id: str) -> dict[str, Any]:
    try:
        folder, meta = _meta(upgrade_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    backup = folder / "backup.py"
    if meta.get("status") != "applied" or not backup.is_file():
        return {"ok": False, "error": "That upgrade is not applied."}
    shutil.copy2(backup, app_dir() / meta["file"])
    meta.update(status="rolled_back")
    (folder / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return {"ok": True, "message": f"Restored {meta['file']} from the backup."}


def list_upgrades() -> dict[str, Any]:
    rows = []
    for meta_file in sorted(upgrades_dir().glob("*/meta.json")) if upgrades_dir().is_dir() else []:
        m = json.loads(meta_file.read_text(encoding="utf-8"))
        rows.append({k: m.get(k) for k in ("id", "tool", "file", "tests_passed", "status")})
    return {"ok": True, "message": f"{len(rows)} proposals.", "upgrades": rows}


def self_upgrade(action: str = "report", tool: str = "", upgrade_id: str = "", confirm: str = "") -> dict[str, Any]:
    action = (action or "report").strip().casefold()
    if action == "report":
        return failure_report()
    if action == "propose":
        return propose_upgrade(tool)
    if action == "apply":
        return apply_upgrade(upgrade_id, confirm)
    if action == "rollback":
        return rollback_upgrade(upgrade_id)
    if action == "list":
        return list_upgrades()
    return {"ok": False, "error": "action must be report, propose, apply, rollback or list."}


DECLARATIONS = [{
    "name": "self_upgrade",
    "description": ("Improve the agent from its own failure log. report = failing tools; propose = Gemini writes a fix, "
                    "tested in a copy of the project; apply = install a tested proposal (ONLY after the user said yes in "
                    "this conversation; pass confirm='yes'); rollback = restore the backup; list = proposals."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["report", "propose", "apply", "rollback", "list"]},
        "tool": {"type": "string"}, "upgrade_id": {"type": "string"},
        "confirm": {"type": "string", "description": "'yes' only when the user explicitly agreed."}}},
}]
TOOLS = {"self_upgrade": self_upgrade}
