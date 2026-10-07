import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit_by_tier
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import Outcome, Listing, SocialPost
from app.services.timeutil import utcnow, to_naive_utc
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/outcomes", tags=["outcomes"])
 
VALID_STATUSES = {"applied", "interview", "rejected", "ghosted", "offer"}
 
 
class OutcomeIn(BaseModel):
    user_id: str
    listing_id: str
    status: str
    reflection: str | None = Field(default=None, max_length=4000)
 
 
@router.post("")
def log_outcome(payload: OutcomeIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Logs a real outcome on an application - the other major
    'something real just happened' moment this app already tracks,
    alongside milestone completion. When a real reflection is
    provided in the same request, also creates a genuine, linked
    Waypoint entry - grounded in the actual listing and outcome, not
    a generic journal prompt. Entirely optional and backward
    compatible - a bare outcome log with no reflection behaves
    exactly as it always has.
    """
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}")
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
        uuid_module.UUID(payload.listing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id and listing_id must be valid UUIDs")
    # Body carries user_id, so verify the token against it directly.
    verify_token_belongs_to_user(payload.user_id, authorization)
    outcome = Outcome(user_id=payload.user_id, listing_id=payload.listing_id, status=payload.status)
    db.add(outcome)
 
    journal_entry_id = None
    if payload.reflection and payload.reflection.strip():
        listing = db.query(Listing).filter(Listing.id == payload.listing_id).first()
        listing_label = f"{listing.title} at {listing.org}" if listing else "a listing"
        outcome_label = {"interview": "Got an interview", "offer": "Got an offer", "rejected": "Rejected", "ghosted": "Ghosted", "applied": "Applied"}.get(payload.status, payload.status)
        post = SocialPost(
            user_id=payload.user_id, body=payload.reflection.strip(),
            tag_value=payload.status, tag_label=f"{outcome_label}: {listing_label}",
        )
        db.add(post)
        db.flush()  # so post.id is populated before commit, to return it below
        journal_entry_id = str(post.id)
 
    db.commit()
    return {"status": "logged", "outcome_status": payload.status, "journal_entry_id": journal_entry_id}
 
 
@router.get("/{user_id}")
def get_outcomes(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return []
    rows = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    return [{"listing_id": str(r.listing_id), "status": r.status, "updated_at": r.updated_at.isoformat()} for r in rows]
 
 
@router.get("/{user_id}/stats")
def get_outcome_stats(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Real aggregation backing the dashboard's donut chart and monthly
    target chart - each application counted ONCE by its latest status, and by
    the month of that latest status, computed from actual logged outcomes (no
    mock numbers).
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"total": 0, "by_status": {}, "by_month": {}}
 
    # An application progresses through statuses over time - applied -> interview
    # -> offer - and log_outcome INSERTs a NEW Outcome row for each step (it never
    # updates in place). Counting raw rows would tally that single application
    # three times, once per status, inflating the donut's total and every segment.
    # The donut means "where each application LANDED" (its latest status), so
    # collapse to the latest outcome per listing first - ordered updated_at ASC so
    # the dict keeps the most recent status per listing (last write wins). Same
    # latest-per-listing dedup the calibration / reminders routes already use.
    rows = (
        db.query(Outcome)
        .filter(Outcome.user_id == user_id)
        .order_by(Outcome.updated_at.asc())
        .all()
    )
    latest_by_listing = {}  # listing_id -> latest Outcome (via asc ordering, last wins)
    for r in rows:
        latest_by_listing[str(r.listing_id)] = r
    latest = list(latest_by_listing.values())
 
    by_status = {}
    for r in latest:
        by_status[r.status] = by_status.get(r.status, 0) + 1
 
    by_month = {}
    for r in latest:
        month_key = r.updated_at.strftime("%b")
        by_month[month_key] = by_month.get(month_key, 0) + 1
 
    return {
        "total": len(latest),
        "by_status": by_status,
        "by_month": by_month,
    }
 
 
@router.get("/{user_id}/calibration")
def get_calibration(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Is Kaidostar's own confidence score actually trustworthy for THIS
    user? Joins real logged outcomes back to the confidence score each
    application had when sent, and reports the real conversion rate
    per confidence bucket. This is the honest, self-auditing feature -
    it will show unflattering numbers if the score isn't well
    calibrated for someone, rather than hiding that.
    """
    from app.models.db_models import Application
    from app.services.calibration import compute_calibration
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"calibration": {}, "total_applications_with_logged_outcomes": 0, "note": None}
 
    # order_by updated_at ASC: the "latest outcome per listing" dedup below is
    # last-write-wins, so unordered rows could label a listing with a stale
    # earlier status (applied instead of a later offer), skewing calibration /
    # personalization. Same ordering the reminders route already uses.
    outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).order_by(Outcome.updated_at.asc()).all()
    applications = db.query(Application).filter(Application.user_id == user_id).all()
 
    outcome_dicts = [{"listing_id": str(o.listing_id), "status": o.status} for o in outcomes]
    app_dicts = [{"listing_id": str(a.listing_id), "confidence_pct": a.confidence_pct} for a in applications]
 
    calibration = compute_calibration(app_dicts, outcome_dicts)
    total_with_outcomes = sum(b["total_with_outcomes"] for b in calibration.values())
    return {
        "calibration": calibration,
        "total_applications_with_logged_outcomes": total_with_outcomes,
        "note": "Buckets with fewer than a handful of outcomes aren't statistically meaningful yet - log more real outcomes to sharpen this." if total_with_outcomes < 5 else None,
    }
 
 
