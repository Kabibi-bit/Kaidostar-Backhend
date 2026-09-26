from fastapi import APIRouter, Depends, HTTPException, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
 
from app.db import get_db
from app.models.db_models import DismissedListing
 
router = APIRouter(prefix="/dismissed", tags=["dismissed"])
 
 
class DismissIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("")
def dismiss_listing(payload: DismissIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Marks a listing 'not interested, never show this again' - the
    real, concrete answer to a documented Jobright weakness (relisting
    jobs a person already rejected). A listing dismissed here is
    excluded from match-cycle candidates entirely, before any real
    scoring work happens on it - see get_match_candidates below.
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
        db.query(DismissedListing)
        .filter(DismissedListing.user_id == payload.user_id, DismissedListing.listing_id == payload.listing_id)
        .first()
    )
    if existing:
        return {"status": "already dismissed"}
 
    dismissed = DismissedListing(user_id=payload.user_id, listing_id=payload.listing_id)
    db.add(dismissed)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent dismiss of the same (user, listing);
        # mirror the "already dismissed" early return rather than 500.
        db.rollback()
        return {"status": "already dismissed"}
    return {"status": "dismissed"}
 
 
@router.delete("/{user_id}/{listing_id}")
def undismiss_listing(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Lets a person change their mind - a real listing they dismissed
    can come back into their match pool if they later reconsider.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not currently dismissed")
    row = (
        db.query(DismissedListing)
        .filter(DismissedListing.user_id == user_id, DismissedListing.listing_id == listing_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not currently dismissed")
    db.delete(row)
    db.commit()
    return {"status": "undismissed"}
 
 
@router.get("/{user_id}")
def get_dismissed(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    rows = db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()
    return [str(r.listing_id) for r in rows]
 
