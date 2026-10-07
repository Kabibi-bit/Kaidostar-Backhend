"""Job Search v2 - the server side of the "Proof Match" engine.
 
The browser runs job-engine.js over the pool this module serves. Whenever the
server has to decide something on its own - Auto mode, saved-search alerts,
the /listings/matches feed other pages read - it runs the identical Python
port (job_engine.py) on the identical inputs, so a job reads the same fit in
every corner of the product. (tests/test_job_engine_parity.py proves the two
engines agree field for field.)
 
Nothing here invents a number: every fit comes from the posting's text and
the user's own profile, resume entries and saved preferences.
"""
import copy
import json
import os
import threading
import time
from datetime import date, timedelta
 
from app.services import job_engine as JE
from app.services.timeutil import to_naive_utc, utcnow
 
STATE_KIND = "job_search_state"     # one workshop_items row per user: prefs, learned rules, saved searches, applied ids
POOL_TYPES = ("job", "internship", "college")
POOL_LIMIT = 800
DESC_LIMIT = 12000                  # the pool ships exactly this text and the server scores exactly this text
AUTO_TOP_N = 10
ALERT_MIN_FIT = 70
SEARCH_CAP = 20                     # saved searches per user (the browser's own limit)
KNOWN_CAP = 800                     # job ids each saved search remembers having announced - the whole pool, so none is announced twice
ALERT_MAX_AGE_DAYS = 14             # only jobs posted in the last two weeks can trigger an alert (same rule as the page)
ALERT_BUDGET_S = 12.0               # one user's saved-search alerts get this much time per scan; the rest run first next time
# the stored record's size budget: 20 searches x 500 remembered ids plus filters fit with room to spare
STATE_MAX_CHARS = 1_000_000
# Listings added by hand (POST /listings/manual) are never delivered to an employer
# unattended: Auto may draft for them, but a person submits.
HAND_ADDED_SOURCES = ("manual",)
 
# What one stored search state may hold - the page's own limits, so a hand-made record
# can't cost the scheduler minutes per user (every list is also the engine's own cap).
STATE_KEYS = ("v", "prefs", "learned", "searches", "applied", "updatedAt", "dbSig")   # "rev" is the server's own
SEARCH_NUM_KEYS = ("v", "baseAt", "created", "newCount", "newAt", "seenNewAt", "lastOpened", "lastCount", "lastCheck", "minFit")
LEARNED_KINDS = ("block_company", "level_above", "level_below", "avoid_place", "salary_floor", "avoid_role", "avoid_skill", "like_role", "avoid_type")
LEARNED_CAP = 40                    # the page keeps the 40 newest learned rules
APPLIED_CAP = 500                   # the page keeps the 500 newest applied ids
ROLES_CAP = 20
ITEM_CHARS = 80                     # one filter value (a company, a keyword, a phrase) - the page's own input limit
LABEL_CHARS = 200                   # a learned rule's label, a search's ignored note
TEXT_CHARS = 500                    # one free-text setting (your locations line)
 
 
# ------------------------------------------------------------------ shaping
def _iso(dt):
    dt = to_naive_utc(dt)
    if dt is None:
        return None
    try:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (AttributeError, ValueError):
        return None
 
 
def listing_for_engine(l) -> dict:
    """A Listing row in the engine's input shape (also the /listings/pool shape)."""
    deadline = getattr(l, "deadline", None)
    return {
        "id": str(l.id),
        "type": l.type or "job",
        "title": l.title or "",
        "org": l.org or "",
        "location": l.location or "",
        "description": (l.description or "")[:DESC_LIMIT],
        "posted_at": _iso(getattr(l, "posted_at", None)),
        "first_seen_at": _iso(getattr(l, "fetched_at", None)),
        "last_seen_at": _iso(getattr(l, "last_seen_at", None)),
        "seen_count": getattr(l, "seen_count", None),
        "repost_count": getattr(l, "repost_count", None) or 0,
        "salary_min": getattr(l, "salary_min", None),
        "salary_max": getattr(l, "salary_max", None),
        "salary_is_predicted": getattr(l, "salary_is_predicted", None),
        "salary_period": getattr(l, "salary_period", None),
        "employment_type": getattr(l, "employment_type", None),
        "contract_type": getattr(l, "contract_type", None),
        "apply_url": l.apply_url or "",
        "source": l.source or "",
        "deadline": deadline.isoformat() if deadline else None,
        "tags": [str(t) for t in (l.tags or [])][:30],
    }
 
 
def profile_for_engine(p) -> dict:
    """The fields of a Profile the engine reads (same names the browser uses)."""
    if p is None:
        return {}
    goal2 = getattr(p, "final_idea", None) or ""
    return {
        "northstar": getattr(p, "northstar", None) or "",
        "final_idea": goal2,
        "finalidea": goal2,
        "skills": getattr(p, "skills", None) or "",
        "stage": getattr(p, "stage", None) or "",
        "loc": getattr(p, "location_pref", None) or "",
        "types": [str(t) for t in (getattr(p, "target_types", None) or [])],
        "dealbreakers": getattr(p, "dealbreakers", None) or "",
        "priorities": [str(x) for x in (getattr(p, "priorities", None) or [])],
    }
 
 
def entries_for_engine(rows) -> list:
    out = []
    for r in sorted(rows or [], key=lambda e: (getattr(e, "display_order", 0) or 0)):
        out.append({
            "entry_type": getattr(r, "entry_type", None) or "work",
            "title": getattr(r, "title", None) or "",
            "org": getattr(r, "org", None) or "",
            "start_date": getattr(r, "start_date", None) or "",
            "end_date": getattr(r, "end_date", None) or "",
            "raw_description": getattr(r, "raw_description", None) or "",
        })
    return out
 
 
def _now_ms():
    return int(time.time() * 1000)
 
 
