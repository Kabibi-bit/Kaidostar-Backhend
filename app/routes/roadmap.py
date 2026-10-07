import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit, rate_limit_by_tier
from app.services.tiers import require_feature
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import Profile, Listing, RoadmapMilestone, RoadmapSummary, SocialPost, WorkshopItem
from app.services.roadmap import generate_roadmap, explain_listing_against_roadmap
from app.services.pathways import generate_pathways
from app.services.matching import rank_listings, _terms_match, tokenize
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/roadmap", tags=["roadmap"])
 
 
def _profile_to_dict(p: Profile) -> dict:
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "timeframe": p.timeframe or "",
        "stage": p.stage or "",
        "priorities": p.priorities or [],
        "dealbreakers": p.dealbreakers or "",
        "target_types": p.target_types or [],
    }
 
 
def _compute_skill_gaps(db: Session, profile_dict: dict) -> list[str]:
    """Finds tags that show up often in this user's top real matches
    but aren't in their stated skills or goal - grounding the roadmap
    in real data instead of generic advice.
    """
    from app.services.feed_common import not_feed
    listings = db.query(Listing).filter(not_feed(Listing)).all()
    if not listings:
        return []
    listing_dicts = [
        {
            "id": str(l.id), "type": l.type, "title": l.title, "org": l.org, "tags": l.tags or [],
            "location": l.location, "deadline": l.deadline.isoformat() if l.deadline else None,
            "description": l.description or "",
        }
        for l in listings
    ]
    ranked = rank_listings(listing_dicts, profile_dict, top_n=8)
 
    skill_tokens = tokenize(profile_dict.get("skills", "") or "")
    goal_tokens = tokenize((profile_dict["northstar"] + " " + profile_dict.get("final_idea", "")) or "")
 
    freq = {}
    for listing in ranked:
        for tag in listing.get("tags", []):
            known = any(_terms_match(t, tag) for t in skill_tokens) or any(_terms_match(t, tag) for t in goal_tokens)
            if not known:
                freq[tag] = freq.get(tag, 0) + 1
    return [tag for tag, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:4]]
 
 
def _ranked_listings(db: Session, profile_dict: dict, top_n: int = 10) -> list:
    """Real listings, scored and ranked for this user - the ground truth the
    pathways atlas is built from (supporting matches, top match, gap tags)."""
    from app.services.feed_common import not_feed
    listings = db.query(Listing).filter(not_feed(Listing)).all()
    if not listings:
        return []
    listing_dicts = [
        {
            "id": str(l.id), "type": l.type, "title": l.title, "org": l.org, "tags": l.tags or [],
            "location": l.location, "deadline": l.deadline.isoformat() if l.deadline else None,
            "description": l.description or "",
        }
        for l in listings
    ]
    return rank_listings(listing_dicts, profile_dict, top_n=top_n)
 
 
def _gaps_from_ranked(ranked: list, profile_dict: dict) -> list[str]:
    skill_tokens = tokenize(profile_dict.get("skills", "") or "")
    goal_tokens = tokenize((profile_dict["northstar"] + " " + profile_dict.get("final_idea", "")) or "")
    freq = {}
    for listing in ranked:
        for tag in listing.get("tags", []):
            known = any(_terms_match(t, tag) for t in skill_tokens) or any(_terms_match(t, tag) for t in goal_tokens)
            if not known:
                freq[tag] = freq.get(tag, 0) + 1
    return [tag for tag, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:4]]
 
 
