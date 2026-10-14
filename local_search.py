"""Local file index for this PC.

File names and text excerpts are stored in SQLite. Questions such as
"where did I save that zombie mod backup" match those words, with a boost
for the time period the question names. A time or file-type question can
also walk the Desktop, Documents, Downloads, the home folder, and the external drive
when that drive is connected. Nothing in the index is executed.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

INDEX_CAP = 4000
SCAN_CAP = 20000
TEXT_STORE_CHARS = 4000
SKIP_DIRS = {
    "$recycle.bin",
    "system volume information",
    "windows",
    "node_modules",
    ".git",
    ".venv",
    "__pycache__",
}
TEXT_EXTS = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".csv",
    ".log",
    ".ini",
    ".cfg",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".lua",
    ".cs",
    ".vb",
    ".yml",
    ".yaml",
    ".rst",
    ".toml",
    ".sql",
    ".docx",
}
SECRET_NAMES = {".env", "id_rsa", "id_dsa", "known_hosts"}
SECRET_EXTS = {".pem", ".key", ".env"}
PROFILE_SKIP = {"appdata", "application data"}
SEARCH_STOP = {
    "where",
    "did",
    "save",
    "saved",
    "that",
    "from",
    "last",
    "month",
    "week",
    "about",
    "the",
    "and",
    "my",
    "you",
    "your",
    "file",
    "files",
    "find",
    "please",
    "show",
    "me",
    "for",
    "with",
    "this",
    "those",
    "what",
    "when",
    "have",
}


def _agent() -> Any:
    import agent_core

    return agent_core


def _place_rules() -> list[tuple[str, re.Pattern[str]]]:
    """Folder words, plus the configured external-drive label."""
    import agent_config

    rules: list[tuple[str, re.Pattern[str]]] = [
        ("desktop", re.compile(r"\bdesktop\b", re.IGNORECASE)),
    ]
    label = agent_config.volume_label()
    if label:
        compact = re.sub(r"[\s_-]+", "", label)
        pattern = rf"\b{re.escape(label)}\b"
        if compact.casefold() != label.casefold():
            pattern += rf"|\b{re.escape(compact)}\b"
        rules.insert(0, (label.casefold(), re.compile(pattern, re.IGNORECASE)))
    return rules


_PLACE_RULES_REST: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "documents",
        re.compile(
            r"\bdocuments folder\b|\b(?:in|on) (?:my |the )?documents\b",
            re.IGNORECASE,
        ),
    ),
    (
        "downloads",
        re.compile(
            r"\bdownloads folder\b|\b(?:in|on) (?:my |the )?downloads?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "project",
        re.compile(r"\bproject folder\b|\bin my project\b|\bin the project\b", re.IGNORECASE),
    ),
    ("home", re.compile(r"\bhome folder\b|\bin my home\b|\buser folder\b", re.IGNORECASE)),
)


def _all_place_rules() -> list[tuple[str, re.Pattern[str]]]:
    return _place_rules() + list(_PLACE_RULES_REST)


def _place_map(agent: Any) -> dict[str, Path]:
    home = Path.home()
    places = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "home": home,
        "project": Path(agent.APP_DIR),
    }
    import agent_config

    external = agent._external_drive_root()
    label = agent_config.volume_label()
    if external is not None and label:
        places[label.casefold()] = external
    return places


def _explicit_dir(agent: Any, query: str) -> Path | str | None:
    """A folder the user named by path. A string result is an error."""
    import agent_config

    label = agent_config.volume_label()
    drive_match = None
    if label:
        drive_match = re.search(
            rf"(?i)\b{re.escape(label)}\b[:\\/]+(\S+)",
            query or "",
        )
    if drive_match:
        external = agent._external_drive_root()
        if external is None:
            return agent_config.drive_missing_message()
        relative = drive_match.group(1).strip().strip('"').strip("'")
        if ".." in Path(relative).parts:
            return "The path cannot contain '..'."
        target = (external / relative).resolve()
    else:
        win = re.search(r"[A-Za-z]:\\[^\r\n\"]+", query or "")
        if win is None:
            return None
        target = Path(win.group(0).strip().rstrip(".,)")).resolve()
        if ".." in target.parts:
            return "The path cannot contain '..'."
    if not agent._path_is_allowed(target):
        return "That folder is outside the folders this agent can search."
    if target.is_file():
        target = target.parent
    if not target.exists():
        return "That folder was not found."
    return target


def _default_places(agent: Any) -> list[Path]:
    home = Path.home()
    roots = [home / "Desktop", home / "Documents", home / "Downloads", home]
    external = agent._external_drive_root()
    if external is not None:
        roots.append(external)
    return roots


def _search_roots(query: str) -> tuple[list[Path], str | None]:
    """Folders for this question. The test override replaces every folder."""
    agent = _agent()
    if agent.search_root_override is not None:
        root = Path(agent.search_root_override)
        if not root.exists():
            return [], f"The search folder is not available at {root}."
        return [root], None
    explicit = _explicit_dir(agent, query)
    if isinstance(explicit, str):
        return [], explicit
    if isinstance(explicit, Path):
        return [explicit], None
    import agent_config

    places = _place_map(agent)
    named_labels = [label for label, pattern in _all_place_rules() if pattern.search(query or "")]
    drive_key = agent_config.volume_label().casefold()
    if named_labels:
        if drive_key and drive_key in named_labels and drive_key not in places:
            return [], agent_config.drive_missing_message()
        named = [(label, places[label]) for label in named_labels if label in places]
        roots = [path for _label, path in named if path.exists()]
        if not roots:
            return [], "That folder is not available."
        return roots, None
    roots = [path for path in _default_places(agent) if path.exists()]
    if not roots:
        return [], "No local folders are available to search."
    return roots, None


def _roots() -> list[Path]:
    roots, _problem = _search_roots("")
    return roots


def _extra_skip(root: Path, roots: list[Path]) -> set[str]:
    """Skip a folder that is already its own search root, plus profile caches."""
    extra = set(PROFILE_SKIP)
    try:
        resolved = root.resolve()
    except OSError:
        return extra
    for other in roots:
        try:
            other_resolved = other.resolve()
        except OSError:
            continue
        if other_resolved.parent == resolved:
            extra.add(other_resolved.name.casefold())
    return extra


def _iter_files(roots: list[Path]):
    seen = 0
    for root in roots:
        if seen >= SCAN_CAP:
            break
        extra = _extra_skip(root, roots)
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [
                name
                for name in dirs
                if name.casefold() not in SKIP_DIRS
                and name.casefold() not in extra
                and not name.startswith(".")
            ]
            if seen >= SCAN_CAP:
                break
            for name in files:
                if seen >= SCAN_CAP:
                    break
                path = Path(current) / name
                if path.is_symlink():
                    continue
                seen += 1
                yield path


def _index_db() -> Path:
    agent = _agent()
    agent.WORKSPACE.mkdir(parents=True, exist_ok=True)
    return agent.WORKSPACE / "file_index.sqlite"


def _tokens(query: str) -> list[str]:
    words: list[str] = []
    for token in re.split(r"[^A-Za-z0-9]+", (query or "").casefold()):
        if len(token) >= 3 and token not in SEARCH_STOP:
            words.append(token)
    return words


def _time_window(query: str, now: float) -> tuple[float, float] | None:
    folded = (query or "").casefold()
    day = 86400
    if "yesterday" in folded:
        return (now - 2 * day, now)
    if "last week" in folded or "past week" in folded:
        return (now - 8 * day, now)
    if "last month" in folded or "past month" in folded:
        return (now - 45 * day, now - 10 * day)
    if "recent" in folded:
        return (now - 21 * day, now)
    return None


def _docx_text(path: Path) -> str:
    agent = _agent()
    try:
        if path.stat().st_size > 1_000_000:
            return ""
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", text)
    return agent._scrub(" ".join(text.split())[:TEXT_STORE_CHARS])


def _read_text(path: Path) -> str:
    agent = _agent()
    name = path.name.casefold()
    if name in SECRET_NAMES or path.suffix.casefold() in SECRET_EXTS:
        return ""
    if path.suffix.casefold() == ".docx":
        return _docx_text(path)
    if path.suffix.casefold() not in TEXT_EXTS:
        return ""
    try:
        if path.stat().st_size > 1_000_000:
            return ""
        raw = path.read_bytes()[:65536]
    except OSError:
        return ""
    if b"\x00" in raw[:1024]:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    return agent._scrub(" ".join(text.split())[:TEXT_STORE_CHARS])


def _create_table(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE files USING fts5(
                path,
                name,
                folder,
                body,
                modified UNINDEXED,
                tokenize = 'porter'
            )
            """
        )
        return True
    except sqlite3.OperationalError:
        connection.execute(
            """
            CREATE TABLE files (
                path TEXT,
                name TEXT,
                folder TEXT,
                body TEXT,
                modified REAL
            )
            """
        )
        return False


