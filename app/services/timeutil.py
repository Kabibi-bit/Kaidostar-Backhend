"""Shared UTC time helper.
 
Replaces datetime.utcnow(), which is deprecated in Python 3.12+. Critically, it
returns a *naive* UTC datetime (no tzinfo) - the SAME kind utcnow() returned -
because the app's DB columns are naive DateTime and existing code compares and
subtracts against those stored naive values. Returning an aware datetime instead
would raise "can't compare offset-naive and offset-aware datetimes" at those
sites. So this is a drop-in: same value, same naive-ness, just not deprecated.
"""
from datetime import datetime, timezone
 
 
def utcnow() -> datetime:
    """Naive UTC now (drop-in for the deprecated datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
 
 
def to_naive_utc(dt):
    """Coerce a datetime that may be tz-AWARE to naive UTC, for safe comparison /
    subtraction against utcnow().
 
    The app's DB columns are declared naive `DateTime` in the models, but several
    are `TIMESTAMPTZ` in the actual Postgres schema (created_at, sendable_at,
    sent_at, updated_at, fetched_at, ...). psycopg2 reads a TIMESTAMPTZ back as a
    tz-AWARE datetime, so a Python-side `utcnow() < row.sendable_at` raises
    "can't compare offset-naive and offset-aware datetimes". This normalizes any
    such value to naive UTC (converting from its own tz first). A naive input is
    assumed already-UTC and returned unchanged; None passes through. Mirrors the
    coercion matching.py already does for fetched_at.
    """
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
 
