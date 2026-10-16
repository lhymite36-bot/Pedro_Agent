"""Send one Gmail message, or look up a saved contact.

A recipient that is already an email address is used as-is. A name is
resolved through the local contact list. Invalid addresses and names that
match more than one contact are returned for clarification and are not sent.

SMTP is stdlib only. Tests set gmail_transport_override and contacts_override
and never open a socket. The app password is not accepted as a tool argument
and is not included in the sender payload.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

MAX_BODY = 20000
MAX_SUBJECT = 200
MAX_MATCHES = 8
_EMAIL_FIND = re.compile(
    r"(?<![A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?![A-Za-z0-9.\-])"
)
_EMAIL_EXACT = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\Z")
_BODY_SPLIT = re.compile(r"\b(?:saying|that|about|regarding)\s+", re.IGNORECASE)
_NAME_SPLIT = re.compile(
    r"\bto\s+(.+?)(?:\s+(?:saying|about|regarding|that)\b|$)",
    re.IGNORECASE,
)


def _agent() -> Any:
    import agent_core

    return agent_core


def _safe(text: str) -> str:
    return _agent()._scrub(text or "")


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return _agent()._ok(_safe(message), **extra)


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return _agent()._err(_safe(message), **extra)


def _clarify(message: str, matches: list[dict[str, str]] | None = None) -> dict[str, Any]:
    extra: dict[str, Any] = {"needs_clarification": True}
    if matches:
        extra["matches"] = matches[:MAX_MATCHES]
    return _err(message, **extra)


def valid_email(value: str) -> bool:
    """True for one plain address with no display name and no extra headers."""
    text = str(value or "").strip()
    if not text or len(text) > 254:
        return False
    if any(char in text for char in "\r\n\t ,;<>\"'\\"):
        return False
    return _EMAIL_EXACT.fullmatch(text) is not None


def _clean_subject(value: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > MAX_SUBJECT:
        text = text[: MAX_SUBJECT - 3].rstrip() + "..."
    return text


def _auto_subject(body: str) -> str:
    line = " ".join(body.split())
    sentence = re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0].strip()
    if len(sentence) > 80:
        cut = sentence[:77].rsplit(" ", 1)[0]
        sentence = (cut or sentence[:77]).rstrip(".,;:") + "..."
    if sentence[:1].islower():
        sentence = sentence[0].upper() + sentence[1:]
    return _clean_subject(sentence or "Note")


def _parse_command(text: str) -> dict[str, Any]:
    raw = " ".join(str(text or "").split())
    subject = ""
    quoted = re.search(r"\bsubject\s*[:\-]?\s*[\"']([^\"']+)[\"']", raw, re.IGNORECASE)
    if quoted:
        subject = quoted.group(1).strip()
        raw = f"{raw[:quoted.start()]} {raw[quoted.end():]}"
        raw = " ".join(raw.split())
    else:
        plain = re.search(
            r"\b(?:with\s+)?subject\s*[:\-]\s*(.+?)(?=\s+\b(?:saying|that|about|regarding)\b|$)",
            raw,
            re.IGNORECASE,
        )
        if plain:
            subject = plain.group(1).strip(" .")
            raw = f"{raw[:plain.start()]} {raw[plain.end():]}"
            raw = " ".join(raw.split())
    emails = _EMAIL_FIND.findall(raw)
    body = ""
    body_match = _BODY_SPLIT.search(raw)
    if body_match:
        body = raw[body_match.end():].strip()
    name = ""
    if not emails:
        name_match = _NAME_SPLIT.search(raw)
        if name_match:
            name = name_match.group(1).strip(" .,")
    return {"emails": emails, "name": name[:80], "subject": subject, "body": body}


def _has_secret(text: str) -> bool:
    raw = str(text or "")
    if not raw:
        return False
    return _safe(raw) != raw


def _load_contacts() -> list[dict[str, str]]:
    agent = _agent()
    override = agent.contacts_override
    if override is not None:
        raw = override() if callable(override) else override
    else:
        path = agent.WORKSPACE / "contacts.json"
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("The contact list could not be read.") from exc
    if not isinstance(raw, list):
        raise RuntimeError("The contact list could not be read.")
    contacts: list[dict[str, str]] = []
    for item in raw[:500]:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())
        email = str(item.get("email") or "").strip()
        if name and valid_email(email):
            contacts.append({"name": name, "email": email})
    return contacts


def _match_contacts(query: str, contacts: list[dict[str, str]]) -> list[dict[str, str]]:
    folded = " ".join(query.casefold().split())
    if not folded:
        return []
    exact = [
        item
        for item in contacts
        if item["name"].casefold() == folded or item["email"].casefold() == folded
    ]
    if exact:
        return exact
    parts = [
        item
        for item in contacts
        if folded in {part.casefold() for part in item["name"].split()}
    ]
    if parts:
        return parts
    return [item for item in contacts if folded in item["name"].casefold()]


def people_contact_search(query: str) -> dict[str, Any]:
    """Find saved contacts by name. This does not send mail."""
    try:
        name = " ".join(str(query or "").split())
        if not name:
            return _clarify("Ask for the contact name.")
        if valid_email(name):
            return _ok(
                "That is already an email address. No contact lookup is needed.",
                matches=[{"name": name, "email": name}],
            )
        found = _match_contacts(name, _load_contacts())
        if not found:
            return _clarify(
                f"I could not find a saved address for {name}. Ask for the email address."
            )
        if len(found) == 1:
            contact = found[0]
            return _ok(
                f"Found {contact['name']} at {contact['email']}.",
                matches=found,
            )
        shown = found[:MAX_MATCHES]
        return _clarify(
            f"{name} matches {len(found)} contacts. Ask which address to use.",
            matches=shown,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"people_contact_search failed: {exc}")


def _interpret(to: str, subject: str, body: str, request: str) -> dict[str, Any]:
    raw_to = str(to or "")
    raw_subject = str(subject or "")
    raw_request = str(request or "")
    if any(char in f"{raw_to}{raw_subject}{raw_request}" for char in "\r\n"):
        return {"clarify": "That address is not valid. Ask for one email address."}
    recipient = " ".join(raw_to.split())
    subject_text = _clean_subject(raw_subject)
    body_text = str(body or "").strip()
    command = raw_request.strip()
    if command and not recipient:
        parsed = _parse_command(command)
        if len(parsed["emails"]) > 1:
            return {
                "clarify": "That request has more than one email address. Ask which one to use.",
                "matches": [{"name": email, "email": email} for email in parsed["emails"][:MAX_MATCHES]],
            }
        recipient = parsed["emails"][0] if parsed["emails"] else parsed["name"]
        if not subject_text:
            subject_text = _clean_subject(parsed["subject"])
        if not body_text:
            body_text = parsed["body"]
    if not recipient:
        return {"clarify": "Who should get this email? Ask for a name or an email address."}
    emails = _EMAIL_FIND.findall(recipient)
    if len(emails) > 1:
        return {
            "clarify": "That request has more than one email address. Ask which one to use.",
            "matches": [{"name": email, "email": email} for email in emails[:MAX_MATCHES]],
        }
    if len(emails) == 1 and emails[0] != recipient:
        parsed = _parse_command(recipient)
        if not body_text:
            body_text = parsed["body"]
        if not subject_text:
            subject_text = _clean_subject(parsed["subject"])
        recipient = emails[0]
    if any(char in recipient for char in "\r\n\t,;<>\"'\\"):
        return {"clarify": "That address is not valid. Ask for one email address."}
    if len(body_text) > MAX_BODY:
        body_text = body_text[:MAX_BODY]
    return {"to": recipient, "subject": subject_text, "body": body_text}


def _configured() -> tuple[str, str] | None:
    address = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = "".join(os.environ.get("GMAIL_APP_PASSWORD", "").split())
    if valid_email(address) and len(password) >= 8:
        return address, password
    try:
        import connectors

        return connectors.gmail_login()
    except Exception:
        return None


def _mail_drop(exc: BaseException) -> bool:
    """True when Gmail closed the connection and another try can still send."""
    import smtplib

    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return False
    code = getattr(exc, "smtp_code", None)
    if isinstance(code, int) and code not in {421, 450, 451, 452}:
        return False
    text = str(exc).casefold()
    if any(token in text for token in (
        "unexpectedly closed", "connection reset", "timed out", "timeout",
        "connection aborted", "disconnected", "connection refused", "eof occurred",
    )):
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


def _smtp_send(sender: str, password: str, recipient: str, subject: str, body: str) -> None:
    import smtplib
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(sender, password)
        smtp.send_message(message)


def _deliver(recipient: str, subject: str, body: str) -> dict[str, Any]:
    agent = _agent()
    sender = os.environ.get("GMAIL_ADDRESS", "").strip()
    payload = {"to": recipient, "subject": subject, "body": body, "from": sender}
    if agent.gmail_transport_override is not None:
        result = agent.gmail_transport_override(payload)
        if not isinstance(result, dict):
            raise RuntimeError("The Gmail sender returned nothing.")
        if result.get("ok") is False:
            return _err(str(result.get("error") or "The email was not sent."))
        return _ok(
            f"Email successfully sent to {recipient}.",
            to=recipient,
            subject=subject,
        )
    setup = _configured()
    if setup is None:
        return _err(
            "Gmail is not set up. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in the environment."
        )
    account, password = setup
    payload["from"] = account
    import smtplib

    last: BaseException | None = None
    for _attempt in range(3):
        try:
            _smtp_send(account, password, recipient, subject, body)
            last = None
            break
        except AssertionError:
            raise
        except smtplib.SMTPAuthenticationError as exc:
            return _err(f"The email was not sent. {_safe(str(exc))}")
        except Exception as exc:
            last = exc
            if _mail_drop(exc):
                continue
            return _err(f"The email was not sent. {_safe(str(exc))}")
    if last is not None:
        return _err(f"The email was not sent. {_safe(str(last))}")
    return _ok(
        f"Email successfully sent to {recipient}.",
        to=recipient,
        subject=subject,
    )


def gmail_send_message(
    to: str = "",
    subject: str = "",
    body: str = "",
    request: str = "",
) -> dict[str, Any]:
    """Send one email. A name is looked up. An address is not."""
    try:
        interpreted = _interpret(to, subject, body, request)
        if interpreted.get("clarify"):
            return _clarify(str(interpreted["clarify"]), interpreted.get("matches"))
        recipient = str(interpreted["to"])
        subject_text = str(interpreted["subject"])
        body_text = str(interpreted["body"]).strip()
        if not body_text:
            return _clarify("The message needs some text. Ask what to say.")
        if "@" in recipient:
            if not valid_email(recipient):
                return _clarify("That address is not valid. Ask for a corrected email address.")
        else:
            found = _match_contacts(recipient, _load_contacts())
            if not found:
                return _clarify(
                    f"I could not find a saved address for {recipient}. Ask for the email address."
                )
            if len(found) > 1:
                return _clarify(
                    f"{recipient} matches more than one contact. Ask which address to use.",
                    matches=found[:MAX_MATCHES],
                )
            recipient = found[0]["email"]
        if not subject_text:
            subject_text = _auto_subject(body_text)
        if _has_secret(subject_text) or _has_secret(body_text) or _has_secret(recipient):
            return _err("The message contains a saved secret. Remove it before sending.")
        return _deliver(recipient, subject_text, body_text)
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"gmail_send_message failed: {exc}")
