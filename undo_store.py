"""1.4.12: undo the last file the agent wrote.

Before a write, remember() copies the old bytes, or notes that the file was new.
undo_last_change puts that file back. Snapshots stay on this PC under workspace/.
Secret files are never copied. A file that changed after the write is left alone.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent / "workspace"
AGENT_DIR = Path(__file__).resolve().parent
MAX_KEEP = 20
MAX_BYTES = 8_000_000
_SECRET_SUFFIX = {".pem", ".key", ".pfx", ".p12"}
recycle_override: Any = None
_lock = threading.Lock()


def _stack_path() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT / "undo_stack.json"


def _blob_dir() -> Path:
    folder = ROOT / "undo_blobs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _load() -> list[dict[str, Any]]:
    try:
        data = json.loads(_stack_path().read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save(items: list[dict[str, Any]]) -> None:
    _stack_path().write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")


def _secret(path: Path) -> bool:
    name = path.name.casefold()
    if name == ".env" or name.startswith(".env."):
        return True
    return path.suffix.casefold() in _SECRET_SUFFIX


def _skip(path: Path) -> bool:
    """True when this path must not be snapshotted or restored."""
    import file_tools
    import rules

    if _secret(path):
        return True
    try:
        if not rules.path_allowed(path):
            return True
    except Exception:
        return True
    if rules.file_write_reason(path):
        return True
    if rules.protect("never_delete_agent_folder") and file_tools._is_agent_code(path, AGENT_DIR):
        return True
    blob = _blob_dir().resolve()
    return path == blob or blob in path.parents


def remember(path: Path, *, directory: bool = False) -> None:
    """Record one file or new folder before the agent writes it. Failures stay quiet."""
    try:
        target = Path(path).resolve()
        if _skip(target):
            return
        with _lock:
            items = _load()
            entry: dict[str, Any] = {
                "id": f"{int(time.time() * 1000):x}-{len(items)}",
                "path": str(target),
                "t": time.strftime("%Y-%m-%d %H:%M"),
                "sealed_size": None,
                "blob": "",
            }
            if directory:
                if target.exists():
                    return
                entry["kind"] = "created_dir"
            elif target.is_file():
                size = target.stat().st_size
                if size > MAX_BYTES:
                    entry["kind"] = "too_big"
                    entry["sealed_size"] = size
                else:
                    blob = _blob_dir() / entry["id"]
                    blob.write_bytes(target.read_bytes())
                    entry["kind"] = "replaced"
                    entry["blob"] = blob.name
            elif target.exists():
                return
            else:
                entry["kind"] = "created"
            items.append(entry)
            while len(items) > MAX_KEEP:
                _drop_blob(items.pop(0))
            _save(items)
    except Exception:
        return


def seal(path: Path) -> None:
    """Mark the newest open snapshot for this path with the size just written."""
    try:
        target = Path(path).resolve()
        size = target.stat().st_size if target.is_file() else 0
        with _lock:
            items = _load()
            for entry in reversed(items):
                if entry.get("path") == str(target) and entry.get("sealed_size") is None:
                    entry["sealed_size"] = size
                    _save(items)
                    return
    except Exception:
        return


def _drop_blob(entry: dict[str, Any]) -> None:
    name = str(entry.get("blob") or "")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return
    try:
        (_blob_dir() / name).unlink(missing_ok=True)
    except Exception:
        pass


def _remove_file(path: Path) -> str:
    if recycle_override is not None:
        recycle_override(str(path))
        return "Removed"
    try:
        from send2trash import send2trash  # type: ignore

        send2trash(str(path))
        return "Moved to the Recycle Bin"
    except Exception:
        path.unlink()
        return "Removed"


def _apply_at(items: list[dict[str, Any]], index: int) -> dict[str, Any]:
    """Undo one snapshot. Pops it unless the file must be left alone."""
    import file_tools

    entry = items[index]
    target = Path(str(entry.get("path") or ""))
    kind = str(entry.get("kind") or "")
    if _skip(target):
        return {"ok": False, "held": True, "error": f"Refusing to undo {target.name}."}
    blocked = file_tools._protected_delete(target)
    if blocked and kind in {"created", "created_dir"}:
        return {"ok": False, "held": True, "error": blocked}

    if kind == "too_big":
        items.pop(index)
        return {"ok": False, "error": f"{target} was too large to keep a copy, so it was not restored."}

    sealed = entry.get("sealed_size")
    if kind == "replaced":
        blob_name = str(entry.get("blob") or "")
        blob = _blob_dir() / blob_name if blob_name else None
        if blob is None or not blob.is_file():
            return {"ok": False, "held": True, "error": f"The saved copy of {target.name} is missing."}
        if not target.is_file():
            return {"ok": False, "held": True, "error": f"{target} is no longer a file, so it was left as it is."}
        if sealed is not None and target.stat().st_size != sealed:
            return {"ok": False, "held": True, "error": f"{target.name} changed after that write, so it was left as it is."}
        target.write_bytes(blob.read_bytes())
        items.pop(index)
        _drop_blob(entry)
        return {"ok": True, "message": f"Restored {target}.", "path": str(target), "left": len(items)}

    if kind == "created":
        if not target.exists():
            items.pop(index)
            return {"ok": True, "message": f"{target.name} was already gone.", "path": str(target), "left": len(items)}
        if not target.is_file():
            return {"ok": False, "held": True, "error": f"{target} is not a file, so it was left as it is."}
        if sealed is not None and target.stat().st_size != sealed:
            return {"ok": False, "held": True, "error": f"{target.name} changed after it was created, so it was left as it is."}
        how = _remove_file(target)
        items.pop(index)
        return {"ok": True, "message": f"{how}: {target}.", "path": str(target), "left": len(items)}

    if kind == "created_dir":
        if not target.exists():
            items.pop(index)
            return {"ok": True, "message": f"{target.name} was already gone.", "path": str(target), "left": len(items)}
        if not target.is_dir():
            return {"ok": False, "held": True, "error": f"{target} is not a folder, so it was left as it is."}
        if any(target.iterdir()):
            return {"ok": False, "held": True, "error": f"{target.name} is not empty, so it was left as it is."}
        target.rmdir()
        items.pop(index)
        return {"ok": True, "message": f"Removed empty folder {target}.", "path": str(target), "left": len(items)}

    items.pop(index)
    return {"ok": False, "error": "That change has no saved copy."}


def undo_last_change() -> dict[str, Any]:
    """Restore the previous copy, or remove a file or empty folder the agent just created."""
    with _lock:
        items = _load()
        if not items:
            return {"ok": False, "error": "Nothing to undo."}
        result = _apply_at(items, len(items) - 1)
        _save(items)
        result.pop("held", None)
        return result


def _path_match(entry_path: str, wanted: list[str]) -> bool:
    try:
        found = str(Path(entry_path).resolve()).casefold()
    except Exception:
        return False
    for folder in wanted:
        if found == folder:
            return True
        prefix = folder.rstrip("\\/")
        if found.startswith(prefix + "\\") or found.startswith(prefix + "/"):
            return True
    return False


def undo_paths(paths: list[str]) -> dict[str, Any]:
    """Undo the snapshots for these files, newest first. Other files stay."""
    wanted: list[str] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            wanted.append(str(Path(text).resolve()).casefold())
        except Exception:
            continue
    if not wanted:
        return {"ok": False, "error": "Nothing to undo."}
    with _lock:
        items = _load()
        hits = [i for i, entry in enumerate(items) if _path_match(str(entry.get("path") or ""), wanted)]
        if not hits:
            return {"ok": False, "error": "Nothing from that reply is left to undo."}
        notes: list[str] = []
        ok_any = False
        for index in reversed(hits):
            result = _apply_at(items, index)
            notes.append(str(result.get("message") or result.get("error") or ""))
            if result.get("ok"):
                ok_any = True
        _save(items)
        text = " ".join(note for note in notes if note)
        if ok_any:
            return {"ok": True, "message": text, "left": len(items)}
        return {"ok": False, "error": text or "Nothing was undone."}


DECLARATIONS = [
    {"name": "undo_last_change",
     "description": "Undo the last file this agent wrote. Restores the previous copy, or removes a file it just created. Refuses if the file changed afterwards, if it is a secret, or if it is too large to have been saved.",
     "parameters": {"type": "object", "properties": {}}},
]
TOOLS = {"undo_last_change": undo_last_change}
