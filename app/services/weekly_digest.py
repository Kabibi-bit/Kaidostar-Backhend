"""
Weekly digest: a genuinely useful, honest summary email that gives a user a real
reason to come back - "here's what actually happened on your search this week."
 
Design principles (consistent with the rest of the app):
- HONEST: it summarizes only real, already-computed data (real new matches, real
  saved-listing deadlines). It never manufactures urgency or invents activity. A
  quiet week is reported as a quiet week.
- OPT-OUT respected: skipped if the user muted digests in notification_preferences.
- AT MOST WEEKLY: guarded by a 'digest_sent' Notification record, so even though
  the scan runs often, a user gets at most one digest per 7 days.
- FAIL-SAFE: never raises into the scan. A digest failure for one user must not
  affect the scan or other users.
"""
from datetime import datetime, timedelta, timezone, date
 
 
DIGEST_INTERVAL_DAYS = 7
_STRONG_MATCH_THRESHOLD = 70  # a "strong" new match worth surfacing
 
 
def _naive_utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
 
 
def _already_sent_recently(db, Notification, user_id) -> bool:
    """True if a digest was sent to this user within DIGEST_INTERVAL_DAYS."""
    cutoff = _naive_utcnow() - timedelta(days=DIGEST_INTERVAL_DAYS)
    try:
        recent = (
            db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.type == "weekly_digest")
            .order_by(Notification.created_at.desc())
            .first()
        )
        if recent is None:
            return False
        created = recent.created_at
        if created is None:
            return False
        # created_at may be tz-aware or naive depending on the DB; normalize
        if getattr(created, "tzinfo", None) is not None:
            created = created.replace(tzinfo=None)
        return created > cutoff
    except Exception:
        # If we can't tell, err toward NOT spamming: treat as recently-sent.
        return True
 
 
def _soonest_deadline(db, Listing, SavedListing, user_id, AthleteEvent=None):
    """The nearest upcoming deadline the user has - across their saved listings
    AND (for athletes) their tracked events (tryouts, camps, application
    deadlines). Returns the single soonest, or None."""
    best = None
    today = date.today()
 
    def _consider(title, d):
        nonlocal best
        try:
            dd = date.fromisoformat(d) if isinstance(d, str) else d
            if not isinstance(dd, date):
                return
        except (ValueError, TypeError):
            return
        days = (dd - today).days
        if days < 0:
            return
        if best is None or days < best["days"]:
            best = {"title": title or "a tracked item", "days": days}
 
    # saved listings (all tracks)
    try:
        for s in db.query(SavedListing).filter(SavedListing.user_id == user_id).all():
            listing = db.query(Listing).filter(Listing.id == s.listing_id).first()
            if listing and getattr(listing, "deadline", None):
                _consider(getattr(listing, "title", None), listing.deadline)
    except Exception:
        pass
 
    # athlete events (tryouts / camps / application deadlines) - a real, time-
    # sensitive nudge that was previously invisible to the digest.
    if AthleteEvent is not None:
        try:
            for e in db.query(AthleteEvent).filter(AthleteEvent.user_id == user_id).all():
                if getattr(e, "event_date", None):
                    _consider(getattr(e, "title", None), e.event_date)
        except Exception:
            pass
 
    return best
 
 
def build_digest_summary(db, models, user_id) -> dict:
    """Gather the real, factual numbers for this user's week. Returns a plain
    dict; no side effects, fully testable. Every field reflects real data."""
    MatchScore = models["MatchScore"]
    Listing = models["Listing"]
    SavedListing = models["SavedListing"]
    Application = models.get("Application")
 
    summary = {"strong_new_matches": 0, "top_match": None, "soonest_deadline": None,
               "pending_applications": 0}
 
    try:
        # newest scan cycle for this user
        latest = (
            db.query(MatchScore.scan_cycle)
            .filter(MatchScore.user_id == user_id)
            .order_by(MatchScore.scan_cycle.desc())
            .first()
        )
        if latest:
            cycle = latest[0]
            rows = (
                db.query(MatchScore)
                .filter(MatchScore.user_id == user_id, MatchScore.scan_cycle == cycle)
                .all()
            )
            strong = [r for r in rows if float(r.score_pct or 0) >= _STRONG_MATCH_THRESHOLD]
            summary["strong_new_matches"] = len(strong)
            if strong:
                best = max(strong, key=lambda r: float(r.score_pct or 0))
                listing = db.query(Listing).filter(Listing.id == best.listing_id).first()
                if listing:
                    summary["top_match"] = {
                        "title": getattr(listing, "title", "a strong match"),
                        "org": getattr(listing, "org", ""),
                        "pct": int(float(best.score_pct or 0)),
                    }
    except Exception:
        pass
 
    summary["soonest_deadline"] = _soonest_deadline(db, Listing, SavedListing, user_id, models.get("AthleteEvent"))
 
    if Application is not None:
        try:
            summary["pending_applications"] = (
                db.query(Application)
                .filter(Application.user_id == user_id, Application.status == "sent",
                        Application.outcome_status.is_(None))
                .count()
            )
        except Exception:
            pass
 
    return summary
 
 
