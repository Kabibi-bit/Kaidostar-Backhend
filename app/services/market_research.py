from app.services.timeutil import utcnow
"""Real, live web research grounded in the candidate's actual
situation - not a generic score, not invented knowledge. Two things
no mainstream job board does:
 
1. research_company() - gives Claude real web search to find and cite
   current, public information about a SPECIFIC company before the
   person applies. Same honest pattern as the athletics program
   research: report only what's actually found, say plainly when
   nothing specific turns up.
 
2. generate_interview_prep() - once someone has a real interview, this
   stitches together the company research, the actual role, and the
   person's own roadmap into a genuine prep brief - not generic
   "tell me about yourself" advice.
"""
 
 
def research_company(anthropic_client, company_name: str, role_title: str) -> dict:
    prompt = (
        f"Search for real, current, publicly available information about \"{company_name}\" that would "
        f"help someone preparing to apply for or interview for a \"{role_title}\" role there - what the "
        "company says about itself, recent news, their stated values or mission, size and stage, and "
        "anything publicly discussed about their interview process or culture.\n\n"
        "Report ONLY what you actually find through search - do not fill in gaps with generic assumptions "
        "about companies of this type in general, and do not invent specific claims this company doesn't "
        "support. If you can't find anything specific and current, say that plainly rather than guessing.\n\n"
        "Paraphrase what you find in your own words rather than quoting sources at length. Structure your "
        "answer as: what you found, and then 2-3 concrete implications for how this candidate should "
        "position themselves for this specific company and role."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    findings = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
    sources = []
    for block in resp.content:
        if getattr(block, "type", None) == "web_search_tool_result":
            for item in getattr(block, "content", []) or []:
                url = getattr(item, "url", None)
                title = getattr(item, "title", None)
                if url:
                    sources.append({"url": url, "title": title or url})
 
    return {"company_name": company_name, "findings": findings, "sources": sources}
 
 
def generate_interview_prep(anthropic_client, company_name: str, role_title: str, company_research: str | None, profile: dict, roadmap_summary: str | None) -> dict:
    research_line = (
        f"Real research on this company: \"{company_research}\"\n\n"
        if company_research else
        "No company research has been done yet for this one - work from the role and candidate's "
        "background only, and don't invent specifics about the company.\n\n"
    )
    prompt = (
        f"A candidate has a real interview for \"{role_title}\" at \"{company_name}\".\n\n"
        f"{research_line}"
        f"Their stated goal: \"{profile.get('northstar','')}\". Skills: \"{profile.get('skills','')}\". "
        f"Their roadmap strategy: \"{roadmap_summary or 'no roadmap yet'}\".\n\n"
        "Generate a real, specific interview prep brief - grounded in what's actually known about this "
        "role and candidate, not generic interview advice.\n\n"
        "Return a JSON object with exactly these four keys:\n"
        "- likely_questions: an array of 3-4 objects, each with exactly two keys - \"question\" (the specific "
        "question this candidate should genuinely expect for this role) and \"note\" (a 1-sentence note on "
        "what a strong answer would actually demonstrate)\n"
        "- talking_points: an array of 3-4 specific things from THIS candidate's real background "
        "(reference their actual stated skills/goal) that are worth emphasizing for this specific role\n"
        "- questions_to_ask: an array of 2-3 real, specific questions this candidate should ask the "
        "interviewer - not generic ('what's the culture like'), grounded in the actual role or company "
        "research if available\n"
        "- roadmap_connection: 1-2 sentences on how this specific interview connects to the candidate's "
        "actual roadmap - what it would mean for their plan if it goes well\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("interview prep response was not valid JSON")
    if not isinstance(parsed, dict):
        raise ValueError(f"interview prep response was not a JSON object: {type(parsed).__name__}")
    # A genuinely valid-JSON-but-incomplete response (missing a key, or
    # the wrong type for one) must not be returned as if it were
    # complete - the exact same gap already fixed on the frontend's
    # generateInterviewPrep. json.loads succeeding here doesn't
    # guarantee the shape the caller and the frontend both depend on.
    required_list_keys = ("likely_questions", "talking_points", "questions_to_ask")
    if not all(isinstance(parsed.get(k), list) for k in required_list_keys) or not isinstance(parsed.get("roadmap_connection"), str):
        raise ValueError(f"Interview prep response had an unexpected shape: {parsed}")
    return parsed
 
 
def research_company_leadership(anthropic_client, company_name: str) -> dict:
    """Searches for a company's real senior leadership - not just the
    CEO, but the CTO, COO, CPO, and other C-suite or VP-level
    executives - and what they've actually, recently said publicly:
    speeches, interviews, conference talks, posts under their own
    name. Then synthesizes a real, honest sense of what this
    company's leadership actually seems to be prioritizing right now,
    grounded in what multiple real people have actually said, not
    just one CEO's framing (which is often more polished, generic
    company messaging than what other leaders reveal in less
    rehearsed settings).
 
    Never invents a leader, a statement, or a priority; if nothing
    real and current turns up for a given person, or for the company
    at all, this says so plainly rather than filling the gap with a
    plausible-sounding guess. priorities_summary is built ONLY from
    what was actually found - if nothing real turned up, it's empty,
    not a generic assumption about companies like this one.
 
    Paraphrases what's found rather than quoting speeches at length -
    both a copyright concern with someone else's original words, and
    a paraphrased idea reads more naturally in an outreach message
    than a lifted quote would anyway. Mirrors research_company's
    real-search pattern above, including real source-URL extraction
    so a candidate can verify this themselves before sending anything
    grounded in it.
 
    Returns {leaders: [{name, title, statements: [{theme,
    source_title}]}], priorities_summary: str, sources: [{url,
    title}]} - leaders and priorities_summary are empty (never
    fabricated) if nothing real was found.
    """
    prompt = (
        f'Search for real, current senior leadership at "{company_name}" - the CEO, and other genuine '
        "C-suite or VP-level executives (CTO, COO, CPO, Head of Engineering, etc., whoever is real and "
        "current for this specific company) - and anything they've genuinely, publicly said recently: a "
        "speech, conference talk, interview, podcast appearance, or a post under their own name on the "
        "company's blog or elsewhere. Look for real statements about what they're building toward, what "
        "they care about, or specific priorities they've mentioned - not generic corporate mission-"
        "statement language.\n\n"
        "Be careful about company name collisions - a search for a smaller or less-documented company can "
        "genuinely surface other, unrelated companies with a similar or overlapping name. Before reporting "
        "a leader, confirm the company you found them at is genuinely the same one named above, not just a "
        "similarly-named one - if you're not genuinely confident it's the same company, treat it as not "
        "found rather than reporting it anyway.\n\n"
        "Be equally careful about whether a role is still current - real sources can genuinely disagree, "
        "for instance a specific announcement of someone starting a role with real quotes, against a more "
        "general company-overview source whose leadership list doesn't mention them at all, which could "
        "mean the overview is just incomplete, or could mean the person has since moved on. If you find "
        "a genuine conflict like this and can't resolve which is more current, don't guess - either treat "
        "that specific person as not confirmed, or say plainly that their current status is unclear rather "
        "than reporting stale information as if it were definitely still true.\n\n"
        "Only report real people and real statements you actually find through search. If you can only "
        "confirm the CEO and no other leaders, that's fine - report just the CEO. If you can't find "
        "anything genuinely specific and recent from anyone, say that plainly rather than guessing or "
        "filling in something generic that sounds plausible.\n\n"
        "For anything you do find, paraphrase the real idea in your own words rather than quoting it at "
        "length - describe the theme or point they made, not their exact original wording. This applies "
        "even to a short, catchy phrase a leader coined for their own idea (a named framework, a company "
        "mantra, a memorable turn of phrase) - describe what the phrase means rather than reproducing it "
        "in quotation marks, even briefly. A phrase being short and memorable is exactly why it's tempting "
        "to quote, not a reason it's exempt.\n\n"
        "After gathering what real leaders have actually said, write a short, honest summary of what this "
        "company's leadership actually seems to be prioritizing right now - genuinely synthesized from "
        "multiple real people's real statements if more than one was found, not just the most polished "
        "one. If you found real statements from only one person, or nothing specific at all, be honest "
        "about that limitation in the summary rather than presenting a single view as the whole company's "
        "position, or inventing a summary from nothing.\n\n"
        "Return a JSON object with exactly these keys:\n"
        "- leaders: an array of objects, each with 'name' (real, confirmed), 'title' (their real, current "
        "title), and 'statements' (an array of up to 2 objects, each with 'theme' - 1-2 sentences "
        "paraphrasing a real point they made, in your own words - and 'source_title' - what the source "
        "actually was, e.g. \"a 2025 conference keynote\" or \"an interview with [real publication]\") - "
        "empty array if no real leaders with real statements were found\n"
        "- priorities_summary: 2-3 honest sentences on what this leadership team's real, recent public "
        "statements actually suggest they're prioritizing - empty string if nothing real enough to "
        "synthesize was found\n\n"
        "Return ONLY the JSON object, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
 
    sources = []
    for block in resp.content:
        if getattr(block, "type", None) == "web_search_tool_result":
            for item in getattr(block, "content", []) or []:
                url = getattr(item, "url", None)
                title = getattr(item, "title", None)
                if url:
                    sources.append({"url": url, "title": title or url})
 
    import json
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"leaders": [], "priorities_summary": "", "sources": sources}
    # json.loads succeeding does NOT guarantee a dict - an LLM can return valid
    # JSON that's a list ("[{...}]") or a bare string/number, and parsed.get(...)
    # below would then raise AttributeError. Degrade gracefully to the SAME safe
    # result as the JSONDecodeError branch (keeping the real sources already
    # collected), rather than erroring out - mirrors interview_prep's isinstance
    # guard and preserves this function's own graceful-degradation intent.
    if not isinstance(parsed, dict):
        return {"leaders": [], "priorities_summary": "", "sources": sources}
 
    return {
        "leaders": parsed.get("leaders") or [],
        "priorities_summary": parsed.get("priorities_summary") or "",
        "sources": sources,
    }
 
 
def get_or_research_company_leadership(db, anthropic_client, company_name: str, max_age_days: int = 30) -> dict:
    """Checks the real cache (CompanyLeadershipResearch) before ever
    making a real, billed web-search call - without this, viewing a
    company's leadership research and then drafting an outreach email
    for it would trigger the same expensive search twice, and every
    other candidate applying to the same company would each trigger
    their own redundant search too.
 
    A cached result older than max_age_days is treated as stale and
    re-researched - a CEO's public priorities from 8 months ago may
    no longer reflect what leadership is actually focused on now.
    """
    from app.models.db_models import CompanyLeadershipResearch
    from datetime import datetime, timedelta
    from sqlalchemy.exc import IntegrityError
 
    normalized = company_name.strip().lower()
    cached = (
        db.query(CompanyLeadershipResearch)
        .filter(CompanyLeadershipResearch.company_name_normalized == normalized)
        .first()
    )
    if cached and cached.researched_at and (utcnow() - cached.researched_at) < timedelta(days=max_age_days):
        return {
            "leaders": cached.leaders, "priorities_summary": cached.priorities_summary,
            "sources": cached.sources, "cached": True,
        }
 
    fresh = research_company_leadership(anthropic_client, company_name)
 
    if cached:
        cached.leaders = fresh["leaders"]
        cached.priorities_summary = fresh["priorities_summary"]
        cached.sources = fresh["sources"]
        cached.researched_at = utcnow()
        db.commit()
    else:
        db.add(CompanyLeadershipResearch(
            company_name_normalized=normalized, company_name_display=company_name,
            leaders=fresh["leaders"], priorities_summary=fresh["priorities_summary"], sources=fresh["sources"],
        ))
        try:
            db.commit()
        except IntegrityError:
            # Lost a race with a concurrent first-research of the SAME company:
            # company_name_normalized is the PRIMARY KEY, so the second insert
            # violates it. This is the same check-then-insert race the rest of the
            # codebase closes (applications / saved / dismissed / outreach) - this
            # cache was the one spot still doing a bare insert. Roll back and return
            # the row the winner just wrote, so a race returns the real cached result
            # rather than surfacing a 502 for research that actually succeeded (and
            # that the very next retry would have found cached anyway).
            db.rollback()
            winner = (
                db.query(CompanyLeadershipResearch)
                .filter(CompanyLeadershipResearch.company_name_normalized == normalized)
                .first()
            )
            if winner:
                return {
                    "leaders": winner.leaders,
                    "priorities_summary": winner.priorities_summary,
                    "sources": winner.sources,
                    "cached": True,
                }
            raise
 
    return {**fresh, "cached": False}
 
