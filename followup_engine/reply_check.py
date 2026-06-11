"""
reply_check.py — Waymark Cold Email Engine v2 (Phase 2 minimal version)

A lightweight "did this thread get an inbound message?" detector for the
follow-up engine. Phase 3 will replace this with the full polling loop
+ OOO filter + Pushover notification described in spec SECTION 9.

For Phase 2 we are conservative: ANY message in the thread from someone
other than Jamie's sending address counts as a reply. That includes OOO
autoreplies, bounces, and "Thanks!" — anything inbound pauses the
sequence. The worst case is a one-off false positive where Jamie has to
manually move the thread out of 06_REPLIED back to its prior state.
That is the right error to make in Phase 2; sending a follow-up over
a real reply is the wrong one.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


def thread_has_inbound(service, thread_id: str, our_email: str) -> bool:
    """Return True if any message in the thread is from someone other than us.

    `our_email` is the authenticated sending mailbox. We match
    case-insensitively against the From header. If we can't read the
    thread at all (deleted, permissions error) we err on the side of
    caution and return True so the engine pauses on it.
    """
    our_norm = our_email.strip().lower()
    if not our_norm:
        log.warning("reply_check called without our_email; pausing thread for safety")
        return True

    try:
        thread = (
            service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["From"],
            )
            .execute()
        )
    except Exception as exc:
        log.warning(f"Could not fetch thread {thread_id} for reply check: {exc}")
        return True

    for msg in thread.get("messages", []):
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        from_addr = (headers.get("from") or "").lower()
        if our_norm not in from_addr:
            return True
    return False
