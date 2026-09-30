import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import verify_token_belongs_to_user, require_valid_token
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import Profile, RoadmapSummary
from app.services.market_research import research_company, generate_interview_prep, mock_interview_turn
from app.services.rate_limit import rate_limit_by_tier
from app.services.tiers import require_feature
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/market", tags=["market"])
 
 
class CompanyResearchIn(BaseModel):
    company_name: str = Field(max_length=200)
    role_title: str = Field(max_length=200)
 
 
@router.post("/research-company")
def research_company_route(payload: CompanyResearchIn, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    # Meter this paid AI + web-search call (was unmetered; require_valid_token only
    # gated it to logged-in callers - so any one token could run up the web-search
    # bill). Fails open; keyed to the caller's own token subject.
    rate_limit_by_tier(db, _auth["sub"], "company-research", per_action_limit=200)
    if not payload.company_name.strip():
        raise HTTPException(status_code=400, detail="company_name is required")
    if not payload.role_title.strip():
        raise HTTPException(status_code=400, detail="role_title is required")
    try:
        result = research_company(client, payload.company_name, payload.role_title)
    except Exception as e:
        _log.warning("Could not research this company just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not research this company just now. Please try again.")
    return result
 
 
class InterviewPrepIn(BaseModel):
    user_id: str
    company_name: str = Field(max_length=200)
    role_title: str = Field(max_length=200)
    company_research: str | None = Field(default=None, max_length=8000)
 
 
@router.post("/interview-prep")
def interview_prep_route(payload: InterviewPrepIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        # A malformed user_id would otherwise reach the DB query
        # below and raise a raw, unhandled database exception -
        # mirrors the identical, established fix already applied to
        # every path-parameter ID in athletics.py this session. The
        # risk is the same whether the ID comes from a path or, as
        # here, a request-body field.
        raise HTTPException(status_code=404, detail="No current profile for this user")
    # Verify the caller's token actually owns this user_id (IDOR defense) before
    # doing any work - the same check every other user-scoped endpoint performs.
    verify_token_belongs_to_user(payload.user_id, authorization)
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == payload.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    require_feature(db, payload.user_id, "interview_prep")  # Interview Prep is Pro+
    rate_limit_by_tier(db, payload.user_id, "interview-prep", per_action_limit=300)
 
    roadmap_summary_row = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == payload.user_id).first()
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
 
    try:
        prep = generate_interview_prep(
            client, payload.company_name, payload.role_title, payload.company_research,
            profile_dict, roadmap_summary_row.summary if roadmap_summary_row else None,
        )
    except Exception as e:
        _log.warning("Could not generate interview prep just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate interview prep just now. Please try again.")
    return prep
 
 
class MockInterviewIn(BaseModel):
    user_id: str
    role_title: str = Field(max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    question: str | None = Field(default=None, max_length=2000)
    answer: str | None = Field(default=None, max_length=8000)
    turn_index: int = Field(default=0, ge=0, le=100)
 
 
@router.post("/mock-interview")
def mock_interview_route(payload: MockInterviewIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """One turn of the live AI mock interviewer. Backs the Interview Prep
    page's practice mode: blank answer -> an opening question; a real answer
    -> honest, specific feedback plus the natural follow-up question."""
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    verify_token_belongs_to_user(payload.user_id, authorization)
    if not (payload.role_title or "").strip():
        raise HTTPException(status_code=400, detail="role_title is required")
    require_feature(db, payload.user_id, "interview_prep")  # Interview Prep is Pro+
    rate_limit_by_tier(db, payload.user_id, "mock-interview", per_action_limit=400)
    try:
        result = mock_interview_turn(
            client, payload.role_title, payload.company_name or "",
            payload.question or "", payload.answer or "", payload.turn_index,
        )
    except Exception as e:
        _log.warning("Could not run the mock interview turn just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not reach the interviewer just now. Please try again.")
    return result
 
