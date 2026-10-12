"""Mission Control endpoint.
 
GET /mission/{user_id} returns the server-computed Mission Control snapshot -
every KPI, funnel stage, conversion, search metric and growth number the
dashboard shows - from the caller's real data (applications, logged outcomes,
the real match ranker, roadmap, saved count, interview-prep items). This is
what makes the dashboard genuinely backend-backed: the numbers are computed and
enforced server-side and are identical across devices, with the browser's
computation kept only as an offline fallback.
 
Auth-scoped to the caller's own user_id (require_auth_for_user). No AI call -
pure aggregation - so it's cheap and safe to hit on every dashboard load.
"""
import logging
import uuid as uuid_module
 
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.services.auth import require_auth_for_user
from app.services.mission import compute_mission
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/mission", tags=["mission"])
 
 
@router.get("/{user_id}")
def get_mission(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    from app.models.db_models import (
        Profile, Application, Outcome, Listing, DismissedListing,
        SavedListing, RoadmapMilestone, WorkshopItem,
    )
    from app.routes.listings import _listing_to_dict, _profile_to_dict
    from app.services.matching import rank_listings
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        return {"has_profile": False}
 
    # Applications, joined to their listing for org/title.
    apps = db.query(Application).filter(Application.user_id == user_id).all()
    # the listings this user applied to (any source - employer-feed jobs included) for org/title, and the
    # board listings for the ranking below (the v1 ranker reads tags employer-feed jobs don't carry)
    from app.services.feed_common import not_feed
    app_listing_ids = list({a.listing_id for a in apps if a.listing_id is not None})
    app_listings = db.query(Listing).filter(Listing.id.in_(app_listing_ids)).all() if app_listing_ids else []
    listings = db.query(Listing).filter(not_feed(Listing)).all()
    listing_by_id = {str(l.id): l for l in app_listings}
    app_dicts = []
    for a in apps:
        l = listing_by_id.get(str(a.listing_id))
        app_dicts.append({
            "status": a.status,
            "listing_id": str(a.listing_id),
            "org": (l.org if l else None),
            "title": (l.title if l else None),
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
            "has_factors": a.factors_snapshot is not None,
            "has_draft": bool(a.draft_content),
        })
 
    # Latest outcome status per listing (same dedup the outcomes/stats route uses).
    orows = (
        db.query(Outcome)
        .filter(Outcome.user_id == user_id)
        .order_by(Outcome.updated_at.asc())
        .all()
    )
    outcomes = {}
    for r in orows:
        outcomes[str(r.listing_id)] = r.status
 
    # Real ranked matches (minus dismissed), via the same ranker the app uses.
    dismissed = {str(r.listing_id) for r in db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()}
    try:
        ranked = rank_listings(
            [_listing_to_dict(l) for l in listings],
            _profile_to_dict(profile),
            top_n=40,
            dismissed_ids=dismissed,
        )
    except Exception as e:
        _log.warning("mission: ranking failed, continuing with no matches - %s", e)
        ranked = []
    matches = [{
        "title": m.get("title"), "org": m.get("org"), "score_pct": m.get("score_pct"),
        "type": m.get("type"), "tags": m.get("tags") or [], "deadline": m.get("deadline"),
        "ghost_risk": m.get("ghost_risk"), "signal_strength": m.get("signal_strength"),
    } for m in ranked]
 
    # Roadmap progress.
    roadmap_rows = db.query(RoadmapMilestone).filter(RoadmapMilestone.user_id == user_id).all()
    done = sum(1 for r in roadmap_rows if r.status == "done")
    total = len(roadmap_rows)
 
    saved_count = db.query(SavedListing).filter(SavedListing.user_id == user_id).count()
 
    wrows = (
        db.query(WorkshopItem)
        .filter(WorkshopItem.user_id == user_id, WorkshopItem.kind.in_(["star_story", "interview_answer", "interview_ask"]))
        .all()
    )
    workshop = {"star_story": 0, "interview_answer": 0, "interview_ask": 0}
    for w in wrows:
        if w.kind in workshop:
            workshop[w.kind] += 1
 
    data = {
        "profile": {"skills": profile.skills or "", "northstar": profile.northstar or ""},
        "applications": app_dicts,
        "outcomes": outcomes,
        "matches": matches,
        "roadmap": {"done": done, "total": total},
        "saved_count": saved_count,
        "workshop": workshop,
    }
    snap = compute_mission(data)
    snap["matches"] = matches  # the frontend renders these as the live top-matches list
    return snap
 
 
# ---------------------------------------------------------------------------
# GET /mission/{user_id}/overview - the rebuilt Mission Control's one read.
# ---------------------------------------------------------------------------
APPS_MAX = 1000          # the newest applications charted (far more than anyone sends in the pages' longest range)
OUTCOMES_MAX = 5000      # outcome rows (one per status change); the newest are kept
SAVED_MAX, DISMISSED_MAX, JOURNAL_MAX = 500, 3000, 1000
# workshop records charted per kind (newest first); count-only kinds are counted, never read in full
WORKSHOP_CAPS = {"interview_session": 200, "star_story": 200, "interview_debrief": 100, "interview_answer": 400,
                 "resume_version": 100, "contact": 400, "target_role": 100}
WORKSHOP_COUNTED = ("interview_ask", "achievement", "reference", "portfolio")
WORKSHOP_SINGLE = ("pitch", "roadmap_plan")
 
 
@router.get("/{user_id}/overview")
def get_overview(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Everything the Mission Control pages chart, in one cheap read: your applications (with their listing's
    place, type and posting date), every outcome you logged (the full history, so a reply's date is known),
    Auto's records (how each application went out, or why it came back to you), saved and dismissed jobs with
    their dates, your practice interviews, stories, debriefs, resume versions, contacts and saved plan, your
    journal's dates, Job Search's saved searches and your resume entries.
 
    Pure reads, auth-scoped to the caller: no scoring, no AI, nothing written. A part that can't be read just
    now is named in "missing" (and left empty) rather than failing the whole page; a list cut at its limit is
    named in "capped", so the page can say it shows the newest ones. Applications, outcomes and the goal history are
    read column by column (never a listing's description or a letter's text)."""
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    import time
    from sqlalchemy import text
    from app.models.db_models import (
        Profile, Application, Outcome, Listing, SavedListing, DismissedListing, WorkshopItem,
        SocialPost, Notification, ResumeEntry, OutreachEmail,
    )
    from app.services import mission as M
    from app.services import auto_runner as AR
 
    now = int(time.time() * 1000)
    missing, capped = [], []
    # "tier" stays None unless it was really read (a failed read is not "free")
    out = {"v": M.OVERVIEW_VERSION, "now": now, "has_profile": False, "profile": None, "tier": None, "features": {},
           "apps": [], "outcomes": [], "saved": [], "dismissed": [], "auto": None, "items": M.compact_workshop([]),
           "search": None, "journal": [], "notifications": [], "resume_entries": [], "outreach": [], "coverage": None,
           "missing": missing, "capped": capped}
 
    pending_caps = []
 
    def part(name, fn):
        del pending_caps[:]
        try:
            fn()
            capped.extend(pending_caps)       # a cut is only reported for a part that was read
        except Exception as e:  # one part failing never takes the page down
            _log.warning("mission overview: %s skipped for %s - %s", name, user_id, e)
            try:
                db.rollback()
            except Exception:
                pass
            missing.append(name)
 
    def newest(query, name, limit):
        """The newest `limit` rows (the query is already ordered newest first); one more is read to know if any were left out."""
        rows = query.limit(limit + 1).all()
        if len(rows) > limit:
            pending_caps.append({"part": name, "limit": limit})
            rows = rows[:limit]
        return rows
 
    profile_box = {}
 
    def _profile():
        # the newest snapshots (every survey save adds one), oldest first
        rows = list(reversed(db.query(Profile.created_at, Profile.northstar).filter(Profile.user_id == user_id)
                             .order_by(Profile.created_at.desc()).limit(60).all()))
        cur = (db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
               .order_by(Profile.created_at.desc()).first())
        profile_box["p"] = cur
        hist = [{"at": AR._ms(r[0]), "northstar": M._txt(r[1], 120)} for r in rows]
        if cur is None:
            out["profile"] = {"history": hist} if hist else None
            return
        out["has_profile"] = True
        out["profile"] = {
            "northstar": M._txt(cur.northstar, 200), "skills": (cur.skills or "")[:1500], "timeframe": M._txt(cur.timeframe, 20),
            "stage": M._txt(cur.stage, 20), "priorities": [M._txt(x, 30) for x in (cur.priorities or [])][:10],
            "target_types": [M._txt(x, 20) for x in (cur.target_types or [])][:6], "location_pref": M._txt(cur.location_pref, 120),
            "is_athlete": bool(cur.is_athlete), "is_student": bool(cur.is_student),
            "created_at": AR._ms(cur.created_at), "history": hist,
        }
        profile_box["ok"] = True
    part("profile", _profile)
 
    def _tier():
        from app.services.tiers import get_user_tier, tier_has_feature
        t = get_user_tier(db, user_id)
        # get_user_tier answers "free" on any error and doesn't roll back: make sure the read really worked
        db.execute(text("SELECT 1"))
        out["tier"] = t
        out["features"] = {k: bool(tier_has_feature(t, k)) for k in ("auto_mode", "auto_submit", "roadmap", "interview_prep", "workshop")}
    part("tier", _tier)
 
    def _apps():
        # only the columns the page uses (never a listing's description or embedding, never a letter's text)
        rows = (db.query(Application.id, Application.listing_id, Application.status, Application.created_at, Application.sendable_at,
                         Application.sent_at, Application.sent_channel, Application.confidence_pct, Application.counterfactual_confidence_pct,
                         Application.auto_generated, Application.draft_flagged_terms, Application.factors_snapshot,
                         Listing.title, Listing.org, Listing.location, Listing.type, Listing.employment_type, Listing.source,
                         Listing.posted_at, Listing.deadline, Listing.apply_url)
                .join(Listing, Application.listing_id == Listing.id)
                .filter(Application.user_id == user_id).order_by(Application.created_at.desc()))
        rows = newest(rows, "applications", APPS_MAX)
        ids = [str(r[0]) for r in rows]
        drafted = set()
        try:
            # which have a letter with real text (Postgres: draft_content ~ '\S') - ids only, never the text
            drafted.update(str(r[0]) for r in db.query(Application.id).filter(
                Application.user_id == user_id, Application.draft_content.regexp_match(r"\S")).all())
        except Exception:
            db.rollback()
            missing.append("drafts")
        pk = {}
        try:
            W = WorkshopItem
            for i in range(0, len(ids), 500):
                for cid, data in db.query(W.client_id, W.data).filter(
                        W.user_id == user_id, W.kind == AR.PACKAGE_KIND, W.client_id.in_(ids[i:i + 500])).all():
                    if isinstance(data, dict):
                        pk[str(cid)] = data
        except Exception:
            db.rollback()
            pk = {}
            missing.append("auto_packages")
        apps = []
        for (aid, lid, status, created, sendable, sent, channel, conf, cf, auto_gen, flagged, factors,
             title, org, location, ltype, emp, source, posted, deadline, apply_url) in rows:
            try:
                route = AR.route_of(apply_url)[0]
            except Exception:
                route = None
            apps.append({
                "id": str(aid), "listing_id": str(lid),
                "title": M._txt(title, 140), "org": M._txt(org, 100), "location": M._txt(location, 120),
                "type": M._key(ltype, 20), "employment_type": M._key(emp, 20), "source": M._key(source, 30),
                "posted_at": AR._ms(posted), "deadline": deadline.isoformat() if deadline else None,
                "route": route, "status": M._key(status, 30),
                "created_at": AR._ms(created), "sendable_at": AR._ms(sendable), "sent_at": AR._ms(sent),
                "channel": M._key(channel, 20),
                "confidence": float(conf) if conf is not None else None,
                "counterfactual": float(cf) if cf is not None else None,
                "auto": bool(auto_gen), "has_draft": str(aid) in drafted,
                "flagged": len(flagged) if isinstance(flagged, list) else 0,
                "factors": M.compact_factors(factors),
                "pkg": M.compact_package(pk.get(str(aid))),
            })
        out["apps"] = apps
    part("applications", _apps)
 
    def _outcomes():
        # one row per status change: keep the newest, oldest first
        rows = newest(db.query(Outcome.listing_id, Outcome.status, Outcome.updated_at).filter(Outcome.user_id == user_id)
                      .order_by(Outcome.updated_at.desc()), "outcomes", OUTCOMES_MAX)
        out["outcomes"] = [{"listing_id": str(r[0]), "status": M._key(r[1], 20), "at": AR._ms(r[2])} for r in reversed(rows)]
    part("outcomes", _outcomes)
 
    def _saved():
        rows = (db.query(SavedListing.listing_id, SavedListing.created_at, Listing.title, Listing.org, Listing.deadline, Listing.type)
                .join(Listing, SavedListing.listing_id == Listing.id).filter(SavedListing.user_id == user_id)
                .order_by(SavedListing.created_at.desc()))
        rows = newest(rows, "saved", SAVED_MAX)
        out["saved"] = [{"listing_id": str(r[0]), "at": AR._ms(r[1]), "title": M._txt(r[2], 140), "org": M._txt(r[3], 100),
                         "deadline": r[4].isoformat() if r[4] else None, "type": M._key(r[5], 20)} for r in rows]
    part("saved", _saved)
 
    def _dismissed():
        rows = newest(db.query(DismissedListing.created_at).filter(DismissedListing.user_id == user_id)
                      .order_by(DismissedListing.created_at.desc()), "dismissed", DISMISSED_MAX)
        out["dismissed"] = [AR._ms(r[0]) for r in rows if r[0] is not None]
    part("dismissed", _dismissed)
 
    def _auto():
        p = profile_box.get("p")
        settings_ok = bool(profile_box.get("ok")) or "profile" not in missing
        st = AR.load_state(db, user_id)
        bank = AR.load_answers(db, user_id)
        try:
            ap = AR.autopilot_status(AR.load_autopilot(db, user_id))
            ap = {k: ap.get(k) for k in ("seenAt", "okAt", "offAt", "live", "onSince", "note", "last", "maxAgeDays")}
        except Exception:
            db.rollback()
            ap = None                     # unknown - not "never seen"
            missing.append("autopilot")
        if not settings_ok:
            missing.append("auto_settings")   # the switch, consent and rules live on the profile, which wasn't read
        from app.services import auto_answers as AA
        out["auto"] = {
            "enabled": bool(getattr(p, "auto_apply_enabled", False)) if settings_ok else None,
            "consent": bool(getattr(p, "auto_submit_consent", False)) if settings_ok else None,
            "tierMax": AR.tier_daily_max(out["tier"]) if out.get("tier") else None,
            "rules": M.compact_rules(AR.rules_of(p)) if settings_ok else None,
            "runs": M.compact_runs(st.get("runs")), "lastRunAt": M._num(st.get("lastRunAt")),
            "extensionSeenAt": M._num(st.get("extensionSeenAt")), "lastError": bool(st.get("lastError")),
            "coverage": AA.coverage(bank), "learned": M.learned_answer_times(bank), "custom": M.custom_answer_counts(bank),
            "autopilot": ap,
        }
    part("auto", _auto)
 
    def _workshop():
        W = WorkshopItem
        rows = []
        # what the charts read: each kind's newest records, so a busy kind never crowds out another
        for kind, limit in WORKSHOP_CAPS.items():
            got = newest(db.query(W.kind, W.client_id, W.data, W.created_at, W.updated_at)
                         .filter(W.user_id == user_id, W.kind == kind).order_by(W.created_at.desc().nullslast()), "workshop:" + kind, limit)
            rows.extend((r[0], r[1], r[2], AR._ms(r[3]), AR._ms(r[4])) for r in got)
        # the counted kinds: ids only, never their contents
        for r in (db.query(W.kind, W.client_id).filter(W.user_id == user_id, W.kind.in_(WORKSHOP_COUNTED)).limit(5000).all()):
            rows.append((r[0], r[1], None, None, None))
        # the single records (the pitch, the saved plan): the most recently changed one of each
        for r in (db.query(W.kind, W.client_id, W.data, W.created_at, W.updated_at)
                  .filter(W.user_id == user_id, W.kind.in_(WORKSHOP_SINGLE)).order_by(W.updated_at.desc().nullslast()).limit(20).all()):
            if not any(x[0] == r[0] for x in rows):
                rows.append((r[0], r[1], r[2], AR._ms(r[3]), AR._ms(r[4])))
        out["items"] = M.compact_workshop(rows)
    part("workshop", _workshop)
 
    def _search():
        from app.services import job_search as JSV
        st, ok = JSV.load_state_checked(db, user_id)
        if not ok:
            missing.append("search")
            return
        out["search"] = M.compact_search_state(st)
    part("search", _search)
 
    def _journal():
        rows = newest(db.query(SocialPost.created_at, SocialPost.tag_value).filter(SocialPost.user_id == user_id)
                      .order_by(SocialPost.created_at.desc()), "journal", JOURNAL_MAX)
        out["journal"] = [{"at": AR._ms(r[0]), "tagged": bool(r[1])} for r in rows if r[0] is not None]
    part("journal", _journal)
 
    def _notes():
        rows = (db.query(Notification.type, Notification.created_at, Notification.is_read).filter(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc()).limit(100).all())
        out["notifications"] = [{"type": M._key(r[0], 30), "at": AR._ms(r[1]), "read": bool(r[2])} for r in rows]
    part("notifications", _notes)
 
    def _entries():
        rows = (db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id)
                .order_by(ResumeEntry.display_order, ResumeEntry.created_at).limit(100).all())
        out["resume_entries"] = [{
            "id": str(e.id), "entry_type": e.entry_type, "title": e.title, "org": e.org, "start_date": e.start_date,
            "end_date": e.end_date, "raw_description": (e.raw_description or "")[:4000], "display_order": e.display_order,
            "created": AR._ms(e.created_at),
        } for e in rows]
    part("resume_entries", _entries)
 
    def _outreach():
        rows = (db.query(OutreachEmail.listing_id, OutreachEmail.status, OutreachEmail.created_at, OutreachEmail.auto_generated,
                         OutreachEmail.address_verified).filter(OutreachEmail.user_id == user_id)
                .order_by(OutreachEmail.created_at.desc()).limit(500).all())
        out["outreach"] = [{"listing_id": str(r[0]), "status": M._key(r[1], 20), "at": AR._ms(r[2]), "auto": bool(r[3]),
                            "verified": bool(r[4])} for r in rows]
    part("outreach", _outreach)
 
    def _coverage():
        from app.services.feed_crawler import coverage_cached
        cov = coverage_cached(db)
        if cov:
            out["coverage"] = {k: cov.get(k) for k in ("jobs", "employers", "checked_24h", "checked_24h_pct", "by_source", "as_of")}
    part("coverage", _coverage)
 
    return out
 