# ------------------------------------------------------------------ storage
def state_row(db, user_id, lock: bool = False, strict: bool = False):
    """The user's one search-state record. If an older client ever left a
    second one, the most recently updated wins - never an arbitrary pick.
    Always the database's current copy: populate_existing() makes the session
    overwrite an object it loaded earlier in this transaction (a scan that read
    the record seconds ago would otherwise keep that old copy, and write it
    back over an edit the user saved since).
    lock=True holds the row (SELECT ... FOR UPDATE) until the next commit."""
    from app.models.db_models import WorkshopItem
    try:
        q = db.query(WorkshopItem).filter(WorkshopItem.user_id == user_id, WorkshopItem.kind == STATE_KIND)
        try:
            q = q.order_by(WorkshopItem.updated_at.desc().nullslast(), WorkshopItem.created_at.desc().nullslast())
        except Exception:
            pass
        try:
            q = q.populate_existing()
        except Exception:
            pass
        if lock:
            try:
                q = q.with_for_update()
            except Exception:
                pass
        return q.first()
    except Exception:
        if strict:
            raise
        return None
 
 
def load_state_checked(db, user_id):
    """(state, ok). ok is False when the record couldn't be read (a database error) -
    the page must never mistake that for "this account has no settings yet" (it would
    then merge against nothing and bring back what other devices deleted)."""
    try:
        row = state_row(db, user_id, strict=True)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None, False
    data = getattr(row, "data", None) if row is not None else None
    return (copy.deepcopy(data) if isinstance(data, dict) else {}), True
 
 
def load_state(db, user_id) -> dict:
    """A private copy of the user's search state. Never the row's own dict:
    editing that in place would leave the ORM seeing "no change" on save, and
    the alert bookkeeping would silently never be stored."""
    row = state_row(db, user_id)
    data = getattr(row, "data", None) if row is not None else None
    return copy.deepcopy(data) if isinstance(data, dict) else {}
 
 
# ------------------------------------------------------------------ the stored record's shape
_BAD = object()
 
 
def _clean_scalar(v, chars=TEXT_CHARS):
    """A JSON scalar as the engine reads it (strings trimmed); anything else is _BAD."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v[:chars]
    if isinstance(v, (int, float)) and v == v and v not in (float("inf"), float("-inf")):
        return v
    return _BAD
 
 
def _clean_list(v, cap, chars=ITEM_CHARS, keep="first") -> list:
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        c = _clean_scalar(x, chars)
        if c is _BAD or c is None:
            continue
        out.append(c)
    return out[-cap:] if keep == "last" else out[:cap]
 
 
def _clean_prefs(src, partial: bool = False) -> dict:
    """Filters in the engine's own shape: only the keys the engine knows, scalars
    as JSON scalars (strings trimmed), every list at the engine's own cap. A full
    record (partial=False) has every key, with the defaults for anything missing -
    exactly what merge_prefs gives the engine. A search's patch (partial=True)
    keeps only the keys it set."""
    defaults = JE.default_prefs()
    out = {} if partial else defaults
    if not isinstance(src, dict):
        return out
    for k, v in src.items():
        if k not in defaults or k == "v":
            continue
        d = defaults[k]
        if k == "weights":
            if isinstance(v, dict):
                out["weights"] = {wk: (JE.clamp(v[wk], 0, 100) if JE.isnum(v.get(wk)) else defaults["weights"][wk]) for wk in defaults["weights"]}
            continue
        if isinstance(d, list):
            if isinstance(v, list):
                out[k] = _clean_list(v, JE.PREF_LIST_CAP)
            continue
        c = _clean_scalar(v)
        if c is not _BAD:
            out[k] = c
    return out
 
 
def _clean_learned(rules) -> list:
    out = []
    for r in (rules if isinstance(rules, list) else []):
        if not isinstance(r, dict) or r.get("kind") not in LEARNED_KINDS:
            continue
        val = _clean_scalar(r.get("value"), ITEM_CHARS)
        if val is _BAD or val is None:
            continue
        c = {"kind": r["kind"], "value": val}
        for k, n in (("id", 120), ("label", LABEL_CHARS)):
            if isinstance(r.get(k), str):
                c[k] = r[k][:n]
        if isinstance(r.get("active"), bool):
            c["active"] = r["active"]
        if JE.isnum(r.get("createdAt")):
            c["createdAt"] = r["createdAt"]
        src = r.get("source")
        if isinstance(src, dict):
            c["source"] = {k: str(src.get(k))[:LABEL_CHARS] for k in ("title", "org", "reason") if isinstance(src.get(k), str)}
        out.append(c)
    return out[-LEARNED_CAP:]
 
 
def _clean_search(s):
    if not isinstance(s, dict) or not isinstance(s.get("id"), (str, int)) or isinstance(s.get("id"), bool):
        return None
    c = {"id": str(s["id"])[:64]}
    if isinstance(s.get("name"), str):
        c["name"] = s["name"][:60]
    if isinstance(s.get("raw"), str):
        c["raw"] = s["raw"][:300]
    if isinstance(s.get("alert"), bool):
        c["alert"] = s["alert"]
    for k in SEARCH_NUM_KEYS:
        if JE.isnum(s.get(k)):
            c[k] = s[k]
    if isinstance(s.get("patch"), dict):
        c["patch"] = _clean_prefs(s["patch"], partial=True)
        if s["patch"].get("salaryUnit") == "hour":   # "$30/hr+" stays an hourly chip on every device
            c["patch"]["salaryUnit"] = "hour"
    if isinstance(s.get("roles"), list):
        c["roles"] = [r for r in _clean_list(s["roles"], ROLES_CAP, 60) if isinstance(r, str)]
    if isinstance(s.get("base"), dict):
        c["base"] = _clean_prefs(s["base"])
    if "known" in s:
        c["known"] = merge_known([], [k for k in (s.get("known") or []) if isinstance(k, (str, int)) and not isinstance(k, bool) and len(str(k)) <= 64]
                                 if isinstance(s.get("known"), list) else [])
    if isinstance(s.get("ignored"), list):
        c["ignored"] = [x for x in _clean_list(s["ignored"], 12, 120) if isinstance(x, str)]
    if isinstance(s.get("ignoredWhy"), dict):
        c["ignoredWhy"] = {str(k)[:120]: v[:20] for k, v in list(s["ignoredWhy"].items())[:12] if isinstance(v, str)}
    return c
 
 
def sanitize_state(data) -> dict:
    """The record exactly as the page and the engine use it, at the page's own
    limits: filters in the engine's shape, at most 20 saved searches (each
    remembering at most 500 announced ids), the 40 newest learned rules and the
    500 newest applied ids. Unknown keys are dropped. A record the page itself
    wrote comes through unchanged; a hand-made one can't cost the scheduler more
    than a normal user's."""
    data = data if isinstance(data, dict) else {}
    out = {}
    if JE.isnum(data.get("v")):
        out["v"] = data["v"]
    if isinstance(data.get("prefs"), dict):
        out["prefs"] = _clean_prefs(data["prefs"])
    if "learned" in data:
        out["learned"] = _clean_learned(data.get("learned"))
    if "searches" in data:
        seen, searches = set(), []
        for s in (data.get("searches") if isinstance(data.get("searches"), list) else []):
            c = _clean_search(s)
            if c is None or c["id"] in seen:
                continue
            seen.add(c["id"])
            searches.append(c)
            if len(searches) >= SEARCH_CAP:
                break
        out["searches"] = searches
    if "applied" in data:
        out["applied"] = [str(x) for x in _clean_list(data.get("applied"), APPLIED_CAP, 64, keep="last")]
    if isinstance(data.get("updatedAt"), str):
        out["updatedAt"] = data["updatedAt"][:40]
    if isinstance(data.get("dbSig"), str):
        out["dbSig"] = data["dbSig"][:4000]
    return out
 
 
