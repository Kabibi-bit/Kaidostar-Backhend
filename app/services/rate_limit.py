"""Per-user rate limiting for expensive (AI-backed) endpoints.
 
Why this exists: 15 route files make paid Anthropic calls. Without a limit, a
single user (or a script with one stolen token) could loop those endpoints and
run up a large API bill or exhaust the quota and take the app down for everyone.
 
Design choices, made deliberately:
- **DB-backed, not in-memory.** An in-memory counter resets on every deploy and
  is wrong the moment there's more than one server instance (Render can run
  several). A tiny Postgres table gives a correct, shared, restart-proof count.
  It reuses the same pattern the codebase already uses for external-API quota.
- **Per authenticated user + per action, per rolling day.** Fairer than per-IP
  (which punishes shared networks like a school), and it maps to real cost.
- **Fails OPEN, not closed.** If the limiter itself errors (e.g. a transient DB
  hiccup), it lets the request through rather than breaking the product over a
  bookkeeping problem. A rate limiter should never be a new outage source.
 
Usage in a route:
 
    from app.services.rate_limit import rate_limit
 
    @router.post("/expensive-thing/{user_id}")
    def expensive(user_id: str, db: Session = Depends(get_db),
                  _auth: dict = Depends(require_auth_for_user)):
        rate_limit(db, user_id, "expensive-thing", limit_per_day=40)
        ...
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
 
 
# Sensible daily ceilings per action. Generous enough that a real student never
# notices, low enough that abuse is capped. Tune per endpoint as needed.
DEFAULT_DAILY_LIMIT = 50
 
 
def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
 
 
def rate_limit(db: Session, user_id: str, action: str, limit_per_day: int = DEFAULT_DAILY_LIMIT) -> None:
    """Atomically count one use of `action` by `user_id` today and raise HTTP 429
    if it would exceed `limit_per_day`. Fails open on any internal error.
 
    Uses an upsert with a RETURNING clause so the read-and-increment is a single
    atomic statement (no race between concurrent requests double-spending).
    """
    key_date = _today()
    try:
        # Atomic upsert-and-increment; returns the new running count for today.
        row = db.execute(
            text(
                """
                INSERT INTO user_rate_limits (user_id, action, date, call_count)
                VALUES (:uid, :action, :d, 1)
                ON CONFLICT (user_id, action, date)
                DO UPDATE SET call_count = user_rate_limits.call_count + 1
                RETURNING call_count
                """
            ),
            {"uid": str(user_id), "action": action, "d": key_date},
        ).fetchone()
        db.commit()
    except Exception:
        # Fail OPEN: a limiter malfunction must never break the actual feature.
        db.rollback()
        return
 
    count = row[0] if row else 0
    if count > limit_per_day:
        # 429 = Too Many Requests. Include a clear, honest, non-alarming message.
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've reached today's limit for this feature ({limit_per_day} uses). "
                "This protects the service for everyone - please try again tomorrow."
            ),
        )
 
 
def usage_today(db: Session, user_id: str, action: str) -> int:
    """How many times `user_id` has used `action` today (0 if none/unknown).
    Read-only; fails open by returning 0."""
    try:
        row = db.execute(
            text(
                "SELECT call_count FROM user_rate_limits "
                "WHERE user_id = :uid AND action = :action AND date = :d"
            ),
            {"uid": str(user_id), "action": action, "d": _today()},
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
 
 
# ---------------------------------------------------------------------------
# Tier-aware limiting: a SHARED daily AI budget that differs by plan.
# ---------------------------------------------------------------------------
# The per-action limits above are anti-abuse ceilings on a single feature. This
# adds the plan-level difference users actually feel: a total number of AI
# actions per DAY across ALL AI features - Free 15, Pro 100, Max effectively
# unlimited. Both checks apply; whichever is stricter wins. Same fail-open
# guarantee: a limiter malfunction never blocks the real request.
 
# The shared counter uses a single reserved action name so every AI endpoint
# draws from one daily bucket per user.
_TIER_BUDGET_ACTION = "_ai_daily_budget"
 
 
def rate_limit_by_tier(db: Session, user_id: str, action: str, per_action_limit: int = DEFAULT_DAILY_LIMIT) -> None:
    """Enforce a PER-FEATURE daily cap that scales by tier, plus a tier-wide
    daily AI budget backstop.
 
    - per-feature cap: from tiers.feature_daily_cap(tier, action) - e.g. a Free
      user gets 3 roadmaps/day, Pro 25, Max unlimited. This is the primary,
      prudent limit and it differs by plan.
    - `per_action_limit`: an optional absolute hard ceiling (anti-abuse), applied
      in addition; whichever is stricter wins.
    - tier budget: overall cap across ALL features (a backstop for abnormal use).
 
    Call this at the top of any AI-backed endpoint. Fails OPEN on any internal
    error so a limiter fault never breaks the feature.
    """
    tier = user_id_tier(db, user_id)
 
    # 1. Per-feature, per-tier cap (primary). 1000+ == effectively unlimited.
    try:
        from app.services.tiers import feature_daily_cap
        feat_cap = feature_daily_cap(tier, action)
    except Exception:
        feat_cap = None
    if feat_cap is not None and feat_cap < 1000:
        # the stricter of the tier's feature cap and any absolute ceiling
        effective = min(feat_cap, per_action_limit) if per_action_limit else feat_cap
        rate_limit(db, user_id, action, limit_per_day=effective)
    elif feat_cap is None:
        # unknown feature: fall back to the passed ceiling
        rate_limit(db, user_id, action, limit_per_day=per_action_limit)
    # (feat_cap >= 1000 -> unlimited for this feature at this tier; no per-action cap)
 
    # 2. Tier-wide shared daily budget backstop.
    try:
        from app.services.tiers import daily_limit as _tier_daily_limit
        budget = _tier_daily_limit(tier)
    except Exception:
        return  # fail open
    if budget >= 1000:
        return  # effectively unlimited (Max); skip the shared cap
    # Count one against the shared bucket and block if over the tier budget.
    key_date = _today()
    try:
        row = db.execute(
            text(
                """
                INSERT INTO user_rate_limits (user_id, action, date, call_count)
                VALUES (:uid, :action, :d, 1)
                ON CONFLICT (user_id, action, date)
                DO UPDATE SET call_count = user_rate_limits.call_count + 1
                RETURNING call_count
                """
            ),
            {"uid": str(user_id), "action": _TIER_BUDGET_ACTION, "d": key_date},
        ).fetchone()
        db.commit()
    except Exception:
        db.rollback()
        return  # fail open
    count = row[0] if row else 0
    if count > budget:
        from app.services.tiers import tier_required_for  # noqa: F401 (kept for symmetry)
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've used your plan's {budget} AI actions for today. "
                "Upgrade your plan for a higher daily limit, or try again tomorrow."
            ),
        )
 
 
def user_id_tier(db: Session, user_id: str) -> str:
    """Small indirection so this module doesn't hard-depend on tiers at import
    time (avoids any import cycle). Reads the user's tier, defaulting to free."""
    try:
        from app.services.tiers import get_user_tier
        return get_user_tier(db, user_id)
    except Exception:
        return "free"
 
 
