"""Matching engine: scores listings against a user's profile.
 
Every factor that shows up in the explanation is a real input to the
score itself - deadline urgency and location fit used to be mentioned
in the rationale text but never actually affected the number, which
is exactly the kind of inconsistency that makes a score feel
untrustworthy even when the prose sounds reasonable. Fixed here: the
score is now a transparent, structured composite of six named
factors, each independently inspectable - not a black-box percentage
with a plausible-sounding paragraph bolted on afterward.
"""
import math
import re
from datetime import date, datetime
from typing import Optional
from app.services.embeddings import semantic_similarity_factor
 
 
def _round_half_up(x: float) -> int:
    """JavaScript's Math.round rounds .5 UP (toward +inf); Python's built-in
    round() uses banker's rounding (half to even). The frontend scorer uses
    Math.round, so a score landing exactly on N.5 rendered as N+1 on the frontend
    but N on the backend - a real 1-point FE/BE divergence on exact-half values
    (e.g. raw 0.5833 -> 90.5 -> 91 on FE, 90 on BE). floor(x + 0.5) reproduces
    Math.round exactly for the always-non-negative percentages here, keeping the
    two layers bit-identical on identical input."""
    return math.floor(x + 0.5)
 
# Honestly scoped: a curated set of common, well-known synonyms in
# tech/career contexts - not a claim of real NLP or embeddings. Pure
# substring matching (the previous approach) misses obvious pairs
# like "js" vs "javascript" or "ml" vs "machine learning"; this closes
# the most common gaps without pretending to be exhaustive.
SYNONYM_GROUPS = [
    {"js", "javascript", "typescript", "ts"},
    {"ml", "machinelearning", "ai", "artificialintelligence"},
    {"sql", "database", "databases", "postgres", "postgresql", "mysql"},
    {"ux", "ui", "design", "uxdesign", "uidesign"},
    {"pm", "productmanagement", "product"},
    {"frontend", "front-end", "front"},
    {"backend", "back-end", "back"},
    {"fullstack", "full-stack"},
    {"analytics", "analysis", "dataanalysis", "data"},
    {"devops", "infrastructure", "infra"},
    {"marketing", "growth", "branding", "socialmedia"},
    {"finance", "financial", "accounting"},
    {"bio", "biology", "biotech"},
    {"sales", "businessdevelopment", "accountexecutive", "ae", "bd"},
    {"operations", "ops", "logistics", "supplychain"},
    {"hr", "humanresources", "peopleops", "recruiting", "talentacquisition"},
    {"customersuccess", "customersupport", "clientsuccess", "accountmanagement"},
    {"healthcare", "clinical", "patientcare", "medical"},
    {"legal", "compliance", "paralegal", "regulatory"},
]
_SYNONYM_LOOKUP: dict[str, set[str]] = {}
for _group in SYNONYM_GROUPS:
    for _term in _group:
        _SYNONYM_LOOKUP[_term] = _group
 
 
def tokenize(text: str) -> list[str]:
    """The general 3-char minimum avoids polluting matches with noise
    words (of, to, in, is, at...), but that same minimum was silently
    dropping short, meaningful abbreviations this app's synonym system
    depends on (js, ai, ux, ui, pm, ml, ts) - so those are extracted
    separately as whole words rather than lowering the general
    minimum and reintroducing noise-word pollution.
    """
    tokens = re.findall(r"[a-z][a-z\-]{2,}", (text or "").lower())
    short_terms = {t for group in SYNONYM_GROUPS for t in group if len(t) <= 2}
    if short_terms:
        text_lower = (text or "").lower()
        for term in short_terms:
            if re.search(rf"\b{re.escape(term)}\b", text_lower):
                tokens.append(term)
    return tokens
 
 
def _word_boundary_contains(haystack: str, needle: str) -> bool:
    """Manual boundary check rather than regex \\b - \\b relies on a
    transition between a word character and a non-word character,
    which silently fails for terms ending in punctuation. "c++" would
    never be recognized as a whole word inside "c++ developer",
    because both the trailing "+" and the following space are
    non-word characters - no transition exists there for \\b to
    detect, even though a person would obviously read that as the
    same term. This checks explicitly: is the character on each side
    of a match (if any) non-alphanumeric, regardless of what specific
    character it is.
    """
    if not needle or not haystack:
        return False
    idx = haystack.find(needle)
    while idx != -1:
        before_ok = idx == 0 or not haystack[idx - 1].isalnum()
        after_idx = idx + len(needle)
        after_ok = after_idx == len(haystack) or not haystack[after_idx].isalnum()
        if before_ok and after_ok:
            return True
        idx = haystack.find(needle, idx + 1)
    return False
 
 
def _terms_match(a: str, b: str) -> bool:
    """True if two terms are the same, one contains the other as a
    genuine whole word, or they belong to the same curated synonym
    group.
 
    Found via testing the roadmap-alignment integration, but the bug
    reached far further: the old plain `a in b or b in a` substring
    check had zero word-boundary awareness, so any short common word
    embedded in a longer, unrelated term produced a false match -
    "and" is a literal substring of "brand"/"branding" (br-AND-ing),
    "at" is a substring of "data" - and "java" is a genuine substring
    of "javascript" despite being different languages. Since this
    function is what goal_fit and skill_fit are built on, this wasn't
    a narrow issue - it could silently inflate or misattribute the
    two most important scoring factors in the whole engine, for any
    profile whose free text happened to contain a short common word.
    Fixed with the same word-boundary principle already used for the
    dealbreaker fix (_has_dealbreaker).
    """
    if a is None or b is None:
        return False
    if a == b:
        return True
    if _word_boundary_contains(a, b) or _word_boundary_contains(b, a):
        return True
    a_clean, b_clean = a.replace("-", ""), b.replace("-", "")
    group_a = _SYNONYM_LOOKUP.get(a_clean)
    return bool(group_a and b_clean in group_a)
 
 
def _has_dealbreaker(tags: list[str], dealbreakers: str) -> bool:
    """Fixed a real false-positive: the previous check was a blind
    substring containment (`tag in dealbreakers_text`), which meant a
    dealbreaker of "javascript" would silently exclude any listing
    tagged "java" - a completely different, unrelated language -
    because "java" is literally a substring of "javascript". Dealbreakers
    are meant to be a precise safety filter; a false-positive here
    means hiding a genuinely good match for no real reason.
 
    Matching now has two complementary parts, both word-aware:
    (1) token-set overlap using the same tokenizer as the rest of
    matching, so "java" and "javascript" are correctly distinct terms
    (plus a de-hyphenated form so "full-stack" matches "fullstack");
    and (2) a word-boundary check that also catches a dealbreaker word
    appearing as a whole word INSIDE a hyphenated tag - e.g. "travel"
    correctly matches the tag "travel-required" (a hyphen is a real
    word boundary), which the tokenizer alone would miss since it
    keeps "travel-required" as a single token. This second part is a
    real safety requirement: without it a stated dealbreaker could
    fail to exclude a listing the person explicitly ruled out. Both
    parts are precise - neither reintroduces the substring false-
    positive (verified: "art" still does not match "startup").
    """
    if not dealbreakers:
        return False
    dealbreaker_tokens = set(tokenize(dealbreakers))
    if not dealbreaker_tokens:
        return False
    for tag in tags:
        tag_lower = tag.lower()
        tag_tokens = set(tokenize(tag)) | {tag_lower.replace("-", "")}
        if dealbreaker_tokens & tag_tokens:
            return True
        # Also catch a dealbreaker word appearing as a whole word INSIDE
        # a hyphenated tag ("travel" inside "travel-required" - a hyphen
        # is a real word boundary). Without this, a stated dealbreaker
        # could fail to exclude a listing the person explicitly ruled
        # out. Matches the frontend hasDealbreaker's behavior.
        if any(_word_boundary_contains(tag_lower, db) for db in dealbreaker_tokens):
            return True
    return False
 
 
def _is_listing_expired(listing: dict) -> bool:
    """A real, hard exclusion - not just a scoring factor. Without
    this, a genuinely excellent skill/goal match with an already-
    passed deadline could still clear the presentable score
    threshold on every other real factor, showing someone a
    confident "great match" for a job that's already closed. A
    listing with no deadline stated at all is never treated as
    expired - "no deadline given" and "already passed" are genuinely
    different things.
    """
    if not listing.get("deadline"):
        return False
    try:
        deadline_date = date.fromisoformat(listing["deadline"]) if isinstance(listing["deadline"], str) else listing["deadline"]
        if not isinstance(deadline_date, date):
            return False
    except (ValueError, TypeError):
        return False
    return deadline_date < date.today()
 
 
