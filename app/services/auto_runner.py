"""Background job that scans real listings daily and re-scores them
for every user with an active profile. This is what makes the
"continuous overnight watch" real instead of a UI animation.
"""
import os
import asyncio
 
# Both real search sources (Adzuna for jobs, ScholarshipAPI for
# fellowships) were being queried with exactly ONE hardcoded term on
# every single scan, every time, for the entire life of this app -
# "internship" for jobs, "scholarship" for fellowships. This meant
# entire real career categories - software engineering, marketing,
# sales, data, finance, design - were NEVER pulled from Adzuna at
# all, not because Adzuna doesn't have them (it certainly does), but
# because the app never once asked. This is the backend-native
# version of the exact same coverage gap found and fixed in the
# frontend demo's static listing set - here it's fixed by actually
# querying broadly instead of hardcoding a single term.
JOB_SEARCH_QUERIES = [
    "internship", "software engineer", "product manager", "marketing",
    "data analyst", "sales", "financial analyst", "operations", "ux designer",
    "human resources", "customer success", "healthcare", "legal",
]
SCHOLARSHIP_SEARCH_QUERIES = ["scholarship", "fellowship", "grant"]
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from app.services.ai_client import get_client
 
from app.db import SessionLocal
from app.models.db_models import User, Profile, Listing, MatchScore, Notification
from app.services.ingestion import (
    fetch_adzuna, normalize_adzuna, dedupe_listings, extract_tags,
    fetch_simplify_internships, parse_simplify_markdown,
    discover_scholarships_via_search, normalize_scholarship_from_search, _scholarship_passes_quality_check,
    fetch_athletic_career_jobs, normalize_athletic_job, ATHLETIC_CAREER_QUERIES,
    fetch_admissions_opportunities, normalize_admissions_opportunity, ADMISSIONS_OPPORTUNITY_QUERIES,
    fetch_ncaa_schools,
    check_and_reserve_quota, ADZUNA_DAILY_CALL_LIMIT,
)
from app.services.matching import rank_listings
from app.services.timeutil import utcnow
from app.services.embeddings import generate_embedding
 
# An approved application that came due more than this many days ago is never auto-sent (see the auto-send pass).
try:   # (a bad value must never stop the app from starting - this module is imported at startup)
    AUTO_SEND_MAX_AGE_DAYS = max(1, int(os.getenv("AUTO_SEND_MAX_AGE_DAYS", "7")))
except ValueError:
    AUTO_SEND_MAX_AGE_DAYS = 7
 
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "1440"))  # default: once/day
# The Anthropic client is resolved LAZILY at scan time via get_client(), never
# constructed here at module scope. main.py does `from app.services.scheduler
# import start_scheduler` at the very top of startup - so any exception raised
# while importing THIS module aborts startup before the app can bind a port
# (Render then reports "no open ports"). The Anthropic SDK RAISES at
# construction when ANTHROPIC_API_KEY is missing, so an eager
# `anthropic.Anthropic(...)` here was a latent startup crash on any environment
# without the key set. get_client() never raises (returns None without a key),
# and the scan/auto-apply paths already degrade gracefully on a None client -
# exactly the same fix the route modules got. Resolving at call time (not here)
# also avoids the import-order trap: this module is imported before main.py runs
# load_dotenv(), so a module-scope resolve would cache the wrong (empty) result.
 
 
def _profile_to_dict(p: Profile) -> dict:
    from app.services.embeddings import generate_embedding
    goal_text = f"{p.northstar or ''}. {p.final_idea or ''}. Skills: {p.skills or ''}"
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "dealbreakers": p.dealbreakers or "",
        "priorities": p.priorities or [],
        "target_types": p.target_types or [],
        "location_pref": p.location_pref or "",
        "stage": p.stage or "",
        "embedding": generate_embedding(goal_text, input_type="query"),
    }
 
 
def _listing_to_dict(l: Listing) -> dict:
    return {
        "id": str(l.id),
        "type": l.type,
        "title": l.title,
        "org": l.org,
        "tags": l.tags or [],
        "location": l.location,
        "deadline": l.deadline.isoformat() if l.deadline else None,
        "description": l.description or "",
        "embedding": list(l.embedding) if l.embedding is not None else None,
        "salary_min": l.salary_min,
        "salary_max": l.salary_max,
        "salary_is_predicted": l.salary_is_predicted,
        "fetched_at": l.fetched_at.isoformat() if l.fetched_at else None,
    }
 
 
