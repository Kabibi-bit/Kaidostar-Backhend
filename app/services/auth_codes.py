"""One-time codes for email verification and login 2FA.
 
A 6-digit code is emailed to the user; only its hash is stored, with a short
expiry, an attempt ceiling, and a resend cooldown. This backs two flows:
  - verify_email : proves the signup email is really theirs before the account
                   can be used.
  - login_2fa    : a second factor on every login - after the password check, a
                   fresh code is emailed and must be entered to get a token.
 
The hashing / matching / expiry helpers are pure (no DB), so they're unit-
testable and can't accidentally depend on request state. issue_code / verify_code
touch the DB (AuthCode rows), imported lazily so the pure helpers stay importable
with nothing installed.
"""
import hashlib
import hmac
import os
import secrets
 
from app.services.timeutil import utcnow
from datetime import timedelta
 
PURPOSES = ("verify_email", "login_2fa")
CODE_TTL_SECONDS = 600          # 10 minutes
MAX_ATTEMPTS = 5                # wrong guesses before the code is dead
RESEND_COOLDOWN_SECONDS = 45    # min gap between code emails for one user+purpose
 
 
def make_code() -> str:
    """A cryptographically-random 6-digit code (secrets, not random)."""
    return f"{secrets.randbelow(1_000_000):06d}"
 
 
def hash_code(code: str) -> str:
    """SHA-256 of the code, peppered with the server secret so a leaked DB alone
    can't be brute-forced offline without it. Codes are short-lived and attempt-
    capped, so a fast hash is appropriate here (unlike passwords)."""
    pepper = os.getenv("JWT_SECRET_KEY", "")
    return hashlib.sha256((str(code) + "|" + pepper).encode("utf-8")).hexdigest()
 
 
def codes_match(submitted: str, stored_hash: str) -> bool:
    """Constant-time comparison of a submitted code against a stored hash."""
    if not stored_hash:
        return False
    return hmac.compare_digest(hash_code(submitted or ""), stored_hash)
 
 
def is_expired(expires_at, now=None) -> bool:
    if not expires_at:
        return True
    now = now or utcnow()
    try:
        return expires_at < now
    except TypeError:
        # naive/aware mismatch - compare naively as a last resort
        return expires_at.replace(tzinfo=None) < now.replace(tzinfo=None)
 
 
def seconds_since(dt, now=None) -> float:
    now = now or utcnow()
    try:
        return (now - dt).total_seconds()
    except TypeError:
        return (now.replace(tzinfo=None) - dt.replace(tzinfo=None)).total_seconds()
 
 
def issue_code(db, user_id: str, purpose: str):
    """Create a fresh code for (user, purpose), returning (code, cooldown_left).
 
    If the last code was issued within the cooldown, returns (None, seconds_left)
    and does NOT issue a new one - so a 'resend' button can't be used to spam the
    user's inbox. Otherwise the previous codes are cleared and one new code is
    stored (hashed); the plaintext is returned once, for the caller to email.
    """
    from app.models.db_models import AuthCode
    assert purpose in PURPOSES
    latest = (
        db.query(AuthCode)
        .filter(AuthCode.user_id == user_id, AuthCode.purpose == purpose)
        .order_by(AuthCode.created_at.desc())
        .first()
    )
    if latest is not None:
        left = RESEND_COOLDOWN_SECONDS - seconds_since(latest.created_at)
        if left > 0:
            return (None, int(left) + 1)
    # clear any prior codes for this purpose, then issue one
    db.query(AuthCode).filter(AuthCode.user_id == user_id, AuthCode.purpose == purpose).delete()
    code = make_code()
    row = AuthCode(
        user_id=user_id,
        purpose=purpose,
        code_hash=hash_code(code),
        expires_at=utcnow() + timedelta(seconds=CODE_TTL_SECONDS),
        attempts=0,
    )
    db.add(row)
    db.commit()
    return (code, 0)
 
 
def verify_code(db, user_id: str, purpose: str, submitted: str):
    """Check a submitted code. Returns (ok, reason) where reason is one of
    'ok' | 'no_code' | 'expired' | 'locked' | 'mismatch'. A correct code is
    single-use (deleted on success); a wrong one burns one of MAX_ATTEMPTS."""
    from app.models.db_models import AuthCode
    row = (
        db.query(AuthCode)
        .filter(AuthCode.user_id == user_id, AuthCode.purpose == purpose)
        .order_by(AuthCode.created_at.desc())
        .first()
    )
    if row is None:
        return (False, "no_code")
    if is_expired(row.expires_at):
        db.query(AuthCode).filter(AuthCode.user_id == user_id, AuthCode.purpose == purpose).delete()
        db.commit()
        return (False, "expired")
    if (row.attempts or 0) >= MAX_ATTEMPTS:
        return (False, "locked")
    if codes_match(submitted, row.code_hash):
        db.query(AuthCode).filter(AuthCode.user_id == user_id, AuthCode.purpose == purpose).delete()
        db.commit()
        return (True, "ok")
    row.attempts = (row.attempts or 0) + 1
    db.commit()
    return (False, "mismatch")
 
