"""Connectors Pedro can use from this PC.

Gmail, Notion, Slack, and Linear keep a secret in the storage folder.
Drive and OneDrive use folders already on the PC. GitHub uses the GitHub
CLI. Outlook uses the Outlook app. Nothing here is printed back to chat
except titles, senders, and file names.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

_lock = threading.Lock()
# Tests set these. None uses the real store, network, or app.
store_override: dict[str, Any] | None = None
http_override: Callable[[str, str, dict[str, str], dict[str, Any] | None], tuple[int, str]] | None = None
imap_override: Callable[[str, str, str], list[dict[str, str]]] | None = None
command_override: Callable[[list[str]], tuple[int, str]] | None = None
folder_roots_override: dict[str, str] | None = None
outlook_override: bool | None = None
outlook_reader: Callable[[str], list[dict[str, str]]] | None = None

_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "gmail", "name": "Gmail", "kind": "gmail",
     "blurb": "Search and read mail on this PC. Sending still asks you first."},
    {"id": "gcalendar", "name": "Google Calendar", "kind": "unavailable",
     "blurb": "Events on a Google account.",
     "detail": "Google Calendar needs a Google sign-in this PC does not have yet."},
    {"id": "gdrive", "name": "Google Drive", "kind": "folder",
     "blurb": "Files in the Google Drive folder on this PC."},
    {"id": "onedrive", "name": "OneDrive", "kind": "folder",
     "blurb": "Files in the OneDrive folder on this PC."},
    {"id": "outlook", "name": "Outlook Mail & Calendar", "kind": "outlook",
     "blurb": "Mail and calendar events in the Outlook app on this PC."},
    {"id": "teams", "name": "Microsoft Teams", "kind": "unavailable",
     "blurb": "Teams chats and channels.",
     "detail": "Teams needs a Microsoft work sign-in this PC does not have yet."},
    {"id": "notion", "name": "Notion", "kind": "token",
     "blurb": "Pages and databases shared with a Notion integration."},
    {"id": "github", "name": "GitHub", "kind": "github",
     "blurb": "Repositories, issues, and pull requests through the GitHub CLI."},
    {"id": "slack", "name": "Slack", "kind": "token",
     "blurb": "Messages a Slack token is allowed to search."},
    {"id": "linear", "name": "Linear", "kind": "token",
     "blurb": "Issues in a Linear workspace."},
    {"id": "youtube", "name": "YouTube", "kind": "youtube",
     "blurb": "The YouTube channel already set up for posting."},
)
_ALIASES = {
    "gmail": "gmail", "googlemail": "gmail",
    "gcalendar": "gcalendar", "googlecalendar": "gcalendar",
    "gdrive": "gdrive", "googledrive": "gdrive",
    "onedrive": "onedrive",
    "outlook": "outlook",
    "teams": "teams", "microsoftteams": "teams",
    "notion": "notion",
    "github": "github",
    "slack": "slack",
    "linear": "linear",
    "youtube": "youtube",
}
_TOKEN_IDS = {"notion", "slack", "linear"}


def _agent() -> Any:
    import agent_core

    return agent_core


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    agent = _agent()
    return agent._ok(agent._scrub(message), **extra)


def _err(message: str, **extra: Any) -> dict[str, Any]:
    agent = _agent()
    return agent._err(agent._scrub(message), **extra)


def _hide(text: str, secret: str) -> str:
    raw = " ".join(str(text or "").split())
    if secret and len(secret) > 4:
        raw = raw.replace(secret, "[hidden]")
    return raw[:400]


def _store_path() -> Path:
    import agent_config

    folder = agent_config.storage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "connectors.json"


def _read_store() -> dict[str, Any]:
    if store_override is not None:
        return store_override
    path = _store_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_store(data: dict[str, Any]) -> None:
    snapshot = {key: (dict(value) if isinstance(value, dict) else value) for key, value in data.items()}
    if store_override is not None:
        store_override.clear()
        store_override.update(snapshot)
        return
    path = _store_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _spec(name: str) -> dict[str, str] | None:
    key = _ALIASES.get("".join(str(name or "").casefold().split()), "")
    for item in _CATALOG:
        if item["id"] == key:
            return item
    return None


def gmail_login() -> tuple[str, str] | None:
    """Address and app password saved from Connectors. None when unset."""
    import gmail_mail

    saved = _read_store().get("gmail")
    if not isinstance(saved, dict):
        return None
    address = str(saved.get("address") or "").strip()
    password = "".join(str(saved.get("password") or "").split())
    if gmail_mail.valid_email(address) and 8 <= len(password) <= 64:
        return address, password
    return None


def _gmail_setup() -> tuple[str, str, str] | None:
    import gmail_mail

    address = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = "".join(os.environ.get("GMAIL_APP_PASSWORD", "").split())
    if gmail_mail.valid_email(address) and 8 <= len(password) <= 64:
        return address, password, "env"
    saved = gmail_login()
    if saved:
        return saved[0], saved[1], "store"
    return None


def _token(name: str) -> str:
    saved = _read_store().get(name)
    if not isinstance(saved, dict):
        return ""
    secret = "".join(str(saved.get("token") or "").split())
    if 8 <= len(secret) <= 200:
        return secret
    return ""


def _http(method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, str]:
    if http_override is not None:
        return http_override(method, url, headers, body)
    import urllib.error
    import urllib.request

    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return int(response.status), response.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(20_000).decode("utf-8", "replace")


def _run(args: list[str]) -> tuple[int, str]:
    if command_override is not None:
        return command_override(args)
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    text = (proc.stdout or "")[:5000]
    if proc.returncode and proc.stderr:
        text = (text + "\n" + proc.stderr[:500]).strip()
    return int(proc.returncode), text


def _folder_roots(name: str) -> list[Path]:
    if folder_roots_override is not None:
        raw = folder_roots_override.get(name) or ""
        path = Path(raw) if raw else None
        return [path] if path and path.is_dir() else []
    found: list[Path] = []
    if name == "onedrive":
        for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            raw = os.environ.get(key, "").strip().strip('"')
            if raw:
                path = Path(raw)
                if path.is_dir() and path not in found:
                    found.append(path)
        for child in Path.home().glob("OneDrive*"):
            if child.is_dir() and child not in found:
                found.append(child)
        return found
    home = Path.home()
    for child in list(home.glob("Google Drive*")) + list(home.glob("My Drive")):
        if child.is_dir() and child not in found:
            found.append(child)
    return found


def _search_names(root: Path, query: str, limit: int = 12) -> list[str]:
    words = [part.casefold() for part in query.split() if len(part) > 1][:6]
    hits: list[str] = []
    seen = 0
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".") and name not in {"node_modules", ".git"}]
        if len(Path(current).relative_to(root).parts) > 4:
            dirnames.clear()
            continue
        for name in filenames:
            seen += 1
            if seen > 4000:
                return hits
            if words and not any(word in name.casefold() for word in words):
                continue
            hits.append(str(Path(current) / name))
            if len(hits) >= limit:
                return hits
    return hits


def _outlook_installed() -> bool:
    if outlook_override is not None:
        return bool(outlook_override)
    if os.name != "nt":
        return False
    try:
        import winreg

        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE")
        return True
    except OSError:
        return False


def _youtube_state() -> tuple[bool, str]:
    client = bool(os.environ.get("YOUTUBE_CLIENT_ID", "").strip() and os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip())
    import agent_config

    signed = (agent_config.storage_dir() / "youtube_token.json").is_file()
    if client and signed:
        return True, "Signed in on this PC."
    if client:
        return False, "The YouTube client is saved. Connect to sign in."
    return False, "YouTube needs a Google sign-in client before it can connect."


def _github_connected() -> bool:
    code, _text = _run(["gh", "auth", "status"])
    return code == 0


def _public(spec: dict[str, str]) -> dict[str, Any]:
    name = spec["id"]
    kind = spec["kind"]
    connected = False
    detail = spec.get("detail") or ""
    account = ""
    if kind == "gmail":
        setup = _gmail_setup()
        connected = setup is not None
        if setup:
            account = setup[0]
        else:
            detail = "Add the Gmail address and an app password. It stays on this PC."
    elif kind == "token":
        connected = bool(_token(name))
        if not connected:
            detail = "Paste the token from that service. It stays on this PC and is not shown again."
    elif kind == "folder":
        roots = _folder_roots(name)
        connected = bool(roots)
        detail = str(roots[0]) if roots else "That folder is not on this PC."
    elif kind == "outlook":
        connected = _outlook_installed()
        detail = "Outlook is installed." if connected else "Outlook is not installed on this PC."
    elif kind == "github":
        connected = _github_connected()
        detail = "Signed in with the GitHub CLI." if connected else "Install GitHub CLI and run gh auth login once."
    elif kind == "youtube":
        connected, detail = _youtube_state()
    row = {
        "id": name,
        "name": spec["name"],
        "blurb": spec["blurb"],
        "kind": kind,
        "connected": connected,
        "detail": detail,
    }
    if account:
        row["account"] = account
    return row


def catalog() -> list[dict[str, Any]]:
    with _lock:
        return [_public(item) for item in _CATALOG]


def list_connectors() -> dict[str, Any]:
    """Which services are connected. No passwords or tokens."""
    rows = catalog()
    ready = [str(row["name"]) for row in rows if row.get("connected")]
    missing = [str(row["name"]) for row in rows if not row.get("connected")]
    return _ok(
        "Connected: " + (", ".join(ready) or "none") + ". Not connected: " + ", ".join(missing) + ".",
        connectors=rows,
    )


def _check_token(name: str, secret: str) -> str:
    if name == "notion":
        status, body = _http(
            "POST",
            "https://api.notion.com/v1/search",
            {"Authorization": "Bearer " + secret, "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
            {"page_size": 1},
        )
        if status != 200:
            return _hide(body, secret) or "Notion refused that token."
        return ""
    if name == "slack":
        status, body = _http(
            "POST",
            "https://slack.com/api/auth.test",
            {"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
            {},
        )
        try:
            data = json.loads(body)
        except ValueError:
            data = {}
        if status != 200 or not data.get("ok"):
            return _hide(str(data.get("error") or body), secret) or "Slack refused that token."
        return ""
    status, body = _http(
        "POST",
        "https://api.linear.app/graphql",
        {"Authorization": secret, "Content-Type": "application/json"},
        {"query": "{ viewer { name } }"},
    )
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if status != 200 or not (data.get("data") or {}).get("viewer"):
        return _hide(body, secret) or "Linear refused that token."
    return ""


def connect(name: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Save a sign-in from the Connectors page. The secret is not returned."""
    spec = _spec(name)
    if spec is None:
        return _err("That connector is not in the list.")
    fields = fields or {}
    kind = spec["kind"]
    if kind == "unavailable":
        return _err(spec.get("detail") or "That connector is not available on this PC.")
    with _lock:
        if kind == "gmail":
            import gmail_mail

            address = str(fields.get("address") or "").strip()
            password = "".join(str(fields.get("secret") or fields.get("password") or "").split())
            if not gmail_mail.valid_email(address) or not (8 <= len(password) <= 64):
                return _err("Enter the Gmail address and the app password.")
            if not gmail_mail.app_password_ok(password):
                return _err(gmail_mail.APP_PASSWORD_HINT)
            data = _read_store()
            data["gmail"] = {"address": address, "password": password}
            _write_store(data)
            os.environ["GMAIL_ADDRESS"] = address
            os.environ["GMAIL_APP_PASSWORD"] = password
            return _ok("Gmail is connected.", id="gmail", connected=True, account=address)
        if kind == "token":
            secret = "".join(str(fields.get("secret") or "").split())
            if not (8 <= len(secret) <= 200):
                return _err("Paste the token from that service.")
            problem = _check_token(spec["id"], secret)
            if problem:
                return _err(problem)
            data = _read_store()
            data[spec["id"]] = {"token": secret}
            _write_store(data)
            return _ok(f"{spec['name']} is connected.", id=spec["id"], connected=True)
        if kind == "youtube":
            import youtube_channel

            result = youtube_channel.youtube_connect()
            return result if isinstance(result, dict) else _err("YouTube did not connect.")
        row = _public(spec)
        if not row["connected"]:
            return _err(str(row.get("detail") or f"{spec['name']} is not available on this PC."))
        return _ok(f"{spec['name']} is connected.", **{k: row[k] for k in ("id", "connected", "detail")})


