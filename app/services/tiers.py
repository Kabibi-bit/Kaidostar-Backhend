"""Subscription tiers — the BACKEND source of truth for what Free / Pro / Max grant.
 
Why this exists: gating was frontend-only, which means a Free user was merely
*shown* a locked overlay - the underlying endpoint still ran for anyone with a
token. That makes the tier difference cosmetic, not real. This module lets the
backend actually ENFORCE the tiers, so a paid feature genuinely can't be used
without the tier, regardless of what the client does.
 
Kept deliberately in sync with the frontend TIERS in kaidostar/state.js. A drift
test guards that the feature flags match.
 
No payment yet: a user's tier lives in users.tier (default 'free') and is set
via a switch endpoint for testing. When billing is added, only the SOURCE of the
tier changes (to the verified subscription) - every enforcement point here keeps
working unchanged.
"""
from fastapi import HTTPException
 
TIER_ORDER = ["free", "pro", "max"]
 
# Feature flags per tier. MUST match kaidostar/state.js TIERS[*].features.
TIER_FEATURES = {
    "free": {
        "opportunity_watch": True, "roadmap": False, "metis": True, "manual_drafting": True,
        "school_readiness": True,
        "interview_prep": False,
        "ai_copilot": True,           # Job Search AI Copilot - FREE (whole Job Search page is free)
        "advanced_search": True,      # Personalised weight-tuning - FREE
        "workshop": False,
        "deep_match_explanations": True,  # Deep match explanations live on Job Search - FREE
        "outreach_drafting": False,
        "auto_mode": False,
        "auto_submit": False,
        "priority_metis": False,
        "early_access": False,
    },
    "pro": {
        "opportunity_watch": True, "roadmap": True, "metis": True, "manual_drafting": True,
        "school_readiness": True,
        "interview_prep": True,
        "ai_copilot": True,
        "advanced_search": True,
        "workshop": True,
        "deep_match_explanations": True,
        "outreach_drafting": True,
        "auto_mode": True,
        "auto_submit": True,
        "priority_metis": False,
        "early_access": False,
    },
    "max": {
        "opportunity_watch": True, "roadmap": True, "metis": True, "manual_drafting": True,
        "interview_prep": True,
        "ai_copilot": True,
        "advanced_search": True,
        "workshop": True,
        "school_readiness": True, "deep_match_explanations": True, "outreach_drafting": True,
        "auto_mode": True,
        "auto_submit": True,
        "priority_metis": True,
        "early_access": True,
    },
}
 
# Daily caps. Two layers:
#   1. A per-FEATURE daily cap per tier (the prudent part): a Free user can
#      genuinely try each feature several times a day - enough to get real value
#      and evaluate it - without any single feature running up cost. Pro gets
#      generous working limits; Max is effectively unlimited.
#   2. An overall daily AI budget per tier (a backstop across all features).
#
# Design intent, stated plainly: Free is meant to be USEFUL, not a locked
# teaser. The free caps below let someone actually run a small real search
# (a few roadmaps, several match explanations, a handful of essay reviews a day)
# - they just can't operate at power-user volume. 1000 == "effectively unlimited".
FEATURE_DAILY_CAPS = {
    # feature/action key ->  {free, pro, max}
    "roadmap-generate":   {"free": 3,  "pro": 25,  "max": 1000},
    "roadmap-explain":    {"free": 8,  "pro": 80,  "max": 1000},
    "strategy-position":  {"free": 3,  "pro": 30,  "max": 1000},
    "career-explain":     {"free": 8,  "pro": 60,  "max": 1000},
    "resume-generate":    {"free": 3,  "pro": 25,  "max": 1000},
    "essay-polish":       {"free": 5,  "pro": 50,  "max": 1000},
    "essay-brainstorm":   {"free": 5,  "pro": 50,  "max": 1000},
    "outreach-draft":     {"free": 0,  "pro": 40,  "max": 1000},  # 0 = gated (Pro+ feature)
    "deep-explain":       {"free": 8,  "pro": 80,  "max": 1000},  # Job Search deep match explanations - FREE (generous free allowance)
    # Free features, but AI-costly - metered so Free can't run unlimited cost.
    # Generous free allowances since these are part of the free experience.
    "metis-chat":         {"free": 25, "pro": 200, "max": 1000},
    "company-research":   {"free": 8,  "pro": 60,  "max": 1000},
    "interview-prep":     {"free": 5,  "pro": 50,  "max": 1000},
    # Interview Studio (Interview Prep page - a Pro feature, so Free is 0 = gated).
    # A spoken Hot Seat session is ~1 plan + 1 judged turn per answer (+ follow-ups) + 1 verdict.
    "interview-plan":     {"free": 0,  "pro": 40,  "max": 1000},
    "interview-turn":     {"free": 0,  "pro": 200, "max": 1000},
    "interview-verdict":  {"free": 0,  "pro": 40,  "max": 1000},
    "interview-coach":    {"free": 0,  "pro": 120, "max": 1000},
    "application-draft":  {"free": 8,  "pro": 60,  "max": 1000},
    "application-autosubmit": {"free": 0, "pro": 40, "max": 1000},  # 0 = gated (Pro+ feature): real browser auto-submission
    "explain-outcome":    {"free": 10, "pro": 80,  "max": 1000},
    "engagement-draft":   {"free": 8,  "pro": 60,  "max": 1000},
    "athlete-content":    {"free": 8,  "pro": 60,  "max": 1000},
    "athlete-roadmap":    {"free": 3,  "pro": 25,  "max": 1000},
    "highlight-detection":{"free": 2,  "pro": 15,  "max": 100},  # video analysis: expensive, capped low
}
 
