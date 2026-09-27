"""System-wide status checks, not tied to a specific user - a
separate file since these don't fit any existing user-scoped router.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.services.auth import require_valid_token
 
router = APIRouter(prefix="/system", tags=["system"])
 
 
@router.get("/embeddings-status")
def embeddings_status(_auth: dict = Depends(require_valid_token)):
    """Whether real semantic matching (see app/services/embeddings.py)
    is actually working right now - previously invisible without
    reading raw server logs. Makes a single real, throwaway call to
    Voyage if a key is configured, so this distinguishes "no key set"
    from "key set but the call is failing" - those need different
    fixes (add a key vs. check the key's validity or Voyage's status)
    and looked identical from the outside before this endpoint
    existed.
    """
    from app.services.embeddings import check_embeddings_status
 
    return check_embeddings_status()
 
 
@router.get("/auto-submit-status")
def auto_submit_status(_auth: dict = Depends(require_valid_token)):
    """Whether Pro auto-submit can actually drive a browser in this runtime.
    Lets the team verify a deploy (does it have Chromium?) without submitting a
    real application. {available: false} means auto-submit safely falls back to
    the manual hand-off until `playwright install --with-deps chromium` is run.
    """
    from app.services.application_submit import check_browser_available
 
    return check_browser_available()
 
 
@router.post("/backfill-embeddings")
def backfill_embeddings(db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    """Any listing ingested before VOYAGE_API_KEY was configured has
    no embedding, permanently - the normal daily scan skips any
    listing it's already seen by source+external_id, so setting up
    the key today does nothing on its own for listings that predate
    it. This is the actual path back to real semantic matching for
    them. Processes up to 100 per call and is safe to call repeatedly
    - each call picks up the next real batch of still-missing rows,
    rather than one very large request against a real rate-limited
    API.
    """
    from app.services.scheduler import backfill_missing_embeddings
 
    return backfill_missing_embeddings(db)
 