def _uses_fts(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'files'"
    ).fetchone()
    return bool(row and row[0] and "fts5" in row[0].casefold())


def _stored_roots(database: Path) -> list[str] | None:
    if not database.is_file():
        return None
    connection = sqlite3.connect(database)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'index_roots'"
        ).fetchone()
        if exists is None:
            return None
        return [str(row[0]) for row in connection.execute("SELECT path FROM index_roots")]
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()


def _same_roots(database: Path, roots: list[Path]) -> bool:
    stored = _stored_roots(database)
    if stored is None:
        return False
    return sorted(stored) == sorted(str(root) for root in roots)


def index_local_files(query: str = "") -> dict[str, Any]:
    """Rebuild the file index. Text files are kept ahead of other names."""
    agent = _agent()
    roots, problem = _search_roots(query)
    if problem:
        return agent._err(problem)
    collected: list[tuple[bool, float, Path]] = []
    for path in _iter_files(roots):
        if path.name.casefold() in {"file_index.sqlite", "memory.sqlite"}:
            continue
        try:
            stat_result = path.stat()
        except OSError:
            continue
        text_file = path.suffix.casefold() in TEXT_EXTS
        collected.append((text_file, stat_result.st_mtime, path))
    collected.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen = collected[:INDEX_CAP]
    database = _index_db()
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TABLE IF EXISTS files")
        connection.execute("DROP TABLE IF EXISTS index_roots")
        _create_table(connection)
        connection.execute("CREATE TABLE index_roots (path TEXT)")
        rows = []
        for _text_file, modified, path in chosen:
            body = _read_text(path)
            rows.append(
                (
                    str(path),
                    path.name,
                    path.parent.name,
                    body,
                    float(modified),
                )
            )
        connection.executemany(
            "INSERT INTO files (path, name, folder, body, modified) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO index_roots (path) VALUES (?)",
            [(str(root),) for root in roots],
        )
        connection.commit()
    finally:
        connection.close()
    return agent._ok(
        f"Indexed {len(rows)} file(s).",
        files=len(rows),
        roots=[str(root) for root in roots],
    )


