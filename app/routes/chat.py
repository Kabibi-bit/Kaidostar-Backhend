import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import verify_token_belongs_to_user
from app.services.rate_limit import rate_limit_by_tier
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import Profile
from app.services.chat_memory import (
    summarize_conversation,
    store_memory,
    retrieve_relevant_memory,
)
from app.services.matching import rank_listings
from app.routes.listings import _profile_to_dict, _listing_to_dict
from app.models.db_models import Listing
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/chat", tags=["chat"])
 
 
class ChatIn(BaseModel):
    user_id: str
    message: str = Field(max_length=8000)
    history: list[dict] = Field(default=[], max_length=100)
    # Workspace context the full Metis workspace composes from the user's OWN
    # material: the active project's instructions, their Metis customisation
    # (name / tone / focus / custom instructions), and their upcoming schedule.
    # Appended to the system prompt so Metis actually reasons over the project
    # and schedule the user is working in. Bounded so it can't balloon the call.
    extra_context: str = Field(default="", max_length=6000)
 
    @field_validator("history")
    @classmethod
    def _validate_history(cls, v: list[dict]) -> list[dict]:
        # max_length=100 bounds the NUMBER of turns but not each turn's size, and
        # history is passed straight to the LLM call - so without this a caller
        # could send 100 turns each with megabytes of content (an unbounded per-call
        # AI-cost/memory vector; the per-action meter only counts it as one call).
        # Also enforce the shape the Anthropic API needs, so a malformed turn fails
        # here with a clear 422 instead of a raw 502 from the model call.
        for m in v:
            if not isinstance(m, dict):
                raise ValueError("each history turn must be an object")
            if m.get("role") not in ("user", "assistant"):
                raise ValueError("each history turn needs a role of 'user' or 'assistant'")
            content = m.get("content")
            if not isinstance(content, str):
                raise ValueError("each history turn's content must be a string")
            if len(content) > 8000:
                raise ValueError("each history turn must be at most 8000 characters")
        return v
 
 
def build_system_context(db: Session, user_id: str) -> str:
    """Pulls the user's real profile, live top matches, and remembered
    facts from past conversations into one system prompt.
    """
    base = (
        "You are the assistant inside Kaidostar, an internship/job/college "
        "opportunity watch app. Answer questions about internships, job "
        "searching, applications, resumes, and career strategy. Be concise "
        "and practical."
    )
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if profile:
        base += (
            f"\n\nThe user's stated goal: \"{profile.northstar}\". "
            f"Timeframe: {profile.timeframe}. Stage: {profile.stage}. "
            f"Priorities: {', '.join(profile.priorities or [])}. "
            f"Skills: \"{profile.skills}\"."
        )
        listings = db.query(Listing).all()
        if listings:
            from app.models.db_models import DismissedListing
            dismissed_ids = {str(row.listing_id) for row in db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()}
            ranked = rank_listings(
                [_listing_to_dict(l) for l in listings],
                _profile_to_dict(profile),
                top_n=6,
                dismissed_ids=dismissed_ids,
            )
            if ranked:
                base += "\n\nTheir current top matches:\n"
                for l in ranked:
                    base += f"- {l['title']} at {l['org']} ({l['score_pct']}% match, due {l['deadline']})\n"
 
    memories = retrieve_relevant_memory(db, user_id)
    if memories:
        base += "\n\nThings you remember about this user from past conversations:\n"
        base += "\n".join(f"- {m}" for m in memories)
 
    return base
 
 
@router.post("")
def chat(payload: ChatIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    verify_token_belongs_to_user(payload.user_id, authorization)
    rate_limit_by_tier(db, payload.user_id, "metis-chat", per_action_limit=300)
    system = build_system_context(db, payload.user_id)
    # The workspace's own context (active project instructions, the user's Metis
    # customisation, and their upcoming schedule) - the user's own material,
    # clearly delimited so Metis treats it as working context, not the base role.
    if payload.extra_context and payload.extra_context.strip():
        system += "\n\n--- Metis workspace context (from this user's own projects, settings and schedule) ---\n"
        system += payload.extra_context.strip()
    messages = payload.history + [{"role": "user", "content": payload.message}]
 
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system,
            messages=messages,
        )
    except Exception as e:
        _log.warning("Could not get a reply just now - try again. - %s", e)
        raise HTTPException(status_code=502, detail="Could not get a reply just now - try again.. Please try again.")
    reply = "".join((b.text or "") for b in resp.content if b.type == "text")
 
    # Summarize anything durable from this exchange and store it -
    # this is what makes memory persist across sessions, not just within one.
    full_convo = messages + [{"role": "assistant", "content": reply}]
    try:
        summary = summarize_conversation(client, full_convo)
        store_memory(db, payload.user_id, summary)
    except Exception as e:
        # A real reply was already generated above - a failure here
        # (summarization API call, or the DB write) must not discard
        # that and turn a successful chat into an error response. The
        # person still gets their real reply; only future-session
        # memory of this exchange is honestly lost, not the exchange
        # itself.
        print(f"Chat memory summarization/storage failed (non-fatal, reply still returned): {e}")
 
    return {"reply": reply}
 
