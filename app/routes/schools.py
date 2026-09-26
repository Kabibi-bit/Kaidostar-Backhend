from fastapi import APIRouter, HTTPException, Depends, Query, Body
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Profile
from app.services.auth import require_auth_for_user
from app.services.rate_limit import rate_limit, rate_limit_by_tier
from app.services.schools import (
    search_schools,
    lookup_school,
    school_guidance_for_profile,
    generate_admissions_roadmap,
    essay_structure,
    admissions_deadline_context,
    admissions_assistant_context,
    admissions_readiness,
    admissions_list_balance,
    admissions_gap_radar,
    build_readiness_snapshot,
    compute_trajectory,
    derive_milestones,
    compute_consistency,
    weekly_focus,
    polish_analyze,
    brainstorm_outline,
    essay_rubric_review,
)
 
router = APIRouter(prefix="/schools", tags=["schools"])
 
 
def _load_student_profile(user_id: str, db: Session) -> dict:
    """Shared: validate the user_id, load the current profile, ensure it's on
    the admissions track, and return it as the plain dict the schools service
    expects. Raises the same HTTP errors every admissions route needs."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if not profile.is_student:
        raise HTTPException(status_code=400, detail="This profile is not on the admissions track")
 
    return {
        "intended_major": profile.intended_major,
        "grade_level": profile.grade_level,
        "target_schools": profile.target_schools,
        "interests": profile.interests,
        "student_achievements": getattr(profile, "student_achievements", None),
    }
 
 
# ---------------------------------------------------------------------------
# Public reference data (school mottos/facts are public - no auth needed)
# ---------------------------------------------------------------------------
 
@router.get("/search")
def schools_search(q: str = Query("", max_length=200)):
    """Autocomplete for the survey school picker. School names and mottos
    are public reference data, so this needs no auth - it's a directory
    lookup, not user data."""
    return {"results": search_schools(q)}
 
 
@router.get("/lookup")
def schools_lookup(name: str = Query("", max_length=200)):
    """Resolve one school name/alias to its curated profile, or null.
    Public reference data (same rationale as /search)."""
    return {"school": lookup_school(name)}
 
 
# ---------------------------------------------------------------------------
# Per-student admissions intelligence (auth-protected to that user)
# ---------------------------------------------------------------------------
 
@router.get("/guidance/{user_id}")
def schools_guidance(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The school-tailored admissions guidance for a specific student -
    each target school's real profile + guidance, plus an honest note for
    any school not in the curated set."""
    return school_guidance_for_profile(_load_student_profile(user_id, db))
 
 
