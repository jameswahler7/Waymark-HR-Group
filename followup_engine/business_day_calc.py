"""
business_day_calc.py — Waymark Cold Email Engine v2

Business-day arithmetic for the follow-up sequence:
  T2 eligible: T1 sent_at + 3 business days
  T3 eligible: T2 sent_at + 5 business days
  T4 eligible: T3 sent_at + 4 business days

A "business day" = a weekday (Mon-Fri) NOT listed in db_v2's holiday_calendar
table. Holidays include US federal holidays plus the spec's Thanksgiving
and Christmas adjacency days.

Spec reference: SECTION 8.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from db_v2 import is_holiday


def _is_business_day(conn, d: date) -> bool:
    if d.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    if is_holiday(conn, d.strftime("%Y-%m-%d")):
        return False
    return True


def add_business_days(conn, start: date, n: int) -> date:
    """Return the date that is `n` business days after `start`.

    `start` itself does NOT count, even if it's a business day. So
    add_business_days(Monday, 1) == Tuesday (if Tuesday is a business day).
    """
    if n <= 0:
        return start
    current = start
    counted = 0
    while counted < n:
        current = current + timedelta(days=1)
        if _is_business_day(conn, current):
            counted += 1
    return current


def is_eligible(conn, sent_at_utc: datetime, n_business_days: int, now_et: datetime) -> bool:
    """True if `now_et` is on or after the eligibility date.

    sent_at_utc is naive UTC (the format used in db_v2.send_log).
    now_et is naive Eastern (the engine's "wall clock").
    We compare on the date in Eastern (the spec is in ET).
    """
    sent_date_et = _utc_to_eastern_date(sent_at_utc)
    eligibility_date = add_business_days(conn, sent_date_et, n_business_days)
    return now_et.date() >= eligibility_date


def _utc_to_eastern_date(utc_dt: datetime) -> date:
    """Approximate UTC -> Eastern date conversion (mirrors send_engine logic).

    For date-granularity comparisons the DST offset matters very little —
    a send at 11 PM UTC is 6-7 PM ET the same day. We use a fixed -5
    fallback when DST math isn't trivially correct.
    """
    # Determine DST: 2nd Sun of March -> 1st Sun of November.
    year = utc_dt.year
    march = datetime(year, 3, 1)
    while march.weekday() != 6:
        march += timedelta(days=1)
    dst_start = march + timedelta(days=7, hours=7)  # 2 AM EST = 7 UTC
    nov = datetime(year, 11, 1)
    while nov.weekday() != 6:
        nov += timedelta(days=1)
    dst_end = nov + timedelta(hours=6)  # 2 AM EDT = 6 UTC
    offset = -4 if dst_start <= utc_dt < dst_end else -5
    eastern_dt = utc_dt + timedelta(hours=offset)
    return eastern_dt.date()
