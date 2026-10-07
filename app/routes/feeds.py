"""Employer career-site feeds: the crawl trigger and the public coverage numbers.
 
GET  /feeds/coverage   how many live employer jobs Kaidostar holds, from how many employers,
                       and how many were re-checked in the last day (public; read from a
                       small cached record, never a heavy query)
GET|POST /feeds/tick   start a few minutes of crawling in the background. Needs the
                       FEED_TICK_KEY secret (header X-Feed-Key, or ?key=). On Render's free
                       plan, point a free uptime pinger (e.g. cron-job.org) at
                       /feeds/tick?key=... every 10 minutes: it keeps the service awake and
                       the crawl moving. Unset FEED_TICK_KEY = the endpoint is off.
GET  /feeds/status     the same numbers plus the crawl's own state (key required)
"""
import hmac
import os
 
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
 
from app.db import get_db
 
router = APIRouter(prefix="/feeds", tags=["feeds"])
 
 
def _check_key(key_param, key_header):
    want = os.getenv("FEED_TICK_KEY", "").strip()
    if not want:
        raise HTTPException(status_code=404, detail="Not found")
    got = (key_header or key_param or "").strip()
    if not got or not hmac.compare_digest(got.encode(), want.encode()):
        raise HTTPException(status_code=403, detail="Wrong or missing key")
 
 
@router.get("/coverage")
def coverage(db: Session = Depends(get_db)):
    from app.services.feed_crawler import coverage_cached
    cov = coverage_cached(db)
    if not cov:
        return {"jobs": 0, "employers": 0, "checked_24h": 0, "checked_24h_pct": None, "as_of": None,
                "note": "The employer-feed crawl hasn't run yet."}
    return {k: cov.get(k) for k in ("jobs", "employers", "checked_24h", "checked_24h_pct", "by_source", "as_of")}
 
 
def _tick(key, x_feed_key):
    _check_key(key, x_feed_key)
    from app.services.feed_crawler import start_tick_in_background, enabled
    if not enabled():
        return {"started": False, "reason": "FEEDS_ENABLED is off"}
    started = start_tick_in_background()
    return {"started": started, "detail": "crawling in the background" if started else "a crawl slice is already running"}
 
 
@router.get("/tick")
def tick_get(key: str | None = None, x_feed_key: str | None = Header(default=None)):
    return _tick(key, x_feed_key)
 
 
@router.post("/tick")
def tick_post(key: str | None = None, x_feed_key: str | None = Header(default=None)):
    return _tick(key, x_feed_key)
 
 
@router.get("/status")
def status(key: str | None = None, x_feed_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    _check_key(key, x_feed_key)
    from app.services import feed_crawler as FCR
    out = {"enabled": FCR.enabled(), "coverage": FCR.coverage_cached(db)}
    try:
        out["schema_ready"] = FCR.schema_ready(db)
        if out["schema_ready"]:
            for k in (FCR.STATE_CAP, FCR.STATE_DISCOVERY, FCR.STATE_CC, FCR.STATE_USAJOBS):
                out[k] = FCR.state_get(db, k)
            out["recent_errors"] = [dict(r) for r in FCR._x(db, "SELECT ats, slug, status, fail_count, last_error, last_try_at FROM employer_boards "
                                                                "WHERE last_error IS NOT NULL ORDER BY last_try_at DESC NULLS LAST LIMIT 15").mappings().all()]
    except Exception as e:
        db.rollback()
        out["error"] = type(e).__name__
    return out
 
