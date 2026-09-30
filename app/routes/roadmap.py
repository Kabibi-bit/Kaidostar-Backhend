import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit, rate_limit_by_tier
from app.services.tiers import require_feature
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import Profile, Listing, RoadmapMilestone, RoadmapSummary, SocialPost
from app.services.roadmap import generate_roadmap, explain_listing_against_roadmap
from app.services.pathways import generate_pathways
from app.services.matching import rank_listings, _terms_match, tokenize
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/roadmap", tags=["roadmap"])
 
 
def _profile_to_dict(p: Profile) -> dict:
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "timeframe": p.timeframe or "",
        "stage": p.stage or "",
        "priorities": p.priorities or [],
        "dealbreakers": p.dealbreakers or "",
        "target_types": p.target_types or [],
    }
 
 
def _compute_skill_gaps(db: Session, profile_dict: dict) -> list[str]:
    """Finds tags that show up often in this user's top real matches
    but aren't in their stated skills or goal - grounding the roadmap
    in real data instead of generic advice.
    """
    listings = db.query(Listing).all()
    if not listings:
        return []
    listing_dicts = [
        {
            "id": str(l.id), "type": l.type, "title": l.title, "org": l.org, "tags": l.tags or [],
            "location": l.location, "deadline": l.deadline.isoformat() if l.deadline else None,
            "description": l.description or "",
        }
        for l in listings
    ]
    ranked = rank_listings(listing_dicts, profile_dict, top_n=8)
 
    skill_tokens = tokenize(profile_dict.get("skills", "") or "")
    goal_tokens = tokenize((profile_dict["northstar"] + " " + profile_dict.get("final_idea", "")) or "")
 
    freq = {}
    for listing in ranked:
        for tag in listing.get("tags", []):
            known = any(_terms_match(t, tag) for t in skill_tokens) or any(_terms_match(t, tag) for t in goal_tokens)
            if not known:
                freq[tag] = freq.get(tag, 0) + 1
    return [tag for tag, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:4]]
 
 
def _ranked_listings(db: Session, profile_dict: dict, top_n: int = 10) -> list:
    """Real listings, scored and ranked for this user - the ground truth the
    pathways atlas is built from (supporting matches, top match, gap tags)."""
    listings = db.query(Listing).all()
    if not listings:
        return []
    listing_dicts = [
        {
            "id": str(l.id), "type": l.type, "title": l.title, "org": l.org, "tags": l.tags or [],
            "location": l.location, "deadline": l.deadline.isoformat() if l.deadline else None,
            "description": l.description or "",
        }
        for l in listings
    ]
    return rank_listings(listing_dicts, profile_dict, top_n=top_n)
 
 
def _gaps_from_ranked(ranked: list, profile_dict: dict) -> list[str]:
    skill_tokens = tokenize(profile_dict.get("skills", "") or "")
    goal_tokens = tokenize((profile_dict["northstar"] + " " + profile_dict.get("final_idea", "")) or "")
    freq = {}
    for listing in ranked:
        for tag in listing.get("tags", []):
            known = any(_terms_match(t, tag) for t in skill_tokens) or any(_terms_match(t, tag) for t in goal_tokens)
            if not known:
                freq[tag] = freq.get(tag, 0) + 1
    return [tag for tag, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:4]]
 
 
