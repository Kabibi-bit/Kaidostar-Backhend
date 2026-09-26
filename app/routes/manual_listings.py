"""Manual listing entry -- the honest stand-in for a real college/
fellowship data pipeline. There is no free, reliable public API for
college admissions or fellowship listings comparable to Adzuna for
jobs (most are paywalled, institution-gated, or require data-sharing
agreements). Rather than fake a data source, this route lets you add
real listings by hand for now, so the matching/roadmap/chatbot
features can be tested against real admissions/fellowship data you
enter yourself. A real pipeline here would mean either paying for a
data license or building partnerships with individual programs.
"""
import hashlib
 
from fastapi import APIRouter, HTTPException, Depends
from app.services.auth import require_valid_token
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import date
 
from app.db import get_db
from app.models.db_models import Listing
 
router = APIRouter(prefix="/listings/manual", tags=["listings"])
 
 
class ManualListingIn(BaseModel):
    title: str = Field(max_length=300)
    org: str = Field(max_length=300)
    type: str = Field(max_length=50)  # "college" or "internship" typically, for this route
    location: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    tags: list[str] = Field(default=[], max_length=50)
    deadline: date | None = None
    # Bounded: any logged-in caller can POST here (require_valid_token), and apply_url
    # is stored raw - an unbounded value was an unbounded-storage vector. 2000 matches
    # the other URL fields (video_url).
    apply_url: str = Field(max_length=2000)
 
    @field_validator("tags")
    @classmethod
    def _tags_items_bounded(cls, v: list[str]) -> list[str]:
        # max_length=50 bounds the tag COUNT but not each tag's size; cap each so a
        # caller can't POST giant strings inside the list (unbounded-storage vector,
        # the same one apply_url was hardened against above). Tags are short labels.
        if v:
            for item in v:
                if item is not None and len(str(item)) > 200:
                    raise ValueError("each tag must be at most 200 characters")
        return v
 
 
@router.post("")
def add_manual_listing(payload: ManualListingIn, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    if not payload.title.strip() or not payload.org.strip() or not payload.apply_url.strip():
        raise HTTPException(status_code=400, detail="title, org, and apply_url cannot be empty")
    # apply_url anchors this instead of title+org - a real, different
    # listing at the same org with the same title (plausible in
    # practice) would otherwise collide against the real, enforced
    # UNIQUE(source, external_id) constraint and fail with a raw,
    # unhandled database error instead of ever being added.
    external_id = "manual_" + hashlib.sha256(payload.apply_url.strip().encode()).hexdigest()[:16]
    listing = Listing(
        source="manual",
        external_id=external_id,
        title=payload.title,
        org=payload.org,
        type=payload.type,
        location=payload.location,
        description=payload.description,
        tags=payload.tags,
        deadline=payload.deadline,
        apply_url=payload.apply_url,
    )
    db.add(listing)
    try:
        db.commit()
    except IntegrityError:
        # Re-adding the same posting (same apply_url -> same source+external_id) hits
        # the UNIQUE(source, external_id) constraint. That's a duplicate add (a
        # re-submit or double-click), not an error: roll back and return the existing
        # listing idempotently instead of a raw 500.
        db.rollback()
        existing = (
            db.query(Listing)
            .filter(Listing.source == "manual", Listing.external_id == external_id)
            .first()
        )
        if existing:
            return {"status": "already_exists", "listing_id": str(existing.id)}
        raise
    db.refresh(listing)
    return {"status": "added", "listing_id": str(listing.id)}
 
