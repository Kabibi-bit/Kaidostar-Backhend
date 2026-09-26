"""Turns a person's own real, plain-language account of their
experience into strong resume language - never generates a work
history from scratch.
 
This exists because a resume is fundamentally a claim about
verifiable past experience: real employers, real dates, real things
someone actually did. Nothing else in this app collects that kind of
structured history (Profile.skills is just a loose text string), and
building a "generate my resume" feature on top of a career goal and a
skills string would leave an AI with no real facts to work from -
meaning it would have to invent company names, dates, and
achievements to produce anything resume-shaped at all. That's not a
UX shortfall, it's misrepresenting a real person to a real employer,
and it stays out regardless of how much better it might make the
feature look.
 
The honest version: the person enters their own real work/education/
project history first (ResumeEntry rows - see db_models.py), in their
own words, however rough. This module's only job is to strengthen the
PHRASING of what they actually wrote - stronger verbs, tighter
structure, resume conventions - never to add a fact, metric, or
responsibility they didn't state themselves.
"""
import re
from app.services.matching import tokenize, _terms_match
 
# Common connective/filler words that clear the 4+ character bar but
# aren't genuine skill or domain keywords - without this, a stated
# goal like "become a frontend engineer using JS" surfaces "become",
# "engineer", and "using" as if they were missing skills, which isn't
# actionable advice for anyone reviewing the ATS check.
_STOPWORDS = {
    "become", "engineer", "engineering", "using", "with", "work", "working",
    "want", "goal", "into", "role", "roles", "career", "field", "someone",
    "person", "years", "year", "experience", "focused", "break", "ship",
    "features", "backed", "real", "help", "helping", "make", "making",
    "build", "building", "learn", "learning", "have", "that", "this",
    "from", "about", "their", "them", "they", "very", "more", "most",
    "used", "use", "uses", "daily", "regularly", "handled", "handle",
    "worked", "helped", "managed", "assisted", "performed", "provided",
    "responsible", "duties", "tasks", "position", "store", "organized",
    "ensured", "maintained", "conducted", "completed", "supported",
    "findings", "hires", "machine", "orders", "reports", "records", "requests",
    # Common irregular past-tense verbs - a real description almost
    # always narrates what someone DID ("wrote", "led", "built",
    # "grew", "sold"), and none of these are skills themselves, but
    # they don't end in -ed/-ly so the suffix rule below can't catch
    # them the way it catches regular verbs like "created"/"managed".
    "wrote", "led", "built", "grew", "sold", "ran", "gave",
    "took", "made", "found", "held", "kept", "left", "spent", "spoke",
    # Short (3-char) English function words - needed because the length
    # filter below admits 3-char tokens (to keep real 3-char skills like
    # "sql", "aws", "api", "css"); without these, common function words
    # would leak into the keyword check. None is ever a skill name.
    "the", "and", "for", "you", "are", "was", "but", "all", "can",
    "has", "our", "had", "not", "its", "new", "any", "via", "per",
    "who", "how", "why", "out", "one", "two", "get", "got", "let",
    "may", "now", "off", "own", "see", "too", "use", "way",
    "drove", "chose", "began", "brought", "taught", "bought", "caught",
    "thought", "sought", "knew", "saw", "went", "came", "did", "said",
    # Quantifiers and generic filler nouns - real, but not skills;
    # neither ends in -ed/-ly so needed here separately.
    "several", "multiple", "various", "many", "much", "some", "each",
    "every", "team", "people", "company", "department", "quality",
    # Prepositions/conjunctions found via testing - "while" and
    # "across" both survived the -ed/-ly suffix rule (neither is a
    # verb or adverb) despite clearly not being skills.
    "while", "across", "through", "during", "within", "toward",
    "against", "between", "before", "after",
    # More irregular past-tense verbs found via systematically testing
    # candidate words against the real filter, the same way the first
    # batch above was found - none end in -ed/-ly so the suffix rule
    # misses them, and none are skills themselves.
    "read", "sent", "paid", "lost", "shot", "stood", "understood",
    # Generic adjectives and frequency adverbs - real words someone
    # might genuinely write ("did a great job", "worked hard"), but
    # not specific enough to be an actionable skill suggestion, the
    # same reasoning as excluding "very"/"more"/"most" above.
    "great", "good", "strong", "hard", "able", "often", "never", "always",
    # Quantifiers and generic filler nouns, extending the existing
    # "several/multiple/various/many/much/some" and "team/people/
    # company" categories with more found via the same testing.
    "lots", "plenty", "thing", "stuff", "part", "parts", "side", "area", "areas",
}
 
 
def _meaningful_tokens(text: str) -> set[str]:
    """Filters entry text down to plausible skill-suggestion
    candidates. Enumerating every English verb and adverb that isn't
    a skill is an endless list - "created", "improved", "quickly",
    "successfully" all showed up as suggested "skills" in real
    testing, none of them names of anything a person actually has.
    Regular past-tense verbs end in -ed and adverbs end in -ly far
    more reliably than any curated stopword list could keep up with,
    and neither suffix appears at the end of a real skill name in
    practice (verified against a broad list of common skills -
    Python, SQL, Photoshop, accounting, forecasting, etc. - before
    adding this, specifically because a structural rule risks
    excluding something legitimate in a way a curated list doesn't).
    Irregular verbs ("wrote", "led", "built") don't end in -ed, so
    those stay in the explicit stopword list above instead.
    """
    return {
        t for t in tokenize(text)
        if len(t) >= 3 and t not in _STOPWORDS
        and not t.endswith("ed") and not t.endswith("ly")
    }
 
 