@router.get("/{user_id}/pathways")
def get_pathways(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The Pathways Atlas: a branching graph of dozens of real routes from
    where the person is now to their goal, grounded in their real ranked
    listings, plus the engine's authoritative recommendation. The browser
    renders this and re-scores live as the person adjusts constraints; this
    is the server-side source of truth for the graph and the initial pick.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    rate_limit_by_tier(db, user_id, "pathways", per_action_limit=400)
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    profile_dict = _profile_to_dict(profile)
    ranked = _ranked_listings(db, profile_dict, top_n=10)
    skill_gaps = _gaps_from_ranked(ranked, profile_dict)
    return generate_pathways(profile_dict, ranked, skill_gaps)
 
 
@router.post("/{user_id}")
def create_roadmap(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    rate_limit_by_tier(db, user_id, "roadmap-generate", per_action_limit=200)
    """Generates a fresh, detailed roadmap: an overall strategy summary
    plus 4-6 milestones, each with success criteria, a timeframe, a
    first action, a concrete resource, and the specific risk of
    stalling on that step. Replaces any previous roadmap.
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
 
    profile_dict = _profile_to_dict(profile)
    skill_gaps = _compute_skill_gaps(db, profile_dict)
    try:
        result = generate_roadmap(client, profile_dict, skill_gaps=skill_gaps)
    except Exception as e:
        _log.warning("Could not generate a roadmap just now - try again. - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate a roadmap just now - try again.. Please try again.")
    milestones = result["milestones"]
    summary = result["summary"]
 
    db.query(RoadmapMilestone).filter(RoadmapMilestone.user_id == user_id).delete()
    for m in milestones:
        db.add(RoadmapMilestone(
            user_id=user_id,
            title=m["title"],
            description=m["description"],
            success_criteria=m.get("success_criteria", ""),
            estimated_timeframe=m.get("estimated_timeframe", ""),
            first_action=m.get("first_action", ""),
            resource=m.get("resource", ""),
            risk=m.get("risk", ""),
            if_it_works=m.get("if_it_works", ""),
            if_it_stalls=m.get("if_it_stalls", ""),
            target_stage=m["stage"],
        ))
 
    existing_summary = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == user_id).first()
    if existing_summary:
        existing_summary.summary = summary
        db.commit()
    else:
        from sqlalchemy.exc import IntegrityError
        db.add(RoadmapSummary(user_id=user_id, summary=summary))
        try:
            db.commit()
        except IntegrityError:
            # Concurrent first-time roadmap generation for this user won the
            # RoadmapSummary row (user_id is its PRIMARY KEY). The failed commit
            # rolled back this run's milestones + summary together, and the winner
            # persisted its own complete roadmap. Return this run's freshly generated
            # result rather than 500-ing on the double-click; the winner's copy is
            # what persists and a refresh (GET /roadmap) shows a complete, valid one.
            db.rollback()
    return {"status": "created", "summary": summary, "milestones": milestones, "skill_gaps_used": skill_gaps}
 
 
@router.get("/{user_id}")
def get_roadmap(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"milestones": [], "summary": None, "note": "No roadmap yet - POST to this URL to generate one."}
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    if not milestones:
        return {"milestones": [], "summary": None, "note": "No roadmap yet - POST to this URL to generate one."}
 
    summary_row = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == user_id).first()
    return {
        "summary": summary_row.summary if summary_row else None,
        "milestones": [
            {
                "id": str(m.id),
                "title": m.title,
                "description": m.description,
                "success_criteria": m.success_criteria,
                "estimated_timeframe": m.estimated_timeframe,
                "first_action": m.first_action,
                "resource": m.resource,
                "risk": m.risk,
                "if_it_works": m.if_it_works,
                "if_it_stalls": m.if_it_stalls,
                "stage": m.target_stage,
                "status": m.status,
            }
            for m in milestones
        ]
    }
 
 
class MilestoneStatusIn(BaseModel):
    status: str
    reflection: str | None = Field(default=None, max_length=4000)
 
 
VALID_MILESTONE_STATUSES = {"planned", "in_progress", "done"}
 
 
@router.post("/milestone/{milestone_id}/status")
def update_milestone_status(milestone_id: str, payload: MilestoneStatusIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Marks real progress on one milestone - this is what makes the
    roadmap a living plan instead of a one-time AI output.
 
    When status genuinely transitions to "done" and the person
    provides a real reflection in the same request, this also creates
    a genuine, linked Waypoint journal entry - tagged to this exact
    milestone's real stage and title, not a generic "write something"
    prompt. This is what makes Waypoint a natural byproduct of real
    progress instead of a separate page someone has to remember to
    visit: the reflection happens right when the real event does,
    grounded in the actual milestone they just completed. Entirely
    optional - a bare status update with no reflection behaves
    exactly as it always has.
    """
    if payload.status not in VALID_MILESTONE_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_MILESTONE_STATUSES}")
    import uuid as uuid_module
    try:
        uuid_module.UUID(milestone_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Milestone not found")
    milestone = db.query(RoadmapMilestone).filter(RoadmapMilestone.id == milestone_id).first()
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")
    # Only a milestone_id in the path, so verify the token against the
    # milestone's real owner before mutating it.
    verify_token_belongs_to_user(str(milestone.user_id), authorization)
    milestone.status = payload.status
 
    journal_entry_id = None
    if payload.status == "done" and payload.reflection and payload.reflection.strip():
        post = SocialPost(
            user_id=milestone.user_id, body=payload.reflection.strip(),
            tag_value=str(milestone.target_stage), tag_label=milestone.title,
        )
        db.add(post)
        db.flush()  # so post.id is populated before commit, to return it below
        journal_entry_id = str(post.id)
 
    db.commit()
    return {"status": "updated", "milestone_status": payload.status, "journal_entry_id": journal_entry_id}
 
 
@router.get("/{user_id}/explain/{listing_id}")
def explain_listing(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    require_feature(db, user_id, "deep_match_explanations")
    rate_limit_by_tier(db, user_id, "roadmap-explain", per_action_limit=200)
    """Returns Claude's explanation of how one specific listing fits
    the user's stored roadmap.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    try:
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    if not milestones:
        raise HTTPException(status_code=404, detail="No roadmap yet - generate one first with POST /roadmap/{user_id}")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    roadmap_dicts = [
        {"stage": m.target_stage, "title": m.title, "description": m.description, "success_criteria": m.success_criteria}
        for m in milestones
    ]
    listing_dict = {"title": listing.title, "org": listing.org, "type": listing.type, "tags": listing.tags or []}
 
    try:
        explanation = explain_listing_against_roadmap(client, listing_dict, roadmap_dicts, _profile_to_dict(profile))
    except Exception as e:
        _log.warning("Could not compare this listing to your roadmap just now - try again. - %s", e)
        raise HTTPException(status_code=502, detail="Could not compare this listing to your roadmap just now - try again.. Please try again.")
    return {"listing": listing.title, "explanation": explanation}
 