def _embed_listing(title: str, description: str, tags: list[str]) -> list[float] | None:
    """Embedded once at ingestion time and cached in the DB - unlike
    the profile embedding (computed fresh per request, since goal text
    changes rarely), re-embedding every listing on every match request
    would be wasteful at scale. Returns None automatically if
    VOYAGE_API_KEY isn't configured - ingestion proceeds exactly as it
    did before this existed, just without the semantic factor.
    """
    text = f"{title}. {description}. Tags: {', '.join(tags or [])}"
    return generate_embedding(text, input_type="document")
 
 
def _v2_fields(db: Session, item: dict) -> dict:
    """Job Search v2 columns for a NEW listing row: the employer's own posting
    date, pay and job type when the source gives them, when we saw it, and the
    company|title|place key that lets a quiet repost be recognised. Every
    field falls back to None/0 - never a guess."""
    key, reposts = None, 0
    try:
        from app.services.job_search import canonical_key_for, repost_count_for
        key = canonical_key_for(item)
        reposts = repost_count_for(db, key, item.get("posted_at"), item.get("source"), item.get("external_id"))
    except Exception as e:
        print(f"  v2 listing fields skipped for '{item.get('title')}': {e}")
    return {
        "posted_at": item.get("posted_at"), "last_seen_at": utcnow(), "seen_count": 1, "repost_count": reposts,
        "employment_type": item.get("employment_type"), "contract_type": item.get("contract_type"),
        "category": item.get("category"), "canonical_key": key,
        "salary_min": item.get("salary_min"), "salary_max": item.get("salary_max"), "salary_is_predicted": item.get("salary_is_predicted"),
    }
 
 
class _IngestPass:
    """What one ingestion pass has handled so far: every (source, external id) -
    the same Adzuna id can come back from two different queries in one pass - and
    the stored listings that turned up again, marked live in one UPDATE after the
    new rows commit (so a failed insert batch can never throw those away)."""
    def __init__(self):
        self.keys = set()
        self.seen_now = {}   # listing id -> fields to fill in on rows stored before Job Search v2
 
 
def _new_listing_problem(item) -> str | None:
    """Why a normalized listing can't be stored, or None. Checked BEFORE the row
    is added: one record without an apply link would otherwise fail the whole
    batch commit."""
    if not isinstance(item, dict):
        return "not a listing record"
    for f in ("source", "external_id", "title", "type", "apply_url"):
        v = item.get(f)
        if not isinstance(v, str) or not v.strip():
            return "no " + f.replace("_", " ")
    if not isinstance(item.get("org"), str):
        return "no company field"
    return None
 
 
def _touch_seen(row, cycle, item=None) -> None:
    """A listing we already have turned up again: it's still live at the source.
    Rows stored before Job Search v2 also get the posting date, job type and
    repost key the source gives now - otherwise they'd say "date unknown" forever."""
    try:
        fill = cycle.seen_now.get(row.id) or {}
        if isinstance(item, dict):
            if getattr(row, "posted_at", None) is None and item.get("posted_at") is not None:
                fill["posted_at"] = item["posted_at"]
            if getattr(row, "employment_type", None) is None and item.get("employment_type"):
                fill["employment_type"] = item["employment_type"]
            if getattr(row, "contract_type", None) is None and item.get("contract_type"):
                fill["contract_type"] = item["contract_type"]
            if getattr(row, "canonical_key", None) is None and "canonical_key" not in fill:
                from app.services.job_search import canonical_key_for
                key = canonical_key_for(item)
                if key:
                    fill["canonical_key"] = key
        cycle.seen_now[row.id] = fill
    except Exception:
        pass
 
 
def _skip_or_touch(db: Session, cycle, item) -> bool:
    """True when this item needs no new row: already handled in this pass,
    unstorable (logged), or already stored - then it's recorded as live again."""
    if not isinstance(item, dict):
        return True
    key = (item.get("source"), item.get("external_id"))
    if key in cycle.keys:
        return True
    problem = _new_listing_problem(item)
    exists = None
    if item.get("source") and item.get("external_id"):
        exists = (
            db.query(Listing)
            .filter(Listing.source == item["source"], Listing.external_id == item["external_id"])
            .first()
        )
    if exists:
        cycle.keys.add(key)
        _touch_seen(exists, cycle, item)
        return True
    if problem:
        # not remembered as handled: a later, valid copy of the same posting in this pass can still be stored
        print(f"  Skipped a listing that can't be stored ({problem}): source={item.get('source')}, ext={item.get('external_id')}")
        return True
    cycle.keys.add(key)
    return False
 
 