def ai_budget_used_today(db: Session, user_id: str) -> int:
    """How many AI actions the user has spent from today's shared budget."""
    return usage_today(db, user_id, _TIER_BUDGET_ACTION)
 
 
# ---------------------------------------------------------------------------
# Login throttling: GRADUATED brute-force protection for the UNAUTHENTICATED
# /login route - a CAPTCHA step-up first, a hard block only as a far backstop.
# ---------------------------------------------------------------------------
# The per-user limiters above key on an authenticated user_id, which login
# doesn't have yet. This throttles by BOTH the email being attempted and the
# client IP, on a rolling HOUR, in two graduated stages:
#   - after a FEW failures  -> require a solved CAPTCHA before the password is
#     even checked. This is the soft gate: a real person who mistyped just solves
#     a challenge and carries on, while automated guessing is stopped cold.
#   - after MANY failures   -> a hard 429 block, the backstop for a CAPTCHA-
#     solving farm sustaining attempts.
# Per-email caps target one specific account; per-IP caps one source spraying
# many accounts; the strictest stage either key triggers wins. Only genuine
# FAILURES consume budget - a correct password never counts - so a real user is
# never throttled by their own successful logins, and everything resets at the
# top of the next hour. Reuses the existing user_rate_limits table (VARCHAR
# columns, so an email/IP key and an hour-stamped bucket fit with no schema
# change). DB-backed, multi-instance-correct, and FAIL-OPEN: a throttle
# malfunction must never lock everyone out of signing in.
LOGIN_CAPTCHA_AFTER_FAILS_PER_EMAIL = 3
LOGIN_CAPTCHA_AFTER_FAILS_PER_IP = 10
LOGIN_MAX_FAILS_PER_EMAIL_PER_HOUR = 20   # hard-block backstop (was the sole gate)
LOGIN_MAX_FAILS_PER_IP_PER_HOUR = 80      # hard-block backstop
_LOGIN_FAIL_ACTION = "login_fail"
 
 
def _login_bucket() -> str:
    """Hour-granularity window key for the user_rate_limits.date column. A failed
    -attempt count naturally resets at the top of each UTC hour."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
 
 
def _login_keys(email: str, ip: str) -> tuple[str, str]:
    return ("login:email:" + (email or "").strip().lower(), "login:ip:" + ((ip or "").strip() or "unknown"))
 
 
def _rate_limit_count(db: Session, key: str, action: str, bucket: str) -> int:
    row = db.execute(
        text("SELECT call_count FROM user_rate_limits WHERE user_id = :k AND action = :a AND date = :d"),
        {"k": key, "a": action, "d": bucket},
    ).fetchone()
    return int(row[0]) if row else 0
 
 
def login_challenge(db: Session, email: str, ip: str) -> str:
    """The graduated brute-force decision for one login attempt. Returns one of:
      'none'    - allow the attempt normally,
      'captcha' - require a solved CAPTCHA before checking the password (soft
                  step-up: a real user just solves it; a bot is stopped),
      'block'   - hard 429 backstop (too many failures even past the CAPTCHA gate).
    Based on the failed-login counts for THIS email and THIS IP in the current
    hour; the STRICTEST level either key triggers wins. READ-ONLY (only
    record_login_failure consumes budget), so it is safe to call on every attempt
    before verifying the password. FAILS OPEN to 'none' on any internal error - a
    throttle malfunction must never lock everyone out of signing in."""
    bucket = _login_bucket()
    email_key, ip_key = _login_keys(email, ip)
    try:
        email_fails = _rate_limit_count(db, email_key, _LOGIN_FAIL_ACTION, bucket)
        ip_fails = _rate_limit_count(db, ip_key, _LOGIN_FAIL_ACTION, bucket)
    except Exception:
        return "none"  # fail OPEN - a throttle read failure must never block real logins
    if email_fails >= LOGIN_MAX_FAILS_PER_EMAIL_PER_HOUR or ip_fails >= LOGIN_MAX_FAILS_PER_IP_PER_HOUR:
        return "block"
    if email_fails >= LOGIN_CAPTCHA_AFTER_FAILS_PER_EMAIL or ip_fails >= LOGIN_CAPTCHA_AFTER_FAILS_PER_IP:
        return "captcha"
    return "none"
 
 
def captcha_configured() -> bool:
    """True only if a CAPTCHA provider secret is set (CAPTCHA_SECRET_KEY). When
    false, the login route falls back to the hard block at the CAPTCHA threshold
    rather than presenting a challenge it has no way to verify - so security is
    never weakened before a provider is wired up."""
    return bool(os.getenv("CAPTCHA_SECRET_KEY"))
 
 
def verify_captcha(token: str, remote_ip: str = "") -> bool:
    """Verify a CAPTCHA token server-side. Provider-agnostic: Cloudflare
    Turnstile, Google reCAPTCHA and hCaptcha all accept the same
    {secret, response, remoteip} POST and return {"success": bool} - pick one via
    CAPTCHA_VERIFY_URL (defaults to Turnstile). FAILS CLOSED: returns False on a
    missing secret or token, a network/timeout error, a non-2xx, or any body that
    isn't an explicit success - an unverifiable token is never treated as a passed
    challenge. stdlib-only, so no new dependency."""
    secret = os.getenv("CAPTCHA_SECRET_KEY")
    if not secret or not token:
        return False
    verify_url = os.getenv("CAPTCHA_VERIFY_URL", "https://challenges.cloudflare.com/turnstile/v0/siteverify")
    try:
        payload = urllib.parse.urlencode(
            {"secret": secret, "response": token, "remoteip": remote_ip or ""}
        ).encode("utf-8")
        req = urllib.request.Request(verify_url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310 (fixed provider URL, not user input)
            body = json.loads(r.read().decode("utf-8"))
        return bool(isinstance(body, dict) and body.get("success") is True)
    except Exception:
        return False
 
 
def clear_login_failures(db: Session, email: str) -> None:
    """Reset the failed-login counter for an email on a SUCCESSFUL login, so a
    real user who mistyped a few times (and got CAPTCHA-gated) isn't challenged
    again on their very next attempt this hour. Safe: this runs only AFTER a
    correct password, so only the genuine account owner can trigger it - an
    attacker who can't authenticate can never reset their own budget. Clears only
    the per-EMAIL counter; the per-IP counter is left intact so a spray source
    still accumulates toward its own ceiling. Fails open - a cleanup error must
    never turn an otherwise-successful login into a 500."""
    email_key, _ = _login_keys(email, "")
    try:
        db.execute(
            text("DELETE FROM user_rate_limits WHERE user_id = :k AND action = :a AND date = :d"),
            {"k": email_key, "a": _LOGIN_FAIL_ACTION, "d": _login_bucket()},
        )
        db.commit()
    except Exception:
        db.rollback()
 
 
def real_client_ip(x_forwarded_for: str, direct_peer: str) -> str:
    """Resolve the real client IP for throttling, resistant to X-Forwarded-For
    spoofing.
 
    A client can PREPEND arbitrary entries to X-Forwarded-For, but each trusted
    proxy in front of the app APPENDS the address it actually received the request
    from. So the genuine client is counted from the RIGHT, not the left: taking
    the leftmost entry (parts[0]) lets an attacker send a random X-Forwarded-For
    on every request, land in a new per-IP bucket each time, and evade the per-IP
    throttle completely (the per-email limit still catches a targeted attack, but
    the spray defense would be gone).
 
    TRUSTED_PROXY_HOPS (default 1, e.g. Render's load balancer) is how many
    trailing entries were added by infrastructure you control; the entry just
    inside them is the real client. Falls back to the direct socket peer when
    there's no X-Forwarded-For (local/dev)."""
    parts = [p.strip() for p in (x_forwarded_for or "").split(",") if p.strip()]
    if parts:
        try:
            hops = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))
        except (ValueError, TypeError):
            hops = 1
        hops = max(1, hops)
        idx = len(parts) - hops
        if idx < 0:
            idx = 0  # fewer entries than trusted hops -> take the leftmost real one
        return parts[idx]
    return (direct_peer or "").strip() or "unknown"
 
 
def record_login_failure(db: Session, email: str, ip: str) -> None:
    """Atomically count one FAILED login against BOTH the email and the IP for
    the current hour. Called only after a genuine credential failure - a
    successful login never calls this, so real users don't spend the budget.
    Each counter is its own atomic upsert; a failure on one still records the
    other, and any error fails OPEN (a bookkeeping fault must never turn a normal
    failed login into a 500)."""
    bucket = _login_bucket()
    for key in _login_keys(email, ip):
        try:
            db.execute(
                text(
                    """
                    INSERT INTO user_rate_limits (user_id, action, date, call_count)
                    VALUES (:k, :a, :d, 1)
                    ON CONFLICT (user_id, action, date)
                    DO UPDATE SET call_count = user_rate_limits.call_count + 1
                    """
                ),
                {"k": key, "a": _LOGIN_FAIL_ACTION, "d": bucket},
            )
            db.commit()
        except Exception:
            db.rollback()  # fail open; skip this one counter
 
