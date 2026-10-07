"""The employer-feed crawler: reads employers' career-site feeds a slice at a time,
keeps the `listings` table in step with them, and stays inside the database budget.
 
How it runs (built for Render's free plan, where the service sleeps when idle):
  * run_feed_tick() does a few minutes of work and stops. It is called every
    FEED_TICK_MINUTES by the in-process scheduler while the service is awake, and
    by GET/POST /feeds/tick (with FEED_TICK_KEY) - which a free uptime pinger can
    call every 10 minutes to keep the service awake and the crawl moving.
  * Only one tick runs at a time anywhere (a lease row in crawl_state).
  * Each tick: refresh the employers that are due (about once a day each), read
    some newly found employers, look for more employers now and then, close jobs
    their employers took down, and keep the pool inside its storage budget.
  * A feed that is byte-for-byte what we last read in full is not parsed again.
 
The storage budget (Supabase's free plan is 500 MB for everything):
  * FEED_DB_CEILING_MB (default 400) - when the database reaches it, the number of
    employer jobs held then becomes the cap; from then on the oldest jobs make
    room for new ones, so the pool stays fresh rather than growing.
  * FEED_MAX_JOBS - an optional hard cap on top.
 
What users did is never lost. A job someone saved, applied to, logged an outcome
for or wrote to the employer about is never deleted: when its employer takes it
down it is only marked closed. Deleting is done in two steps - lock the rows,
then check again in a fresh statement - so a save made at that very moment is
either seen (and the job kept) or refused cleanly (the job is gone), never
silently cascaded away. If the check of those tables can't be made, nothing is
changed that tick.
 
Every write goes through plain SQL (sqlalchemy.text) so the listings model and
the rest of the app don't change shape; the columns it uses come from
db/schema_additions_employer_feeds.sql.
"""
import hashlib
import json
import logging
import os
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
 
from app.services.feed_common import compress_text, decompress_text
from app.services import employer_feeds as EF
from app.services import employer_directory as ED
 
log = logging.getLogger("kaidostar.feeds")
 
FEED_ATS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee")
TICK_BUDGET_S = float(os.getenv("FEED_TICK_SECONDS", "240"))
WORKERS = max(1, min(4, int(os.getenv("FEED_WORKERS", "2"))))
DETAILS_PER_TICK = int(os.getenv("FEED_DETAILS_PER_TICK", "500"))
DETAILS_PER_BOARD = 120
CEILING_MB = float(os.getenv("FEED_DB_CEILING_MB", "400"))
REFRESH_HOURS = 20                      # an employer is re-read about once a day (20-24 h, spread out)
EMPTY_DAYS = 4                          # an employer with no US jobs is looked at again in a few days
STALE_DAYS = 4                          # jobs of an employer we couldn't read for this long are closed - we can't vouch for them
LEASE_MIN = 20
REINDEX_BATCH = 800
SKIPS_MAX = 300000
# tables whose rows are a person's own history: a job they point at is never deleted
PROTECT_TABLES = ("saved_listings", "applications", "outcomes", "outreach_emails")
# tables whose rows only make sense while the job exists: cleared with it
CLEAR_TABLES = ("dismissed_listings", "match_scores")
STATE_LOCK, STATE_COVERAGE, STATE_CAP, STATE_CC, STATE_USAJOBS, STATE_DISCOVERY, STATE_INDEX = (
    "feed_lock", "feed_coverage", "feed_cap", "feed_cc_cursor", "feed_usajobs_cursor", "feed_discovery", "feed_index")
MAX_JOBS_ENV = os.getenv("FEED_MAX_JOBS", "").strip()
 
_local_running = threading.Lock()
 
 
class GuardUnavailable(Exception):
    """The tables that protect users' records couldn't be checked: nothing may be deleted."""
 
 
