from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import Response
import logging
import threading
from app.services.auth import require_auth_for_user
from app.services.ai_client import get_client
from app.services.tiers import require_feature
from app.services.rate_limit import rate_limit_by_tier
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
 
from app.db import get_db
from app.models.db_models import Profile, Listing, Outcome, RoadmapMilestone
from app.services.matching import rank_listings, rank_listings_with_near_misses, get_tag_weights_from_outcomes, get_personalized_factor_weights
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/listings", tags=["listings"])
 
# /listings/matches: pages ask for it a few times a day at most. Scoring a listings table is real
# CPU work on the one process every request shares - so, on every branch: one computation per user
# at a time, a few at once across everyone, and a daily ceiling far above what the pages need.
MATCHES_DAILY_LIMIT = 120
MATCHES_AT_ONCE = 2
LEGACY_MATCH_LIMIT = 2000           # the original ranking reads the newest listings, never the whole table
_MATCHES_SLOTS = threading.BoundedSemaphore(MATCHES_AT_ONCE)
_V2_IN_FLIGHT = set()
_V2_LOCK = threading.Lock()
 
 
def _v2_begin(user_id) -> bool:
    with _V2_LOCK:
        if str(user_id) in _V2_IN_FLIGHT:
            return False
        _V2_IN_FLIGHT.add(str(user_id))
        return True
 
 
def _v2_end(user_id):
    with _V2_LOCK:
        _V2_IN_FLIGHT.discard(str(user_id))
 
 
def _profile_to_dict(p: Profile) -> dict:
    """The profile's embedding is computed fresh here rather than
    stored - profile goal text changes far less often than listings
    get scanned, and computing it on-demand means it's never stale,
    unlike a cached value that would need invalidating on every
    profile edit. Degrades to None (no semantic factor) automatically
    if VOYAGE_API_KEY isn't configured - see app/services/embeddings.py.
    """
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
 
def _csv_param(v, cap=20, item_chars=60):
    if not isinstance(v, str) or not v.strip():
        return []
    return [x.strip()[:item_chars] for x in v.split(",") if x.strip()][:cap]
 
 
