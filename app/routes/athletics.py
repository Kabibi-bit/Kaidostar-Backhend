import os
import logging
from datetime import date
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user, require_valid_token
from app.services.highlight_detection import detect_highlights_from_url, detection_available
from app.services.tiers import require_feature
from app.services.rate_limit import rate_limit_by_tier
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import AthleteEvent, AthleteOutreach, AthleteRoadmapMilestone, AthleteRoadmapSummary, SocialPost
from app.services.athletics import generate_recruiting_content_plan, research_target_program, draft_coach_outreach, generate_clip_edit_plan, generate_athlete_roadmap
from app.services.email_send import guess_contact_emails, send_email
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/athletics", tags=["athletics"])
 
VALID_DIRECTIONS = {"play-college", "go-pro", "coach", "sports-management"}
 
 
class ContentPlanIn(BaseModel):
    user_id: Optional[str] = None
    sport: str = Field(max_length=100)
    level: str = Field(max_length=100)
    career_direction: str = Field(max_length=100)
    achievements: str = Field(default="", max_length=4000)
 
 
@router.post("/content-coach")
def content_coach(payload: ContentPlanIn, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Generates real, grounded recruiting content guidance - a
    highlight reel structure, commonly-evaluated skills/metrics for
    this sport and level, specific drills to practice, and a filming
    checklist. Takes the athlete's profile fields directly in the
    request rather than looking one up, since there's no stored
    athlete-profile table on the backend yet - the athlete survey
    data has stayed frontend-only so far, an honest gap rather than
    something silently assumed to exist.
    """
    # Meter against the CALLER'S OWN token subject, always - never a body user_id.
    # require_valid_token doesn't tie the token to a body user_id, so metering only
    # `if payload.user_id` let a caller bypass the cap by omitting the field, or
    # charge this paid AI call against another user by passing their id.
    rate_limit_by_tier(db, _auth["sub"], "athlete-content", per_action_limit=300)
    if not payload.sport.strip():
        raise HTTPException(status_code=400, detail="sport is required")
    if not payload.level.strip():
        raise HTTPException(status_code=400, detail="level is required")
    if payload.career_direction not in VALID_DIRECTIONS:
        raise HTTPException(status_code=400, detail=f"career_direction must be one of {VALID_DIRECTIONS}")
    try:
        plan = generate_recruiting_content_plan(
            client, payload.sport, payload.level, payload.career_direction, payload.achievements
        )
    except Exception as e:
        _log.warning("Could not generate a content plan just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate a content plan just now. Please try again.")
    return plan
 
 
class ProgramResearchIn(BaseModel):
    user_id: Optional[str] = None
    sport: str = Field(max_length=100)
    level: str = Field(max_length=100)
    program_name: str = Field(max_length=300)
 
 
@router.post("/research-program")
def research_program(payload: ProgramResearchIn, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """The real-search upgrade: gives Claude the actual Anthropic web
    search tool to find and cite genuine, current public information
    about a specific named program, rather than general knowledge.
    Reports plainly when search doesn't turn up anything specific.
    """
    # Meter against the caller's OWN token subject, always (see content_coach): a
    # body user_id under require_valid_token could bypass the cap by omission or bill
    # this paid web-search call to another user. Especially important here - this is
    # the real Anthropic web-search tool, the costliest call in the file.
    rate_limit_by_tier(db, _auth["sub"], "company-research", per_action_limit=300)
    if not payload.sport.strip():
        raise HTTPException(status_code=400, detail="sport is required")
    if not payload.level.strip():
        raise HTTPException(status_code=400, detail="level is required")
    if not payload.program_name.strip():
        raise HTTPException(status_code=400, detail="program_name is required")
    try:
        result = research_target_program(client, payload.sport, payload.level, payload.program_name)
    except Exception as e:
        _log.warning("Could not research this program just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not research this program just now. Please try again.")
    return result
 
 
VALID_EVENT_TYPES = {"tryout", "camp", "combine", "application_deadline", "other"}
VALID_EVENT_STATUSES = {"upcoming", "attended", "passed", "missed"}
 
 
class EventIn(BaseModel):
    user_id: str
    title: str = Field(max_length=300)
    org: str | None = Field(default=None, max_length=300)
    event_type: str
    event_date: date | None = None
    roadmap_stage: int | None = None
    roadmap_stage_title: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=4000)
 
 
@router.post("/events")
def create_event(payload: EventIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Tracks a deadline or trial opportunity - a tryout, camp,
    combine, or application deadline - optionally tied to a specific
    roadmap stage.
    """
    verify_token_belongs_to_user(payload.user_id, authorization)
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    if payload.event_type not in VALID_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"event_type must be one of {VALID_EVENT_TYPES}")
    event = AthleteEvent(
        user_id=payload.user_id, title=payload.title, org=payload.org,
        event_type=payload.event_type, event_date=payload.event_date,
        roadmap_stage=payload.roadmap_stage, roadmap_stage_title=payload.roadmap_stage_title,
        notes=payload.notes,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"event_id": str(event.id), "status": "created"}
 
 