def enabled() -> bool:
    return os.getenv("FEEDS_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
 
 
def _x(db, sql, params=None):
    from sqlalchemy import text
    return db.execute(text(sql), params or {})
 
 
def _now():
    return datetime.utcnow().replace(microsecond=0)
 
 
def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None
 
 
def index_version() -> str:
    """Changes whenever the engine or its taxonomy changes - then stored jobs are re-indexed."""
    try:
        from app.services import job_engine as JE
        h = hashlib.sha1((str(JE.ENGINE_VERSION) + json.dumps([JE.TAX.get("roles"), JE.TAX.get("metros")], sort_keys=True, default=str)).encode())
        return h.hexdigest()[:12]
    except Exception:
        return "unknown"
 
 
# ------------------------------------------------------------------ small state store
def state_get(db, key):
    row = _x(db, "SELECT value FROM crawl_state WHERE key = :k", {"k": key}).fetchone()
    if not row or row[0] is None:
        return None
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return None
 
 
def state_set(db, key, value):
    _x(db, "INSERT INTO crawl_state (key, value, updated_at) VALUES (:k, :v, :t) "
           "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
       {"k": key, "v": json.dumps(value), "t": _now()})
 
 
def schema_ready(db) -> bool:
    try:
        _x(db, "SELECT id, ats, slug, status, feed_sig FROM employer_boards LIMIT 1").fetchall()
        _x(db, "SELECT board_id, body_z, feed_keys, content_hash, closed_at, salary_period FROM listings LIMIT 0").fetchall()
        _x(db, "SELECT key FROM crawl_state LIMIT 1").fetchall()
        _x(db, "SELECT board_id FROM employer_job_skips LIMIT 0").fetchall()
        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False
 
 
def _lease(db, owner) -> bool:
    now = _now()
    _x(db, "INSERT INTO crawl_state (key, value, updated_at) VALUES (:k, NULL, :t) ON CONFLICT (key) DO NOTHING", {"k": STATE_LOCK, "t": now})
    got = _x(db, "UPDATE crawl_state SET value = :o, updated_at = :t WHERE key = :k AND (value IS NULL OR updated_at < :stale) RETURNING key",
             {"o": json.dumps(owner), "t": now, "k": STATE_LOCK, "stale": now - timedelta(minutes=LEASE_MIN)}).fetchone()
    db.commit()
    return bool(got)
 
 
def _release(db, owner):
    try:
        db.rollback()                     # whatever failed before must not take the release down with it
    except Exception:
        pass
    try:
        _x(db, "UPDATE crawl_state SET value = NULL, updated_at = :t WHERE key = :k AND value = :o", {"t": _now(), "k": STATE_LOCK, "o": json.dumps(owner)})
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
 
 
def _existing(db, tables) -> list:
    """Which of these tables exist. Raises GuardUnavailable if that can't be told."""
    out = []
    for t in tables:
        try:
            if _x(db, "SELECT to_regclass(:t)", {"t": "public." + t}).scalar():
                out.append(t)
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            raise GuardUnavailable("couldn't check %s: %s" % (t, type(e).__name__))
    return out
 
 
class Guard:
    """The protected and the clearable tables that exist in this database."""
 
    def __init__(self, db):
        self.protect = _existing(db, PROTECT_TABLES)
        self.clear = _existing(db, CLEAR_TABLES)
 
    def referenced_sql(self, alias="l") -> str:
        return " OR ".join("EXISTS (SELECT 1 FROM %s p_%d WHERE p_%d.listing_id = %s.id)" % (t, i, i, alias)
                           for i, t in enumerate(self.protect)) or "FALSE"
 
 
def drop_listings(db, ids, guard: Guard, now, set_aside=False) -> tuple:
    """Delete these employer-feed listings - except the ones a person acted on, which are only
    marked closed. Rows are locked first; the check runs after, in its own statement.
    Returns (deleted, kept_closed). set_aside: remember deleted ones as set aside for room."""
    ids = [str(i) for i in ids if i]
    if not ids:
        return 0, 0
    locked = [str(r[0]) for r in _x(db, "SELECT id FROM listings WHERE id = ANY(CAST(:ids AS uuid[])) AND board_id IS NOT NULL FOR UPDATE",
                                    {"ids": ids}).fetchall()]
    if not locked:
        return 0, 0
    keep = {str(r[0]) for r in _x(db, "SELECT l.id FROM listings l WHERE l.id = ANY(CAST(:ids AS uuid[])) AND (" + guard.referenced_sql("l") + ")",
                                  {"ids": locked}).fetchall()}
    gone = [i for i in locked if i not in keep]
    if gone:
        for t in guard.clear:
            _x(db, "DELETE FROM %s WHERE listing_id = ANY(CAST(:ids AS uuid[]))" % t, {"ids": gone})
        rows = _x(db, "DELETE FROM listings WHERE id = ANY(CAST(:ids AS uuid[])) RETURNING board_id, external_id, content_hash", {"ids": gone}).fetchall()
        if set_aside and rows:
            _x(db, "INSERT INTO employer_job_skips (board_id, external_id, sig, reason, created_at) "
                   "SELECT b, e, s, 'room', :t FROM unnest(CAST(:b AS integer[]), CAST(:e AS text[]), CAST(:s AS text[])) AS x(b, e, s) "
                   "ON CONFLICT (board_id, external_id) DO UPDATE SET sig = EXCLUDED.sig, reason = 'room'",
               {"b": [r[0] for r in rows], "e": [r[1] for r in rows], "s": [r[2] or "" for r in rows], "t": now})
    if keep:
        _x(db, "UPDATE listings SET closed_at = coalesce(closed_at, :t), feed_keys = NULL WHERE id = ANY(CAST(:ids AS uuid[]))",
           {"t": now, "ids": list(keep)})
    return len(gone), len(keep)
 
 
# ------------------------------------------------------------------ directory
def add_boards(db, pairs, found_via) -> int:
    """Register (hiring system, feed name) pairs we don't know yet. Returns how many were new."""
    pairs = [(a, s[:200]) for a, s in pairs if (a in FEED_ATS or a == "usajobs") and s]
    added = 0
    for i in range(0, len(pairs), 500):
        chunk = pairs[i:i + 500]
        rows = _x(db, "INSERT INTO employer_boards (ats, slug, status, found_via, created_at) "
                      "SELECT a, s, 'new', :via, :t FROM unnest(CAST(:a AS text[]), CAST(:s AS text[])) AS x(a, s) "
                      "ON CONFLICT (ats, lower(slug)) DO NOTHING RETURNING id",
                  {"a": [p[0] for p in chunk], "s": [p[1] for p in chunk], "via": found_via, "t": _now()}).fetchall()
        added += len(rows)
    db.commit()
    return added
 
 
def discover(db, fetcher, deadline, now_fn=time.monotonic) -> dict:
    """Look for more employers: the starter list once, links already in the database and the
    SimplifyJobs lists once a day, then the Common Crawl index a few pages at a time."""
    out = {"seed": 0, "listings": 0, "simplify": 0, "commoncrawl": 0}
    st = state_get(db, STATE_DISCOVERY) or {}
    today = _now().strftime("%Y-%m-%d")
    if not st.get("seeded"):
        out["seed"] = add_boards(db, ED.seed_pairs(), "seed")
        st["seeded"] = True
    if EF.usajobs_configured() and not st.get("usajobs"):
        add_boards(db, [("usajobs", "public")], "seed")
        st["usajobs"] = True
    if st.get("links_day") != today:
        pairs = set()
        try:
            for (url,) in _x(db, "SELECT DISTINCT apply_url FROM listings WHERE board_id IS NULL AND apply_url ~* "
                                 "'(greenhouse\\.io|lever\\.co|ashbyhq\\.com|workable\\.com|smartrecruiters\\.com|recruitee\\.com)' LIMIT 20000").fetchall():
                pairs |= ED.boards_in_text(url)
        except Exception:
            db.rollback()
        out["listings"] = add_boards(db, pairs, "listing")
        if now_fn() < deadline:
            out["simplify"] = add_boards(db, ED.boards_from_simplify(fetcher), "simplify")
        st["links_day"] = today
    state_set(db, STATE_DISCOVERY, st)
    db.commit()
    if now_fn() < deadline:
        cursor = state_get(db, STATE_CC)
        if ED.cc_due(cursor):
            found, cursor = ED.cc_step(fetcher, cursor, deadline, now_fn)
            out["commoncrawl"] = add_boards(db, found, "commoncrawl")
            if cursor is not None:
                state_set(db, STATE_CC, cursor)
                db.commit()
    return out
 
 
# ------------------------------------------------------------------ capacity
def capacity(db, guard: Guard) -> dict:
    """How many employer jobs we hold, how many we may hold, and room for more right now.
    A Postgres database doesn't shrink when rows are deleted (the space is reused), so the cap is
    set once, when the database first reaches the ceiling, and only cut again if it keeps growing."""
    open_rows = int(_x(db, "SELECT count(*) FROM listings WHERE board_id IS NOT NULL AND closed_at IS NULL").scalar() or 0)
    try:
        db_mb = float(_x(db, "SELECT pg_database_size(current_database())").scalar() or 0) / (1024 * 1024)
    except Exception:
        db.rollback()
        db_mb = 0.0
    st = state_get(db, STATE_CAP)
    st = st if isinstance(st, dict) else {}
    cap = st.get("cap") if isinstance(st.get("cap"), int) else None
    if cap is not None and db_mb and db_mb < CEILING_MB * 0.85:
        cap = None                                   # the ceiling was raised (or space freed): grow again
        st = {}
    if db_mb >= CEILING_MB and cap is None:
        cap = max(0, int(open_rows * 0.97))
        st = {"cap": cap, "cut_mb": db_mb}
    elif cap is not None and db_mb >= max(CEILING_MB + 30, float(st.get("cut_mb") or 0) + 10):
        cap = int(cap * 0.95)                        # still growing past the ceiling: hold fewer
        st = {"cap": cap, "cut_mb": db_mb}
    hard = int(MAX_JOBS_ENV) if MAX_JOBS_ENV.isdigit() else None
    eff = cap if hard is None else (hard if cap is None else min(cap, hard))
    state_set(db, STATE_CAP, st or None)
    db.commit()
    evicted = 0
    if eff is not None and open_rows > int(eff * 0.99) + 1:
        target = max(0, int(eff * 0.95))
        evicted = evict_oldest(db, open_rows - target, guard)
        open_rows -= evicted
    room = None if eff is None else max(0, eff - open_rows)
    return {"open": open_rows, "db_mb": round(db_mb, 1), "cap": eff, "room": room, "evicted": evicted, "ceiling_mb": CEILING_MB}
 
 
def evict_oldest(db, n, guard: Guard) -> int:
    """Make room: the oldest employer jobs nobody has acted on go first. Each is remembered as
    set aside, so its employer's next read doesn't bring it straight back."""
    gone = 0
    while n > 0:
        k = min(n, 1000)
        ids = [str(r[0]) for r in _x(db, "SELECT l.id FROM listings l WHERE l.board_id IS NOT NULL AND l.closed_at IS NULL AND NOT (" +
                                     guard.referenced_sql("l") + ") ORDER BY coalesce(l.posted_at, l.fetched_at) ASC NULLS FIRST LIMIT :n",
                                     {"n": k}).fetchall()]
        if not ids:
            break
        d, _ = drop_listings(db, ids, guard, _now(), set_aside=True)
        db.commit()
        gone += d
        if len(ids) < k:
            break
        n -= k
    return gone
 
 
# ------------------------------------------------------------------ reading boards
_BOARD_COLS = "id, ats, slug, company, status, fail_count, last_ok_at, last_error, feed_sig, jobs_live"
 
 
def due_boards(db, n_refresh, n_new) -> list:
    now = _now()
    rows = _x(db, "SELECT " + _BOARD_COLS + " FROM employer_boards WHERE status IN ('active', 'empty', 'failing', 'blocked', 'too_big') "
                  "AND ats = ANY(CAST(:ats AS text[])) AND (next_due_at IS NULL OR next_due_at <= :now) ORDER BY next_due_at NULLS FIRST, id LIMIT :n",
              {"ats": list(FEED_ATS), "now": now, "n": n_refresh}).mappings().all()
    rows = [dict(r) for r in rows]
    if n_new > 0:
        fresh = _x(db, "SELECT " + _BOARD_COLS + " FROM employer_boards WHERE status = 'new' AND ats = ANY(CAST(:ats AS text[])) "
                       "AND (next_due_at IS NULL OR next_due_at <= :now) ORDER BY next_due_at NULLS FIRST, id LIMIT :n",
                   {"ats": list(FEED_ATS), "now": now, "n": n_new}).mappings().all()
        rows += [dict(r) for r in fresh]
    return rows
 
 
def board_state(db, board_id):
    """What we hold for one employer: {external_id: (listing id, signature, closed?)} and the set-aside jobs."""
    held = {}
    for r in _x(db, "SELECT id, external_id, content_hash, closed_at FROM listings WHERE board_id = :b", {"b": board_id}).fetchall():
        held[r[1]] = (str(r[0]), r[2], r[3] is not None)
    skips = {r[0]: r[1] for r in _x(db, "SELECT external_id, sig FROM employer_job_skips WHERE board_id = :b", {"b": board_id}).fetchall()}
    return held, skips
 
 
_INSERT_COLS = ("id", "source", "external_id", "title", "org", "type", "location", "body_z", "apply_url", "fetched_at", "posted_at",
                "last_seen_at", "repost_count", "salary_min", "salary_max", "salary_is_predicted", "salary_period", "employment_type",
                "contract_type", "category", "canonical_key", "deadline", "board_id", "feed_keys", "content_hash")
 
 
def _row_params(row, board_id, now):
    has_pay = row.get("salary_min") is not None or row.get("salary_max") is not None
    dl = row.get("deadline")
    return {
        "id": str(uuid.uuid4()), "source": row["source"], "external_id": row["external_id"][:200], "title": row["title"][:300],
        "org": (row["org"] or "")[:200], "type": row["type"], "location": (row.get("location") or "")[:300] or None,
        "body_z": compress_text(row.get("text") or ""), "apply_url": row["apply_url"][:1000], "fetched_at": now,
        "posted_at": row.get("posted_at"), "last_seen_at": now, "repost_count": 0,
        "salary_min": row.get("salary_min"), "salary_max": row.get("salary_max"),
        "salary_is_predicted": False if has_pay else None, "salary_period": row.get("salary_period") if has_pay else None,
        "employment_type": row.get("employment_type"), "contract_type": row.get("contract_type"), "category": (row.get("category") or "")[:120] or None,
        "canonical_key": (row.get("canonical_key") or None) and row["canonical_key"][:300],
        "deadline": dl.date() if isinstance(dl, datetime) else dl,
        "board_id": board_id, "feed_keys": list(row.get("feed_keys") or []), "content_hash": row["sig"],
    }
 
 
def _casts(col, name):
    return {"id": "CAST(:%s AS uuid)" % name, "feed_keys": "CAST(:%s AS text[])" % name}.get(col, ":" + name)
 
 
def insert_rows(db, rows, board_id, now) -> list:
    """Many new jobs in a few statements (one round trip per 40 rows). Returns the new listing ids."""
    ids = []
    for i in range(0, len(rows), 40):
        chunk = rows[i:i + 40]
        params, values = {}, []
        for j, row in enumerate(chunk):
            p = _row_params(row, board_id, now)
            names = []
            for c in _INSERT_COLS:
                k = "%s_%d" % (c, j)
                params[k] = p[c]
                names.append(_casts(c, k))
            values.append("(" + ", ".join(names) + ")")
        got = _x(db, "INSERT INTO listings (" + ", ".join(_INSERT_COLS) + ") VALUES " + ", ".join(values) +
                 " ON CONFLICT DO NOTHING RETURNING id", params).fetchall()
        ids.extend(str(r[0]) for r in got)
    return ids
 
 
def update_row(db, listing_id, row, now):
    p = _row_params(row, None, now)
    p["lid"] = listing_id
    _x(db, "UPDATE listings SET title = :title, org = :org, type = :type, location = :location, body_z = :body_z, apply_url = :apply_url, "
           "posted_at = coalesce(:posted_at, posted_at), last_seen_at = :last_seen_at, salary_min = :salary_min, salary_max = :salary_max, "
           "salary_is_predicted = :salary_is_predicted, salary_period = :salary_period, employment_type = :employment_type, "
           "contract_type = :contract_type, category = :category, canonical_key = :canonical_key, deadline = :deadline, "
           "feed_keys = CAST(:feed_keys AS text[]), content_hash = :content_hash, closed_at = NULL WHERE id = CAST(:lid AS uuid)", p)
 
 
def set_reposts(db, listing_ids):
    """A job a company already posted (same company, title and place) more than a week earlier
    is a repost - counted the way the rest of Kaidostar counts them."""
    if not listing_ids:
        return
    _x(db, "UPDATE listings n SET repost_count = sub.c FROM ("
           " SELECT n2.id, max(coalesce(o.repost_count, 0) + 1) AS c FROM listings n2 JOIN listings o"
           " ON o.canonical_key = n2.canonical_key AND o.id <> n2.id"
           " AND coalesce(o.posted_at, o.fetched_at) < coalesce(n2.posted_at, n2.fetched_at) - interval '7 days'"
           " WHERE n2.id = ANY(CAST(:ids AS uuid[])) AND n2.canonical_key IS NOT NULL GROUP BY n2.id) sub WHERE n.id = sub.id",
       {"ids": list(listing_ids)})
 
 
def close_jobs(db, board_id, exts, guard: Guard, now) -> int:
    """Jobs their employer took down: deleted - or, if someone acted on them, marked closed."""
    if not exts:
        return 0
    ids = [str(r[0]) for r in _x(db, "SELECT id FROM listings WHERE board_id = :b AND closed_at IS NULL AND external_id = ANY(CAST(:e AS text[]))",
                                 {"b": board_id, "e": list(exts)}).fetchall()]
    d, k = drop_listings(db, ids, guard, now)
    return d + k
 
 
def sync_skips(db, board_id, old: dict, new: dict, complete: bool):
    """Keep the set-aside list in step: new entries added, changed ones refreshed, and - when the
    whole list was read - entries for jobs no longer listed dropped. Reasons of unchanged entries stay."""
    drop = [e for e, s in old.items() if (complete and e not in new) or (e in new and new[e] != s)]
    add = {e: s for e, s in new.items() if old.get(e) != s}
    if drop:
        _x(db, "DELETE FROM employer_job_skips WHERE board_id = :b AND external_id = ANY(CAST(:e AS text[]))", {"b": board_id, "e": drop})
    if add:
        ex = list(add)
        _x(db, "INSERT INTO employer_job_skips (board_id, external_id, sig, reason, created_at) "
               "SELECT :b, e, s, 'not_kept', :t FROM unnest(CAST(:e AS text[]), CAST(:s AS text[])) AS x(e, s) "
               "ON CONFLICT (board_id, external_id) DO UPDATE SET sig = EXCLUDED.sig, reason = 'not_kept'",
           {"b": board_id, "e": ex, "s": [add[e] or "" for e in ex], "t": _now()})
 
 
def _next_due(now, status, fail_count=0, retry_after=None):
    if status == "active":
        return now + timedelta(hours=REFRESH_HOURS) + timedelta(minutes=random.randint(0, 240))
    if status == "empty":
        return now + timedelta(days=EMPTY_DAYS) + timedelta(minutes=random.randint(0, 600))
    if status in ("blocked", "too_big"):
        return now + timedelta(days=7)
    if status == "gone":
        return now + timedelta(days=3650)
    # a failure: back off 1 h, 2 h, 4 h ... up to 3 days, and never sooner than the feed asked
    hours = min(72, 2 ** max(0, fail_count - 1))
    if retry_after:
        hours = max(hours, min(72, retry_after / 3600.0))
    return now + timedelta(hours=hours) + timedelta(minutes=random.randint(0, 20))
 
 
def _soft_fail(db, board, why, hours, now):
    _x(db, "UPDATE employer_boards SET last_try_at = :t, fail_count = fail_count + 1, last_error = :e, next_due_at = :d WHERE id = :b",
       {"t": now, "e": why[:300], "d": now + timedelta(hours=hours), "b": board["id"]})
 
 
def apply_result(db, board: dict, held: dict, old_skips: dict, res, room, guard: Guard, now) -> dict:
    """Store one employer's read. Returns counts; room is a one-item list [remaining or None]."""
    st = {"added": 0, "updated": 0, "closed": 0, "full": 0}
    bid = board["id"]
    if res.status == "ok":
        open_held = [ext for ext, (lid, sig, closed) in held.items() if not closed]
        # a feed that suddenly lists nothing (or almost nothing) is confirmed on a second read before its jobs go
        sudden = (res.complete and not res.unchanged and len(open_held) >= 5 and
                  (len(res.seen) == 0 or (len(open_held) >= 20 and len(res.seen) < 0.1 * len(open_held))))
        if sudden and (board.get("last_error") or "") != "sudden_drop":
            _soft_fail(db, board, "sudden_drop", 2, now)
            db.commit()
            return st
        inserted = []
        for row in res.rows:
            have = held.get(row["external_id"])
            if have:
                update_row(db, have[0], row, now)
                st["updated"] += 1
                if have[2]:
                    st["added"] += 1          # reopened
            elif room[0] is None or room[0] > 0:
                inserted.append(row)
                if room[0] is not None:
                    room[0] -= 1
            else:
                st["full"] += 1
        new_ids = insert_rows(db, inserted, bid, now) if inserted else []
        st["added"] += len(new_ids)
        if new_ids:
            set_reposts(db, new_ids)
        if res.complete:
            gone = [ext for ext in open_held if ext not in res.seen]
            st["closed"] += close_jobs(db, bid, gone, guard, now)
        if res.skips != old_skips:
            sync_skips(db, bid, old_skips, res.skips, res.complete)
        # jobs of this employer we hold open now: the ones still listed that we had, plus the new ones stored
        kept = len([e for e in res.seen if e in held]) + len(new_ids)
        status = "active" if kept else "empty"
        clean = res.complete and not res.pending and not st["full"] and not res.detail_errors
        if res.pending and res.detail_errors >= res.pending:
            due = now + timedelta(hours=1)            # only failing detail calls are left: try those again in an hour
        elif res.pending:
            due = now                                 # the pass's budget ran out: carry on next tick
        else:
            due = _next_due(now, status)
        _x(db, "UPDATE employer_boards SET status = :s, company = coalesce(:c, company), jobs_live = coalesce(:l, jobs_live), jobs_kept = :k, "
               "last_ok_at = :t, last_try_at = :t, fail_count = 0, last_error = NULL, next_due_at = :d, feed_sig = :sig WHERE id = :b",
           {"s": status, "c": (res.company or None) and res.company[:200], "l": res.listed, "k": kept, "t": now, "d": due,
            "sig": (res.sig if clean else None), "b": bid})
    else:
        fails = int(board.get("fail_count") or 0) + 1
        prev = board.get("status") or "new"
        if res.status == "error" and "robots.txt" in (res.error or ""):
            # the host's robots.txt couldn't be read just now: not this employer's fault - look again soon
            _x(db, "UPDATE employer_boards SET last_try_at = :t, last_error = :e, next_due_at = :d WHERE id = :b",
               {"t": now, "e": res.error[:300], "d": now + timedelta(minutes=30 + random.randint(0, 30)), "b": bid})
            db.commit()
            return st
        if res.status == "dead":
            # a feed that was never there is gone at once; a live one has to be missing twice
            status = "gone" if (prev == "new" or fails >= 2) else "failing"
        elif res.status in ("blocked", "too_big"):
            status = res.status
        elif fails >= 3:
            status = "failing"
        else:
            status = prev if prev in ("new", "active", "empty", "failing") else "failing"
        if status in ("gone", "blocked"):
            # no longer readable (taken down, or the site asked us not to read it): its jobs go
            open_ext = [ext for ext, (lid, sig, closed) in held.items() if not closed]
            st["closed"] += close_jobs(db, bid, open_ext, guard, now)
        due = _next_due(now, status if status in ("gone", "blocked", "too_big") else "retry", fails, res.retry_after)
        _x(db, "UPDATE employer_boards SET status = :s, last_try_at = :t, fail_count = :f, last_error = :e, next_due_at = :d, feed_sig = NULL WHERE id = :b",
           {"s": status, "t": now, "f": fails, "e": (res.error or res.status)[:300], "d": due, "b": bid})
    db.commit()
    return st
 
 
def record_store_failure(db, board, err, now):
    """Storing a board's read failed (rolled back): note it and back off, so it isn't re-read every tick."""
    try:
        db.rollback()
        fails = int(board.get("fail_count") or 0) + 1
        _x(db, "UPDATE employer_boards SET last_try_at = :t, fail_count = :f, last_error = :e, next_due_at = :d, feed_sig = NULL, "
               "status = CASE WHEN status = 'new' AND :f >= 3 THEN 'failing' ELSE status END WHERE id = :b",
           {"t": now, "f": fails, "e": ("could not store: " + err)[:300], "d": _next_due(now, "retry", fails + 2), "b": board["id"]})
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
 
 
def close_stale(db, guard: Guard, now) -> int:
    """Employers we couldn't read for STALE_DAYS: their jobs can't be vouched for as live, so they go."""
    rows = _x(db, "SELECT l.board_id, l.external_id FROM listings l JOIN employer_boards b ON b.id = l.board_id "
                  "WHERE l.closed_at IS NULL AND b.ats <> 'usajobs' AND (b.last_ok_at IS NULL OR b.last_ok_at < :stale) LIMIT 5000",
              {"stale": now - timedelta(days=STALE_DAYS)}).fetchall()
    by = {}
    for b, e in rows:
        by.setdefault(b, []).append(e)
    n = 0
    for b, exts in by.items():
        n += close_jobs(db, b, exts, guard, now)
        db.commit()
    return n
 
 
def prune_skips(db) -> int:
    """Set-aside lists of employers we no longer read go; the whole list stays bounded."""
    n = 0
    got = _x(db, "DELETE FROM employer_job_skips s USING employer_boards b WHERE s.board_id = b.id AND b.status IN ('gone', 'blocked') "
                 "RETURNING 1").fetchall()
    n += len(got)
    total = int(_x(db, "SELECT count(*) FROM employer_job_skips").scalar() or 0)
    if total > SKIPS_MAX:
        got = _x(db, "DELETE FROM employer_job_skips WHERE ctid IN (SELECT ctid FROM employer_job_skips ORDER BY created_at ASC NULLS FIRST LIMIT :n) RETURNING 1",
                 {"n": total - SKIPS_MAX}).fetchall()
        n += len(got)
    db.commit()
    return n
 
 
def reindex_step(db, deadline) -> int:
    """After an engine / taxonomy update, re-read the selection keys of stored jobs, a batch at a time."""
    ver = index_version()
    st = state_get(db, STATE_INDEX)
    if not isinstance(st, dict):
        # first run: everything stored so far was keyed by this code
        state_set(db, STATE_INDEX, {"version": ver, "cursor": None, "done": True})
        db.commit()
        return 0
    if st.get("version") == ver and st.get("done"):
        return 0
    if st.get("version") != ver:
        st = {"version": ver, "cursor": None, "done": False}
    done = 0
    while time.monotonic() < deadline:
        rows = _x(db, "SELECT id, title, org, location, body_z, type FROM listings WHERE board_id IS NOT NULL AND closed_at IS NULL "
                      "AND (CAST(:c AS uuid) IS NULL OR id > CAST(:c AS uuid)) ORDER BY id LIMIT :n",
                  {"c": st.get("cursor"), "n": REINDEX_BATCH}).fetchall()
        if not rows:
            st["done"] = True
            break
        ids, keys = [], []
        for r in rows:
            ids.append(str(r[0]))
            keys.append("|".join(EF.feed_keys(r[1] or "", r[2] or "", r[3] or "", decompress_text(r[4]), None, r[5] or "job")))
        _x(db, "UPDATE listings l SET feed_keys = string_to_array(x.k, '|') FROM unnest(CAST(:ids AS uuid[]), CAST(:ks AS text[])) AS x(id, k) "
               "WHERE l.id = x.id", {"ids": ids, "ks": keys})
        st["cursor"] = ids[-1]
        done += len(ids)
        state_set(db, STATE_INDEX, st)
        db.commit()
    state_set(db, STATE_INDEX, st)
    db.commit()
    return done
 
 
# ------------------------------------------------------------------ USAJOBS (paged, one cycle a day)
def usajobs_step(db, fetcher, deadline, room, guard: Guard, now_fn=time.monotonic) -> dict:
    st = {"added": 0, "updated": 0, "closed": 0, "pages": 0}
    if not EF.usajobs_configured():
        return st
    b = _x(db, "SELECT " + _BOARD_COLS + ", next_due_at FROM employer_boards WHERE ats = 'usajobs' LIMIT 1").mappings().first()
    if not b:
        return st
    b = dict(b)
    now = _now()
    cur = state_get(db, STATE_USAJOBS) or {}
    if not cur.get("cycle_start"):
        if b.get("next_due_at") and b["next_due_at"] > now:
            return st
        cur = {"cycle_start": _iso(now), "prev_start": cur.get("last_start"), "page": 1, "pages": None}
    held, skips = board_state(db, b["id"])
    while now_fn() < deadline:
        job = EF.BoardJob(b["id"], "usajobs", b["slug"], "USAJOBS", {e: v[1] for e, v in held.items() if not v[2]}, skips,
                          EF.DetailBudget(0), now)
        res, pages = EF.read_usajobs_page(fetcher, job, int(cur["page"]))
        if res.status != "ok":
            apply_result(db, b, held, skips, res, room, guard, now)
            break
        cur["pages"] = pages
        res.complete = False
        part = apply_result(db, b, held, skips, res, room, guard, now)
        for k in ("added", "updated"):
            st[k] += part[k]
        if res.seen:
            _x(db, "UPDATE listings SET last_seen_at = :t WHERE board_id = :b AND external_id = ANY(CAST(:e AS text[]))",
               {"t": now, "b": b["id"], "e": list(res.seen)})
            db.commit()
        st["pages"] += 1
        held, skips = board_state(db, b["id"])
        cur["page"] = int(cur["page"]) + 1
        if cur["page"] > pages:
            # the whole public list was read. Closed now: jobs past their closing date, and jobs missing from
            # this cycle AND the one before (results shift between pages while a cycle runs, so one miss isn't proof)
            prev = (datetime.strptime(cur["prev_start"], "%Y-%m-%dT%H:%M:%SZ") - timedelta(hours=1)) if cur.get("prev_start") else None
            gone = [r[0] for r in _x(db, "SELECT external_id FROM listings WHERE board_id = :b AND closed_at IS NULL AND "
                                         "((deadline IS NOT NULL AND deadline < :today) OR "
                                         "(CAST(:prev AS timestamp) IS NOT NULL AND (last_seen_at IS NULL OR last_seen_at < CAST(:prev AS timestamp))))",
                                     {"b": b["id"], "today": now.date(), "prev": prev}).fetchall()]
            st["closed"] += close_jobs(db, b["id"], gone, guard, now)
            _x(db, "UPDATE employer_boards SET next_due_at = :d WHERE id = :b", {"d": _next_due(now, "active"), "b": b["id"]})
            cur = {"last_start": cur["cycle_start"]}
            break
    state_set(db, STATE_USAJOBS, cur)
    db.commit()
    return st
 
 
# ------------------------------------------------------------------ coverage
def compute_coverage(db, cap_info=None) -> dict:
    now = _now()
    row = _x(db, "SELECT count(*) AS jobs, count(DISTINCT l.board_id) AS employers, "
                 "count(*) FILTER (WHERE (CASE WHEN b.ats = 'usajobs' THEN l.last_seen_at ELSE b.last_ok_at END) >= :fresh) AS fresh "
                 "FROM listings l JOIN employer_boards b ON b.id = l.board_id WHERE l.closed_at IS NULL",
             {"fresh": now - timedelta(hours=24)}).fetchone()
    by_source = {r[0]: int(r[1]) for r in _x(db, "SELECT source, count(*) FROM listings WHERE board_id IS NOT NULL AND closed_at IS NULL GROUP BY source").fetchall()}
    boards = {r[0]: int(r[1]) for r in _x(db, "SELECT status, count(*) FROM employer_boards GROUP BY status").fetchall()}
    jobs, employers, fresh = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
    cov = {
        "jobs": jobs, "employers": employers, "checked_24h": fresh,
        "checked_24h_pct": round(100.0 * fresh / jobs, 1) if jobs else None,
        "by_source": by_source, "boards": boards, "as_of": _iso(now),
    }
    if cap_info:
        cov["storage"] = {k: cap_info.get(k) for k in ("db_mb", "cap", "ceiling_mb")}
    state_set(db, STATE_COVERAGE, cov)
    db.commit()
    return cov
 
 
def coverage_cached(db) -> dict | None:
    try:
        with db.begin_nested():
            return state_get(db, STATE_COVERAGE)
    except Exception:
        return None
 
 
# ------------------------------------------------------------------ one tick
def run_feed_tick(budget_s: float | None = None, session_factory=None, fetcher=None) -> dict:
    """A few minutes of crawling. Never raises; returns what it did."""
    if not enabled():
        return {"ran": False, "reason": "FEEDS_ENABLED is off"}
    if not _local_running.acquire(blocking=False):
        return {"ran": False, "reason": "a tick is already running in this process"}
    db = None
    owner = {"pid": os.getpid(), "id": uuid.uuid4().hex[:8]}
    try:
        if session_factory is None:
            from app.db import SessionLocal
            session_factory = SessionLocal
        db = session_factory()
        if not schema_ready(db):
            return {"ran": False, "reason": "the employer-feed tables are missing - run db/RUN_THIS_migration.sql"}
        if not _lease(db, owner):
            return {"ran": False, "reason": "another tick is running"}
        try:
            return _tick(db, budget_s or TICK_BUDGET_S, fetcher)
        except GuardUnavailable as e:
            log.warning("employer-feed tick stopped: %s", e)
            return {"ran": False, "reason": "couldn't check which jobs people saved or applied to - nothing was changed (%s)" % e}
        finally:
            _release(db, owner)
    except Exception as e:
        log.exception("employer-feed tick failed")
        try:
            if db is not None:
                db.rollback()
        except Exception:
            pass
        return {"ran": False, "error": type(e).__name__}
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        _local_running.release()
 
 
def _tick(db, budget_s, fetcher=None) -> dict:
    t0 = time.monotonic()
    deadline = t0 + budget_s
    own_fetcher = fetcher is None
    f = fetcher or EF.Fetcher()
    summary = {"ran": True, "boards": 0, "unchanged": 0, "added": 0, "updated": 0, "closed": 0, "full": 0, "errors": 0, "pending": 0}
    try:
        guard = Guard(db)                         # raises GuardUnavailable: then nothing at all is changed
        cap = capacity(db, guard)
        summary["capacity"] = cap
        room = [cap["room"]]
        waiting = int(_x(db, "SELECT count(*) FROM employer_boards WHERE status = 'new'").scalar() or 0)
        if waiting < 300:
            summary["discovered"] = discover(db, f, min(deadline, time.monotonic() + budget_s * 0.25))
        if EF.usajobs_configured() and time.monotonic() < deadline:
            u = usajobs_step(db, f, min(deadline, time.monotonic() + budget_s * 0.2), room, guard)
            for k in ("added", "updated", "closed"):
                summary[k] += u[k]
            summary["usajobs_pages"] = u["pages"]
        n_new = 0 if (room[0] is not None and room[0] <= 0) else 40
        boards = due_boards(db, 160, n_new)
        stop_at = deadline - 15
        details = EF.DetailBudget(DETAILS_PER_TICK, deadline=stop_at)
        now = _now()
        pending_futs = {}
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            queue = list(boards)
            while queue or pending_futs:
                while queue and len(pending_futs) < WORKERS * 2 and time.monotonic() < stop_at:
                    b = queue.pop(0)
                    held, skips = board_state(db, b["id"])
                    job = EF.BoardJob(b["id"], b["ats"], b["slug"], b.get("company"),
                                      {e: v[1] for e, v in held.items() if not v[2]}, skips,
                                      EF.DetailBudget(DETAILS_PER_BOARD, details, deadline=stop_at), now, last_sig=b.get("feed_sig"))
                    pending_futs[pool.submit(EF.read_board, f, job)] = (b, held, skips)
                if not pending_futs:
                    break
                done, _ = wait(list(pending_futs), timeout=5, return_when=FIRST_COMPLETED)
                for fut in done:
                    b, held, skips = pending_futs.pop(fut)
                    try:
                        res = fut.result()
                        part = apply_result(db, b, held, skips, res, room, guard, _now())
                    except GuardUnavailable:
                        raise
                    except Exception as e:
                        log.exception("storing employer feed %s/%s failed", b.get("ats"), b.get("slug"))
                        record_store_failure(db, b, type(e).__name__ + ": " + str(e)[:200], _now())
                        summary["errors"] += 1
                        continue
                    summary["boards"] += 1
                    if res.unchanged:
                        summary["unchanged"] += 1
                    if res.status != "ok":
                        summary["errors"] += 1
                    summary["pending"] += res.pending
                    for k in ("added", "updated", "closed", "full"):
                        summary[k] += part[k]
        summary["closed"] += close_stale(db, guard, _now())
        summary["skips_pruned"] = prune_skips(db)
        if time.monotonic() < deadline:
            summary["reindexed"] = reindex_step(db, deadline)
        summary["coverage"] = compute_coverage(db, cap)
        summary["requests"] = f.requests
        summary["seconds"] = round(time.monotonic() - t0, 1)
        log.info("employer feeds: %s", json.dumps({k: v for k, v in summary.items() if k != "coverage"}, default=str))
        return summary
    finally:
        if own_fetcher:
            f.close()
 
 
# ------------------------------------------------------------------ background start (for the route)
_bg_thread = None
 
 
def start_tick_in_background(budget_s: float | None = None) -> bool:
    """Start a tick on its own thread unless one is already running here. True if started."""
    global _bg_thread
    if _bg_thread is not None and _bg_thread.is_alive():
        return False
    _bg_thread = threading.Thread(target=run_feed_tick, kwargs={"budget_s": budget_s}, daemon=True, name="feed-tick")
    _bg_thread.start()
    return True
 
