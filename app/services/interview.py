"""Interview Studio routes - the AI behind the Interview Prep page.
 
  POST /interview/plan     the questions a realistic interviewer would ask (role, JD, resume)
  POST /interview/turn     judge one answer harshly + decide the follow-up (the live Hot Seat)
  POST /interview/verdict  the hiring-committee verdict over a whole session
  POST /interview/tool     the studio's other AI tools (predict, forge, grill, x-ray, ...)
 
Every route: the caller's token must own user_id, Interview Prep must be in
their plan (it's Pro+ - enforced here, not just in the UI), inputs are bounded,
and each call is metered per tier. AI output is normalized and quote-checked in
app/services/interview_coach.py before it ever reaches the browser.
"""
import logging
import uuid as uuid_module
 
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Profile
from app.services.ai_client import get_client
from app.services.auth import verify_token_belongs_to_user
from app.services.interview_coach import TOOLS, Withheld, run_plan, run_turn, run_verdict, run_tool
from app.services.rate_limit import rate_limit_by_tier
from app.services.tiers import require_feature
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/interview", tags=["interview"])
 
_AI_DOWN = "AI service is not configured. Please try again later."
_AI_FAILED = "The interviewer couldn't respond just now. Please try again."
 
# What each tool can't run without - checked BEFORE metering, so a
# half-filled form never burns a daily allowance.
_REQUIRED = {
    "predict": ("jd", "Paste the job description first."),
    "forge": ("notes", "Jot down what happened first - a few rough lines is enough."),
    "grill": ("resume", "Add your resume (Workshop > Resume) first, so the questions come from it."),
    "position": ("findings", "Run the company research first."),
    "ask": ("role", "Name the role first."),
    "xray": ("sentences", "Type or paste your answer first."),
    "gauntlet": ("original", "Give the answer you want to stress-test first."),
    "tmays": ("background", "Add your background first (profile or resume)."),
    "negotiate": ("offer", "Enter the offer you're negotiating first."),
    "brief": ("role", "Name the role first."),
    "debrief": ("notes", "Jot down how the interview went first."),
    "drills": ("summary", "Do at least one judged practice answer first."),
}
 
 
class PlanIn(BaseModel):
    user_id: str
    role: str = Field(max_length=200)
    company: str = Field(default="", max_length=200)
    jd: str = Field(default="", max_length=8000)
    resume: str = Field(default="", max_length=6000)
    stories: str = Field(default="", max_length=3000)
    persona: str = Field(default="hiring_manager", max_length=40)
    difficulty: str = Field(default="brutal", max_length=20)
    focus: str = Field(default="mixed", max_length=20)
    count: int = Field(default=5, ge=1, le=10)
    skip_opener: bool = False
 
 
class TurnIn(BaseModel):
    user_id: str
    role: str = Field(max_length=200)
    company: str = Field(default="", max_length=200)
    persona: str = Field(default="hiring_manager", max_length=40)
    difficulty: str = Field(default="brutal", max_length=20)
    qtype: str = Field(default="behavioral", max_length=20)
    question: str = Field(max_length=1000)
    answer: str = Field(max_length=12000)
    history: str = Field(default="", max_length=6000)
    earlier: list = Field(default_factory=list)   # their earlier answers this session (quotable as theirs)
    meta: dict = Field(default_factory=dict)
    allow_follow_up: bool = True
 
 
class VerdictIn(BaseModel):
    user_id: str
    role: str = Field(max_length=200)
    company: str = Field(default="", max_length=200)
    persona: str = Field(default="hiring_manager", max_length=40)
    difficulty: str = Field(default="brutal", max_length=20)
    turns: list = Field(default_factory=list)
 
 
class ToolIn(BaseModel):
    user_id: str
    tool: str = Field(max_length=30)
    inputs: dict = Field(default_factory=dict)
 
 
