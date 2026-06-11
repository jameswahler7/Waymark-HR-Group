"""
intake_parser.py — Waymark Cold Email Engine v2

Parses the 3-line Gmail draft format documented in SECTION 5 of the spec:

    To:  bob@buffaloplumbing.com
    Body:
      Bob
      https://buffaloplumbing.com
      (optional notes for Jamie's own reference, ignored by engine)

Validation rules (spec SECTION 5):
  * To: address must be present and look like an email
  * Recipient domain may NOT be a consumer mailbox (gmail/yahoo/etc.)
  * First body line must be a clean first name (alphabetic, 1-20 chars,
    may include hyphens or apostrophes)
  * Second body line must be an http(s) URL
  * Email must not be in do_not_contact or bounce_history

A `--test-mode` flag (handled by the orchestrator) bypasses the consumer-
domain blocklist so Jamie can test against his own personal address.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlparse

CONSUMER_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "aol.com", "icloud.com", "me.com", "mac.com",
    "live.com", "msn.com", "comcast.net", "verizon.net", "att.net",
    "googlemail.com", "ymail.com", "protonmail.com", "proton.me",
}

# Permissive but real email validation. RFC 5322 is overkill for outbound.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# First name: 1-20 letters, may include hyphens or apostrophes.
FIRST_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{0,19}$")


class ValidationError(Exception):
    """Raised when an intake draft fails any validation rule."""


@dataclass
class Lead:
    email: str
    first_name: str
    company_url: str
    thread_id: str
    message_id: str
    draft_id: Optional[str]
    notes: str  # everything from body line 3 onward (engine ignores, kept for Jamie)

    @property
    def company_domain(self) -> str:
        return _bare_domain(self.company_url)


# ---------------------------------------------------------------------------
# Header / body extraction from a Gmail format=full message
# ---------------------------------------------------------------------------

def _get_header(msg: dict, name: str) -> str:
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return (h.get("value") or "").strip()
    return ""


def _extract_plaintext_body(payload: dict) -> str:
    """Walk Gmail's payload tree and return the first text/plain body."""
    if not payload:
        return ""

    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []) or []:
        text = _extract_plaintext_body(part)
        if text:
            return text

    # Last resort: a single-part text/plain message stores body at root.
    if payload.get("body", {}).get("data") and not payload.get("parts"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    return ""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _split_to_field(to_header: str) -> str:
    """Pull a clean email address out of a To header like 'Bob <bob@x.com>'."""
    to_header = to_header.strip()
    if "<" in to_header and ">" in to_header:
        return to_header.split("<", 1)[1].rsplit(">", 1)[0].strip()
    return to_header


def _bare_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if url.startswith(("http://", "https://")) else f"https://{url}")
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _validate_email(addr: str, allow_consumer: bool) -> None:
    if not addr:
        raise ValidationError("To address is missing")
    if not EMAIL_RE.match(addr):
        raise ValidationError(f"To address looks malformed: {addr!r}")
    domain = addr.split("@", 1)[1].lower()
    if not allow_consumer and domain in CONSUMER_DOMAINS:
        raise ValidationError(
            f"Recipient domain {domain!r} is a consumer mailbox — not a business prospect"
        )


def _validate_first_name(name: str) -> None:
    if not name:
        raise ValidationError("First name (body line 1) is missing")
    if not FIRST_NAME_RE.match(name):
        raise ValidationError(
            f"First name {name!r} must be 1-20 alphabetic characters (hyphens/apostrophes OK)"
        )


def _validate_company_url(url: str) -> None:
    if not url:
        raise ValidationError("Company URL (body line 2) is missing")
    if not url.startswith(("http://", "https://")):
        raise ValidationError(f"Company URL must start with http:// or https://, got {url!r}")
    if "." not in _bare_domain(url):
        raise ValidationError(f"Company URL {url!r} has no valid domain")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_queued_draft(
    draft: dict,
    *,
    is_blocked_fn=lambda addr: None,
    allow_consumer: bool = False,
) -> Lead:
    """Parse a queued draft into a validated Lead.

    Args:
        draft: dict from LabelManager.get_queued_drafts() — contains the full
               format=full message under draft["raw_message"].
        is_blocked_fn: callable that takes an email address and returns a
                       reason string if blocked (DNC / bounce) or None.
        allow_consumer: if True, skip the consumer-domain blocklist. Used
                        for --test-mode runs only.

    Raises:
        ValidationError on any failure. The orchestrator catches this and
        moves the thread to the INVALID_INPUT label.
    """
    msg = draft["raw_message"]

    # 1. Recipient from To header
    to_header = _get_header(msg, "To")
    recipient = _split_to_field(to_header)
    _validate_email(recipient, allow_consumer=allow_consumer)

    # 2. Body extraction
    body_text = _extract_plaintext_body(msg.get("payload", {}))
    if not body_text.strip():
        raise ValidationError("Draft body is empty — expected 3-line format")

    # Normalize line endings and strip empty leading lines.
    lines = [ln.strip() for ln in body_text.replace("\r\n", "\n").split("\n")]
    # Drop leading blank lines (Gmail composers sometimes add them).
    while lines and not lines[0]:
        lines.pop(0)

    if len(lines) < 2:
        raise ValidationError(
            "Draft body must have at least 2 lines: first name on line 1, URL on line 2"
        )

    first_name = lines[0]
    company_url = lines[1]
    notes = "\n".join(lines[2:]).strip()

    _validate_first_name(first_name)
    _validate_company_url(company_url)

    # 3. DNC / bounce check
    block_reason = is_blocked_fn(recipient)
    if block_reason:
        raise ValidationError(f"Recipient is blocked: {block_reason}")

    return Lead(
        email=recipient,
        first_name=first_name,
        company_url=company_url,
        thread_id=draft["thread_id"],
        message_id=draft["message_id"],
        draft_id=draft.get("draft_id"),
        notes=notes,
    )
