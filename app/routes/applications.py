import os
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit_by_tier
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import Application
from app.services.auto_apply import (
    draft_application,
    decide_auto_send,
    compute_sendable_at,
    create_application_for_match,
)
from app.services.timeutil import utcnow, to_naive_utc
 
_log = logging.getLogger("kaidostar")
 
 
def _candidate_dict(db, user_id):
    """The real applicant identity (name/email/phone) used to fill an application
    form, drawn from the user's account + current profile. Never invents data -
    a missing field stays empty, and the form filler (server-side submitter or the
    browser extension) safely hands off any form that needs what we don't have."""
    from app.services import auto_runner as AR
    return AR.candidate_identity(db, user_id, AR._profile(db, user_id))
 
 
def _build_resume_docx(db, user_id, pkg_resume=None):
    """The .docx that goes with an application: the person's own resume - the saved Resume Studio
    version Auto picked for this job when it picked one, else their current resume - with the
    posting's skills first. Never adds anything. None when they have no resume at all."""
    from app.services import auto_runner as AR
    return AR.resume_docx(db, user_id, AR._profile(db, user_id), pkg_resume)
 
 
def _require_autosubmit_access(db, app_record):
    """The one real gate shared by every auto-submit delivery channel (server-side
    Playwright AND the browser extension): the user must be on a tier that includes
    `auto_submit` (Pro/Max) AND have granted explicit, revocable consent to let
    Kaidostar submit applications on their behalf. Enforced on the server so a
    modified extension or a direct API call can't bypass it. Raises 403 otherwise."""
    from app.services.tiers import tier_has_feature, get_user_tier
    from app.models.db_models import Profile
    if not tier_has_feature(get_user_tier(db, str(app_record.user_id)), "auto_submit"):
        raise HTTPException(status_code=403, detail="Automatic application submission is a Pro feature. Upgrade to unlock it.")
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == app_record.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not (profile and getattr(profile, "auto_submit_consent", False)):
        raise HTTPException(
            status_code=403,
            detail="Grant Kaidostar permission to submit applications on your behalf before using auto-fill.",
        )
 
 
def deliver_accepted_application(db, app_record, listing, client=None, unattended: bool = False):
    """The single REAL delivery path for an accepted application, shared by the
    manual /send route AND Auto's unattended send (auto_runner.deliver_due), so both
    deliver identically and NEITHER ever marks an application 'sent' without a real send.
 
    The decision is deterministic and explained (no AI picks the channel, and no
    company address is ever guessed): a job board that forbids automation, a missing
    consent, a closed job, a question the person's answer bank doesn't cover - each
    becomes a ready-to-submit hand-off with the reason. A send happens only to the
    address the posting itself gives (when it's plainly the company's), or through a
    browser submission that sees the employer's confirmation - and keeps the proof."""
    from app.services.auto_runner import deliver_application
    return deliver_application(db, app_record, listing, client, unattended=unattended)
 
 
def _package_extra(db, app_record):
    """What an Auto package adds to a delivery or list response (best-effort)."""
    try:
        from app.services import auto_runner as AR
        pkg = AR.load_package(db, app_record.user_id, app_record.id)
    except Exception:
        return None
    return pkg
 
 
router = APIRouter(prefix="/applications", tags=["applications"])
 
 
class AcceptIn(BaseModel):
    user_id: str
    listing_id: str
    # The Job Search page's "Draft application" button: write the draft, never approve
    # it - the user reviews it first, whatever its fit. (Starring and "accept" keep the
    # one-click behaviour: approved when the fit clears the user's threshold.)
    draft_only: bool = False
 
 
def _v2_fit_or_none(db, user_id, listing_id):
    """The Job Search v2 fit for this listing - the number the user saw on the
    card - so the auto-approve threshold judges the same score. None (fall back
    to the older score) if the listing or profile can't be scored."""
    try:
        from app.models.db_models import Profile, Listing
        from app.services.job_search import v2_fit_for_listing
        profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if profile is None or listing is None or getattr(profile, "is_athlete", False):
            return None
        return v2_fit_for_listing(db, user_id, profile, listing)
    except Exception:
        return None
 
 