def _find_fabricated_numbers(original: str, polished: str) -> list[str]:
    """A real, deterministic safety-net check, not a substitute for
    the prompt's anti-fabrication instructions but a second, testable
    layer on top of it - the same two-layer pattern already used for
    scholarship discovery elsewhere in this app. Flags any digit
    sequence appearing in the polished bullet that appears nowhere in
    the original raw_description - a common shape a fabricated metric
    takes (a specific percentage, dollar figure, or count the person
    never actually stated).
 
    Also catches a real, more dangerous class of fabrication that
    bare digit-matching alone missed: the same number reused with a
    completely different, fabricated meaning. Verified with concrete
    scenarios before adding this - "worked there for 2.5 years"
    becoming "reduced costs by $2.5 thousand", and "helped 20
    customers a day" becoming "increased satisfaction by 20%", both
    slipped through entirely undetected under bare-digit matching,
    since 2.5 and 20 genuinely appear in the original text, just with
    a completely different, fabricated meaning attached. For any
    number that carries a $ or % unit in the polished text, this
    additionally requires that same number to carry that same unit
    somewhere in the original - a number honestly reused with the
    same unit (e.g. "$50 thousand" staying "$50 thousand") is
    correctly left alone.
 
    The unit test recognizes both symbol and word forms ($ / "dollars"
    / "USD"; % / "percent" / "percentage" / "pct"), because a
    fabricated "20 percent" written as a word is exactly as dishonest
    as "20%" and was previously slipping through the symbol-only check.
    Word-and-symbol are treated as the same unit, so an honest "$5"
    becoming "5 dollars" is not flagged. Numbers are also matched with
    their thousands separators ("1,000") and compared with commas
    stripped, so an honest number merely reformatted ("1,000" -> "1000")
    is no longer flagged as fabricated.
    """
    NUM = r"\d[\d,]*(?:\.\d+)?"
    def _norm(s: str) -> str:
        return s.replace(",", "")
    original_numbers = {_norm(n) for n in re.findall(NUM, original)}
 
    def _unit_context(text: str, start_idx: int, end_idx: int) -> tuple[bool, bool]:
        before = text[max(0, start_idx - 1):start_idx]
        after = text[end_idx:end_idx + 12].lower()
        is_dollar = (before == "$") or bool(re.match(r"\s*(dollars?|usd)\b", after))
        is_percent = bool(re.match(r"\s*%", after)) or bool(re.match(r"\s*(percent|percentage|pct)\b", after))
        return is_dollar, is_percent
 
    flagged = set()
    for m in re.finditer(NUM, polished):
        raw = m.group()
        num = _norm(raw)
        if num not in original_numbers:
            flagged.add(raw)
            continue
        p_dollar, p_percent = _unit_context(polished, m.start(), m.end())
        if not p_dollar and not p_percent:
            continue  # no specific unit to verify; bare-number matching is enough
        matching_context_found = any(
            _norm(om.group()) == num and _unit_context(original, om.start(), om.end()) == (p_dollar, p_percent)
            for om in re.finditer(NUM, original)
        )
        if not matching_context_found:
            flagged.add(raw)
    return sorted(flagged)
 
 
