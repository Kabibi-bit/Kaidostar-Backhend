import os
from fastapi import APIRouter, Depends, HTTPException
from app.services.auth import require_auth_for_user
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import User
 
router = APIRouter(prefix="/users", tags=["users"])
 
VALID_ROLES = {"candidate"}
 
# Self-serve tier switching exists ONLY so tiers are testable before billing is
# wired. Left open in production it is a genuine "upgrade yourself to Max for free"
# hole, so it is gated: enabled by default (local/demo testing and the in-app tier
# switcher keep working unchanged), but set ALLOW_SELF_SERVE_TIER=false in the
# production environment to lock it. When real billing lands, tier changes should
# flow from verified subscription webhooks and this setter should be removed.
_SELF_SERVE_TIER_ENABLED = os.getenv("ALLOW_SELF_SERVE_TIER", "true").strip().lower() in ("1", "true", "yes")
 
# POST /users creates a bare, password-less demo record with no authentication
# (see the note on create_user). It's genuinely useful for local/demo testing,
# but left open in production it's an unauthenticated, unbounded row-creation
# (spam/abuse) endpoint. Gated the same way as self-serve tiers: enabled by
# default so testing is unchanged, but set ALLOW_PUBLIC_USER_CREATE=false in the
# production environment - real accounts go through /auth/signup regardless.
_PUBLIC_USER_CREATE_ENABLED = os.getenv("ALLOW_PUBLIC_USER_CREATE", "true").strip().lower() in ("1", "true", "yes")
 
 
class UserIn(BaseModel):
    email: EmailStr
    role: str = "candidate"
 
 
@router.post("")
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    # NOTE: intentionally public and unauthenticated. This is a bare,
    # password-less user record used for demo/testing only; real
    # account creation goes through /auth/signup (which hashes a
    # password and issues a token). Kept public because there is no
    # token to check before an account exists - and gated by env so it
    # can be turned off entirely in production (see the flag above).
    if not _PUBLIC_USER_CREATE_ENABLED:
        raise HTTPException(status_code=403, detail="Public user creation is disabled - sign up via /auth/signup.")
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {VALID_ROLES}")
 
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        return {"user_id": str(existing.id), "status": "already exists", "role": existing.role}
 
    user = User(email=payload.email, role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": str(user.id), "status": "created", "role": user.role}
 
 
@router.get("/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": str(user.id), "email": user.email, "role": user.role}
 
 
# --- Subscription tier (no payment yet; set via this endpoint for testing) ---
from app.services.tiers import normalize_tier, get_user_tier, TIER_FEATURES  # noqa: E402
from pydantic import BaseModel as _BaseModel  # noqa: E402
 
 
class _SetTierIn(_BaseModel):
    tier: str
 
 
@router.get("/{user_id}/tier")
def get_tier(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The user's current tier, its feature flags, the overall daily AI budget,
    and per-feature usage-vs-cap for today - so the client (e.g. the Plan page)
    can show real usage honestly instead of guessing."""
    t = get_user_tier(db, user_id)
    from app.services.tiers import daily_limit, feature_daily_cap
    from app.services.rate_limit import ai_budget_used_today, usage_today
    cap = daily_limit(t)
    used = ai_budget_used_today(db, user_id)
    # Per-feature usage today, keyed by the labels the Plan page displays.
    # (display label -> the rate-limit action name it counts against)
    _feature_actions = {
        "roadmaps": "roadmap-generate",
        "essay reviews": "essay-polish",
        "match explanations": "deep-explain",
    }
    features_usage = {}
    for label, action in _feature_actions.items():
        fcap = feature_daily_cap(t, action)
        features_usage[label] = {
            "used_today": usage_today(db, user_id, action),
            "limit": fcap,
            "unlimited": fcap >= 1000,
        }
    return {
        "tier": t,
        "features": TIER_FEATURES[t],
        "ai_budget": {"used_today": used, "limit": cap, "unlimited": cap >= 1000},
        "feature_usage": features_usage,
    }
 
 
@router.post("/{user_id}/tier")
def set_tier(user_id: str, payload: _SetTierIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Set the user's tier. Gated by ALLOW_SELF_SERVE_TIER (default on for testing;
    turn OFF in production). When billing is added, tier changes should flow from
    verified subscription events (a webhook), not this open setter."""
    if not _SELF_SERVE_TIER_ENABLED:
        raise HTTPException(status_code=403, detail="Tier changes are managed through billing.")
    from sqlalchemy import text
    t = normalize_tier(payload.tier)
    db.execute(text("UPDATE users SET tier = :t WHERE id = :uid"), {"t": t, "uid": str(user_id)})
    db.commit()
    return {"tier": t, "features": TIER_FEATURES[t]}
 