def _add_listing(db: Session, item: dict, tags) -> int:
    db.add(Listing(
        source=item["source"], external_id=item["external_id"], title=item["title"],
        org=item["org"], type=item["type"], location=item["location"],
        description=item["description"], tags=tags, deadline=item["deadline"],
        apply_url=item["apply_url"],
        embedding=_embed_listing(item["title"], item["description"], tags),
        **_v2_fields(db, item),
    ))
    return 1
 
 
def _apply_seen(db: Session, cycle) -> int:
    """Marks every listing that turned up again as still live - bulk UPDATEs
    after the inserts commit - and fills in what pre-v2 rows were missing."""
    ids = list(cycle.seen_now)
    if not ids:
        return 0
    try:
        from sqlalchemy import func
        now = utcnow()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            db.query(Listing).filter(Listing.id.in_(chunk)).update(
                {Listing.last_seen_at: now, Listing.seen_count: func.coalesce(Listing.seen_count, 1) + 1},
                synchronize_session=False)
        for lid, fill in cycle.seen_now.items():
            if fill:
                db.query(Listing).filter(Listing.id == lid).update(fill, synchronize_session=False)
        db.commit()
        return len(ids)
    except Exception as e:
        db.rollback()
        print(f"Marking re-seen listings as live failed (non-fatal): {e}")
        return 0
 
 
def _safe_normalize(fn, raw):
    """One malformed record from a source must not cost the whole source's batch
    (or, uncaught, the whole day's scan)."""
    try:
        return fn(raw)
    except Exception as e:
        print(f"  Skipped a malformed record from {getattr(fn, '__name__', 'a source')}: {e}")
        return None
 
 
def backfill_missing_embeddings(db: Session, batch_size: int = 100) -> dict:
    """Any listing ingested before VOYAGE_API_KEY was configured has
    embedding=None permanently - the ingestion upsert above (`if
    exists: continue`) skips any listing already in the database by
    source+external_id, so those specific rows are never revisited by
    a normal scan, no matter how many days pass or how many times the
    key gets fixed afterward. Setting up the key correctly today does
    nothing for listings that predate it; this is the only path back
    to a real embedding for them, short of waiting for every one of
    them to naturally expire and get replaced by a fresh listing.
 
    Capped at batch_size per call rather than processing everything
    at once - safe to call repeatedly (each call picks up the next
    batch of still-null rows) rather than risking one very large,
    slow request against a real rate-limited API.
 
    Returns a real count of what happened, not just "done" - honest
    about a real, if unlikely, partial-failure case: a specific
    listing's text triggering an API error while others succeed.
    """
    from app.services.embeddings import is_configured
 
    if not is_configured():
        return {"attempted": 0, "succeeded": 0, "detail": "VOYAGE_API_KEY is not set - nothing to backfill until it's configured."}
 
    from app.services.feed_common import not_feed
    # employer-feed jobs are never embedded: hundreds of thousands of paid embedding calls for no use
    candidates = db.query(Listing).filter(Listing.embedding.is_(None)).filter(not_feed(Listing)).limit(batch_size).all()
    succeeded = 0
    for listing in candidates:
        embedding = _embed_listing(listing.title, listing.description, listing.tags)
        if embedding is not None:
            listing.embedding = embedding
            succeeded += 1
    db.commit()
    return {"attempted": len(candidates), "succeeded": succeeded, "detail": f"Processed {len(candidates)} listings with no embedding yet; {succeeded} succeeded. Call again to process the next batch if more remain."}
 
 