def disconnect(name: str) -> dict[str, Any]:
    spec = _spec(name)
    if spec is None:
        return _err("That connector is not in the list.")
    if spec["kind"] not in {"gmail", "token"}:
        return _err(f"{spec['name']} is detected on this PC. There is no saved secret to remove.")
    with _lock:
        data = _read_store()
        if spec["id"] == "gmail":
            saved = data.get("gmail") if isinstance(data.get("gmail"), dict) else {}
            password = "".join(str((saved or {}).get("password") or "").split())
            data.pop("gmail", None)
            _write_store(data)
            if password and os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "") == password:
                os.environ.pop("GMAIL_ADDRESS", None)
                os.environ.pop("GMAIL_APP_PASSWORD", None)
            elif _gmail_setup() and _gmail_setup()[-1] == "env":  # type: ignore[index]
                return _ok("Removed the saved Gmail sign-in. The environment still has one.")
            return _ok("Gmail is disconnected.", id="gmail", connected=False)
        data.pop(spec["id"], None)
        _write_store(data)
    return _ok(f"{spec['name']} is disconnected.", id=spec["id"], connected=False)


def _format_rows(title: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        return _ok(f"{title} returned nothing for that search.", items=[])
    lines = [title + ":"]
    clean: list[dict[str, str]] = []
    for row in rows[:8]:
        item = {key: " ".join(str(row.get(key) or "").split())[:400] for key in ("from", "title", "when", "snippet", "path", "url") if row.get(key)}
        if not item:
            continue
        clean.append(item)
        bits = [item.get("when") or "", item.get("from") or "", item.get("title") or item.get("path") or ""]
        line = " — ".join(bit for bit in bits if bit)
        if item.get("snippet"):
            line += ". " + item["snippet"]
        lines.append(line)
    return _ok("\n".join(lines), items=clean)


def _gmail_search(query: str) -> dict[str, Any]:
    setup = _gmail_setup()
    if setup is None:
        return _err("Gmail is not connected. Open Connectors and connect it.")
    address, password, _source = setup
    text = " ".join((query or "").split())[:200] or "newer_than:14d"
    if imap_override is not None:
        return _format_rows("Gmail", imap_override(address, password, text))
    try:
        rows = _gmail_imap(address, password, text)
    except Exception:
        return _err("Gmail did not open. Check the address and the app password in Connectors.")
    return _format_rows("Gmail", rows)


def _decode_header(value: str) -> str:
    from email.header import decode_header

    parts: list[str] = []
    for chunk, encoding in decode_header(value or ""):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(encoding or "utf-8", "replace"))
        else:
            parts.append(str(chunk))
    return " ".join(" ".join(parts).split())[:300]


