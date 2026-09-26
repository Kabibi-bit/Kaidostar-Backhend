from fastapi import APIRouter, HTTPException, Depends
import logging
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
 
@router.get("/matches/{user_id}")
def get_matches(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
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
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    listings = db.query(Listing).all()
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
    from app.services.auto_apply import create_application_for_match, draft_outreach_for_match
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    # Meter the manual scan: the most expensive action (Adzuna pulls + AI drafting).
    # Fails open. The current frontend doesn't call this route (watch mode re-scores
    # via GET matches), so this purely caps direct/abusive hammering of it.
    rate_limit_by_tier(db, user_id, "listing-scan", per_action_limit=50)
 
    new_count = await _pull_and_store_new_listings(db)
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
        listings = db.query(Listing).all()
        from app.models.db_models import DismissedListing
        dismissed_ids = {str(row.listing_id) for row in db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()}
        ranked = rank_listings([_listing_to_dict(l) for l in listings], _profile_to_dict(profile), top_n=10, dismissed_ids=dismissed_ids)
        for listing in ranked:
            # Isolate each listing so one failure doesn't abort the rest of the
            # user's auto-apply/outreach batch (and doesn't 500 the whole request).
            try:
                outcome = create_application_for_match(db, client, user_id, listing["id"], auto_generated=True)
                if not outcome.get("error") and not outcome.get("already_existed") and outcome.get("status") == "approved":
                    auto_applied.append({"listing_id": listing["id"], "title": listing["title"], "confidence": outcome["composite_confidence"]})
            except Exception:
                db.rollback()
 
            # Auto mode also drafts a referral outreach email for the
            # same eligible matches - queued in Workshop, never sent
            # automatically. This is what runs "while you're away":
            # by the time you're back, applications AND outreach
            # drafts are both waiting for a single review/send click.
            try:
                outreach_result = draft_outreach_for_match(db, client, user_id, listing["id"], auto_generated=True)
                if not outreach_result.get("error") and not outreach_result.get("already_existed"):
                    auto_drafted_outreach.append({"listing_id": listing["id"], "title": listing["title"], "to_address": outreach_result.get("to_address")})
            except Exception:
                db.rollback()
    result["auto_applied"] = auto_applied
    result["auto_drafted_outreach"] = auto_drafted_outreach
 
    return result
 
 
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
 
    description_line = ""
    if listing.description:
        description_line = f"The actual posting text (not just its extracted tags): \"{listing.description[:1500]}\"\n\n"
 
    prompt = (
        f"A candidate's goal: \"{profile.northstar}\". What 'made it' looks like: \"{profile.final_idea or ''}\". "
        f"Their skills: \"{profile.skills or ''}\". What matters most to them: {', '.join(profile.priorities or [])}. "
        f"Location preference: \"{profile.location_pref or ''}\".\n\n"
        f"{roadmap_line}"
        f"A listing they're considering: \"{listing.title}\" at {listing.org} ({listing.type}), "
        f"location {listing.location or 'unspecified'}, tags: {', '.join(listing.tags or [])}.\n\n"
        f"{description_line}"
        "Write a genuine, specific 3-4 sentence case for why this is or isn't a strong match for "
        "THIS candidate specifically - reference their actual goal, skills, priorities, and roadmap "
        f"by name where relevant.{' If the actual posting text above reveals something the tags alone would have missed - a specific requirement, a seniority signal, team context - point that out specifically.' if listing.description else ''} "
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
 
    prompt = (
        f"A candidate is applying to \"{listing.title}\" at {listing.org} ({listing.type}), "
        f"tags: {', '.join(listing.tags or [])}. Their background: skills \"{profile.skills or ''}\", "
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
 
