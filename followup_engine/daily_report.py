#!/usr/bin/env python3
"""
daily_report.py — Waymark Cold Email Engine v2 (Phase 4)

Emails Jamie a one-screen report at 5:30 PM ET every business day.

Report format follows spec SECTION 10:
  - Sent today by touch + daily cap utilization
  - Replies today (real / OOO / unsubscribe / bounce)
  - Pipeline snapshot (live label counts 01-08)
  - This-week stats (M-F rolling: sent, real replies, reply rate)
  - Alerts (daily cap reached, enrichment / generation failures, errors 24h)
  - Tomorrow's queue preview

Sent FROM the authenticated mailbox (Jamie.wahler@waymarkhrgroup.com)
TO the same mailbox. Jamie sets a Gmail filter on subject prefix
"Waymark engine —" to label these `Reports`.

CLI:
  python3 daily_report.py             # send the report
  python3 daily_report.py --dry-run   # print to stdout, do not send
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta

from dotenv import load_dotenv
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_THIS_DIR, ".env"))
load_dotenv(os.path.join(os.path.dirname(_THIS_DIR), ".env"))

from gmail_auth import get_gmail_service
from db_v2 import init_db, count_sends_since, count_replies_since
from label_manager import (
    LabelManager,
    LABEL_QUEUED, LABEL_SENT_T1, LABEL_SENT_T2, LABEL_SENT_T3, LABEL_SENT_T4,
    LABEL_REPLIED, LABEL_BOOKED, LABEL_CLOSED_WON,
)
from notifier import send_email_alert
from send_engine import _now_eastern

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "waymark_engine.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "daily_report.log")
REPORT_TO = os.getenv("WAYMARK_REPORT_TO", "Jamie.wahler@waymarkhrgroup.com")
DAILY_CAP = 25


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
# Time helpers
# ---------------------------------------------------------------------------

def _et_to_utc_iso(et_dt: datetime) -> str:
    """Naive Eastern -> UTC ISO. Conservative: use -5 offset year-round.

    A 1-hour DST drift means a single hour's worth of sends might fall in the
    wrong bucket near 5:30 PM. For daily reporting that's acceptable.
    """
    return (et_dt + timedelta(hours=5)).isoformat()


def _today_window(now_et: datetime) -> str:
    today_start_et = datetime(now_et.year, now_et.month, now_et.day)
    return _et_to_utc_iso(today_start_et)


def _week_window(now_et: datetime) -> str:
    """Return ISO UTC for Monday 00:00 ET of the current week."""
    monday = now_et - timedelta(days=now_et.weekday())
    monday_start = datetime(monday.year, monday.month, monday.day)
    return _et_to_utc_iso(monday_start)


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _count_sends_today_by_touch(conn, today_start_iso: str) -> dict:
    out = {}
    for t in (1, 2, 3, 4):
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM send_log WHERE sent_at >= ? AND touch_number = ?",
            (today_start_iso, t),
        ).fetchone()
        out[t] = int(row["c"]) if row else 0
    return out


def _count_errors_like(conn, since_iso: str, pattern: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM errors WHERE timestamp >= ? AND message LIKE ?",
        (since_iso, pattern),
    ).fetchone()
    return int(row["c"]) if row else 0


def _count_errors_total(conn, since_iso: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM errors WHERE timestamp >= ?",
        (since_iso,),
    ).fetchone()
    return int(row["c"]) if row else 0


def _build_report(conn, lm: LabelManager, now_et: datetime) -> str:
    today_start_iso = _today_window(now_et)
    week_start_iso = _week_window(now_et)
    last_24h_iso = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    # Sent today
    sent_today = _count_sends_today_by_touch(conn, today_start_iso)
    total_today = sum(sent_today.values())

    # Replies today
    replied_today = {
        kind: count_replies_since(conn, today_start_iso, kind)
        for kind in ("real", "ooo", "unsubscribe", "bounce")
    }

    # Pipeline live counts
    pipeline = {
        "01_QUEUED":    len(lm.get_threads_in_label(LABEL_QUEUED)),
        "02_SENT_T1":   len(lm.get_threads_in_label(LABEL_SENT_T1)),
        "03_SENT_T2":   len(lm.get_threads_in_label(LABEL_SENT_T2)),
        "04_SENT_T3":   len(lm.get_threads_in_label(LABEL_SENT_T3)),
        "05_SENT_T4":   len(lm.get_threads_in_label(LABEL_SENT_T4)),
        "06_REPLIED":   len(lm.get_threads_in_label(LABEL_REPLIED)),
        "07_BOOKED":    len(lm.get_threads_in_label(LABEL_BOOKED)),
        "08_CLOSED_WON": len(lm.get_threads_in_label(LABEL_CLOSED_WON)),
    }

    # Week stats
    week_sent = count_sends_since(conn, week_start_iso)
    week_real = count_replies_since(conn, week_start_iso, "real")
    reply_rate = (week_real / week_sent * 100.0) if week_sent > 0 else 0.0

    # Alerts
    enrich_fails_today = _count_errors_like(conn, today_start_iso, "enrichment:%")
    gen_fails_today = _count_errors_like(conn, today_start_iso, "%generation:%")
    errors_24h = _count_errors_total(conn, last_24h_iso)
    cap_reached = "YES" if total_today >= DAILY_CAP else "NO"

    # Build text
    return f"""SENT TODAY
  Touch 1 (new):       {sent_today[1]}
  Touch 2 (3d FU):     {sent_today[2]}
  Touch 3 (pivot):     {sent_today[3]}
  Touch 4 (breakup):   {sent_today[4]}
  Total today:         {total_today} / {DAILY_CAP}