def _snippet(body: str, tokens: list[str]) -> str:
    compact = " ".join((body or "").split())
    if not compact:
        return ""
    folded = compact.casefold()
    index = 0
    for token in tokens:
        found = folded.find(token)
        if found >= 0:
            index = found
            break
    start = max(0, index - 80)
    piece = compact[start : start + 240]
    if start:
        piece = "..." + piece
    return _agent()._scrub(piece)


def _search_rows(
    connection: sqlite3.Connection,
    tokens: list[str],
    fts: bool,
) -> list[sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    if fts:
        match = " OR ".join(f'"{token}"' for token in tokens)
        try:
            return list(
                connection.execute(
                    """
                    SELECT path, name, folder, body, modified, bm25(files) AS rank
                    FROM files
                    WHERE files MATCH ?
                    ORDER BY rank
                    LIMIT 40
                    """,
                    (match,),
                )
            )
        except sqlite3.OperationalError:
            pass
    clauses = []
    args: list[str] = []
    for token in tokens:
        clauses.append("(lower(path) LIKE ? OR lower(body) LIKE ? OR lower(name) LIKE ?)")
        like = f"%{token}%"
        args.extend([like, like, like])
    if not clauses:
        return []
    sql = (
        "SELECT path, name, folder, body, modified, 0 AS rank FROM files WHERE "
        + " OR ".join(clauses)
        + " LIMIT 40"
    )
    return list(connection.execute(sql, args))


def search_local_files(query: str, refresh: Any = False, limit: Any = 8) -> dict[str, Any]:
    """Find files from a plain-language question. Nothing is opened."""
    agent = _agent()
    try:
        refresh_index = agent._as_bool(refresh, False)
        if isinstance(limit, bool) or not isinstance(limit, (int, float)):
            cap = 8
        else:
            cap = min(20, max(1, int(limit)))
        text = " ".join((query or "").split())
        if not text:
            return agent._err("Say which file or note to look for.")
        tokens = _tokens(text)
        if not tokens:
            return agent._err("Say which file or note to look for.")
        roots, problem = _search_roots(text)
        if problem:
            return agent._err(problem)
        database = _index_db()
        if refresh_index or not _same_roots(database, roots):
            built = index_local_files(text)
            if not built.get("ok"):
                return built
        connection = sqlite3.connect(database)
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'files'"
            ).fetchone()
            if exists is None:
                connection.close()
                built = index_local_files(text)
                if not built.get("ok"):
                    return built
                connection = sqlite3.connect(database)
            fts = _uses_fts(connection)
            rows = _search_rows(connection, tokens, fts)
        finally:
            connection.close()
        now = time.time()
        window = _time_window(text, now)

        def sort_key(row: sqlite3.Row) -> tuple[int, float]:
            score = 0
            name = str(row["name"] or "").casefold()
            folder = str(row["path"] or "").casefold()
            for token in tokens:
                if token in name:
                    score += 3
                elif token in folder:
                    score += 1
            modified = float(row["modified"] or 0)
            if window is not None and window[0] <= modified <= window[1]:
                score += 5
            return score, modified

        ranked = sorted(rows, key=sort_key, reverse=True)[:cap]
        matches = []
        for row in ranked:
            path_text = agent._scrub(str(row["path"]))
            matches.append(
                {
                    "path": path_text,
                    "name": agent._scrub(str(row["name"])),
                    "modified": float(row["modified"] or 0),
                    "snippet": _snippet(str(row["body"] or ""), tokens),
                }
            )
        if not matches:
            return agent._ok("No matching files.", matches=[], query=text)
        return agent._ok(
            f"Found {len(matches)} file(s).",
            matches=matches,
            query=text,
        )
    except Exception as exc:
        return agent._err(f"search_local_files failed: {exc}")