# Overall daily AI budget across ALL features (a backstop, not the primary cap).
# Kept comfortably above the sum a normal Free user would reach via per-feature
# caps, so it only catches genuinely abnormal usage.
TIER_LIMITS = {
    "free": {"ai_actions_per_day": 10, "auto_drafts_per_day": 0},
    "pro": {"ai_actions_per_day": 250, "auto_drafts_per_day": 10},
    "max": {"ai_actions_per_day": 5000, "auto_drafts_per_day": 5000},
}
 
 
def feature_daily_cap(tier, feature_key: str) -> int:
    """The per-day cap for a specific feature at this tier. Unknown feature ->
    a safe default from the overall budget (so a new AI endpoint is bounded even
    before it's listed here). 1000+ means effectively unlimited."""
    caps = FEATURE_DAILY_CAPS.get(feature_key)
    t = normalize_tier(tier)
    if caps is None:
        return daily_limit(t)  # fall back to the overall budget
    return caps.get(t, 0)
 
 
def normalize_tier(tier) -> str:
    """Coerce any stored/blank/invalid value to a valid tier. Defaults to free
    (fail-closed: an unknown tier gets the least, never the most)."""
    t = (tier or "").strip().lower()
    return t if t in TIER_FEATURES else "free"
 
 
def tier_has_feature(tier, feature_key: str) -> bool:
    """True if `tier` includes `feature_key`. Unknown feature -> False
    (fail-closed: a missing flag hides a paid feature, never exposes it)."""
    feats = TIER_FEATURES[normalize_tier(tier)]
    return bool(feats.get(feature_key, False))
 
 
def tier_required_for(feature_key: str):
    """The lowest tier that grants a feature (for upgrade messaging)."""
    for t in TIER_ORDER:
        if TIER_FEATURES[t].get(feature_key):
            return t
    return None
 
 
def daily_limit(tier, key: str = "ai_actions_per_day") -> int:
    return TIER_LIMITS[normalize_tier(tier)].get(key, 0)
 
 
def get_user_tier(db, user_id: str) -> str:
    """Read a user's tier from the DB. Fails closed to 'free' on any error or
    missing column, so enforcement never breaks the app but also never
    accidentally grants a paid tier."""
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT tier FROM users WHERE id = :uid"), {"uid": str(user_id)}
        ).fetchone()
        return normalize_tier(row[0]) if row else "free"
    except Exception:
        return "free"
 
 
def require_feature(db, user_id: str, feature_key: str) -> None:
    """Raise HTTP 403 if the user's tier does not include `feature_key`. This is
    the real enforcement: call it at the top of any paid endpoint. The 403 names
    the tier needed, so the client can prompt an upgrade honestly."""
    if tier_has_feature(get_user_tier(db, user_id), feature_key):
        return
    needed = tier_required_for(feature_key)
    needed_name = {"pro": "Pro", "max": "Max"}.get(needed, "a paid plan")
    raise HTTPException(
        status_code=403,
        detail=f"This feature requires {needed_name}. Upgrade to unlock it.",
    )
 