def polish_resume_entry(anthropic_client, entry: dict) -> dict:
    """entry: {entry_type, title, org, start_date, end_date, raw_description}
    all real, user-provided fields. Returns {bullets: [str], flagged_numbers: [str]}.
 
    flagged_numbers is non-empty only when the safety-net check above
    catches a number in the output that wasn't in the input - this
    doesn't silently discard the bullets (a false positive here would
    make the feature less useful for no real safety gain, since the
    person still reviews everything before it becomes their resume),
    it surfaces the flag so the person can verify it themselves before
    trusting it.
    """
    prompt = (
        f"Here is something a real person wrote, in their own words, about something they actually did:\n\n"
        f'Role/title: "{entry.get("title") or "(untitled)"}"' + (f' at {entry["org"]}' if entry.get("org") else "") + "\n"
        f'What they said they did, in their own words: "{entry.get("raw_description") or ""}"\n\n'
        "Turn this into 2-4 strong resume bullet points - but if what they wrote genuinely only supports "
        "fewer distinct, honest bullets without repeating yourself or splitting one real responsibility "
        "into several separate-sounding ones, write fewer. Even a single bullet is fine if that's all the "
        "material honestly supports; hitting a minimum count is never a reason to invent a second, distinct "
        "responsibility that wasn't there.\n\n"
        "Critical rule, more important than anything else here: you may only strengthen the PHRASING of "
        "what they actually wrote - stronger action verbs, tighter and more concrete language, standard "
        "resume conventions. You may NEVER add a specific number, percentage, dollar amount, team size, "
        "tool, responsibility, or outcome that isn't already stated or clearly implied in what they wrote. "
        "This includes an unstated causal step connecting two things they mentioned separately - if they "
        "said they built a feedback mechanism AND separately that something is still in use, do not write "
        "that the feedback was used to improve it unless they actually said that connection happened; state "
        "the two real things they said, not a process linking them that you're inferring. "
        "If what they wrote is vague or doesn't include a metric, write a vague-but-honest bullet rather "
        "than inventing a specific one - a real person may submit this to a real employer, and a fabricated "
        "detail here is not a stylistic choice, it's misrepresenting them.\n\n"
        "No cliches like \"results-driven\", \"team player\", \"go-getter\", \"detail-oriented\", or "
        "\"leveraged\" as a verb - write like a specific, real person describing specific, real work, not a "
        "template filled in with generic resume language.\n\n"
        "Return a JSON array of the bullet point strings - 2-4 for most entries, fewer only if the "
        "material genuinely doesn't support more - nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        bullets = json.loads(text)
    except json.JSONDecodeError:
        bullets = []
    if not isinstance(bullets, list):
        bullets = []
    # Keep only real string bullets - a list of non-strings (e.g. [1,2,3]) would
    # otherwise crash the string ops in _find_fabricated_numbers below.
    bullets = [b for b in bullets if isinstance(b, str)]
 
    flagged = []
    for bullet in bullets:
        flagged.extend(_find_fabricated_numbers(entry.get("raw_description", ""), bullet))
 
    return {"bullets": bullets, "flagged_numbers": sorted(set(flagged))}
 
 
def generate_resume_summary(anthropic_client, profile: dict, entries: list[dict]) -> dict:
    """A short professional summary line (1-2 sentences), grounded in
    the person's real stated goal and their real entries - framing
    what's genuinely there, not inventing new facts. Returns
    {summary: "", flagged_numbers: []} if there isn't enough real
    material to say anything honest.
 
    Applies the same deterministic fabrication safety net used for
    bullets (see _find_fabricated_numbers) - this previously relied
    entirely on the prompt's "do not invent years of experience"
    instruction, with no testable check behind it, unlike
    polish_resume_entry right above it. A summary line is exactly the
    kind of place a fabricated "5+ years of experience" could appear
    if the model doesn't follow that instruction perfectly every
    time, and prompt instructions alone were never meant to be a
    substitute for the second, deterministic layer - that's the whole
    reason the two-layer pattern exists in the first place.
    """
    if not profile.get("northstar") and not entries:
        return {"summary": "", "flagged_numbers": []}
 
    entry_lines = [f'- {e["title"]}' + (f' at {e["org"]}' if e.get("org") else "") for e in entries[:5]]
    prompt = (
        f'Real stated career goal: "{profile.get("northstar", "")}"\n'
        + ("Real experience entries:\n" + "\n".join(entry_lines) + "\n" if entry_lines else "")
        + "\nWrite a single, honest 1-2 sentence professional summary line for a resume, grounded only in "
        "the real goal and entries above. Do not invent skills, years of experience, or achievements not "
        "implied by what's given. No cliches like \"results-driven\" or \"passionate professional\" - write "
        "like a specific, real person, not a template.\n\n"
        "Return ONLY the summary text, nothing else."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    summary = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
    source_text = f'{profile.get("northstar") or ""} ' + " ".join(e.get("raw_description") or "" for e in entries)
    flagged = _find_fabricated_numbers(source_text, summary)
    return {"summary": summary, "flagged_numbers": flagged}
 
 
def check_ats_alignment(profile: dict, entries: list[dict]) -> dict:
    """Real, deterministic keyword coverage check - does the resume's
    actual content contain genuine overlap with what the person says
    they're targeting? Reuses the exact same synonym-aware, word-
    boundary-safe matching already proven in the core matching engine
    (see matching.py's _terms_match), so a resume that says "js" and
    a stated goal of "javascript" correctly recognize each other -
    not just literal exact-string presence, and not the old unguarded
    substring bug either (this inherits that fix automatically by
    reusing the same function, rather than re-implementing matching
    logic a second time with its own risk of drifting out of sync).
    """
    goal_and_skills = f"{profile.get('northstar') or ''} {profile.get('skills') or ''}"
    target_tokens = sorted(_meaningful_tokens(goal_and_skills))
    if not target_tokens:
        return {"matched_keywords": [], "missing_keywords": [], "coverage_pct": 0}
 
    resume_text = " ".join(f"{e.get('title') or ''} {e.get('raw_description') or ''}" for e in entries)
    resume_tokens = set(tokenize(resume_text))
 
    matched, missing = [], []
    for t in target_tokens:
        (matched if any(_terms_match(t, rt) for rt in resume_tokens) else missing).append(t)
 
    coverage_pct = round(len(matched) / len(target_tokens) * 100)
    return {"matched_keywords": matched, "missing_keywords": missing, "coverage_pct": coverage_pct}
 
 
def rank_entries_for_listing(entries: list[dict], listing: dict) -> list[dict]:
    """Which of the person's REAL entries are most worth leading with
    for THIS specific listing - reuses the same synonym-aware term
    matching, applied to real entry content instead of a goal string.
    Never changes what an entry says, only how entries get ordered:
    the honest content stays identical regardless of which job it's
    being tailored for, only the emphasis (order) changes. Returns
    entries sorted by real overlap, each annotated with which of the
    listing's own tags it actually matched.
    """
    listing_tags = listing.get("tags") or []
    scored = []
    for e in entries:
        entry_tokens = set(tokenize(f"{e.get('title') or ''} {e.get('raw_description') or ''}"))
        matched_tags = [tag for tag in listing_tags if any(_terms_match(tag.lower(), t) for t in entry_tokens)]
        scored.append({**e, "relevance_tags": matched_tags, "relevance_score": len(matched_tags)})
    scored.sort(key=lambda e: e["relevance_score"], reverse=True)
    return scored
 
 
def build_skills_section(profile: dict, entries: list[dict]) -> dict:
    """The skills section a resume shows is a direct, bare claim -
    "I have this skill" - with even less surrounding context than a
    bullet point to qualify it. That makes it more fabrication-
    sensitive, not less, so this only ever lists skills the person
    explicitly typed as their own (profile.skills), cleaned and
    deduplicated. Anything genuinely implied by their real entries but
    not in that explicit list is surfaced separately as a suggestion
    - never auto-added to the claimed list, since inferring a skill
    from entry text is a meaningfully weaker claim than the person
    stating it themselves, and the two shouldn't look identical on
    the page.
    """
    raw_skills = profile.get("skills", "") or ""
    seen_lower = set()
    explicit_skills = []
    for s in raw_skills.split(","):
        s = s.strip()
        if s and s.lower() not in seen_lower:
            seen_lower.add(s.lower())
            explicit_skills.append(s)
    explicit_skills.sort(key=str.lower)
 
    entry_text = " ".join(e.get("raw_description") or "" for e in entries)
    entry_tokens = _meaningful_tokens(entry_text)
    explicit_lower = {s.lower() for s in explicit_skills}
    suggested = sorted(t for t in entry_tokens if not any(_terms_match(t, s) for s in explicit_lower))
 
    return {"skills": explicit_skills, "suggested_additions": suggested[:8]}
 
 
def add_skill_to_skills_string(current_skills: str, new_skill: str) -> str:
    """Appends a skill to the person's explicit, comma-separated
    skills string - built specifically to support turning a
    suggested_additions entry from build_skills_section into a real,
    one-click action rather than a static, read-only list. This is
    the ONLY sanctioned way a suggested skill moves into the explicit
    list: the person clicking to confirm it, never an automatic
    promotion. Case-insensitive duplicate check so "Python" doesn't
    get added twice just because it's capitalized differently from
    what's already there. Returns the string unchanged if the skill
    (by any casing) is already present.
    """
    current_skills = current_skills or ""
    new_skill = (new_skill or "").strip()
    if not new_skill:
        return current_skills
    existing = [s.strip() for s in current_skills.split(",") if s.strip()]
    if any(s.lower() == new_skill.lower() for s in existing):
        return current_skills
    existing.append(new_skill)
    return ", ".join(existing)
 
 
def remove_skill_from_skills_string(current_skills: str, skill_to_remove: str) -> str:
    """The other half of the skills panel's add action - removing a
    skill someone added by mistake, or one they no longer want
    claimed, should be exactly as easy as adding it was. Without
    this, the one-click "add this suggestion" action (see
    add_skill_to_skills_string) would be one-way: easy to add a skill
    with a single click, no way to undo it short of manually editing
    the whole comma-separated string elsewhere. Case-insensitive
    match, same as the add path, so removing "python" also removes
    an entry stored as "Python".
    """
    current_skills = current_skills or ""
    skill_to_remove = (skill_to_remove or "").strip()
    if not skill_to_remove:
        return current_skills
    existing = [s.strip() for s in current_skills.split(",") if s.strip()]
    remaining = [s for s in existing if s.lower() != skill_to_remove.lower()]
    return ", ".join(remaining)
 
