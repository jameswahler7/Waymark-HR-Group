"""
notifier.py — Waymark Cold Email Engine v2 (Phase 3)

Two notification channels for "real reply" events and operational alerts:

  1. Pushover  — primary, sub-5-minute phone push (paid $5 one-time iOS license)
  2. Email backup — sent to the +alerts suffix on Jamie's Workspace mailbox
                    via Gmail filter the user can configure to label these.

Spec reference: SECTION 9 + handoff checklist.

Both channels are best-effort. If Pushover isn't configured the engine still
runs — it just falls back to the email backup. The point of two channels is
that one of them lands within 5 minutes; we never block the engine on a
notification failure.
"""
from __future__ import annotations

import base64
import logging
import os
from email.mime.text import MIMEText
from typing import Optional

import requests

log = logging.getLogger(__name__)

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"

# Read from .env at module import. Empty string = not configured.
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "").strip()
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN", "").strip()
PUSHOVER_DEVICE = os.getenv("PUSHOVER_DEVICE", "").strip()  # optional, target one device

# Default backup-alert recipient. Spec SECTION 9 uses Gmail "+addressing".
BACKUP_ALERT_EMAIL = os.getenv(
    "WAYMARK_ALERT_EMAIL", "Jamie.wahler+alerts@waymarkhrgroup.com"
)


def pushover_enabled() -> bool:
    """True iff both Pushover user key and app token are present."""
    return bool(PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN)


def send_pushover(
    *,
    title: str,
    message: str,
    url: Optional[str] = None,
    priority: int = 0,
) -> bool:
    """Send a Pushover push. Returns True on confirmed delivery to Pushover.

    `priority`:
       0 = default, beeps and shows banner
       1 = high priority, bypasses Quiet Hours
       (we never use 2; that requires user acknowledgment)
    """
    if not pushover_enabled():
        log.warning("Pushover not configured (PUSHOVER_USER_KEY / PUSHOVER_API_TOKEN missing)")
        return False

    payload = {
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "title": title[:250],     # Pushover title cap
        "message": message[:1024],  # Pushover message cap
        "priority": priority,
    }
    if url:
        payload["url"] = url
        payload["url_title"] = "Open thread"
    if PUSHOVER_DEVICE:
        payload["device"] = PUSHOVER_DEVICE

    try:
        resp = requests.post(PUSHOVER_API_URL, data=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("status") == 1:
            log.info(f"Pushover delivered: {title}")
            return True
        log.error(f"Pushover rejected: {result}")
        return False
    except requests.RequestException as exc:
        log.error(f"Pushover request failed: {exc}")
        return False


def send_email_alert(
    service,
    *,
    subject: str,
    body: str,
    to_email: Optional[str] = None,
) -> bool:
    """Send a plain-text email alert via the Gmail API.

    Default recipient is BACKUP_ALERT_EMAIL (Jamie.wahler+alerts@...). The
    caller can override for the daily report (sent to the main mailbox).
    """
    to_addr = to_email or BACKUP_ALERT_EMAIL
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = to_addr
        msg["Subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        log.info(f"Email alert sent to {to_addr}: {subject}")
        return True
    except Exception as exc:
        log.error(f"Email alert failed ({to_addr}): {exc}")
        return False


def gmail_thread_url(thread_id: str) -> str:
    """Return the Gmail web URL for a thread (works on phone + desktop)."""
    return f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"
