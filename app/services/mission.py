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
import math
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
 
 
# ============================================================================
# The overview (GET /mission/{user_id}/overview): everything the Mission Control
# pages chart, in one cheap read. The route loads the rows; these pure helpers
# turn each stored record into the small, typed shape the pages read - only the
# fields a chart or a "needs you" line uses (no letter text, no answers, no
# transcripts), so the payload stays small and nothing private travels further
# than it has to. No scoring and no AI here: every figure the pages show is
# counted from these records.
# ============================================================================
OVERVIEW_VERSION = 1
FACTOR_KEYS = ("goal_fit", "skill_fit", "priority_fit", "location_fit", "deadline_urgency",
               "description_fit", "semantic_fit", "roadmap_fit")
 
 
def _num(v):
    """A finite number, or None (never a bool, never NaN)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if math.isfinite(v) else None
 
 
def _int(v, default=0):
    n = _num(v)
    return int(n) if n is not None else default
 
 
def _txt(v, n=80):
    """A short, clean string (or "")."""
    if not isinstance(v, str):
        return ""
    s = re.sub(r"\s+", " ", v).strip()
    return s[:n]
 
 
def _key(v, n=40):
    """A machine key: lower-case letters, digits, _ - : . (or "")."""
    s = _txt(v, n)
    return s if re.fullmatch(r"[A-Za-z0-9_\-:.]*", s) else ""
 
 
def _dicts(v, cap=None):
    out = [x for x in (v if isinstance(v, list) else []) if isinstance(x, dict)]
    return out[-cap:] if cap else out
 
 
def _camel(k):
    return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), k)
 
 
def compact_factors(snap):
    """The match factors an application was scored with (camelCase, numbers only) - what the pages'
    'which signals predicted your replies' check reads."""
    if not isinstance(snap, dict):
        return None
    out = {}
    for k in FACTOR_KEYS:
        n = _num(snap.get(k))
        if n is not None:
            out[_camel(k)] = n
    return out or None
 
 
def compact_package(pkg):
    """An Auto application's record, reduced to what the pages chart: fit, how it was delivered (or why it
    came back to the person), its timeline and its follow-up."""
    if not isinstance(pkg, dict):
        return None
    h = pkg.get("handoff") if isinstance(pkg.get("handoff"), dict) else None
    dl = pkg.get("delivery") if isinstance(pkg.get("delivery"), dict) else {}
    rs = pkg.get("resume") if isinstance(pkg.get("resume"), dict) else {}
    fu = pkg.get("followUp") if isinstance(pkg.get("followUp"), dict) else None
    ap = pkg.get("autopilot") if isinstance(pkg.get("autopilot"), dict) else {}
    cov = rs.get("coverage") if isinstance(rs.get("coverage"), dict) else {}
    attempts = []
    for a in _dicts(pkg.get("attempts"), 10):
        attempts.append({"at": _num(a.get("at")), "channel": _key(a.get("channel"), 20), "status": _key(a.get("status"), 30)})
    by_autopilot = (_int(ap.get("tries")) > 0 or any(a["status"] == "autopilot" for a in attempts)
                    or bool(h and h.get("by") == "autopilot"))
    src = _key(rs.get("source"), 20)
    return {
        "manual": bool(pkg.get("manual")),
        "fit": _num(pkg.get("fit")), "band": _key(pkg.get("band"), 20), "confidence": _key(pkg.get("confidence"), 20),
        "stretch": bool(pkg.get("stretch")),
        "freshness": _key(pkg.get("freshness"), 20), "ghost": _key(pkg.get("ghost"), 20), "ageDays": _num(pkg.get("ageDays")),
        "route": _key(pkg.get("route"), 20),
        "delivery": _key(dl.get("method"), 20), "deliveryKey": _key(dl.get("key"), 30),
        "needs": [_key(n.get("key"), 30) for n in _dicts(pkg.get("needs")) if _key(n.get("key"), 30)][:8],
        "hold": bool(pkg.get("hold")),
        "handoff": ({"key": _key(h.get("key"), 30), "by": _key(h.get("by"), 20), "step": _key(h.get("step"), 20),
                     "possiblySent": bool(h.get("possiblySent")), "at": _num(h.get("at")), "autopilot": bool(h.get("autopilot"))}
                    if h else None),
        "createdAt": _num(pkg.get("createdAt")), "approvedAt": _num(pkg.get("approvedAt")),
        "sendAt": _num(pkg.get("sendAt")), "sentAt": _num(pkg.get("sentAt")),
        "sentChannel": _key(pkg.get("sentChannel"), 20),
        "resume": "version" if src == "version" else ("none" if src == "none" else ("current" if src else "")),
        "reordered": bool(rs.get("moved")),
        "skillCover": ({"have": _int(cov.get("have")), "of": _int(cov.get("of"))} if cov else None),
        "cover": bool(pkg.get("coverLetter")), "coverPolicy": _key(pkg.get("coverPolicy"), 10),
        "attempts": attempts,
        "followUp": ({"dueAt": _num(fu.get("dueAt")), "doneAt": _num(fu.get("doneAt")), "notifiedAt": _num(fu.get("notifiedAt"))}
                     if fu else None),
        "autopilot": by_autopilot, "tries": _int(ap.get("tries")),
    }
 
 
def compact_runs(runs):
    """Auto's recent passes: what each one considered, made and held back (and why) - no job titles."""
    out = []
    for r in _dicts(runs, 20):
        held = r.get("heldCounts") if isinstance(r.get("heldCounts"), dict) else {}
        exc = r.get("excluded") if isinstance(r.get("excluded"), dict) else {}
        err = r.get("errors") if isinstance(r.get("errors"), dict) else {}
        cap = r.get("capacity") if isinstance(r.get("capacity"), dict) else {}
        out.append({
            "at": _num(r.get("at")), "reason": _key(r.get("reason"), 20),
            "considered": _int(r.get("considered")), "created": _int(r.get("created")), "review": _int(r.get("review")),
            "approved": _int(r.get("approved")), "waiting": _int(r.get("waiting")), "held": _int(r.get("held")),
            "heldCounts": {_key(k, 30): _int(v) for k, v in held.items() if _key(k, 30) and _int(v) > 0},
            "excluded": {_key(k, 30): _int(v) for k, v in exc.items() if _key(k, 30) and _int(v) > 0},
            "errors": sum(_int(v) for v in err.values()),
            "paused": _key(r.get("paused"), 20),
            "cap": _int(cap.get("cap")), "madeToday": _int(cap.get("madeToday")), "slots": _int(cap.get("slots")),
        })
    return out
 
 
