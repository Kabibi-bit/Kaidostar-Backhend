import os
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Header, UploadFile, File, Form
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit, rate_limit_by_tier
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import ResumeEntry, ResumeDocument, Profile
from app.services.timeutil import utcnow
 
_log = logging.getLogger("kaidostar")
router = APIRouter(prefix="/resume", tags=["resume"])
 
 
@router.post("/ingest")
async def ingest_resume(
    user_id: str = Form(...),
    text: str = Form(None),
    url: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
    authorization: str = Header(None),
):
    """The "skip the survey - just give us your resume" fast path.
 
    Accepts an uploaded file (PDF / .docx / .txt), pasted text, OR a link, pulls
    out the plain text, and asks the model to EXTRACT a profile + the person's
    real experience entries (never inventing anything - see the resume_profile
    task and resume_ingest.parse_resume_profile_json). Returns a profile patch
    the client saves before sending the person straight into the job search.
    """
    import uuid as uuid_module
    from app.services.resume_ingest import (
        extract_resume_text, fetch_url_text, parse_resume_profile_json,
        ResumeIngestError, MAX_RESUME_CHARS, MAX_FILE_BYTES,
    )
    from app.services.ai_assist import run_assist
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    verify_token_belongs_to_user(user_id, authorization)
 
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
 
    # Assemble the resume text from whichever input was given.
    resume_text = (text or "").strip()
    if file is not None:
        raw = await file.read()
        if len(raw) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="That file is too large (max 4 MB).")
        try:
            extracted = extract_resume_text(file.filename or "", raw)
        except ResumeIngestError as ve:
            # user_message is a curated, non-sensitive string written for display.
            raise HTTPException(status_code=422, detail=ve.user_message)
        resume_text = (resume_text + "\n\n" + extracted).strip() if resume_text else extracted.strip()
    elif url:
        try:
            fetched = fetch_url_text(url)
        except ResumeIngestError as ve:
            raise HTTPException(status_code=422, detail=ve.user_message)
        resume_text = (resume_text + "\n\n" + fetched).strip() if resume_text else fetched.strip()
 
    if not resume_text:
        raise HTTPException(status_code=400, detail="No resume text found - upload a PDF/Word/TXT file, paste your resume, or add a link.")
    resume_text = resume_text[:MAX_RESUME_CHARS]
 
    # Metered like the other paid AI calls; fails open (see rate_limit_by_tier).
    rate_limit_by_tier(db, user_id, "resume-ingest", per_action_limit=100)
 
    try:
        model_out = run_assist(client, "resume_profile", {"resume": resume_text}, {})
    except Exception as e:
        _log.warning("resume ingest model call failed - %s", e)
        raise HTTPException(status_code=502, detail="Couldn't read your resume just now. Please try again, or fill in the survey.")
 
    try:
        profile, entries = parse_resume_profile_json(model_out)
    except ValueError:
        # The model returned something unparseable - don't ship a fake empty
        # profile as if it worked; tell the client so it can fall back.
        raise HTTPException(status_code=422, detail="Couldn't make sense of that resume - try pasting the text, or fill in the survey instead.")
 
    return {"profile": profile, "entries": entries, "chars": len(resume_text)}
 
 
class TailorToJdIn(BaseModel):
    jd: str = Field(max_length=12000)
    # The current builder entries (so tailoring matches exactly what the person
    # sees, including just-imported or just-added ones). Falls back to the DB.
    entries: list[dict] = Field(default_factory=list)
 
 
