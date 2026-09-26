import os
import logging
import secrets
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit_by_tier
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import EngagementSuggestion, Profile, User
from app.services.timeutil import utcnow
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/engagement", tags=["engagement"])
 
 
def _suggestion_to_dict(s: EngagementSuggestion) -> dict:
    return {
        "id": str(s.id),
        "post_content": s.post_content,
        "poster_context": s.poster_context,
        "drafted_question": s.drafted_question,
        "is_smaller_decision_maker": s.is_smaller_decision_maker,
        "reasoning": s.reasoning,
        "status": s.status,
        "email_sent_at": s.email_sent_at.isoformat() if s.email_sent_at else None,
        "responded_at": s.responded_at.isoformat() if s.responded_at else None,
        "communication_log": s.communication_log or [],
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
 
 
class DraftIn(BaseModel):
    user_id: str
    post_content: str = Field(max_length=8000)
    poster_context: str | None = Field(default=None, max_length=2000)
 
 
@router.post("/draft")
def draft_suggestion(payload: DraftIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Drafts a real, thoughtful engagement question for a real post
    the person pasted in themselves - never scrapes or auto-posts,
    see app/services/engagement.py's module docstring for why.
    """
    from app.services.engagement import draft_engagement_suggestion
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    verify_token_belongs_to_user(payload.user_id, authorization)
    rate_limit_by_tier(db, payload.user_id, "engagement-draft", per_action_limit=300)
 
    if not payload.post_content or not payload.post_content.strip():
        raise HTTPException(status_code=400, detail="post_content cannot be empty")
 
    profile = db.query(Profile).filter(Profile.user_id == payload.user_id, Profile.is_current == True).first()  # noqa: E712
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
 
    try:
        result = draft_engagement_suggestion(client, profile_dict, payload.post_content.strip(), payload.poster_context)
    except ValueError as e:
        # Log the real reason server-side; return a generic message so the raw
        # exception (which can include the full model response / internals) never
        # reaches the client. Mirrors the global handler's no-leak contract.
        _log.warning("Could not draft an engagement suggestion just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not draft a suggestion just now. Please try again.")
 
    suggestion = EngagementSuggestion(
        user_id=payload.user_id,
        post_content=payload.post_content.strip(),
        poster_context=payload.poster_context,
        drafted_question=result["drafted_question"],
        is_smaller_decision_maker=result["is_smaller_decision_maker"],
        reasoning=result["reasoning"],
        status="drafted",
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return _suggestion_to_dict(suggestion)
 
 
@router.get("/{user_id}")
def list_suggestions(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return []
    suggestions = (
        db.query(EngagementSuggestion)
        .filter(EngagementSuggestion.user_id == user_id)
        .order_by(EngagementSuggestion.created_at.desc())
        .all()
    )
    return [_suggestion_to_dict(s) for s in suggestions]
 
 
@router.post("/{suggestion_id}/send-email")
def send_suggestion_email(suggestion_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Emails the real, drafted suggestion to the person's own
    registered address, with a real, secure, single-use accept link -
    this is the "if the AI finds someone they like, they'll email the
    candidate saying it's a good idea to post this" flow, built on
    the real Resend integration already proven in email_send.py.
    """
    from app.services.email_send import send_email
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(suggestion_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Suggestion not found")
 
    suggestion = db.query(EngagementSuggestion).filter(EngagementSuggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
 
    verify_token_belongs_to_user(str(suggestion.user_id), authorization)
    user = db.query(User).filter(User.id == suggestion.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user found for this suggestion")
 
    # A real, cryptographically secure, single-use token - not a
    # guessable id, since this link works without any login.
    token = secrets.token_urlsafe(32)
    suggestion.accept_token = token
 
    app_base_url = os.getenv("APP_BASE_URL", "https://app.example.com")
    accept_url = f"{app_base_url.rstrip('/')}/engagement/accept/{token}"
 
    subject = "A real opportunity worth engaging with"
    truncated_post = f'{suggestion.post_content[:280]}{"..." if len(suggestion.post_content) > 280 else ""}'
    body = (
        f"We found a post worth a thoughtful reply:\n\n"
        f'"{truncated_post}"\n\n'
        f"Suggested question:\n\"{suggestion.drafted_question}\"\n\n"
        f"Why this one: {suggestion.reasoning}\n\n"
        f"If this looks good, confirm here and we'll mark it ready to post:\n{accept_url}\n\n"
        f"You'll still post it yourself - we never post on your behalf."
    )
 
    import html as html_module
    html_body = f"""<!DOCTYPE html>
<html><body style="margin:0; padding:0; background-color:#f4f4f7; font-family:-apple-system,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f7; padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="100%" style="max-width:520px; background-color:#ffffff; border-radius:12px; overflow:hidden;">
<tr><td style="padding:32px;">
<p style="margin:0 0 16px; font-size:13px; color:#8a8a9a; text-transform:uppercase; letter-spacing:0.04em;">A real opportunity worth engaging with</p>
<p style="margin:0 0 8px; font-size:13px; color:#6b6b7a; font-weight:600;">The post</p>
<p style="margin:0 0 20px; font-size:14px; color:#3a3a45; line-height:1.6; padding:12px 16px; background-color:#f7f7fa; border-radius:8px; border-left:3px solid #d0d0dc;">{html_module.escape(truncated_post)}</p>
<p style="margin:0 0 8px; font-size:13px; color:#6b6b7a; font-weight:600;">Suggested reply</p>
<p style="margin:0 0 20px; font-size:15px; color:#1a1a24; line-height:1.6; font-weight:500;">{html_module.escape(suggestion.drafted_question)}</p>
<p style="margin:0 0 24px; font-size:13px; color:#8a8a9a; line-height:1.6; font-style:italic;">{html_module.escape(suggestion.reasoning)}</p>
<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="border-radius:8px; background-color:#1a1a24;">
<a href="{accept_url}" style="display:inline-block; padding:12px 28px; font-size:14px; font-weight:600; color:#ffffff; text-decoration:none;">Looks good, mark this ready to post &rarr;</a>
</td></tr></table>
<p style="margin:24px 0 0; font-size:12px; color:#a0a0ac; line-height:1.5;">You'll still post it yourself - we never post on your behalf.</p>
</td></tr>
</table>
</td></tr>
</table>
</body></html>"""
 
    try:
        send_email(user.email, subject, body, html_body=html_body)
    except Exception as e:
        _log.warning("Could not send the email just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not send the email just now. Please try again.")
 
    suggestion.status = "emailed"
    suggestion.email_sent_at = utcnow()
    db.commit()
    db.refresh(suggestion)
    return _suggestion_to_dict(suggestion)
 
 
@router.get("/accept/{token}")
def accept_suggestion(token: str, db: Session = Depends(get_db)):
    """The real, public, no-login endpoint the email's accept link
    points to - deliberately requires no authentication, since the
    whole point is accepting directly from an email. Genuinely single-
    use: the token is cleared after a real accept, so the same link
    can't be replayed.
    """
    if not token or len(token) < 20:
        raise HTTPException(status_code=404, detail="This link is invalid or has expired")
 
    suggestion = db.query(EngagementSuggestion).filter(EngagementSuggestion.accept_token == token).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="This link is invalid or has expired")
 
    if suggestion.status == "accepted":
        return {"already_accepted": True, "drafted_question": suggestion.drafted_question}
 
    suggestion.status = "accepted"
    suggestion.responded_at = utcnow()
    suggestion.accept_token = None  # genuinely single-use - cleared so this exact link can't be replayed
    db.commit()
    return {"already_accepted": False, "drafted_question": suggestion.drafted_question, "post_content": suggestion.post_content}
 
 
class DeclineIn(BaseModel):
    pass
 
 
@router.post("/{suggestion_id}/decline")
def decline_suggestion(suggestion_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(suggestion_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Suggestion not found")
 
    suggestion = db.query(EngagementSuggestion).filter(EngagementSuggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
 
    verify_token_belongs_to_user(str(suggestion.user_id), authorization)
    suggestion.status = "declined"
    suggestion.responded_at = utcnow()
    suggestion.accept_token = None
    db.commit()
    db.refresh(suggestion)
    return _suggestion_to_dict(suggestion)
 
 
class LogEntryIn(BaseModel):
    note: str = Field(max_length=4000)
 
 
@router.post("/{suggestion_id}/log")
def add_communication_log_entry(suggestion_id: str, payload: LogEntryIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Records a real, user-entered update on what actually happened
    after posting - a reply they got, a follow-up question - the
    "response and questions and communication will all be considered
    by the AI" piece. This is what a future draft_engagement_suggestion
    call for the same real thread could read as genuine context,
    mirroring the same "history informs the next suggestion" pattern
    already proven for strategic-position analysis.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(suggestion_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Suggestion not found")
 
    if not payload.note or not payload.note.strip():
        raise HTTPException(status_code=400, detail="note cannot be empty")
 
    suggestion = db.query(EngagementSuggestion).filter(EngagementSuggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
 
    verify_token_belongs_to_user(str(suggestion.user_id), authorization)
    log = list(suggestion.communication_log or [])
    log.append({"at": utcnow().isoformat(), "note": payload.note.strip()})
    suggestion.communication_log = log
    db.commit()
    db.refresh(suggestion)
    return _suggestion_to_dict(suggestion)
 
