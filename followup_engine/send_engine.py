"""
send_engine.py — Waymark Cold Email Engine v2

Pacing rules + the actual Gmail send.

Pacing constraints (spec SECTION 3):
  * Daily cap: 25 sends across ALL touches (T1+T2+T3+T4 share the cap)
  * Send window: 9:00 AM - 4:30 PM Eastern, Mon-Fri
  * No US federal holidays + Thanksgiving/Christmas adjacencies
  * 12-28 min randomized gap between sends
  * Never more than 4 sends in any rolling 60-minute window

Phase 1 only sends T1. T1 uses Gmail's drafts.send (the lead arrived as a
draft, so we just send the existing draft — preserves the To: address and
gives Jamie the original draft body for reference if needed).

For T2-T4 (Phase 2), we will use messages.send with In-Reply-To +
References headers to nest replies on the same thread. That code is NOT
in this file yet.
"""
from __future__ import annotations

import base64
import logging
import random
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Optional, Tuple

from db_v2 import count_sends_since, is_holiday, last_send_at

log = logging.getLogger(__name__)

# Spec constants
DAILY_CAP = 25
HOURLY_BURST_CAP = 4
GAP_MIN_SEC = 12 * 60
GAP_MAX_SEC = 28 * 60
SEND_WINDOW_START = (9, 0)    # 9:00 AM ET
SEND_WINDOW_END = (16, 30)    # 4:30 PM ET

# Eastern time without pulling in pytz: use timezone.offset for EST/EDT.
# US DST: second Sunday of March to first Sunday of November.
# This is good enough for send-window enforcement (we are not scheduling
# down to the second).


def _now_eastern() -> datetime:
    """Return current time as a naive datetime in US Eastern (DST-aware)."""
    now_utc = datetime.now(timezone.utc)
    return _to_eastern(now_utc)


