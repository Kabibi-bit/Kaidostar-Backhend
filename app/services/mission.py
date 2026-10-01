"""Mission Control snapshot — the BACKEND computation behind the dashboard.
 
The Mission Control pages used to compute every number in the browser. This
module makes the dashboard genuinely server-backed: it takes the user's real
data (applications, logged outcomes, ranked matches, roadmap, saved count,
interview-prep items) and computes the same KPIs, funnel, conversions, search
metrics and growth/potential the pages show - so the numbers are authoritative
and identical across devices, not re-derived (and divergeable) per browser.
 
Kept deliberately pure and dependency-free (no DB, no matching import): the
route loads the rows and hands plain dicts in here, so this is unit-testable
with no infrastructure. The frontend's mission.js mirrors these formulas as an
offline fallback; a parity test guards that they agree.
"""
import re
from datetime import date
 
 
def _tokenize(text) -> list:
    return [t for t in re.split(r"[^a-z0-9+]+", str(text or "").lower()) if t]
 
 
def _rate(a, b) -> int:
    return round(a / b * 100) if b else 0
 
 
def _clamp_pct(n) -> int:
    try:
        n = round(n)
    except (TypeError, ValueError):
        n = 0
    return max(0, min(100, n))
 
 
def _days_left(deadline):
    """Days until an ISO date string (or None). Negative = past."""
    if not deadline:
        return None
    try:
        d = date.fromisoformat(str(deadline)[:10])
        return (d - date.today()).days
    except (ValueError, TypeError):
        return None
 
 
def compute_mission(data: dict) -> dict:
    """Compute the full Mission Control snapshot from plain data.
 
    data = {
      profile: {skills, northstar},
      applications: [{status, listing_id, org, sent_at, has_factors, has_draft}],
      outcomes: {listing_id: status},         # latest status per listing
      matches: [{score_pct, type, tags, deadline, ghost_risk, title, org}],
      roadmap: {done, total},
      saved_count: int,
      workshop: {star_story, interview_answer, interview_ask},
    }
    """
    profile = data.get("profile") or {}
    apps = data.get("applications") or []
    outcomes = {str(k): v for k, v in (data.get("outcomes") or {}).items()}
    matches = data.get("matches") or []
    roadmap = data.get("roadmap") or {}
    saved_count = int(data.get("saved_count") or 0)
    workshop = data.get("workshop") or {}
 
    # ---- application queue ----
    def _st(s):
        return sum(1 for a in apps if a.get("status") == s)
    apps_sent = _st("sent")
    pending = _st("pending_review")
    approved = _st("approved")
 
    # ---- outcomes (latest status per listing) ----
    oc = {}
    for s in outcomes.values():
        oc[s] = oc.get(s, 0) + 1
    offers = oc.get("offer", 0)
    interviews = oc.get("interview", 0)
    applied = oc.get("applied", 0)
    rejected = oc.get("rejected", 0)
    ghosted = oc.get("ghosted", 0)
    interviews_secured = interviews + offers
    apps_with_outcome = len(outcomes)
    replied = offers + interviews + rejected
    response_rate = _rate(replied, apps_with_outcome)
    applied_to_interview = _rate(interviews_secured, apps_sent)
    interview_to_offer = _rate(offers, interviews_secured)
 
    # ---- matches ----
    m_count = len(matches)
    avg_match = round(sum((m.get("score_pct") or 0) for m in matches) / m_count) if m_count else 0
    high_fit = sum(1 for m in matches if (m.get("score_pct") or 0) >= 75)
    closing_soon = 0
    for m in matches:
        d = _days_left(m.get("deadline"))
        if d is not None and 0 <= d <= 14:
            closing_soon += 1
    ghost_risk = sum(1 for m in matches if m.get("ghost_risk") == "high")
    by_type = {}
    for m in matches:
        t = m.get("type") or "other"
        by_type[t] = by_type.get(t, 0) + 1
 
    # ---- growth / potential ----
    done = int(roadmap.get("done") or 0)
    total = int(roadmap.get("total") or 0)
    roadmap_progress = _rate(done, total)
    skill_tokens = _tokenize(profile.get("skills"))
    skill_strength = min(100, len(skill_tokens) * 8)
    match_quality = avg_match if m_count else 40
    potential = round(roadmap_progress * 0.3 + skill_strength * 0.3 + match_quality * 0.4)
    # Health: a composite of match quality, applying activity and responses.
    # (Deliberately NOT dependent on scan-cycle history, which the server
    # doesn't own - so this number is identical whether computed here or in the
    # browser fallback.)
    health = _clamp_pct(match_quality * 0.35 + min(100, apps_sent * 12) * 0.30 + response_rate * 0.35)
 
    # ---- interview prep ----
    star = int(workshop.get("star_story") or 0)
    q_practiced = int(workshop.get("interview_answer") or 0)
    q_bank = int(workshop.get("interview_ask") or 0)
    companies = {}
    for a in apps:
        st = outcomes.get(str(a.get("listing_id")))
        if st in ("interview", "offer"):
            org = a.get("org")
            if org:
                companies[org] = companies.get(org, 0) + 1
 
    return {
        "has_profile": True,
        # application queue
        "appsSent": apps_sent, "pending": pending, "approved": approved,
        # outcomes
        "offers": offers, "interviews": interviews, "applied": applied,
        "rejected": rejected, "ghosted": ghosted,
        "interviewsSecured": interviews_secured, "appsWithOutcome": apps_with_outcome,
        "responseRate": response_rate, "appliedToInterview": applied_to_interview,
        "interviewToOffer": interview_to_offer,
        # matches / search
        "matchCount": m_count, "avgMatch": avg_match, "highFit": high_fit,
        "closingSoon": closing_soon, "ghostRisk": ghost_risk, "byType": by_type,
        # growth
        "roadmapDone": done, "roadmapTotal": total, "roadmapProgress": roadmap_progress,
        "skillStrength": skill_strength, "skillsListed": len(skill_tokens),
        "matchQuality": match_quality, "potential": potential, "health": health,
        # interviews
        "starCount": star, "qPracticed": q_practiced, "qBank": q_bank,
        "companies": companies,
        # misc
        "savedCount": saved_count,
    }
 