@router.get("/events/{user_id}")
def list_events(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        # A malformed user_id would otherwise reach the DB query
        # below and raise a raw, unhandled database exception -
        # mirrors the identical, verified risk in resume.py. An
        # explicit 400 here rather than silently returning an empty
        # list, since a malformed ID is a genuine client error worth
        # surfacing, not something that should look identical to
        # "no events exist yet."
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    rows = (
        db.query(AthleteEvent)
        .filter(AthleteEvent.user_id == user_id)
        .order_by(AthleteEvent.event_date.asc().nullslast())
        .all()
    )
    return [
        {
            "id": str(e.id), "title": e.title, "org": e.org, "event_type": e.event_type,
            "event_date": e.event_date.isoformat() if e.event_date else None,
            "roadmap_stage": e.roadmap_stage, "roadmap_stage_title": e.roadmap_stage_title,
            "status": e.status, "notes": e.notes, "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]
 
 
class EventStatusIn(BaseModel):
    status: str
 
 
@router.post("/events/{event_id}/status")
def update_event_status(event_id: str, payload: EventStatusIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    if payload.status not in VALID_EVENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_EVENT_STATUSES}")
    try:
        uuid_module.UUID(event_id)
    except ValueError:
        # Mirrors resume.py's established pattern - a malformed
        # event_id would otherwise raise a raw, unhandled database
        # exception at the query below.
        raise HTTPException(status_code=404, detail="Event not found")
    event = db.query(AthleteEvent).filter(AthleteEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    verify_token_belongs_to_user(str(event.user_id), authorization)
    event.status = payload.status
    db.commit()
    return {"status": "updated", "event_status": event.status}
 
 
@router.delete("/events/{event_id}")
def delete_event(event_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Event not found")
    event = db.query(AthleteEvent).filter(AthleteEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    verify_token_belongs_to_user(str(event.user_id), authorization)
    db.delete(event)
    db.commit()
    return {"status": "deleted"}
 
 
class CoachOutreachIn(BaseModel):
    user_id: str
    sport: str = Field(max_length=100)
    level: str = Field(max_length=100)
    career_direction: str = Field(max_length=100)
    achievements: str = Field(default="", max_length=4000)
    target_description: str = Field(max_length=2000)
    org_name: str = Field(max_length=300)
    roadmap_stage: int | None = None
    roadmap_stage_title: str | None = Field(default=None, max_length=300)
 
 
@router.post("/outreach")
def create_outreach(payload: CoachOutreachIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Drafts a real email and cold-call script for reaching a coach or
    staff member, and stores it as a real draft - review/edit/send
    from here, same lifecycle as every other outreach draft in the
    app. Never invents a specific named person - only describes the
    TYPE of contact and gives a real, usable script.
    """
    verify_token_belongs_to_user(payload.user_id, authorization)
    require_feature(db, payload.user_id, "outreach_drafting")
    rate_limit_by_tier(db, payload.user_id, "outreach-draft", per_action_limit=200)
    if not payload.sport.strip():
        raise HTTPException(status_code=400, detail="sport is required")
    if not payload.level.strip():
        raise HTTPException(status_code=400, detail="level is required")
    if not payload.target_description.strip():
        raise HTTPException(status_code=400, detail="target_description is required")
    if not payload.org_name.strip():
        raise HTTPException(status_code=400, detail="org_name is required")
 
    # Checked before the AI draft call, not after - this is a cheap,
    # fast, local check that can fail independently of the draft.
    # Running it first means a failed guess never discards an
    # already-completed, real AI generation that cost real time to
    # produce.
    guess = guess_contact_emails(payload.org_name)
    if not guess.get("candidates"):
        raise HTTPException(status_code=400, detail="Could not guess a contact address for this program")
 
    try:
        drafted = draft_coach_outreach(
            client, payload.sport, payload.level, payload.career_direction,
            payload.achievements, payload.target_description,
        )
    except Exception as e:
        _log.warning("Could not generate outreach just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate outreach just now. Please try again.")
 
    outreach = AthleteOutreach(
        user_id=payload.user_id,
        target_description=payload.target_description,
        to_address=guess["candidates"][0],
        address_verified=False,
        subject=drafted["email_subject"],
        body=drafted["email_body"],
        cold_call_script=drafted["cold_call_script"],
        roadmap_stage=payload.roadmap_stage,
        roadmap_stage_title=payload.roadmap_stage_title,
    )
    db.add(outreach)
    db.commit()
    db.refresh(outreach)
    return {
        "outreach_id": str(outreach.id),
        "who_to_contact": drafted["who_to_contact"],
        "how_to_find": drafted["how_to_find"],
        "to_address": outreach.to_address,
        "subject": outreach.subject,
        "body": outreach.body,
        "cold_call_script": outreach.cold_call_script,
        "status": "drafted",
    }
 
 
@router.get("/outreach/{user_id}")
def list_outreach(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    rows = db.query(AthleteOutreach).filter(AthleteOutreach.user_id == user_id).order_by(AthleteOutreach.created_at.desc()).all()
    return [
        {
            "id": str(o.id), "target_description": o.target_description, "to_address": o.to_address,
            "subject": o.subject, "body": o.body, "cold_call_script": o.cold_call_script,
            "roadmap_stage": o.roadmap_stage, "roadmap_stage_title": o.roadmap_stage_title,
            "status": o.status, "created_at": o.created_at.isoformat(),
        }
        for o in rows
    ]
 
 
class EditOutreachIn(BaseModel):
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=10000)
    to_address: str | None = Field(default=None, max_length=300)
 
 
@router.patch("/outreach/{outreach_id}")
def edit_outreach(outreach_id: str, payload: EditOutreachIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(outreach_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    outreach = db.query(AthleteOutreach).filter(AthleteOutreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    verify_token_belongs_to_user(str(outreach.user_id), authorization)
    if outreach.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent, cannot edit")
    if payload.subject is not None:
        outreach.subject = payload.subject
    if payload.body is not None:
        outreach.body = payload.body
    if payload.to_address is not None:
        outreach.to_address = payload.to_address
        outreach.address_verified = False
    db.commit()
    return {"status": "updated"}
 
 
@router.post("/outreach/{outreach_id}/send")
def send_outreach(outreach_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(outreach_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    outreach = db.query(AthleteOutreach).filter(AthleteOutreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    verify_token_belongs_to_user(str(outreach.user_id), authorization)
    if outreach.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent")
    try:
        send_email(outreach.to_address, outreach.subject, outreach.body)
        outreach.status = "sent"
        db.commit()
        return {"status": "sent", "to_address": outreach.to_address}
    except Exception as e:
        outreach.status = "failed"
        db.commit()
        _log.warning("Send failed - %s", e)
        raise HTTPException(status_code=502, detail="Send failed. Please try again.")
 
 
class ClipEditPlanIn(BaseModel):
    user_id: Optional[str] = None
    sport: str = Field(max_length=100)
    level: str = Field(max_length=100)
    career_direction: str = Field(max_length=100)
    clips_description: str = Field(max_length=4000)
    target_schools: str = Field(default="", max_length=1000)
 
 
class DetectHighlightsIn(BaseModel):
    user_id: Optional[str] = None
    video_url: str = Field(max_length=2000)
 
 
@router.post("/edit-plan")
def edit_plan(payload: ClipEditPlanIn, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Not real video editing or processing - there's no video hosting
    infrastructure in this stack. This is a real, specific edit PLAN
    grounded in the athlete's own description of their footage, for
    them to execute in whatever editor they already use.
    """
    # Meter against the caller's OWN token subject, always (see content_coach): a
    # body user_id under require_valid_token could bypass the cap by omission or bill
    # this paid AI call to another user.
    rate_limit_by_tier(db, _auth["sub"], "athlete-content", per_action_limit=300)
    if not payload.sport.strip():
        raise HTTPException(status_code=400, detail="sport is required")
    if not payload.level.strip():
        raise HTTPException(status_code=400, detail="level is required")
    if not payload.clips_description.strip():
        raise HTTPException(status_code=400, detail="clips_description is required")
    try:
        plan = generate_clip_edit_plan(
            client, payload.sport, payload.level, payload.career_direction,
            payload.clips_description, target_schools=payload.target_schools,
        )
    except Exception as e:
        _log.warning("Could not generate an edit plan just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate an edit plan just now. Please try again.")
    return plan
 
 
class AthleteRoadmapIn(BaseModel):
    user_id: str
    sport: str = Field(max_length=100)
    level: str = Field(max_length=100)
    career_direction: str = Field(max_length=100)
    achievements: str = Field(default="", max_length=4000)
 
 
@router.post("/roadmap")
def create_athlete_roadmap(payload: AthleteRoadmapIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Generates and persists a real roadmap for this athlete -
    replaces any previous one on regeneration, same behavior as the
    candidate roadmap endpoint.
    """
    verify_token_belongs_to_user(payload.user_id, authorization)
    rate_limit_by_tier(db, payload.user_id, "athlete-roadmap", per_action_limit=300)
    if not payload.sport.strip():
        raise HTTPException(status_code=400, detail="sport is required")
    if not payload.level.strip():
        raise HTTPException(status_code=400, detail="level is required")
    if payload.career_direction not in VALID_DIRECTIONS:
        raise HTTPException(status_code=400, detail=f"career_direction must be one of {VALID_DIRECTIONS}")
    try:
        roadmap = generate_athlete_roadmap(
            client, payload.sport, payload.level, payload.career_direction, payload.achievements
        )
    except Exception as e:
        _log.warning("Could not generate a roadmap just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate a roadmap just now. Please try again.")
 
    db.query(AthleteRoadmapMilestone).filter(AthleteRoadmapMilestone.user_id == payload.user_id).delete()
    db.query(AthleteRoadmapSummary).filter(AthleteRoadmapSummary.user_id == payload.user_id).delete()
 
    summary_row = AthleteRoadmapSummary(user_id=payload.user_id, summary=roadmap["summary"])
    db.add(summary_row)
 
    milestone_rows = []
    for m in roadmap["milestones"]:
        row = AthleteRoadmapMilestone(
            user_id=payload.user_id,
            title=m["title"], description=m.get("description"),
            success_criteria=m.get("success_criteria"), estimated_timeframe=m.get("estimated_timeframe"),
            first_action=m.get("first_action"), resource=m.get("resource"), risk=m.get("risk"),
            if_it_works=m.get("if_it_works"), if_it_stalls=m.get("if_it_stalls"),
            target_stage=m["stage"], status="planned",
        )
        db.add(row)
        milestone_rows.append(row)
 
    from sqlalchemy.exc import IntegrityError
    try:
        db.commit()
    except IntegrityError:
        # Concurrent first-time athlete-roadmap generation for this user won the
        # AthleteRoadmapSummary row (user_id is its PRIMARY KEY); this run's rows
        # rolled back with the failed commit. Return the winner's persisted roadmap
        # (this same athlete's equally-valid plan) instead of 500-ing on a
        # double-click - the same check-then-insert race the rest of the codebase
        # guards. Re-queried (not the rolled-back in-memory rows) so the ids are real.
        db.rollback()
        win_ms = (
            db.query(AthleteRoadmapMilestone)
            .filter(AthleteRoadmapMilestone.user_id == payload.user_id)
            .order_by(AthleteRoadmapMilestone.target_stage)
            .all()
        )
        win_sum = db.query(AthleteRoadmapSummary).filter(AthleteRoadmapSummary.user_id == payload.user_id).first()
        return {
            "summary": win_sum.summary if win_sum else roadmap["summary"],
            "milestones": [
                {
                    "id": str(r.id), "title": r.title, "description": r.description,
                    "success_criteria": r.success_criteria, "estimated_timeframe": r.estimated_timeframe,
                    "first_action": r.first_action, "resource": r.resource, "risk": r.risk,
                    "if_it_works": r.if_it_works, "if_it_stalls": r.if_it_stalls,
                    "stage": r.target_stage, "status": r.status,
                }
                for r in win_ms
            ],
        }
    for row in milestone_rows:
        db.refresh(row)
 
    return {
        "summary": roadmap["summary"],
        "milestones": [
            {
                "id": str(r.id), "title": r.title, "description": r.description,
                "success_criteria": r.success_criteria, "estimated_timeframe": r.estimated_timeframe,
                "first_action": r.first_action, "resource": r.resource, "risk": r.risk,
                "if_it_works": r.if_it_works, "if_it_stalls": r.if_it_stalls,
                "stage": r.target_stage, "status": r.status,
            }
            for r in milestone_rows
        ],
    }
 
 
@router.get("/roadmap/{user_id}")
def get_athlete_roadmap(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No roadmap generated yet for this user")
    summary_row = db.query(AthleteRoadmapSummary).filter(AthleteRoadmapSummary.user_id == user_id).first()
    if not summary_row:
        raise HTTPException(status_code=404, detail="No roadmap generated yet for this user")
    milestones = (
        db.query(AthleteRoadmapMilestone)
        .filter(AthleteRoadmapMilestone.user_id == user_id)
        .order_by(AthleteRoadmapMilestone.target_stage)
        .all()
    )
    return {
        "summary": summary_row.summary,
        "milestones": [
            {
                "id": str(m.id), "title": m.title, "description": m.description,
                "success_criteria": m.success_criteria, "estimated_timeframe": m.estimated_timeframe,
                "first_action": m.first_action, "resource": m.resource, "risk": m.risk,
                "if_it_works": m.if_it_works, "if_it_stalls": m.if_it_stalls,
                "stage": m.target_stage, "status": m.status,
            }
            for m in milestones
        ],
    }
 
 
class MilestoneStatusIn(BaseModel):
    status: str
    reflection: str | None = Field(default=None, max_length=4000)
 
 
@router.post("/roadmap/milestone/{milestone_id}/status")
def update_milestone_status(milestone_id: str, payload: MilestoneStatusIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Marks real progress on one milestone.
 
    When status genuinely transitions to "done" and the person
    provides a real reflection in the same request, this also
    creates a genuine, linked Waypoint journal entry - tagged to
    this exact milestone's real stage and title. Mirrors the
    identical, already-proven capability on the candidate side's
    roadmap.py exactly - a gap that genuinely existed here until now,
    the same one just found and fixed on the frontend. Entirely
    optional - a bare status update with no reflection behaves
    exactly as it always has.
    """
    import uuid as uuid_module
    if payload.status not in {"planned", "in_progress", "done"}:
        raise HTTPException(status_code=400, detail="status must be planned, in_progress, or done")
    try:
        uuid_module.UUID(milestone_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Milestone not found")
    milestone = db.query(AthleteRoadmapMilestone).filter(AthleteRoadmapMilestone.id == milestone_id).first()
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")
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
    return {"status": "updated", "milestone_status": milestone.status, "journal_entry_id": journal_entry_id}
 
 
class DetectHighlightsIn(BaseModel):
    user_id: Optional[str] = None
    video_url: str = Field(max_length=2000)
    sport: str = Field(default="", max_length=100)
 
 
@router.post("/detect-highlights")
def detect_highlights(payload: DetectHighlightsIn, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    """Auto-detect high-activity moments in a video the athlete links by URL.
 
    HONEST SCOPE: the computer-vision inference runs via Roboflow on a
    GPU-capable deployment with ROBOFLOW_API_KEY set. Where that isn't
    configured (e.g. a plain web dyno), this returns available=False with an
    honest note and zero fabricated moments - the athlete can still use the
    clip-planning workshop. Every returned moment is a real detection with a
    real timestamp; nothing is invented.
    """
    # Meter under the dedicated "highlight-detection" key, keyed to the CALLER'S OWN
    # token subject - never a body-supplied user_id. Previously this metered against
    # payload.user_id and ONLY when it was present, which was doubly exploitable
    # under require_valid_token (which doesn't tie the token to a body user_id): a
    # caller could bypass the cap entirely just by OMITTING user_id, or charge the
    # expensive Roboflow CV inference against another user by passing their id.
    # FEATURE_DAILY_CAPS caps this low (free 2, pro 15, max 100) precisely because
    # the CV inference is genuinely expensive, so the cap must always apply to the
    # real caller.
    rate_limit_by_tier(db, _auth["sub"], "highlight-detection", per_action_limit=100)
    if not payload.video_url.strip():
        raise HTTPException(status_code=400, detail="video_url is required")
    try:
        return detect_highlights_from_url(payload.video_url.strip(), sport=payload.sport)
    except Exception as e:
        # never 500 into a fabricated result - return an honest failure
        return {"available": False, "moments": [], "note": f"Detection could not run: {e}. Use the clip-planning workshop.", "model_id": None}
 