REPLIES TODAY
  Real replies:        {replied_today['real']}   <- Handle in 06_REPLIED
  Out-of-office:       {replied_today['ooo']}
  Unsubscribes:        {replied_today['unsubscribe']}
  Bounces:             {replied_today['bounce']}

PIPELINE SNAPSHOT (live label counts)
  01_QUEUED:           {pipeline['01_QUEUED']}
  02_SENT_T1:          {pipeline['02_SENT_T1']}
  03_SENT_T2:          {pipeline['03_SENT_T2']}
  04_SENT_T3:          {pipeline['04_SENT_T3']}
  05_SENT_T4:          {pipeline['05_SENT_T4']}
  06_REPLIED:          {pipeline['06_REPLIED']}  <- Jamie's action items

THIS WEEK (M-F rolling, since Monday 00:00 ET)
  Sent total:          {week_sent}
  Real replies:        {week_real}
  Reply rate:          {reply_rate:.1f}%
  Booked sessions:     {pipeline['07_BOOKED']}  (current 07_BOOKED count)
  Closed won:          {pipeline['08_CLOSED_WON']}  (current 08_CLOSED_WON count)

ALERTS
  - Daily cap reached:           {cap_reached}
  - Enrichment failures today:   {enrich_fails_today}
  - Generation failures today:   {gen_fails_today}
  - Errors (last 24h):           {errors_24h}
  - Domain reputation:           not checked in Phase 4 MVP

TOMORROW'S QUEUE PREVIEW
  01_QUEUED waiting:   {pipeline['01_QUEUED']}
"""


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run_report(args: argparse.Namespace) -> int:
    log = logging.getLogger("daily_report")
    conn = init_db(DB_PATH)
    service = get_gmail_service(BASE_DIR)
    lm = LabelManager(service)
    lm.ensure_labels()

    now_et = _now_eastern()
    report = _build_report(conn, lm, now_et)
    weekday = now_et.strftime("%A")
    date_str = f"{now_et.strftime('%B')} {now_et.day}, {now_et.year}"
    subject = f"Waymark engine — {weekday}, {date_str}"

    if args.dry_run:
        print(f"DRY RUN — would email to {REPORT_TO}")
        print(f"Subject: {subject}\n")
        print(report)
    else:
        ok = send_email_alert(service, subject=subject, body=report, to_email=REPORT_TO)
        if ok:
            log.info(f"Daily report delivered to {REPORT_TO}")
        else:
            log.error(f"Daily report failed to send")

    conn.close()
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Waymark Daily Report (Phase 4)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print report to stdout instead of sending")
    return p.parse_args()


def main() -> int:
    setup_logging()
    try:
        return run_report(parse_args())
    except Exception as exc:
        logging.getLogger("daily_report").exception(f"Fatal: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