def _flag_modified(row):
    try:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(row, "data")
    except Exception:
        pass
 
 
def _int(v) -> int:
    try:
        return int(v) if v is not None and not isinstance(v, bool) else 0
    except (TypeError, ValueError, OverflowError):
        return 0
 
 
def _num(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return 0
    return v
 
 
def merge_known(a, b, pool_ids=None) -> list:
    """What a saved search has already announced: the union of two lists
    (oldest first, newest kept when trimmed), never a replacement - so neither
    the page nor the server can make the other announce a job twice. Ids that
    have left a live pool can't come back, so they're dropped to keep the
    record small."""
    out, seen = [], set()
    for x in list(a if isinstance(a, list) else []) + list(b if isinstance(b, list) else []):
        if x is None or isinstance(x, (dict, list)):
            continue
        k = str(x)
        if k not in seen:
            seen.add(k)
            out.append(k)
    if pool_ids:
        out = [k for k in out if k in pool_ids]
    return out[-KNOWN_CAP:]
 
 
def merge_incoming_state(incoming: dict, stored) -> dict:
    """The page's copy of the state is about to replace the stored one. The
    page wins for everything the user edits - filters, rules, which searches
    exist, names, thresholds (a stale copy never gets this far: the save is
    refused when it was based on an older revision). The alert bookkeeping is
    merged: what was already announced is a union, and an unread count the
    server added after the page last looked at the search survives - so a tab
    left open since before the nightly run can't make anyone announce the same
    job twice, or lose the "3 new" badge.
 
    "Last looked" is the server's own newAt the page had seen when the search
    was opened (seenNewAt) - one clock, so a browser whose clock runs slow can
    still clear the badge. Pages from before seenNewAt send lastOpened instead."""
    out = dict(incoming) if isinstance(incoming, dict) else {}
    if not isinstance(out.get("searches"), list):
        return out
    old = {}
    if isinstance(stored, dict) and isinstance(stored.get("searches"), list):
        for s in stored["searches"]:
            if isinstance(s, dict) and s.get("id") is not None:
                old[str(s.get("id"))] = s
    merged = []
    for s in [x for x in out["searches"] if isinstance(x, dict)][:SEARCH_CAP]:
        s = dict(s)
        o = old.get(str(s.get("id"))) if s.get("id") is not None else None
        if o is None:
            s["known"] = merge_known([], s.get("known"))
        else:
            s["known"] = merge_known(o.get("known"), s.get("known"))
            o_new_at = _num(o.get("newAt"))
            seen = s.get("seenNewAt") if "seenNewAt" in s else s.get("lastOpened")
            if o_new_at > _num(seen):
                # the server found new matches after this page last opened the search
                s["newCount"] = max(_int(s.get("newCount")), _int(o.get("newCount")))
            if o_new_at > _num(s.get("newAt")):
                s["newAt"] = o.get("newAt")
            if _num(o.get("lastCheck")) > _num(s.get("lastCheck")):
                s["lastCheck"], s["lastCount"] = o.get("lastCheck"), o.get("lastCount")
        merged.append(s)
    out["searches"] = merged
    return out
 
 
def _search_sig(s) -> str:
    """What decides a saved search's alerts - its filters, roles and threshold."""
    try:
        return json.dumps([s.get("base"), s.get("patch"), s.get("roles"), s.get("minFit")], sort_keys=True, default=str)
    except Exception:
        return ""
 
 
def alert_what(n: int, min_fit: int = ALERT_MIN_FIT) -> str:
    """"3 new strong matches" - "strong" only means 70+; a search set lower says
    what it really is ("3 new matches at 55+"), exactly as the page words it."""
    if min_fit >= 70:
        return f"{n} new strong match{'es' if n != 1 else ''}"
    return f"{n} new match{'es' if n != 1 else ''} at {min_fit}+"
 
 
def save_alert_updates(db, user_id, results: dict, notify: bool = True) -> int:
    """Decides what is new and remembers it, on the newest copy of the record
    (re-read under a row lock, so nothing can change between the decision and
    the write):
    - a search the user deleted, or switched alerts off for, while the scan ran
      is skipped - never notified, never brought back;
    - a job counts as new only if neither this scan nor the page (since) has
      already announced it - checked against the "known" list read under the lock;
    - only the bookkeeping is written (known ids, unread count, last check), so
      any edit the user made while the scan ran stays exactly as they left it.
    Posts one Inbox notification per search with new matches (unless notify is
    False - the user muted scan notifications) and commits. Returns how many new
    matches were announced.
    results: {search_id: {"strong": [{"ids", "age", "title", "org", "fit"}...], "now": ms, "pool": set|None}}"""
    from app.models.db_models import Notification
    if not results:
        return 0
    row = state_row(db, user_id, lock=True)
    if row is None or not isinstance(getattr(row, "data", None), dict):
        db.commit()   # releases the lock (nothing to write)
        return 0
    data = copy.deepcopy(row.data)
    searches = data.get("searches") if isinstance(data.get("searches"), list) else []
    announced = 0
    for s in searches:
        if not isinstance(s, dict) or not s.get("alert"):
            continue
        r = results.get(str(s.get("id")))
        if not r:
            continue
        strong = r.get("strong") or []
        if r.get("sig") is not None and _search_sig(s) != r["sig"]:
            continue   # edited while the pass ran (threshold, filters): judged with its new settings next time
        kn = s.get("known") if isinstance(s.get("known"), list) else []   # a malformed record never stops the pass
        known = set(str(k) for k in kn if not isinstance(k, (dict, list)))
        fresh = [it for it in strong
                 if not any(i in known for i in it["ids"])
                 and it.get("age") is not None and it["age"] <= ALERT_MAX_AGE_DAYS]
        if fresh and notify:
            name = str(s.get("name") or "Saved search")[:60]
            db.add(Notification(
                user_id=user_id, type="scan",
                title=f"“{name}”: {alert_what(len(fresh), r.get('min_fit') or ALERT_MIN_FIT)}",
                detail=" · ".join(f"{it['title']} at {it['org']} (fit {it['fit']})" for it in fresh[:3])[:500],
            ))
        announced += len(fresh)
        now_ids = [i for it in strong for i in it["ids"]]
        # never pruned against this pass's pool snapshot: a job the page announced after the
        # snapshot was taken would be forgotten, then announced again (the cap bounds the size)
        s["known"] = merge_known(s.get("known"), now_ids)
        if fresh:
            s["newCount"] = _int(s.get("newCount")) + len(fresh)
            # never earlier than an alert time already recorded or seen (a device clock running ahead)
            s["newAt"] = max(r["now"], _num(s.get("newAt")) + 1, _num(s.get("seenNewAt")) + 1)
        s["lastCheck"] = r["now"]
        s["lastCount"] = len(strong)
    data["searches"] = searches
    row.data = data
    _flag_modified(row)
    db.commit()
    return announced
 
 
def pool_rows(db, limit: int = POOL_LIMIT):
    """The listings a candidate searches: jobs, internships and programs, newest
    (by the employer's own posting date when known) first, never past their
    deadline."""
    from sqlalchemy import func, or_
    from app.models.db_models import Listing
    yesterday = date.today() - timedelta(days=1)
    q = db.query(Listing)
    try:   # the engine never reads the 512-d embedding - don't load it 800 times
        from sqlalchemy.orm import defer
        q = q.options(defer(Listing.embedding))
    except Exception:
        pass
    from app.services.feed_common import not_feed
    return (
        q
        .filter(Listing.type.in_(POOL_TYPES))
        .filter(not_feed(Listing))   # employer-feed jobs are picked per person (feed_dicts), never as "the newest 800"
        .filter(or_(Listing.deadline.is_(None), Listing.deadline >= yesterday))
        .order_by(func.coalesce(Listing.posted_at, Listing.fetched_at).desc())
        .limit(limit)
        .all()
    )
 
 
def _id_set(rows, attr="listing_id"):
    return {str(getattr(r, attr)) for r in rows or []}
 
 
def pool_dicts(db, limit: int = POOL_LIMIT) -> list:
    """The pool already in the engine's shape. The scheduler builds this once per
    cycle: plain dicts don't expire when a user's scan commits, so 800 listings
    never turn into 800 lazy re-loads per user."""
    return [listing_for_engine(l) for l in pool_rows(db, limit)]
 
 
# ------------------------------------------------------------------ employer-feed jobs for one person
FEED_POOL_LIMIT = int(os.getenv("FEED_POOL_LIMIT", "600"))        # what the page gets on top of the shared pool
FEED_SERVER_LIMIT = int(os.getenv("FEED_SERVER_LIMIT", "400"))    # what Auto and alerts score on the server
FEED_PER_EMPLOYER = 25                                            # no single employer fills someone's pool
FEED_ADJ_MIN = 0.5                                                # neighbouring role families this close are worth a look
FEED_STALE_DAYS = 4                                               # an employer not re-read for this long: its jobs aren't vouched for
 
 
def _adjacent_roles(role_ids) -> list:
    out = []
    for a, b, w in JE.TAX.get("role_adj") or []:
        if w is None or w < FEED_ADJ_MIN:
            continue
        if a in role_ids and b not in role_ids:
            out.append(b)
        elif b in role_ids and a not in role_ids:
            out.append(a)
    return list(dict.fromkeys(out))
 
 
def feed_want(prof, entries, prefs, query=None) -> dict:
    """Who to look for in the employer pool - read with the engine's own candidate reader, so it
    names the same role families and places the scoring will: the roles you aim for (and the ones
    a search on the page names), then neighbouring families and the ones your own work history
    is in; where you'd work (or anywhere / remote); jobs or internships as your profile says."""
    query = query if isinstance(query, dict) else {}
    try:
        cand = JE.build_candidate(prof or {}, entries or [], JE.merge_prefs(prefs or {}, None), _now_ms())
    except Exception:
        cand = {"roles": [], "location": {}}
    goal = [r["id"] for r in cand.get("roles") or [] if isinstance(r, dict) and r.get("id")]
    q_roles = [r for r in (query.get("roles") or []) if isinstance(r, str) and r in JE.idx().role]
    primary = list(dict.fromkeys(q_roles or goal))
    history = []
    for e in entries or []:
        if isinstance(e, dict) and (e.get("entry_type") or "work") in ("work", "internship", "volunteer"):
            for r in JE.find_roles(e.get("title") or "")[:1]:
                history.append(r["id"])
    secondary = [r for r in dict.fromkeys(_adjacent_roles(primary) + history + ([] if not q_roles else goal)) if r not in primary]
    loc = cand.get("location") or {}
    if isinstance(query.get("loc"), str) and query["loc"].strip():
        loc = JE.parse_user_location(query["loc"])
    modes = [m for m in (query.get("modes") or []) if m in ("remote", "hybrid", "onsite")]
    excl = set(m for m in ((prefs or {}).get("excludeModes") or []) if isinstance(m, str))   # "never" work modes
    places = None                                   # None = anywhere
    if modes == ["remote"] or loc.get("remoteOnly"):
        places = ["w:remote"]
    elif loc.get("metros") or loc.get("states"):
        places = ["m:" + m for m in loc.get("metros") or []] + ["s:" + st for st in loc.get("states") or []]
        if "remote" not in excl:
            places.append("w:remote")
    if loc.get("anywhere") and places != ["w:remote"]:
        places = None
    types = [t for t in (prof or {}).get("types") or [] if t in ("job", "internship")] or ["job", "internship"]
    kw = [w.strip() for w in (query.get("keywords") or []) if isinstance(w, str) and 2 < len(w.strip()) <= 40][:6]
    return {"primary": primary, "secondary": secondary, "places": places, "types": types, "keywords": kw}
 
 
_EMPLOYER = "CASE WHEN l.source = 'usajobs' THEN 'u:' || l.org ELSE 'b:' || l.board_id END"   # one federal feed, many agencies
 
 
def _feed_ids(db, want, limit, since=None) -> list:
    from sqlalchemy import text
    # only jobs still open, not past their closing date, from an employer we re-read recently
    conds = ["l.board_id IS NOT NULL", "l.closed_at IS NULL", "l.feed_keys && CAST(:types AS text[])",
             "(l.deadline IS NULL OR l.deadline >= :today)",
             "EXISTS (SELECT 1 FROM employer_boards b WHERE b.id = l.board_id AND "
             "(CASE WHEN b.ats = 'usajobs' THEN l.last_seen_at ELSE b.last_ok_at END) >= :fresh)"]
    now = utcnow()
    params = {"types": ["t:" + t for t in want["types"]], "n": int(limit), "per": FEED_PER_EMPLOYER,
              "r1": ["r:" + r for r in want["primary"]], "r2": ["r:" + r for r in want["secondary"]],
              "today": (now - timedelta(days=1)).date(), "fresh": now - timedelta(days=FEED_STALE_DAYS)}
    if want["places"] is not None:
        conds.append("l.feed_keys && CAST(:places AS text[])")
        params["places"] = want["places"]
    if since is not None:
        conds.append("coalesce(l.posted_at, l.fetched_at) >= :since")
        params["since"] = since
    ids = []
    if want["primary"] or want["secondary"]:
        sql = ("WITH pick AS (SELECT l.id, " + _EMPLOYER + " AS emp, CASE WHEN l.feed_keys && CAST(:r1 AS text[]) THEN 1 ELSE 2 END AS tier, "
               "coalesce(l.posted_at, l.fetched_at) AS at FROM listings l WHERE " + " AND ".join(conds) +
               " AND l.feed_keys && CAST(:rall AS text[])), "
               "ranked AS (SELECT id, tier, at, row_number() OVER (PARTITION BY emp ORDER BY tier, at DESC) AS k FROM pick) "
               "SELECT id FROM ranked WHERE k <= :per ORDER BY tier, at DESC LIMIT :n")
        params["rall"] = params["r1"] + params["r2"]
        ids = [str(r[0]) for r in db.execute(text(sql), params).fetchall()]
    if want["keywords"] and len(ids) < limit:
        p2 = dict(params, pats=["%" + w.replace("%", "").replace("_", "") + "%" for w in want["keywords"]], n=int(limit) - len(ids))
        sql = ("SELECT l.id FROM listings l WHERE " + " AND ".join(conds) + " AND l.title ILIKE ANY(CAST(:pats AS text[])) "
               "ORDER BY coalesce(l.posted_at, l.fetched_at) DESC LIMIT :n")
        seen = set(ids)
        ids += [str(r[0]) for r in db.execute(text(sql), p2).fetchall() if str(r[0]) not in seen]
    if not want["primary"] and not want["secondary"] and not want["keywords"]:
        # nothing to aim at yet (an empty profile): the newest jobs where you are
        sql = ("WITH ranked AS (SELECT l.id, coalesce(l.posted_at, l.fetched_at) AS at, row_number() OVER (PARTITION BY " + _EMPLOYER +
               " ORDER BY coalesce(l.posted_at, l.fetched_at) DESC) AS k FROM listings l WHERE " + " AND ".join(conds) + ") "
               "SELECT id FROM ranked WHERE k <= :per ORDER BY at DESC LIMIT :n")
        ids = [str(r[0]) for r in db.execute(text(sql), params).fetchall()]
    return ids[:int(limit)]
 
 
_FEED_ROW_SQL = ("SELECT l.id, l.source, l.title, l.org, l.type, l.location, l.body_z, l.apply_url, l.fetched_at, l.posted_at, "
                 "CASE WHEN b.ats = 'usajobs' THEN l.last_seen_at ELSE b.last_ok_at END AS seen_at, l.repost_count, l.salary_min, "
                 "l.salary_max, l.salary_is_predicted, l.salary_period, l.employment_type, l.contract_type, l.deadline, l.closed_at "
                 "FROM listings l JOIN employer_boards b ON b.id = l.board_id WHERE l.id = ANY(CAST(:ids AS uuid[]))")
 
 
def feed_dicts(db, want, limit=FEED_POOL_LIMIT, since=None) -> list:
    """This person's employer-feed jobs, already in the engine's shape. [] when the feeds aren't
    set up (migration not run) or nothing matches - never an error for the caller."""
    if limit <= 0:
        return []
    try:
        with db.begin_nested():
            ids = _feed_ids(db, want, limit, since)
    except Exception as e:
        print(f"  employer-feed jobs unavailable ({type(e).__name__}): {str(e)[:200]}")
        return []
    return feed_dicts_by_ids(db, ids)
 
 
def feed_dicts_by_ids(db, ids, include_closed: bool = False) -> list:
    """Employer-feed listings by id, in the engine's shape (the text decompressed, "last seen" =
    when the employer's feed last confirmed it) - the same shape the page gets, so a job scores
    the same wherever it is scored. Closed ones are left out unless include_closed."""
    ids = [str(i) for i in ids or [] if i]
    if not ids:
        return []
    from app.services.feed_common import decompress_text
    try:
        from sqlalchemy import text
        with db.begin_nested():
            rows = db.execute(text(_FEED_ROW_SQL), {"ids": ids}).mappings().all()
    except Exception as e:
        print(f"  employer-feed jobs unavailable ({type(e).__name__}): {str(e)[:200]}")
        return []
    order = {i: k for k, i in enumerate(ids)}
    out = []
    for r in sorted(rows, key=lambda r: order.get(str(r["id"]), 0)):
        if r.get("closed_at") is not None and not include_closed:
            continue
        dl = r.get("deadline")
        out.append({
            "id": str(r["id"]), "type": r["type"] or "job", "title": r["title"] or "", "org": r["org"] or "", "location": r["location"] or "",
            "description": decompress_text(r["body_z"])[:DESC_LIMIT], "posted_at": _iso(r["posted_at"]), "first_seen_at": _iso(r["fetched_at"]),
            "last_seen_at": _iso(r["seen_at"]), "seen_count": None, "repost_count": r["repost_count"] or 0,
            "salary_min": r["salary_min"], "salary_max": r["salary_max"], "salary_is_predicted": r["salary_is_predicted"],
            "salary_period": r["salary_period"], "employment_type": r["employment_type"], "contract_type": r["contract_type"],
            "apply_url": r["apply_url"] or "", "source": r["source"] or "", "deadline": dl.isoformat() if dl else None, "tags": [],
        })
    return out
 
 
def feed_dicts_for_user(db, user_id, profile, state=None, query=None, limit=FEED_POOL_LIMIT, since=None) -> list:
    from app.models.db_models import ResumeEntry
    state = state if isinstance(state, dict) else load_state(db, user_id)
    prefs = state.get("prefs") if isinstance(state.get("prefs"), dict) else {}
    try:
        entries = entries_for_engine(db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all())
    except Exception:
        db.rollback()
        entries = []
    return feed_dicts(db, feed_want(profile_for_engine(profile), entries, prefs, query), limit=limit, since=since)
 
 
def applied_listing_ids(db, user_id, include_undone: bool = False) -> set:
    """Jobs this user already has an application for (Auto's own, or a draft
    they accepted) - never offered to Auto or announced again. An application
    the user undid (never sent) doesn't count by default: that job comes back to
    the feed, where "Draft application" re-opens it. include_undone=True is for
    Auto, which never takes back a job you discarded. Reads only the ids."""
    try:
        from app.models.db_models import Application
    except ImportError:
        return set()
    try:
        q = db.query(Application.listing_id).filter(Application.user_id == user_id)
        if not include_undone:
            q = q.filter(Application.status.is_(None) | (Application.status != "undone"))
        rows = q.all()
        return {str(r[0]) for r in rows if r[0] is not None}
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return set()
 
 
def _inputs(db, user_id, profile, rows=None, state=None, feed_limit=0, feed_since=None):
    from app.models.db_models import DismissedListing, ResumeEntry
    state = state if isinstance(state, dict) else load_state(db, user_id)
    rows = rows if rows is not None else pool_rows(db)
    if feed_limit:
        rows = list(rows) + feed_dicts_for_user(db, user_id, profile, state=state, limit=feed_limit, since=feed_since)
    dismissed = {i: True for i in _id_set(db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all())}
    applied_src = state.get("applied") if isinstance(state.get("applied"), list) else []
    applied = {str(x): True for x in applied_src if x is not None and not isinstance(x, (dict, list))}
    for i in applied_listing_ids(db, user_id):
        applied[i] = True
    prefs = state.get("prefs") if isinstance(state.get("prefs"), dict) else {}
    learned_src = state.get("learned") if isinstance(state.get("learned"), list) else []
    learned = [r for r in learned_src if isinstance(r, dict)][-LEARNED_CAP:]
    prof = profile_for_engine(profile)
    entries = entries_for_engine(db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all())
    # an employer-feed job handed in as a database row is read in the page's shape (its text lives compressed
    # in body_z, its "last seen" is its employer's last read) - so the server scores exactly what the card shows
    from app.services.feed_common import is_feed_source
    orm_feed = [str(l.id) for l in rows if not isinstance(l, dict) and is_feed_source(getattr(l, "source", None))]
    fmap = {d["id"]: d for d in feed_dicts_by_ids(db, orm_feed, include_closed=True)} if orm_feed else {}
    listings = [l if isinstance(l, dict) else (fmap.get(str(l.id)) or listing_for_engine(l)) for l in rows]
    opts = {"now": _now_ms(), "types": prof.get("types") or None, "dismissed": dismissed, "applied": applied, "useServerCache": True}
    return {"state": state, "listings": listings, "prof": prof, "entries": entries, "prefs": prefs, "learned": learned, "opts": opts}
 
 
def analyze_for_user(db, user_id, profile, rows=None, state=None, extra_opts=None, best_first: bool = False, feed_limit: int = 0):
    """The same analyzePool the browser runs, for this user, on the live pool.
    best_first: rank by fit whatever display sort the user picked on the page -
    what Auto acts on and what other pages call "top matches" must be the best
    fits, never the newest or best-paid. feed_limit: also score up to this many
    of the employer-feed jobs picked for this person."""
    x = _inputs(db, user_id, profile, rows=rows, state=state, feed_limit=feed_limit)
    opts = dict(x["opts"])
    opts.update(extra_opts or {})
    prefs = dict(x["prefs"], sort="best") if best_first else x["prefs"]
    return JE.analyze_pool(x["listings"], x["prof"], x["entries"], prefs, x["learned"], opts)
 
 
# ------------------------------------------------------------------ legacy shape
def _why(it) -> str:
    s = it["score"]
    if s["fit"] is None:
        return "The posting says too little to score reliably."
    pos = [p["text"] for p in s.get("positives") or []]
    gaps = [g["text"] for g in s.get("gaps") or []]
    if s["fit"] >= 55 and pos:
        return " · ".join(pos[:3] + gaps[:1])
    return " · ".join((gaps[:3] + pos[:1])) or "Few of its requirements match your profile."
 
 
def _days_until(deadline):
    if not deadline:
        return None
    try:
        return (date.fromisoformat(str(deadline)[:10]) - date.today()).days
    except ValueError:
        return None
 
 
def legacy_backend_match(it) -> dict:
    """A v2 analysis in the shape older consumers read (/listings/matches,
    the Auto rules). score_pct IS the honest v2 fit - no remapping."""
    j, s, o = it["job"], it["score"], it["opp"]
    L = JE.to_legacy_match(it)
    loc = j["location"] or ""
    if j["mode"] == "remote" and "remote" not in loc.lower():
        loc = (loc + " (Remote)").strip() if loc else "Remote"
    sal = j["salary"]
    return {
        "id": j["id"], "title": j["title"], "org": j["org"], "type": j["type"], "location": loc,
        "deadline": j["deadline"], "description": j["description"], "tags": L["tags"], "apply_url": j["applyUrl"],
        "score_pct": L["pct"], "fit": s["fit"], "band": s["band"], "band_label": s["bandLabel"], "confidence": s["confidence"],
        "signal_strength": L["signalStrength"], "signal_score": L["signalScore"], "signal_band": s["bandLabel"],
        "signal_headline": _why(it), "rationale": _why(it),
        "goal_match_tags": L["matchedGoal"], "skill_match_tags": L["matchedSkill"], "missing_skills": L["missingSkills"],
        "blocker": s["capApplied"]["why"] if s["capApplied"] else None,
        # annual dollars, as stored for real listings (the Auto salary rule reads either unit)
        "salary_min": sal["annualMin"], "salary_max": sal["annualMax"], "salary_is_predicted": sal["source"] == "estimated",
        "freshness": o["freshness"], "ghost_risk": o["ghost"], "ghost_reasons": o["ghostReasons"], "age_days": o["ageDays"],
        "personalized": False, "data_quality": None,
        "factors": {"days_left": _days_until(j["deadline"]), "skills": s["dims"]["skills"], "level": s["dims"]["level"], "role": s["dims"]["role"], "industry": s["dims"]["industry"], "preferences": s["pref"]["score"]},
        "engine": "proof-v2",
    }
 
 
def v2_matches_payload(res, top_n: int = 25) -> dict:
    vis = res["visible"]
    hidden = sorted(res["hidden"], key=lambda it: -(it["score"]["fit"] or 0))[:5]
    near = []
    for it in hidden:
        m = legacy_backend_match(it)
        m["rationale"] = "Hidden by your filters: " + "; ".join(h["why"] for h in it["filters"]["hide"])
        near.append(m)
    strong = sum(1 for it in vis if (it["score"]["fit"] or 0) >= 70)
    note = None
    if not vis:
        note = "Nothing in the current listings gets past your filters - see what was hidden on the Job Search page."
    elif strong == 0:
        note = "None of the current listings is a strong fit (70+) for you yet - the closest ones are shown, scored honestly."
    return {"matches": [legacy_backend_match(it) for it in vis[:top_n]], "near_misses": near, "engine": "proof-v2",
            "engine_version": JE.ENGINE_VERSION, "hidden_count": len(res["hidden"]), "low_match_note": note}
 
 
# ------------------------------------------------------------------ Auto + accept
def auto_candidates(db, user_id, profile, rows=None, top_n: int = AUTO_TOP_N) -> list:
    """What Auto may act on: the user's own top-ranked visible matches - so
    every Job Search dealbreaker (hidden companies, sponsorship conflicts,
    pay floors set to Hide...) binds Auto too. score_pct is the v2 fit the
    user sees on the card, and v2_fit rides along so the approval decision
    uses the very same number."""
    res = analyze_for_user(db, user_id, profile, rows=rows, best_first=True, feed_limit=FEED_SERVER_LIMIT)
    # a job you discarded an application for is yours to re-open, never Auto's to take again
    # (it would also spend a daily-cap slot on a job that can't be applied to twice)
    taken = applied_listing_ids(db, user_id, include_undone=True)
    out = []
    for it in res["visible"]:
        if len(out) >= top_n:
            break
        if it["score"]["fit"] is None:   # a job too thin to score never takes one of the slots
            continue
        if taken and any(i in taken for i in _group_ids(it)):
            continue
        m = legacy_backend_match(it)
        m["v2_fit"] = it["score"]["fit"]
        out.append(m)
    return out
 
 
def v2_fit_for_listing(db, user_id, profile, listing) -> int | None:
    """The fit the card shows for one listing under your standing view: your
    profile's roles and saved preferences, ignoring filters (an explicit accept
    is your call) and any one-off search typed on the page. None if it can't be
    scored."""
    try:
        x = _inputs(db, user_id, profile, rows=[listing])
        prefs = JE.merge_prefs(x["prefs"], None)
        cand = JE.build_candidate(x["prof"], x["entries"], prefs, x["opts"]["now"])
        cand["country"] = x["opts"].get("country") or "US"   # exactly as analyze_pool sets it, so region-locked remote jobs cap the same
        job = JE.parse_job_cached(x["listings"][0])
        return JE.score_job(job, cand, prefs, {})["fit"]
    except Exception:
        try:
            db.rollback()   # a failed query must not leave the caller's session unusable
        except Exception:
            pass
        return None
 
 
# ------------------------------------------------------------------ saved-search alerts
def _group_ids(it) -> list:
    """A card's id plus its duplicates' - a job is the same job whichever
    site's copy happens to represent it this time."""
    j = it["job"]
    return [str(j["id"])] + [str(d.get("id")) for d in (j.get("duplicates") or []) if isinstance(d, dict) and d.get("id") is not None]
 
 
def run_saved_search_alerts(db, user_id, profile, rows=None, budget_s: float = ALERT_BUDGET_S) -> int:
    """Runs each saved search that has alerts on, exactly as the page does:
    the filters saved with the search (its snapshot), its own minimum fit
    (default 70), and only jobs posted in the last 14 days can trigger an
    alert. Then save_alert_updates decides, under the record's lock, what is
    really new, posts one Inbox notification per search with new strong
    matches and remembers what it told the user in the same record the page
    uses - so the page and the server never announce one job twice.
 
    Searches whose filters come out identical are scored once. One user gets at
    most budget_s seconds per scan: the searches checked longest ago go first,
    so any left over run first next time. Returns how many new matches were
    announced."""
    state = load_state(db, user_id)
    searches = [s for s in (state.get("searches") if isinstance(state.get("searches"), list) else [])
                if isinstance(s, dict) and s.get("alert")][:SEARCH_CAP]
    if not searches:
        return 0
    searches.sort(key=lambda s: _num(s.get("lastCheck")))
    # alerts are about new jobs: the employer-feed jobs posted in the alert window are enough
    x = _inputs(db, user_id, profile, rows=rows, state=state, feed_limit=FEED_SERVER_LIMIT,
                feed_since=utcnow() - timedelta(days=ALERT_MAX_AGE_DAYS + 1))
    pool_ids = set()
    for l in x["listings"]:
        pool_ids.add(str(l.get("id")))
    prefs_mute = (getattr(profile, "notification_preferences", None) or {}) if profile is not None else {}
    muted = prefs_mute.get("scan", True) is False
    results, memo, feed_memo = {}, {}, {}
    alert_since = utcnow() - timedelta(days=ALERT_MAX_AGE_DAYS + 1)
    have_ids = {str(l.get("id")) for l in x["listings"]}
    t0 = time.monotonic()
    for k, s in enumerate(searches):
        if time.monotonic() - t0 > budget_s:
            print(f"    saved-search alerts: time budget reached, {len(searches) - k} search(es) wait for the next scan")
            break
        # a malformed search is skipped, never run as "everything"
        if not isinstance(s.get("patch") if s.get("patch") is not None else {}, dict) or not isinstance(s.get("roles") if s.get("roles") is not None else [], list):
            continue
        if s.get("id") is None:
            continue
        try:
            base = s.get("base") if isinstance(s.get("base"), dict) else x["prefs"]
            prefs = JE.compose_prefs(base, s.get("patch") or {})
            roles = [r for r in (s.get("roles") or []) if isinstance(r, str)]
            sig = json.dumps([prefs, roles], sort_keys=True, default=str)
            res = memo.get(sig)
            if res is None:
                # the employer jobs this search would fetch on the page (its own roles and places), on top of the standing pool
                patch = s.get("patch") if isinstance(s.get("patch"), dict) else {}
                query = {"roles": roles, "loc": patch.get("locations") if isinstance(patch.get("locations"), str) else "",
                         "modes": patch.get("modes") if isinstance(patch.get("modes"), list) else [],
                         "keywords": [w for w in (patch.get("keywords") or []) + (patch.get("rankKeywords") or []) if isinstance(w, str)]}
                listings = x["listings"]
                if roles or query["loc"] or query["modes"] or query["keywords"]:
                    want = feed_want(x["prof"], x["entries"], base, query)
                    wsig = json.dumps(want, sort_keys=True)
                    extra = feed_memo.get(wsig)
                    if extra is None:
                        extra = feed_memo[wsig] = [d for d in feed_dicts(db, want, limit=FEED_SERVER_LIMIT, since=alert_since) if d["id"] not in have_ids]
                    if extra:
                        listings = listings + extra
                        for d in extra:
                            pool_ids.add(str(d["id"]))
                opts = dict(x["opts"])
                opts["queryRoles"] = roles
                res = memo[sig] = JE.analyze_pool(listings, x["prof"], x["entries"], prefs, x["learned"], opts)
            try:
                min_fit = max(40, min(100, int(s.get("minFit") or ALERT_MIN_FIT)))
            except (TypeError, ValueError, OverflowError):
                min_fit = ALERT_MIN_FIT
            strong = [{"ids": _group_ids(it), "age": it["opp"]["ageDays"], "title": it["job"]["title"], "org": it["job"]["org"], "fit": it["score"]["fit"]}
                      for it in res["visible"] if it["score"]["fit"] is not None and it["score"]["fit"] >= min_fit]
            results[str(s.get("id"))] = {"strong": strong, "now": x["opts"]["now"], "pool": pool_ids if pool_ids else None, "min_fit": min_fit,
                                         "sig": _search_sig(s)}
        except Exception as e:  # one bad search must not stop the others
            print(f"    saved-search alert skipped ({s.get('name')!r}): {e}")
    if not results:
        db.commit()
        return 0
    return save_alert_updates(db, user_id, results, notify=not muted)
 
 
# ------------------------------------------------------------------ ingestion helpers
def canonical_key_for(item: dict) -> str | None:
    """company|title|place for a freshly normalized listing - the same key the
    engine dedupes on - so a repost can be recognised at ingestion time."""
    try:
        job = JE.parse_job({"id": item.get("external_id") or "", "title": item.get("title"), "org": item.get("org"),
                            "location": item.get("location"), "description": item.get("description") or "", "type": item.get("type")})
        key = job.get("canonicalKey") or None
        # no real company name ("Unknown", "Confidential"): two such postings are not the same job
        if not key or key.startswith("#"):
            return None
        return key[:300]
    except Exception:
        return None
 
 
def repost_count_for(db, key, posted_at, source=None, external_id=None) -> int:
    """If the same company|title|place was already posted more than 7 days
    before this one, this is a repost: one more than that listing's count."""
    if not key:
        return 0
    from app.models.db_models import Listing
    try:
        rows = db.query(Listing).filter(Listing.canonical_key == key).all()
    except Exception:
        return 0
    when = to_naive_utc(posted_at) or utcnow()
    best = 0
    for r in rows:
        if source is not None and r.source == source and r.external_id == external_id:
            continue
        prev = to_naive_utc(getattr(r, "posted_at", None) or getattr(r, "fetched_at", None))
        if prev is not None and (when - prev).days > 7:
            best = max(best, (getattr(r, "repost_count", None) or 0) + 1)
    return best
 