def _gmail_imap(address: str, password: str, query: str) -> list[dict[str, str]]:
    import email
    import imaplib

    rows: list[dict[str, str]] = []
    conn = imaplib.IMAP4_SSL("imap.gmail.com", timeout=20)
    try:
        conn.login(address, password)
        conn.select("INBOX", readonly=True)
        try:
            _typ, data = conn.uid("SEARCH", "X-GM-RAW", query)
        except imaplib.IMAP4.error:
            _typ, data = conn.uid("SEARCH", "ALL")
        raw = data[0] if data and data[0] else b""
        uids = raw.split()[-8:]
        for uid in reversed(uids):
            _typ, fetched = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.700>)")
            blob = b""
            snippet = ""
            for part in fetched or []:
                if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], (bytes, bytearray)):
                    piece = bytes(part[1])
                    if b"From:" in piece[:400] or b"Subject:" in piece[:400]:
                        blob += piece
                    else:
                        snippet = piece.decode("utf-8", "replace")
            message = email.message_from_bytes(blob or b"")
            text = " ".join(snippet.replace("\r", " ").replace("\n", " ").split())
            rows.append({
                "from": _decode_header(str(message.get("From") or "")),
                "title": _decode_header(str(message.get("Subject") or "(no subject)")),
                "when": _decode_header(str(message.get("Date") or "")),
                "snippet": text[:400],
            })
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return rows