@router.get("/roadmap/{user_id}")
def schools_roadmap(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The school-aware admissions roadmap for a student - branches
    US-holistic vs UK-course-specific on their anchor school, weaves in that
    school's real values, and stays honest about data depth. Deterministic;
    no fabricated per-school tactics."""
    return generate_admissions_roadmap(_load_student_profile(user_id, db))
 
 
@router.post("/essay/{user_id}")
def schools_essay(user_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """A school-aware application-essay scaffold for a student. Branches the
    US personal-narrative essay vs the UK subject-focused UCAS statement (the
    two are genuinely different), weaving in the anchor school's real values.
    Honest scaffolding only - never a written-for-you essay. Body may include
    an optional 'theme' string (the story/trait the essay should show)."""
    theme = ""
    if isinstance(payload, dict):
        theme = str(payload.get("theme", ""))[:300]
    return essay_structure(_load_student_profile(user_id, db), theme)
 
 
@router.get("/deadlines/{user_id}")
def schools_deadlines(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """School-aware application-deadline reminders for the student's target
    countries (real, well-known UCAS/ED/EA dates; no fabricated per-school
    specifics)."""
    return {"deadlines": admissions_deadline_context(_load_student_profile(user_id, db))}
 
 
@router.get("/assistant-context/{user_id}")
def schools_assistant_context(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The school-aware system prompt for an admissions AI guide, built from
    the student's profile and target schools. Lets a server-side assistant
    give the same school-specific, honest guidance the frontend Metis does."""
    return {"system": admissions_assistant_context(_load_student_profile(user_id, db))}
 
 
 
@router.get("/readiness/{user_id}")
def schools_readiness(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """X-factor: an honest, evidence-based read of where the student stands for
    EACH target school - a readiness band (never a fake admit probability), the
    real evidence behind it, and the single highest-leverage next move per
    school. Assembles activity signals from stored data where available."""
    profile = _load_student_profile(user_id, db)
    # Best-effort activity signals from stored records; readiness degrades
    # gracefully to profile-only evidence if these tables aren't populated.
    signals = {}
    try:
        from app.models.db_models import Application
        apps = db.query(Application).filter(Application.user_id == user_id).all()
        signals["tracked_count"] = len(apps)
    except Exception:
        pass
    return admissions_readiness(profile, signals)
 
 
 
@router.get("/list-balance/{user_id}")
def schools_list_balance(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """UNIQUE: is the student's school list realistic? An honest verdict on the
    list SHAPE (reach/target/likely mix) plus the specific structural fix -
    computed from verified tiers and the student's own readiness, not guessed."""
    profile = _load_student_profile(user_id, db)
    signals = {}
    try:
        from app.models.db_models import Application
        signals["tracked_count"] = db.query(Application).filter(Application.user_id == user_id).count()
    except Exception:
        pass
    result = admissions_list_balance(profile, signals)
    if result is None:
        raise HTTPException(status_code=404, detail="No target schools we have data on are set on this profile")
    return result
 
 
@router.get("/gap-radar/{user_id}")
def schools_gap_radar(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """UNIQUE: the single highest-leverage move that would strengthen the
    student's standing across the MOST of their target schools at once -
    whole-list optimization against their real profile."""
    profile = _load_student_profile(user_id, db)
    signals = {}
    try:
        from app.models.db_models import Application
        signals["tracked_count"] = db.query(Application).filter(Application.user_id == user_id).count()
    except Exception:
        pass
    result = admissions_gap_radar(profile, signals)
    if result is None:
        raise HTTPException(status_code=404, detail="No target schools we have data on are set on this profile")
    return result
 
 
 
def _snapshot_signals(user_id: str, db: Session) -> dict:
    signals = {}
    try:
        from app.models.db_models import Application
        signals["tracked_count"] = db.query(Application).filter(Application.user_id == user_id).count()
    except Exception:
        pass
    return signals
 
 
@router.post("/snapshot/{user_id}")
def schools_snapshot(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Record a timestamped readiness snapshot for the student's trajectory -
    but only if >12h since the last one OR their evidence actually changed, so
    the series reflects real progress, not repeated loads. This persistence is
    what makes the trajectory feature possible."""
    from datetime import datetime, timezone
    from app.models.db_models import AdmissionsSnapshot
    profile = _load_student_profile(user_id, db)
    snap = build_readiness_snapshot(profile, _snapshot_signals(user_id, db))
    if snap is None:
        raise HTTPException(status_code=404, detail="No target schools we have data on are set on this profile")
 
    last = (
        db.query(AdmissionsSnapshot)
        .filter(AdmissionsSnapshot.user_id == user_id)
        .order_by(AdmissionsSnapshot.created_at.desc())
        .first()
    )
    should_write = True
    if last is not None:
        ev_changed = (last.evidence or {}) != snap["evidence"]
        age_h = (datetime.now(timezone.utc) - (last.created_at.replace(tzinfo=timezone.utc) if last.created_at.tzinfo is None else last.created_at)).total_seconds() / 3600
        should_write = ev_changed or age_h > 12
    if should_write:
        row = AdmissionsSnapshot(user_id=user_id, avg=snap["avg"], per_school=snap["per_school"], evidence=snap["evidence"])
        db.add(row)
        db.commit()
    return {"recorded": should_write, "avg": snap["avg"]}
 
 
@router.get("/trajectory/{user_id}")
def schools_trajectory(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """THE UNIQUE ONE: the student's readiness trajectory over real time -
    momentum, what moved the needle, and pace vs runway. Something no stateless
    chatbot and no single meeting can produce. Reads persisted snapshots."""
    from app.models.db_models import AdmissionsSnapshot
    profile = _load_student_profile(user_id, db)
    rows = (
        db.query(AdmissionsSnapshot)
        .filter(AdmissionsSnapshot.user_id == user_id)
        .order_by(AdmissionsSnapshot.created_at.asc())
        .all()
    )
    snaps = [{"created_at": r.created_at, "avg": r.avg, "evidence": r.evidence or {}} for r in rows]
    return compute_trajectory(snaps, profile)
 
 
 
@router.get("/journey/{user_id}")
def schools_journey(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """THE compounding x-factor, in one call: the student's trajectory, the
    milestones they've earned, their consistency/streak, and this week's adaptive
    focus. All derived from their persisted snapshot history - the richness grows
    the longer they use the app, which no stateless assistant can match."""
    from app.models.db_models import AdmissionsSnapshot
    profile = _load_student_profile(user_id, db)
    rows = (
        db.query(AdmissionsSnapshot)
        .filter(AdmissionsSnapshot.user_id == user_id)
        .order_by(AdmissionsSnapshot.created_at.asc())
        .all()
    )
    snaps = [{"created_at": r.created_at, "avg": r.avg, "evidence": r.evidence or {}} for r in rows]
    signals = _snapshot_signals(user_id, db)
    return {
        "trajectory": compute_trajectory(snaps, profile),
        "milestones": derive_milestones(snaps),
        "consistency": compute_consistency(snaps),
        "weekly_focus": weekly_focus(profile, snaps, signals),
    }
 
 
 
@router.post("/essay-polish/{user_id}")
def schools_essay_polish(user_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    rate_limit_by_tier(db, user_id, "essay-polish", per_action_limit=200)
    """The honest humanizer: analyze the STUDENT'S OWN essay draft for clichés,
    AI-tells, vague words, and school-format misfit, returning concrete revision
    feedback. Does NOT rewrite the essay and is NOT a detector-evasion tool -
    the student revises in their own voice. Body: {'text': '<the draft>'}."""
    profile = _load_student_profile(user_id, db)
    text = ""
    if isinstance(payload, dict):
        text = str(payload.get("text", ""))[:20000]
    if len(text.strip()) < 120:
        raise HTTPException(status_code=400, detail="Provide at least a few sentences of the draft to analyze")
    prompt = str(payload.get("prompt", ""))[:500] if isinstance(payload, dict) else ""
    return {
        "rubric": essay_rubric_review(text, profile, prompt),
        "report": polish_analyze(text, profile),
    }
 
 
@router.post("/essay-brainstorm/{user_id}")
def schools_essay_brainstorm(user_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Assemble the student's OWN answers into a personal essay outline - helps
    them write a real essay without writing it for them. Body may include
    'moment', 'struggle', 'did', 'changed' (their answers)."""
    profile = _load_student_profile(user_id, db)
    answers = payload if isinstance(payload, dict) else {}
    answers = {k: str(answers.get(k, ""))[:2000] for k in ("moment", "struggle", "did", "changed")}
    return brainstorm_outline(profile, answers)
 
