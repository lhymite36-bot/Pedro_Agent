"""Headless Blender jobs. The desktop window is not opened.

Tests set blender_runner_override so this module never starts blender.exe.
The modeling script may use bpy. This module adds the export and checks the file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

EXPORT_SUFFIXES = (".obj", ".fbx", ".blend")
SCRIPT_LIMIT = 50_000
TIMEOUT_SECONDS = 600
MAX_JOBS = 2
MIN_MODEL_BYTES = 16

_lock = threading.Lock()
_threads: list[threading.Thread] = []
_assertions: list[BaseException] = []
_active = 0
_inflight: dict[str, str] = {}
last_notice: dict[str, Any] | None = None
# Long enough to catch a crash during launch, short enough that a real
# Blender process is still reported as started.
_LAUNCH_JOIN_SECONDS = 0.5

_FORBIDDEN: tuple[tuple[str, str], ...] = (
    (
        r"\bsubprocess\b|\bos\s*\.\s*(?:system|popen|exec|spawn)|__import__|\beval\s*\(|\bexec\s*\(|\bcompile\s*\(",
        "The script cannot start a program or run generated code.",
    ),
    (
        r"\b(?:ctypes|socket|urllib|requests|webbrowser|winreg|shutil|importlib|pickle|marshal|base64)\b|\bimport\s+os\b|\bfrom\s+os\b",
        "The script cannot use the network, the shell, or file helpers.",
    ),
    (
        r"powershell|cmd\.exe|\bcmd\s*/c\b|bash\s+-c",
        "The script cannot start a shell.",
    ),
    (
        r"\bopen\s*\(|save_as_mainfile|export_scene|obj_export",
        "Do not open or export files in the script. The tool saves the model.",
    ),
    (
        r"[A-Za-z]:\\|\\\\|\.\.",
        "Do not put a file path in the script. Pass output_path to the tool.",
    ),
)


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def reset_jobs() -> None:
    """Wait for test jobs and drop the last notice."""
    global last_notice
    wait_for_jobs()
    last_notice = None
    with _lock:
        _inflight.clear()


def wait_for_jobs(timeout: float = 5) -> None:
    """Join background jobs. An assertion from a test guard is raised here."""
    with _lock:
        threads = list(_threads)
    for thread in threads:
        thread.join(timeout)
    with _lock:
        errors = list(_assertions)
        _assertions.clear()
        _threads.clear()
    if errors:
        raise errors[0]


def _safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", (name or "").strip()).strip("-_")
    return cleaned[:40]


def _check_script(script: str) -> str | None:
    text = script or ""
    if not text.strip():
        return "A bpy script is required."
    if len(text) > SCRIPT_LIMIT:
        return "The modeling script is too long."
    if "\x00" in text:
        return "The modeling script contains a null character."
    agent = _agent()
    key = os.environ.get("GEMINI_API_KEY", "")
    if key and key in text:
        return "The modeling script cannot contain an API key."
    if not re.search(r"\bbpy\b", text):
        return "The script must use Blender's bpy API."
    for pattern, message in _FORBIDDEN:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return message
    try:
        compile(text, "<blender-task>", "exec")
    except SyntaxError as exc:
        return f"The modeling script has a syntax error: {exc.msg}."
    return None


def _default_output(name: str) -> str:
    stem = _safe_stem(name) or "model"
    agent = _agent()
    if agent._external_drive_root() is not None:
        return f"external/Blender/{stem}.obj"
    return str(agent.WORKSPACE / "blender" / f"{stem}.obj")


def find_blender() -> Path | None:
    """Locate blender.exe. An override of False means it is not installed."""
    agent = _agent()
    override = agent.blender_executable_override
    if override is False:
        return None
    if override:
        return Path(override)
    configured = os.environ.get("BLENDER_EXECUTABLE", "").strip().strip('"')
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return candidate
    found = shutil.which("blender")
    if found:
        return Path(found)
    if os.name != "nt":
        return None
    roots: list[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value) / "Blender Foundation")
    matches: list[Path] = []
    for root in roots:
        if root.is_dir():
            matches.extend(root.glob("Blender */blender.exe"))
    matches.sort(reverse=True)
    return matches[0] if matches else None


def _wrapped_script(user_script: str, output: Path) -> str:
    destination = json.dumps(str(output))
    return (
        "import bpy\n"
        + user_script.strip()
        + "\n"
        + f"_out = {destination}\n"
        + "import os as _os\n"
        + '_os.makedirs(_os.path.dirname(_out) or ".", exist_ok=True)\n'
        + "_ext = _os.path.splitext(_out)[1].lower()\n"
        + "if _ext == '.blend':\n"
        + "    bpy.ops.wm.save_as_mainfile(filepath=_out)\n"
        + "elif _ext == '.fbx':\n"
        + "    bpy.ops.export_scene.fbx(filepath=_out, use_selection=False)\n"
        + "elif _ext == '.obj':\n"
        + "    try:\n"
        + "        bpy.ops.wm.obj_export(filepath=_out, export_selected_objects=False)\n"
        + "    except Exception:\n"
        + "        bpy.ops.export_scene.obj(filepath=_out, use_selection=False)\n"
        + "else:\n"
        + "    raise RuntimeError('Unsupported export type: ' + _ext)\n"
    )


def _model_problem(path: Path) -> str | None:
    if not path.is_file():
        return "Blender finished without creating the file."
    size = path.stat().st_size
    if size < MIN_MODEL_BYTES:
        return "Blender created a file that is too small to be a model."
    ext = path.suffix.casefold()
    head = path.read_bytes()[:64]
    if ext == ".blend" and not head.startswith(b"BLENDER"):
        return "The .blend file is not a Blender file."
    if ext == ".fbx" and not (
        head.startswith(b"Kaydara FBX") or b"FBX" in head.upper()
    ):
        return "The .fbx file is not an FBX file."
    if ext == ".obj":
        preview = path.read_text(encoding="utf-8", errors="ignore")[:4000]
        if re.search(r"(?m)^v\s+", preview) is None:
            return "The .obj file does not contain any vertices."
    return None


def _error_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if "Error" in line or line.startswith("Error:"):
            return line[:400]
    if lines:
        return lines[-1][:400]
    return ""


def explain_failure(stdout: str, stderr: str, returncode: int, problem: str | None) -> str:
    """Turn Blender's console text into a short reason."""
    combined = _agent()._scrub(f"{stderr}\n{stdout}")
    if re.search(r"ModuleNotFoundError|ImportError", combined):
        missing = re.search(r"No module named ['\"]([^'\"]+)['\"]", combined)
        if missing:
            return f"Blender is missing the {missing.group(1)} dependency."
        return "Blender could not import a module the script needs."
    if "SyntaxError" in combined:
        return f"The modeling script has a syntax error. {_error_line(combined)}".strip()
    if re.search(r"AttributeError|TypeError|RuntimeError|ValueError|NameError", combined):
        detail = _error_line(combined)
        if detail:
            return f"Blender rejected the modeling step. {detail}"
        return "Blender rejected the modeling step."
    if "timed out" in combined.casefold():
        return "Blender took too long and was stopped."
    if problem:
        return problem
    detail = _error_line(combined)
    if detail:
        return detail
    return f"Blender exited with code {returncode}."


