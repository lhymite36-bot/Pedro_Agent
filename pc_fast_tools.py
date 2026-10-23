"""1.4.16: built-in read-only PC tools, so simple look-ups need no terminal command (and no approval card).

list_files: one folder (or a short recursive walk), sorted, filtered, counted - one call instead of several `dir`s.
pc_status: free disk space, memory and the programs using the most memory - no PowerShell start-up.
Nothing here changes, moves or deletes anything.
"""

from __future__ import annotations

import fnmatch
import os
import time
from pathlib import Path
from typing import Any

_KNOWN = {"downloads": "Downloads", "desktop": "Desktop", "documents": "Documents", "pictures": "Pictures",
          "videos": "Videos", "music": "Music", "home": ""}


# 1.4.19: Windows known-folder ids, so redirected (OneDrive or moved) Documents/Pictures/Videos resolve correctly
_FOLDERIDS = {"Downloads": "{374DE290-123F-4565-9164-39C4925E467B}", "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
              "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
              "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}"}


def known_folder(sub: str) -> Path:
    """The real location of Documents, Pictures, Videos... (follows OneDrive and folder redirection)."""
    home = Path.home()
    if not sub:
        return home
    if os.name == "nt" and sub in _FOLDERIDS:
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]
            u = uuid.UUID(_FOLDERIDS[sub])
            g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                found = Path(out.value or "")
                ctypes.windll.ole32.CoTaskMemFree(out)
                if found.is_dir():
                    return found
        except Exception:
            pass
    for cand in (home / sub, home / "OneDrive" / sub):
        if cand.is_dir():
            return cand
    return home / sub


def _folder(path: str) -> Path:
    raw = os.path.expandvars(os.path.expanduser(str(path or "").strip().strip('"')))
    if not raw:
        return Path.home()
    parts = [x for x in raw.replace("/", "\\").split("\\") if x]
    head = parts[0].casefold().strip() if parts else ""
    head = head[3:] if head.startswith("my ") else head
    if head in _KNOWN and not Path(raw).is_absolute():
        # "Documents", "Documents\\PedroAgent", "my pictures/Ped Bot" -> under the real known folder
        return known_folder(_KNOWN[head]).joinpath(*parts[1:])
    return Path(raw)