def _to_eastern(dt_utc: datetime) -> datetime:
    """Convert UTC datetime to naive US Eastern."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    # Determine DST: roughly 2nd Sun of March -> 1st Sun of Nov, 2 AM local.
    year = dt_utc.year
    # 2nd Sunday of March
    march = datetime(year, 3, 1, tzinfo=timezone.utc)
    while march.weekday() != 6:  # 6 = Sunday
        march += timedelta(days=1)
    dst_start_utc = march + timedelta(days=7, hours=7)  # 2 AM EST = 7 UTC
    # 1st Sunday of November
    nov = datetime(year, 11, 1, tzinfo=timezone.utc)
    while nov.weekday() != 6:
        nov += timedelta(days=1)
    dst_end_utc = nov + timedelta(hours=6)  # 2 AM EDT = 6 UTC
    offset_hours = -4 if dst_start_utc <= dt_utc < dst_end_utc else -5
    eastern = dt_utc + timedelta(hours=offset_hours)
    return eastern.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Pacing check
# ---------------------------------------------------------------------------

def can_send_now(
    conn,
    *,
    ignore_pacing: bool = False,
) -> Tuple[bool, str]:
    """Return (allowed, reason). reason is human-readable.

    When ignore_pacing is True we skip every check EXCEPT the absolute safety
    rails (daily cap and the bounce/DNC checks, which run elsewhere). This
    is for --test-mode dry runs only.
    """
    now_et = _now_eastern()

    # Daily cap — never bypassed, even in test mode.
    today_start_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc_iso = (today_start_et + timedelta(hours=4)).replace(
        tzinfo=None
    ).isoformat()
    sends_today = count_sends_since(conn, today_start_utc_iso)
    if sends_today >= DAILY_CAP:
        return False, f"daily cap reached ({sends_today}/{DAILY_CAP})"

    if ignore_pacing:
        return True, "ignore_pacing=true (test mode)"

    # Day-of-week
    if now_et.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False, f"weekend ({now_et.strftime('%A')})"

    # Holiday
    holiday = is_holiday(conn, now_et.strftime("%Y-%m-%d"))
    if holiday:
        return False, f"holiday: {holiday}"

    # Send window
    start_h, start_m = SEND_WINDOW_START
    end_h, end_m = SEND_WINDOW_END
    window_start = now_et.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    window_end = now_et.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    if not (window_start <= now_et <= window_end):
        return False, (
            f"outside send window 9:00 AM - 4:30 PM ET (currently {now_et.strftime('%H:%M')} ET)"
        )

    # 60-min burst cap
    hour_ago_utc_iso = (datetime.utcnow() - timedelta(minutes=60)).isoformat()
    sends_last_hour = count_sends_since(conn, hour_ago_utc_iso)
    if sends_last_hour >= HOURLY_BURST_CAP:
        return False, f"rolling 60-min burst cap reached ({sends_last_hour}/{HOURLY_BURST_CAP})"

    # 12-28 min gap
    last_dt = last_send_at(conn)
    if last_dt is not None:
        seconds_since_last = (datetime.utcnow() - last_dt).total_seconds()
        # We pick a fresh per-tick random threshold so this isn't deterministic.
        threshold = random.randint(GAP_MIN_SEC, GAP_MAX_SEC)
        if seconds_since_last < threshold:
            need = int(threshold - seconds_since_last)
            return False, (
                f"gap-since-last {int(seconds_since_last)}s < threshold {threshold}s "
                f"(need ~{need}s more)"
            )

    return True, "ok"


# ---------------------------------------------------------------------------
# Send mechanics
# ---------------------------------------------------------------------------

def _build_raw_message(
    *,
    to_email: str,
    from_email: str,
    from_name: str,
    subject: str,
    body: str,
) -> str:
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_email
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["Subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")


def send_t1_via_new_message(
    service,
    *,
    to_email: str,
    from_email: str,
    from_name: str,
    subject: str,
    body: str,
) -> Tuple[str, str]:
    """Send a brand-new T1 message via users.messages.send.

    Returns (message_id, thread_id). We use messages.send (not drafts.send)
    because the drafts that Jamie created with the 3-line format have the
    raw "Bob\\nhttps://...\\nnotes" as the BODY -- that is intake data, not
    the actual email we want to send. We replace it with the generated
    Hormozi-grade body.

    After sending, the orchestrator deletes the original intake draft so it
    doesn't clutter Jamie's drafts folder.
    """
    raw = _build_raw_message(
        to_email=to_email,
        from_email=from_email,
        from_name=from_name,
        subject=subject,
        body=body,
    )
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )
    return sent["id"], sent["threadId"]


def get_thread_metadata(service, thread_id: str, our_email: str) -> dict:
    """Pull metadata needed to build a properly-threaded reply.

    Returns a dict with:
      - 'first_subject':  the Subject of the first message in the thread
                          (used to construct "re: {original subject}" for T2)
      - 'last_outbound_message_id':  the RFC822 Message-Id header of the most
                          recent message we sent in this thread (used for
                          In-Reply-To header on the next follow-up)
      - 'references_chain': space-separated chain of all Message-Id headers
                          in the thread, in order (used for References header)
      - 'recipient':  the To: address from our most recent outbound (so we
                          send the follow-up to the same person)

    Required so T2/T3/T4 nest correctly under the existing Gmail thread.
    """
    our_norm = our_email.strip().lower()
    thread = (
        service.users()
        .threads()
        .get(
            userId="me",
            id=thread_id,
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Message-ID", "References"],
        )
        .execute()
    )

    messages = thread.get("messages", [])
    first_subject = ""
    references_chain_parts = []
    last_outbound_msg_id = None
    recipient = ""

    for i, msg in enumerate(messages):
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        msg_id_header = headers.get("message-id", "")
        if msg_id_header:
            references_chain_parts.append(msg_id_header)
        if i == 0:
            first_subject = headers.get("subject", "")
        from_addr = (headers.get("from") or "").lower()
        if our_norm in from_addr:
            if msg_id_header:
                last_outbound_msg_id = msg_id_header
            to_hdr = headers.get("to", "")
            # If the To header has "Name <email>" form, extract email.
            if "<" in to_hdr and ">" in to_hdr:
                recipient = to_hdr.split("<", 1)[1].rsplit(">", 1)[0].strip()
            elif to_hdr:
                recipient = to_hdr.strip()

    return {
        "first_subject": first_subject,
        "last_outbound_message_id": last_outbound_msg_id,
        "references_chain": " ".join(references_chain_parts),
        "recipient": recipient,
    }


def send_followup_reply(
    service,
    *,
    thread_id: str,
    to_email: str,
    from_email: str,
    from_name: str,
    subject: str,
    body: str,
    in_reply_to: Optional[str],
    references: Optional[str],
) -> Tuple[str, str]:
    """Send a reply message nested onto an existing Gmail thread.

    Uses users.messages.send with `threadId` set so the message lands in
    the same thread as T1. Sets In-Reply-To and References headers so the
    message also chains correctly client-side at the recipient.

    Returns (gmail_message_id, gmail_thread_id).
    """
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_email
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": thread_id})
        .execute()
    )
    return sent["id"], sent["threadId"]


def delete_intake_draft(service, draft_id: Optional[str]) -> None:
    """Best-effort delete of the original 01_QUEUED intake draft."""
    if not draft_id:
        return
    try:
        service.users().drafts().delete(userId="me", id=draft_id).execute()
    except Exception as exc:
        log.warning(f"Failed to delete intake draft {draft_id}: {exc}")


# ---------------------------------------------------------------------------
# Eastern-time helpers exported for the orchestrator's logging
# ---------------------------------------------------------------------------

def now_eastern_str() -> str:
    return _now_eastern().strftime("%Y-%m-%d %H:%M ET")