@router.get("/{user_id}/personalization-audit")
def get_personalization_audit(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The self-audit no mainstream job platform does: checks whether
    Kaidostar's OWN personalized scoring is actually helping THIS user,
    or just moving numbers around. Compares the real (personalized)
    score each application had against what it would have scored
    without personalization, restricted to cases where the two
    genuinely differed - then checks which version better tracked
    the real outcome. Will honestly report "hurting" if that's what
    the data shows.
    """
    from app.models.db_models import Application
    from app.services.matching import audit_personalization_effect
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"verdict": "insufficient_data", "sample_size": 0, "note": "No current profile for this user"}
 
    # order_by updated_at ASC: the "latest outcome per listing" dedup below is
    # last-write-wins, so unordered rows could label a listing with a stale
    # earlier status (applied instead of a later offer), skewing calibration /
    # personalization. Same ordering the reminders route already uses.
    outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).order_by(Outcome.updated_at.asc()).all()
    outcome_by_listing = {str(o.listing_id): o.status for o in outcomes}
 
    applications = (
        db.query(Application)
        .filter(
            Application.user_id == user_id,
            Application.counterfactual_confidence_pct.isnot(None),
            # confidence_pct is a nullable column (Numeric, no nullable=False), and
            # the audit needs BOTH values as floats - float(a.confidence_pct) on a
            # NULL (a legacy/partial row that has a counterfactual but no confidence)
            # would raise TypeError and 500 this route. Guard it the same way the
            # counterfactual is already guarded, rather than assuming it's set.
            Application.confidence_pct.isnot(None),
        )
        .all()
    )
    audit_input = [
        {
            "confidence_pct": float(a.confidence_pct),
            "counterfactual_confidence_pct": float(a.counterfactual_confidence_pct),
            "outcome_status": outcome_by_listing[str(a.listing_id)],
        }
        for a in applications
        if str(a.listing_id) in outcome_by_listing
    ]
    return audit_personalization_effect(audit_input)
 
 
@router.get("/{user_id}/personalization-insights")
def get_personalization_insights(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    rate_limit_by_tier(db, user_id, "explain-outcome", per_action_limit=200)
    """The genuine depth upgrade beyond factor-category reweighting -
    reads the real content of applications you actually sent, not
    just pre-computed numeric factor tallies, and finds specific,
    content-grounded patterns in what's actually worked. Complements
    /personalization-audit (which checks whether the numeric
    reweighting is helping) with something numbers alone can't give:
    real qualitative insight into what you've actually written.
    """
    from app.models.db_models import Application, Listing
    from app.services.matching import generate_deep_personalization_insights
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"insights": [], "sample_size": 0, "note": "No current profile for this user"}
 
    # order_by updated_at ASC: the "latest outcome per listing" dedup below is
    # last-write-wins, so unordered rows could label a listing with a stale
    # earlier status (applied instead of a later offer), skewing calibration /
    # personalization. Same ordering the reminders route already uses.
    outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).order_by(Outcome.updated_at.asc()).all()
    outcome_by_listing = {str(o.listing_id): o.status for o in outcomes}
 
    applications = (
        db.query(Application, Listing)
        .join(Listing, Application.listing_id == Listing.id)
        .filter(Application.user_id == user_id)
        .order_by(Application.created_at)
        # Without an explicit order, PostgreSQL returns rows in an
        # unspecified order that "must not be relied on" (per the
        # official docs) - meaning "Application 3" could genuinely
        # refer to a different real application between calls, which
        # would directly undermine the whole point of the model
        # referencing applications by number and the flagged_insight
        # check that verifies those references. Ordered by creation
        # time so the numbering is stable and chronologically sensible.
        .all()
    )
    # employer-feed jobs carry no stored tags - the skills read in their postings stand in, read in one
    # query, and only for the applications the insight can actually use (a draft and an outcome)
    from app.services.feed_common import tags_by_listing
    tags = tags_by_listing(db, [listing for a, listing in applications
                                if a.draft_content and outcome_by_listing.get(str(a.listing_id))])
    app_input = [
        {
            "draft_content": a.draft_content,
            "listing_title": listing.title,
            "listing_org": listing.org,
            "listing_tags": tags.get(str(listing.id), listing.tags or []),
            "outcome_status": outcome_by_listing.get(str(a.listing_id)),
        }
        for a, listing in applications
    ]
    try:
        return generate_deep_personalization_insights(client, app_input)
    except Exception as e:
        _log.warning("Could not generate personalization insights just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate personalization insights just now. Please try again.")
 
 
@router.get("/{user_id}/factor-interactions")
def get_factor_interactions(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Goes beyond /personalization-audit and the numeric weights in
    /listings/matches: those can only ever say whether a SINGLE
    factor predicts success in isolation. This checks whether PAIRS
    of signals only work TOGETHER - e.g. real skill overlap might
    only actually predict success for this person when it's paired
    with genuine conceptual fit, and neither alone is enough. A real
    statistical concept (interaction effects) that even sophisticated
    platforms rarely expose transparently.
    """
    from app.models.db_models import Application
    from app.services.matching import compute_factor_interactions
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"findings": [], "sample_size": 0, "readiness": []}
 
    # order_by updated_at ASC: the "latest outcome per listing" dedup below is
    # last-write-wins, so unordered rows could label a listing with a stale
    # earlier status (applied instead of a later offer), skewing calibration /
    # personalization. Same ordering the reminders route already uses.
    outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).order_by(Outcome.updated_at.asc()).all()
    outcome_by_listing_status = {str(o.listing_id): o.status for o in outcomes}
 
    applications = (
        db.query(Application)
        .filter(Application.user_id == user_id, Application.factors_snapshot.isnot(None))
        .all()
    )
    app_input = [
        {"factors_snapshot": a.factors_snapshot, "outcome_status": outcome_by_listing_status[str(a.listing_id)]}
        for a in applications
        if str(a.listing_id) in outcome_by_listing_status
    ]
    from app.services.matching import get_interaction_readiness
    findings = compute_factor_interactions(app_input)
    readiness = get_interaction_readiness(app_input)
    return {"findings": findings, "sample_size": len(app_input), "readiness": readiness}
 
 