POOL_DAILY_LIMIT = 400              # the page asks on load, every 15 minutes and when a search changes field or place
_POOL_IN_FLIGHT = set()
_POOL_LOCK = threading.Lock()
 
 
@router.get("/pool/{user_id}")
def get_pool(user_id: str, request: Request, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user),
             roles: str | None = None, loc: str | None = None, modes: str | None = None, kw: str | None = None):
    """Job Search v2: everything the browser's Proof Match engine needs to
    score this user's search on the device - the listing pool (jobs,
    internships and programs, newest by the employer's own posting date,
    never past their deadline), the user's dismissed and saved ids, their
    resume entries, and their saved search state (preferences, learned
    rules, saved searches). The server runs the identical engine for Auto
    and alerts, so both sides agree on every score.
 
    On top of the shared pool come the employer career-site jobs picked for
    this person from the much larger employer pool: the role families their
    goal (or the search on the page - roles / loc / modes / kw) names, where
    they'd work. Every one is still scored in full on the page."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    # one pool at a time per person (a fast typist's searches don't stack up on a small server)
    with _POOL_LOCK:
        if user_id in _POOL_IN_FLIGHT:
            raise HTTPException(status_code=429, detail="Your listings are already loading - try again in a moment.")
        _POOL_IN_FLIGHT.add(user_id)
    try:
        from app.services.rate_limit import rate_limit
        rate_limit(db, user_id, "listing-pool", limit_per_day=POOL_DAILY_LIMIT)
        payload = _pool_payload(user_id, db, roles, loc, modes, kw)
    finally:
        with _POOL_LOCK:
            _POOL_IN_FLIGHT.discard(user_id)
    # a few MB of posting text: serialised and compressed here, in the worker thread - never on the event loop
    import gzip
    import json as _json
    body = _json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    if "gzip" in (request.headers.get("accept-encoding") or "").lower() and len(body) > 4096:
        return Response(content=gzip.compress(body, compresslevel=5), media_type="application/json",
                        headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(content=body, media_type="application/json", headers={"Vary": "Accept-Encoding"})
 
 
def _pool_payload(user_id, db, roles, loc, modes, kw) -> dict:
    from datetime import datetime as _dt, timezone as _tz
    from app.models.db_models import DismissedListing, SavedListing, ResumeEntry
    from app.services import job_search as JSV
    from app.services.job_engine import ENGINE_VERSION
    listings = JSV.pool_dicts(db)
    dismissed = sorted({str(r.listing_id) for r in db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()})
    saved = sorted({str(r.listing_id) for r in db.query(SavedListing).filter(SavedListing.user_id == user_id).all()})
    applied = sorted(JSV.applied_listing_ids(db, user_id))
    entries = JSV.entries_for_engine(db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all())
    state, state_ok = JSV.load_state_checked(db, user_id)
    pool_count = len(listings)
    feed, coverage = [], None
    try:
        profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
        query = {"roles": _csv_param(roles), "loc": (loc or "")[:200], "modes": _csv_param(modes, 3), "keywords": _csv_param(kw, 6, 40)}
        prefs = (state or {}).get("prefs") if isinstance((state or {}).get("prefs"), dict) else {}
        feed = JSV.feed_dicts(db, JSV.feed_want(JSV.profile_for_engine(profile), entries, prefs, query))
        # the employer jobs you saved or applied to stay in your pool while they're open, whatever you search for
        have = {d["id"] for d in feed} | {d["id"] for d in listings}
        mine = [i for i in list(saved) + list(applied) if i not in have]
        if mine:
            feed = feed + JSV.feed_dicts_by_ids(db, mine)
        from app.services.feed_crawler import coverage_cached
        coverage = coverage_cached(db)
    except Exception as e:
        db.rollback()
        _log.warning("employer-feed jobs skipped for %s: %s", user_id, e)
    listings = listings + feed
    return {
        "engine_version": ENGINE_VERSION,
        "generated_at": _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(listings),
        "truncated": pool_count >= JSV.POOL_LIMIT,
        # how many of the listings are employer career-site jobs picked for you, and the size of the pool they came from
        "employer_count": len(feed),
        "coverage": coverage,
        "listings": listings,
        "dismissed_ids": dismissed,
        "saved_ids": saved,
        # jobs with an application already (Auto's, or a draft you accepted): the page
        # leaves them out of your feed, exactly as Auto and alerts do
        "applied_ids": applied,
        "entries": entries,
        "state": (state or None) if state_ok else None,
        # the saved settings couldn't be read just now (not "there are none"): the page keeps its copy and waits
        "state_unavailable": not state_ok,
    }
 
 
@router.get("/matches/{user_id}")
def get_matches(user_id: str, engine: str | None = None, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Returns the current top-ranked listings for a user, scored live
    against whatever's currently in the listings table. Roadmap
    alignment is a real, graded factor baked directly into the score
    itself now, not just a decorative field shown alongside a number
    it never influenced - a listing that clearly advances the user's
    current roadmap stage genuinely ranks higher than an otherwise-
    identical one that doesn't. The specific stage/milestone matched
    is still surfaced per-listing via factors.roadmap_alignment, for
    explanation and UI display.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if not _v2_begin(user_id):
        raise HTTPException(status_code=429, detail="Your matches are already being worked out - try again in a moment.")
    try:
        if not _MATCHES_SLOTS.acquire(timeout=20):
            raise HTTPException(status_code=503, detail="Matching is busy right now - try again in a moment.")
        try:
            # counted only once the request is really going to run
            from app.services.rate_limit import rate_limit
            rate_limit(db, user_id, "listing-matches", limit_per_day=MATCHES_DAILY_LIMIT)
            return _get_matches(user_id, engine, db)
        finally:
            _MATCHES_SLOTS.release()
    finally:
        _v2_end(user_id)
 
 
def _get_matches(user_id: str, engine, db):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    # Job Search v2 ("?engine=v2", what the web app asks for): the same honest
    # Proof Match fit the Job Search page shows, in the shape older pages read.
    # Athletes keep the athletics ranking. Any failure falls through to the
    # original ranking below rather than returning nothing.
    if engine == "v2" and not getattr(profile, "is_athlete", False):
        try:
            from app.services import job_search as JSV
            # "top matches" are the best fits, whatever display sort the Job Search page uses
            return JSV.v2_matches_payload(JSV.analyze_for_user(db, user_id, profile, best_first=True, feed_limit=JSV.FEED_SERVER_LIMIT))
        except Exception as e:
            db.rollback()   # a failed query leaves the session unusable for the fallback below
            _log.warning("v2 matches failed for %s, using the original ranking: %s", user_id, e)
 
    from app.services.feed_common import not_feed
    try:
        listings = db.query(Listing).filter(not_feed(Listing)).order_by(Listing.fetched_at.desc()).limit(LEGACY_MATCH_LIMIT).all()
    except Exception:
        db.rollback()
        listings = db.query(Listing).filter(not_feed(Listing)).limit(LEGACY_MATCH_LIMIT).all()
    if not listings:
        return {"matches": [], "note": "No listings in the database yet - run a scan first."}
 
    # Pull this user's real outcome history and let it adjust scores -
    # this is the actual "self-correcting" piece: a heuristic, not
    # machine learning, but grounded in real recorded results.
    outcome_rows = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    listings_by_id = {str(l.id): l for l in listings}
    outcome_dicts = []
    for o in outcome_rows:
        listing = listings_by_id.get(str(o.listing_id))
        if listing:
            outcome_dicts.append({"tags": listing.tags or [], "status": o.status, "updated_at": o.updated_at})
    tag_weights = get_tag_weights_from_outcomes(outcome_dicts)
 
    # The higher-order learning layer: not just which tags predicted
    # success (tag_weights above), but which TYPES of signal did -
    # joins this user's past applications (with their preserved factor
    # breakdown) against the real outcomes those specific listings
    # led to.
    from app.models.db_models import Application
    applications_with_snapshots = (
        db.query(Application)
        .filter(Application.user_id == user_id, Application.factors_snapshot.isnot(None))
        .all()
    )
    outcome_status_by_listing = {str(o.listing_id): o.status for o in outcome_rows}
    outcome_time_by_listing = {str(o.listing_id): o.updated_at for o in outcome_rows}
    factor_learning_input = [
        {"factors_snapshot": a.factors_snapshot, "outcome_status": outcome_status_by_listing[str(a.listing_id)], "updated_at": outcome_time_by_listing.get(str(a.listing_id))}
        for a in applications_with_snapshots
        if str(a.listing_id) in outcome_status_by_listing
    ]
    factor_weights = get_personalized_factor_weights(factor_learning_input)
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    milestone_dicts = [{"stage": m.target_stage, "title": m.title, "description": m.description} for m in milestones]
 
    ranked, near_misses = rank_listings_with_near_misses(
        [_listing_to_dict(l) for l in listings],
        _profile_to_dict(profile),
        top_n=10,
        tag_weights=tag_weights,
        factor_weights=factor_weights,
        roadmap_milestones=milestone_dicts,
    )
 
    low_match_note = None
    if len(ranked) == 0:
        low_match_note = "No strong matches this cycle - nothing in the current listing pool genuinely clears the bar for your stated goal and skills. This isn't padded with weaker options; check the near-misses below for what came closest, or broaden your search criteria."
    elif len(ranked) < 5:
        low_match_note = f"Only {len(ranked)} listing{'s' if len(ranked) != 1 else ''} genuinely cleared the quality bar this cycle - shown as-is rather than padded with weaker options to hit a round number."
 
    return {
        "matches": ranked,
        "near_misses": near_misses,
        "profile_id": str(profile.id),
        "outcomes_considered": len(outcome_dicts),
        "factor_weights_learned": factor_weights,
        "applications_used_for_learning": len(factor_learning_input),
        "low_match_note": low_match_note,
    }
 
 
@router.post("/scan/{user_id}")
async def trigger_scan(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Manually triggers an immediate scan: pulls fresh listings from
    Adzuna (if any are new), then re-scores everything for this user.
    If the user has Auto Apply mode enabled, this also automatically
    drafts and queues applications for every eligible match above
    their configured threshold - no manual starring required.
    """
    import os
    import anthropic
    import uuid as uuid_module
    from app.services.scheduler import run_scan_for_user, _pull_and_store_new_listings
    from app.services.auto_apply import auto_apply_and_outreach_for_user
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    # Meter the manual scan: the most expensive action (Adzuna pulls + AI drafting).
    # Fails open. The current frontend doesn't call this route (watch mode re-scores
    # via GET matches), so this purely caps direct/abusive hammering of it.
    rate_limit_by_tier(db, user_id, "listing-scan", per_action_limit=50)
 
    import asyncio
    from starlette.concurrency import run_in_threadpool
    # The pull makes blocking calls (tagging, embeddings, the database, parsing every
    # new posting), so it runs on a worker thread with its own event loop - never on
    # the loop every other request shares. The session is used by one thread at a time.
    new_count = await run_in_threadpool(lambda: asyncio.run(_pull_and_store_new_listings(db)))
 
    def _rescore_and_auto():
        # Scoring 800 listings is real CPU work: it runs in the worker threadpool,
        # never on the event loop every other request shares.
        result = run_scan_for_user(db, user_id)
        result["new_listings_pulled"] = new_count
        profile = (
            db.query(Profile)
            .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
            .first()
        )
        auto_applied = []
        auto_drafted_outreach = []
        client = get_client()
        if profile and profile.auto_apply_enabled and client is not None:
            if getattr(profile, "is_athlete", False):
                from app.services.feed_common import not_feed
                listings = db.query(Listing).filter(not_feed(Listing)).all()
                from app.models.db_models import DismissedListing
                dismissed_ids = {str(row.listing_id) for row in db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()}
                ranked = rank_listings([_listing_to_dict(l) for l in listings], _profile_to_dict(profile), top_n=10, dismissed_ids=dismissed_ids)
            else:
                # Same as the nightly scan: Auto acts on the user's own Job Search v2
                # matches (their honest fit, their dealbreakers) - or not at all.
                try:
                    from app.services.job_search import auto_candidates
                    ranked = auto_candidates(db, user_id, profile)
                except Exception as e:
                    db.rollback()
                    _log.warning("v2 auto candidates failed for %s: %s", user_id, e)
                    ranked = []
            # Same shared autonomous pass as the nightly scheduler: it enforces the
            # user's own acceptance rules + daily cap (the set the Auto page previews)
            # so a manual "scan now" applies to exactly what the engine would apply to
            # unattended - never bypassing the rules, which matters most once consent
            # has removed the undo window. Each listing is isolated inside the helper.
            summary = auto_apply_and_outreach_for_user(db, client, user_id, profile, ranked)
            auto_applied = summary["applied"]
            auto_drafted_outreach = summary["outreach"]
        result["auto_applied"] = auto_applied
        result["auto_drafted_outreach"] = auto_drafted_outreach
        return result
 
    return await run_in_threadpool(_rescore_and_auto)
 
 