@router.post("/{user_id}/tailor-to-jd")
def tailor_resume_for_jd(user_id: str, payload: TailorToJdIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Jobright-style per-job tailoring: rewrite the person's REAL resume to
    foreground what this specific job asks for, honestly (see
    resume_builder.tailor_resume_to_jd - it rephrases only, never invents, and
    the fabrication net flags any number the rewrite added). Works on whatever
    entries the builder currently has (sent in the body), or the saved ones.
    """
    import uuid as uuid_module
    from app.services.resume_builder import tailor_resume_to_jd
 
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="No profile for this user")
    rate_limit_by_tier(db, user_id, "resume-tailor", per_action_limit=200)
 
    # Prefer the entries the client sent (current builder state), clipped for size;
    # otherwise fall back to the saved resume entries for this user.
    entries = []
    for e in (payload.entries or [])[:40]:
        if not isinstance(e, dict):
            continue
        entries.append({
            "id": str(e.get("id") or "")[:80],
            "entry_type": str(e.get("entry_type") or "work")[:40],
            "title": str(e.get("title") or "")[:300],
            "org": str(e.get("org") or "")[:300],
            "start_date": str(e.get("start_date") or "")[:50],
            "end_date": str(e.get("end_date") or "")[:50],
            "raw_description": str(e.get("raw_description") or "")[:5000],
        })
    if not entries:
        rows = (
            db.query(ResumeEntry)
            .filter(ResumeEntry.user_id == user_id)
            .order_by(ResumeEntry.display_order, ResumeEntry.created_at)
            .all()
        )
        entries = [{"id": str(r.id), "entry_type": r.entry_type, "title": r.title, "org": r.org,
                    "start_date": r.start_date, "end_date": r.end_date, "raw_description": r.raw_description} for r in rows]
    if not entries:
        raise HTTPException(status_code=400, detail="Add or import at least one real resume entry before tailoring.")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    profile_dict = {"northstar": profile.northstar if profile else "", "skills": (profile.skills or "") if profile else ""}
 
    result = tailor_resume_to_jd(client, entries, payload.jd, profile_dict)
    return result
 
 
class TailorDownloadIn(BaseModel):
    summary: str | None = Field(default="", max_length=2000)
    skills: str | None = Field(default="", max_length=3000)
    entries: list[dict] = Field(default_factory=list)
 
 
@router.post("/{user_id}/tailor-to-jd/download")
def download_tailored_to_jd(user_id: str, payload: TailorDownloadIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Download the job-tailored resume as a real .docx. Reuses the same document
    generator as the master resume - it only lays out the tailored content the
    person just reviewed on screen, it generates nothing new."""
    from fastapi import Response
    from app.models.db_models import User
    from app.services.resume_docx import generate_resume_document
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No user found")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user found")
 
    polished_entries = []
    for e in (payload.entries or [])[:40]:
        if not isinstance(e, dict):
            continue
        bullets = [str(b)[:2000] for b in (e.get("bullets") or []) if isinstance(b, str) and b.strip()][:8]
        polished_entries.append({
            "entry_type": str(e.get("entry_type") or "work")[:40],
            "title": str(e.get("title") or "")[:300],
            "org": str(e.get("org") or "")[:300],
            "dates": str(e.get("dates") or "")[:100],
            "bullets": bullets,
            "flagged_numbers": [],
        })
    if not polished_entries:
        raise HTTPException(status_code=400, detail="Nothing to download yet - tailor your resume to a job first.")
 
    skills_list = [s.strip() for s in str(payload.skills or "").split(",") if s.strip()][:40]
    docx_bytes = generate_resume_document(
        email=user.email, summary_line=(payload.summary or ""),
        polished_entries=polished_entries, skills=skills_list,
    )
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=tailored_resume.docx"},
    )
 
 
class ResumeEntryIn(BaseModel):
    user_id: str
    entry_type: str = Field(max_length=50)  # work / education / project
    title: str = Field(max_length=300)
    org: str | None = Field(default=None, max_length=300)
    start_date: str | None = Field(default=None, max_length=50)
    end_date: str | None = Field(default=None, max_length=50)
    raw_description: str = Field(max_length=5000)
    display_order: int = 0
 
 
class ResumeEntryUpdate(BaseModel):
    entry_type: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=300)
    org: str | None = Field(default=None, max_length=300)
    start_date: str | None = Field(default=None, max_length=50)
    end_date: str | None = Field(default=None, max_length=50)
    raw_description: str | None = Field(default=None, max_length=5000)
    display_order: int | None = None
 
 