def file_content_rag_search(query: str, limit: Any = 8) -> dict[str, Any]:
    """Answer from the local FTS index. This is not a cloud embedding model."""
    agent = _agent()
    try:
        found = search_local_files(query, refresh=False, limit=limit)
        if not found.get("ok"):
            return found
        matches = list(found.get("matches") or [])
        found["engine"] = "fts5"
        if not matches:
            found["message"] = "No matching notes in the local file index."
            return found
        bits = []
        for item in matches[:3]:
            snippet = str(item.get("snippet") or "").strip()
            if snippet:
                bits.append(f"{item.get('name')}: {snippet}")
        detail = " ".join(bits)
        found["message"] = (
            "Local file index, not a cloud embedding model. "
            + (detail or f"Found {len(matches)} file(s).")
        )
        return found
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"file_content_rag_search failed: {exc}")


RAG_DECLARATIONS = [
    {
        "name": "file_content_rag_search",
        "description": (
            "Search indexed text, code, and docx notes on this PC and return "
            "a short snippet. This is a local FTS index, not a cloud embedding "
            "model. It does not open or run the files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words or a question about a local file."},
                "limit": {"type": "integer", "description": "Maximum matches. Default 8, at most 20."},
            },
            "required": ["query"],
        },
    }
]


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}
PDF_EXTS = {".pdf"}
DOCUMENT_EXTS = {".pdf", ".txt", ".md", ".doc", ".docx", ".rtf", ".odt"}
EXCEL_EXTS = {".xlsx", ".xlsm", ".xls", ".csv"}
_TYPE_WORDS: tuple[tuple[str, set[str]], ...] = (
    ("video", VIDEO_EXTS),
    ("movie", VIDEO_EXTS),
    ("audio", AUDIO_EXTS),
    ("music", AUDIO_EXTS),
    ("photo", PHOTO_EXTS),
    ("picture", PHOTO_EXTS),
    ("image", PHOTO_EXTS),
    ("pdf", PDF_EXTS),
    ("document", DOCUMENT_EXTS),
    ("excel", EXCEL_EXTS),
    ("spreadsheet", EXCEL_EXTS),
    ("workbook", EXCEL_EXTS),
)
_EXT_WORDS = {
    ext[1:]: {ext}
    for ext in VIDEO_EXTS | AUDIO_EXTS | PHOTO_EXTS | DOCUMENT_EXTS | EXCEL_EXTS
}


