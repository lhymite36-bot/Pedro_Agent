"""Rerun a Python file the agent wrote, and rewrite it after a traceback.

The process is [sys.executable, script] with shell=False. Tests set
heal_runner_override and heal_rewriter_override. Gemini is called only when
no rewriter override is set, self-heal is allowed, and the turn is not private.
Downloads, deletes, git pushes, and process kills are not retried here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import rules

MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 30
_JOIN_SECONDS = 0.5
_MAX_CHARS = 100_000

_lock = threading.Lock()
_threads: list[threading.Thread] = []


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def _game_folder(path: Path) -> bool:
    cursor = path
    while True:
        if (cursor / "GTA5.exe").is_file():
            return True
        if cursor == cursor.parent:
            return False
        cursor = cursor.parent


def _check_source(path: Path, source: str) -> str | None:
    agent = _agent()
    if not source.strip():
        return "The script is empty."
    if len(source) > _MAX_CHARS:
        return "The script is too long."
    if "\x00" in source:
        return "The script contains a null character."
    key = os.environ.get("GEMINI_API_KEY", "")
    if key and key in source:
        return "The script cannot contain an API key."
    if agent.PIRACY_TERMS.search(source):
        return "The script asks for a crack or a repack. It was not run."
    if _game_folder(path):
        return "Do not run or repair a script inside the game folder."
    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg}"
    return None


def _resolve(script_path: str) -> Path:
    agent = _agent()
    path = agent._resolve_user_path(script_path, ".py")
    if rules.limit("keep_builds_out_of_game_folder") and _game_folder(path):
        raise ValueError("Do not run or repair a script inside the game folder.")
    if not path.is_file():
        raise ValueError("That Python file does not exist.")
    return path


def strip_code_fence(text: str) -> str:
    """Drop a markdown fence so a model reply can be saved as Python."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def rewrite_source(source: str, error: str, *, private: bool = False) -> str:
    """Return replacement source. Tests pass heal_rewriter_override."""
    agent = _agent()
    rewriter = agent.heal_rewriter_override
    if rewriter is not None:
        rewritten = rewriter(source, error)
        if not isinstance(rewritten, str):
            raise RuntimeError("The rewriter did not return a script.")
        return rewritten
    import local_llm

    if private or agent._turn_is_local or local_llm.use_local_first(agent._turn_request):
        return local_llm.rewrite_with_ollama(source, error)
    return gemini_rewrite(source, error)


def gemini_rewrite(source: str, error: str) -> str:
    """Ask Gemini for a replacement script. Tests must not call this."""
    agent = _agent()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set, so the script was not rewritten.")
    from google import genai

    prompt = (
        "The script failed. Return only the replacement Python source. "
        "Do not add a shell command, a download, or an explanation.\n\n"
        f"ERROR:\n{agent._scrub(error)[:4000]}\n\n"
        f"SCRIPT:\n{agent._scrub(source)[:20000]}"
    )
    if agent.genai_client_override is not None:
        client = agent.genai_client_override(key)
    else:
        client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", agent.DEFAULT_MODEL),
        contents=prompt,
    )
    text = strip_code_fence(getattr(response, "text", None) or agent._text_from(response))
    if not text.strip():
        raise RuntimeError("The rewriter returned an empty script.")
    return text


def _launch(command: list[str], script_path: Path) -> dict[str, Any]:
    """Run the script. command is a list and shell stays off."""
    del script_path
    try:
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            cwd=str(Path(command[-1]).parent),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 1,
            "stdout": exc.stdout or "",
            "stderr": f"{exc.stderr or ''}\nThe script timed out.",
        }
    except OSError as exc:
        return {"returncode": 1, "stdout": "", "stderr": str(exc)}
    return {
        "returncode": completed.returncode if completed.returncode is not None else 1,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def _failure_text(completed: dict[str, Any]) -> str:
    stderr = str(completed.get("stderr") or "").strip()
    stdout = str(completed.get("stdout") or "").strip()
    if stderr:
        return stderr[-4000:]
    if stdout:
        return stdout[-4000:]
    return f"The script exited with code {completed.get('returncode', 1)}."


def _run_loop(path: Path, *, private: bool) -> dict[str, Any]:
    agent = _agent()
    runner = agent.heal_runner_override or _launch
    last_error = "The script failed."
    for attempt in range(1, MAX_ATTEMPTS + 1):
        source = path.read_text(encoding="utf-8")
        problem = _check_source(path, source)
        if problem and not problem.startswith("SyntaxError"):
            return agent._err(problem, path=str(path), attempts=attempt)
        if problem:
            completed = {"returncode": 1, "stdout": "", "stderr": problem}
        else:
            command = [sys.executable, str(path)]
            completed = runner(command, path)
            if not isinstance(completed, dict):
                raise RuntimeError("The script runner returned nothing.")
        code = int(completed.get("returncode", 1))
        if code == 0 and problem is None:
            message = f"The script finished. {path}"
            if attempt > 1:
                message = f"Fixed and finished on attempt {attempt}. {path}"
                print(f"[heal] {message}", flush=True)
                try:
                    import remote_bridge

                    remote_bridge.notify(agent._scrub(message))
                except Exception:
                    pass
            return agent._ok(message, status="ready", path=str(path), attempts=attempt)
        last_error = agent._scrub(_failure_text(completed))
        if attempt >= MAX_ATTEMPTS:
            break
        rewritten = rewrite_source(source, last_error, private=private)
        rewritten = strip_code_fence(rewritten)
        rejected = _check_source(path, rewritten)
        if rejected and not rejected.startswith("SyntaxError"):
            return agent._err(rejected, path=str(path), attempts=attempt)
        if rewritten == source:
            continue
        path.write_text(rewritten if rewritten.endswith("\n") else rewritten + "\n", encoding="utf-8")
        print(f"[heal] Retrying {path.name}, attempt {attempt + 1}.", flush=True)
    return agent._err(
        f"Stopped after {MAX_ATTEMPTS} attempts. {last_error}",
        status="failed",
        path=str(path),
        attempts=MAX_ATTEMPTS,
    )


def self_heal_execution(script_path: str) -> dict[str, Any]:
    """Run one allowed .py file and rewrite it after a traceback, at most 3 times."""
    agent = _agent()
    try:
        path = _resolve(script_path)
        private = bool(agent._turn_is_local)
        if not private:
            import local_llm

            private = local_llm.use_local_first(agent._turn_request)
        if agent.heal_runner_override is not None:
            return _run_loop(path, private=private)
        holder: dict[str, Any] = {}

        def _thread() -> None:
            try:
                holder["result"] = _run_loop(path, private=private)
            except AssertionError as exc:
                holder["assertion"] = exc
            except Exception as exc:
                holder["result"] = agent._err(f"self_heal_execution failed: {exc}", path=str(path))

        worker = threading.Thread(target=_thread, name="heal-job", daemon=True)
        with _lock:
            _threads.append(worker)
        worker.start()
        worker.join(_JOIN_SECONDS)
        if "assertion" in holder:
            raise holder["assertion"]
        if "result" in holder and not worker.is_alive():
            return holder["result"]
        return agent._ok(
            "The script is running in the background. It is not finished yet.",
            status="started",
            path=str(path),
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"self_heal_execution failed: {exc}")