def compact_session(d, created_ms=None):
    """A judged practice interview with its scores and measured delivery, without the transcript."""
    if not isinstance(d, dict):
        return None
    v = d.get("verdict") if isinstance(d.get("verdict"), dict) else {}
    overall = _num(v.get("overall"))
    if overall is None:
        return None
    dims = d.get("dims") if isinstance(d.get("dims"), dict) else {}
    dl = d.get("delivery") if isinstance(d.get("delivery"), dict) else None
    turns = []
    for t in _dicts(d.get("turns"))[:30]:
        j = t.get("judge") if isinstance(t.get("judge"), dict) else None
        m = t.get("m") if isinstance(t.get("m"), dict) else {}
        sc = j.get("scores") if j and isinstance(j.get("scores"), dict) else {}
        turns.append({
            "qtype": _key(t.get("qtype"), 20), "follow": bool(t.get("follow")), "skipped": bool(t.get("skipped")),
            "not_reached": bool(t.get("not_reached")),
            "judge": ({"overall": _num(j.get("overall")), "unscored": bool(j.get("unscored")), "source": _key(j.get("source"), 10),
                       "scores": {_key(k, 20): _num(x) for k, x in sc.items() if _key(k, 20) and _num(x) is not None}}
                      if j else None),
            "m": {k: _num(m.get(k)) for k in ("seconds", "wpm", "words", "fillers", "i", "we", "is", "ws") if _num(m.get(k)) is not None},
        })
    at = d.get("at") if isinstance(d.get("at"), str) else ""
    return {
        "id": _txt(d.get("id"), 60), "at": at[:40], "created": created_ms,
        "role": _txt(d.get("role"), 60), "company": _txt(d.get("company"), 60),
        "persona": _key(d.get("persona"), 20), "difficulty": _key(d.get("difficulty"), 10), "focus": _key(d.get("focus"), 20),
        "mode": _key(d.get("mode"), 10), "source": _key(d.get("source"), 10),
        "verdict": {"overall": overall, "decision": _key(v.get("decision"), 30),
                    "competencies": [{"name": _txt(c.get("name"), 40), "rating": _num(c.get("rating"))}
                                     for c in _dicts(v.get("competencies"))[:8] if _txt(c.get("name"), 40)]},
        "dims": {_key(k, 20): _num(x) for k, x in dims.items() if _key(k, 20) and _num(x) is not None},
        "delivery": ({k: _num(dl.get(k)) for k in ("answers", "spoken", "wpm", "fillers", "fillersPerMin", "hedges", "longestPause",
                                                   "latency", "overTime", "iCount", "weCount", "seconds") if _num(dl.get(k)) is not None}
                     if dl else None),
        "issues": [_key(x, 20) for x in (d.get("issues") if isinstance(d.get("issues"), list) else []) if _key(x, 20)][:30],
        "turns": turns,
    }
 
 
