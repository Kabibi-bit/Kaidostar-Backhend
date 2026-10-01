"""Mission Control endpoint.
 
GET /mission/{user_id} returns the server-computed Mission Control snapshot -
every KPI, funnel stage, conversion, search metric and growth number the
dashboard shows - from the caller's real data (applications, logged outcomes,
the real match ranker, roadmap, saved count, interview-prep items). This is
what makes the dashboard genuinely backend-backed: the numbers are computed and
enforced server-side and are identical across devices, with the browser's
computation kept only as an offline fallback.
 
Auth-scoped to the caller's own user_id (require_auth_for_user). No AI call -
pure aggregation - so it's cheap and safe to hit on every dashboard load.
"""
import logging
import uuid as uuid_module
 
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.services.auth import require_auth_for_user
from app.services.mission import compute_mission
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/mission", tags=["mission"])
 
 
@router.get("/{user_id}")
def get_mission(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    from app.models.db_models import (
        Profile, Application, Outcome, Listing, DismissedListing,
        SavedListing, RoadmapMilestone, WorkshopItem,
    )
    from app.routes.listings import _listing_to_dict, _profile_to_dict
    from app.services.matching import rank_listings
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        return {"has_profile": False}
 
    # Applications, joined to their listing for org/title.
    apps = db.query(Application).filter(Application.user_id == user_id).all()
    listings = db.query(Listing).all()
    listing_by_id = {str(l.id): l for l in listings}
    app_dicts = []
    for a in apps:
        l = listing_by_id.get(str(a.listing_id))
        app_dicts.append({
            "status": a.status,
            "listing_id": str(a.listing_id),
            "org": (l.org if l else None),
            "title": (l.title if l else None),
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
            "has_factors": a.factors_snapshot is not None,
            "has_draft": bool(a.draft_content),
        })
 
    # Latest outcome status per listing (same dedup the outcomes/stats route uses).
    orows = (
        db.query(Outcome)
        .filter(Outcome.user_id == user_id)
        .order_by(Outcome.updated_at.asc())
        .all()
    )
    outcomes = {}
    for r in orows:
        outcomes[str(r.listing_id)] = r.status
 
    # Real ranked matches (minus dismissed), via the same ranker the app uses.
    dismissed = {str(r.listing_id) for r in db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()}
    try:
        ranked = rank_listings(
            [_listing_to_dict(l) for l in listings],
            _profile_to_dict(profile),
            top_n=40,
            dismissed_ids=dismissed,
        )
    except Exception as e:
        _log.warning("mission: ranking failed, continuing with no matches - %s", e)
        ranked = []
    matches = [{
        "title": m.get("title"), "org": m.get("org"), "score_pct": m.get("score_pct"),
        "type": m.get("type"), "tags": m.get("tags") or [], "deadline": m.get("deadline"),
        "ghost_risk": m.get("ghost_risk"), "signal_strength": m.get("signal_strength"),
    } for m in ranked]
 
    # Roadmap progress.
    roadmap_rows = db.query(RoadmapMilestone).filter(RoadmapMilestone.user_id == user_id).all()
    done = sum(1 for r in roadmap_rows if r.status == "done")
    total = len(roadmap_rows)
 
    saved_count = db.query(SavedListing).filter(SavedListing.user_id == user_id).count()
 
    wrows = (
        db.query(WorkshopItem)
        .filter(WorkshopItem.user_id == user_id, WorkshopItem.kind.in_(["star_story", "interview_answer", "interview_ask"]))
        .all()
    )
    workshop = {"star_story": 0, "interview_answer": 0, "interview_ask": 0}
    for w in wrows:
        if w.kind in workshop:
            workshop[w.kind] += 1
 
    data = {
        "profile": {"skills": profile.skills or "", "northstar": profile.northstar or ""},
        "applications": app_dicts,
        "outcomes": outcomes,
        "matches": matches,
        "roadmap": {"done": done, "total": total},
        "saved_count": saved_count,
        "workshop": workshop,
    }
    snap = compute_mission(data)
    snap["matches"] = matches  # the frontend renders these as the live top-matches list
    return snap
 