def _launch(
    command: list[str],
    script_path: Path | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    """Run blender -b -P. script_path and output match the test runner."""
    del output
    if script_path is not None and not Path(script_path).is_file():
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "The Blender script was not written.",
        }
    flags: dict[str, Any] = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        shell=False,
        **flags,
    )
    try:
        stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        stderr = f"{stderr or ''}\nBlender timed out."
        return {
            "returncode": process.returncode if process.returncode is not None else 1,
            "stdout": stdout or "",
            "stderr": stderr,
        }
    return {
        "returncode": process.returncode if process.returncode is not None else 1,
        "stdout": stdout or "",
        "stderr": stderr or "",
    }


def _notify(message: str, *, ok: bool, path: str, job_id: str) -> None:
    global last_notice
    agent = _agent()
    safe = agent._scrub(message)
    notice = {"ok": ok, "message": safe, "path": path, "job_id": job_id}
    with _lock:
        last_notice = notice
    print(f"[blender] {safe}", flush=True)
    try:
        import remote_bridge

        remote_bridge.notify(safe)
    except Exception:
        pass
    if agent.blender_notify_override is not None:
        agent.blender_notify_override(safe)
        return
    with agent._speech_lock:
        busy = agent._speech_stop is not None
    if busy:
        return
    try:
        agent.speak_response(safe, barge_in=False)
    except Exception:
        return


def _finish(
    job_id: str,
    command: list[str],
    script_path: Path,
    output: Path,
    user_script: str = "",
    private: bool = False,
) -> None:
    global _active
    agent = _agent()
    try:
        runner = agent.blender_runner_override or _launch
        for attempt in range(1, 4):
            completed = runner(command, script_path, output)
            if not isinstance(completed, dict):
                raise RuntimeError("Blender runner returned nothing.")
            code = int(completed.get("returncode", 1))
            stdout = str(completed.get("stdout") or "")
            stderr = str(completed.get("stderr") or "")
            problem = _model_problem(output)
            if code == 0 and problem is None:
                size = output.stat().st_size
                message = f"The 3D model is ready. Saved {size} bytes to {output}."
                if attempt > 1:
                    message = f"Fixed and finished on attempt {attempt}. {message}"
                _notify(message, ok=True, path=str(output), job_id=job_id)
                return
            if attempt >= 3 or not agent.self_heal_enabled:
                reason = explain_failure(stdout, stderr, code, problem)
                _notify(
                    f"Blender could not build the model. {reason}",
                    ok=False,
                    path=str(output),
                    job_id=job_id,
                )
                return
            import self_heal

            rewritten = self_heal.rewrite_source(
                user_script,
                f"{stderr}\n{stdout}",
                private=private,
            )
            rewritten = self_heal.strip_code_fence(rewritten or "")
            rejected = _check_script(rewritten)
            if rejected or not rewritten.strip():
                reason = rejected or explain_failure(stdout, stderr, code, problem)
                _notify(
                    f"Blender could not build the model. {reason}",
                    ok=False,
                    path=str(output),
                    job_id=job_id,
                )
                return
            user_script = rewritten
            script_path.write_text(_wrapped_script(user_script, output), encoding="utf-8")
            print(f"[heal] Retrying the Blender script, attempt {attempt + 1}.", flush=True)
    except AssertionError as exc:
        with _lock:
            _assertions.append(exc)
    except Exception as exc:
        _notify(
            f"Blender could not build the model. {exc}",
            ok=False,
            path=str(output),
            job_id=job_id,
        )
    finally:
        with _lock:
            _active -= 1
            _inflight.pop(job_id, None)