def compact_story(d, created_ms=None):
    """A STAR story - its words are kept (shortened) because what it shows is read from them."""
    if not isinstance(d, dict):
        return None
    out = {"id": _txt(d.get("id"), 60), "title": _txt(d.get("title"), 120), "created": created_ms,
           "created_at": _txt(d.get("created_at"), 40) or None,
           "competencies": [_key(x, 30) for x in (d.get("competencies") if isinstance(d.get("competencies"), list) else []) if _key(x, 30)][:12],
           "source": _key(d.get("source"), 30)}
    for k in ("s", "t", "a", "r", "situation", "task", "action", "result"):
        if isinstance(d.get(k), str) and d.get(k).strip():
            out[k] = _txt(d.get(k), 400)
    return out
 
 
def compact_debrief(d, created_ms=None):
    if not isinstance(d, dict):
        return None
    return {"id": _txt(d.get("id"), 60), "at": _num(d.get("at")) if _num(d.get("at")) is not None else created_ms,
            "date": _txt(d.get("date"), 10), "stage": _txt(d.get("stage"), 40), "company": _txt(d.get("company"), 80),
            "role": _txt(d.get("role"), 80), "questions": len(d.get("questions")) if isinstance(d.get("questions"), list) else 0}
 
 
def compact_answer(d):
    if not isinstance(d, dict):
        return None
    sc = d.get("score") if isinstance(d.get("score"), dict) else {}
    return {"id": _txt(d.get("id"), 40), "category": _key(d.get("category"), 20),
            "answered": bool(isinstance(d.get("answer"), str) and d.get("answer").strip()),
            "score": {k: _num(sc.get(k)) for k in ("structure", "specificity", "clarity") if _num(sc.get(k)) is not None},
            "story": bool(d.get("star_id"))}
 
 
def compact_version(d, created_ms=None):
    if not isinstance(d, dict):
        return None
    sent = d.get("sent_to") if isinstance(d.get("sent_to"), list) else []
    return {"id": _txt(d.get("id"), 60), "name": _txt(d.get("name"), 80), "source": _key(d.get("source"), 20),
            "created_at": _txt(d.get("created_at"), 40) or None, "created": created_ms,
            "updated_at": _txt(d.get("updated_at"), 40) or None,
            "sent_to": [str(x)[:60] for x in sent if isinstance(x, (str, int)) and not isinstance(x, bool)][:300]}
 
 