LISTING_STALE_DAYS = 30  # aggregated boards routinely leave filled roles up for weeks; past ~a month un-re-seen, verification is genuinely worth flagging
 
 
def _get_listing_staleness_note(listing: dict, now: "datetime | None" = None) -> Optional[dict]:
    """The honest answer to the documented ghost-job problem: an
    aggregated listing Kaidostar hasn't re-seen in a long time is more
    likely to be already filled or stale. Crucially SOFT, not a hard
    exclusion like _is_listing_expired - staleness is genuinely
    uncertain (the role might still be open), so this cautions rather
    than removes, and says exactly what it does and doesn't know.
    Pairs with the standard, real advice to verify on the company's
    own careers page before applying. Returns None when there's no
    fetched_at to judge, or when the listing is genuinely recent -
    never fabricates a concern from absent data.
    """
    from datetime import datetime as _dt, timezone
    fetched = listing.get("fetched_at")
    if not fetched:
        return None
    try:
        if isinstance(fetched, str):
            fetched_dt = _dt.fromisoformat(fetched)
        elif isinstance(fetched, _dt):
            fetched_dt = fetched
        else:
            return None
    except (ValueError, TypeError):
        return None
    current = now or _dt.utcnow()
    if fetched_dt.tzinfo is not None:
        fetched_dt = fetched_dt.astimezone(timezone.utc).replace(tzinfo=None)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    days = (current - fetched_dt).days
    if days < LISTING_STALE_DAYS:
        return None
    return {
        "days_since_seen": days,
        "note": f"Kaidostar last saw this posting {days} days ago - aggregated listings can be filled or removed without the board updating, so it's worth confirming it's still open on the company's own careers page before applying.",
    }
 
 
def _detect_seniority_mismatch(listing: dict, profile: dict) -> Optional[dict]:
    """Mirrors the frontend's detectSeniorityMismatch exactly: only
    ever flags a CLEAR, unambiguous seniority gap between a listing's
    title and the person's real stated stage, never a guess. The
    concrete answer to a documented competitor weakness where a
    keyword-strong but genuinely overqualified/underqualified role
    still scored high with no honest flag distinguishing it from a
    true fit.
    """
    import re as _re
    title = (listing.get("title") or "").lower()
    stage = profile.get("stage") or ""
    senior_markers = _re.compile(r"\b(senior|sr\.?|staff|principal|lead|director|head of|vp|vice president|chief|manager|executive)\b")
    junior_markers = _re.compile(r"\b(intern|internship|junior|jr\.?|entry[- ]?level|trainee|apprentice|assistant|fellow|graduate|new grad)\b")
    is_senior = bool(senior_markers.search(title))
    is_junior = bool(junior_markers.search(title))
    if is_senior and is_junior:
        return None  # genuinely ambiguous title - honestly flag nothing
    early_career = stage in ("student", "grad")
    established_career = stage == "working"
    if early_career and is_senior:
        return {"direction": "above", "note": "This role's title suggests a seniority level well above where you said you are - it may be a reach, and worth weighing against roles closer to your current stage."}
    if established_career and is_junior:
        return {"direction": "below", "note": "This role's title suggests a level below your stated experience - you may be seen as overqualified, which is worth weighing before spending an application on it."}
    return None
 
 
def _deadline_urgency_factor(listing: dict, profile: dict | None = None) -> tuple[float, int | None]:
    """Returns (score_contribution, days_left). A deadline that's
    close but not unrealistically close gets a small real boost -
    genuinely actionable urgency, not panic-inducing. Too far out or
    already passed contributes nothing.
 
    Scaled by the USER'S stated search timeframe (mirrors the frontend
    deadlineUrgencyFactor): a "now" searcher has soon-closing roles weighted
    up; a "2yr+" explorer isn't pushed by urgency they don't feel.
    """
    if not listing.get("deadline"):
        return 0.0, None
    try:
        deadline_date = date.fromisoformat(listing["deadline"]) if isinstance(listing["deadline"], str) else listing["deadline"]
        if not isinstance(deadline_date, date):
            return 0.0, None
    except (ValueError, TypeError):
        return 0.0, None
    days_left = (deadline_date - date.today()).days
    if days_left < 0:
        return 0.0, days_left
    if days_left <= 3:
        base = 0.5
    elif days_left <= 14:
        base = 1.5  # the genuinely actionable window
    elif days_left <= 30:
        base = 0.5
    else:
        base = 0.0
    tf = (profile or {}).get("timeframe", "")
    urgency_mult = {"now": 1.6, "6-12mo": 1.0, "1-2yr": 0.6, "2yr+": 0.3}.get(tf, 1.0)
    return base * urgency_mult, days_left
 
 
def _detect_location_mismatch(listing: dict, profile: dict) -> Optional[dict]:
    """Mirrors the frontend's detectLocationMismatch exactly: only
    flags a CLEAR onsite/relocation gap - an onsite (non-remote)
    listing in a location that doesn't match the person's stated
    city, when they haven't signaled remote. The concrete answer to
    the documented 'remote does not mean anywhere / HR mislabels
    location' problem - surfaces the relocation reality rather than
    letting a keyword-strong score hide it.
    """
    listing_loc = (listing.get("location") or "").lower().strip()
    location_pref = (profile.get("location_pref") or "").lower().strip()
    if not listing_loc or not location_pref:
        return None
    if "remote" in listing_loc:
        return None
    if "remote" in location_pref:
        return None
    pref_tokens = [t for t in tokenize(location_pref) if len(t) > 3]
    if not pref_tokens:
        return None
    if any(t in listing_loc for t in pref_tokens):
        return None
    return {"note": f"This role is based in {listing.get('location')}, which doesn't match your stated location ({profile.get('location_pref')}) and isn't remote - it would likely require relocating, worth weighing before applying."}
 
 
def _location_fit_factor(listing: dict, profile: dict) -> tuple[float, str | None]:
    """Returns (score_contribution, reason). Mirrors what the
    explanation already claimed to consider - remote-preference match,
    flexibility priority, and a real location-token overlap - now
    actually feeding the score instead of only appearing in prose.
    """
    listing_loc = (listing.get("location") or "").lower()
    location_pref = (profile.get("location_pref") or "").lower()
    priorities = profile.get("priorities") or []
 
    if "flexibility" in priorities and "remote" in listing_loc:
        return 1.5, "remote, matching your stated need for flexibility"
    if location_pref and listing_loc:
        if "remote" in location_pref and "remote" in listing_loc:
            return 1.5, "matches your remote location preference"
        pref_tokens = [t for t in tokenize(location_pref) if len(t) > 3]
        if any(t in listing_loc for t in pref_tokens):
            return 1.0, f"based in {listing.get('location')}, inside your stated location preference"
        # Remote work is inherently compatible with living anywhere -
        # a real, positive signal even when someone stated a specific
        # city rather than explicitly asking for remote. Smaller than
        # an explicit remote match, since we don't know for certain
        # they'd prefer it over staying near their stated city.
        if "remote" in listing_loc:
            return 0.75, "remote, which works regardless of your location"
    return 0.0, None
 
 
def _description_overlap_factor(listing: dict, goal_tokens: list[str], skill_tokens: list[str], matched_tag_terms: set[str]) -> tuple[float, list[str]]:
    """Real signal from the actual job posting text, not just the
    6-10 tags an earlier ingestion step compressed it down to. Tag
    extraction is inherently lossy - a specific requirement mentioned
    once in a long posting can easily not survive being reduced to a
    handful of tags. This scans the title AND description for goal/
    skill terms that AREN'T already accounted for by a tag match -
    the title is often the single most information-dense field on a
    listing (a real gap existed here where a term appearing only in
    the title, never in tags or description, was completely invisible
    to this factor) - catching real signal the compression step lost,
    without needing a paid AI call for every listing in every scan.
 
    Description text is capped at 4000 characters before scanning -
    found via stress-testing against realistic long postings (real
    aggregated listings can run 10,000+ characters once legal
    boilerplate and benefits sections are included). This function
    runs once per listing per candidate on every scan cycle, so
    tokenizing the full text every time is real, avoidable
    computational cost for signal that's overwhelmingly concentrated
    in the requirements/responsibilities section near the top of a
    real posting, not buried in the boilerplate at the end.
    """
    combined_text = f"{listing.get('title') or ''} {(listing.get('description') or '')[:4000]}".lower()
    if not combined_text.strip():
        return 0.0, []
    desc_tokens = set(tokenize(combined_text))
    found = []
    for term in set(goal_tokens) | set(skill_tokens):
        term_clean = term.replace("-", "")
        if term_clean in matched_tag_terms:
            continue  # already credited via a tag match - avoid double-counting the same signal
        if term in desc_tokens or any(_terms_match(term, d) for d in desc_tokens):
            found.append(term)
    # Capped and weighted lower than a real tag match - this is
    # supplementary signal from a noisier source (free text vs a
    # curated tag), not a replacement for it.
    contribution = min(2.0, len(found) * 0.4)
    return contribution, found[:5]
 
 
def assess_listing_data_quality(listing: dict) -> dict:
    """Every listing gets scored with the same apparent confidence,
    but the underlying data backing that score varies enormously - a
    listing with a real description and 5+ specific tags supports a
    genuinely trustworthy score; one with a 2-word title, no
    description, and 1 generic tag does not, no matter how the math
    comes out. This is honest about that gap instead of letting a
    thin listing produce a falsely confident-looking percentage.
 
    Returns a quality tier and the specific real reasons behind it -
    not a black-box penalty.
    """
    reasons = []
    points = 0
 
    title = str(listing.get("title") or "").strip()
    if len(title.split()) >= 3:
        points += 1
    else:
        reasons.append("title is very short")
 
    tags = listing.get("tags") if isinstance(listing.get("tags"), (list, tuple)) else []
    if len(tags) >= 4:
        points += 2
    elif len(tags) >= 2:
        points += 1
    else:
        reasons.append("very few tags to match against")
 
    description = str(listing.get("description") or "").strip()
    if len(description) >= 200:
        points += 2
    elif len(description) >= 50:
        points += 1
    else:
        reasons.append("no real description text - matching relies on tags alone")
 
    if listing.get("location"):
        points += 1
    else:
        reasons.append("no location listed")
 
    if listing.get("deadline"):
        points += 1
    else:
        reasons.append("no deadline listed")
 
    # Max possible: 1 (title) + 2 (tags) + 2 (description) + 1 (location) + 1 (deadline) = 7
    if points >= 6:
        tier = "rich"
    elif points >= 3:
        tier = "adequate"
    else:
        tier = "thin"
 
    return {"tier": tier, "points": points, "max_points": 7, "reasons": reasons}
 
 