def _check_uuid(user_id: str):
    try:
        uuid_module.UUID(str(user_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
 
def _size(v) -> int:
    try:
        return len(str(v))
    except Exception:
        raise HTTPException(status_code=400, detail="inputs are not serializable")
 
 
def _bound_earlier(earlier: list) -> list:
    if not isinstance(earlier, list) or len(earlier) > 8 or not all(isinstance(x, str) for x in earlier):
        raise HTTPException(status_code=400, detail="earlier must be a short list of answers")
    if sum(len(x) for x in earlier) > 20000:
        raise HTTPException(status_code=400, detail="earlier answers are too long")
    return earlier
 
 
def _bound_meta(meta: dict) -> dict:
    if not isinstance(meta, dict):
        raise HTTPException(status_code=400, detail="meta must be an object")
    if len(meta) > 24 or sum(_size(v) for v in meta.values()) > 2000:
        raise HTTPException(status_code=400, detail="meta is too large")
    return meta
 
 
def _bound_turns(turns: list) -> list:
    if not isinstance(turns, list) or not turns:
        raise HTTPException(status_code=400, detail="Answer at least one question first.")
    # Up to 10 planned questions plus as many follow-ups (the browser caps
    # follow-ups at the plan length), skipped ones included.
    if len(turns) > 24:
        raise HTTPException(status_code=400, detail="too many turns")
    total = 0
    for t in turns:
        if not isinstance(t, dict) or len(t) > 14:
            raise HTTPException(status_code=400, detail="each turn must be a small object")
        total += sum(_size(v) for v in t.values())
    if total > 80000:
        raise HTTPException(status_code=400, detail="this session is too large to judge")
    return turns
 
 
def _bound_inputs(inputs: dict) -> dict:
    if not isinstance(inputs, dict):
        raise HTTPException(status_code=400, detail="inputs must be an object")
    if len(inputs) > 30:
        raise HTTPException(status_code=400, detail="too many inputs")
    if sum(_size(v) for v in inputs.values()) > 32000:
        raise HTTPException(status_code=400, detail="inputs are too large")
    return inputs
 
 
def _profile(db, user_id):
    try:
        row = (
            db.query(Profile)
            .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
            .first()
        )
    except Exception:
        row = None
    return {"northstar": (row.northstar or "") if row else "", "skills": (row.skills or "") if row else ""}
 
 
@router.post("/plan")
def plan_route(payload: PlanIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    _check_uuid(payload.user_id)
    verify_token_belongs_to_user(payload.user_id, authorization)
    require_feature(db, payload.user_id, "interview_prep")
    if not payload.role.strip():
        raise HTTPException(status_code=400, detail="Name the role you're interviewing for first.")
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail=_AI_DOWN)
    rate_limit_by_tier(db, payload.user_id, "interview-plan", per_action_limit=120)
    try:
        return run_plan(client, payload.model_dump(), _profile(db, payload.user_id))
    except Exception as e:
        _log.warning("interview plan failed - %s", e)
        raise HTTPException(status_code=502, detail=_AI_FAILED)
 
 
@router.post("/turn")
def turn_route(payload: TurnIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    _check_uuid(payload.user_id)
    verify_token_belongs_to_user(payload.user_id, authorization)
    require_feature(db, payload.user_id, "interview_prep")
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    if len(payload.answer.strip()) < 2:
        raise HTTPException(status_code=400, detail="Give an answer first - even a short one.")
    _bound_meta(payload.meta)
    _bound_earlier(payload.earlier)
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail=_AI_DOWN)
    rate_limit_by_tier(db, payload.user_id, "interview-turn", per_action_limit=600)
    try:
        return run_turn(client, payload.model_dump(), _profile(db, payload.user_id))
    except Exception as e:
        _log.warning("interview turn failed - %s", e)
        raise HTTPException(status_code=502, detail=_AI_FAILED)
 
 
@router.post("/verdict")
def verdict_route(payload: VerdictIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    _check_uuid(payload.user_id)
    verify_token_belongs_to_user(payload.user_id, authorization)
    require_feature(db, payload.user_id, "interview_prep")
    _bound_turns(payload.turns)
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail=_AI_DOWN)
    rate_limit_by_tier(db, payload.user_id, "interview-verdict", per_action_limit=120)
    try:
        return run_verdict(client, payload.model_dump(), _profile(db, payload.user_id))
    except Exception as e:
        _log.warning("interview verdict failed - %s", e)
        raise HTTPException(status_code=502, detail="The hiring committee couldn't reach a verdict just now. Please try again.")
 
 
@router.post("/tool")
def tool_route(payload: ToolIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    _check_uuid(payload.user_id)
    verify_token_belongs_to_user(payload.user_id, authorization)
    require_feature(db, payload.user_id, "interview_prep")
    if payload.tool not in TOOLS:
        raise HTTPException(status_code=400, detail="unknown tool")
    inputs = _bound_inputs(payload.inputs)
    key, msg = _REQUIRED[payload.tool]
    val = inputs.get(key)
    if not val or (isinstance(val, str) and not val.strip()):
        raise HTTPException(status_code=400, detail=msg)
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail=_AI_DOWN)
    rate_limit_by_tier(db, payload.user_id, "interview-coach", per_action_limit=400)
    try:
        return {"tool": payload.tool, "result": run_tool(client, payload.tool, inputs, _profile(db, payload.user_id))}
    except Withheld:
        # Everything usable quoted words or figures that aren't in the material: say so (the
        # page keeps the AI on and asks for a retry), never a generic failure.
        raise HTTPException(status_code=422, detail="withheld: the AI's answer used quotes or figures that aren't in your material, so it was withheld - try again.")
    except Exception as e:
        _log.warning("interview tool %s failed - %s", payload.tool, e)
        raise HTTPException(status_code=502, detail="Couldn't generate this just now. Please try again.")
 