def compact_contact(d, created_ms=None):
    if not isinstance(d, dict):
        return None
    return {"id": _txt(d.get("id"), 60), "name": _txt(d.get("name"), 60), "company": _txt(d.get("company"), 80),
            "how": _txt(d.get("how"), 40), "followup": _txt(d.get("followup"), 10) or None,
            "last_contacted": _txt(d.get("last_contacted"), 10) or None,
            "created_at": _txt(d.get("created_at"), 40) or None, "created": created_ms}
 
 
def compact_target(d):
    if not isinstance(d, dict):
        return None
    return {"id": _txt(d.get("id"), 60), "role": _txt(d.get("role"), 80), "company": _txt(d.get("company"), 80),
            "status": _key(d.get("status"), 20)}
 
 
def compact_plan(d):
    """The saved roadmap plan, as the Roadmap page saves it (minus the archived plans for other roles)."""
    if not isinstance(d, dict):
        return None
    items = []
    for it in _dicts(d.get("items"))[:40]:
        x = {"id": _txt(it.get("id"), 80), "kind": _key(it.get("kind"), 20)}
        for k in ("skillId", "haveAtStart", "status"):
            if _key(it.get(k), 60):
                x[k] = _key(it.get(k), 60)
        for k in ("startedAt", "doneAt", "dueAt", "verifiedAt", "hours"):
            if _num(it.get(k)) is not None:
                x[k] = _num(it.get(k))
        items.append(x)
    hist = []
    for h in _dicts(d.get("history"), 60):
        hist.append({"at": _num(h.get("at")), "role": _key(h.get("role"), 60), "n": _int(h.get("n")), "strong": _int(h.get("strong")),
                     "reach": _int(h.get("reach")), "median": _num(h.get("median"))})
    out = {"v": _int(d.get("v"), 1), "role": _key(d.get("role"), 60), "forRole": _key(d.get("forRole"), 60),
           "route": _key(d.get("route"), 80), "items": items, "history": hist}
    for k in ("hoursPerWeek", "targetAt", "startAt", "baselineReadyAt", "readySince", "builtAt", "updatedAt", "changedAt"):
        if _num(d.get(k)) is not None:
            out[k] = _num(d.get(k))
    return out
 
 
def compact_search_state(st):
    """Job Search's saved state, reduced to what the overview shows: your standing targets and your saved
    searches (with how many new matches each has) - not the long lists of ids."""
    if not isinstance(st, dict):
        return None
    p = st.get("prefs") if isinstance(st.get("prefs"), dict) else {}
    prefs = {}
    for k in ("targetRoles", "modes", "levels", "types", "industries"):
        if isinstance(p.get(k), list):
            prefs[k] = [_txt(x, 60) for x in p.get(k) if isinstance(x, str) and _txt(x, 60)][:30]
    for k in ("salaryFloor", "salaryTarget", "years"):
        if _num(p.get(k)) is not None:
            prefs[k] = _num(p.get(k))
    for k in ("locations", "modeRule", "level"):
        if isinstance(p.get(k), str):
            prefs[k] = _txt(p.get(k), 120)
    searches = []
    for s in _dicts(st.get("searches"))[:20]:
        searches.append({"id": _txt(s.get("id"), 40), "name": _txt(s.get("name") or s.get("raw"), 80), "alert": bool(s.get("alert")),
                         "created": _num(s.get("created")), "newCount": _int(s.get("newCount")), "lastCount": _int(s.get("lastCount")),
                         "lastCheck": _num(s.get("lastCheck")), "newAt": _num(s.get("newAt")), "lastOpened": _num(s.get("lastOpened")),
                         "minFit": _num(s.get("minFit"))})
    learned = st.get("learned") if isinstance(st.get("learned"), list) else []
    applied = st.get("applied") if isinstance(st.get("applied"), list) else []
    return {"prefs": prefs, "searches": searches,
            "learned": len([x for x in learned if isinstance(x, dict) and x.get("active", True) is not False]),
            "applied": len(applied), "updatedAt": _num(st.get("updatedAt"))}
 
 
