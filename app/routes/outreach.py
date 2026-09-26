import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user, require_valid_token
from app.services.tiers import require_feature
from app.services.rate_limit import rate_limit_by_tier
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import OutreachEmail, Listing
from app.services.auto_apply import draft_outreach_for_match
from app.services.email_send import send_email
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/outreach", tags=["outreach"])
 
 
class DraftIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("/draft")
def draft_outreach(payload: DraftIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """The 'Find a contact' action - drafts a referral email straight
    into Workshop instead of showing it inline. Never sends anything.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    verify_token_belongs_to_user(payload.user_id, authorization)
    require_feature(db, payload.user_id, "outreach_drafting")
    try:
        uuid_module.UUID(payload.listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
    result = draft_outreach_for_match(db, client, payload.user_id, payload.listing_id, auto_generated=False)
    if result.get("error") == "no_profile":
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if result.get("error") == "listing_not_found":
        raise HTTPException(status_code=404, detail="Listing not found")
    if result.get("error") == "no_contact_guess":
        raise HTTPException(status_code=400, detail="Could not guess a contact address for this company")
    if (result.get("error") or "").startswith("draft_generation_failed"):
        _log.warning("Outreach draft failed - %s", result["error"])
        raise HTTPException(status_code=502, detail="Could not generate a draft just now. Please try again.")
    return result
 
 
class DraftLeadershipGroundedIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("/draft-leadership-grounded")
def draft_leadership_grounded_outreach_endpoint(payload: DraftLeadershipGroundedIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Researches the company's real, current senior leadership - not
    just the CEO, but other genuine current executives too - and what
    they've actually, recently said and prioritized publicly, then
    drafts an outreach email grounded in that real, synthesized view
    - instead of a generic referral request every other applicant
    could send. Two real web-search-backed steps, not one call
    pretending to be simple: research first, then drafting, so a
    genuine "nothing specific was found" result from the first step
    honestly shapes what the second step writes, rather than the
    draft inventing something that sounds plausible.
    """
    from app.services.market_research import get_or_research_company_leadership
    from app.services.auto_apply import draft_leadership_grounded_outreach
    from app.models.db_models import Listing
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    verify_token_belongs_to_user(payload.user_id, authorization)
    require_feature(db, payload.user_id, "outreach_drafting")
    try:
        uuid_module.UUID(payload.listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    listing = db.query(Listing).filter(Listing.id == payload.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    try:
        leadership_research = get_or_research_company_leadership(db, client, listing.org)
    except Exception as e:
        _log.warning("Could not research the company's leadership just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not research the company's leadership just now. Please try again.")
 
    result = draft_leadership_grounded_outreach(db, client, payload.user_id, payload.listing_id, leadership_research)
    if result.get("error") == "no_profile":
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if result.get("error") == "listing_not_found":
        raise HTTPException(status_code=404, detail="Listing not found")
    if result.get("error") == "no_contact_guess":
        raise HTTPException(status_code=400, detail="Could not guess a contact address for this company")
    if (result.get("error") or "").startswith("draft_generation_failed"):
        _log.warning("Outreach draft failed - %s", result["error"])
        raise HTTPException(status_code=502, detail="Could not generate a draft just now. Please try again.")
    return {
        **result,
        "priorities_summary": leadership_research.get("priorities_summary") or "",
        "leadership_research_sources": leadership_research.get("sources") or [],
    }
 
 
@router.get("/leadership-research/{listing_id}")
def get_leadership_research(listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    # Meter this paid AI + web-search call (was unmetered; require_valid_token only
    # gated it to logged-in callers). Fails open; company/leadership research is the
    # same cost class as company-research, so it shares that tier cap.
    rate_limit_by_tier(db, _auth["sub"], "company-research", per_action_limit=200)
    """A standalone view of the company research itself, not tied to
    drafting an email - so a candidate can genuinely understand what
    a company's real leadership seems to be prioritizing before
    deciding whether to reach out at all, not just see it buried
    inside a drafted message afterward.
    """
    from app.services.market_research import get_or_research_company_leadership
    from app.models.db_models import Listing
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    try:
        return get_or_research_company_leadership(db, client, listing.org)
    except Exception as e:
        _log.warning("Could not research this company's leadership just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not research this company's leadership just now. Please try again.")
 
 
@router.get("/{user_id}")
def list_outreach(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Lists every outreach email (drafted or sent) for Workshop -
    both auto-generated (while Auto mode was running) and manually
    requested via 'Find a contact'.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    rows = (
        db.query(OutreachEmail, Listing)
        .join(Listing, OutreachEmail.listing_id == Listing.id)
        .filter(OutreachEmail.user_id == user_id)
        .order_by(OutreachEmail.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(o.id),
            "listing_id": str(o.listing_id),
            "listing_title": l.title,
            "listing_org": l.org,
            "to_address": o.to_address,
            "address_verified": o.address_verified,
            "subject": o.subject,
            "body": o.body,
            "status": o.status,
            "auto_generated": o.auto_generated,
            "leadership_grounded": o.leadership_grounded,
            "leadership_research_sources": o.leadership_research_sources or [],
            "created_at": o.created_at.isoformat(),
        }
        for o, l in rows
    ]
 
 
class EditOutreachIn(BaseModel):
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=10000)
    to_address: str | None = Field(default=None, max_length=300)
 
 
@router.patch("/{outreach_id}")
def edit_outreach(outreach_id: str, payload: EditOutreachIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Lets the user edit a drafted email in Workshop before sending."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(outreach_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    outreach = db.query(OutreachEmail).filter(OutreachEmail.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    verify_token_belongs_to_user(str(outreach.user_id), authorization)
    if outreach.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent, cannot edit")
    if payload.subject is not None:
        outreach.subject = payload.subject
    if payload.body is not None:
        outreach.body = payload.body
    if payload.to_address is not None:
        outreach.to_address = payload.to_address
        outreach.address_verified = False  # editing the address resets verification status
    db.commit()
    return {"status": "updated"}
 
 
@router.post("/{outreach_id}/send")
def send_outreach(outreach_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The one real send action - fires only when explicitly called,
    which the frontend only does from a user clicking Send in
    Workshop. Never called automatically by any scan or Auto cycle.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(outreach_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    outreach = db.query(OutreachEmail).filter(OutreachEmail.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    verify_token_belongs_to_user(str(outreach.user_id), authorization)
    if outreach.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent")
 
    try:
        send_email(outreach.to_address, outreach.subject, outreach.body)
        outreach.status = "sent"
        db.commit()
        return {"status": "sent", "to_address": outreach.to_address}
    except Exception as e:
        outreach.status = "failed"
        db.commit()
        _log.warning("Send failed - %s", e)
        raise HTTPException(status_code=502, detail="Send failed. Please try again.")
 
 
@router.post("/send-all/{user_id}")
def send_all_pending(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The 'Send all pending outreach' bulk action for Workshop - still
    a single, explicit, human-triggered click, just covering everything
    queued at once instead of one at a time.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    pending = db.query(OutreachEmail).filter(OutreachEmail.user_id == user_id, OutreachEmail.status == "drafted").all()
    results = []
    for outreach in pending:
        try:
            send_email(outreach.to_address, outreach.subject, outreach.body)
            outreach.status = "sent"
            # Commit per-send, mirroring the single /send route. send_email fires an
            # irreversible REAL email, so its "sent" status must be durable BEFORE the
            # next iteration. The old single commit AFTER the whole loop meant any
            # failure mid-loop (or between the loop and the commit) left already-sent
            # emails still "drafted" - so a retry re-sent every one of them, emailing
            # real people twice. Committing each send closes that window to at most the
            # one in-flight item.
            db.commit()
            results.append({"id": str(outreach.id), "status": "sent"})
        except Exception as e:
            # send_email is a pure network call and never touches the DB session, so
            # (like the single /send route) no rollback is needed before recording the
            # failure. Log the real error internally; never return str(e) to the client
            # - it can carry provider/internal detail (matches /send's hygiene).
            outreach.status = "failed"
            db.commit()
            _log.warning("Bulk send failed for outreach %s - %s", outreach.id, e)
            results.append({"id": str(outreach.id), "status": "failed"})
    return {"results": results, "total": len(results)}
 