def _clock_now(agent: Any) -> float:
    clock = agent.scheduler_clock
    if clock is None:
        return time.time()
    return float(clock())


def _calendar_window(query: str, now: float) -> tuple[float, float] | None:
    """Half-open local window. The end is exclusive."""
    folded = (query or "").casefold()
    moment = datetime.fromtimestamp(now)
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if "yesterday" in folded:
        start = midnight - timedelta(days=1)
        return (start.timestamp(), midnight.timestamp())
    if "today" in folded:
        return (midnight.timestamp(), now + 1)
    if "last week" in folded or "past week" in folded:
        this_monday = midnight - timedelta(days=midnight.weekday())
        last_monday = this_monday - timedelta(days=7)
        return (last_monday.timestamp(), this_monday.timestamp())
    if "last month" in folded or "past month" in folded:
        first_this = midnight.replace(day=1)
        previous = first_this - timedelta(days=1)
        first_prev = previous.replace(day=1)
        return (first_prev.timestamp(), first_this.timestamp())
    if "recent" in folded:
        start = midnight - timedelta(days=14)
        return (start.timestamp(), now + 1)
    return None


def _wanted_types(query: str) -> set[str]:
    folded = (query or "").casefold()
    wanted: set[str] = set()
    for word, suffixes in _TYPE_WORDS:
        if word == "document":
            if re.search(r"\bdocument\b", folded) and not re.search(r"\bdocuments\b", folded):
                wanted.update(suffixes)
            continue
        if re.search(rf"\b{re.escape(word)}s?\b", folded):
            wanted.update(suffixes)
    for word, suffixes in _EXT_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", folded):
            wanted.update(suffixes)
    return wanted


def _secret_file(path: Path) -> bool:
    name = path.name.casefold()
    return name in SECRET_NAMES or name.endswith(".env") or path.suffix.casefold() in SECRET_EXTS


def search_files_by_time(
    query: str,
    file_type: str = "",
    when: str = "",
    limit: Any = 8,
) -> dict[str, Any]:
    """Find files by a calendar window, a file type, or both. Nothing is opened."""
    agent = _agent()
    try:
        if isinstance(limit, bool) or not isinstance(limit, (int, float)):
            cap = 8
        else:
            cap = min(20, max(1, int(limit)))
        text = " ".join(
            part.strip()
            for part in (query or "", file_type or "", when or "")
            if str(part or "").strip()
        )
        if not text:
            return agent._err("Say a file type or a time, such as videos from last week.")
        wanted = _wanted_types(text)
        window = _calendar_window(text, _clock_now(agent))
        if not wanted and window is None:
            return agent._err("Say a file type or a time, such as videos from last week.")
        roots, problem = _search_roots(text)
        if problem:
            return agent._err(problem)
        found: list[tuple[float, Path]] = []
        for path in _iter_files(roots):
            if _secret_file(path):
                continue
            suffix = path.suffix.casefold()
            if wanted and suffix not in wanted:
                continue
            try:
                modified = path.stat().st_mtime
            except OSError:
                continue
            if window is not None and not (window[0] <= modified < window[1]):
                continue
            found.append((modified, path))
        found.sort(key=lambda item: item[0], reverse=True)
        matches = []
        for modified, path in found[:cap]:
            matches.append(
                {
                    "path": agent._scrub(str(path)),
                    "name": agent._scrub(path.name),
                    "modified": modified,
                    "suffix": path.suffix.casefold(),
                }
            )
        if not matches:
            return agent._ok("No matching files.", matches=[], query=text)
        return agent._ok(
            f"Found {len(matches)} file(s).",
            matches=matches,
            query=text,
            roots=[str(root) for root in roots],
        )
    except Exception as exc:
        return agent._err(f"search_files_by_time failed: {exc}")