@router.get("/matches/{user_id}/explain/{listing_id}")
def explain_match_deep(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    require_feature(db, user_id, "deep_match_explanations")
    rate_limit_by_tier(db, user_id, "deep-explain", per_action_limit=200)
    """On-demand DEEP explanation of why a listing is a good match -
    a real Claude call producing an actual paragraph grounded in the
    full profile, the listing, and the roadmap if one exists. This is
    separate from the free, instant explain_score() text that ships
    with every match by default - that one covers the same signals
    but as a quick multi-clause sentence. This endpoint is for when
    someone wants more depth than that, and is deliberately only
    called when asked for, not automatically for every listing in a
    scan (which would multiply your Anthropic usage by however many
    matches are returned, every cycle).
    """
    import os
    import anthropic
    from app.models.db_models import RoadmapMilestone
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    try:
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    roadmap_line = ""
    if milestones:
        roadmap_line = "Their roadmap:\n" + "\n".join(f"{m.target_stage}. {m.title}" for m in milestones) + "\n\n"
 
    from app.services.feed_common import listing_text, listing_tags
    posting_text = listing_text(db, listing)   # employer-feed jobs keep their text compressed elsewhere
    tags = listing_tags(db, listing, text=posting_text)   # ...and carry no stored tags: their posting's skills stand in
    description_line = ""
    if posting_text:
        description_line = f"The actual posting text (not just its extracted tags): \"{posting_text[:1500]}\"\n\n"
 
    prompt = (
        f"A candidate's goal: \"{profile.northstar}\". What 'made it' looks like: \"{profile.final_idea or ''}\". "
        f"Their skills: \"{profile.skills or ''}\". What matters most to them: {', '.join(profile.priorities or [])}. "
        f"Location preference: \"{profile.location_pref or ''}\".\n\n"
        f"{roadmap_line}"
        f"A listing they're considering: \"{listing.title}\" at {listing.org} ({listing.type}), "
        f"location {listing.location or 'unspecified'}, tags: {', '.join(tags)}.\n\n"
        f"{description_line}"
        "Write a genuine, specific 3-4 sentence case for why this is or isn't a strong match for "
        "THIS candidate specifically - reference their actual goal, skills, priorities, and roadmap "
        f"by name where relevant.{' If the actual posting text above reveals something the tags alone would have missed - a specific requirement, a seniority signal, team context - point that out specifically.' if posting_text else ''} "
        "Be honest about weak fit if it's weak, don't oversell. No generic "
        "filler like 'this could be a great opportunity' - every sentence should reference a specific "
        "fact about the candidate or the listing."
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        explanation = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    except Exception as e:
        _log.warning("Could not generate this explanation just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate this explanation just now. Please try again.")
    return {"listing_id": listing_id, "listing_title": listing.title, "explanation": explanation}
 
 
@router.get("/matches/{user_id}/connect/{listing_id}")
def get_connection_strategy(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    require_feature(db, user_id, "outreach_drafting")
    rate_limit_by_tier(db, user_id, "outreach-draft", per_action_limit=200)
    """Generates a real referral/networking strategy for a specific
    listing - who to look for, how to actually find them, and a
    tailored outreach message. This deliberately does NOT invent a
    real named person at the company: there is no data source
    connected here that has real employee/contact information, and
    fabricating a name would be presenting made-up data as real,
    which is a much worse outcome than being upfront that this is
    guidance rather than an actual contact lookup.
    """
    import os
    import anthropic
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    try:
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    from app.services.feed_common import listing_tags
    prompt = (
        f"A candidate is applying to \"{listing.title}\" at {listing.org} ({listing.type}), "
        f"tags: {', '.join(listing_tags(db, listing))}. Their background: skills \"{profile.skills or ''}\", "
        f"goal \"{profile.northstar}\".\n\n"
        "Help them get a real human connection at this company before applying cold. Return a JSON "
        "object with exactly these three keys:\n"
        "- contact_type: the specific TYPE of person worth reaching out to for this role (e.g. "
        "'someone currently in a similar individual-contributor role on this team' or 'the hiring "
        "manager, likely titled X') - a role description, never a real invented name\n"
        "- search_guidance: 1-2 concrete sentences on exactly how to actually find that person - "
        "specific search terms or approach (e.g. what to search on LinkedIn, alumni networks, or "
        "a company's team page), not 'network more'\n"
        "- outreach_message: a genuine, specific 80-120 word message they could send once they find "
        "someone - reference the candidate's real skills/goal and the specific role, ask for a short "
        "conversation or referral, not generic flattery\n\n"
        "Return ONLY valid JSON with exactly those three keys, nothing else, no markdown fences."
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        import json
        parsed = json.loads(text)
        # Match the frontend's strict shape check (fetchConnectionStrategy, which
        # throws on any non-string key). Previously `.get(k, "")` below silently
        # turned a MISSING key into an empty string, so a logged-in user could get
        # a blank outreach_message that then flowed straight into a drafted outreach
        # email - while an offline user (the FE direct path) correctly got a "try
        # again". Rejecting an incomplete/empty shape here makes both paths behave
        # identically (this raise is caught just below and returned as a 502).
        if not all(isinstance(parsed.get(k), str) and parsed.get(k).strip()
                   for k in ("contact_type", "search_guidance", "outreach_message")):
            raise ValueError("connection strategy response has an unexpected or empty shape")
    except Exception as e:
        _log.warning("Could not generate a connection strategy just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate a connection strategy just now. Please try again.")
 
    return {
        "listing_id": listing_id,
        "listing_title": listing.title,
        "listing_org": listing.org,
        "contact_type": parsed["contact_type"],
        "search_guidance": parsed["search_guidance"],
        "outreach_message": parsed["outreach_message"],
    }
 
 
@router.get("/matches/{user_id}/connect/{listing_id}/guess-email")
def guess_contact_email(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Returns a best-guess general contact address for the company -
    explicitly NOT a specific verified person, since no real employee
    lookup is connected. The frontend shows this to the user before
    any send happens - this is the one confirmation step that stays
    in place regardless of how the send flow is triggered.
    """
    from app.services.email_send import guess_contact_emails
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    guess = guess_contact_emails(listing.org)
    return {"listing_id": listing_id, "listing_org": listing.org, **guess}
 
 
class SendOutreachIn(BaseModel):
    to_address: str = Field(max_length=300)
    subject: str = Field(max_length=500)
    body: str = Field(max_length=10000)
    address_verified: bool = False
 
 
@router.post("/matches/{user_id}/connect/{listing_id}/send-email")
def send_outreach_email(user_id: str, listing_id: str, payload: SendOutreachIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Actually sends a real email via Resend, and logs it. The
    to_address must be supplied by the caller (i.e. shown to and
    confirmed by the user in the frontend first) - this endpoint does
    not look up or choose the recipient itself.
    """
    from app.services.email_send import send_email
    from app.models.db_models import OutreachEmail
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    try:
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    # Outreach is a Pro+ feature and every OTHER path that touches it enforces
    # that: outreach.py's draft endpoints call require_feature("outreach_drafting"),
    # and the sibling get_connection_strategy in THIS file gates + meters the same
    # way. This endpoint - which does the most sensitive thing of all, sending a
    # REAL email via Resend to a caller-supplied arbitrary address - was the lone
    # one enforcing neither, so a Free user (or any token) could send arbitrary,
    # unmetered real email through the app's own verified sending domain, bypassing
    # both the tier gate and every send cap the rest of the feature has. Gate and
    # meter it identically to its sibling so the enforcement is real, not cosmetic.
    require_feature(db, user_id, "outreach_drafting")
    rate_limit_by_tier(db, user_id, "outreach-draft", per_action_limit=200)
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    status = "sent"
    error_detail = None
    try:
        send_email(payload.to_address, payload.subject, payload.body)
    except Exception as e:
        status = "failed"
        error_detail = str(e)
 
    # One outreach row per (user, listing): the rest of the codebase reads outreach
    # with .filter(user_id, listing_id).first() and OutreachEmail carries
    # UNIQUE(user_id, listing_id). So record this send by UPDATING an existing row
    # for this listing (e.g. a prior draft) if there is one, else inserting. A bare
    # insert would both violate the constraint (500, after the email already sent)
    # and leave two rows that every .first()-based read would then pick between
    # arbitrarily.
    def _apply(row):
        row.to_address = payload.to_address
        row.address_verified = payload.address_verified
        row.subject = payload.subject
        row.body = payload.body
        row.status = status
 
    log = (
        db.query(OutreachEmail)
        .filter(OutreachEmail.user_id == user_id, OutreachEmail.listing_id == listing_id)
        .first()
    )
    if log:
        _apply(log)
        db.commit()
    else:
        log = OutreachEmail(user_id=user_id, listing_id=listing_id)
        _apply(log)
        db.add(log)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent send/draft won the (user, listing) slot - update it instead.
            db.rollback()
            log = (
                db.query(OutreachEmail)
                .filter(OutreachEmail.user_id == user_id, OutreachEmail.listing_id == listing_id)
                .first()
            )
            if not log:
                raise
            _apply(log)
            db.commit()
 
    if status == "failed":
        # error_detail is the raw send-provider exception (str(e)); log it
        # server-side and return a generic message rather than leaking it.
        _log.warning("Outreach email send failed - %s", error_detail)
        raise HTTPException(status_code=502, detail="Sending the email failed just now. Please try again.")
    return {"status": "sent", "to_address": payload.to_address}
 