@router.post("/entries")
def create_entry(payload: ResumeEntryIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Adds one real, user-provided fact about their experience - the
    only kind of input this feature accepts. Nothing here is ever
    generated; raw_description is always the person's own words.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    verify_token_belongs_to_user(payload.user_id, authorization)
    entry = ResumeEntry(
        user_id=payload.user_id, entry_type=payload.entry_type, title=payload.title,
        org=payload.org, start_date=payload.start_date, end_date=payload.end_date,
        raw_description=payload.raw_description, display_order=payload.display_order,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": str(entry.id)}
 
 
@router.get("/entries/{user_id}")
def list_entries(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    entries = (
        db.query(ResumeEntry)
        .filter(ResumeEntry.user_id == user_id)
        .order_by(ResumeEntry.display_order, ResumeEntry.created_at)
        .all()
    )
    return {
        "entries": [
            {
                "id": str(e.id), "entry_type": e.entry_type, "title": e.title, "org": e.org,
                "start_date": e.start_date, "end_date": e.end_date,
                "raw_description": e.raw_description, "display_order": e.display_order,
            }
            for e in entries
        ]
    }
 
 
@router.patch("/entries/{entry_id}")
def update_entry(entry_id: str, payload: ResumeEntryUpdate, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry = db.query(ResumeEntry).filter(ResumeEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    verify_token_belongs_to_user(str(entry.user_id), authorization)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    entry.updated_at = utcnow()
    db.commit()
    return {"updated": True}
 
 
@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry = db.query(ResumeEntry).filter(ResumeEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    verify_token_belongs_to_user(str(entry.user_id), authorization)
    db.delete(entry)
    db.commit()
    return {"deleted": True}
 
 
@router.post("/generate/{user_id}")
def generate_resume(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    rate_limit_by_tier(db, user_id, "resume-generate", per_action_limit=200)
    """Polishes the person's own real entries into resume language -
    never generates work history from scratch. Requires at least one
    real entry; there is no fallback that invents one.
    """
    from app.services.resume_builder import polish_resume_entry, generate_resume_summary
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Add at least one real work, education, or project entry before generating a resume.")
 
    entries = (
        db.query(ResumeEntry)
        .filter(ResumeEntry.user_id == user_id)
        .order_by(ResumeEntry.display_order, ResumeEntry.created_at)
        .all()
    )
    if not entries:
        raise HTTPException(status_code=400, detail="Add at least one real work, education, or project entry before generating a resume.")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    profile_dict = {"northstar": profile.northstar if profile else ""}
 
    entry_dicts = [
        {"id": str(e.id), "entry_type": e.entry_type, "title": e.title, "org": e.org,
         "start_date": e.start_date, "end_date": e.end_date, "raw_description": e.raw_description}
        for e in entries
    ]
 
    try:
        polished_entries = []
        entries_snapshot = []
        for e in entry_dicts:
            try:
                result = polish_resume_entry(client, e)
            except Exception as polish_error:
                # One entry's transient failure (a temporary API issue)
                # must not fail the person's entire resume request when
                # their other entries would have succeeded fine - falls
                # back to their own real, honest raw description as a
                # single bullet rather than silently dropping this real
                # work experience from their resume.
                print(f"  Polishing failed for entry '{e['title']}', falling back to their raw description: {polish_error}")
                result = {"bullets": [e["raw_description"]] if e["raw_description"] else [], "flagged_numbers": []}
            polished_entries.append({
                "entry_id": e["id"], "title": e["title"], "org": e["org"],
                "dates": f'{e["start_date"] or ""} - {e["end_date"] or ""}'.strip(" -"),
                "bullets": result["bullets"], "flagged_numbers": result["flagged_numbers"],
            })
            entries_snapshot.append({"entry_id": e["id"], "raw_description": e["raw_description"]})
        try:
            summary_result = generate_resume_summary(client, profile_dict, entry_dicts)
        except Exception as summary_error:
            # A summary-generation failure must not discard every entry
            # that was just successfully polished above - the same
            # principle as the per-entry fallback, applied to the one
            # remaining single point of failure in this same request.
            print(f"  Summary generation failed, falling back to no summary line rather than losing the polished entries: {summary_error}")
            summary_result = {"summary": "", "flagged_numbers": []}
        summary_line = summary_result["summary"]
        summary_flagged_numbers = summary_result["flagged_numbers"]
    except Exception as e:
        _log.warning("Could not generate the resume just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate the resume just now. Please try again.")
 
    doc = db.query(ResumeDocument).filter(ResumeDocument.user_id == user_id).first()
    if doc:
        doc.summary_line = summary_line
        doc.polished_entries = polished_entries
        doc.entries_snapshot = entries_snapshot
        doc.generated_at = utcnow()
        db.commit()
    else:
        from sqlalchemy.exc import IntegrityError
        doc = ResumeDocument(
            user_id=user_id, summary_line=summary_line,
            polished_entries=polished_entries, entries_snapshot=entries_snapshot,
        )
        db.add(doc)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent first-time generate for this user won the row (user_id is
            # the PRIMARY KEY of resume_documents), so this bare insert would otherwise
            # 500 on a double-click. Roll back and return this run's freshly polished
            # result - the winner persisted this same user's equally-valid resume, and
            # a page refresh (GET /resume) shows the stored copy. Mirrors the
            # check-then-insert IntegrityError handling used across the codebase.
            db.rollback()
 
    # any_flags now also covers the summary line, not just bullets -
    # a fabricated "5+ years of experience" in the summary is exactly
    # as real a problem as a fabricated number in a bullet, and was
    # previously invisible to this check entirely.
    any_bullet_flags = any(pe["flagged_numbers"] for pe in polished_entries)
    any_flags = any_bullet_flags or bool(summary_flagged_numbers)
    if any_bullet_flags and summary_flagged_numbers:
        review_note = "One or more bullets AND the summary line include a number that wasn't in what you originally wrote - double check those before using this."
    elif summary_flagged_numbers:
        review_note = "The summary line includes a number that wasn't in what you originally wrote - double check it before using this."
    elif any_bullet_flags:
        review_note = "One or more bullets include a number that wasn't in what you originally wrote - double check those before using this."
    else:
        review_note = None
    return {
        "summary_line": summary_line,
        "entries": polished_entries,
        "review_note": review_note,
    }
 
 
@router.get("/{user_id}")
def get_resume(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        return {"summary_line": None, "entries": [], "generated_at": None}
    doc = db.query(ResumeDocument).filter(ResumeDocument.user_id == user_id).first()
    if not doc:
        return {"summary_line": None, "entries": [], "generated_at": None}
    return {"summary_line": doc.summary_line, "entries": doc.polished_entries, "generated_at": doc.generated_at.isoformat() if doc.generated_at else None}
 
 
@router.get("/{user_id}/ats-check")
def get_ats_alignment(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Real, deterministic keyword coverage between the resume's
    actual content and the person's stated goal/skills - reuses the
    same synonym-aware matching already proven in the core matching
    engine, so this stays in sync with that fix rather than drifting
    from a second, separately-maintained copy of the same logic.
    """
    from app.services.resume_builder import check_ats_alignment
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    entry_dicts = [{"title": e.title, "raw_description": e.raw_description} for e in entries]
    profile_dict = {"northstar": profile.northstar if profile else "", "skills": profile.skills if profile else ""}
    return check_ats_alignment(profile_dict, entry_dicts)
 
 
@router.get("/{user_id}/tailor/{listing_id}")
def tailor_resume_for_listing(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Which of the person's real entries are most worth leading with
    for this specific listing. Never changes what an entry says, only
    how they're ordered - the honest content is identical regardless
    of which job this is for.
    """
    import uuid as uuid_module
    from app.services.resume_builder import rank_entries_for_listing
    from app.models.db_models import Listing
 
    try:
        uuid_module.UUID(listing_id)
        uuid_module.UUID(user_id)
    except ValueError:
        # A malformed listing_id or user_id (not just a valid-but-
        # nonexistent one) would otherwise reach the DB query below
        # and raise a raw, unhandled database exception - verified
        # directly against real SQLAlchemy/psycopg2 behavior before
        # adding this check, since both are user-controllable URL
        # path parameters, not something this endpoint can trust is
        # always well-formed. ResumeEntry.user_id is the identical
        # UUID(as_uuid=True) column type as Listing.id, so the same
        # risk applies to both, not just the one caught first.
        raise HTTPException(status_code=404, detail="Listing not found")
 
    entries = (
        db.query(ResumeEntry)
        .filter(ResumeEntry.user_id == user_id)
        .order_by(ResumeEntry.display_order, ResumeEntry.created_at)
        .all()
    )
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    entry_dicts = [
        {"id": str(e.id), "title": e.title, "org": e.org, "start_date": e.start_date,
         "end_date": e.end_date, "raw_description": e.raw_description}
        for e in entries
    ]
    from app.services.feed_common import listing_tags
    ranked = rank_entries_for_listing(entry_dicts, {"tags": listing_tags(db, listing)})
    return {"entries": ranked}
 
 
@router.get("/{user_id}/skills")
def get_skills_section(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Only ever lists skills the person explicitly typed as their
    own; anything genuinely implied by their real entries but not
    already in that list comes back separately as a suggestion, never
    auto-added to the claimed list. See build_skills_section's
    docstring for why a skills section is more fabrication-sensitive
    than a bullet point, not less.
    """
    from app.services.resume_builder import build_skills_section
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    entry_dicts = [{"raw_description": e.raw_description} for e in entries]
    profile_dict = {"skills": profile.skills if profile else ""}
    return build_skills_section(profile_dict, entry_dicts)
 
 
class SkillAddIn(BaseModel):
    skill: str = Field(max_length=200)
 
 
@router.post("/{user_id}/skills/add")
def add_suggested_skill(user_id: str, body: SkillAddIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The only sanctioned way a suggested_additions entry moves into
    the person's explicit, claimed skills list - a deliberate action
    on a specific skill, never an automatic promotion. There's no
    general profile-edit endpoint elsewhere in this codebase; this is
    intentionally narrow (just this one field, just this one
    operation) rather than a broader endpoint this UI action doesn't
    need. Returns the freshly recomputed skills section so the caller
    can re-render immediately without a second round trip.
    """
    from app.services.resume_builder import add_skill_to_skills_string, build_skills_section
    import uuid as uuid_module
 
    if not body.skill or not body.skill.strip():
        raise HTTPException(status_code=400, detail="skill cannot be empty")
    if "," in body.skill:
        # Skills are stored as a single comma-separated string
        # throughout this codebase - a comma inside one intended
        # skill name would silently split into two separate, wrong
        # entries rather than crash, so this is rejected explicitly
        # rather than corrupt the person's real skills list quietly.
        raise HTTPException(status_code=400, detail="skill cannot contain a comma - add each skill separately")
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile found for this user")
 
    profile.skills = add_skill_to_skills_string(profile.skills, body.skill)
    db.commit()
 
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    entry_dicts = [{"raw_description": e.raw_description} for e in entries]
    return build_skills_section({"skills": profile.skills}, entry_dicts)
 
 
@router.post("/{user_id}/skills/remove")
def remove_explicit_skill(user_id: str, body: SkillAddIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The other half of the add endpoint above - removing a skill
    someone added by mistake, or one they no longer want claimed,
    should be exactly as easy as adding it was. Without this, the
    one-click add action would be one-way: easy to add a skill with
    a single click, no way to undo it short of editing the raw
    comma-separated string some other way. Reuses SkillAddIn since
    the payload shape (just a skill name) is identical.
    """
    from app.services.resume_builder import remove_skill_from_skills_string, build_skills_section
    import uuid as uuid_module
 
    if not body.skill or not body.skill.strip():
        raise HTTPException(status_code=400, detail="skill cannot be empty")
    if "," in body.skill:
        raise HTTPException(status_code=400, detail="skill cannot contain a comma - remove each skill separately")
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile found for this user")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile found for this user")
 
    profile.skills = remove_skill_from_skills_string(profile.skills, body.skill)
    db.commit()
 
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    entry_dicts = [{"raw_description": e.raw_description} for e in entries]
    return build_skills_section({"skills": profile.skills}, entry_dicts)
 
 
@router.get("/{user_id}/download")
def download_resume_docx(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Real, downloadable .docx - the actual end product every other
    resume endpoint has been building toward. Uses the person's real,
    most recently generated resume (via POST /generate/{user_id}) and
    their real, explicitly-claimed skills - never suggested_additions,
    since those are inferred, not stated by the person themselves.
    """
    from fastapi import Response
    from app.models.db_models import User
    from app.services.resume_builder import build_skills_section
    from app.services.resume_docx import generate_resume_document
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile found for this user")
 
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user found")
 
    doc = db.query(ResumeDocument).filter(ResumeDocument.user_id == user_id).first()
    if not doc or not doc.polished_entries:
        raise HTTPException(status_code=404, detail="No generated resume yet - generate one first")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    entry_dicts = [{"raw_description": e.raw_description} for e in entries]
    skills_section = build_skills_section({"skills": profile.skills if profile else ""}, entry_dicts)
 
    docx_bytes = generate_resume_document(
        email=user.email,
        summary_line=doc.summary_line,
        polished_entries=doc.polished_entries,
        skills=skills_section["skills"],
    )
 
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=resume.docx"},
    )
 
 
@router.get("/{user_id}/download/tailored/{listing_id}")
def download_tailored_resume_docx(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """A real, downloadable .docx tailored for one specific listing -
    connects two pieces that already existed separately: the real
    relevance-ranking already proven in tailor_resume_for_listing
    above, and the real .docx generation above. Never re-polishes or
    changes what any bullet says - the honest content is identical to
    the master resume, only which entries appear first changes,
    exactly the same discipline the in-app tailor view already
    follows. Reuses generate_resume_document completely unchanged;
    tailoring is entirely just reordering the same polished_entries
    list before handing it to the same, already-tested generator.
    """
    from fastapi import Response
    from app.models.db_models import User, Listing
    from app.services.resume_builder import build_skills_section, rank_entries_for_listing
    from app.services.resume_docx import generate_resume_document
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
        uuid_module.UUID(listing_id)
    except ValueError:
        # A malformed listing_id or user_id (not just a valid-but-
        # nonexistent one) would otherwise reach the DB query below
        # and raise a raw, unhandled database exception - the exact
        # same real risk already found and fixed in
        # tailor_resume_for_listing above, so it's checked identically
        # here rather than assumed to only matter there.
        raise HTTPException(status_code=404, detail="Listing not found")
 
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user found")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    doc = db.query(ResumeDocument).filter(ResumeDocument.user_id == user_id).first()
    if not doc or not doc.polished_entries:
        raise HTTPException(status_code=404, detail="No generated resume yet - generate one first")
 
    raw_entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    raw_entry_dicts = [{"id": str(e.id), "title": e.title, "raw_description": e.raw_description} for e in raw_entries]
    from app.services.feed_common import listing_tags
    listing_dict = {"tags": listing_tags(db, listing)}
    ranked = rank_entries_for_listing(raw_entry_dicts, listing_dict)
    rank_order = {r["id"]: i for i, r in enumerate(ranked)}
 
    # Reorder the REAL, already-polished entries to match the real
    # relevance ranking - an entry whose id isn't in rank_order (a
    # genuinely plausible edge case if an entry was deleted after the
    # resume was last generated) sorts last rather than crashing.
    tailored_entries = sorted(
        doc.polished_entries,
        key=lambda e: rank_order.get(e.get("entry_id"), len(rank_order)),
    )
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    entry_dicts_for_skills = [{"raw_description": e.raw_description} for e in raw_entries]
    skills_section = build_skills_section({"skills": profile.skills if profile else ""}, entry_dicts_for_skills)
 
    docx_bytes = generate_resume_document(
        email=user.email,
        summary_line=doc.summary_line,
        polished_entries=tailored_entries,
        skills=skills_section["skills"],
    )
 
    safe_org = "".join(c for c in (listing.org or "resume") if c.isalnum() or c in " -_").strip().replace(" ", "_") or "resume"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={safe_org}_resume.docx"},
    )
 
 
@router.get("/{user_id}/cover-letter/{listing_id}")
def generate_cover_letter_for_listing(user_id: str, listing_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    # Meter this paid AI generation (was unmetered). Fails open; a cover letter is
    # the same cost class as an application draft, so it shares that tier cap.
    rate_limit_by_tier(db, user_id, "application-draft", per_action_limit=200)
    """A real cover letter for one specific listing, grounded only in
    the person's own real entries and stated goal - the concrete
    answer to a documented, verified competitor failure where their
    generator invented a fake personal connection to a company's
    markets/locations. See app/services/cover_letter.py for the full
    reasoning and the anti-fabrication discipline this follows.
    """
    from app.services.cover_letter import generate_cover_letter
    from app.models.db_models import Listing
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
        uuid_module.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    if not entries:
        raise HTTPException(status_code=400, detail="Add at least one real work, education, or project entry before generating a cover letter.")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    profile_dict = {"northstar": profile.northstar if profile else "", "skills": profile.skills if profile else ""}
    entry_dicts = [{"title": e.title, "org": e.org, "raw_description": e.raw_description} for e in entries]
    from app.services.feed_common import listing_text
    from app.services.feed_common import listing_tags
    listing_dict = {"title": listing.title, "org": listing.org, "tags": listing_tags(db, listing), "description": listing_text(db, listing)}
 
    result = generate_cover_letter(client, profile_dict, entry_dicts, listing_dict)
    return result
 
 
class UpdateBulletIn(BaseModel):
    entry_id: str
    bullet_index: int
    new_text: str = Field(max_length=2000)
 
 
@router.patch("/{user_id}/bullet")
def update_resume_bullet(user_id: str, body: UpdateBulletIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Lets a person directly edit one bullet in their already-
    generated resume - the concrete backend answer to a documented
    complaint that users wish they could edit an AI-tailored resume
    directly, rather than only being able to regenerate the whole
    thing. Re-checks which flagged numbers are still genuinely
    present across ALL bullets in this entry after the edit - editing
    away the one number that was flagged clears that warning, but a
    different, still-present flagged number in another bullet
    correctly keeps its own warning, mirroring the frontend's
    identical logic exactly.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No generated resume found")
 
    doc = db.query(ResumeDocument).filter(ResumeDocument.user_id == user_id).first()
    if not doc or not doc.polished_entries:
        raise HTTPException(status_code=404, detail="No generated resume found")
 
    entries = list(doc.polished_entries)
    entry = next((e for e in entries if e.get("entry_id") == body.entry_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Resume entry not found")
    if body.bullet_index < 0 or body.bullet_index >= len(entry.get("bullets", [])):
        raise HTTPException(status_code=400, detail="bullet_index is out of range for this entry")
 
    entry["bullets"][body.bullet_index] = body.new_text
    if entry.get("flagged_numbers"):
        entry["flagged_numbers"] = [n for n in entry["flagged_numbers"] if any(n in b for b in entry["bullets"])]
 
    doc.polished_entries = entries
    db.commit()
    db.refresh(doc)
    return {"entry_id": body.entry_id, "bullets": entry["bullets"], "flagged_numbers": entry.get("flagged_numbers", [])}
 
