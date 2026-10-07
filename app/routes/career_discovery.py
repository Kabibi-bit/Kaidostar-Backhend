import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit, rate_limit_by_tier
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import CareerDiscoveryResult, Listing
from app.services.career_discovery import score_career_directions, explain_direction_deep, CAREER_DIRECTIONS
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/career-discovery", tags=["career-discovery"])
 
 
class DiscoveryAnswersIn(BaseModel):
    user_id: str
    people: int = Field(default=0, ge=0, le=3)
    data: int = Field(default=0, ge=0, le=3)
    creative: int = Field(default=0, ge=0, le=3)
    structure: int = Field(default=0, ge=0, le=3)
    free_text: str = Field(default="", max_length=4000)
 
 
@router.post("")
def submit_discovery(payload: DiscoveryAnswersIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Scores the assessment against real stored listings (not just
    static descriptions), and saves the result so it persists.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    verify_token_belongs_to_user(payload.user_id, authorization)
 
    answers = {"people": payload.people, "data": payload.data, "creative": payload.creative, "structure": payload.structure, "free_text": payload.free_text}
    from app.services.feed_common import not_feed
    listings = db.query(Listing).filter(not_feed(Listing)).all()
    all_tags = [l.tags or [] for l in listings]
    directions = score_career_directions(answers, all_tags)
 
    existing = db.query(CareerDiscoveryResult).filter(CareerDiscoveryResult.user_id == payload.user_id).first()
    if existing:
        existing.answers = answers
        existing.directions = directions
        db.commit()
    else:
        from sqlalchemy.exc import IntegrityError
        db.add(CareerDiscoveryResult(user_id=payload.user_id, answers=answers, directions=directions))
        try:
            db.commit()
        except IntegrityError:
            # Concurrent first-time submit for this user won the row (user_id is the
            # PRIMARY KEY of career_discovery_results), so this bare insert would
            # otherwise 500. This is the same check-then-insert race the (user,listing)
            # tables already guard; roll back and return this run's freshly computed
            # result (the winner persisted this same user's equally-valid answers).
            db.rollback()
 
    return {"answers": answers, "directions": directions}
 
 
@router.get("/{user_id}")
def get_discovery(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"answers": None, "directions": None, "note": "No discovery assessment taken yet."}
    result = db.query(CareerDiscoveryResult).filter(CareerDiscoveryResult.user_id == user_id).first()
    if not result:
        return {"answers": None, "directions": None, "note": "No discovery assessment taken yet."}
    return {"answers": result.answers, "directions": result.directions}
 
 
class ExplainDirectionIn(BaseModel):
    direction_id: str
 
 
@router.post("/{user_id}/explain")
def explain_direction(user_id: str, payload: ExplainDirectionIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    rate_limit_by_tier(db, user_id, "career-explain", per_action_limit=200)
    """On-demand, real Claude explanation for one direction - only
    called when someone actually wants more than the instant score,
    same cost-conscious pattern as the deep match explanation.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No discovery assessment on file - submit one first")
    result = db.query(CareerDiscoveryResult).filter(CareerDiscoveryResult.user_id == user_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="No discovery assessment on file - submit one first")
 
    direction = next((d for d in CAREER_DIRECTIONS if d["id"] == payload.direction_id), None)
    if not direction:
        raise HTTPException(status_code=404, detail="Unknown direction id")
 
    try:
        explanation = explain_direction_deep(client, direction, result.answers)
    except Exception as e:
        _log.warning("Could not generate this explanation just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate this explanation just now. Please try again.")
    return {"direction_id": payload.direction_id, "explanation": explanation}
 