def _notion_search(query: str) -> dict[str, Any]:
    secret = _token("notion")
    if not secret:
        return _err("Notion is not connected. Open Connectors and paste the integration token.")
    status, body = _http(
        "POST",
        "https://api.notion.com/v1/search",
        {"Authorization": "Bearer " + secret, "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
        {"query": query[:200], "page_size": 8},
    )
    if status != 200:
        return _err("Notion did not answer. " + _hide(body, secret))
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    rows = []
    for item in (data.get("results") or [])[:8]:
        props = item.get("properties") or {}
        title = ""
        for prop in props.values():
            rich = prop.get("title") if isinstance(prop, dict) else None
            if isinstance(rich, list) and rich:
                title = "".join(str(bit.get("plain_text") or "") for bit in rich)
                break
        if not title:
            title = str((item.get("title") or [{}])[0].get("plain_text") or "") if isinstance(item.get("title"), list) else ""
        rows.append({"title": title or "Untitled", "url": str(item.get("url") or "")})
    return _format_rows("Notion", rows)


def _slack_search(query: str) -> dict[str, Any]:
    secret = _token("slack")
    if not secret:
        return _err("Slack is not connected. Open Connectors and paste the token.")
    status, body = _http(
        "GET",
        "https://slack.com/api/search.messages?query=" + __import__("urllib.parse", fromlist=["quote"]).quote(query[:200]),
        {"Authorization": "Bearer " + secret},
        None,
    )
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if status != 200 or not data.get("ok"):
        return _err("Slack did not answer. " + _hide(str(data.get("error") or body), secret))
    matches = ((data.get("messages") or {}).get("matches") or [])[:8]
    rows = []
    for item in matches:
        channel = item.get("channel")
        rows.append({
            "from": str(item.get("username") or item.get("user") or ""),
            "title": str(channel.get("name") or "") if isinstance(channel, dict) else "",
            "snippet": str(item.get("text") or "")[:400],
            "url": str(item.get("permalink") or ""),
        })
    return _format_rows("Slack", rows)


def _linear_search(query: str) -> dict[str, Any]:
    secret = _token("linear")
    if not secret:
        return _err("Linear is not connected. Open Connectors and paste the API key.")
    status, body = _http(
        "POST",
        "https://api.linear.app/graphql",
        {"Authorization": secret, "Content-Type": "application/json"},
        {"query": "query($q: String!) { searchIssues(term: $q, first: 8) { nodes { identifier title url } } }",
         "variables": {"q": query[:200]}},
    )
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    nodes = (((data.get("data") or {}).get("searchIssues") or {}).get("nodes") or []) if status == 200 else []
    if status != 200 or data.get("errors"):
        return _err("Linear did not answer. " + _hide(body, secret))
    rows = [{"title": f"{item.get('identifier') or ''} {item.get('title') or ''}".strip(), "url": str(item.get("url") or "")} for item in nodes]
    return _format_rows("Linear", rows)


def _folder_search(name: str, label: str, query: str) -> dict[str, Any]:
    roots = _folder_roots(name)
    if not roots:
        return _err(f"{label} is not on this PC.")
    rows: list[dict[str, str]] = []
    for root in roots:
        for path in _search_names(root, query):
            rows.append({"title": Path(path).name, "path": path})
    return _format_rows(label, rows)


def _github_search(query: str) -> dict[str, Any]:
    if not _github_connected():
        return _err("GitHub is not connected. Install GitHub CLI and run gh auth login once.")
    text = " ".join((query or "is:open").split())[:200]
    code, out = _run(["gh", "search", "issues", text, "--limit", "6"])
    if code != 0:
        return _err("GitHub search failed. " + " ".join(out.split())[:300])
    rows = [{"title": line.strip()} for line in out.splitlines() if line.strip()]
    return _format_rows("GitHub", rows)


def _outlook_search(query: str) -> dict[str, Any]:
    if outlook_reader is not None:
        return _format_rows("Outlook", outlook_reader(query))
    if not _outlook_installed():
        return _err("Outlook is not installed on this PC.")
    try:
        rows = _outlook_com(query)
    except Exception as exc:
        return _err("Outlook did not open. Open Outlook once, then try again. " + type(exc).__name__)
    return _format_rows("Outlook", rows)


def _outlook_com(query: str) -> list[dict[str, str]]:
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")
    words = [part.casefold() for part in query.split() if len(part) > 1][:6]
    rows: list[dict[str, str]] = []

    def take(folder_id: int, when_attr: str, who_attr: str, title_attr: str) -> None:
        folder = namespace.GetDefaultFolder(folder_id)
        items = folder.Items
        items.Sort("[" + when_attr + "]", True)
        count = min(int(items.Count), 30)
        for index in range(1, count + 1):
            if len(rows) >= 8:
                return
            item = items.Item(index)
            title = str(getattr(item, title_attr, "") or "")
            who = str(getattr(item, who_attr, "") or "")
            blob = (title + " " + who).casefold()
            if words and not any(word in blob for word in words):
                continue
            when = str(getattr(item, when_attr, "") or "")
            rows.append({"from": who, "title": title or "(no subject)", "when": when[:40]})

    take(6, "ReceivedTime", "SenderName", "Subject")
    take(9, "Start", "Organizer", "Subject")
    return rows


def connector_search(name: str, query: str = "") -> dict[str, Any]:
    """Read one connected service. This does not send, delete, or post."""
    spec = _spec(name)
    if spec is None:
        return _err("Unknown connector. Call list_connectors and use one of those names.")
    text = " ".join(str(query or "").split())[:200]
    kind = spec["kind"]
    if kind == "unavailable":
        return _err(spec.get("detail") or f"{spec['name']} is not available on this PC.")
    if spec["id"] == "gmail":
        return _gmail_search(text)
    if spec["id"] == "notion":
        return _notion_search(text)
    if spec["id"] == "slack":
        return _slack_search(text)
    if spec["id"] == "linear":
        return _linear_search(text)
    if spec["id"] == "gdrive":
        return _folder_search("gdrive", "Google Drive", text)
    if spec["id"] == "onedrive":
        return _folder_search("onedrive", "OneDrive", text)
    if spec["id"] == "github":
        return _github_search(text)
    if spec["id"] == "outlook":
        return _outlook_search(text)
    connected, detail = _youtube_state()
    if not connected:
        return _err(detail)
    return _ok("YouTube is signed in on this PC. " + detail + " Use search_youtube to open a search, or watch_video for a link.")