async def _pull_and_store_new_listings(db: Session):
    """Fetches real listings from two sources - Adzuna for jobs (tagged
    via Claude) and SimplifyJobs for internships (tagged via free
    keyword matching, no AI cost) - and upserts anything new.
 
    Adzuna gets queried once per term in JOB_SEARCH_QUERIES, not once
    overall - a single hardcoded "internship" query meant entire real
    career categories were never being pulled at all, regardless of
    how good the downstream matching got.
 
    Adzuna's real free tier is roughly 1,000 calls a month (about 33
    a day, verified against their actual current documentation) - the
    13 job queries + 6 athletic queries this function can make (19
    total) leave very little headroom for a manual "check now"
    trigger on the same day as the scheduled scan without genuinely
    risking exceeding that real quota. check_and_reserve_quota below
    tracks real daily usage and gracefully limits how many of these
    queries actually run today, rather than blindly firing all 19
    regardless of what's already been consumed.
    """
    anthropic_client = get_client()  # None if no API key; extract_tags degrades to []
    stored_count = 0
    cycle = _IngestPass()
    total_possible_queries = len(JOB_SEARCH_QUERIES) + len(ATHLETIC_CAREER_QUERIES) + len(ADMISSIONS_OPPORTUNITY_QUERIES)
    reserved_calls = check_and_reserve_quota(db, "adzuna", calls_needed=total_possible_queries, daily_limit=ADZUNA_DAILY_CALL_LIMIT)
    # Proportional split, not a hard job-queries-first priority - direct
    # testing showed the hard-priority version completely zeroed out
    # athletic queries any time reserved_calls fell at or below 13 (the
    # job query count), which isn't a rare edge case: it's exactly what
    # happens whenever a manual "check now" trigger runs on the same day
    # the scheduled scan already consumed part of the daily budget - a
    # completely ordinary usage pattern, not an extreme one. Proportional
    # allocation means athletic listings keep getting refreshed at a
    # reduced rate under a constrained budget instead of being the one
    # source that silently stops updating.
    if reserved_calls >= total_possible_queries:
        job_query_budget, athletic_query_budget = len(JOB_SEARCH_QUERIES), len(ATHLETIC_CAREER_QUERIES)
        admissions_query_budget = len(ADMISSIONS_OPPORTUNITY_QUERIES)
    else:
        job_query_budget = min(round(reserved_calls * len(JOB_SEARCH_QUERIES) / total_possible_queries), reserved_calls)
        athletic_query_budget = min(round(reserved_calls * len(ATHLETIC_CAREER_QUERIES) / total_possible_queries), reserved_calls - job_query_budget)
        admissions_query_budget = reserved_calls - job_query_budget - athletic_query_budget
    if reserved_calls < total_possible_queries:
        print(f"Adzuna daily quota reached or nearly reached - running {reserved_calls} of {total_possible_queries} possible queries today ({job_query_budget} job, {athletic_query_budget} athletic, {admissions_query_budget} admissions).")
 
    # Source 1: Adzuna, for jobs - queried across every category in
    # JOB_SEARCH_QUERIES, not just one hardcoded term, then merged
    # and deduped by (source, external_id) before any DB writes or
    # paid tag-extraction calls happen on a listing twice.
    #
    # Each query is isolated with its own try/except - confirmed by
    # tracing the real exception path that a single query's failure
    # (a transient network issue, a temporary Adzuna-side error) would
    # otherwise propagate all the way up through this function to
    # run_scan_for_all_users' outer handler, aborting the ENTIRE daily
    # scan: every remaining Adzuna and athletic query, every user's
    # rescoring, and every user's Auto Apply run for that day - not
    # just the one query that actually failed.
    all_adzuna_raw = []
    for q in JOB_SEARCH_QUERIES[:job_query_budget]:
        try:
            all_adzuna_raw.extend(await fetch_adzuna(q))
        except Exception as e:
            print(f"  Adzuna query '{q}' failed, skipping it for today: {e}")
    adzuna_normalized = dedupe_listings([_safe_normalize(normalize_adzuna, r) for r in all_adzuna_raw])
    for item in adzuna_normalized:
        if _skip_or_touch(db, cycle, item):
            continue
        try:
            tags = await extract_tags(item["description"], anthropic_client)
        except Exception as e:
            print(f"  Tag extraction failed for '{item['title']}', storing with no tags rather than losing it: {e}")
            tags = []
        stored_count += _add_listing(db, item, tags)
 
    # Source 2: SimplifyJobs, for internships - free, no Claude call
    try:
        markdown_text = await fetch_simplify_internships()
        simplify_listings = parse_simplify_markdown(markdown_text)
        for item in simplify_listings:
            if _skip_or_touch(db, cycle, item):
                continue
            stored_count += _add_listing(db, item, item["tags"])
    except Exception as e:
        print(f"SimplifyJobs ingestion failed (non-fatal, Adzuna results still saved): {e}")
 
    # Source 3: real web-search-grounded scholarship/fellowship
    # discovery - replaces the old ScholarshipAPI integration, which
    # needed replacing for two real, honest reasons: it only ever
    # covered Australia/New Zealand universities (not the US this
    # platform is built around), and separately, its response schema
    # was only ever guessed from public docs, never verified against
    # a real call. This uses the same proven real-search pattern
    # already working elsewhere in this app - every field comes from
    # an actual, current search result, not a guessed field mapping.
    try:
        all_scholarship_raw = []
        for q in SCHOLARSHIP_SEARCH_QUERIES:
            try:
                all_scholarship_raw.extend(await discover_scholarships_via_search(anthropic_client, q))
            except Exception as e:
                print(f"  Scholarship search '{q}' failed, skipping it for today: {e}")
        # Real, visible rejection reasons rather than silently
        # discarding them - the same "make it visible, not silent"
        # principle already applied to candidate match transparency
        # elsewhere in this app.
        accepted_raw = []
        for r in all_scholarship_raw:
            passes, reason = _scholarship_passes_quality_check(r)
            if passes:
                accepted_raw.append(r)
            else:
                print(f"Scholarship quality gate rejected \"{r.get('title', '(no title)')}\": {reason}")
        scholarship_normalized = [_safe_normalize(normalize_scholarship_from_search, r) for r in accepted_raw]
        scholarship_normalized = dedupe_listings([r for r in scholarship_normalized if r is not None])
        for item in scholarship_normalized:
            if _skip_or_touch(db, cycle, item):
                continue
            stored_count += _add_listing(db, item, item["tags"])
    except Exception as e:
        print(f"Scholarship discovery failed (non-fatal): {e}")
 
    # Source 4: Athletic-career jobs (coaching, athletic training, sports
    # management) - real data via the same Adzuna connection, just
    # queried with sports-specific terms. See ingestion.py for why this
    # is the honest alternative to a dedicated athletic scholarship API,
    # which doesn't exist as a free public service.
    try:
        raw_athletic = await fetch_athletic_career_jobs(max_queries=athletic_query_budget)
        athletic_normalized = dedupe_listings([_safe_normalize(normalize_athletic_job, r) for r in raw_athletic])
        for item in athletic_normalized:
            if _skip_or_touch(db, cycle, item):
                continue
            try:
                tags = await extract_tags(item["description"], anthropic_client)
            except Exception as e:
                print(f"  Tag extraction failed for '{item['title']}', storing with no tags rather than losing it: {e}")
                tags = []
            tags = list(set(tags + ["athletics"]))  # ensure it's always discoverable by the athletics filter
            stored_count += _add_listing(db, item, tags)
    except Exception as e:
        print(f"Athletic-career job ingestion failed (non-fatal): {e}")
 
    # Source 5: Admissions opportunities (internships, research, pre-college,
    # volunteer/leadership programs) - real data via the same Adzuna
    # connection, queried with student-focused terms. The honest
    # alternative to a dedicated competitions/extracurriculars API, exactly
    # mirroring the athletic source above.
    try:
        raw_admissions = await fetch_admissions_opportunities(max_queries=admissions_query_budget)
        admissions_normalized = dedupe_listings([_safe_normalize(normalize_admissions_opportunity, r) for r in raw_admissions])
        for item in admissions_normalized:
            if _skip_or_touch(db, cycle, item):
                continue
            try:
                tags = await extract_tags(item["description"], anthropic_client)
            except Exception as e:
                print(f"  Tag extraction failed for '{item['title']}', storing with no tags rather than losing it: {e}")
                tags = []
            tags = list(set(tags + ["admissions"]))  # ensure it's always discoverable by the admissions filter
            stored_count += _add_listing(db, item, tags)
    except Exception as e:
        print(f"Admissions opportunity ingestion failed (non-fatal): {e}")
 
    # Source 6: NCAA target programs (real college athletic programs from the
    # free NCAA schools API via a self-hosted ncaa-api instance). Recruiting is
    # relationship-based, so these are programs to PURSUE via coach-outreach,
    # not scholarships to "apply" to. No Claude call (tags/description are built
    # from the school record). Fails safe: fetch_ncaa_schools returns [] if
    # NCAA_API_BASE is unset or the fetch fails, so this is a clean no-op then.
    try:
        ncaa_programs = await fetch_ncaa_schools(limit=200)
        for item in ncaa_programs:
            if _skip_or_touch(db, cycle, item):
                continue
            tags = list(set((item.get("tags") or []) + ["athletic"]))  # always discoverable by the athletic filter
            stored_count += _add_listing(db, item, tags)
    except Exception as e:
        print(f"NCAA target-program ingestion failed (non-fatal): {e}")
 
    # Resilient commit: normally one batch commit. But if a single malformed row
    # violates a DB constraint, a plain commit() rolls back the ENTIRE session -
    # losing every listing from every source this scan. So on failure, roll back
    # and re-commit the pending rows one at a time, skipping only the bad one(s),
    # so one bad row can't discard a whole scan's worth of good listings.
    try:
        db.commit()
    except Exception as batch_err:
        print(f"Batch commit failed ({batch_err}); retrying row-by-row to save the good rows.")
        # Capture the pending Listing rows BEFORE rolling back - rollback expunges
        # db.new, so snapshot the objects first, then rollback, then re-add each.
        pending = [obj for obj in list(db.new) if isinstance(obj, Listing)]
        # detach them so they survive the rollback, then re-add individually
        snapshot = [{
            "source": o.source, "external_id": o.external_id, "title": o.title, "org": o.org,
            "type": o.type, "location": o.location, "description": o.description, "tags": o.tags,
            "deadline": o.deadline, "apply_url": o.apply_url, "embedding": o.embedding,
            "salary_min": o.salary_min, "salary_max": o.salary_max, "salary_is_predicted": o.salary_is_predicted,
            "posted_at": o.posted_at, "last_seen_at": o.last_seen_at, "seen_count": o.seen_count, "repost_count": o.repost_count,
            "employment_type": o.employment_type, "contract_type": o.contract_type, "category": o.category, "canonical_key": o.canonical_key,
        } for o in pending]
        db.rollback()
        saved = 0
        for row in snapshot:
            try:
                db.add(Listing(**row))
                db.commit()
                saved += 1
            except Exception as row_err:
                db.rollback()
                print(f"  Skipped a bad listing row (source={row.get('source')}, ext={row.get('external_id')}): {row_err}")
        stored_count = saved
    _apply_seen(db, cycle)
    return stored_count
 
 
