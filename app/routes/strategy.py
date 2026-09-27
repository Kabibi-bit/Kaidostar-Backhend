import os
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.services.auth import require_auth_for_user
from app.services.rate_limit import rate_limit, rate_limit_by_tier
from sqlalchemy.orm import Session
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import Profile, RoadmapMilestone, Application, SavedListing, Listing, Outcome
from app.services.strategy import get_or_analyze_strategic_position
 
router = APIRouter(prefix="/strategy", tags=["strategy"])
_log = logging.getLogger("kaidostar")
 
 
@router.get("/{user_id}/position")
def get_strategic_position(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    rate_limit_by_tier(db, user_id, "strategy-position", per_action_limit=200)
    """The real, new synthesis this platform has never had - not
    another per-listing match score, but an honest read on where a
    person genuinely stands given everything they've actually done,
    and whether their real actions compound toward something or are
    genuinely disconnected from each other.
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
 
    profile_dict = {
        "northstar": profile.northstar,
        "final_idea": profile.final_idea or "",
        "skills": profile.skills or "",
        "priorities": profile.priorities or [],
    }
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    milestones_list = [
        {"target_stage": m.target_stage, "title": m.title, "status": m.status}
        for m in milestones
    ]
 
    applications_rows = (
        db.query(Application, Listing)
        .join(Listing, Application.listing_id == Listing.id)
        .filter(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
        .limit(20)
        .all()
    )
    outcomes_by_listing = {
        str(o.listing_id): o.status
        for o in db.query(Outcome).filter(Outcome.user_id == user_id).all()
    }
    applications_list = [
        {
            "listing_title": listing.title,
            "listing_org": listing.org,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "outcome_status": outcomes_by_listing.get(str(listing.id)),
        }
        for a, listing in applications_rows
    ]
 
    saved_rows = (
        db.query(SavedListing, Listing)
        .join(Listing, SavedListing.listing_id == Listing.id)
        .filter(SavedListing.user_id == user_id)
        .limit(15)
        .all()
    )
    saved_list = [{"title": l.title, "org": l.org} for _, l in saved_rows]
 
    from app.models.db_models import EngagementSuggestion
    engagement_rows = db.query(EngagementSuggestion).filter(EngagementSuggestion.user_id == user_id).all()
    engagement_list = [
        {"status": e.status, "poster_context": e.poster_context, "communication_log": e.communication_log or []}
        for e in engagement_rows
    ]
 
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
    try:
        return get_or_analyze_strategic_position(
            db, client, user_id, profile_dict, milestones_list, applications_list, saved_list,
            engagement_activity=engagement_list,
        )
    except ValueError as e:
        # Log server-side; return a generic message so an internal validation
        # detail never leaks to the client (matches the global handler's contract).
        _log.warning("Could not generate a strategic position just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate your strategic position just now. Please try again.")
 
