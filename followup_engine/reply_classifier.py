"""
reply_classifier.py — Waymark Cold Email Engine v2 (Phase 3)

Walk a Gmail thread and classify the most recent inbound message as one of:

  'none'         no inbound message present (we only sent, no reply yet)
  'real'         genuine human reply — engine pauses sequence + notifies
  'ooo'          out-of-office / auto-reply — engine ignores, continues sending
  'unsubscribe'  unsubscribe / opt-out / hostile — silent DNC move
  'bounce'       mailer-daemon / delivery failure — record bounce + skip thread

Spec reference: SECTION 9.

Used by both:
  - reply_detector.py (polling cron, runs every 2 min)
  - followup_engine.py (orchestrator safety check before each T2/T3/T4 send)
"""
from __future__ import annotations

import base64
import logging
import re
from typing import NamedTuple, Optional

log = logging.getLogger(__name__)

# ----- OOO patterns (spec SECTION 9) ---------------------------------------
# Compiled with IGNORECASE + DOTALL so multi-line autoreplies match.
_OOO_PATTERNS = [
    r"\bout of office\b",
    r"\booo\b",
    r"\bout of the office\b",
    r"\baway from the office\b",
    r"\bautomatic reply\b",
    r"\bauto-?\s?reply\b",
    r"\bthis is an automated\b",
    r"\bi am currently away\b",
    r"\bi'?m currently away\b",
    r"\bcurrently out\b",
    r"\bwill return on\b",
    r"\bwill be back on\b",
    r"\bback in the office on\b",
    r"for immediate assistance.{0,80}?please contact",
    r"\bi am out\b.{0,40}?\d",          # "I am out (date)"
    r"\bi'?m out\b.{0,40}?\d",
    r"thank you for your (email|message).{0,80}?(will respond|will reply|will be back|out of)",
]
_OOO_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _OOO_PATTERNS]

# ----- Unsubscribe patterns ------------------------------------------------
# Plain unsubscribe keywords — case-insensitive substring match.
_UNSUB_PLAIN = [
    "unsubscribe",
    "remove me",
    "take me off",
    "stop emailing",
    "do not contact",
    "do not email",
    "please stop",
    "leave me alone",
]
# Hostile shutdowns — spec calls these out explicitly.
_UNSUB_HOSTILE = [
    "fuck off",
    "f*** off",
    "f off",
]
# "Not interested" only counts as unsubscribe with strong language nearby
# (per spec). For now we treat "not interested" plus a hostile word as unsub,
# and bare "not interested" as a real reply (Jamie answers gracefully).
_NOT_INTERESTED_HOSTILE_PAIR = re.compile(
    r"not interested.{0,80}?(stop|leave|never|don'?t)|(stop|leave|never|don'?t).{0,80}?not interested",
    re.IGNORECASE | re.DOTALL,
)

# ----- Bounce indicators ---------------------------------------------------
# Mail providers tag bounces in the From header. We check From first; if
# that matches, body parsing isn't strictly required.
_BOUNCE_FROM_TOKENS = [
    "mailer-daemon",
    "postmaster@",
    "mail delivery subsystem",
    "delivery status notification",
    "delivery failure",
    "mail.protection.outlook.com",  # M365 NDR sender
]


class ReplyKind(NamedTuple):
    kind: str                      # 'none' | 'real' | 'ooo' | 'unsubscribe' | 'bounce'
    message_id: Optional[str]      # Gmail message ID of the inbound message
    from_address: Optional[str]    # raw From header
    subject: Optional[str]         # raw Subject header
    body_excerpt: Optional[str]    # first 1KB of plain text body


def classify_thread(service, thread_id: str, our_email: str) -> ReplyKind:
    """Classify the most recent inbound (non-our) message on the thread.

    If the thread has no inbound message at all, returns kind='none'.
    """
    our_norm = (our_email or "").strip().lower()
    if not our_norm:
        log.warning("classify_thread called without our_email")
        return ReplyKind("none", None, None, None, None)

    try:
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
    except Exception as exc:
        log.warning(f"Could not fetch thread {thread_id}: {exc}")
        return ReplyKind("none", None, None, None, None)

    messages = thread.get("messages", [])
    inbound_msg = None
    # Walk newest-first; first non-our message wins.
    for msg in reversed(messages):
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        from_addr = (headers.get("from") or "").lower()
        if our_norm not in from_addr:
            inbound_msg = msg
            break

    if not inbound_msg:
        return ReplyKind("none", None, None, None, None)

    headers = {
        h["name"].lower(): h["value"]
        for h in inbound_msg.get("payload", {}).get("headers", [])
    }
    msg_id = inbound_msg.get("id")
    from_addr = headers.get("from") or ""
    subject = headers.get("subject") or ""
    body = _extract_plaintext(inbound_msg.get("payload", {}))

    # 1. Bounce check (From header is the strongest signal)
    from_lower = from_addr.lower()
    if any(token in from_lower for token in _BOUNCE_FROM_TOKENS):
        return ReplyKind("bounce", msg_id, from_addr, subject, body[:1024])

    # 2. OOO check — scan subject + body
    subj_lower = subject.lower()
    body_lower = body.lower()
    for pat in _OOO_RE:
        if pat.search(subj_lower) or pat.search(body_lower):
            return ReplyKind("ooo", msg_id, from_addr, subject, body[:1024])

    # 3. Unsubscribe check
    for phrase in _UNSUB_PLAIN:
        if phrase in body_lower or phrase in subj_lower:
            return ReplyKind("unsubscribe", msg_id, from_addr, subject, body[:1024])
    for phrase in _UNSUB_HOSTILE:
        if phrase in body_lower or phrase in subj_lower:
            return ReplyKind("unsubscribe", msg_id, from_addr, subject, body[:1024])
    if _NOT_INTERESTED_HOSTILE_PAIR.search(body_lower):
        return ReplyKind("unsubscribe", msg_id, from_addr, subject, body[:1024])

    # 4. Everything else = real reply
    return ReplyKind("real", msg_id, from_addr, subject, body[:1024])


# ---------------------------------------------------------------------------
# Body extraction (mirrors intake_parser._extract_plaintext_body)
# ---------------------------------------------------------------------------

def _extract_plaintext(payload: dict) -> str:
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _extract_plaintext(part)
        if text:
            return text
    if payload.get("body", {}).get("data") and not payload.get("parts"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    return ""
