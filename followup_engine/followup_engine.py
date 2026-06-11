#!/usr/bin/env python3
"""
followup_engine.py — Waymark Cold Email Engine v2 — Phase 1 + Phase 2

Phase 1 (live, tested 2026-06-10):
  - Intake parser (3-line Gmail draft format)
  - Auto-enrichment via Anthropic web_search
  - Auto-angle picker (HIRING vs COMPLIANCE)
  - Touch 1 email generator using WAYMARK_COLD_EMAIL_SKILL.md
  - Gmail 11-label state machine
  - Send pacing
  - SQLite operational DB

Phase 2 (this build):
  - Touch 2 generator (+3 biz days, primary angle reinforced, primary URL)
  - Touch 3 generator (+5 biz days from T2, PIVOT to secondary, secondary URL)
  - Touch 4 generator (+4 biz days from T3, breakup)
  - Business-day eligibility calculator (respects holiday_calendar)
  - Send-order priority: T4 -> T3 -> T2 -> T1 (warm threads finish first)
  - Threaded replies (In-Reply-To + References headers, threadId nesting)
  - Minimal reply-pause safeguard: any inbound message on a sent thread
    moves it to 06_REPLIED 🔥 instead of firing the next touch

Not in Phase 2 (Phase 3-4):
  - Full polling-based reply detection + OOO filter
  - Pushover notifications
  - Daily report email
  - Bounce monitoring

CLI:
  python3 followup_engine.py                  # send up to 1 lead, real send, with pacing
  python3 followup_engine.py --dry-run        # generate but do NOT send/label
  python3 followup_engine.py --limit 3        # send up to 3 leads this run
  python3 followup_engine.py --ignore-pacing  # bypass pacing (testing only — still respects daily cap)
  python3 followup_engine.py --test-mode      # allow consumer domains as recipients
  python3 followup_engine.py --list-only      # print queued + eligible follow-ups
  python3 followup_engine.py --only-touch 1   # only process T1 sends this run (or 2/3/4)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import datetime
from typing import List, Optional, Tuple

# Load .env BEFORE importing modules that instantiate the Anthropic client.
from dotenv import load_dotenv
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_THIS_DIR, ".env"))
load_dotenv(os.path.join(os.path.dirname(_THIS_DIR), ".env"))

# Local modules
from gmail_auth import get_gmail_service, get_sender_address
from db_v2 import (
    init_db, cache_enrichment, get_cached_enrichment, log_send, log_error,
    already_sent, is_blocked, get_last_send_for_thread,
    add_do_not_contact, add_bounce,
    is_reply_notified, mark_reply_notified,
)
from label_manager import (
    LabelManager,
    LABEL_QUEUED, LABEL_SENT_T1, LABEL_SENT_T2, LABEL_SENT_T3, LABEL_SENT_T4,
    LABEL_REPLIED, LABEL_INVALID, LABEL_ENRICH_FAILED, LABEL_GEN_FAILED,
    LABEL_DO_NOT_CONTACT, LABEL_CLOSED_LOST,
)
from intake_parser import parse_queued_draft, ValidationError
from enrichment import enrich_lead, EnrichmentError
from email_generator import (
    generate_t1, generate_t2, generate_t3, generate_t4, GenerationError,
)
from send_engine import (
    can_send_now, send_t1_via_new_message, send_followup_reply,
    get_thread_metadata, delete_intake_draft, now_eastern_str, _now_eastern,
)
from business_day_calc import is_eligible
from reply_classifier import classify_thread
from notifier import (
    send_pushover, send_email_alert, gmail_thread_url, pushover_enabled,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "waymark_engine.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "waymark_engine.log")
SKILL_FILE = os.path.join(PROJECT_ROOT, "WAYMARK_COLD_EMAIL_SKILL.md")

# Spec SECTION 5
SENDER_EMAIL = "Jamie.wahler@waymarkhrgroup.com"
SENDER_NAME = "Jamie Wahler"

# Spec SECTION 2 — business-day eligibility windows.
T2_BIZ_DAYS = 3
T3_BIZ_DAYS = 5
T4_BIZ_DAYS = 4


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

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
# Orchestrator
# ---------------------------------------------------------------------------

def run_engine(args: argparse.Namespace) -> int:
    log = logging.getLogger("orchestrator")

    if not os.path.exists(SKILL_FILE):
        log.error(f"Skill file not found: {SKILL_FILE}")
        return 2

    log.info(f"Waymark Engine v2 (Phases 1+2) starting at {now_eastern_str()}")
    log.info(
        f"Args: dry_run={args.dry_run} limit={args.limit} "
        f"ignore_pacing={args.ignore_pacing} test_mode={args.test_mode} "
        f"list_only={args.list_only} only_touch={args.only_touch}"
    )

    conn = init_db(DB_PATH)
    service = get_gmail_service(BASE_DIR)
    auth_addr = get_sender_address(service)
    log.info(f"Authenticated mailbox: {auth_addr}")
    if auth_addr.lower() != SENDER_EMAIL.lower():
        log.warning(
            f"Mailbox {auth_addr!r} != expected {SENDER_EMAIL!r}. "
            "Sends will go from the authenticated address."
        )

    lm = LabelManager(service)
    lm.ensure_labels()

    # Build the eligible work list across all four touches, in priority order:
    #   T4 (breakups) -> T3 (pivots) -> T2 (follow-ups) -> T1 (cold opens)
    work = _build_work_list(args, log, conn, lm, service, auth_addr)
    log.info(
        "Eligible: "
        + ", ".join(f"T{t}={len([w for w in work if w[0]==t])}" for t in (4, 3, 2, 1))
    )

    if args.list_only:
        for touch, thread_id, _ in work:
            print(f"  T{touch}  thread={thread_id}")
        conn.close()
        return 0

    sent_count = 0
    for touch_number, thread_id, payload in work:
        if sent_count >= args.limit:
            log.info(f"Reached --limit {args.limit}; stopping for this run.")
            break

        allowed, reason = can_send_now(conn, ignore_pacing=args.ignore_pacing)
        if not allowed:
            log.info(f"Pacing block: {reason}. Exiting this tick.")
            break

        if _try_process_one(args, log, conn, lm, service, auth_addr,
                            touch_number, thread_id, payload):
            sent_count += 1

    log.info(f"Run complete. Sends this run: {sent_count}")
    conn.close()
    return 0


# ---------------------------------------------------------------------------
# Work-list assembly
# ---------------------------------------------------------------------------

def _build_work_list(
    args, log, conn, lm: LabelManager, service, our_email: str,
) -> List[Tuple[int, str, dict]]:
    """Return a list of (touch_number, thread_id, payload) sorted by spec priority.

    payload contains everything _try_process_one needs to fire that touch
    without re-querying. For T1 the payload is the draft dict; for T2-T4
    it carries the cached enrichment + thread metadata.
    """
    now_et = _now_eastern()
    work: List[Tuple[int, str, dict]] = []

    # ---- T4 (breakups) ----
    if args.only_touch in (None, 4):
        for thread_id in lm.get_threads_in_label(LABEL_SENT_T3):
            payload = _followup_payload(
                conn, service, thread_id, prev_touch=3, n_biz_days=T4_BIZ_DAYS,
                our_email=our_email, now_et=now_et, log=log,
            )
            if payload:
                work.append((4, thread_id, payload))

    # ---- T3 (pivots) ----
    if args.only_touch in (None, 3):
        for thread_id in lm.get_threads_in_label(LABEL_SENT_T2):
            payload = _followup_payload(
                conn, service, thread_id, prev_touch=2, n_biz_days=T3_BIZ_DAYS,
                our_email=our_email, now_et=now_et, log=log,
            )
            if payload:
                work.append((3, thread_id, payload))

    # ---- T2 (first follow-ups) ----
    if args.only_touch in (None, 2):
        for thread_id in lm.get_threads_in_label(LABEL_SENT_T1):
            payload = _followup_payload(
                conn, service, thread_id, prev_touch=1, n_biz_days=T2_BIZ_DAYS,
                our_email=our_email, now_et=now_et, log=log,
            )
            if payload:
                work.append((2, thread_id, payload))

    # ---- T1 (new cold opens, from 01_QUEUED draft folder) ----
    if args.only_touch in (None, 1):
        queued = lm.get_queued_drafts()
        for draft in queued:
            work.append((1, draft["thread_id"], {"draft": draft}))

    return work


def _followup_payload(
    conn, service, thread_id: str,
    *, prev_touch: int, n_biz_days: int, our_email: str, now_et, log,
) -> Optional[dict]:
    """Decide whether `thread_id` is eligible for the next touch.

    Returns a payload dict if eligible, else None.
    """
    last = get_last_send_for_thread(conn, thread_id)
    if not last:
        log.warning(
            f"Thread {thread_id} is in SENT_T{prev_touch} label but has no send_log row. "
            "Skipping (manual investigation needed)."
        )
        return None
    if last["touch_number"] != prev_touch:
        log.warning(
            f"Thread {thread_id} label says SENT_T{prev_touch} but send_log says "
            f"last touch was T{last['touch_number']}. Skipping."
        )
        return None

    sent_at = datetime.fromisoformat(last["sent_at"])
    if not is_eligible(conn, sent_at, n_biz_days, now_et):
        return None

    enrichment = get_cached_enrichment(conn, thread_id)
    if not enrichment:
        log.warning(
            f"Thread {thread_id} eligible but no cached enrichment. Skipping."
        )
        return None

    return {
        "enrichment": enrichment,
        "last_send": last,
    }


# ---------------------------------------------------------------------------
# Per-thread processing
# ---------------------------------------------------------------------------

def _try_process_one(
    args, log, conn, lm: LabelManager, service, our_email: str,
    touch_number: int, thread_id: str, payload: dict,
) -> bool:
    """Process one touch end-to-end. Returns True if a send was made."""
    if touch_number == 1:
        return _process_t1(args, log, conn, lm, service, payload["draft"])
    else:
        return _process_followup(
            args, log, conn, lm, service, our_email,
            touch_number, thread_id, payload,
        )


# ---- T1 -------------------------------------------------------------------

def _process_t1(args, log, conn, lm, service, draft) -> bool:
    thread_id = draft["thread_id"]
    draft_id = draft.get("draft_id")

    if already_sent(conn, thread_id, 1):
        log.warning(f"Thread {thread_id} already has T1. Fixing label only.")
        _safe_move(lm, thread_id, LABEL_QUEUED, LABEL_SENT_T1, log)
        return False

    try:
        lead = parse_queued_draft(
            draft,
            is_blocked_fn=lambda addr: is_blocked(conn, addr),
            allow_consumer=args.test_mode,
        )
    except ValidationError as exc:
        log.warning(f"INVALID input on thread {thread_id}: {exc}")
        log_error(conn, "warning", thread_id, f"intake: {exc}")
        if not args.dry_run:
            _safe_move(lm, thread_id, LABEL_QUEUED, LABEL_INVALID, log)
        return False

    log.info(f"T1 parsed: {lead.first_name} <{lead.email}> {lead.company_url}")

    try:
        enrichment = enrich_lead(lead)
    except EnrichmentError as exc:
        log.error(f"ENRICHMENT_FAILED on thread {thread_id}: {exc}")
        log_error(conn, "error", thread_id, f"enrichment: {exc}")
        if not args.dry_run:
            _safe_move(lm, thread_id, LABEL_QUEUED, LABEL_ENRICH_FAILED, log)
        return False

    log.info(
        f"Enriched: angle={enrichment.get('primary_angle')} "
        f"anchor={(enrichment.get('best_anchor') or '')[:120]!r}"
    )

    try:
        email = generate_t1(enrichment, SKILL_FILE)
    except GenerationError as exc:
        log.error(f"T1 GENERATION_FAILED on thread {thread_id}: {exc}")
        log_error(conn, "error", thread_id, f"t1 generation: {exc}")
        if not args.dry_run:
            _safe_move(lm, thread_id, LABEL_QUEUED, LABEL_GEN_FAILED, log)
        return False

    log.info(f"T1 generated: subject={email['subject']!r}")

    if args.dry_run:
        _print_dry_run(lead.email, 1, enrichment, email)
        return False

    try:
        msg_id, sent_thread_id = send_t1_via_new_message(
            service,
            to_email=lead.email,
            from_email=SENDER_EMAIL, from_name=SENDER_NAME,
            subject=email["subject"], body=email["body"],
        )
    except Exception as exc:
        log.exception(f"Gmail send failed for thread {thread_id}: {exc}")
        log_error(conn, "critical", thread_id, f"send: {exc}")
        return False

    log.info(f"T1 sent: msg_id={msg_id} new_thread={sent_thread_id} to={lead.email}")
    log_send(conn, sent_thread_id, 1, msg_id, lead.email)
    cache_enrichment(conn, sent_thread_id, enrichment)
    _safe_move(lm, sent_thread_id, None, LABEL_SENT_T1, log)
    delete_intake_draft(service, draft_id)
    _safe_remove_label(lm, service, thread_id, LABEL_QUEUED, log)
    return True


# ---- T2 / T3 / T4 ---------------------------------------------------------

def _process_followup(
    args, log, conn, lm: LabelManager, service, our_email: str,
    touch_number: int, thread_id: str, payload: dict,
) -> bool:
    enrichment = payload["enrichment"]
    last_send = payload["last_send"]
    recipient = last_send["recipient_email"]

    label_map = {
        2: (LABEL_SENT_T1, LABEL_SENT_T2),
        3: (LABEL_SENT_T2, LABEL_SENT_T3),
        4: (LABEL_SENT_T3, LABEL_SENT_T4),
    }
    from_label, to_label = label_map[touch_number]

    if already_sent(conn, thread_id, touch_number):
        log.warning(
            f"Thread {thread_id} already has T{touch_number}. Fixing label only."
        )
        _safe_move(lm, thread_id, from_label, to_label, log)
        return False

    # Phase 3 reply check: classify any inbound and dispatch.
    # OOO replies don't stop the sequence (we continue to send the follow-up).
    # Real / unsubscribe / bounce do — orchestrator handles them just like
    # reply_detector.py does, with the same dedup table so the two paths
    # never double-notify on the same message.
    inbound = classify_thread(service, thread_id, our_email)
    if inbound.kind == "real":
        log.info(
            f"Thread {thread_id} has a real reply (from {inbound.from_address!r}) — "
            f"pausing sequence, moving to {LABEL_REPLIED}."
        )
        if args.dry_run:
            return False
        already = inbound.message_id and is_reply_notified(conn, thread_id, inbound.message_id)
        _safe_move(lm, thread_id, from_label, LABEL_REPLIED, log)
        if not already:
            _notify_real_reply_from_orchestrator(
                service=service, conn=conn, log=log,
                thread_id=thread_id, enrichment=enrichment, inbound=inbound,
            )
            if inbound.message_id:
                mark_reply_notified(conn, thread_id, inbound.message_id, kind="real")
        return False

    if inbound.kind == "unsubscribe":
        log.info(f"Thread {thread_id}: unsubscribe detected; silent DNC.")
        if args.dry_run:
            return False
        if recipient:
            add_do_not_contact(conn, recipient, "unsubscribe-orchestrator")
        _safe_move(lm, thread_id, from_label, LABEL_DO_NOT_CONTACT, log)
        if inbound.message_id:
            mark_reply_notified(conn, thread_id, inbound.message_id, kind="unsubscribe")
        return False

    if inbound.kind == "bounce":
        log.info(f"Thread {thread_id}: bounce detected; closing thread.")
        if args.dry_run:
            return False
        if recipient:
            add_bounce(conn, recipient, "hard")
        _safe_move(lm, thread_id, from_label, LABEL_CLOSED_LOST, log)
        if inbound.message_id:
            mark_reply_notified(conn, thread_id, inbound.message_id, kind="bounce")
        return False

    if inbound.kind == "ooo":
        # Spec SECTION 9: OOO does NOT pause the sequence. Continue to send.
        log.info(f"Thread {thread_id}: OOO detected; sequence continues.")
        if inbound.message_id and not args.dry_run:
            mark_reply_notified(conn, thread_id, inbound.message_id, kind="ooo")
        # fall through to generation + send

    # Fetch thread metadata for proper reply threading.
    try:
        meta = get_thread_metadata(service, thread_id, our_email)
    except Exception as exc:
        log.error(f"Could not load thread metadata for {thread_id}: {exc}")
        log_error(conn, "error", thread_id, f"thread_meta: {exc}")
        return False

    # Sender-side preferred recipient: cached send_log value. If we somehow
    # lost it, fall back to the To: from the thread.
    if not recipient and meta.get("recipient"):
        recipient = meta["recipient"]
    if not recipient:
        log.error(f"Thread {thread_id} has no known recipient. Skipping.")
        return False

    # Re-check the DNC / bounce list before every follow-up.
    block_reason = is_blocked(conn, recipient)
    if block_reason:
        log.info(f"Thread {thread_id} recipient now blocked ({block_reason}); skipping.")
        if not args.dry_run:
            _safe_move(lm, thread_id, from_label, LABEL_DO_NOT_CONTACT, log)
        return False

    t1_subject = meta.get("first_subject") or ""

    # Generate the right touch.
    try:
        if touch_number == 2:
            email = generate_t2(enrichment, t1_subject, SKILL_FILE)
        elif touch_number == 3:
            email = generate_t3(enrichment, SKILL_FILE)
        else:  # 4
            email = generate_t4(enrichment, SKILL_FILE)
    except GenerationError as exc:
        log.error(f"T{touch_number} GENERATION_FAILED on {thread_id}: {exc}")
        log_error(conn, "error", thread_id, f"t{touch_number} generation: {exc}")
        if not args.dry_run:
            _safe_move(lm, thread_id, from_label, LABEL_GEN_FAILED, log)
        return False

    log.info(f"T{touch_number} generated: subject={email['subject']!r}")

    if args.dry_run:
        _print_dry_run(recipient, touch_number, enrichment, email)
        return False

    try:
        msg_id, sent_thread_id = send_followup_reply(
            service,
            thread_id=thread_id,
            to_email=recipient,
            from_email=SENDER_EMAIL, from_name=SENDER_NAME,
            subject=email["subject"], body=email["body"],
            in_reply_to=meta.get("last_outbound_message_id"),
            references=meta.get("references_chain"),
        )
    except Exception as exc:
        log.exception(f"Gmail follow-up send failed for {thread_id}: {exc}")
        log_error(conn, "critical", thread_id, f"t{touch_number} send: {exc}")
        return False

    log.info(
        f"T{touch_number} sent: msg_id={msg_id} thread={sent_thread_id} to={recipient}"
    )
    log_send(conn, thread_id, touch_number, msg_id, recipient)
    _safe_move(lm, thread_id, from_label, to_label, log)
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notify_real_reply_from_orchestrator(
    *, service, conn, log,
    thread_id: str, enrichment: dict, inbound,
) -> None:
    """Mirror reply_detector's notification when the orchestrator catches a reply
    before the polling detector did.
    """
    company = (enrichment.get("company_name") or "(unknown company)").strip()
    first_name = (enrichment.get("first_name") or "").strip()
    title = f"🔥 REPLY: {company} — {first_name}".strip()
    url = gmail_thread_url(thread_id)
    excerpt = (inbound.body_excerpt or "").strip()
    push_message = excerpt[:400] or f"Reply from {inbound.from_address}"
    send_pushover(title=title, message=push_message, url=url, priority=1)
    email_body = (
        f"From: {inbound.from_address}\n"
        f"Thread: {url}\n\n"
        f"--- Reply excerpt ---\n{excerpt}\n"
    )
    send_email_alert(service, subject=title, body=email_body)
    log.info(f"Orchestrator-side notifications dispatched for {thread_id}")
    if not pushover_enabled():
        log.warning("Pushover not configured — used email backup only.")


def _safe_move(lm, thread_id, from_label, to_label, log) -> None:
    try:
        lm.move_thread(thread_id, from_label, to_label)
    except Exception as exc:
        log.error(f"Label move failed ({from_label} -> {to_label}) on {thread_id}: {exc}")


def _safe_remove_label(lm, service, thread_id, label_name, log) -> None:
    try:
        from googleapiclient.errors import HttpError
        try:
            service.users().threads().modify(
                userId="me", id=thread_id,
                body={"removeLabelIds": [lm.get_id(label_name)]},
            ).execute()
        except HttpError as e:
            if e.resp.status != 404:
                raise
    except Exception as exc:
        log.warning(f"Could not remove label {label_name} from {thread_id}: {exc}")


def _print_dry_run(recipient: str, touch_number: int, enrichment: dict, email: dict) -> None:
    print()
    print("=" * 70)
    print(f"DRY RUN — would send T{touch_number} to {recipient}")
    print(f"From:    {SENDER_NAME} <{SENDER_EMAIL}>")
    print(f"Subject: {email['subject']}")
    print(f"Angle:   {enrichment.get('primary_angle')} "
          f"(secondary: {enrichment.get('secondary_angle')})")
    print(f"Anchor:  {enrichment.get('best_anchor')}")
    print("-" * 70)
    print(email["body"])
    print("=" * 70)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Waymark Cold Email Engine v2 — Phases 1+2")
    p.add_argument("--dry-run", action="store_true",
                   help="Generate but do not send or change labels")
    p.add_argument("--limit", type=int, default=1,
                   help="Max sends in this run (default 1)")
    p.add_argument("--ignore-pacing", action="store_true",
                   help="Bypass pacing checks. Still respects daily cap. Test only.")
    p.add_argument("--test-mode", action="store_true",
                   help="Allow consumer domains as recipients. Test only.")
    p.add_argument("--list-only", action="store_true",
                   help="Print queued + eligible follow-ups, take no action")
    p.add_argument("--only-touch", type=int, choices=[1, 2, 3, 4], default=None,
                   help="Only consider sends of the given touch number this run")
    return p.parse_args()


def main() -> int:
    setup_logging()
    try:
        return run_engine(parse_args())
    except Exception as exc:
        logging.getLogger("orchestrator").exception(f"Fatal error: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
