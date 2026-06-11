"""
db_v2.py — Waymark Cold Email Engine v2

Operational SQLite database. Gmail labels are the primary state machine;
this DB only stores operational state that doesn't belong in Gmail:

  enrichment_cache  — one row per thread, populated at T1, reused for T2-T4
  send_log          — one row per send for pacing + follow-up timing
  bounce_history    — never send to a bounced address again
  do_not_contact    — hard exclude list (manual or from unsubscribe replies)
  holiday_calendar  — US federal holidays + Thanksgiving/Christmas adjacencies
  errors            — surfaces in daily report

DB is created at followup_engine/waymark_engine.db on first run.

Spec reference: SECTION 11.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

# Pre-loaded US federal holidays + Thanksgiving / Christmas adjacencies.
# Spec requires no sends on US federal holidays, no sends on the business day
# before or after Thanksgiving and Christmas.
PRELOADED_HOLIDAYS = [
    # 2026
    ("2026-01-01", "New Year's Day"),
    ("2026-01-19", "Martin Luther King Jr. Day"),
    ("2026-02-16", "Presidents Day"),
    ("2026-05-25", "Memorial Day"),
    ("2026-06-19", "Juneteenth"),
    ("2026-07-03", "Independence Day (observed)"),
    ("2026-09-07", "Labor Day"),
    ("2026-10-12", "Columbus Day"),
    ("2026-11-11", "Veterans Day"),
    ("2026-11-25", "Day before Thanksgiving"),
    ("2026-11-26", "Thanksgiving Day"),
    ("2026-11-27", "Day after Thanksgiving"),
    ("2026-12-24", "Christmas Eve"),
    ("2026-12-25", "Christmas Day"),
    ("2026-12-28", "Business day after Christmas"),
    ("2026-12-31", "New Year's Eve"),
    # 2027
    ("2027-01-01", "New Year's Day"),
    ("2027-01-18", "Martin Luther King Jr. Day"),
    ("2027-02-15", "Presidents Day"),
    ("2027-05-31", "Memorial Day"),
    ("2027-06-18", "Juneteenth (observed)"),
    ("2027-07-05", "Independence Day (observed)"),
    ("2027-09-06", "Labor Day"),
    ("2027-10-11", "Columbus Day"),
    ("2027-11-11", "Veterans Day"),
    ("2027-11-24", "Day before Thanksgiving"),
    ("2027-11-25", "Thanksgiving Day"),
    ("2027-11-26", "Day after Thanksgiving"),
    ("2027-12-23", "Day before Christmas"),
    ("2027-12-24", "Christmas Eve"),
    ("2027-12-27", "Business day after Christmas"),
]


def init_db(db_path: str) -> sqlite3.Connection:
    """Open (or create) the operational DB and ensure schema + seed data."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS enrichment_cache (
            thread_id        TEXT PRIMARY KEY,
            enrichment_json  TEXT NOT NULL,
            captured_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS send_log (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id         TEXT NOT NULL,
            touch_number      INTEGER NOT NULL,
            sent_at           TEXT NOT NULL,
            message_id        TEXT NOT NULL,
            recipient_email   TEXT NOT NULL,
            UNIQUE(thread_id, touch_number)
        );

        CREATE INDEX IF NOT EXISTS idx_send_log_sent_at ON send_log(sent_at);

        CREATE TABLE IF NOT EXISTS bounce_history (
            email_address  TEXT PRIMARY KEY,
            bounced_at     TEXT NOT NULL,
            bounce_type    TEXT
        );

        CREATE TABLE IF NOT EXISTS do_not_contact (
            email_address  TEXT PRIMARY KEY,
            added_at       TEXT NOT NULL,
            source         TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS holiday_calendar (
            date  TEXT PRIMARY KEY,
            name  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS errors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            severity    TEXT NOT NULL,
            thread_id   TEXT,
            message     TEXT NOT NULL
        );

        -- Phase 3: tracks every reply event the engine has handled so that the
        -- polling detector and orchestrator never double-notify or re-process
        -- the same inbound message. Also feeds the daily report counts.
        CREATE TABLE IF NOT EXISTS replied_notifications (
            thread_id    TEXT NOT NULL,
            message_id   TEXT NOT NULL,
            notified_at  TEXT NOT NULL,
            kind         TEXT NOT NULL,   -- 'real' | 'ooo' | 'unsubscribe' | 'bounce'
            PRIMARY KEY (thread_id, message_id)
        );

        CREATE INDEX IF NOT EXISTS idx_replied_notified_at
            ON replied_notifications(notified_at);
        """
    )

    # Seed holidays if empty
    existing = cur.execute("SELECT COUNT(*) FROM holiday_calendar").fetchone()[0]
    if existing == 0:
        cur.executemany(
            "INSERT OR IGNORE INTO holiday_calendar(date, name) VALUES (?, ?)",
            PRELOADED_HOLIDAYS,
        )

    conn.commit()
    return conn


# ----------------------------- enrichment cache -----------------------------

def cache_enrichment(conn: sqlite3.Connection, thread_id: str, enrichment: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO enrichment_cache(thread_id, enrichment_json, captured_at) VALUES (?, ?, ?)",
        (thread_id, json.dumps(enrichment), datetime.utcnow().isoformat()),
    )
    conn.commit()


def get_cached_enrichment(conn: sqlite3.Connection, thread_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT enrichment_json FROM enrichment_cache WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    return json.loads(row["enrichment_json"]) if row else None


# ----------------------------- send log -------------------------------------

def log_send(
    conn: sqlite3.Connection,
    thread_id: str,
    touch_number: int,
    message_id: str,
    recipient_email: str,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO send_log(thread_id, touch_number, sent_at, message_id, recipient_email) VALUES (?, ?, ?, ?, ?)",
        (thread_id, touch_number, datetime.utcnow().isoformat(), message_id, recipient_email),
    )
    conn.commit()


def already_sent(conn: sqlite3.Connection, thread_id: str, touch_number: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM send_log WHERE thread_id = ? AND touch_number = ?",
        (thread_id, touch_number),
    ).fetchone()
    return row is not None


def count_sends_since(conn: sqlite3.Connection, since_iso: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM send_log WHERE sent_at >= ?",
        (since_iso,),
    ).fetchone()
    return int(row["c"])


def get_last_send_for_thread(conn: sqlite3.Connection, thread_id: str) -> Optional[dict]:
    """Return the most recent send_log row for a thread (highest touch_number).

    Used by the follow-up orchestrator to determine when the previous touch
    was sent (eligibility window) and what touch number to send next.
    """
    row = conn.execute(
        "SELECT thread_id, touch_number, sent_at, message_id, recipient_email "
        "FROM send_log WHERE thread_id = ? ORDER BY touch_number DESC LIMIT 1",
        (thread_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def last_send_at(conn: sqlite3.Connection) -> Optional[datetime]:
    row = conn.execute(
        "SELECT sent_at FROM send_log ORDER BY sent_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return datetime.fromisoformat(row["sent_at"])


# ----------------------------- exclusion lists ------------------------------

def is_blocked(conn: sqlite3.Connection, email_address: str) -> Optional[str]:
    """Return reason string if email is in DNC or bounce history, else None."""
    e = (email_address or "").strip().lower()
    if not e:
        return None
    row = conn.execute(
        "SELECT source FROM do_not_contact WHERE email_address = ?", (e,)
    ).fetchone()
    if row:
        return f"do_not_contact ({row['source']})"
    row = conn.execute(
        "SELECT bounce_type FROM bounce_history WHERE email_address = ?", (e,)
    ).fetchone()
    if row:
        return f"bounced ({row['bounce_type'] or 'unknown'})"
    return None


def add_do_not_contact(conn: sqlite3.Connection, email_address: str, source: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO do_not_contact(email_address, added_at, source) VALUES (?, ?, ?)",
        (email_address.strip().lower(), datetime.utcnow().isoformat(), source),
    )
    conn.commit()


def add_bounce(conn: sqlite3.Connection, email_address: str, bounce_type: str) -> None:
    """Record a bounced address so future intake validation rejects it."""
    conn.execute(
        "INSERT OR REPLACE INTO bounce_history(email_address, bounced_at, bounce_type) VALUES (?, ?, ?)",
        (email_address.strip().lower(), datetime.utcnow().isoformat(), bounce_type),
    )
    conn.commit()


# ----------------------------- reply notifications --------------------------

def is_reply_notified(conn: sqlite3.Connection, thread_id: str, message_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM replied_notifications WHERE thread_id = ? AND message_id = ?",
        (thread_id, message_id),
    ).fetchone()
    return row is not None


def mark_reply_notified(
    conn: sqlite3.Connection,
    thread_id: str,
    message_id: str,
    kind: str,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO replied_notifications(thread_id, message_id, notified_at, kind) VALUES (?, ?, ?, ?)",
        (thread_id, message_id, datetime.utcnow().isoformat(), kind),
    )
    conn.commit()


def count_replies_since(conn: sqlite3.Connection, since_iso: str, kind: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM replied_notifications WHERE notified_at >= ? AND kind = ?",
        (since_iso, kind),
    ).fetchone()
    return int(row["c"])


# ----------------------------- holiday calendar -----------------------------

def is_holiday(conn: sqlite3.Connection, date_iso: str) -> Optional[str]:
    row = conn.execute(
        "SELECT name FROM holiday_calendar WHERE date = ?", (date_iso,)
    ).fetchone()
    return row["name"] if row else None


# ----------------------------- errors ---------------------------------------

def log_error(
    conn: sqlite3.Connection,
    severity: str,
    thread_id: Optional[str],
    message: str,
) -> None:
    conn.execute(
        "INSERT INTO errors(timestamp, severity, thread_id, message) VALUES (?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), severity, thread_id, message),
    )
    conn.commit()