@router.post("/accept")
def accept_match(payload: AcceptIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """The one-click 'I accept this match' action - this is also what
    fires automatically when a user stars a listing (see /saved in
    saved_listings.py). Computes the real match score, drafts a
    tailored application via Claude, and decides whether it's
    confident enough to queue for auto-send or needs human review.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    verify_token_belongs_to_user(payload.user_id, authorization)
    try:
        uuid_module.UUID(payload.listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
    # Meter this paid AI drafting (was unmetered - it's the primary "apply"/star
    # action, so the highest-traffic gap). Matches the sibling /draft route's cap.
    # Fails open.
    rate_limit_by_tier(db, payload.user_id, "application-draft", per_action_limit=200)
    result = create_application_for_match(db, client, payload.user_id, payload.listing_id, fit_override=_v2_fit_or_none(db, payload.user_id, payload.listing_id),
                                          mode="draft_only" if getattr(payload, "draft_only", False) is True else None)
 
    if result.get("error") == "no_profile":
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if result.get("error") == "listing_not_found":
        raise HTTPException(status_code=404, detail="Listing not found")
    if result.get("error") == "posting_closed":
        from app.services.feed_common import closed_draft_message
        raise HTTPException(status_code=410, detail=closed_draft_message(result.get("closed")))
    if result.get("error") == "dealbreaker_conflict":
        raise HTTPException(status_code=400, detail="This listing conflicts with one of your stated deal-breakers - not drafting an application for it.")
 
    if result.get("already_existed"):
        result["note"] = "An application for this match already exists - returning it instead of drafting a duplicate."
    else:
        result["note"] = "approved = eligible to auto-send after the undo window; pending_review = needs your explicit approval first"
    return result
 
 
class DraftIn(BaseModel):
    user_id: str
    listing_id: str
    confidence_pct: float = Field(ge=0, le=100)
 
 
@router.post("/draft")
def create_draft(payload: DraftIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Drafts an application and decides auto-send vs review, based on
    the confidence score you pass in (use the score from /listings/matches).
    Kept for manual/testing use - /accept is the real one-click path.
    """
    from app.models.db_models import Profile, Listing, ResumeEntry
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    verify_token_belongs_to_user(payload.user_id, authorization)
    rate_limit_by_tier(db, payload.user_id, "application-draft", per_action_limit=300)
    try:
        uuid_module.UUID(payload.listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == payload.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    listing = db.query(Listing).filter(Listing.id == payload.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    # a job from an employer's career site that may have closed gets no new (paid) draft - as /accept
    from app.services.feed_common import listing_text, listing_tags, listing_closed, closed_draft_message
    _closed = listing_closed(db, listing)
    if _closed is not None:
        raise HTTPException(status_code=410, detail=closed_draft_message(_closed))
 
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
    posting_text = listing_text(db, listing)
    # the posting text too, as the main accept path already gives it - and employer-feed jobs carry no
    # stored tags, so the skills read in their posting stand in (they also pick which experience leads)
    listing_dict = {"title": listing.title, "org": listing.org, "tags": listing_tags(db, listing, text=posting_text),
                    "description": posting_text}
    resume_entry_rows = db.query(ResumeEntry).filter(ResumeEntry.user_id == payload.user_id).all()
    resume_entry_dicts = [{"title": e.title, "org": e.org, "raw_description": e.raw_description} for e in resume_entry_rows]
    draft_result = draft_application(client, listing_dict, profile_dict, resume_entry_dicts)
    # A genuine API failure returns {"error": ...} with no "text" key -
    # confirmed this was previously accessed directly without checking,
    # unlike create_application_for_match, which correctly guards
    # against the identical shape from the same function.
    if "error" in draft_result:
        # The service encodes the raw exception in draft_result["error"] (e.g.
        # "draft_generation_failed: <exception>"); log that server-side but return
        # a generic message so the internal detail never reaches the client.
        _log.warning("Application draft failed - %s", draft_result["error"])
        raise HTTPException(status_code=502, detail="Could not generate a draft just now. Please try again.")
    draft_text = draft_result["text"]
    status = decide_auto_send(payload.confidence_pct)
 
    app_record = Application(
        user_id=payload.user_id,
        listing_id=payload.listing_id,
        draft_content=draft_text,
        confidence_pct=payload.confidence_pct,
        status=status,
        sendable_at=compute_sendable_at() if status == "approved" else None,
        draft_flagged_terms=draft_result["flagged_terms"],
        # factors_snapshot intentionally left None here - this fallback
        # endpoint takes confidence_pct directly from the caller rather
        # than computing it via score_listing(), so there's no real
        # factor breakdown to capture. The primary path (/accept, via
        # create_application_for_match) does capture it.
    )
    db.add(app_record)
    db.commit()
    db.refresh(app_record)
 
    return {
        "application_id": str(app_record.id),
        "status": status,
        "draft": draft_text,
        "review_note": "This draft includes a number or timing claim that wasn't in the job posting or your profile - double check it before sending." if draft_result["flagged_terms"] else None,
        "note": "approved = eligible to auto-send after the undo window; pending_review = needs your explicit approval first",
    }
 
 
@router.get("/{user_id}")
def list_applications(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Lists all drafted applications for a user - this is what backs
    the frontend's Workshop page.
    """
    from app.models.db_models import Listing
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    rows = (
        db.query(Application, Listing)
        .join(Listing, Application.listing_id == Listing.id)
        .filter(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
        .all()
    )
 
    # Join the real logged outcomes so each application carries its
    # outcome_status. Without this, the frontend - which reads
    # a.outcome_status in ~25 places (outcome badges, calibration, the
    # rejection/ghost autopsy, "any positive" checks) - saw undefined for
    # every logged-in application, because overview/workshop overwrite local
    # state with this response (saveApplications(bApps)). A user who logged an
    # outcome would lose it from the UI on their next visit even though the
    # backend had it the whole time. Keep the most recent outcome per listing.
    from app.models.db_models import Outcome
    outcome_rows = (
        db.query(Outcome)
        .filter(Outcome.user_id == user_id)
        .order_by(Outcome.updated_at.asc())
        .all()
    )
    outcome_status_by_listing = {}
    outcome_time_by_listing = {}
    for o in outcome_rows:  # ascending order -> last write per listing wins (most recent)
        outcome_status_by_listing[str(o.listing_id)] = o.status
        outcome_time_by_listing[str(o.listing_id)] = o.updated_at
 
    # A hand-off for a job from an employer's career site that Kaidostar can no longer vouch for as
    # open says so on its Workshop card (the card shows send_reasoning) - one query for all of them.
    from app.services.feed_common import closed_by_listing, closed_note
    closed = closed_by_listing(db, [l for a, l in rows if a.status == "ready_to_submit"])
    # Auto's packages: why a hand-off happened (and whether it may already have gone through)
    try:
        from app.services.auto_runner import packages_for, load_autopilot
        pkgs = packages_for(db, user_id)
        apst = load_autopilot(db, user_id)
    except Exception:
        db.rollback()
        pkgs, apst = {}, {}
 
    def _route(url):
        try:
            from app.services.auto_runner import route_of
            return route_of(url)[0]
        except Exception:
            return None
 
    def _closed_extra(a, l):
        # where the apply link goes ("employer" hiring system, "company_site", "aggregator" job board) - the
        # extension never opens a job board's form for you
        out = {"apply_route": _route(l.apply_url)}
        pkg = pkgs.get(str(a.id))
        if isinstance(pkg, dict):
            if not pkg.get("manual"):
                out["auto_prepared"] = True
            ho = pkg.get("handoff") if isinstance(pkg.get("handoff"), dict) else None
            if a.status == "ready_to_submit" and ho:
                out["send_reasoning"] = str(ho.get("why") or "")[:400]
                if ho.get("possiblySent"):
                    out["auto_submit_possibly_sent"] = True
                if ho.get("autopilot"):
                    # handed to Autopilot: said only while it will take it (on, and not too long ago)
                    try:
                        from app.services.auto_runner import autopilot_will_take
                        takes = autopilot_will_take(apst, pkg, out["apply_route"])
                    except Exception:
                        takes = False
                    out["autopilot_takes"] = bool(takes)
                    if not takes:
                        out["send_reasoning"] = "Ready for one click: open it with the Kaidostar Apply extension (it fills the form in your browser), or submit it at the posting."
        c = closed.get(str(l.id)) if a.status == "ready_to_submit" else None
        if c is not None:
            # a standing heads-up, not a cause: the hand-off may have happened earlier for another reason
            out.update({"send_reasoning": closed_note(c, sent=False), "posting_closed": True})
        return out
 
    return [
        {
            "id": str(a.id),
            "listing_id": str(a.listing_id),
            "listing_title": l.title,
            "listing_org": l.org,
            "status": a.status,
            "confidence_pct": float(a.confidence_pct) if a.confidence_pct else None,
            "draft": a.draft_content,
            "sendable_at": a.sendable_at.isoformat() if a.sendable_at else None,
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
            # How/where an accepted application was actually delivered - so the
            # Workshop can honestly show "emailed to <addr>" vs. a web hand-off
            # with the direct apply link, instead of a bare "sent" label.
            "sent_channel": a.sent_channel,
            "sent_to_address": a.sent_to_address,
            "apply_url": l.apply_url,
            "auto_generated": a.auto_generated,
            "created_at": a.created_at.isoformat(),
            "outcome_status": outcome_status_by_listing.get(str(a.listing_id)),
            "outcome_logged_at": outcome_time_by_listing[str(a.listing_id)].isoformat() if outcome_time_by_listing.get(str(a.listing_id)) else None,
            # The frontend overwrites local application state with this response
            # (overview/workshop call saveApplications(bApps)), and its
            # outcome-learned personalization, self-audit, and factor-interaction
            # features read these two off each application:
            # getPersonalizedFactorWeightsJS / getFactorReliabilityDetail /
            # computeFactorInteractions filter on factors_snapshot, and
            # auditPersonalizationEffect needs counterfactual_confidence_pct.
            # Omitting them silently reset ALL of those to "no data" on a logged-in
            # user's next visit even though the backend stored them - the exact
            # hydration-drop already fixed just above for outcome_status.
            # `is not None` (not truthiness) so a genuine 0 counterfactual survives.
            "counterfactual_confidence_pct": float(a.counterfactual_confidence_pct) if a.counterfactual_confidence_pct is not None else None,
            "factors_snapshot": a.factors_snapshot,
            **_closed_extra(a, l),
        }
        for a, l in rows
    ]
 
 
@router.post("/{application_id}/approve")
def approve_application(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """For applications sitting in pending_review - the human approval step."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    # an application that has gone out (or is going out right now) is never re-approved - that
    # would queue the same application to be sent a second time
    if app_record.status == "sent":
        raise HTTPException(status_code=409, detail="This application has already been sent.")
    if app_record.status == "sending":
        raise HTTPException(status_code=409, detail="This application is being sent right now.")
    _refuse_if_maybe_sent(db, app_record)
    app_record.status = "approved"
    app_record.sendable_at = compute_sendable_at()
    try:
        from app.services.auto_runner import note_person_approved
        note_person_approved(db, app_record, app_record.sendable_at)
    except Exception:
        pass
    db.commit()
    return {"status": "approved", "sendable_at": app_record.sendable_at.isoformat()}
 
 
@router.post("/{application_id}/send")
def send_application(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Delivers an accepted application for real - only if approved and the
    undo window has passed (or a retry of one that was handed back).
 
    Deterministic and explained (deliver_accepted_application): sent only to the
    address the posting itself gives when it's plainly the company's, or by a
    browser submission that sees the employer's confirmation (proof kept) - and
    otherwise handed back ready to submit, with the reason. It never claims a
    submission it didn't make and never emails a guessed address.
    """
    from app.models.db_models import Listing
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    # "approved" is a fresh send; "ready_to_submit" is a retry of a delivery that
    # previously fell back to the hand-off (e.g. the user has now granted consent),
    # so allow it to re-attempt without going back through the undo window.
    if app_record.status == "sending":
        raise HTTPException(status_code=409, detail="This application is being sent right now.")
    if app_record.status not in ("approved", "ready_to_submit"):
        raise HTTPException(status_code=400, detail="Application is not approved yet")
    _refuse_if_maybe_sent(db, app_record)
    if app_record.status == "approved":
        # Coerce the DB value to naive UTC: sendable_at is TIMESTAMPTZ, so psycopg2
        # reads it back tz-aware, and comparing/subtracting it against the naive
        # utcnow() would raise "can't compare offset-naive and offset-aware datetimes"
        # on real Postgres (it just happens to work if the dev DB returns naive).
        _sendable_at = to_naive_utc(app_record.sendable_at)
        if _sendable_at and utcnow() < _sendable_at:
            remaining = (_sendable_at - utcnow()).seconds // 60
            raise HTTPException(status_code=400, detail=f"Still in undo window - {remaining} minutes left")
 
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    # The real, shared delivery path (also used by Auto's unattended send). It
    # actually sends or hands off, and never marks 'sent' without a real send.
    return deliver_accepted_application(db, app_record, listing)
 
 
def _refuse_if_maybe_sent(db, app_record):
    """An application that may already have reached the employer is never sent, approved or submitted again until
    you say it didn't go through (the Auto page, or the extension's panel)."""
    pkg = _package_extra(db, app_record) or {}
    ho = pkg.get("handoff") if isinstance(pkg.get("handoff"), dict) else {}
    if app_record.status == "ready_to_submit" and ho.get("possiblySent"):
        raise HTTPException(status_code=409, detail="This application may already have gone through - check the posting (or your email). If it didn't, choose “It didn’t go through” on the Auto page first.")
 
 
@router.post("/{application_id}/mark-submitted")
def mark_application_submitted(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The user confirms they actually submitted a web-form application at the
    posting's apply_url. Valid from ready_to_submit (or approved, if they went
    straight to the posting) - flips it to sent so the record and outcome
    tracking reflect a genuinely-submitted application, without the app ever
    claiming to have submitted a web form it cannot.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    if app_record.status not in ("ready_to_submit", "approved"):
        raise HTTPException(status_code=400, detail="Application is not ready to submit")
    if not _mark_sent_once(db, app_record, app_record.sent_channel or "web"):
        raise HTTPException(status_code=409, detail="This application was just sent (or is being sent) - refresh to see it.")
    _package_sent(db, app_record, {"by": "you", "url": None})
    db.commit()
    return {"status": "sent", "sent_at": app_record.sent_at.isoformat(), "channel": app_record.sent_channel}
 
 
def _mark_sent_once(db, app_record, channel) -> bool:
    """approved / ready_to_submit -> sent, in one conditional update, so an unattended send and a
    confirmation from your browser can never both record the same application."""
    now = utcnow()
    n = (db.query(Application)
         .filter(Application.id == app_record.id, (Application.status == "ready_to_submit") | (Application.status == "approved"))
         .update({Application.status: "sent", Application.sent_at: now, Application.sent_channel: channel}, synchronize_session=False))
    if n != 1:
        db.rollback()
        return False
    app_record.status, app_record.sent_at, app_record.sent_channel = "sent", now, channel
    return True
 
 
def _package_sent(db, app_record, proof):
    """Record a send on the application's Auto package (sent date, proof, follow-up date). Best-effort."""
    try:
        from app.services import auto_runner as AR
        pkg = AR.load_package(db, app_record.user_id, app_record.id)
        if pkg is None:
            return
        rules = AR.rules_of(AR._profile(db, app_record.user_id))
        AR._attempt(pkg, app_record.sent_channel or "web", "sent", "Sent", proof)
        AR.mark_sent_package(pkg, rules, AR._ms(app_record.sent_at) or AR._now_ms(), proof, app_record.sent_channel)
        AR.save_package(db, app_record.user_id, app_record.id, pkg)
    except Exception:
        pass
 
 
@router.get("/{application_id}/autofill")
def application_autofill_data(application_id: str, autopilot: bool = False, lease: str | None = None, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The data the Kaidostar browser extension needs to fill THIS application's
    form in the user's own browser - their real logged-in session and residential
    IP, which is what actually reaches login-gated ATSes and avoids the bot-block a
    server-side headless browser trips. Returns first/last/full name, email, phone,
    the cover-letter text, the posting's apply URL, and whether a real résumé file
    is available (fetched separately from /resume-file).
 
    Gated by the SAME real gate as server-side auto-submit - Pro tier AND explicit
    auto-submit consent (_require_autosubmit_access). The extension is just another
    delivery channel for the auto_submit feature, so the gate is enforced here on
    the server: a modified client cannot bypass it. This makes no AI call and starts
    no server-side browser (the fill runs client-side, at no per-call server cost),
    so it is deliberately not metered against the auto-submit cap - the Pro+consent
    gate is the control. Never invents applicant data; empty fields stay empty and
    the extension's safety guards hand off any form it can't fill honestly.
 
    autopilot (+ lease): the extension's Autopilot is opening it, to apply on its own - only one this browser was given
    (its lease token, from POST /auto/{user_id}/autopilot) and hasn't lost. Without it, you're opening it yourself:
    it's yours from then on (Autopilot never takes it, and stops applying to it if it was).
    """
    from app.models.db_models import Listing, ResumeEntry
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    _require_autosubmit_access(db, app_record)
    if app_record.status == "sent":
        raise HTTPException(status_code=409, detail="This application was already sent.")
    if app_record.status == "sending":
        raise HTTPException(status_code=409, detail="Kaidostar is sending this application right now.")
    if app_record.status not in ("approved", "ready_to_submit"):
        raise HTTPException(status_code=400, detail="Approve this application first.")
 
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    from app.services import auto_runner as AR
    # a job board's own apply form is never filled or submitted for you - those sites forbid it
    route, host = AR.route_of(listing.apply_url)
    if route == "aggregator":
        raise HTTPException(status_code=409, detail=(host or "This") + " is a job board, and the extension never fills a job board's own form - apply there yourself (your answers are on the Auto page: Copy my answers).")
    # a submit whose result was never seen may already have reached the employer: never opened for a second go
    pkg0 = _package_extra(db, app_record) or {}
    ho0 = pkg0.get("handoff") if isinstance(pkg0.get("handoff"), dict) else {}
    if ho0.get("possiblySent"):
        raise HTTPException(status_code=409, detail="This application may already have gone through - check the posting (or your email). If it didn't, choose “It didn’t go through” on the Auto page, then open it again.")
    if autopilot:
        # Autopilot opens only one this browser was given, and still has (you didn't open it yourself meanwhile, its time
        # isn't up)
        if not (app_record.status == "ready_to_submit" and ho0.get("key") == "extension" and AR.autopilot_lease_held(pkg0, token=lease or "")):
            raise HTTPException(status_code=409, detail="Autopilot isn't applying to this one any more - it was opened elsewhere, or its turn ran out.")
    elif app_record.status == "ready_to_submit":
        # you're opening it yourself: it's yours - Autopilot never takes it (and stops if it was applying to it)
        try:
            pkg1 = AR.load_package(db, app_record.user_id, app_record.id, locked=True)
            if AR.autopilot_take_over(pkg1):
                AR.save_package(db, app_record.user_id, app_record.id, pkg1)
            db.commit()
        except Exception:
            db.rollback()
 
    if app_record.status == "approved":
        # you're submitting it in your browser now: the unattended send must not also deliver it
        n = (db.query(Application).filter(Application.id == app_record.id, Application.status == "approved")
             .update({Application.status: "ready_to_submit", Application.sent_channel: "web"}, synchronize_session=False))
        db.commit()
        if n != 1:
            raise HTTPException(status_code=409, detail="Kaidostar is sending this application right now.")
        app_record.status = "ready_to_submit"
        try:
            from app.services import auto_runner as AR
            pkg = AR.load_package(db, app_record.user_id, app_record.id, locked=True)
            if pkg is not None:
                AR.autopilot_release(pkg)
                pkg["handoff"] = {"key": "extension_opened", "why": "Opened in the Kaidostar Apply extension - finish it there, or at the posting.", "possiblySent": False,
                                  "at": AR._now_ms()}
                AR.save_package(db, app_record.user_id, app_record.id, pkg)
            db.commit()
        except Exception:
            db.rollback()
 
    candidate = _candidate_dict(db, app_record.user_id)
    has_resume = (
        db.query(ResumeEntry).filter(ResumeEntry.user_id == app_record.user_id).first() is not None
    )
    pkg = _package_extra(db, app_record) or {}
    if not has_resume and (pkg.get("resume") or {}).get("source") == "version":
        has_resume = True   # a saved Resume Studio version is a resume too
    try:
        from app.services import auto_runner as AR
        AR.note_extension_seen(db, app_record.user_id)
        policy = AR.rules_of(AR._profile(db, app_record.user_id)).get("coverLetter", "asked")
    except Exception:
        policy = "asked"
    return {
        "application_id": str(app_record.id),
        "first_name": candidate["first_name"],
        "last_name": candidate["last_name"],
        "full_name": candidate["full_name"],
        "email": candidate["email"],
        "phone": candidate["phone"],
        "cover_letter": app_record.draft_content or "",
        "apply_url": listing.apply_url,
        "listing_title": listing.title,
        "listing_org": listing.org,
        "resume_available": has_resume,
        "resume_url": f"/applications/{app_record.id}/resume-file" if has_resume else None,
        # the form's other questions are answered only from the person's own answer bank
        "answers_url": f"/applications/{app_record.id}/answers",
        # a cover letter is written on request only (when the form asks for one), never by default
        "cover_letter_policy": policy,
        "cover_letter_url": f"/applications/{app_record.id}/cover-letter",
        "resume_note": " ".join((pkg.get("resume") or {}).get("changes") or [])[:400],
        # where the extension may submit on its own (an employer's hiring system); elsewhere the click is yours
        "ats_domains": _ats_domains(),
        # job boards: the extension never fills or submits there, even if a link leads to one
        "board_domains": _board_domains(),
        # the extension tells Kaidostar right before it clicks submit, so a result it never sees isn't retried
        "attempt_url": f"/applications/{app_record.id}/submit-attempt",
        # the application form's own page, on hiring systems that keep it apart from the job's page ("" otherwise)
        "form_url": _form_url(listing.apply_url),
    }
 
 
def _form_url(apply_url) -> str:
    try:
        from app.services import auto_runner as AR
        return AR.application_form_url(apply_url)
    except Exception:
        return ""
 
 
def _ats_domains() -> list:
    try:
        from app.services import job_engine as JE
        return [str(d) for d in (JE.TAX.get("ats_domains") or [])][:60]
    except Exception:
        return []
 
 
def _board_domains() -> list:
    try:
        from app.services import job_engine as JE
        return [str(d) for d in (JE.TAX.get("aggregator_domains") or [])][:60]
    except Exception:
        return []
 
 
AUTOPILOT_NOT_ITS = ("Autopilot no longer holds this application - it was opened elsewhere, approved again, or its turn ran out - "
                     "so it doesn't submit it.")
 
 
@router.post("/{application_id}/submit-attempt")
def application_submit_attempt(application_id: str, own: bool = False, autopilot: bool = False, lease: str | None = None, db: Session = Depends(get_db),
                               authorization: str = Header(None)):
    """The extension calls this right BEFORE it clicks the form's submit button - or as you submit the form yourself
    (own). If it then never sees the result (the page moved on, the tab closed, the browser crashed), the application is
    already marked "may have gone through": Kaidostar won't open it again for you, and tells you to check before
    resubmitting. A confirmed submission afterwards records it as sent, as usual. Same Pro + consent gate as autofill.
    autopilot (+ lease): Autopilot's own click, applying on its own - only while the application is still this browser's
    (you didn't open it yourself, or approve it again, meanwhile): otherwise it's refused, and nothing is clicked."""
    from app.models.db_models import Listing
    from app.services import auto_runner as AR
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    _require_autosubmit_access(db, app_record)
    if app_record.status in ("sent", "sending"):
        raise HTTPException(status_code=409, detail="This application was already sent.")
    if app_record.status not in ("approved", "ready_to_submit"):
        raise HTTPException(status_code=400, detail="Approve this application first.")
    by_autopilot = autopilot and not own
    if by_autopilot:
        # Autopilot's click: checked before anything changes - only one this browser holds, still waiting to be submitted
        pk0 = AR.load_package(db, app_record.user_id, app_record.id) or {}
        ho0 = pk0.get("handoff") if isinstance(pk0.get("handoff"), dict) else {}
        if app_record.status != "ready_to_submit" or ho0.get("key") != "extension" or not AR.autopilot_lease_held(pk0, token=lease or ""):
            raise HTTPException(status_code=409, detail=AUTOPILOT_NOT_ITS)
    if app_record.status == "approved":
        # submitting in your browser now: the unattended send must not also deliver it
        n = (db.query(Application).filter(Application.id == app_record.id, Application.status == "approved")
             .update({Application.status: "ready_to_submit", Application.sent_channel: "web"}, synchronize_session=False))
        db.commit()
        if n != 1:
            raise HTTPException(status_code=409, detail="Kaidostar is sending this application right now.")
        app_record.status = "ready_to_submit"
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    pkg = AR.load_package(db, app_record.user_id, app_record.id, locked=True) or AR._manual_pkg(app_record, listing)
    ho = pkg.get("handoff") if isinstance(pkg.get("handoff"), dict) else {}
    if by_autopilot and not (ho.get("key") == "extension" and AR.autopilot_lease_held(pkg, token=lease or "")):
        db.rollback()
        raise HTTPException(status_code=409, detail=AUTOPILOT_NOT_ITS)
    if ho.get("possiblySent"):
        if own is True:
            # you submitted it again yourself (after one whose result wasn't seen): it stays "may have gone through" -
            # noted, never refused (your click has already happened)
            AR._attempt(pkg, "web_ext", "clicked", "Submitted again on the page, by you - waiting for the page to confirm it")
            AR.save_package(db, app_record.user_id, app_record.id, pkg)
            db.commit()
            return {"ok": True, "again": True}
        # one submit whose result nobody saw is enough: a second (another tab, a second run) could send it twice
        raise HTTPException(status_code=409, detail="This application may already have gone through - check the posting (or your email). If it didn't, choose “It didn’t go through” first.")
    AR._attempt(pkg, "web_ext", "clicked", ("Submit clicked by Kaidostar Apply's Autopilot" if by_autopilot else "Submit clicked in the Kaidostar Apply extension")
                + " - waiting for the page to confirm it")
    pkg["handoff"] = {"key": "extension_clicked", "possiblySent": True, "at": AR._now_ms(),
                      "why": "Submitted from the Kaidostar Apply extension, but its confirmation wasn't seen - check the posting (or your email) before submitting again."}
    AR.save_package(db, app_record.user_id, app_record.id, pkg)
    db.commit()
    return {"ok": True}
 
 
@router.post("/{application_id}/not-sent")
def application_not_sent(application_id: str, took_back: bool = False, db: Session = Depends(get_db), authorization: str = Header(None)):
    """You checked: an application Kaidostar flagged as "may have gone through" did not. The flag is cleared,
    so you (or the extension) can submit it again. Only you can say this - Kaidostar never clears it for a submit that
    was clicked. took_back: the extension taking back its own note because it never clicked (you closed its panel
    while it was about to, or the form's button couldn't be pressed)."""
    from app.services import auto_runner as AR
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    if app_record.status != "ready_to_submit":
        raise HTTPException(status_code=409 if app_record.status in ("sent", "sending") else 400,
                            detail="This application was already sent." if app_record.status in ("sent", "sending") else "This application isn't waiting to be submitted.")
    pkg = AR.load_package(db, app_record.user_id, app_record.id, locked=True)
    ho = pkg.get("handoff") if isinstance(pkg, dict) and isinstance(pkg.get("handoff"), dict) else None
    if ho and ho.get("possiblySent"):
        ho["possiblySent"] = False
        ho["at"] = AR._now_ms()
        if took_back:
            ho["why"] = "Kaidostar Apply didn't click submit after all - ready for you to submit."
            AR._attempt(pkg, "check", "not_sent", "Kaidostar Apply took back its note: it never clicked submit")
        else:
            ho["why"] = "You checked - it didn't go through. Ready for you to submit."
            AR._attempt(pkg, "check", "not_sent", "You said it didn't go through")
        AR.save_package(db, app_record.user_id, app_record.id, pkg)
    db.commit()
    return {"ok": True}
 
 
@router.get("/{application_id}/resume-file")
def application_resume_file(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The user's real résumé as a .docx, for the extension to attach to a form's
    file input in the user's browser. Same Pro+consent gate as /autofill. Returns
    404 when the user has no résumé entries - the form's résumé field, if required,
    then safely blocks the extension's auto-submit rather than sending without one.
    """
    from fastapi import Response
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    _require_autosubmit_access(db, app_record)
 
    pkg = _package_extra(db, app_record) or {}
    data = _build_resume_docx(db, app_record.user_id, pkg.get("resume"))
    if not data:
        raise HTTPException(status_code=404, detail="No résumé on file to attach")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=resume.docx"},
    )
 
 
class SubmitProofIn(BaseModel):
    url: str | None = Field(default=None, max_length=1000)
    phrase: str | None = Field(default=None, max_length=200)
    answered: int | None = Field(default=None, ge=0, le=200)
    answers: list | None = Field(default=None, max_length=40)   # [{label, answer}] - what the form was told
 
 
@router.post("/{application_id}/confirm-autofill-submit")
def confirm_autofill_submit(application_id: str, payload: SubmitProofIn | None = None, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The extension calls this ONLY after it has verified a real submission
    happened in the browser (a genuine post-submit change - URL moved to a
    confirmation page or a confirmation message newly appeared - via
    KaidostarFill.looksConfirmed). Flips the application to sent with channel
    'web_ext', so the record honestly reflects a submission the extension actually
    observed. If the extension can't confirm, it does NOT call this - the app stays
    ready_to_submit and the user is shown the filled form to finish. Valid from
    approved/ready_to_submit only, so it can never fabricate a 'sent' out of thin
    air for an application that was never accepted."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    # The Pro+consent gate still applies: confirming an extension submission is
    # part of the same paid, consented feature.
    _require_autosubmit_access(db, app_record)
    if app_record.status not in ("ready_to_submit", "approved"):
        raise HTTPException(status_code=409 if app_record.status in ("sent", "sending") else 400,
                            detail="This application was already sent." if app_record.status in ("sent", "sending") else "Application is not ready to submit")
    if not _mark_sent_once(db, app_record, "web_ext"):
        raise HTTPException(status_code=409, detail="This application was already sent.")
    proof = {"by": "extension"}
    if payload is not None:
        if isinstance(getattr(payload, "url", None), str) and payload.url.lower().startswith(("http://", "https://")):
            proof["url"] = payload.url[:1000]
        if isinstance(getattr(payload, "phrase", None), str):
            proof["phrase"] = payload.phrase[:200]
        if isinstance(getattr(payload, "answered", None), int):
            proof["answered"] = payload.answered
        if isinstance(getattr(payload, "answers", None), list):
            proof["answers"] = [{"label": str(a.get("label") or "")[:120], "answer": str(a.get("answer") or "")[:120]}
                                for a in payload.answers[:40] if isinstance(a, dict)]
    _package_sent(db, app_record, proof)
    db.commit()
    return {"status": "sent", "sent_at": app_record.sent_at.isoformat(), "channel": "web_ext"}
 
 
@router.post("/{application_id}/undo")
def undo_application(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    if app_record.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent, cannot undo")
    if app_record.status == "sending":
        raise HTTPException(status_code=409, detail="It's being sent right now - check back in a minute.")
    app_record.status = "undone"
    db.commit()
    return {"status": "undone"}
 
 
@router.get("/{application_id}/package")
def application_package(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """What Auto put in this application and why: the resume it chose (and what it changed), the
    cover-letter decision, the answers it still needs, every delivery attempt and the proof of a send."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    pkg = _package_extra(db, app_record)
    if pkg is None:
        raise HTTPException(status_code=404, detail="This application wasn't prepared by Auto")
    return pkg
 
 
@router.get("/{application_id}/resume.docx")
def application_resume_download(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The resume that goes with this application (the one Auto chose, skills ordered for the job),
    for the person to download and submit themselves. Just theirs - no Pro or consent needed."""
    from fastapi import Response
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    pkg = _package_extra(db, app_record) or {}
    data = _build_resume_docx(db, app_record.user_id, pkg.get("resume"))
    if not data:
        raise HTTPException(status_code=404, detail="No resume on file yet - add one in Resume Studio.")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=resume.docx"},
    )
 
 
@router.post("/{application_id}/cover-letter")
def application_cover_letter(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Write a cover letter for this application on request (the form asks for one, or the person
    wants one). From the posting and their own words, checked for invented claims; replaces the
    draft only while the application hasn't been sent."""
    import uuid as uuid_module
    from app.models.db_models import Listing
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    if app_record.status in ("sent", "sending", "undone"):
        raise HTTPException(status_code=400, detail="This application can't be changed now.")
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    from app.services import auto_runner as AR
    profile = AR._profile(db, app_record.user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
    rate_limit_by_tier(db, str(app_record.user_id), "application-draft", per_action_limit=200)
    pkg = _package_extra(db, app_record) or {}
    cand = {"coverAsked": True, "skills": ((pkg.get("resume") or {}).get("moved") or [])}
    res = AR.cover_letter_for(db, client, app_record.user_id, profile, listing, cand, AR.rules_of(profile), force=True)
    if not res.get("text"):
        raise HTTPException(status_code=502, detail="Couldn't write a cover letter just now. Please try again.")
    app_record.draft_content = res["text"]
    app_record.draft_flagged_terms = res["flagged"] or None
    returned = False
    if res["flagged"] and app_record.status == "approved":
        # it mentions something that isn't in the posting or your profile: never sent before you've read it
        app_record.status, app_record.sendable_at, returned = "pending_review", None, True
    if pkg:
        pkg["coverLetter"] = True
        pkg["coverNote"] = res.get("note", "")
        pkg["needs"] = [n for n in (pkg.get("needs") or []) if n.get("key") != "cover_letter"]
        if returned:
            pkg["approvedAt"] = None
            pkg["needs"] = [n for n in pkg["needs"] if n.get("key") != "flagged"] + [{"key": "flagged", "why": "The new cover letter mentions " + ", ".join(res["flagged"][:3]) + ", which isn't in the posting or your profile - read it, then approve again"}]
        AR.save_package(db, app_record.user_id, app_record.id, pkg)
    db.commit()
    return {"cover_letter": res["text"], "flagged_terms": res["flagged"], "status": app_record.status,
            "review_note": ("It mentions " + ", ".join(res["flagged"][:3]) + ", which isn't in the posting or your profile - check it" +
                            (" (it's back in Needs you until you approve it again)." if returned else ".")) if res["flagged"] else None}
 
 
class QuestionsIn(BaseModel):
    questions: list = Field(default_factory=list, max_length=80)
    page: dict | None = None      # the job page's own structured data (schema.org JobPosting), as the extension read it
 
 
def _clean_page(page):
    """What the extension read from the job page's structured data, bounded and typed - or None."""
    if not isinstance(page, dict):
        return None
    def strs(v):
        return [str(x)[:120] for x in (v if isinstance(v, list) else [])[:20] if isinstance(x, str) and x.strip()]
    n = page.get("n")
    return {"n": n if isinstance(n, int) and 0 <= n <= 50 else 0, "title": str(page.get("title") or "")[:200],
            "countries": strs(page.get("countries")), "regions": strs(page.get("regions")), "localities": strs(page.get("localities")),
            "remote": strs(page.get("remote")), "telecommute": page.get("telecommute") is True}
 
 
@router.post("/{application_id}/answers")
def application_answers(application_id: str, payload: QuestionsIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The extension sends the questions on an application form; this answers the ones the person's
    own answer bank covers - and says, for the rest, why it won't. The rules first; a question they don't
    recognise is read by AI from its own words (never the person's answers) and answered only when two
    readings agree (auto_runner.answer_form). Same Pro + consent gate as autofill."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    _require_autosubmit_access(db, app_record)
    from app.services import auto_answers as AA
    from app.services import auto_runner as AR
    from app.models.db_models import Listing
    qs = []
    for q in (payload.questions or [])[:80]:
        if not isinstance(q, dict):
            qs.append({})
            continue
        qs.append({"label": str(q.get("label") or "")[:300], "type": str(q.get("type") or "text")[:20],
                   "options": [str(o)[:200] for o in (q.get("options") if isinstance(q.get("options"), list) else [])[:60]],
                   "required": bool(q.get("required")),
                   # an answer the form picked by itself (no "Select..." placeholder, a pre-checked radio)
                   "preset": bool(q.get("preset")), "current": str(q.get("current") or "")[:200]})
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    client = get_client()
    if client is not None:
        # AI reading is metered per person per day; past the limit a form is answered by the rules alone (never refused)
        from app.services.rate_limit import rate_limit
        from app.services.question_reader import DAILY_READS
        try:
            rate_limit(db, str(app_record.user_id), "question-reading", limit_per_day=DAILY_READS)
        except HTTPException:
            client = None
    try:
        answers = AR.answer_form(db, app_record.user_id, listing, qs, _clean_page(payload.page), client, metered=True)
    except Exception as e:
        _log.info("Answering with readings failed - %s", e)
        db.rollback()
        answers = AR.withhold_learned(AA.resolve_all(qs, AR.load_answers(db, app_record.user_id), AR.job_country_of(db, listing),
                                                     None, getattr(listing, "org", None)), qs, db)
    return {"answers": answers}
 
 
class LearnIn(BaseModel):
    answers: list = Field(default_factory=list, max_length=40)   # [{label, type, options, answer}] the person gave on the form
    page: dict | None = None                                     # the job page's structured data (pageJob), for the job's country
 
 
@router.post("/{application_id}/learn-answers")
def application_learn_answers(application_id: str, payload: LearnIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The person answered some of a form's questions on the page themselves and asked Kaidostar to remember them:
    each is saved to their answer bank, for that same question, word for word (never a question Kaidostar doesn't
    answer for anyone, a voluntary equal-opportunity one, or a tick box). Same Pro + consent gate as autofill."""
    import uuid as uuid_module
    from app.models.db_models import Listing
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    _require_autosubmit_access(db, app_record)
    from app.services import auto_answers as AA
    from app.services import auto_runner as AR
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    bank = AR.load_answers(db, app_record.user_id)
    given = [dict(g) for g in (payload.answers or [])[:40] if isinstance(g, dict)]
    # what each question is: as the AI read it on the form - or, for one it hasn't read, read now (the question's own words
    # only; counted with the form readings). A work-authorization, medical or voluntary question the rules' words miss is
    # never remembered.
    kinds = [None] * len(given)
    try:
        from app.services import question_reader as QR
        qforms = [{"label": g.get("label"), "type": g.get("type"), "options": g.get("options")} for g in given]
        kinds = [QR.cached_kind(q, db) for q in qforms]
        client = get_client() if bank.get("ai", True) else None
        if client is not None and any(k is None for k in kinds):
            from app.services.rate_limit import rate_limit
            try:
                rate_limit(db, str(app_record.user_id), "question-reading", limit_per_day=QR.DAILY_READS)
            except HTTPException:
                client = None
            if client is not None:
                fresh = iter(QR.kinds_now([q for q, k in zip(qforms, kinds) if k is None], client, db))
                kinds = [k if k is not None else next(fresh, None) for k in kinds]
    except Exception:
        pass
    for g, k in zip(given, kinds):
        g["read"] = k or ""
    # (an answer is reused for jobs in the country of this one only - when that's known)
    try:
        country = AR.job_country_of(db, listing, _clean_page(payload.page))
    except Exception:
        db.rollback()
        country = None
    merged, saved, skipped = AA.learn(bank, given, org=(getattr(listing, "org", "") or ""), now_ms=AR._now_ms(), country=country)
    if saved:
        bank = AR.save_answers(db, app_record.user_id, merged)
        db.commit()
    return {"saved": saved, "skipped": skipped, "custom": len(bank.get("custom") or [])}
 
 
class FollowUpIn(BaseModel):
    done: bool = True
    snooze_days: int = Field(default=0, ge=0, le=30)
 
 
@router.post("/{application_id}/followed-up")
def application_followed_up(application_id: str, payload: FollowUpIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Mark a sent application's follow-up done (you sent your note), or snooze the reminder."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    from app.services import auto_runner as AR
    pkg = _package_extra(db, app_record)
    if pkg is None:
        raise HTTPException(status_code=404, detail="This application wasn't prepared by Auto")
    fu = pkg.get("followUp") if isinstance(pkg.get("followUp"), dict) else {}
    now = AR._now_ms()
    if payload.snooze_days and not payload.done:
        fu.update({"dueAt": now + payload.snooze_days * AR.DAY_MS, "notifiedAt": None, "doneAt": None})
    elif payload.done:
        fu["doneAt"] = now
    else:
        fu["doneAt"] = None
    pkg["followUp"] = fu
    AR.save_package(db, app_record.user_id, app_record.id, pkg)
    db.commit()
    return {"followUp": fu}
 
 
@router.get("/{application_id}/explain-outcome")
def explain_outcome(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The rejection/ghost autopsy - a real, specific comparison of what
    was actually sent against the actual listing, grounded in the real
    outcome logged for it. Requires an outcome to already be logged via
    POST /outcomes for this listing, since there's nothing to analyze
    against otherwise.
    """
    import os
    import anthropic
    from app.models.db_models import Listing, Profile, Outcome
    from app.services.calibration import explain_outcome_deep
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
 
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    # Meter this paid AI autopsy (was unmetered). Fails open; shares the
    # "explain-outcome" tier cap, consistent with personalization-insights.
    rate_limit_by_tier(db, str(app_record.user_id), "explain-outcome", per_action_limit=200)
 
    outcome = (
        db.query(Outcome)
        .filter(Outcome.user_id == app_record.user_id, Outcome.listing_id == app_record.listing_id)
        .order_by(Outcome.updated_at.desc())
        .first()
    )
    if not outcome:
        raise HTTPException(status_code=400, detail="No outcome logged for this application yet - log one via POST /outcomes first")
    if outcome.status not in {"rejected", "ghosted"}:
        raise HTTPException(status_code=400, detail="Autopsy is only meaningful for a rejected or ghosted outcome")
 
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == app_record.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not listing or not profile:
        raise HTTPException(status_code=404, detail="Listing or profile not found")
 
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
    from app.services.feed_common import listing_tags
    listing_dict = {"title": listing.title, "org": listing.org, "tags": listing_tags(db, listing)}
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
 
    try:
        explanation = explain_outcome_deep(
            client, listing_dict, app_record.draft_content,
            float(app_record.confidence_pct or 0), outcome.status, profile_dict,
        )
    except Exception as e:
        _log.warning("Could not generate this explanation just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate this explanation just now. Please try again.")
    return {"application_id": application_id, "outcome_status": outcome.status, "explanation": explanation}
 
 
SAME_COMPANY_CAUTION_THRESHOLD = 3
 
 
@router.get("/{user_id}/company-concentration")
def get_company_concentration(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Surfaces companies the person has applied to enough times that a
    further application starts reading as spray-pattern in an ATS -
    the concrete answer to the documented etiquette line (~2-3
    relevant roles per company is normal; more looks unfocused).
    Counts only genuinely ACTIVE applications (a discarded/undone one
    was never actually sent, so it doesn't count against the line),
    grouped by a normalized org name so trivial formatting
    differences don't split or miss a real repeat. Never blocks
    anything - it's honest awareness the person can act on.
    """
    import uuid as uuid_module
    import re
    from app.models.db_models import Listing
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    rows = (
        db.query(Application, Listing)
        .join(Listing, Application.listing_id == Listing.id)
        .filter(Application.user_id == user_id, Application.status != "undone")
        .all()
    )
 
    def norm(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())
 
    # Group active applications by normalized org, keeping a real
    # display name (the first genuinely-seen spelling) for each.
    by_company = {}
    for app, listing in rows:
        key = norm(listing.org)
        if not key:
            continue
        if key not in by_company:
            by_company[key] = {"org": listing.org, "count": 0}
        by_company[key]["count"] += 1
 
    cautions = [
        {
            "org": info["org"],
            "count": info["count"],
            "note": f"You already have {info['count']} active applications to {info['org']}. Applying to several roles at one company can read as unfocused in their applicant system - it's often stronger to concentrate on the single best fit here.",
        }
        for info in by_company.values()
        if info["count"] >= SAME_COMPANY_CAUTION_THRESHOLD
    ]
    return {"cautions": cautions}
 