def run_scan_for_user(db: Session, user_id: str) -> dict:
    """Re-scores current listings for one user and stores the results.
    Used both by the daily scheduled job and the manual /listings/scan/{user_id} route.
    """
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        return {"status": "no active profile", "user_id": user_id}
 
    from app.services.feed_common import not_feed
    listings = db.query(Listing).filter(not_feed(Listing)).all()   # the v1 ranking reads tags/embeddings employer-feed jobs don't have
    from app.models.db_models import DismissedListing
    dismissed_ids = {str(row.listing_id) for row in db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()}
    ranked = rank_listings(
        [_listing_to_dict(l) for l in listings],
        _profile_to_dict(profile),
        top_n=10,
        dismissed_ids=dismissed_ids,
    )
 
    # Determine this user's next scan_cycle number
    last_cycle = (
        db.query(MatchScore.scan_cycle)
        .filter(MatchScore.user_id == user_id)
        .order_by(MatchScore.scan_cycle.desc())
        .first()
    )
    next_cycle = (last_cycle[0] + 1) if last_cycle else 1
 
    for l in ranked:
        db.add(MatchScore(
            user_id=user_id,
            listing_id=l["id"],
            profile_id=profile.id,
            score_pct=l["score_pct"],
            goal_match_tags=l["goal_match_tags"],
            skill_match_tags=l["skill_match_tags"],
            rationale=l["rationale"],
            scan_cycle=next_cycle,
        ))
    db.commit()
 
    return {"status": "scanned", "user_id": user_id, "matches": len(ranked), "cycle": next_cycle}
 
 
