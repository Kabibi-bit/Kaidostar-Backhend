"""Real authentication: bcrypt password hashing (never stores or
compares plain-text passwords) and JWT session tokens.
 
Honest scope note: this file, plus the /auth routes built on it, is
a genuinely working login/signup system, and its checks are now
applied across the app - not aspirational. Two enforced patterns:
 
  - require_auth_for_user: the dependency for a route whose own URL
    path carries {user_id}. Every such route uses it (or calls
    verify_token_belongs_to_user directly), so the path user_id is
    always checked against the caller's token - a token can only act
    on its own user's data.
  - verify_token_belongs_to_user(resource.user_id, ...): for a route
    keyed on some OTHER resource's id (an application, outreach,
    post, milestone, etc.), the resource is loaded first and this is
    called with its real owning user_id, so one user can't touch
    another user's resource by guessing its id (no IDOR).
 
The deliberately public, no-token routes are limited to: /auth/signup,
/auth/login, /auth/me (self-scoped - reads only the token's own user),
POST /users (a password-less demo record that can never obtain a token,
so it reaches no protected data), /schools/* (public reference data),
and /engagement/accept/{token} (a cryptographically-random, single-use
capability token IS the authorization). require_valid_token guards the
one authenticated-but-not-owned case (listing leadership research).
 
Keep this note accurate: it is read as the app's security posture. If
a new route is added, wire the matching check above rather than
trusting a URL user_id.
"""
import os
from app.services.timeutil import utcnow
from fastapi import HTTPException, Header
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
 
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
# Auth-token lifetime. Was 14 days, which is a long exposure window if a token
# leaks. Shortened to 3 days by default - a meaningful security improvement that
# still avoids forcing users to log in constantly. Override with JWT_EXPIRY_HOURS
# in the environment (e.g. tune up for convenience, down for stricter security).
try:
    JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", str(24 * 3)))
except (ValueError, TypeError):
    JWT_EXPIRY_HOURS = 24 * 3
 
 
def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        # bcrypt's real, underlying limit is 72 BYTES, not characters -
        # a fundamental property of the algorithm itself (its key
        # schedule only processes the first 72 bytes of input), not a
        # library quirk. Without this explicit check, two genuinely
        # different passwords sharing the same first 72 bytes would
        # hash identically - a real, silent risk this raises loudly
        # against instead, regardless of how the installed bcrypt
        # version itself handles an over-length input.
        raise ValueError("Password is too long (max 72 bytes once UTF-8 encoded)")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")
 
 
def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        # Mirrors the identical guard in hash_password - a password
        # over the real 72-byte limit could never have been the one
        # genuinely hashed in the first place, so this is honestly a
        # non-match, not a case worth passing through to bcrypt itself.
        return False
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))
    except ValueError:
        return False
    except Exception:
        # Safety net mirroring decode_access_token in this same file: a
        # security-critical credential check must treat any unexpected error
        # (e.g. a bcrypt version raising a non-ValueError on a malformed stored
        # hash) as an honest non-match, never a raw unhandled 500 at the login gate.
        return False
 
 
_DUMMY_PASSWORD_HASH = None
 
 
def dummy_password_hash() -> str:
    """A real, valid bcrypt hash to verify a submitted password against when NO
    user matches the login email, so an attempt for a nonexistent address costs
    the same ~time as a wrong password for a real one.
 
    Without this, login() short-circuits (`not user or not verify_password(...)`)
    before ever calling bcrypt for an unknown email, so that path returns
    measurably faster than the wrong-password path (~250ms of bcrypt) - a real
    timing side-channel that lets an attacker enumerate which emails have
    accounts, quietly defeating the deliberately-generic "Incorrect email or
    password" message. Computed once, lazily, so module import stays cheap and
    doesn't depend on bcrypt at import time."""
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = hash_password("kaidostar-constant-time-dummy-credential")
    return _DUMMY_PASSWORD_HASH
 
 
def create_access_token(user_id: str, role: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set - generate a long random string and add it to "
            "your Render environment variables before using auth in production."
        )
    payload = {
        "sub": user_id,
        "role": role,
        "exp": utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
 
 
def decode_access_token(token: str) -> dict | None:
    if not JWT_SECRET:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        # A genuine, final safety net - the two specific exception
        # types above cover the real, documented pyjwt failure modes,
        # but a security-critical token-decode path should never let
        # an unexpected exception type propagate as a raw, unhandled
        # error instead of an honest "invalid token" rejection.
        return None
 
 
def verify_token_belongs_to_user(user_id: str, authorization: str | None) -> dict:
    """The real, shared verification core: a valid, non-expired token
    whose own sub claim genuinely matches the given user_id. Used
    both directly (when a route already has user_id from its own URL
    path) and indirectly (when a route only has some other resource's
    id, and the caller looks up that resource's real owning user_id
    first before calling this)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("sub") != user_id:
        raise HTTPException(status_code=403, detail="This token does not belong to the requested user")
    return payload
 
 
def require_auth_for_user(user_id: str, authorization: str = Header(None)) -> dict:
    """A real, reusable FastAPI dependency for the common case: a
    route whose own URL path already has user_id. Not usable as-is
    for a route that only has some other resource's id (e.g. a
    post_id) - that case needs the resource's real owner looked up
    first, then verify_token_belongs_to_user called directly with
    that real owner's id (see e.g. social.py's edit_post/delete_post).
    """
    return verify_token_belongs_to_user(user_id, authorization)
 
 
def require_valid_token(authorization: str = Header(None)) -> dict:
    """A real, reusable dependency for endpoints whose data isn't
    owned by a specific user (e.g. a public company's leadership
    research derived from a listing) but which should still require a
    genuinely logged-in caller - so an expensive AI/web-search call
    can't be hit anonymously. Enforces a valid, non-expired token
    only; deliberately no ownership check, since there is no owning
    user to check against."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload
 