STALE_THRESHOLD_DAYS = 14
INTERVIEW_FOLLOWUP_DAYS = 7
 
 
@router.get("/{user_id}/reminders")
def get_reminders(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Surfaces real, time-sensitive nudges Jobright's tracker lacks -
    it has statuses (Applied, Interviewing, Offer...) but no layer
    prompting timely action on them. Two genuinely distinct cases,
    mirroring the frontend exactly:
 
    - interview_followups: an application whose LATEST outcome is
      'interview', logged more than INTERVIEW_FOLLOWUP_DAYS ago with
      nothing newer. Higher-stakes and time-sensitive (interview
      momentum decays fast), so a shorter window.
    - stale_applications: a genuinely sent application with NO logged
      outcome at all, past STALE_THRESHOLD_DAYS - a cold, never-
      answered application, a real signal to focus elsewhere.
 
    An application that progressed past interview (to offer or
    rejection) is correctly in neither list.
    """
    import uuid as uuid_module
    from app.models.db_models import Application
    from datetime import datetime
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    now = utcnow()
 
    # Each application's LATEST outcome by listing - a later 'offer'
    # must genuinely supersede an earlier 'interview', so ordering by
    # updated_at and keeping the most recent per listing is the only
    # correct read, not just any interview row that ever existed.
    outcome_rows = (
        db.query(Outcome)
        .filter(Outcome.user_id == user_id)
        .order_by(Outcome.updated_at.asc())
        .all()
    )
    latest_outcome = {}  # listing_id -> (status, updated_at), last write wins via asc ordering
    for o in outcome_rows:
        latest_outcome[str(o.listing_id)] = (o.status, o.updated_at)
 
    applications = db.query(Application).filter(Application.user_id == user_id).all()
    # only the listings this user applied to - the table also holds the large employer-job pool
    app_listing_ids = list({a.listing_id for a in applications if a.listing_id is not None})
    listings = {str(l.id): l for l in db.query(Listing).filter(Listing.id.in_(app_listing_ids)).all()} if app_listing_ids else {}
 
    interview_followups = []
    stale_applications = []
    for a in applications:
        lid = str(a.listing_id)
        listing = listings.get(lid)
        title = listing.title if listing else "a listing"
        org = listing.org if listing else ""
        outcome = latest_outcome.get(lid)
 
        if outcome and outcome[0] == "interview":
            # to_naive_utc: updated_at is TIMESTAMPTZ (read back tz-aware); subtracting
            # it from the naive `now` would raise on real Postgres without this.
            days = (now - to_naive_utc(outcome[1])).days
            if days >= INTERVIEW_FOLLOWUP_DAYS:
                interview_followups.append({"listing_id": lid, "title": title, "org": org, "days_since_interview": days})
        elif not outcome and a.status == "sent" and a.sent_at:
            # to_naive_utc: sent_at is TIMESTAMPTZ (read back tz-aware); see above.
            days = (now - to_naive_utc(a.sent_at)).days
            if days >= STALE_THRESHOLD_DAYS:
                stale_applications.append({"listing_id": lid, "title": title, "org": org, "days_since_sent": days})
 
    return {"interview_followups": interview_followups, "stale_applications": stale_applications}
 
 
SEARCH_STRAIN_MIN_SENT = 15
SEARCH_STRAIN_MIN_DAYS = 21
 
 
@router.get("/{user_id}/search-strain")
def get_search_strain(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The honest, human answer to the documented burnout dimension:
    a long, high-volume search with no positive traction quietly
    erodes confidence, and a tool that just says 'apply to more'
    makes it worse. This reflects a genuine pattern in the person's
    OWN logged data - never cheerleading, never manufactured concern.
    Only fires with real volume (SEARCH_STRAIN_MIN_SENT genuinely
    sent), over a real span (SEARCH_STRAIN_MIN_DAYS), with ZERO
    positive outcomes. A single interview or offer anywhere means the
    approach is working somewhere - no strain flag. Mirrors the
    frontend's detectSearchStrainPattern exactly.
    """
    import uuid as uuid_module
    from datetime import datetime
    from app.models.db_models import Application
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    now = utcnow()
    sent = (
        db.query(Application)
        .filter(Application.user_id == user_id, Application.status == "sent", Application.sent_at.isnot(None))
        .all()
    )
    if len(sent) < SEARCH_STRAIN_MIN_SENT:
        return {"strain": None}
 
    # Any positive outcome anywhere means it's working - no strain.
    positive_exists = (
        db.query(Outcome)
        .filter(Outcome.user_id == user_id, Outcome.status.in_(["interview", "offer"]))
        .first()
    )
    if positive_exists:
        return {"strain": None}
 
    # to_naive_utc: sent_at is TIMESTAMPTZ (read back tz-aware), so subtracting the
    # min of them from the naive `now` would raise on real Postgres. This endpoint
    # fires precisely for a long-searching user with no positive outcome - exactly
    # the case that hits this line - so the coercion matters.
    oldest = to_naive_utc(min(a.sent_at for a in sent))
    span_days = (now - oldest).days
    if span_days < SEARCH_STRAIN_MIN_DAYS:
        return {"strain": None}
 
    return {
        "strain": {
            "sent_count": len(sent),
            "span_days": span_days,
            "note": f"You've sent {len(sent)} applications over about {span_days} days without an interview or offer logged yet. That's genuinely draining, and it usually reflects the approach more than you - it can be worth pausing volume to concentrate on a few highest-fit roles, tightening how your experience is framed for them, or leaning on a referral, rather than sending more of the same.",
        }
    }
 