def run_scan_for_all_users():
    """The actual daily job: pulls fresh listings once, then re-scores
    every user against the updated listings table. Also runs Auto
    Apply for any user who's enabled it - this is what makes the
    autonomous mode actually autonomous, not just a bigger manual
    button: it fires even if nobody opens the app that day.
    """
    from app.services.auto_apply import auto_apply_and_outreach_for_user
 
    anthropic_client = get_client()  # None if no API key; auto-apply/outreach are wrapped per-listing
    db = SessionLocal()
    try:
        print(f"[{utcnow().isoformat()}] Starting daily scan...")
        try:
            new_count = asyncio.run(_pull_and_store_new_listings(db))
            print(f"Pulled {new_count} new listings.")
        except Exception as e:
            # a failed pull must not cancel rescoring, Auto, alerts or auto-send for everyone
            db.rollback()
            print(f"Pulling new listings failed (non-fatal - scoring what we have): {e}")
 
        # Runs automatically every day rather than depending on a
        # human remembering the manual /system/backfill-embeddings
        # endpoint exists - the self-healing this function offers was
        # real, but genuinely unreachable without that reminder,
        # inconsistent with the rest of this system's design ("fires
        # even if nobody opens the app that day"). Cheap and safe to
        # run daily: capped at 100 rows, a genuine no-op query when
        # there's nothing to backfill. Isolated in its own try/except
        # so a real failure here can never cancel user rescoring or
        # Auto Apply below it, the same isolation already applied to
        # the ingestion loops above.
        try:
            backfill_result = backfill_missing_embeddings(db)
            if backfill_result["attempted"] > 0:
                print(f"Embedding backfill: {backfill_result['detail']}")
        except Exception as e:
            print(f"Embedding backfill failed (non-fatal, rest of the scan continues): {e}")
 
        # Surfaces embeddings health passively in the same logs
        # someone's already watching for the daily scan, rather than
        # depending on a separate, remembered check of
        # /system/embeddings-status - a silent problem here (an
        # expired key, a Voyage-side account issue) could otherwise
        # go unnoticed indefinitely. Genuinely silent when everything
        # is fine - only speaks up when there's something real to say,
        # the same restraint already applied to the backfill log above.
        try:
            from app.services.embeddings import check_embeddings_status
            embeddings_status = check_embeddings_status()
            if not embeddings_status["working"]:
                print(f"WARNING - embeddings not working: {embeddings_status['detail']}")
        except Exception as e:
            print(f"Embeddings status check itself failed (non-fatal): {e}")
 
        users = db.query(User).join(Profile).filter(Profile.is_current == True).all()  # noqa: E712
        # Load the listing set once per cycle - it's identical for every
        # user in this pass, so re-querying it inside the loop was N
        # redundant full-table loads. Fetched here and reused below.
        # Turned into plain dicts right away: ORM rows expire at every commit inside
        # the loop below, and re-reading them would mean one query per listing per user.
        from app.services.feed_common import not_feed
        all_listing_dicts_this_cycle = [_listing_to_dict(l) for l in db.query(Listing).filter(not_feed(Listing)).all()]
        # The Job Search v2 pool (jobs/internships/programs, newest first) - also
        # built once, as engine-ready dicts, and shared by every user's Auto pass
        # and saved-search alerts.
        try:
            from app.services.job_search import pool_dicts
            v2_pool_this_cycle = pool_dicts(db)
        except Exception as e:
            db.rollback()
            print(f"Job Search v2 pool unavailable this cycle (Auto and alerts will skip): {e}")
            v2_pool_this_cycle = None
        for user in users:
            # Isolated per-user, mirroring the exact same defensive
            # pattern already applied consistently everywhere else in
            # this file (each Adzuna/Simplify/scholarship/athletic
            # source above, the notification write, the auto-send
            # pass below). Without this, an unexpected failure
            # processing ONE user's scan (a malformed profile row, a
            # database constraint issue - anything not already caught
            # by create_application_for_match's own internal
            # protection) would abort every remaining user in the
            # batch for the entire day, contradicting this file's own
            # consistent "one failure shouldn't cancel everything"
            # design applied throughout every other part of it.
            try:
                result = run_scan_for_user(db, str(user.id))
                print(f"  {user.email}: {result}")
 
                profile = (
                    db.query(Profile)
                    .filter(Profile.user_id == user.id, Profile.is_current == True)  # noqa: E712
                    .first()
                )
                # Auto runs on its own tick (auto_runner.run_tick: twice-daily passes per person, sends
                # within minutes of their undo window, follow-up reminders). Athletes keep the athletics
                # Auto they always had (their listings aren't in the Job Search pool).
                if profile and profile.auto_apply_enabled and getattr(profile, "is_athlete", False):
                    from app.models.db_models import DismissedListing
                    dismissed_ids = {str(row.listing_id) for row in db.query(DismissedListing).filter(DismissedListing.user_id == user.id).all()}
                    ranked = rank_listings(all_listing_dicts_this_cycle, _profile_to_dict(profile), top_n=10, dismissed_ids=dismissed_ids)
                    summary = auto_apply_and_outreach_for_user(db, anthropic_client, str(user.id), profile, ranked)
                    print(f"    Athlete Auto: {len(summary['applied'])} approved, {len(summary['outreach'])} outreach drafted for {user.email}")
 
                # Saved-search alerts (Job Search v2): new strong matches for any saved
                # search with alerts on go to the Inbox - once per job, shared with the
                # browser's own alert check so nobody is told twice.
                if profile and not getattr(profile, "is_athlete", False) and v2_pool_this_cycle is not None:
                    try:
                        from app.services.job_search import run_saved_search_alerts
                        n_alerts = run_saved_search_alerts(db, str(user.id), profile, rows=v2_pool_this_cycle)
                        if n_alerts:
                            print(f"    Saved-search alerts: {n_alerts} new strong match(es) for {user.email}")
                    except Exception as e:
                        db.rollback()
                        print(f"    Saved-search alerts skipped (non-fatal): {e}")
 
                # Weekly digest: at most once per 7 days per user, only when there's
                # something real to say, respecting the mute preference. Fully
                # fail-safe internally; the outer try is belt-and-suspenders.
                try:
                    from app.services.weekly_digest import maybe_send_weekly_digest
                    # (MatchScore and Listing come from this module's own imports: importing them again
                    # anywhere in this function would make them local names for ALL of it, and the
                    # earlier `db.query(Listing)` would then fail with UnboundLocalError - the whole scan with it)
                    from app.models.db_models import SavedListing, Application, AthleteEvent, Notification as _Notif
                    _digest_profile = (
                        db.query(Profile)
                        .filter(Profile.user_id == user.id, Profile.is_current == True)  # noqa: E712
                        .first()
                    )
                    _digest_models = {
                        "MatchScore": MatchScore, "Listing": Listing, "SavedListing": SavedListing,
                        "Application": Application, "AthleteEvent": AthleteEvent, "Notification": _Notif, "_profile": _digest_profile,
                    }
                    _digest_result = maybe_send_weekly_digest(db, _digest_models, user)
                    if _digest_result.get("status") == "sent":
                        print(f"    Weekly digest sent to {user.email}")
                except Exception as e:
                    # Roll back a failed digest write so a dirty session can't break
                    # the next user's iteration.
                    db.rollback()
                    print(f"    Weekly digest skipped (non-fatal): {e}")
            except Exception as e:
                # Roll back before moving to the next user. A failure mid-transaction
                # (e.g. run_scan_for_user's MatchScore commit hitting its unique
                # constraint) leaves the session in a FAILED state; without this
                # rollback every remaining user's queries would then raise
                # PendingRollbackError - one user's failure cascading to the whole
                # batch, defeating the per-user isolation this block exists for.
                db.rollback()
                print(f"  Scan failed for {user.email}, continuing with remaining users: {e}")
        print("Daily scan complete.")
 
        # Auto right after the day's new listings: sends that are due, follow-ups, and a pass for
        # everyone whose last one is old enough (the same tick that runs every AUTO_TICK_MINUTES).
        try:
            from app.services.auto_runner import run_tick
            print(f"Auto tick after the scan: {run_tick()}")
        except Exception as e:
            print(f"Auto tick after the scan failed (non-fatal): {e}")
    except Exception as e:
        print(f"Scan failed: {e}")
    finally:
        db.close()
 
 