def learned_answer_times(bank):
    """When each answer the extension remembered from a form was saved (ms), oldest first."""
    custom = bank.get("custom") if isinstance(bank, dict) and isinstance(bank.get("custom"), list) else []
    return sorted(_int(c.get("at")) for c in custom if isinstance(c, dict) and c.get("src") == "form" and _int(c.get("at")) > 0)
 
 
def custom_answer_counts(bank):
    custom = bank.get("custom") if isinstance(bank, dict) and isinstance(bank.get("custom"), list) else []
    form = sum(1 for c in custom if isinstance(c, dict) and c.get("src") == "form")
    return {"form": form, "yours": sum(1 for c in custom if isinstance(c, dict)) - form}
 
 
def compact_rules(r):
    if not isinstance(r, dict):
        return {}
    out = {}
    for k in ("mode", "sendDays", "tz", "coverLetter"):
        if isinstance(r.get(k), str):
            out[k] = _txt(r.get(k), 40)
    for k in ("minFit", "dailyCap", "weeklyCap", "delayMinutes", "followUpDays", "pausedUntil", "perCompany"):
        if _num(r.get(k)) is not None:
            out[k] = _num(r.get(k))
    out["pauseOnInterview"] = bool(r.get("pauseOnInterview"))
    return out
 
 
WORKSHOP_KINDS = ("star_story", "interview_session", "interview_debrief", "interview_answer", "interview_ask",
                  "resume_version", "contact", "target_role", "achievement", "reference", "portfolio", "pitch", "roadmap_plan")
 
 
def compact_workshop(rows):
    """rows: [(kind, client_id, data, created_ms, updated_ms)] -> the overview's 'items' block."""
    out = {"stories": [], "sessions": [], "debriefs": [], "answers": [], "versions": [], "contacts": [], "targets": [],
           "counts": {"asks": 0, "achievements": 0, "references": 0, "portfolio": 0, "pitch": False},
           "plan": None, "planAt": None}
    seen = set()
    for kind, cid, data, created, updated in rows:
        if (kind, cid) in seen:
            continue
        seen.add((kind, cid))
        if kind == "star_story":
            x = compact_story(data, created)
            if x:
                out["stories"].append(x)
        elif kind == "interview_session":
            x = compact_session(data, created)
            if x:
                out["sessions"].append(x)
        elif kind == "interview_debrief":
            x = compact_debrief(data, created)
            if x:
                out["debriefs"].append(x)
        elif kind == "interview_answer":
            x = compact_answer(data)
            if x:
                out["answers"].append(x)
        elif kind == "resume_version":
            x = compact_version(data, created)
            if x:
                out["versions"].append(x)
        elif kind == "contact":
            x = compact_contact(data, created)
            if x:
                out["contacts"].append(x)
        elif kind == "target_role":
            x = compact_target(data)
            if x:
                out["targets"].append(x)
        elif kind == "interview_ask":
            out["counts"]["asks"] += 1
        elif kind == "achievement":
            out["counts"]["achievements"] += 1
        elif kind == "reference":
            out["counts"]["references"] += 1
        elif kind == "portfolio":
            out["counts"]["portfolio"] += 1
        elif kind == "pitch":
            out["counts"]["pitch"] = bool(isinstance(data, dict) and any(isinstance(v, str) and v.strip() for v in data.values()))
        elif kind == "roadmap_plan":
            out["plan"] = compact_plan(data)
            out["planAt"] = updated or created
    return out
 