def run_blender_task(
    script: str,
    output_path: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Start a headless Blender job and return before it finishes.

    The script builds the mesh with bpy. Export is appended here. The saved
    file must exist and be a non-empty model before the completion notice.
    """
    global _active
    agent = _agent()
    try:
        rejected = _check_script(script)
        if rejected:
            return agent._err(rejected)
        destination = (output_path or "").strip() or _default_output(name)
        output = agent._resolve_user_path(destination, EXPORT_SUFFIXES)
        output.parent.mkdir(parents=True, exist_ok=True)
        if agent.blender_executable_override is False:
            return agent._err(
                "Blender is not installed. Install Blender, or set "
                "BLENDER_EXECUTABLE to blender.exe."
            )
        if agent.blender_runner_override is None:
            executable = find_blender()
            if executable is None:
                return agent._err(
                    "Blender is not installed. Install Blender, or set "
                    "BLENDER_EXECUTABLE to blender.exe."
                )
        else:
            chosen = agent.blender_executable_override
            executable = Path(chosen) if chosen else Path("blender")
        with _lock:
            if _active >= MAX_JOBS:
                return agent._err("A Blender model is already being built.")
            _active += 1
        job_id = uuid.uuid4().hex[:8]
        try:
            script_dir = agent.WORKSPACE / "blender_jobs"
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path = script_dir / f"{job_id}.py"
            script_path.write_text(_wrapped_script(script, output), encoding="utf-8")
            command = [str(executable), "-b", "-P", str(script_path)]
            import local_llm

            private = bool(agent._turn_is_local) or local_llm.use_local_first(agent._turn_request)
            worker = threading.Thread(
                target=_finish,
                args=(job_id, command, script_path, output, script, private),
                name="blender-job",
                daemon=True,
            )
            with _lock:
                _threads.append(worker)
                _inflight[job_id] = str(output)
            worker.start()
        except Exception:
            with _lock:
                _active -= 1
                _inflight.pop(job_id, None)
            raise
        worker.join(_LAUNCH_JOIN_SECONDS)
        with _lock:
            notice = dict(last_notice) if last_notice else None
            alive = worker.is_alive()
        if notice and notice.get("job_id") == job_id and not alive:
            if notice.get("ok"):
                return agent._ok(
                    str(notice.get("message") or "The 3D model is ready."),
                    status="ready",
                    path=str(output),
                    job_id=job_id,
                )
            return agent._err(
                str(notice.get("message") or "Blender could not build the model."),
                status="failed",
                path=str(output),
                job_id=job_id,
            )
        return agent._ok(
            "Blender is building the model in the background. "
            "The file is not ready yet. I will say when it is saved.",
            status="started",
            path=str(output),
            job_id=job_id,
            command=command,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"run_blender_task failed: {exc}")


def blender_job_status(open_file: bool = False) -> dict[str, Any]:
    """Report the latest Blender job. Does not start another one."""
    agent = _agent()
    try:
        with _lock:
            inflight = list(_inflight.values())
            notice = dict(last_notice) if last_notice else None
        if inflight:
            return agent._ok(
                "Blender is still building the model. The file is not ready.",
                status="started",
                path=inflight[-1],
            )
        if not notice:
            return agent._err("No Blender model has been started.")
        path = Path(str(notice.get("path") or ""))
        ready = bool(notice.get("ok")) and _model_problem(path) is None
        if not ready:
            return agent._err(
                str(notice.get("message") or "The model is not ready."),
                status="failed",
                path=str(path),
            )
        if agent._as_bool(open_file):
            opener = agent.blender_open_override
            if opener is not None:
                opener(str(path))
            elif os.name == "nt":
                os.startfile(path)
            else:
                return agent._err("Opening the model is only set up on Windows.")
            return agent._ok(
                f"Opened {path.name}.",
                status="ready",
                path=str(path),
            )
        return agent._ok(
            str(notice.get("message") or "The 3D model is ready."),
            status="ready",
            path=str(path),
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"blender_job_status failed: {exc}")