@router.get("/{user_id}/pathways")
def get_pathways(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The Pathways Atlas: a branching graph of dozens of real routes from
    where the person is now to their goal, grounded in their real ranked
    listings, plus the engine's authoritative recommendation. The browser
    renders this and re-scores live as the person adjusts constraints; this
    is the server-side source of truth for the graph and the initial pick.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    require_feature(db, user_id, "roadmap")  # Roadmap (incl. the Pathways Atlas) is Pro+
    rate_limit_by_tier(db, user_id, "pathways", per_action_limit=400)
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    profile_dict = _profile_to_dict(profile)
    ranked = _ranked_listings(db, profile_dict, top_n=10)
    skill_gaps = _gaps_from_ranked(ranked, profile_dict)
    return generate_pathways(profile_dict, ranked, skill_gaps)
 
 
@router.post("/{user_id}")
def create_roadmap(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    rate_limit_by_tier(db, user_id, "roadmap-generate", per_action_limit=200)
    """Generates a fresh, detailed roadmap: an overall strategy summary
    plus 4-6 milestones, each with success criteria, a timeframe, a
    first action, a concrete resource, and the specific risk of
    stalling on that step. Replaces any previous roadmap.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    require_feature(db, user_id, "roadmap")  # Roadmap is Pro+
    profile_dict = _profile_to_dict(profile)
    skill_gaps = _compute_skill_gaps(db, profile_dict)
    try:
        result = generate_roadmap(client, profile_dict, skill_gaps=skill_gaps)
    except Exception as e:
        _log.warning("Could not generate a roadmap just now - try again. - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate a roadmap just now - try again.. Please try again.")
    milestones = result["milestones"]
    summary = result["summary"]
 
    db.query(RoadmapMilestone).filter(RoadmapMilestone.user_id == user_id).delete()
    for m in milestones:
        db.add(RoadmapMilestone(
            user_id=user_id,
            title=m["title"],
            description=m["description"],
            success_criteria=m.get("success_criteria", ""),
            estimated_timeframe=m.get("estimated_timeframe", ""),
            first_action=m.get("first_action", ""),
            resource=m.get("resource", ""),
            risk=m.get("risk", ""),
            if_it_works=m.get("if_it_works", ""),
            if_it_stalls=m.get("if_it_stalls", ""),
            target_stage=m["stage"],
        ))
 
    existing_summary = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == user_id).first()
    if existing_summary:
        existing_summary.summary = summary
        db.commit()
    else:
        from sqlalchemy.exc import IntegrityError
        db.add(RoadmapSummary(user_id=user_id, summary=summary))
        try:
            db.commit()
        except IntegrityError:
            # Concurrent first-time roadmap generation for this user won the
            # RoadmapSummary row (user_id is its PRIMARY KEY). The failed commit
            # rolled back this run's milestones + summary together, and the winner
            # persisted its own complete roadmap. Return this run's freshly generated
            # result rather than 500-ing on the double-click; the winner's copy is
            # what persists and a refresh (GET /roadmap) shows a complete, valid one.
            db.rollback()
    return {"status": "created", "summary": summary, "milestones": milestones, "skill_gaps_used": skill_gaps}
 
 
@router.get("/{user_id}")
def get_roadmap(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"milestones": [], "summary": None, "note": "No roadmap yet - POST to this URL to generate one."}
    require_feature(db, user_id, "roadmap")  # Roadmap is Pro+
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    if not milestones:
        return {"milestones": [], "summary": None, "note": "No roadmap yet - POST to this URL to generate one."}
 
    summary_row = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == user_id).first()
    return {
        "summary": summary_row.summary if summary_row else None,
        "milestones": [
            {
                "id": str(m.id),
                "title": m.title,
                "description": m.description,
                "success_criteria": m.success_criteria,
                "estimated_timeframe": m.estimated_timeframe,
                "first_action": m.first_action,
                "resource": m.resource,
                "risk": m.risk,
                "if_it_works": m.if_it_works,
                "if_it_stalls": m.if_it_stalls,
                "stage": m.target_stage,
                "status": m.status,
            }
            for m in milestones
        ]
    }
 
 
# ---------------------------------------------------------------------------
# The Proof Plan: the Roadmap page's saved route, steps, statuses and daily
# readiness snapshots - plus the milestones and summary every other part of
# Kaidostar reads (overview, Mission Control, Waypoint, chat, Auto's roadmap fit),
# written together so they always agree. The page computes the plan from live
# jobs (roadmap-engine.js); the server stores it, bounded and checked field by
# field, and never invents any of it.
# ---------------------------------------------------------------------------
import json as _json
import math as _math
import re as _re
 
PLAN_KIND = "roadmap_plan"
PLAN_MAX_CHARS = 60000
PLAN_MAX_ITEMS = 30
PLAN_MAX_HISTORY = 60
PLAN_MAX_MILESTONES = 16
PLAN_MAX_ARCHIVE = 4
PLAN_SAVES_PER_DAY = 1000
_ROLE_ID = _re.compile(r"^[a-z0-9_]{1,60}$")
_ROUTE_ID = _re.compile(r"^[a-z0-9_:]{1,80}$")
_STEP_ID = _re.compile(r"^[a-z0-9_:.\-]{1,80}$")
_ITEM_KINDS = {"skill", "prove", "credential", "network", "apply", "interview"}
_USER_STATUSES = {"doing", "done", "skip"}
_HAVE_LEVELS = {"missing", "adjacent", "related", "stated", "proven"}
_MS_STATUSES = {"planned", "in_progress", "done"}
_MS_FIELDS = {"title": 240, "description": 1500, "success_criteria": 700, "estimated_timeframe": 140, "first_action": 700,
              "resource": 500, "risk": 500, "if_it_works": 500, "if_it_stalls": 500}
_TIME_MIN, _TIME_MAX = 946684800000, 4102444800000   # 2000-01-01 .. 2100-01-01, in ms
 
 
def _num(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and _math.isfinite(v)
 
 
def _rnd(v):
    # the page rounds halves up (Math.floor(x + 0.5)); Python's round() would round them to even
    return int(_math.floor(v + 0.5))
 
 
def _ms_time(v):
    return int(_math.floor(v)) if _num(v) and _TIME_MIN <= v <= _TIME_MAX else None
 
 
def _int_in(v, lo, hi):
    if not _num(v):
        return None
    r = _rnd(v)
    return r if lo <= r <= hi else None
 
 
def _int_clamp(v, lo, hi):
    return max(lo, min(hi, _rnd(v))) if _num(v) else None
 
 
def _str_match(v, pattern):
    # fullmatch: a trailing newline must fail here exactly as it does in the page's regex
    return v if isinstance(v, str) and pattern.fullmatch(v) else None
 
 
def _clean_items(raw) -> list[dict]:
    items, seen = [], set()
    for x in (raw if isinstance(raw, list) else [])[:200]:
        if not isinstance(x, dict) or len(items) >= PLAN_MAX_ITEMS:
            continue
        sid = _str_match(x.get("id"), _STEP_ID)
        kind = x.get("kind") if isinstance(x.get("kind"), str) and x.get("kind") in _ITEM_KINDS else None
        if not sid or not kind or sid in seen:
            continue
        seen.add(sid)
        o = {"id": sid, "kind": kind}
        skill = _str_match(x.get("skillId"), _ROLE_ID)
        if skill:
            o["skillId"] = skill
        if isinstance(x.get("haveAtStart"), str) and x["haveAtStart"] in _HAVE_LEVELS:
            o["haveAtStart"] = x["haveAtStart"]
        if isinstance(x.get("status"), str) and x["status"] in _USER_STATUSES:
            o["status"] = x["status"]
        for k in ("startedAt", "doneAt", "dueAt", "verifiedAt"):
            t = _ms_time(x.get(k))
            if t is not None:
                o[k] = t
        if _num(x.get("hours")) and x["hours"] > 0:
            o["hours"] = _int_clamp(x["hours"], 1, 2000)
        items.append(o)
    return items
 
 
def _clean_archive(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    rows = []
    for k, e in raw.items():
        if not isinstance(k, str) or not _ROLE_ID.fullmatch(k) or not isinstance(e, dict):
            continue
        rows.append((k, {
            "route": _str_match(e.get("route"), _ROUTE_ID), "forRoute": _str_match(e.get("forRoute"), _ROUTE_ID),
            "startAt": _ms_time(e.get("startAt")), "baselineReadyAt": _ms_time(e.get("baselineReadyAt")),
            "savedAt": _ms_time(e.get("savedAt")), "items": _clean_items(e.get("items")),
        }))
    # newest first, ties by role id - the same order the page keeps
    rows.sort(key=lambda r: (-(r[1]["savedAt"] or 0), r[0]))
    return {k: v for k, v in rows[:PLAN_MAX_ARCHIVE]}
 
 
def clean_plan(raw) -> dict:
    """The saved plan, exactly the fields the page's normPlan keeps - anything else is dropped,
    every value bounded with the same rules. Mirrors RoadmapEngine.normPlan."""
    p = raw if isinstance(raw, dict) else {}
    history = []
    hist = p.get("history") if isinstance(p.get("history"), list) else []
    for h in hist[-PLAN_MAX_HISTORY:]:
        if not isinstance(h, dict):
            continue
        at = _ms_time(h.get("at"))
        if at is None:
            continue
        history.append({
            "at": at, "role": _str_match(h.get("role"), _ROLE_ID) or "",
            "n": _int_in(h.get("n"), 0, 1000000) or 0, "strong": _int_in(h.get("strong"), 0, 1000000) or 0,
            "reach": _int_in(h.get("reach"), 0, 1000000) or 0, "median": _int_in(h.get("median"), 0, 100),
        })
    return {
        "v": 1,
        "role": _str_match(p.get("role"), _ROLE_ID),
        "forRole": _str_match(p.get("forRole"), _ROLE_ID),
        "route": _str_match(p.get("route"), _ROUTE_ID),
        "forRoute": _str_match(p.get("forRoute"), _ROUTE_ID),
        "hoursPerWeek": _int_clamp(p.get("hoursPerWeek"), 2, 60),
        "targetAt": _ms_time(p.get("targetAt")),
        "startAt": _ms_time(p.get("startAt")),
        "items": _clean_items(p.get("items")),
        "baselineReadyAt": _ms_time(p.get("baselineReadyAt")),
        "readySince": _ms_time(p.get("readySince")),
        "history": history,
        "archive": _clean_archive(p.get("archive")),
        "builtAt": _ms_time(p.get("builtAt")),
        "updatedAt": _ms_time(p.get("updatedAt")),
        "changedAt": _ms_time(p.get("changedAt")),
    }
 
 
def clean_milestones(raw) -> list[dict]:
    """The shared milestone shape (title, description, success criteria, timeframe, first action, resource, risk,
    if it works / stalls, status) - strings only, bounded, numbered 1..n in the order given."""
    out = []
    for m in (raw if isinstance(raw, list) else [])[:200]:
        if len(out) >= PLAN_MAX_MILESTONES:
            break
        if not isinstance(m, dict):
            continue
        row = {}
        for k, cap in _MS_FIELDS.items():
            v = m.get(k)
            row[k] = v.strip()[:cap] if isinstance(v, str) else ""
        if not row["title"]:
            continue
        row["status"] = m.get("status") if m.get("status") in _MS_STATUSES else "planned"
        row["stage"] = len(out) + 1
        out.append(row)
    return out
 
 
class PlanIn(BaseModel):
    plan: dict = Field(default_factory=dict)
    milestones: list = Field(default_factory=list, max_length=200)
    summary: str = Field(default="", max_length=4000)
    # the changedAt of the account's copy this page last saw (null: it hasn't seen one). A save based on an older copy
    # - another device changed the plan since - is refused with 409, so the page merges instead of overwriting.
    base_changed_at: int | None = Field(default=None, ge=0)
 
 
def _merge_history(stored: list, incoming: list) -> list:
    """The daily readiness snapshots from both copies: one per day and destination, the incoming one winning a tie."""
    by = {}
    for h in list(stored or []) + list(incoming or []):
        by[(h["at"] // 86400000, h["role"])] = h
    return sorted(by.values(), key=lambda h: h["at"])[-PLAN_MAX_HISTORY:]
 
 
def _plan_row(db: Session, user_id: str, lock: bool = False):
    """The person's one plan record (the most recently updated, if an old race ever left two). Always the database's
    current copy; lock=True holds the row (SELECT ... FOR UPDATE) until the commit, so two saves at the same moment
    are checked one after the other - the same pattern as the Job Search state."""
    q = db.query(WorkshopItem).filter(WorkshopItem.user_id == user_id, WorkshopItem.kind == PLAN_KIND)
    try:
        q = q.order_by(WorkshopItem.updated_at.desc().nullslast(), WorkshopItem.created_at.desc().nullslast())
    except Exception:
        q = q.order_by(WorkshopItem.updated_at.desc())
    try:
        q = q.populate_existing()
    except Exception:
        pass
    if lock:
        try:
            q = q.with_for_update()
        except Exception:
            pass
    return q.first()
 
 
@router.get("/{user_id}/plan")
def get_plan(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Your saved Proof Plan (null when there isn't one yet)."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No plan for this user")
    require_feature(db, user_id, "roadmap")  # Roadmap is Pro+
    row = _plan_row(db, user_id)
    if row is None or not isinstance(row.data, dict):
        return {"plan": None, "updated_at": None}
    return {"plan": clean_plan(row.data), "updated_at": (row.updated_at.isoformat() + "Z") if row.updated_at else None}
 
 
@router.put("/{user_id}/plan")
def save_plan(user_id: str, payload: PlanIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Saves the plan, and replaces the milestones and summary the rest of Kaidostar reads with the ones from the
    same plan - one commit, so they can't disagree."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    require_feature(db, user_id, "roadmap")  # Roadmap is Pro+
    rate_limit(db, user_id, "roadmap-plan-save", limit_per_day=PLAN_SAVES_PER_DAY)
    plan = clean_plan(payload.plan)
    if len(_json.dumps(plan)) > PLAN_MAX_CHARS:
        raise HTTPException(status_code=400, detail="The plan is too large to save.")
    milestones = clean_milestones(payload.milestones)
    summary = (payload.summary or "").strip()[:2000]
    base = payload.base_changed_at if isinstance(payload.base_changed_at, int) and not isinstance(payload.base_changed_at, bool) else None
    return _write_plan(db, user_id, plan, milestones, summary, base, retry=True)
 
 
def _write_plan(db: Session, user_id: str, plan: dict, milestones: list, summary: str, base, retry: bool):
    from sqlalchemy.exc import IntegrityError
    from datetime import datetime as _dt
    row = _plan_row(db, user_id, lock=True)
    if row is not None and isinstance(row.data, dict):
        stored = clean_plan(row.data)
        stored_changed = stored.get("changedAt") or 0
        # another device changed the plan since this page last saw it: refuse, so the page merges instead of overwriting
        if stored_changed and stored_changed != (base or 0) and stored_changed > (plan.get("changedAt") or 0):
            db.rollback()
            raise HTTPException(status_code=409, detail="Your plan changed on another device - reload to merge, then save again.")
        plan = dict(plan, history=_merge_history(stored["history"], plan["history"]))
    if row is not None:
        # one record per person: drop any stray duplicates, then update in place
        db.query(WorkshopItem).filter(WorkshopItem.user_id == user_id, WorkshopItem.kind == PLAN_KIND, WorkshopItem.id != row.id).delete(synchronize_session=False)
        row.data = plan
        row.updated_at = _dt.utcnow()
        try:
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(row, "data")
        except Exception:
            pass
    else:
        db.add(WorkshopItem(user_id=user_id, kind=PLAN_KIND, client_id=PLAN_KIND, data=plan))
    if milestones:
        db.query(RoadmapMilestone).filter(RoadmapMilestone.user_id == user_id).delete(synchronize_session=False)
        for m in milestones:
            db.add(RoadmapMilestone(
                user_id=user_id, title=m["title"], description=m["description"], success_criteria=m["success_criteria"],
                estimated_timeframe=m["estimated_timeframe"], first_action=m["first_action"], resource=m["resource"],
                risk=m["risk"], if_it_works=m["if_it_works"], if_it_stalls=m["if_it_stalls"],
                target_stage=m["stage"], status=m["status"],
            ))
        if summary:
            srow = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == user_id).first()
            if srow is not None:
                srow.summary = summary
                srow.updated_at = _dt.utcnow()
            else:
                db.add(RoadmapSummary(user_id=user_id, summary=summary))
    try:
        db.commit()
    except IntegrityError:
        # two first saves at once (a double tab): the other one created the rows - update them instead
        db.rollback()
        if not retry:
            raise HTTPException(status_code=409, detail="Your plan was saved from another tab at the same moment - try again.")
        return _write_plan(db, user_id, plan, milestones, summary, base, retry=False)
    return {"status": "saved", "milestones": len(milestones)}
 
 
class MilestoneStatusIn(BaseModel):
    status: str
    reflection: str | None = Field(default=None, max_length=4000)
 
 
VALID_MILESTONE_STATUSES = {"planned", "in_progress", "done"}
 
 
@router.post("/milestone/{milestone_id}/status")
def update_milestone_status(milestone_id: str, payload: MilestoneStatusIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Marks real progress on one milestone - this is what makes the
    roadmap a living plan instead of a one-time AI output.
 
    When status genuinely transitions to "done" and the person
    provides a real reflection in the same request, this also creates
    a genuine, linked Waypoint journal entry - tagged to this exact
    milestone's real stage and title, not a generic "write something"
    prompt. This is what makes Waypoint a natural byproduct of real
    progress instead of a separate page someone has to remember to
    visit: the reflection happens right when the real event does,
    grounded in the actual milestone they just completed. Entirely
    optional - a bare status update with no reflection behaves
    exactly as it always has.
    """
    if payload.status not in VALID_MILESTONE_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_MILESTONE_STATUSES}")
    import uuid as uuid_module
    try:
        uuid_module.UUID(milestone_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Milestone not found")
    milestone = db.query(RoadmapMilestone).filter(RoadmapMilestone.id == milestone_id).first()
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")
    # Only a milestone_id in the path, so verify the token against the
    # milestone's real owner before mutating it.
    verify_token_belongs_to_user(str(milestone.user_id), authorization)
    milestone.status = payload.status
 
    journal_entry_id = None
    if payload.status == "done" and payload.reflection and payload.reflection.strip():
        post = SocialPost(
            user_id=milestone.user_id, body=payload.reflection.strip(),
            tag_value=str(milestone.target_stage), tag_label=milestone.title,
        )
        db.add(post)
        db.flush()  # so post.id is populated before commit, to return it below
        journal_entry_id = str(post.id)
 
    db.commit()
    return {"status": "updated", "milestone_status": payload.status, "journal_entry_id": journal_entry_id}
 
 
@router.get("/{user_id}/explain/{listing_id}")
def explain_listing(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    require_feature(db, user_id, "roadmap")  # this explains fit to the user's stored roadmap - a Roadmap (Pro+) feature, not the free Job Search deep-explain
    rate_limit_by_tier(db, user_id, "roadmap-explain", per_action_limit=200)
    """Returns Claude's explanation of how one specific listing fits
    the user's stored roadmap.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    try:
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    if not milestones:
        raise HTTPException(status_code=404, detail="No roadmap yet - generate one first with POST /roadmap/{user_id}")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    roadmap_dicts = [
        {"stage": m.target_stage, "title": m.title, "description": m.description, "success_criteria": m.success_criteria}
        for m in milestones
    ]
    from app.services.feed_common import listing_tags
    listing_dict = {"title": listing.title, "org": listing.org, "type": listing.type, "tags": listing_tags(db, listing)}
 
    try:
        explanation = explain_listing_against_roadmap(client, listing_dict, roadmap_dicts, _profile_to_dict(profile))
    except Exception as e:
        _log.warning("Could not compare this listing to your roadmap just now - try again. - %s", e)
        raise HTTPException(status_code=502, detail="Could not compare this listing to your roadmap just now - try again.. Please try again.")
    return {"listing": listing.title, "explanation": explanation}
 