def list_files(path: str = "", sort: str = "newest", limit: int = 20, pattern: str = "*",
               recursive: bool = False, kind: str = "all") -> dict[str, Any]:
    """List a folder: names, sizes, modified times, sorted; plus the total count that matches."""
    folder = _folder(path)
    if not folder.is_dir():
        return {"ok": False, "error": f"Folder not found: {folder}"}
    limit = max(1, min(int(limit or 20), 200))
    pats = [p.strip() for p in str(pattern or "*").replace(";", ",").split(",") if p.strip()] or ["*"]
    want = str(kind or "all").casefold()
    items: list[tuple[str, Path, os.stat_result, bool]] = []
    started = time.monotonic()
    walker = os.walk(folder) if recursive else [(str(folder), None, None)]
    for root, _dirs, _files in walker:
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                if recursive and is_dir:
                    continue   # os.walk visits it; count files only
                if (want == "files" and is_dir) or (want == "folders" and not is_dir):
                    continue
                if not any(fnmatch.fnmatch(entry.name.casefold(), p.casefold()) for p in pats):
                    continue
                items.append((entry.name, Path(entry.path), entry.stat(follow_symlinks=False), is_dir))
            except OSError:
                continue
        if len(items) > 50000 or time.monotonic() - started > 20:
            break
    order = str(sort or "newest").casefold()
    keyfn = {"oldest": lambda i: i[2].st_mtime, "largest": lambda i: -i[2].st_size, "smallest": lambda i: i[2].st_size,
             "name": lambda i: i[0].casefold()}.get(order, lambda i: -i[2].st_mtime)
    items.sort(key=keyfn)
    shown = [{"name": n if not recursive else str(p.relative_to(folder)), "folder": d, "size_kb": round(s.st_size / 1024, 1),
              "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(s.st_mtime))} for n, p, s, d in items[:limit]]
    files = sum(1 for i in items if not i[3])
    names = ", ".join(x["name"] for x in shown[:10])
    return {"ok": True, "folder": str(folder), "count": len(items), "files": files, "folders": len(items) - files,
            "sorted_by": order, "items": shown,
            "message": f"{len(items)} match in {folder} ({files} files). {order.title()} first: {names}"}


def pc_status(top: int = 5) -> dict[str, Any]:
    """Free disk space per drive, memory in use, CPU load and the programs using the most memory."""
    out: dict[str, Any] = {"ok": True}
    try:
        import psutil
    except ImportError:
        psutil = None
    drives = []
    letters = [f"{c}:\\" for c in "CDEFGHIJ"] if os.name == "nt" else ["/"]
    import shutil
    for d in letters:
        try:
            u = shutil.disk_usage(d)
        except OSError:
            continue
        drives.append({"drive": d, "free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1),
                       "used_pct": round(100 * u.used / u.total, 1) if u.total else 0})
    out["drives"] = drives
    if psutil is not None:
        vm = psutil.virtual_memory()
        out["memory"] = {"used_gb": round(vm.used / 2**30, 1), "total_gb": round(vm.total / 2**30, 1), "used_pct": vm.percent}
        out["cpu_pct"] = psutil.cpu_percent(interval=0.3)
        totals: dict[str, int] = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                totals[p.info["name"] or "?"] = totals.get(p.info["name"] or "?", 0) + p.info["memory_info"].rss
            except Exception:
                continue
        top = max(1, min(int(top or 5), 20))
        out["top_memory"] = [{"program": n, "memory_mb": round(v / 2**20)} for n, v in sorted(totals.items(), key=lambda x: -x[1])[:top]]
    parts = [f"{d['drive']} {d['free_gb']} GB free of {d['total_gb']} GB" for d in drives]
    if "memory" in out:
        parts.append(f"memory {out['memory']['used_pct']}% used")
        parts.append("top memory: " + ", ".join(f"{t['program']} {t['memory_mb']} MB" for t in out["top_memory"]))
    out["message"] = "; ".join(parts)
    return out


import re

_LISTING = re.compile(r"^\s*(?:dir|ls|gci|get-childitem)(?:\s+(?:-path\s+|-literalpath\s+)?(?P<q>[\"']?)(?P<path>[^\"'|;]+?)(?P=q))?"
                      r"(?P<flags>(?:\s+-(?:file|directory|recurse|force|name))*)\s*"
                      r"(?P<pipe>(?:\|\s*(?:sort-object|sort|select-object|select)[^|;]*)*)\s*$", re.I)


def listing_from_terminal(command: str) -> dict[str, Any] | None:
    """1.4.16: a plain `dir <folder>` (optionally sorted / first N) becomes list_files arguments. None otherwise."""
    text = str(command or "")
    if re.search(r"[<>&`$]", text):   # redirects, sub-expressions, variables: not a plain listing
        return None
    m = _LISTING.match(text)
    if not m:
        return None
    pipe = (m.group("pipe") or "").casefold()
    flags = (m.group("flags") or "").casefold()
    args: dict[str, Any] = {"path": (m.group("path") or "").strip() or str(Path.home()), "limit": 50,
                            "recursive": "-recurse" in flags,
                            "kind": "files" if "-file" in flags else ("folders" if "-directory" in flags else "all")}
    if "lastwritetime" in pipe or "creationtime" in pipe:
        args["sort"] = "newest" if "desc" in pipe else "oldest"
    elif "length" in pipe:
        args["sort"] = "largest" if "desc" in pipe else "smallest"
    else:
        args["sort"] = "name" if "sort" in pipe or not pipe else "newest"
    first = re.search(r"-first\s+(\d+)", pipe)
    if first:
        args["limit"] = int(first.group(1))
    return args


DECLARATIONS = [
    {"name": "list_files",
     "description": ("Read-only folder listing, no approval needed. Use this instead of dir/Get-ChildItem for listing, "
                     "counting, finding newest/largest files or files of a type (pattern '*.pdf'). One call does it: "
                     "it sorts, filters and counts. path may be 'Downloads', 'Desktop', 'Documents' or a full path."),
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Folder: Downloads, Desktop, Documents, Pictures, or a full path."},
         "sort": {"type": "string", "enum": ["newest", "oldest", "largest", "smallest", "name"]},
         "limit": {"type": "integer", "description": "How many to show (default 20). The count covers all matches."},
         "pattern": {"type": "string", "description": "Name filter such as *.pdf or *.jpg,*.png (default *)."},
         "recursive": {"type": "boolean", "description": "Include subfolders (files only)."},
         "kind": {"type": "string", "enum": ["all", "files", "folders"]}}}},
    {"name": "pc_status",
     "description": ("Read-only: free disk space per drive, memory and CPU in use, and the programs using the most "
                     "memory. No approval needed; use it instead of terminal commands for these questions."),
     "parameters": {"type": "object", "properties": {"top": {"type": "integer", "description": "How many programs (default 5)."}}}},
]
TOOLS = {"list_files": list_files, "pc_status": pc_status}
READ_ONLY = frozenset(TOOLS)
