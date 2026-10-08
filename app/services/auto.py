"""Auto - the endpoints behind the Auto page.
 
GET  /auto/{user_id}/state     everything the page shows: settings (normalized), the candidate jobs the
                               server would plan on (the page runs the identical planner on them, so its
                               preview is exactly what Auto will do), the person's context, their Auto
                               applications with each one's package and proof, the answer bank, the
                               run log and what this server can and can't do.
PUT  /auto/{user_id}/settings  turn Auto on/off and save its rules (normalized and bounded here).
PUT  /auto/{user_id}/answers   save the answer bank.
POST /auto/{user_id}/run       run a pass now ("Run now").
POST /auto/{user_id}/approve   approve prepared applications (each still gets the undo window).
POST /auto/{user_id}/skip      discard prepared applications that haven't gone out.
"""
import json
import uuid as uuid_module
 
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.services.auth import require_auth_for_user
from app.services.rate_limit import rate_limit
from app.services.tiers import require_feature
 
router = APIRouter(prefix="/auto", tags=["auto"])
 
APPS_SHOWN = 300
 
 
def _uuid(user_id):
    try:
        uuid_module.UUID(str(user_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
 
def _current_profile(db, user_id):
    from app.models.db_models import Profile
    p = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    if p is None:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    return p
 
 
def _job_search_prefill(db, user_id) -> dict:
    """What the Job Search settings already say (sponsorship, citizenship) - offered as suggestions
    for the answer bank, never filled in without the person saying so."""
    try:
        from app.services.job_search import load_state
        prefs = (load_state(db, user_id) or {}).get("prefs") or {}
        out = {}
        if prefs.get("needsSponsorship") is True:
            out["sponsorship"] = "yes"
        if prefs.get("citizen") is True:
            out["citizen"] = "yes"
        elif prefs.get("citizen") is False:
            out["citizen"] = "no"
        return out
    except Exception:
        db.rollback()
        return {}
 
 
def apps_payload(db, user_id) -> list:
    """The person's applications (newest first) with each Auto one's package: what it contains, why it
    was chosen, what it still needs, every delivery attempt and the proof of a send."""
    from app.models.db_models import Application, Listing, Outcome
    from app.services import auto_runner as AR
    rows = (db.query(Application, Listing).join(Listing, Application.listing_id == Listing.id)
            .filter(Application.user_id == user_id).order_by(Application.created_at.desc()).limit(APPS_SHOWN).all())
    outcomes = {}
    for o in db.query(Outcome).filter(Outcome.user_id == user_id).order_by(Outcome.updated_at.asc()).all():
        outcomes[str(o.listing_id)] = o.status
    pk = AR.packages_for(db, user_id)
 
    def iso(d):
        d = AR.to_naive_utc(d)
        return d.isoformat() + "Z" if d is not None else None
    out = []
    for a, l in rows:
        out.append({
            "id": str(a.id), "listing_id": str(a.listing_id), "listing_title": l.title, "listing_org": l.org,
            "status": a.status, "confidence_pct": float(a.confidence_pct) if a.confidence_pct is not None else None,
            "draft": a.draft_content or "", "flagged": list(a.draft_flagged_terms or []),
            "created_at": iso(a.created_at), "sendable_at": iso(a.sendable_at), "sent_at": iso(a.sent_at),
            "sent_channel": a.sent_channel, "sent_to_address": a.sent_to_address, "apply_url": l.apply_url,
            "apply_route": _route_of(AR, l.apply_url),
            "auto_generated": bool(a.auto_generated), "outcome_status": outcomes.get(str(a.listing_id)),
            "package": pk.get(str(a.id)),
        })
    return out
 
 
def _route_of(AR, url):
    try:
        return AR.route_of(url)[0]
    except Exception:
        return None
 
 
@router.get("/{user_id}/state")
def get_state(user_id: str, refresh: bool = False, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    _uuid(user_id)
    from app.services import auto_answers as AA
    from app.services import auto_engine as AE
    from app.services import auto_runner as AR
    from app.services.tiers import get_user_tier
    profile = _current_profile(db, user_id)
    tier = get_user_tier(db, user_id)
    tmax = AR.tier_daily_max(tier)
    rules = AR.rules_of(profile)
    bank = AR.load_answers(db, user_id)
    st = AR.load_state(db, user_id)
    cands, at, note = [], None, None
    if getattr(profile, "is_athlete", False):
        note = "Auto applies to jobs from your Job Search matches - athlete programs aren't covered here."
    elif tmax <= 0:
        note = "Auto is part of Pro and Max."
    else:
        if refresh:
            rate_limit(db, user_id, "auto-refresh", limit_per_day=60)
        try:
            cands, at = AR.candidates_for(db, user_id, profile, fresh=bool(refresh))
        except Exception:
            db.rollback()
            note = "Your matches couldn't be loaded just now - the preview will fill in on the next try."
    ctx = AR.build_ctx(db, user_id, profile, rules, tier, bank=bank, state=st)
    ctx["taken"] = {}   # the candidates already leave out every job you have an application for
    last = st.get("lastRunAt")
    return {
        "enabled": bool(getattr(profile, "auto_apply_enabled", False)), "rules": rules, "threshold": rules["minFit"],
        "tier": tier, "tierMax": tmax, "consent": bool(getattr(profile, "auto_submit_consent", False)),
        "candidates": cands, "candidatesAt": at, "note": note, "ctx": ctx,
        "apps": apps_payload(db, user_id), "answers": bank, "coverage": AA.coverage(bank),
        "prefill": _job_search_prefill(db, user_id),
        "state": {"lastRunAt": last, "runs": (st.get("runs") or [])[-10:], "lastError": st.get("lastError"),
                  "extensionSeenAt": st.get("extensionSeenAt")},
        "server": {"browserAvailable": ctx["browserAvailable"], "emailReady": ctx["emailReady"],
                   "tickMinutes": AR.TICK_MINUTES, "passHours": AR.PASS_HOURS,
                   "nextPassAt": (last + AR.PASS_HOURS * 3600 * 1000) if last else None},
        "engineVersion": AE.VERSION, "now": ctx["now"],
    }
 
 
class SettingsIn(BaseModel):
    enabled: bool
    rules: dict = Field(default_factory=dict)
 
 
@router.put("/{user_id}/settings")
def put_settings(user_id: str, payload: SettingsIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    _uuid(user_id)
    if payload.enabled:
        require_feature(db, user_id, "auto_mode")   # turning Auto OFF is always allowed (a plan that lapsed included)
    from app.services import auto_engine as AE
    from app.services import auto_runner as AR
    try:
        if len(json.dumps(payload.rules)) > 20000:
            raise HTTPException(status_code=400, detail="Those settings are too large.")
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Those settings aren't valid.")
    profile = _current_profile(db, user_id)
    rules = AE.norm_rules(payload.rules if isinstance(payload.rules, dict) and payload.rules else {"v": 2}, profile.auto_apply_threshold)
    note = None
    if rules["delayMinutes"] == 0 and not getattr(profile, "auto_submit_consent", False):
        rules["delayMinutes"] = 30
        note = "Sending with no delay needs your permission for Kaidostar to submit for you - kept a 30-minute undo window."
    profile.auto_apply_enabled = bool(payload.enabled)
    profile.auto_apply_threshold = rules["minFit"]
    profile.auto_apply_rules = rules
    db.commit()
    AR.invalidate(user_id)
    return {"enabled": profile.auto_apply_enabled, "rules": rules, "threshold": rules["minFit"], "note": note}
 
 
class AnswersIn(BaseModel):
    answers: dict = Field(default_factory=dict)
 
 
@router.put("/{user_id}/answers")
def put_answers(user_id: str, payload: AnswersIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    _uuid(user_id)
    from app.services import auto_answers as AA
    from app.services import auto_runner as AR
    try:
        if len(json.dumps(payload.answers)) > 30000:
            raise HTTPException(status_code=400, detail="Those answers are too long.")
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Those answers aren't valid.")
    bank = AR.save_answers(db, user_id, payload.answers)
    db.commit()
    AR.invalidate(user_id)
    return {"answers": bank, "coverage": AA.coverage(bank)}
 
 
@router.post("/{user_id}/run")
def run_now(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    _uuid(user_id)
    require_feature(db, user_id, "auto_mode")
    rate_limit(db, user_id, "auto-run", limit_per_day=12)
    from app.services import auto_runner as AR
    from app.services.ai_client import get_client
    profile = _current_profile(db, user_id)
    if not getattr(profile, "auto_apply_enabled", False):
        raise HTTPException(status_code=400, detail="Turn Auto on first.")
    res = AR.run_pass(db, get_client(), user_id, reason="manual")
    if res.get("skipped") == "busy":
        raise HTTPException(status_code=409, detail="Auto is already running for you - give it a minute.")
    if res.get("error"):
        raise HTTPException(status_code=502, detail="Auto couldn't finish this run - try again in a few minutes.")
    return res
 
 
class IdsIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=100)
 
 
def _own_apps(db, user_id, ids):
    from app.models.db_models import Application
    good = []
    for i in (ids or [])[:100]:
        try:
            good.append(str(uuid_module.UUID(str(i))))
        except ValueError:
            continue
    if not good:
        return []
    return db.query(Application).filter(Application.user_id == user_id, Application.id.in_(good)).all()
 
 
@router.post("/{user_id}/approve")
def approve(user_id: str, payload: IdsIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Approve prepared applications you've reviewed. Each goes out on your own timing - your undo
    window, weekdays-only if you chose it, and any referral hold its card showed."""
    _uuid(user_id)
    from app.services import auto_runner as AR
    rules = AR.rules_of(_current_profile(db, user_id))
    now = AR.utcnow()
    n, first = 0, None
    for a in _own_apps(db, user_id, payload.ids):
        if a.status != "pending_review":
            continue
        h = (AR.load_package(db, user_id, a.id) or {}).get("hold")
        hold = (h.get("days") or 0) if isinstance(h, dict) else 0
        a.status = "approved"
        a.sendable_at = AR.send_time(now, rules, hold)
        AR.note_person_approved(db, a, a.sendable_at)
        first = a.sendable_at if first is None or a.sendable_at < first else first
        n += 1
    db.commit()
    AR.invalidate(user_id)
    return {"approved": n, "firstSendAt": AR._ms(first) if first is not None else None}
 
 
@router.post("/{user_id}/skip")
def skip(user_id: str, payload: IdsIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Discard prepared applications that haven't gone out. Auto never takes those jobs again."""
    _uuid(user_id)
    from app.services import auto_runner as AR
    n = 0
    for a in _own_apps(db, user_id, payload.ids):
        if a.status not in ("pending_review", "approved", "ready_to_submit"):
            continue
        a.status = "undone"
        n += 1
    db.commit()
    AR.invalidate(user_id)
    return {"skipped": n}
 
