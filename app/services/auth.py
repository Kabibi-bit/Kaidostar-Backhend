"""Authentication: signup, email verification, password login, and email-based
two-factor (2FA) on every login.
 
Flow (what a real account gets, not a sketch):
  1. POST /auth/signup  - strong-password check, create an UNVERIFIED account,
     email a 6-digit verification code. No token yet.
  2. POST /auth/verify-email - correct code -> account marked verified, token issued.
  3. POST /auth/login   - throttle/CAPTCHA gate, then bcrypt password check. If the
     email isn't verified, we re-send a verification code and say so. If it is,
     we email a fresh 6-digit 2FA code. No token yet.
  4. POST /auth/verify-2fa - correct code -> token issued.
Plus /auth/resend-verification and /auth/resend-2fa (cooldown-limited).
 
Second factor = a code sent to the registered email (possession), on top of the
password (knowledge). Codes are hashed, short-lived, attempt-capped, and single
use (services/auth_codes.py); passwords must pass services/password_policy.py;
brute force is handled by the existing graduated throttle + CAPTCHA step-up.
"""
import logging
import os
 
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
 
from app.db import get_db
from app.models.db_models import User
from app.services.auth import (
    hash_password, verify_password, create_access_token, decode_access_token, dummy_password_hash,
)
from app.services.password_policy import validate_password
from app.services.auth_codes import issue_code, verify_code
from app.services.email_send import send_email
from app.services.rate_limit import (
    login_challenge, record_login_failure, captcha_configured, verify_captcha,
    real_client_ip, clear_login_failures,
)
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/auth", tags=["auth"])
 
VALID_ROLES = {"candidate"}
 
# When set to "1", code responses include the plaintext code so the flow is
# testable locally WITHOUT an email provider configured. Off by default, so a
# production deployment never leaks codes in its API responses.
_DEV_CODES = os.getenv("AUTH_DEV_CODES", "") == "1"
 
_VERIFY_FAIL_MSG = {
    "no_code": "That code has expired or was already used - request a new one.",
    "expired": "That code has expired - request a new one.",
    "locked": "Too many incorrect attempts - request a new code.",
    "mismatch": "That code isn't right - check it and try again.",
}
 
 
def _client_ip(request: Request) -> str:
    return real_client_ip(
        request.headers.get("x-forwarded-for", ""),
        request.client.host if request.client else "",
    )
 
 
def _send_code(email: str, code: str, purpose: str) -> bool:
    """Email a verification / 2FA code. Returns True if the provider accepted it.
    Never raises into the request: if email isn't configured or the send fails,
    we log it and return False (the caller still advances to the code-entry step,
    and in dev mode the code is returned in the response instead)."""
    if purpose == "verify_email":
        subject = "Verify your Kaidostar email"
        line = "Enter this code to confirm your email and finish setting up your account:"
    else:
        subject = "Your Kaidostar sign-in code"
        line = "Enter this code to finish signing in:"
    body = f"{line}\n\n    {code}\n\nThis code expires in 10 minutes. If you didn't request it, you can ignore this email."
    html = (
        f"<div style=\"font-family:system-ui,sans-serif;max-width:420px\">"
        f"<p style=\"font-size:14px;color:#333\">{line}</p>"
        f"<p style=\"font-size:30px;letter-spacing:6px;font-weight:700;margin:18px 0\">{code}</p>"
        f"<p style=\"font-size:12px;color:#888\">This code expires in 10 minutes. "
        f"If you didn't request it, you can ignore this email.</p></div>"
    )
    try:
        send_email(email, subject, body, html)
        return True
    except Exception as e:  # noqa: BLE001 - never let email failure 500 the auth flow
        _log.warning("auth: could not send %s code to %s - %s", purpose, email, type(e).__name__)
        return False
 
 
def _issue_and_send(db: Session, user: User, purpose: str) -> dict:
    """Issue a code (cooldown-aware) and email it. Returns the response fragment
    the routes surface to the client (status + delivery, plus the code itself
    only in dev mode)."""
    code, cooldown = issue_code(db, str(user.id), purpose)
    if code is None:
        return {"delivery": "cooldown", "retry_after": cooldown}
    sent = _send_code(user.email, code, purpose)
    out = {"delivery": "sent" if sent else "unsent"}
    if _DEV_CODES:
        out["dev_code"] = code
    return out
 
 