def _feed_tick_job():
    """A few minutes of employer-feed crawling (see feed_crawler.py). Never raises."""
    try:
        from app.services.feed_crawler import run_feed_tick
        run_feed_tick()
    except Exception as e:
        print(f"Employer-feed tick failed (non-fatal): {e}")
 
 
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scan_for_all_users, "interval", minutes=SCAN_INTERVAL_MINUTES,
        max_instances=1,  # never run two scans at once (explicit; also APScheduler default)
        coalesce=True,    # if runs pile up (e.g. after downtime), collapse to a single catch-up run
    )
    # Employer career-site feeds: a short crawl slice every few minutes while the service is up.
    # (On a plan that sleeps when idle, /feeds/tick called by a free pinger keeps both going.)
    feed_minutes = max(5, int(os.getenv("FEED_TICK_MINUTES", "10")))
    scheduler.add_job(_feed_tick_job, "interval", minutes=feed_minutes, max_instances=1, coalesce=True)
    # Auto: sends approved applications soon after their undo window, follow-up reminders, and each
    # person's twice-daily pass. First run a few minutes after start-up, so a restart (a free plan
    # sleeps) never leaves due applications waiting a whole interval.
    try:
        from datetime import timedelta as _td
        from app.services.auto_runner import TICK_MINUTES
        scheduler.add_job(_auto_tick_job, "interval", minutes=TICK_MINUTES, max_instances=1, coalesce=True,
                          next_run_time=datetime.now() + _td(minutes=3))
    except Exception as e:
        print(f"Auto tick not scheduled (non-fatal): {e}")
    scheduler.start()
    return scheduler
 
 
def _auto_tick_job():
    """One Auto tick (see auto_runner.run_tick). Never raises."""
    try:
        from app.services.auto_runner import run_tick
        res = run_tick()
        if res.get("passes") or res.get("delivered") or res.get("recovered"):
            print(f"Auto tick: {res}")
    except Exception as e:
        print(f"Auto tick failed (non-fatal): {e}")
 
