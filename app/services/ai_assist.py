"""Generic AI writing-assistant endpoint.
 
One route powers every AI-backed tool in the Workshop and Interview Prep
pages. The client names a `task` and passes its inputs; the server grounds
the prompt in the caller's real profile and returns plain text. Auth,
rate-limiting, and the missing-key guard mirror the other AI routes.
"""
import logging
import uuid as uuid_module
 
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Profile
from app.services.auth import verify_token_belongs_to_user
from app.services.ai_client import get_client
from app.services.ai_assist import run_assist, ALLOWED_TASKS
from app.services.rate_limit import rate_limit_by_tier
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/ai", tags=["ai"])
 
 
class AssistIn(BaseModel):
    user_id: str
    task: str = Field(max_length=40)
    inputs: dict = Field(default_factory=dict)
 
 
def _bound_inputs(inputs: dict) -> dict:
    if not isinstance(inputs, dict):
        raise HTTPException(status_code=400, detail="inputs must be an object")
    if len(inputs) > 30:
        raise HTTPException(status_code=400, detail="too many inputs")
    total = 0
    for v in inputs.values():
        try:
            total += len(str(v))
        except Exception:
            raise HTTPException(status_code=400, detail="inputs are not serializable")
    if total > 24000:
        raise HTTPException(status_code=400, detail="inputs are too large")
    return inputs
 
 
@router.post("/assist")
def assist_route(payload: AssistIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    verify_token_belongs_to_user(payload.user_id, authorization)
    if payload.task not in ALLOWED_TASKS:
        raise HTTPException(status_code=400, detail="unknown task")
    _bound_inputs(payload.inputs)
    rate_limit_by_tier(db, payload.user_id, "ai-assist", per_action_limit=400)
 
    profile_row = (
        db.query(Profile)
        .filter(Profile.user_id == payload.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    profile = {
        "northstar": profile_row.northstar if profile_row else "",
        "skills": (profile_row.skills or "") if profile_row else "",
    }
    try:
        result = run_assist(client, payload.task, payload.inputs, profile)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.warning("AI assist failed for task %s - %s", payload.task, e)
        raise HTTPException(status_code=502, detail="Could not generate this just now. Please try again.")
    return {"result": result, "task": payload.task}
 