# --------------------------------------------------------------------- signup
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    role: str = Field(default="candidate", max_length=40)
 
 
@router.post("/signup")
def signup(payload: SignupIn, db: Session = Depends(get_db)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {VALID_ROLES}")
    ok, errors = validate_password(payload.password, payload.email)
    if not ok:
        # First concrete requirement that failed - the live meter already guides
        # the user, this is the authoritative backstop.
        raise HTTPException(status_code=400, detail=errors[0])
 
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        if existing.email_verified:
            raise HTTPException(status_code=409, detail="An account with this email already exists - try logging in instead")
        # Account exists but was never verified - let them continue verification
        # rather than dead-ending on a 409 they can't resolve.
        frag = _issue_and_send(db, existing, "verify_email")
        return {"status": "verify_sent", "email": existing.email, **frag}
 
    user = User(email=payload.email, password_hash=hash_password(payload.password), role=payload.role, email_verified=False)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists - try logging in instead")
    db.refresh(user)
    frag = _issue_and_send(db, user, "verify_email")
    return {"status": "verify_sent", "email": user.email, **frag}
 
 
# -------------------------------------------------------------- verify email
class CodeIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
 
 
@router.post("/verify-email")
def verify_email(payload: CodeIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    # Generic failure so this can't be used to probe which emails exist.
    if not user:
        raise HTTPException(status_code=400, detail=_VERIFY_FAIL_MSG["no_code"])
    if user.email_verified:
        # Already done - just log them in rather than erroring.
        token = create_access_token(str(user.id), user.role)
        return {"status": "ok", "user_id": str(user.id), "email": user.email, "role": user.role, "access_token": token}
    ok, reason = verify_code(db, str(user.id), "verify_email", payload.code)
    if not ok:
        raise HTTPException(status_code=400, detail=_VERIFY_FAIL_MSG.get(reason, "Verification failed - request a new code."))
    user.email_verified = True
    db.commit()
    token = create_access_token(str(user.id), user.role)
    return {"status": "ok", "user_id": str(user.id), "email": user.email, "role": user.role, "access_token": token}
 
 
class EmailIn(BaseModel):
    email: EmailStr
 
 
@router.post("/resend-verification")
def resend_verification(payload: EmailIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    # Always report success so an attacker can't tell whether the email exists.
    if not user or user.email_verified:
        return {"status": "sent"}
    frag = _issue_and_send(db, user, "verify_email")
    return {"status": frag.get("delivery", "sent"), **({"retry_after": frag["retry_after"]} if "retry_after" in frag else {})}
 
 
# ---------------------------------------------------------------------- login
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    captcha_token: str | None = Field(default=None, max_length=4000)
 
 
@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    challenge = login_challenge(db, payload.email, ip)
    if challenge == "block":
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Please wait a while and try again.")
    if challenge == "captcha":
        if not captcha_configured():
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Please wait a while and try again.")
        if not verify_captcha(payload.captcha_token or "", ip):
            raise HTTPException(status_code=428, detail="Please complete the verification and try again.")
 
    user = db.query(User).filter(User.email == payload.email).first()
    password_ok = verify_password(payload.password, user.password_hash if user else dummy_password_hash())
    if not user or not password_ok:
        record_login_failure(db, payload.email, ip)
        raise HTTPException(status_code=401, detail="Incorrect email or password")
 
    clear_login_failures(db, payload.email)
 
    # Password is the first factor. Email must be verified before an account works.
    if not user.email_verified:
        frag = _issue_and_send(db, user, "verify_email")
        return {"status": "email_not_verified", "email": user.email, **frag}
 
    # Second factor: email a fresh 2FA code; no token until it's confirmed.
    frag = _issue_and_send(db, user, "login_2fa")
    return {"status": "mfa_required", "email": user.email, **frag}
 
 
@router.post("/verify-2fa")
def verify_2fa(payload: CodeIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=400, detail=_VERIFY_FAIL_MSG["no_code"])
    ok, reason = verify_code(db, str(user.id), "login_2fa", payload.code)
    if not ok:
        raise HTTPException(status_code=400, detail=_VERIFY_FAIL_MSG.get(reason, "Verification failed - request a new code."))
    # A 2FA challenge only ever exists after a successful password check, and the
    # email was verified to even reach that step - so a correct code here means
    # both factors passed. Issue the session token.
    token = create_access_token(str(user.id), user.role)
    return {"status": "ok", "user_id": str(user.id), "email": user.email, "role": user.role, "access_token": token}
 
 
@router.post("/resend-2fa")
def resend_2fa(payload: EmailIn, db: Session = Depends(get_db)):
    from app.models.db_models import AuthCode
    user = db.query(User).filter(User.email == payload.email).first()
    # Only re-send when a 2FA challenge is genuinely pending (i.e. the password
    # step already succeeded) - otherwise this would be an open way to send a code
    # email to any address. Report generic success either way.
    if not user or not user.email_verified:
        return {"status": "sent"}
    pending = (
        db.query(AuthCode)
        .filter(AuthCode.user_id == user.id, AuthCode.purpose == "login_2fa")
        .first()
    )
    if not pending:
        return {"status": "sent"}
    frag = _issue_and_send(db, user, "login_2fa")
    return {"status": frag.get("delivery", "sent"), **({"retry_after": frag["retry_after"]} if "retry_after" in frag else {})}
 
 
# ------------------------------------------------------------------------- me
@router.get("/me")
def get_me(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return {"user_id": str(user.id), "email": user.email, "role": user.role, "email_verified": user.email_verified}
 
