import os
from fastapi import APIRouter, Depends, HTTPException, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit_by_tier
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import SavedListing, Listing
from app.services.auto_apply import create_application_for_match
 
router = APIRouter(prefix="/saved", tags=["saved"])
 
 
class SaveIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("")
def save_listing(payload: SaveIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Stars a listing - this is what backs the frontend's star icon
    and Saved panel. Starring ALSO automatically drafts a tailored
    application for that match (via create_application_for_match),
    landing in the Workshop page for review/approval/send. If the
    draft fails for any reason (no profile yet, a deal-breaker
    conflict, an AI call failure), the star itself still succeeds -
    drafting failures never block the save.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    verify_token_belongs_to_user(payload.user_id, authorization)
    try:
        uuid_module.UUID(payload.listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    existing = (
        db.query(SavedListing)
        .filter(SavedListing.user_id == payload.user_id, SavedListing.listing_id == payload.listing_id)
        .first()
    )
    if existing:
        return {"status": "already saved"}
 
    saved = SavedListing(user_id=payload.user_id, listing_id=payload.listing_id)
    db.add(saved)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent save of the same (user, listing): the winner
        # already saved (and will draft). Mirror the "already saved" early return
        # rather than 500 or double-drafting.
        db.rollback()
        return {"status": "already saved"}
 
    draft_result = None
    try:
        rate_limit_by_tier(db, payload.user_id, "application-draft", per_action_limit=300)
        draft_result = create_application_for_match(db, client, payload.user_id, payload.listing_id)
        if draft_result.get("error"):
            draft_result = None  # profile missing, dealbreaker conflict, etc. - just skip silently
    except Exception:
        draft_result = None  # an AI/network failure should never break the save itself
 
    return {
        "status": "saved",
        "application_drafted": draft_result is not None and not draft_result.get("already_existed"),
        "application_id": draft_result.get("application_id") if draft_result else None,
    }
 
 
@router.delete("/{user_id}/{listing_id}")
def unsave_listing(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not currently saved")
    row = (
        db.query(SavedListing)
        .filter(SavedListing.user_id == user_id, SavedListing.listing_id == listing_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not currently saved")
    db.delete(row)
    db.commit()
    return {"status": "unsaved"}
 
 
@router.get("/{user_id}")
def get_saved(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    rows = (
        db.query(SavedListing, Listing)
        .join(Listing, SavedListing.listing_id == Listing.id)
        .filter(SavedListing.user_id == user_id)
        .all()
    )
    return [
        {"listing_id": str(l.id), "title": l.title, "org": l.org, "type": l.type, "deadline": l.deadline.isoformat() if l.deadline else None}
        for _, l in rows
    ]
 