# ============================================================================
# SIGNAL SCORE (backend mirror of the frontend computeSignalScore).
# Reframes the discredited "match %" into "how much does applying here actually
# help your case?" - folding fit + freshness + ghost-risk. Kept in byte-for-byte
# behavioural parity with kaidostar/state.js so the UI shows identical results
# whether scored locally (logged out) or here (logged in).
# ============================================================================
 
def _posting_age_days(listing: dict):
    """Days since the posting appeared, from its real timestamp. None if unknown."""
    ts = listing.get("fetched_at") or listing.get("posted_at") or listing.get("created_at")
    if not ts:
        return None
    from datetime import datetime, timezone
    if isinstance(ts, datetime):
        t = ts
    else:
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0, int((now - t).total_seconds() // 86400))
 
 
def assess_listing_signal(listing: dict) -> dict:
    """Freshness + ghost-risk assessment for one listing. Honest bands, never a fake %."""
    age = _posting_age_days(listing)
    dq = listing.get("data_quality") if isinstance(listing.get("data_quality"), dict) else {}
    q = dq.get("tier")
    desc = listing.get("description")
    has_desc = bool(desc and len(str(desc).strip()) > 40)
    tags = listing.get("tags") or []
    tag_count = len(tags) if isinstance(tags, list) else 0
 
    if age is None:
        freshness, fresh_note = "unknown", "No post date available - freshness unverified."
    elif age <= 3:
        freshness = "fresh"
        when = "today" if age == 0 else f"{age} day{'s' if age > 1 else ''} ago"
        fresh_note = f"Posted {when} - you're early, before the crush."
    elif age <= 10:
        freshness, fresh_note = "recent", f"Posted {age} days ago - still active, but the pile is growing."
    elif age <= 25:
        freshness, fresh_note = "aging", f"Posted {age} days ago - likely crowded; many roles fill by now."
    else:
        freshness, fresh_note = "stale", f"Posted {age}+ days ago - high chance it's filled or a \"ghost\" posting. Verify on the company site before spending effort."
 
    ghost_risk = "low"
    staleish = (age is not None and age > 25)
    thin = (q == "thin") or (not has_desc and tag_count < 3)
    if staleish and thin:
        ghost_risk = "high"
    elif staleish or thin:
        ghost_risk = "elevated"
 
    return {"age_days": age, "freshness": freshness, "fresh_note": fresh_note, "ghost_risk": ghost_risk, "thin": thin}
 
 
def compute_signal_score(scored_listing: dict) -> dict:
    """The Signal Score: 0-97, honest, capped. Fit adjusted for freshness + ghost risk."""
    fit = scored_listing.get("score_pct")
    # math.isfinite, not just isinstance: isinstance(nan, float) is True, so a NaN
    # score_pct slipped through and produced a NaN signal_score - defeating the
    # defaulting this guard exists to do. Mirrors the frontend's Number.isFinite fix.
    fit = fit if isinstance(fit, (int, float)) and math.isfinite(fit) else 0
    sig = assess_listing_signal(scored_listing)
 
    score = float(fit)
    fresh_mult = {"fresh": 1.0, "recent": 0.94, "aging": 0.8, "stale": 0.55, "unknown": 0.9}[sig["freshness"]]
    score *= fresh_mult
    if sig["ghost_risk"] == "high":
        score *= 0.7
    elif sig["ghost_risk"] == "elevated":
        score *= 0.88
    # _round_half_up, not round(): score here is a FLOAT (fit * freshness *
    # ghost multipliers), so it lands on exact N.5 values in the real domain
    # (e.g. fit 75 * 0.94 recent = 70.5). The frontend's computeSignalScore uses
    # Math.round (half up), and the scorer already uses _round_half_up for the
    # same reason - plain round()'s banker's rounding made the Signal Score read
    # 70 on the backend but 71 on the frontend for the same listing. Half-up
    # keeps the honest number identical on both paths.
    score = max(0, min(97, _round_half_up(score)))
 
    fr = sig["freshness"]
    if sig["ghost_risk"] == "high":
        band = "Weak signal"
        headline = ("Applying here is a weak signal - " +
                    ("the posting looks stale/ghost" if fr == "stale" else "thin, unverifiable posting") +
                    ". Spend your effort somewhere fresher.")
    elif fit >= 70 and fr in ("fresh", "recent"):
        band = "Strong signal"
        headline = f"Strong fit on a live posting - applying here genuinely moves your case. {sig['fresh_note']}"
    elif fit >= 70:
        band = "Good fit, weak timing"
        headline = f"Good fit, but {sig['fresh_note'][0].lower() + sig['fresh_note'][1:]} A tailored application still helps - move fast."
    elif score >= 45:
        band = "Moderate signal"
        headline = f"A reasonable but not standout signal. {sig['fresh_note']}"
    else:
        band = "Low signal"
        headline = ("Low signal - weak fit" +
                    (" and an aging posting" if fr in ("stale", "aging") else "") +
                    ". Only worth it if you're broadening your search.")
 
    return {"signal_score": score, "signal_band": band, "signal_headline": headline,
            "freshness": fr, "fresh_note": sig["fresh_note"], "ghost_risk": sig["ghost_risk"], "age_days": sig["age_days"]}
 
 
def score_listing(listing: dict, profile: dict, factor_weights: dict | None = None, roadmap_milestones: list | None = None) -> Optional[dict]:
    """Returns None if the listing is excluded by a dealbreaker, else a
    structured score dict with a top-level score_pct plus every named
    factor that contributed to it, independently inspectable.
 
    factor_weights, when provided, is the output of
    get_personalized_factor_weights() - real, per-user multipliers
    learned from logged outcomes about which TYPES of signal actually
    predict success for THIS person. Defaults to no personalization
    (every factor at its designed weight) when not provided or when
    there isn't yet enough outcome history to learn from - fully
    backward compatible.
 
    roadmap_milestones, when provided, makes roadmap alignment a real,
    named factor that genuinely moves the score - not just a
    decorative badge shown alongside a number it never influenced,
    which is what this used to be. A listing that clearly advances
    your actual current roadmap stage now scores meaningfully higher
    than an otherwise-identical one that doesn't connect to your plan
    at all.
    """
    factor_weights = factor_weights or {}
    # Defensive lowercase: tag comparison below is case-sensitive, and
    # a stray uppercase tag from any source (LLM extraction, manual
    # listings, legacy rows) would otherwise silently score far lower.
    listing_tags = [str(t).lower() for t in (listing.get("tags") or [])]
    if _has_dealbreaker(listing_tags, profile.get("dealbreakers") or ""):
        return None
 
    # Defensive: every OTHER profile field here is read with .get() and a
    # default, and explain_score() already reads northstar as
    # `profile.get("northstar") or ""`. score_listing was the lone place that
    # subscripted it directly, so a profile dict assembled without northstar
    # (a partial/legacy row, an internal caller) crashed the core scorer here
    # while the frontend's scoreListing tolerated it via `profile.northstar || ''`.
    # Match that tolerance and that internal consistency.
    goal_tokens = tokenize(f"{profile.get('northstar') or ''} {profile.get('final_idea', '')}")
    skill_tokens = tokenize(profile.get("skills", ""))
    # Dedupe once (order-preserving). The tag loop below uses any(...) over these
    # (short-circuit, so duplicates can't change the result) and the description
    # factor already de-dupes via set(), so this is purely a speed guard keeping the
    # O(tags x tokens) hot path bounded for a repetitive profile. Mirrors the FE.
    goal_tokens = list(dict.fromkeys(goal_tokens))
    skill_tokens = list(dict.fromkeys(skill_tokens))
    priorities = profile.get("priorities") or []
 
    goal_fit, skill_fit = 0.0, 0.0
    matched_goal, matched_skill = [], []
    matched_tag_terms = set()
    double_match_count = 0
    for tag in listing_tags:
        in_goal = any(_terms_match(t, tag) for t in goal_tokens)
        in_skill = any(_terms_match(t, tag) for t in skill_tokens)
        if in_goal:
            goal_fit += 3
            matched_goal.append(tag)
            matched_tag_terms.add(tag.replace("-", ""))
        if in_skill:
            skill_fit += 2
            matched_skill.append(tag)
            matched_tag_terms.add(tag.replace("-", ""))
        if in_goal and in_skill:
            double_match_count += 1
 
    priority_fit = 0.0
    if "learning" in priorities and listing.get("type") in ("internship", "college"):
        priority_fit += 1.5
    if "pay" in priorities and listing.get("type") == "job":
        priority_fit += 1.5
 
    location_fit, location_reason = _location_fit_factor(listing, profile)
    deadline_urgency, days_left = _deadline_urgency_factor(listing, profile)
    description_fit, description_terms = _description_overlap_factor(listing, goal_tokens, skill_tokens, matched_tag_terms)
    semantic_fit = semantic_similarity_factor(listing.get("embedding"), profile.get("embedding"), tag_count=len(listing_tags))
    roadmap_alignment = compute_roadmap_alignment(listing, roadmap_milestones) if roadmap_milestones else None
    roadmap_fit = round(roadmap_alignment["strength"] * 3.0, 2) if roadmap_alignment else 0.0
 
    # Apply personalized weighting - each factor's REAL, learned
    # reliability for this specific person, not a generic default.
    goal_fit *= factor_weights.get("goal_fit", 1.0)
    skill_fit *= factor_weights.get("skill_fit", 1.0)
    priority_fit *= factor_weights.get("priority_fit", 1.0)
    location_fit *= factor_weights.get("location_fit", 1.0)
    deadline_urgency *= factor_weights.get("deadline_urgency", 1.0)
    description_fit *= factor_weights.get("description_fit", 1.0)
    semantic_fit *= factor_weights.get("semantic_fit", 1.0)
    roadmap_fit *= factor_weights.get("roadmap_fit", 1.0)
 
    raw_total = goal_fit + skill_fit + priority_fit + location_fit + deadline_urgency + description_fit + semantic_fit + roadmap_fit
    # Headroom only applies for factors that actually earned real
    # points for THIS listing/profile pair, not just ones that
    # theoretically could have - whether title+description text turns
    # into a real contribution depends on this specific profile's
    # terms overlapping it, not just on the text existing. Tying
    # headroom to actual earned contribution (rather than trying to
    # predict potential contribution ahead of time) means no
    # listing/profile pair is ever diluted by a ceiling for a signal
    # that contributed nothing.
    # Headroom equals each factor's OWN contribution, not a flat
    # theoretical maximum - this isn't just a heuristic, it's
    # mathematically guaranteed: adding x to both raw_total and denom
    # can never decrease the resulting percentage when x > 0 (proof:
    # (a+x)/(b+x) >= a/b whenever b >= a, which always holds here
    # since a valid percentage never exceeds its own ceiling). The
    # earlier flat-headroom version (always the full theoretical max,
    # e.g. always +4.0 whenever semantic_fit was merely nonzero) could
    # net DILUTE the score for any weak-but-real match that fell well
    # short of the theoretical maximum - found via direct testing,
    # not by inspection, on a semantic_fit case this exact bug had
    # been hiding in since it was first built.
    description_headroom = description_fit
    semantic_headroom = semantic_fit
    roadmap_headroom = roadmap_fit
    # skill_fit's own headroom was missing here even though goal_fit's
    # was always included (len(tags)*3), even though a tag matching
    # both dimensions gets credited in the numerator for both.
    #
    # Two prior attempts before landing here, both tested and
    # rejected before shipping: (1) adding skill_fit's full
    # theoretical ceiling (len(tags)*2) unconditionally assumed an
    # unrealistic ideal listing where every tag matches both goal and
    # skill simultaneously, dragging genuinely good realistic matches
    # to the scoring floor. (2) using skill_fit's own earned
    # contribution as headroom - the same principle proven for
    # description/semantic/roadmap - turned out not to apply here:
    # that principle only holds when a factor is NEWLY added to both
    # numerator and denominator together (true for semantic/roadmap,
    # which don't exist without embeddings/a roadmap). skill_fit
    # already existed in the numerator before this fix, so adding it
    # to the denominator alone unconditionally lowered every score
    # with meaningful skill_fit - including realistic cases where
    # skill_fit is legitimately strong but goal_fit is weak or
    # absent, which was never the actual bug.
    #
    # double_match_count (tags that hit BOTH dimensions, tracked
    # during the tag loop above) targets only the real problem: a tag
    # corroborating both goal and skill gets credited for both in the
    # numerator, but the denominator only ever budgeted for the
    # goal_fit half of that specific tag. Verified against a broad
    # spread of realistic match-quality scenarios, including the
    # specific skill-only and goal-only cases the first two attempts
    # got wrong, before shipping.
    skill_headroom = double_match_count * 2
    # priority_fit's real ceiling is 1.5, not 2 - its two branches
    # ("learning" for internship/college, "pay" for job) are mutually
    # exclusive per listing type, so only one can ever fire for any
    # single listing, and this is always potentially achievable
    # regardless of the specific listing's data. location_fit and
    # deadline_urgency are different: their ceilings only apply when
    # the listing actually HAS a location or deadline field to
    # possibly match against - budgeting a flat 3.0 for both
    # unconditionally repeated the exact mistake already learned from
    # with the first skill_fit attempt (assuming an unrealistic ideal
    # every listing could reach), and directly caused a real,
    # verified regression: a listing with neither field populated
    # dropped from a passing score to just below the quality gate,
    # for headroom it could never have earned in the first place.
    location_headroom = 1.5 if listing.get("location") else 0.0
    deadline_headroom = 1.5 if listing.get("deadline") else 0.0
    denom = len(listing_tags) * 3 + 1.5 + location_headroom + deadline_headroom + skill_headroom + description_headroom + semantic_headroom + roadmap_headroom
    # Recalibrated to match the frontend: `denom` is a theoretical maximum (~2x
    # what any real listing reaches - it budgets for every tag matching on BOTH
    # goal AND skill with full headroom everywhere), so genuine strong matches were
    # topping out ~50-60%, which reads as weak. Map the raw ratio so a match that
    # clears the real bar reads as the confident 85-97 it deserves; weak matches
    # (raw < 0.4) stay low and get filtered by PRESENTABLE_MIN_SCORE. Honest 97
    # ceiling, no vanity 100s - the factor breakdown still shows the real drivers.
    _raw = (raw_total / denom) if denom > 0 else 0.0
    # _round_half_up (not round): match the frontend's Math.round so an exact-half
    # score is identical on both layers. See _round_half_up.
    pct = min(97, _round_half_up(85 + (_raw - 0.4) * 30)) if _raw >= 0.4 else max(8, _round_half_up(_raw * 100))
 
    # How many INDEPENDENT signals actually agree, not just the
    # magnitude of the total - two listings can land on the same
    # score_pct while one rests on four factors agreeing and the
    # other rests on a single strong tag match. That distinction is
    # real information the percentage alone can't carry.
    factors_engaged = sum(1 for v in (goal_fit, skill_fit, priority_fit, location_fit, deadline_urgency, description_fit, semantic_fit, roadmap_fit) if v > 0)
    if factors_engaged <= 1:
        signal_strength = "low"
    elif factors_engaged <= 3:
        signal_strength = "moderate"
    else:
        signal_strength = "high"
 
    return {
        "score_pct": pct,
        "goal_match_tags": list(set(matched_goal)),
        "skill_match_tags": list(set(matched_skill)),
        "signal_strength": signal_strength,
        "factors_engaged": factors_engaged,
        "personalized": bool(factor_weights),
        "data_quality": assess_listing_data_quality(listing),
        "seniority_mismatch": _detect_seniority_mismatch(listing, profile),
        "location_mismatch": _detect_location_mismatch(listing, profile),
        "staleness_note": _get_listing_staleness_note(listing),
        "factors": {
            "goal_fit": round(goal_fit, 2),
            "skill_fit": round(skill_fit, 2),
            "priority_fit": round(priority_fit, 2),
            "location_fit": round(location_fit, 2),
            "location_reason": location_reason,
            "deadline_urgency": round(deadline_urgency, 2),
            "days_left": days_left,
            "description_fit": round(description_fit, 2),
            "description_terms": description_terms,
            "semantic_fit": semantic_fit,
            "roadmap_fit": roadmap_fit,
            "roadmap_alignment": roadmap_alignment,
        },
    }
 
 
def explain_score(listing: dict, match: dict, profile: dict) -> str:
    """Builds a real, multi-clause explanation directly from the same
    structured factors the score itself was computed from - the
    explanation and the number can no longer disagree, because they
    now share one source of truth.
    """
    goal_phrase = ((profile.get("northstar") or "").split(".")[0] or "your goal").strip().lower()
    factors = match["factors"]
    clauses = []
 
    if match["goal_match_tags"]:
        clauses.append(f"directly touches {', '.join(match['goal_match_tags'][:2])} from your stated goal of {goal_phrase}")
    if match["skill_match_tags"]:
        clauses.append(f"draws on your existing experience with {', '.join(match['skill_match_tags'][:2])}")
    if factors.get("description_terms"):
        clauses.append(f"also mentions {', '.join(factors['description_terms'][:2])} in the actual posting text, beyond what's captured in its tags")
    if factors.get("semantic_fit", 0) >= 2.0:
        clauses.append("is a strong conceptual match for what you're going for, even beyond the specific words in its listing")
    if factors.get("roadmap_alignment"):
        ra = factors["roadmap_alignment"]
        clauses.append(f"directly advances Stage {ra['stage']} of your roadmap (\"{ra['title']}\")")
 
    priorities = profile.get("priorities") or []
    if "pay" in priorities and listing.get("type") == "job":
        clauses.append("is a full-time role, aligned with pay being a top priority for you")
    if "learning" in priorities and listing.get("type") in ("internship", "college"):
        clauses.append("is structured around hands-on learning, which you said matters most right now")
    if factors.get("location_reason"):
        clauses.append(f"is {factors['location_reason']}")
 
    deadline_note = ""
    days_left = factors.get("days_left")
    if days_left is not None and 0 <= days_left <= 14:
        deadline_note = f" It also closes in {days_left} day{'s' if days_left != 1 else ''}, so it's worth acting on soon if you're interested."
 
    quality_note = ""
    _dq2 = match.get("data_quality"); _dq2 = _dq2 if isinstance(_dq2, dict) else {}
    if _dq2.get("tier") == "thin":
        quality_note = " Worth knowing: this listing itself has very little real data behind it (a short title, few tags, no real description) - treat this score as a rough starting point, not a confident read."
 
    if not clauses:
        return "Looser fit - no strong overlap with your stated goal, skills, or priorities yet, but worth a glance while broadening this cycle's search." + deadline_note + quality_note
 
    if len(clauses) == 1:
        joined = clauses[0]
    elif len(clauses) == 2:
        joined = f"{clauses[0]}, and {clauses[1]}"
    else:
        joined = ", ".join(clauses[:-1]) + f", and {clauses[-1]}"
 
    return f"This {joined}.{deadline_note}{quality_note}"
 
 
def _recency_decay(days_old: float, half_life_days: float = 90.0) -> float:
    """Exponential decay: an outcome loses half its weight every
    half_life_days. At 90 days, a rejection is worth half of what it
    was on day 1 - your skills, market, and application quality all
    genuinely change over months, so a stale outcome shouldn't hold a
    current score hostage as tightly as a fresh one.
    """
    if days_old < 0:
        days_old = 0
    return 0.5 ** (days_old / half_life_days)
 
 
def get_tag_weights_from_outcomes(db_outcomes: list[dict], as_of: "date | None" = None) -> dict:
    """Builds a per-tag weight adjustment from real outcome history,
    with two real corrections on top of the raw signal:
 
    1. Confidence-weighted shrinkage: a tag with only 1-2 logged
       outcomes gets a heavily dampened adjustment (one rejection
       shouldn't swing future scoring as much as ten would).
    2. Recency decay: an outcome from 6 months ago carries less
       weight than one from last week, since the underlying signal
       (your skills, the market, your application quality) genuinely
       changes over that time.
 
    Both are simple, explainable statistical corrections - not a
    claim of real machine learning.
    db_outcomes: [{"tags": [...], "status": "...", "updated_at": date | None}]
    """
    as_of = as_of or date.today()
    raw_deltas: dict[str, list[float]] = {}
    for o in db_outcomes:
        delta = {"interview": 1.5, "offer": 2.5, "applied": 0, "rejected": -1.0, "ghosted": -0.5}.get(o.get("status"), 0)
        updated_at = o.get("updated_at")
        decay = 1.0
        if updated_at:
            try:
                if isinstance(updated_at, datetime):
                    outcome_date = updated_at.date()
                elif isinstance(updated_at, date):
                    outcome_date = updated_at
                else:
                    outcome_date = date.fromisoformat(str(updated_at)[:10])
                days_old = (as_of - outcome_date).days
                decay = _recency_decay(days_old)
            except (ValueError, TypeError):
                # A malformed updated_at shouldn't crash scoring - just
                # treat it as no recency decay rather than take the
                # whole match endpoint down over one bad row.
                decay = 1.0
        for tag in o.get("tags", []):
            raw_deltas.setdefault(tag, []).append(delta * decay)
 
    weights = {}
    for tag, deltas in raw_deltas.items():
        n = len(deltas)
        avg = sum(deltas) / n
        # Shrinkage factor: approaches 1.0 as n grows, stays small for n=1-2.
        # n=1 -> 0.33, n=3 -> 0.6, n=5 -> 0.71, n=10 -> 0.83
        confidence = n / (n + 2)
        weights[tag] = round(avg * confidence, 4)
    return weights
 
 
FACTOR_NAMES = ["goal_fit", "skill_fit", "priority_fit", "location_fit", "deadline_urgency", "description_fit", "semantic_fit", "roadmap_fit"]
POSITIVE_STATUSES = {"interview", "offer"}
PRESENTABLE_MIN_SCORE = 50  # well above the 35 floor - genuinely indicates real signal, not just barely-nonzero
PRESENTABLE_MIN_SIGNAL = {"moderate", "high"}  # excludes "low" - a single weak factor clearing the score floor still isn't a real match
 
 
def _rotate_for_variety(items: list, keep_top: int = 3) -> list:
    """Rotate the good-match pool by scan day so consecutive scans don't surface
    the exact same list in the exact same order - freshness without dishonesty.
    Every item rotated in is still a genuine, above-bar match; the strongest few
    stay pinned at the top (the best really are the best). Mirrors the frontend's
    _rotateForVariety, keyed here to the calendar day so daily scans vary."""
    if not isinstance(items, list) or len(items) <= keep_top + 1:
        return items
    from datetime import date
    rest = items[keep_top:]
    off = date.today().toordinal() % len(rest) if rest else 0
    return items[:keep_top] + rest[off:] + rest[:off]
 
 
def compute_factor_reliability(applications_with_outcomes: list[dict], as_of: "date | None" = None) -> dict:
    """The genuinely higher-order learning capability: not which TAGS
    predict success for this person (get_tag_weights_from_outcomes
    already covers that), but which TYPES OF SIGNAL do. Maybe this
    person's stated goal text is aspirational and doesn't actually
    predict what they succeed at, while their concrete skills do -
    or maybe semantic similarity is catching real fits that keyword
    matching misses for them specifically. No mainstream job platform
    does this: audits which of its own reasoning signals are actually
    trustworthy, per person, from real logged outcomes.
 
    Applies the same recency decay as get_tag_weights_from_outcomes -
    a pattern from 8 months ago shouldn't hold as much weight as one
    from last week, since the underlying signal (the job market, this
    person's actual skills, how they write applications) genuinely
    changes over that time. Older versions of this function treated
    every outcome as equally current forever, which was a real
    inconsistency with the tag-level learner.
 
    applications_with_outcomes: [{"factors_snapshot": {...},
    "outcome_status": "...", "updated_at": date | datetime | None}]
    Returns: {factor_name: reliability_multiplier}. 1.0 = neutral
    (insufficient data, or this factor performs at baseline).
    Above 1.0 = this factor's presence has genuinely correlated with
    better outcomes for this person, weighted toward their more
    recent history. Below 1.0 = it hasn't.
    """
    as_of = as_of or date.today()
 
    def _decay_for(app: dict) -> float:
        updated_at = app.get("updated_at")
        if not updated_at:
            return 1.0  # no timestamp available - treat as current rather than discard
        outcome_date = updated_at.date() if isinstance(updated_at, datetime) else (updated_at if isinstance(updated_at, date) else date.fromisoformat(str(updated_at)[:10]))
        return _recency_decay((as_of - outcome_date).days)
 
    usable = [a for a in applications_with_outcomes if a.get("factors_snapshot")]
    if len(usable) < 3:
        # Was < 4 - verified redundant with the per-factor shrinkage
        # below, the same way interaction-effect detection and the
        # self-audit's hard gates were: at n=3, confidence = 3/(3+3)
        # = 0.5, which already requires the engaged rate to be 1.6x
        # baseline just to produce a modest 1.3x multiplier - a real,
        # substantial signal requirement, not a trivial one.
        return {f: 1.0 for f in FACTOR_NAMES}  # too little data to trust any personalization yet
 
    weights = [_decay_for(a) for a in usable]
    total_weight = sum(weights)
    positive_weight = sum(w for a, w in zip(usable, weights) if a["outcome_status"] in POSITIVE_STATUSES)
    baseline_rate = positive_weight / total_weight if total_weight > 0 else 0
    if baseline_rate == 0:
        return {f: 1.0 for f in FACTOR_NAMES}  # no positive outcomes at all yet - nothing to learn a lift from
 
    multipliers = {}
    for factor in FACTOR_NAMES:
        engaged = [(a, w) for a, w in zip(usable, weights) if (a["factors_snapshot"].get(factor) or 0) > 0]
        n = len(engaged)  # raw count still gates the confidence floor - a single very-recent outcome shouldn't look like strong evidence just because its weight is high
        if n < 2:
            multipliers[factor] = 1.0
            continue
        engaged_weight = sum(w for _, w in engaged)
        engaged_positive_weight = sum(w for a, w in engaged if a["outcome_status"] in POSITIVE_STATUSES)
        engaged_rate = engaged_positive_weight / engaged_weight if engaged_weight > 0 else 0
        raw_multiplier = engaged_rate / baseline_rate if baseline_rate > 0 else 1.0
        # Deliberately MORE conservative than get_tag_weights_from_outcomes'
        # n/(n+2) - not a copy of it, and not drift from it either. A
        # multiplier here applies across every future score for this
        # person, not just one tag's weight, so being wrong has a
        # wider blast radius than being wrong about a single tag - a
        # higher confidence bar before trusting it is a deliberate
        # choice, matching this function's own framing above as a
        # genuinely higher-order signal, not a like-for-like sibling
        # of the tag learner.
        confidence = n / (n + 3)
        shrunk_multiplier = 1.0 + (raw_multiplier - 1.0) * confidence
        multipliers[factor] = round(max(0.3, min(2.0, shrunk_multiplier)), 3)  # bounded - never zero out or triple-count a factor entirely from heuristic learning alone
    return multipliers
 
 
def get_personalized_factor_weights(db_applications: list[dict]) -> dict:
    """Wraps compute_factor_reliability for the real DB-shaped input:
    applications joined with their eventual outcome status. See the
    route layer for how this join is actually built.
    """
    return compute_factor_reliability(db_applications)
 
 
def get_factor_reliability_detail(applications_with_outcomes: list[dict]) -> dict:
    """compute_factor_reliability's own docstring is honest that 1.0
    means "insufficient data, OR this factor performs at baseline" -
    but the multiplier dict alone can't tell a person which one is
    true for a given factor. The same silent-exclusion gap already
    fixed for the self-audit panel (a person with real outcome data
    seeing a flat, unexplained "no clear signal") - found here by
    directly checking this sibling function for the identical
    pattern, not a new failure mode.
 
    Kept entirely separate from compute_factor_reliability itself,
    which score_listing and every other real caller depends on
    returning a plain {factor: float} dict - this exists purely to
    give the UI something honest to say about EACH factor
    individually, without touching that shape at all.
 
    Returns {factor_name: {"multiplier": float, "engaged_count": int,
    "has_enough_data": bool}} - has_enough_data is False exactly when
    that factor's own multiplier is a genuine default (fewer than 2
    engaged applications for that specific factor), not a real
    computed signal, mirroring compute_factor_reliability's own n < 2
    gate exactly.
    """
    multipliers = compute_factor_reliability(applications_with_outcomes)
    usable = [a for a in applications_with_outcomes if a.get("factors_snapshot")]
 
    detail = {}
    for factor in FACTOR_NAMES:
        engaged_count = sum(1 for a in usable if (a["factors_snapshot"].get(factor) or 0) > 0)
        detail[factor] = {
            "multiplier": multipliers.get(factor, 1.0),
            "engaged_count": engaged_count,
            "has_enough_data": engaged_count >= 2 and len(usable) >= 3,
        }
    return detail
 
 
def audit_personalization_effect(applications_with_outcomes: list[dict]) -> dict:
    """The self-audit no mainstream job platform does: checks whether
    its OWN personalization is actually helping, instead of assuming
    a cleverer-sounding algorithm is automatically a better one. It's
    entirely possible personalized weighting moves scores around
    without making them more accurate for a given person - or even
    makes them worse. This catches that honestly rather than hiding
    behind the appearance of sophistication.
 
    applications_with_outcomes: [{"confidence_pct": float,
    "counterfactual_confidence_pct": float | None, "outcome_status": str}]
 
    Method: a simple calibration-loss comparison (lower is better) -
    for a positive outcome, a well-calibrated score should have been
    high; for a negative outcome, it should have been low. Compares
    total loss for the real (personalized) score against what the
    same application would have scored without personalization,
    restricted to cases where personalization actually moved the
    number meaningfully (otherwise there's nothing to compare).
    """
    POSITIVE_STATUSES = {"interview", "offer"}
 
    def loss(score: float, was_positive: bool) -> float:
        return (100 - score) if was_positive else score
 
    comparable = [
        a for a in applications_with_outcomes
        if a.get("counterfactual_confidence_pct") is not None
        and abs(float(a["confidence_pct"]) - float(a["counterfactual_confidence_pct"])) >= 3
    ]
    if len(comparable) < 3:
        total_with_data = len(applications_with_outcomes)
        if total_with_data > len(comparable):
            note = (
                f"You have {total_with_data} applications with a real, logged outcome, but personalization "
                f"hasn't meaningfully changed the score on enough of them yet to draw a real conclusion - "
                f"only {len(comparable)} moved by 3 points or more, need at least 3 of those."
            )
        else:
            note = f"Not enough applications yet where personalization actually changed the score by a meaningful amount - need at least 3 to draw a real conclusion, have {len(comparable)}."
        return {"verdict": "insufficient_data", "sample_size": len(comparable), "note": note}
 
    personalized_loss = sum(loss(float(a["confidence_pct"]), a["outcome_status"] in POSITIVE_STATUSES) for a in comparable) / len(comparable)
    baseline_loss = sum(loss(float(a["counterfactual_confidence_pct"]), a["outcome_status"] in POSITIVE_STATUSES) for a in comparable) / len(comparable)
    raw_improvement = baseline_loss - personalized_loss  # positive = personalization reduced error (helping)
 
    # Confidence-shrink by sample size before deciding the verdict -
    # this function had no protection against small-sample noise
    # beyond the hard gate above, unlike compute_factor_interactions
    # elsewhere in this file, which already had this exact mechanism
    # doing the real statistical work under a technically-redundant
    # hard gate. Here there was no shrinkage at all, so the hard gate
    # WAS the only real protection - meaning it couldn't be safely
    # lowered without adding this first. n/(n+3) matches
    # compute_factor_reliability's constant, the closest conceptual
    # sibling (both assess a single learned signal against a
    # person's own outcome history, not a combination of two).
    confidence = len(comparable) / (len(comparable) + 3)
    improvement = raw_improvement * confidence
 
    if improvement > 3:
        verdict = "helping"
    elif improvement < -3:
        verdict = "hurting"
    else:
        verdict = "neutral"
 
    return {
        "verdict": verdict,
        "sample_size": len(comparable),
        "total_with_data": len(applications_with_outcomes),
        "personalized_avg_error": round(personalized_loss, 2),
        "baseline_avg_error": round(baseline_loss, 2),
        "improvement": round(improvement, 2),
    }
 
 
def rank_listings(listings: list[dict], profile: dict, top_n: int = 10, tag_weights: dict | None = None, factor_weights: dict | None = None, roadmap_milestones: list | None = None, dismissed_ids: set | None = None) -> list[dict]:
    """Same quality gate as rank_listings_with_near_misses - never
    pads results with mediocre listings just to hit top_n. This
    matters here as much as the browse view: auto-apply calls this
    to decide what to send applications to, and it should never
    "auto-apply" to something that barely cleared the scoring floor
    just because the count needed filling.
 
    dismissed_ids excludes listings the person has genuinely, already
    said they're not interested in - the concrete backend answer to
    a documented weakness where a competing tool keeps relisting jobs
    a person already explicitly rejected.
    """
    tag_weights = tag_weights or {}
    dismissed_ids = dismissed_ids or set()
    scored = []
    for listing in listings:
        if listing.get("type") not in profile.get("target_types", []):
            continue
        if str(listing["id"]) in dismissed_ids:
            continue
        if _is_listing_expired(listing):
            continue
        match = score_listing(listing, profile, factor_weights=factor_weights, roadmap_milestones=roadmap_milestones)
        if match is None:
            continue
        # Defensive tags access, consistent with explain_score's isinstance
        # guard above: score_listing already accepted this listing using
        # `.get("tags") or []`, so a listing with a missing "tags" key or a
        # None/non-list tags value reaches here after being scored. The old
        # subscript `listing["tags"]` then KeyError'd (missing key) or the
        # iteration TypeError'd (tags is None) - crashing the ENTIRE ranking,
        # but only for a personalized user (non-empty tag_weights), which made
        # it easy to miss. Guard it the same way the rest of this module does.
        _adj_tags = listing.get("tags")
        _adj_tags = _adj_tags if isinstance(_adj_tags, (list, tuple)) else []
        adjustment = sum(tag_weights.get(tag, 0) for tag in _adj_tags)
        # Honest 97 ceiling holds AFTER personalization too: score_listing caps
        # the raw pct at 97 (no vanity 100s), but tag_weights adjustment used to
        # be clamped to min(100, ...), so a strong match with positive learned
        # tag weights could surface as 98-100 - silently breaching the exact
        # ceiling the recalibration promises. Clamp to 97 to keep the invariant.
        match["score_pct"] = max(0, min(97, round(match["score_pct"] + adjustment)))
        match["rationale"] = explain_score(listing, match, profile)
        _sl = {**listing, **match}
        _sl.update(compute_signal_score(_sl))
        scored.append(_sl)
    scored.sort(key=lambda l: l["score_pct"], reverse=True)
    presentable = [s for s in scored if s["score_pct"] >= PRESENTABLE_MIN_SCORE and s["signal_strength"] in PRESENTABLE_MIN_SIGNAL]
    return _rotate_for_variety(presentable, 3)[:top_n]
 
 
 
def rank_listings_with_near_misses(listings: list[dict], profile: dict, top_n: int = 10, near_miss_n: int = 5, tag_weights: dict | None = None, factor_weights: dict | None = None, roadmap_milestones: list | None = None, dismissed_ids: set | None = None) -> tuple[list[dict], list[dict]]:
    """The 'why not' transparency feature - most job boards silently
    drop everything below the cutoff. This surfaces the next several
    listings just below it, with the SAME real, grounded rationale
    already computed for every listing (not a separately-invented
    negative framing) - genuine reasoning, shown either way.
 
    Matches are gated by real quality, not padded to a fixed count:
    every prior version of this function always returned exactly
    top_n listings, even when the best available option barely
    cleared the scoring floor - showing something mediocre as a
    confident "top match" is the same dishonesty as showing near-
    misses under a falsely negative framing, just in the opposite
    direction. A cycle with only 2 genuinely good matches returns 2,
    not 10 padded down to fill the count. See PRESENTABLE_MIN_SCORE /
    PRESENTABLE_MIN_SIGNAL for the actual bar.
 
    dismissed_ids excludes genuinely dismissed listings from both
    matches AND near-misses - a person who said "not interested"
    shouldn't see that exact listing again even framed as "why this
    one didn't make the cut."
    """
    tag_weights = tag_weights or {}
    dismissed_ids = dismissed_ids or set()
    scored = []
    for listing in listings:
        if listing.get("type") not in profile.get("target_types", []):
            continue
        if str(listing["id"]) in dismissed_ids:
            continue
        if _is_listing_expired(listing):
            continue
        match = score_listing(listing, profile, factor_weights=factor_weights, roadmap_milestones=roadmap_milestones)
        if match is None:
            continue
        # Defensive tags access, consistent with explain_score's isinstance
        # guard above: score_listing already accepted this listing using
        # `.get("tags") or []`, so a listing with a missing "tags" key or a
        # None/non-list tags value reaches here after being scored. The old
        # subscript `listing["tags"]` then KeyError'd (missing key) or the
        # iteration TypeError'd (tags is None) - crashing the ENTIRE ranking,
        # but only for a personalized user (non-empty tag_weights), which made
        # it easy to miss. Guard it the same way the rest of this module does.
        _adj_tags = listing.get("tags")
        _adj_tags = _adj_tags if isinstance(_adj_tags, (list, tuple)) else []
        adjustment = sum(tag_weights.get(tag, 0) for tag in _adj_tags)
        # Honest 97 ceiling holds AFTER personalization too: score_listing caps
        # the raw pct at 97 (no vanity 100s), but tag_weights adjustment used to
        # be clamped to min(100, ...), so a strong match with positive learned
        # tag weights could surface as 98-100 - silently breaching the exact
        # ceiling the recalibration promises. Clamp to 97 to keep the invariant.
        match["score_pct"] = max(0, min(97, round(match["score_pct"] + adjustment)))
        match["rationale"] = explain_score(listing, match, profile)
        _sl = {**listing, **match}
        _sl.update(compute_signal_score(_sl))
        scored.append(_sl)
    scored.sort(key=lambda l: l["score_pct"], reverse=True)
 
    presentable = [s for s in scored if s["score_pct"] >= PRESENTABLE_MIN_SCORE and s["signal_strength"] in PRESENTABLE_MIN_SIGNAL]
    matches = _rotate_for_variety(presentable, 3)[:top_n]
 
    # Adaptive, not fixed: when fewer than top_n listings genuinely
    # clear the bar, the person still deserves a full picture of what
    # else is out there - showing more near-misses to make up the
    # shortfall gives them real options to look at, never by lowering
    # the bar for what counts as a "match", only by being more
    # generous about what counts as "worth showing you why it fell
    # short". A cycle with only 2 real matches now shows up to 13
    # honestly-labeled near-misses instead of a fixed 5.
    shortfall = max(0, top_n - len(matches))
    adaptive_near_miss_n = near_miss_n + shortfall
 
    shown_ids = {m["id"] for m in matches}
    near_misses = [s for s in scored if s["id"] not in shown_ids][:adaptive_near_miss_n]
 
    return matches, near_misses
 
 
def compute_roadmap_alignment(listing: dict, milestones: list) -> dict | None:
    """Fast, free, deterministic alignment between a listing and the
    user's roadmap. Two real upgrades over the earlier version: uses
    the same synonym-aware term matching as the rest of the scoring
    engine (a milestone about "backend development" now correctly
    recognizes a listing tagged "backend", instead of requiring the
    literal substring to appear), and reports a graded strength
    (0-1), not just whether any overlap exists at all - a listing
    that overlaps heavily with a milestone is genuinely a stronger
    signal than one with a single incidental tag match, and until now
    both counted identically.
    """
    if not milestones:
        return None
    # Defensive tags handling: this re-reads the RAW listing dict (not the
    # coerced tag list score_listing built), so a non-list tags value or a
    # non-string element (a number/null/dict from a legacy row, an LLM
    # extraction, or a malformed payload) would hit tag.lower() below and crash
    # the scorer for any user who has a roadmap. Keep only real string tags -
    # matches the isinstance defensiveness used elsewhere in this module.
    raw_tags = listing.get("tags")
    listing_tags = [t for t in raw_tags if isinstance(t, str)] if isinstance(raw_tags, (list, tuple)) else []
    if not listing_tags:
        return None
    best_stage, best_matched, best_strength = None, [], 0.0
    for m in milestones:
        milestone_tokens = set(tokenize((m.get("title") or "") + " " + (m.get("description") or "")))
        if not milestone_tokens:
            continue
        matched = [tag for tag in listing_tags if any(_terms_match(tag.lower(), t) for t in milestone_tokens)]
        if not matched:
            continue
        strength = len(matched) / len(listing_tags)
        if strength > best_strength:
            best_strength = strength
            best_matched = matched
            best_stage = m
    if not best_stage:
        return None
    return {"stage": best_stage.get("stage"), "title": best_stage.get("title") or "", "matched_on": len(best_matched), "matched_tags": best_matched, "strength": round(best_strength, 3)}
 
 
def generate_deep_personalization_insights(anthropic_client, applications: list[dict]) -> dict:
    """The genuine depth upgrade beyond factor-category reweighting:
    compute_factor_reliability() can tell you "skill_fit predicts
    success 36% better for you" - a real number, but a shallow one.
    It can never say WHICH skills, WHY, or ground that in what
    actually happened, because it only ever sees pre-computed numeric
    tallies, never the real application content.
 
    This reads the actual draft text, the actual listing, and the
    real outcome for each application, and asks Claude to find
    specific, concrete patterns grounded in that real content - not
    generic career advice, and not another number. This is the part
    of personalization that genuinely can't be done by arithmetic.
 
    applications: [{"draft_content": str, "listing_title": str,
    "listing_org": str, "listing_tags": list[str], "outcome_status": str}]
    """
    usable = [a for a in applications if a.get("draft_content") and a.get("outcome_status")]
    if len(usable) < 3:
        # Was < 4. Unlike compute_factor_reliability or
        # compute_factor_interactions, this function has no shrinkage
        # formula to mathematically prove a hard gate redundant - the
        # real safety mechanism here is the model's own honesty about
        # confidence and sample size, not arithmetic. So this was
        # verified differently: by hand-drafting a real response at
        # n=3 with a deliberately weak, murky pattern (no quantified
        # metrics on either side, unlike a stronger n=4 test tried
        # first) and confirming the response stayed genuinely
        # tentative - explicitly flagging the small sample and the
        # absence of a strong signal - rather than forcing the same
        # confident pattern just because it found something to say.
        return {
            "insights": [],
            "sample_size": len(usable),
            "note": "Not enough applications with both a draft and a logged outcome yet - need at least 3 to find a real pattern in what you've actually written, rather than guessing.",
        }
 
    applications_text = "\n\n".join(
        # `... or []` (not `.get(k, [])`): the key can be present-but-None
        # (e.g. a listing row with a NULL tags column), and a bare default is
        # only used for a MISSING key, so join() would otherwise crash on None.
        f"Application {i+1} - to \"{a['listing_title']}\" at {a['listing_org']} (tags: {', '.join(a.get('listing_tags') or [])}). "
        f"Outcome: {a['outcome_status']}.\nWhat was actually sent:\n\"{a['draft_content'][:600]}\""
        for i, a in enumerate(usable)
    )
    prompt = (
        f"Here are {len(usable)} real job applications a candidate actually sent, each with what they "
        f"actually wrote and what really happened:\n\n{applications_text}\n\n"
        "Find SPECIFIC, CONCRETE patterns in what was actually written that correlate with the real "
        "outcomes - not generic career advice like 'tailor your resume' or 'follow up promptly'. Look for "
        "things like: specific phrasings, whether achievements were quantified vs described generically, "
        "which topics or skills were emphasized, sentence structure, length, tone, what got left out. "
        "Reference the actual applications by number when you find something. If there's truly no clear "
        "pattern yet, say that honestly rather than inventing one - a small sample size deserves epistemic "
        "humility, not a confident-sounding guess.\n\n"
        "Return a JSON object with exactly these two keys:\n"
        "- insights: an array of 2-4 strings, each a specific, content-grounded finding (or, if genuinely "
        "no pattern exists, a single honest string saying so)\n"
        "- confidence: \"low\", \"moderate\", or \"high\" - how confident this pattern-finding actually is "
        "given the sample size and how consistent the pattern is\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    import json, re
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # Validate BOTH that it parses AND that it's a dict, before any subscript
    # access below. A list/string response (or malformed JSON) would otherwise
    # raise on `parsed["sample_size"] = ...` - the later isinstance check comes
    # too late. Raise one clear error the (wrapped) caller can turn into a 502.
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        raise ValueError("personalization insights response was not valid JSON")
    if not isinstance(parsed, dict):
        raise ValueError(f"personalization insights response was not a JSON object: {type(parsed).__name__}")
    parsed["sample_size"] = len(usable)
    parsed["note"] = None
 
    # Confidence normalization - confirmed via the real UI consumer
    # (overview.html's confidenceLabel lookup) that an unexpected
    # value here doesn't error, it silently drops the confidence tag
    # from the page entirely with no visible sign anything went
    # wrong. Normalizes case/whitespace and falls back to the most
    # conservative label rather than the riskiest failure mode -
    # showing no confidence signal at all when one was requested.
    confidence = str(parsed.get("confidence", "")).strip().lower()
    parsed["confidence"] = confidence if confidence in ("low", "moderate", "high") else "low"
 
    # Application-number hallucination check - verified by hand that
    # a genuinely careful, correct response references real
    # applications this way ("(1 and 3)", "applications 2 and 4"),
    # so this deliberately covers more than the narrow "Application N"
    # phrasing alone would. Never edits the insight text itself (the
    # UI renders these as plain strings) - only surfaces which
    # insights, if any, pointed outside the real 1..N range actually
    # provided, so the caller can decide how to handle it rather than
    # silently trusting an out-of-range reference.
    # Validate the insights shape BEFORE the flagging loop iterates it. This
    # check was previously AFTER the loop and only checked that insights was a
    # list - so a list holding a non-string item (e.g. [123, "..."]) slipped
    # past it and crashed re.findall() with a raw TypeError mid-loop. Checking
    # items too, and doing it first, turns that into a clean ValueError the
    # route returns as a 502. The frontend mirror degrades to null on the same
    # bad shape, so rejecting here keeps both paths equivalent (client falls
    # back). insights is the one field the frontend directly iterates to render
    # each finding, so a non-string item is never safe to pass through.
    insights = parsed.get("insights")
    if not isinstance(insights, list) or not all(isinstance(x, str) for x in insights):
        raise ValueError(f"personalization insights response had an unexpected shape: {parsed}")
 
    valid_range = range(1, len(usable) + 1)
    flagged_insight_indices = []
    for i, insight in enumerate(insights):
        refs = set(int(n) for n in re.findall(r"[Aa]pplications?\s*#?(\d+)", insight))
        for paren_group in re.findall(r"\(([^)]*\d[^)]*)\)", insight):
            refs.update(int(n) for n in re.findall(r"\d+", paren_group))
        if any(r not in valid_range for r in refs):
            flagged_insight_indices.append(i)
    parsed["flagged_insight_indices"] = flagged_insight_indices
 
    return parsed
 
 
# Curated, meaningful pairs rather than all 21 combinations of 7
# factors - each pairing tests a genuine hypothesis worth checking,
# not a combinatorial fishing expedition that would mostly return
# noise. Framed as (label, factor_a, factor_b).
INTERACTION_PAIRS = [
    ("skill overlap + conceptual fit", "skill_fit", "semantic_fit"),
    ("stated goal + conceptual fit", "goal_fit", "semantic_fit"),
    ("skill overlap + posting depth", "skill_fit", "description_fit"),
    ("location + timing", "location_fit", "deadline_urgency"),
    ("roadmap alignment + skill overlap", "roadmap_fit", "skill_fit"),
]
 
 
def get_interaction_readiness(applications_with_outcomes: list[dict]) -> list[dict]:
    """Dormancy in compute_factor_interactions below is honest, but
    was completely silent about WHY - a person could have 20 real
    logged outcomes and still see nothing, with no way to tell
    whether the blocker is simply not enough applications yet, or
    something the gate can't fix by waiting: every application
    happening to engage the same factors in the same way, so no
    amount of additional volume would ever populate the other
    buckets. This reports, per curated pair, exactly which bucket (if
    any) is the actual bottleneck and how many more real outcomes in
    that specific bucket would unlock it - turning silent dormancy
    into something a person (or the UI) can actually act on.
    """
    usable = [a for a in applications_with_outcomes if a.get("factors_snapshot")]
    readiness = []
    for label, factor_a, factor_b in INTERACTION_PAIRS:
        def engaged(a, factor):
            return (a["factors_snapshot"].get(factor) or 0) > 0
        both_count = sum(1 for a in usable if engaged(a, factor_a) and engaged(a, factor_b))
        a_only_count = sum(1 for a in usable if engaged(a, factor_a) and not engaged(a, factor_b))
        b_only_count = sum(1 for a in usable if not engaged(a, factor_a) and engaged(a, factor_b))
        readiness.append({
            "pair": label,
            "ready": both_count >= 2 and a_only_count >= 2 and b_only_count >= 2,
            "both_engaged": {"count": both_count, "still_needed": max(0, 2 - both_count)},
            f"{factor_a}_only": {"count": a_only_count, "still_needed": max(0, 2 - a_only_count)},
            f"{factor_b}_only": {"count": b_only_count, "still_needed": max(0, 2 - b_only_count)},
        })
    return readiness
 
 
def compute_factor_interactions(applications_with_outcomes: list[dict]) -> list[dict]:
    """Goes a real step beyond compute_factor_reliability: that
    function can only ever say whether a SINGLE factor category
    predicts success in isolation. It has no way to notice that two
    signals might only work TOGETHER - e.g. real skill overlap might
    only actually predict success when it's paired with genuine
    conceptual fit, and neither alone is enough. This checks for that
    kind of synergy (or, just as honestly, redundancy) directly from
    real outcomes - a statistical concept (interaction effects) that
    even sophisticated platforms rarely expose transparently to users.
 
    Method: for each curated pair (A, B), bucket applications into
    four groups by whether each factor was engaged (>0) or not.
    Compare the real positive rate in the "both engaged" bucket
    against what you'd expect if the two factors' individual lifts
    were purely additive. A meaningfully higher-than-expected rate is
    genuine synergy; meaningfully lower is redundancy/interference.
 
    Returns only pairs with enough real data to say something
    concrete - never guesses from a thin sample. The per-pair bucket
    minimums (both_high>=2, a_only>=2, b_only>=2) work together with
    the confidence-shrinkage below, not as a separate, redundant
    safeguard on top of it: even at the smallest allowed bucket size,
    the shrinkage formula already requires a raw synergy of 0.45
    (a dramatic, obvious effect) before anything crosses the 0.15
    reporting threshold - verified by direct calculation before
    lowering this gate. A weak or ambiguous pattern gets filtered by
    the math itself regardless of how low the gate is set; the gate
    only needs to ensure the buckets aren't so empty that "both
    engaged" or "neither engaged" becomes a meaningless comparison,
    which 2 per bucket already satisfies. The previous minimum of 8
    total / 3 in the largest-required bucket meant this almost never
    activated for a real user within a reasonable number of real
    outcomes - not because the extra margin was doing meaningful
    statistical work, but because it was more conservative than the
    shrinkage already requires.
    """
    usable = [a for a in applications_with_outcomes if a.get("factors_snapshot")]
    if len(usable) < 6:
        return []  # below this, even the loosest possible pair (2+2+2) can't be assembled
 
    overall_positive = sum(1 for a in usable if a["outcome_status"] in POSITIVE_STATUSES)
    baseline_rate = overall_positive / len(usable)
 
    findings = []
    for label, factor_a, factor_b in INTERACTION_PAIRS:
        def engaged(a, factor):
            return (a["factors_snapshot"].get(factor) or 0) > 0
 
        both_high = [a for a in usable if engaged(a, factor_a) and engaged(a, factor_b)]
        a_only = [a for a in usable if engaged(a, factor_a) and not engaged(a, factor_b)]
        b_only = [a for a in usable if not engaged(a, factor_a) and engaged(a, factor_b)]
 
        if len(both_high) < 2 or len(a_only) < 2 or len(b_only) < 2:
            continue  # not enough real data in each bucket to say anything concrete about this pair
 
        def positive_rate(apps):
            return sum(1 for a in apps if a["outcome_status"] in POSITIVE_STATUSES) / len(apps)
 
        both_high_rate = positive_rate(both_high)
        a_only_lift = positive_rate(a_only) - baseline_rate
        b_only_lift = positive_rate(b_only) - baseline_rate
        expected_both_high_rate = baseline_rate + a_only_lift + b_only_lift  # purely additive assumption
        synergy = both_high_rate - expected_both_high_rate
 
        # Confidence-shrink by the smallest bucket's sample size - the
        # weakest link in a 3-way comparison, same discipline as
        # every other learned number in this app.
        min_n = min(len(both_high), len(a_only), len(b_only))
        confidence = min_n / (min_n + 4)
        shrunk_synergy = synergy * confidence
 
        if shrunk_synergy >= 0.15:
            findings.append({
                "pair": label, "type": "synergy",
                "both_engaged_rate": round(both_high_rate, 3),
                "expected_if_additive": round(max(0, min(1, expected_both_high_rate)), 3),
                "sample_size": len(both_high),
            })
        elif shrunk_synergy <= -0.15:
            findings.append({
                "pair": label, "type": "redundant",
                "both_engaged_rate": round(both_high_rate, 3),
                "expected_if_additive": round(max(0, min(1, expected_both_high_rate)), 3),
                "sample_size": len(both_high),
            })
 
    return findings
 
