#!/usr/bin/env python3
"""
reply_detector.py — Waymark Cold Email Engine v2 (Phase 3)

Polling-based reply detector. Designed to run from launchd every 2 minutes
so any real reply lands in Pushover within 5 minutes (spec target).

On every tick:
  1. Walk threads in 02_SENT_T1, 03_SENT_T2, 04_SENT_T3, 05_SENT_T4.
  2. For each thread, ask reply_classifier.classify_thread() what's there.
  3. Dispatch based on kind:
       'none'        -> ignore
       'real'        -> move to 06_REPLIED 🔥, Pushover + email backup
       'ooo'         -> log only, sequence continues
       'unsubscribe' -> add to do_not_contact, move to 00_DO_NOT_CONTACT, silent
       'bounce'      -> add to bounce_history, move to 10_CLOSED_LOST, silent
  4. Mark every processed message in replied_notifications so the next tick
     doesn't reprocess.

Spec reference: SECTION 9.

CLI:
  python3 reply_detector.py           # real run
  python3 reply_detector.py --dry-run # classify and log, no label moves, no notifications
  python3 reply_detector.py --once    # explicit single-pass (default behavior)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback

from dotenv import load_dotenv
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_THIS_DIR, ".env"))
load_dotenv(os.path.join(os.path.dirname(_THIS_DIR), ".env"))

from gmail_auth import get_gmail_service, get_sender_address
from db_v2 import (
    init_db, log_error, get_cached_enrichment,
    is_reply_notified, mark_reply_notified,
    add_do_not_contact, add_bounce, get_last_send_for_thread,
)
from label_manager import (
    LabelManager,
    LABEL_SENT_T1, LABEL_SENT_T2, LABEL_SENT_T3, LABEL_SENT_T4,
    LABEL_REPLIED, LABEL_DO_NOT_CONTACT, LABEL_CLOSED_LOST,
)
from reply_classifier import classify_thread, ReplyKind
from notifier import (
    send_pushover, send_email_alert, gmail_thread_url, pushover_enabled,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "waymark_engine.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "reply_detector.log")

ACTIVE_LABELS = [LABEL_SENT_T1, LABEL_SENT_T2, LABEL_SENT_T3, LABEL_SENT_T4]


def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run_detector(args: argparse.Namespace) -> int:
    log = logging.getLogger("detector")
    conn = init_db(DB_PATH)
    service = get_gmail_service(BASE_DIR)
    our_email = get_sender_address(service)
    if not our_email:
        log.error("Could not resolve our email address; aborting")
        return 1
    log.info(f"Authenticated mailbox: {our_email}")
    if not pushover_enabled():
        log.warning("Pushover not configured — falling back to email backup only")

    lm = LabelManager(service)
    lm.ensure_labels()

    counts = {"real": 0, "ooo": 0, "unsubscribe": 0, "bounce": 0, "none": 0, "skipped_dup": 0}

    for from_label in ACTIVE_LABELS:
        thread_ids = lm.get_threads_in_label(from_label)
        if thread_ids:
            log.info(f"Checking {len(thread_ids)} threads in {from_label}")
        for thread_id in thread_ids:
            try:
                _process_thread(args, log, conn, lm, service, our_email,
                                from_label, thread_id, counts)
            except Exception as exc:
                log.exception(f"Error processing thread {thread_id}: {exc}")
                log_error(conn, "error", thread_id, f"detector: {exc}")

    log.info(f"Detector complete: {counts}")
    conn.close()
    return 0


def _process_thread(
    args, log, conn, lm: LabelManager, service, our_email: str,
    from_label: str, thread_id: str, counts: dict,
) -> None:
    result = classify_thread(service, thread_id, our_email)

    if result.kind == "none":
        counts["none"] += 1
        return

    # Dedup: have we already handled this exact reply message?
    if result.message_id and is_reply_notified(conn, thread_id, result.message_id):
        counts["skipped_dup"] += 1
        return

    counts[result.kind] = counts.get(result.kind, 0) + 1
    log.info(
        f"Thread {thread_id}: {result.kind.upper()} from {result.from_address!r} "
        f"subj={result.subject!r}"
    )

    if result.kind == "ooo":
        # Don't move the label. Mark this specific message as processed so we
        # don't re-trigger on it next tick.
        if not args.dry_run and result.message_id:
            mark_reply_notified(conn, thread_id, result.message_id, kind="ooo")
        return

    if result.kind == "unsubscribe":
        last_send = get_last_send_for_thread(conn, thread_id)
        recipient = last_send["recipient_email"] if last_send else None
        if args.dry_run:
            log.info(
                f"DRY RUN: would silently DNC {recipient!r} and move {thread_id} "
                f"to {LABEL_DO_NOT_CONTACT}"
            )
        else:
            if recipient:
                add_do_not_contact(conn, recipient, "unsubscribe-reply")
            _safe_move(lm, thread_id, from_label, LABEL_DO_NOT_CONTACT, log)
            if result.message_id:
                mark_reply_notified(conn, thread_id, result.message_id, kind="unsubscribe")
        return

    if result.kind == "bounce":
        last_send = get_last_send_for_thread(conn, thread_id)
        recipient = last_send["recipient_email"] if last_send else None
        if args.dry_run:
            log.info(
                f"DRY RUN: would record bounce for {recipient!r} and move {thread_id} "
                f"to {LABEL_CLOSED_LOST}"
            )
        else:
            if recipient:
                add_bounce(conn, recipient, "hard")
            _safe_move(lm, thread_id, from_label, LABEL_CLOSED_LOST, log)
            if result.message_id:
                mark_reply_notified(conn, thread_id, result.message_id, kind="bounce")
        return

    if result.kind == "real":
        enrichment = get_cached_enrichment(conn, thread_id) or {}
        company = enrichment.get("company_name") or "(unknown company)"
        first_name = enrichment.get("first_name") or ""

        if args.dry_run:
            log.info(
                f"DRY RUN: would move {thread_id} to {LABEL_REPLIED} and notify "
                f"({company} / {first_name})"
            )
            return

        # Cancel sequence: move to 06_REPLIED first so the orchestrator
        # never re-considers this thread for a follow-up.
        _safe_move(lm, thread_id, from_label, LABEL_REPLIED, log)

        _notify_real_reply(
            service=service,
            thread_id=thread_id,
            company=company,
            first_name=first_name,
            from_address=result.from_address or "",
            body_excerpt=result.body_excerpt or "",
            log=log,
        )

        if result.message_id:
            mark_reply_notified(conn, thread_id, result.message_id, kind="real")


def _notify_real_reply(
    *, service, thread_id: str, company: str, first_name: str,
    from_address: str, body_excerpt: str, log,
) -> None:
    title = f"🔥 REPLY: {company} — {first_name}".strip()
    url = gmail_thread_url(thread_id)

    # Pushover: short excerpt is enough for the lock-screen banner.
    short = body_excerpt.strip()[:400]
    if short:
        push_message = short
    else:
        push_message = f"Reply received from {from_address}"
    send_pushover(title=title, message=push_message, url=url, priority=1)

    # Backup email: full excerpt + thread link.
    email_body = (
        f"From: {from_address}\n"
        f"Thread: {url}\n\n"
        f"--- Reply excerpt ---\n"
        f"{body_excerpt.strip()}\n"
    )
    send_email_alert(service, subject=title, body=email_body)
    log.info(f"Notifications dispatched for {thread_id}")


def _safe_move(lm: LabelManager, thread_id: str, from_label, to_label, log) -> None:
    try:
        lm.move_thread(thread_id, from_label, to_label)
    except Exception as exc:
        log.error(f"Move {from_label} -> {to_label} on {thread_id}: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Waymark Reply Detector (Phase 3)")
    p.add_argument("--dry-run", action="store_true",
                   help="Classify and log, but do not move labels or notify")
    p.add_argument("--once", action="store_true",
                   help="(Default) one-pass classification; cron handles cadence")
    return p.parse_args()


def main() -> int:
    setup_logging()
    try:
        return run_detector(parse_args())
    except Exception as exc:
        logging.getLogger("detector").exception(f"Fatal: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