def _esc(s) -> str:
    return (str("" if s is None else s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
 
 
def render_digest_email(summary: dict) -> tuple[str, str, str] | None:
    """Turn a summary into (subject, text_body, html_body). Returns None if there
    is genuinely nothing worth emailing about (so we never send an empty digest)."""
    strong = summary.get("strong_new_matches", 0)
    top = summary.get("top_match")
    deadline = summary.get("soonest_deadline")
    pending = summary.get("pending_applications", 0)
 
    # Nothing real to say -> don't send. Honest: no manufactured "we found nothing!" spam.
    has_deadline_soon = deadline is not None and deadline["days"] <= 14
    if strong == 0 and not has_deadline_soon and pending == 0:
        return None
 
    lines = []
    if strong > 0:
        if top:
            lines.append(f"{strong} new strong match{'es' if strong != 1 else ''} this week - "
                         f"top pick: \"{top['title']}\"" + (f" at {top['org']}" if top['org'] else "")
                         + f" ({top['pct']}% match).")
        else:
            lines.append(f"{strong} new strong match{'es' if strong != 1 else ''} surfaced this week.")
    if has_deadline_soon:
        d = deadline["days"]
        when = "today" if d == 0 else ("tomorrow" if d == 1 else f"in {d} days")
        lines.append(f"Heads up: \"{deadline['title']}\" (saved) closes {when}.")
    if pending > 0:
        lines.append(f"You have {pending} sent application{'s' if pending != 1 else ''} "
                     f"awaiting an outcome - logging what happened helps Kaidostar tune your matches.")
 
    subject = "Your Kaidostar week" + (f": {strong} new strong match{'es' if strong != 1 else ''}" if strong else "")
    text_body = "Here's what actually happened on your search this week:\n\n" + "\n".join("- " + l for l in lines) \
                + "\n\nOpen Kaidostar to act on any of these. (Reply STOP or turn off digests in settings to stop these.)"
 
    html_lines = "".join(f"<li style='margin:8px 0;line-height:1.5;'>{_esc(l)}</li>" for l in lines)
    html_body = f"""<!doctype html><html><body style="margin:0;background:#0b0c1f;padding:24px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#e8e8f0;">
<div style="max-width:520px;margin:0 auto;background:#171933;border:1px solid #2a2d52;border-radius:16px;overflow:hidden;">
  <div style="padding:20px 24px;border-bottom:1px solid #2a2d52;">
    <div style="font-size:18px;font-weight:700;color:#F0B24E;">Your Kaidostar week</div>
    <div style="font-size:13px;color:#9a9ab0;margin-top:4px;">What actually happened on your search &mdash; real, not padded.</div>
  </div>
  <div style="padding:20px 24px;">
    <ul style="margin:0;padding-left:18px;font-size:14px;">{html_lines}</ul>
  </div>
  <div style="padding:16px 24px;border-top:1px solid #2a2d52;font-size:11.5px;color:#7a7a90;">
    Open Kaidostar to act on any of these. You can turn off digests anytime in settings.
  </div>
</div></body></html>"""
 
    return subject, text_body, html_body
 
 
def maybe_send_weekly_digest(db, models, user, anthropic_client=None) -> dict:
    """The scan-loop entry point. Fully fail-safe: returns a status dict and never
    raises. Sends at most one digest per DIGEST_INTERVAL_DAYS per user, respects
    the digest mute preference, and only sends when there's something real to say."""
    Notification = models["Notification"]
    from app.services.email_send import send_email
 
    try:
        user_id = user.id
        to_address = getattr(user, "email", None)
        if not to_address:
            return {"status": "no email"}
 
        # respect opt-out
        profile = models.get("_profile")  # optional, passed by caller if available
        prefs = None
        if profile is not None:
            prefs = getattr(profile, "notification_preferences", None) or {}
        if prefs is not None and prefs.get("weekly_digest", True) is False:
            return {"status": "muted"}
 
        if _already_sent_recently(db, Notification, user_id):
            return {"status": "already sent this week"}
 
        summary = build_digest_summary(db, models, user_id)
        rendered = render_digest_email(summary)
        if rendered is None:
            return {"status": "nothing to send"}
 
        subject, text_body, html_body = rendered
        try:
            send_email(to_address, subject, text_body, html_body=html_body)
        except Exception as e:
            # email infra not configured / transient failure - don't record a
            # 'sent' marker, so we retry next scan, and never crash the scan.
            return {"status": "send failed", "detail": str(e)[:60]}
 
        # record that we sent, so we don't send again for DIGEST_INTERVAL_DAYS
        try:
            db.add(Notification(user_id=user_id, type="weekly_digest",
                                title=subject, body=text_body[:500]))
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "sent", "summary": summary}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:60]}
 
