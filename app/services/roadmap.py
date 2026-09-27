"""Generates a real career roadmap from a user's profile using Claude,
and explains how a specific listing fits into that roadmap. Each
milestone includes success criteria, a timeframe, a first action, a
concrete resource to use, the most common way this specific step
goes wrong, and what to do whether it works out or stalls -- this is
what turns it into a real plan instead of a motivational list.
"""
import json
 
 
def generate_roadmap(anthropic_client, profile: dict, skill_gaps: list[str] | None = None) -> dict:
    """Produces an overall summary plus 4-6 ordered milestones from
    where the person is now to their stated goal. Returns a dict with
    'summary' (why this order, what the overall strategy is) and
    'milestones' (a list of dicts with title, description,
    success_criteria, estimated_timeframe, first_action, resource,
    risk, if_it_works, if_it_stalls, and stage).
    """
    gap_line = (
        f"Skills that show up often in listings that match their goal, but aren't in their stated skills yet: {', '.join(skill_gaps)}.\n"
        if skill_gaps else ""
    )
    prompt = (
        f"A person's long-term career goal: \"{profile['northstar']}\"\n"
        f"What 'made it' looks like to them, concretely: \"{profile.get('final_idea', '')}\"\n"
        f"Their timeframe: {profile.get('timeframe', 'unspecified')}\n"
        f"Current stage: {profile.get('stage', 'unspecified')}\n"
        f"Current skills: \"{profile.get('skills', '')}\"\n"
        f"What matters most to them: {', '.join(profile.get('priorities', []))}\n"
        f"{gap_line}\n"
        "Generate a REAL, actionable roadmap from where they are now to "
        "that goal.\n\n"
        "BANNED as too vague, do not use language like this anywhere: "
        "'build skills', 'gain experience', 'network more', 'improve your "
        "profile', 'stay consistent', 'work hard', or any milestone that "
        "doesn't name a specific artifact, action, or outcome. If a "
        "milestone could apply to literally any career goal, rewrite it "
        "until it could only apply to THIS person's specific goal.\n\n"
        "Return a JSON object with exactly two top-level keys:\n\n"
        "1. \"summary\": 2-3 sentences explaining the overall strategy - "
        "why these stages happen in this specific order, and what the "
        "single biggest risk to the whole plan is.\n\n"
        "2. \"milestones\": an array of 4-6 objects, each with exactly "
        "these nine keys:\n"
        "- title: a concrete action naming a real artifact or outcome "
        "(e.g. 'Ship a SQL-based analytics project using a real public "
        "dataset', not 'Build skills')\n"
        "- description: 1-2 sentences on exactly what to do and why it "
        "matters for THIS person's specific goal - reference their actual "
        "stated goal or skills by name\n"
        "- success_criteria: a specific, checkable outcome someone else "
        "could verify - not a feeling of readiness\n"
        "- estimated_timeframe: a realistic duration for this one step "
        "(e.g. '2-3 weeks', '1-2 months')\n"
        "- first_action: the literal, physical first thing to do TODAY "
        "to start this milestone - doable in the next hour\n"
        "- resource: ONE concrete, real category of resource to use for "
        "this step - name a real, generally-known platform, community, "
        "or resource type (e.g. 'a public dataset on Kaggle in your "
        "target domain', 'your school's alumni directory filtered by "
        "current employer', 'a free-tier project on GitHub'). Never "
        "invent a specific company name, person, or URL that may not "
        "be real.\n"
        "- risk: the single most common way people fail or stall on "
        "THIS specific milestone, and one sentence on how to avoid it - "
        "grounded, not generic ('running out of time' is not a risk, "
        "'picking a project too broad to finish in 3 weeks' is)\n"
        "- if_it_works: 1 sentence on the real next move once this "
        "milestone succeeds\n"
        "- if_it_stalls: 1 sentence of honest, concrete guidance for "
        "what to do if this milestone doesn't pan out as hoped\n"
        "- stage: the order number, starting at 1\n\n"
        "If skill gaps were listed above, at least one milestone must "
        "directly address closing one of them by name. Return ONLY valid "
        "JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"roadmap response was not a JSON object: {type(parsed).__name__}")
    # A genuinely valid-JSON-but-incomplete response must not be
    # returned as if it were complete - confirmed this had zero shape
    # validation, meaning a milestone genuinely missing "title" or
    # "stage" would raise an uncaught KeyError the moment the caller
    # accessed it, producing a raw 500 for this central feature.
    required_milestone_keys = (
        "title", "description", "success_criteria", "estimated_timeframe",
        "first_action", "resource", "risk", "if_it_works", "if_it_stalls", "stage",
    )
    if not isinstance(parsed.get("summary"), str) or not isinstance(parsed.get("milestones"), list) or not parsed["milestones"]:
        raise ValueError(f"Roadmap response had an unexpected shape: {parsed}")
    for m in parsed["milestones"]:
        if not isinstance(m, dict) or not all(k in m for k in required_milestone_keys):
            raise ValueError(f"A roadmap milestone had an unexpected shape: {m}")
        text_keys = [k for k in required_milestone_keys if k != "stage"]
        # Mirrors the identical strengthening already applied to
        # athletics.py's generate_athlete_roadmap - the check above
        # only verifies key existence, not whether a value is
        # genuinely real text. A milestone with every key present but
        # every value None or empty would otherwise pass silently and
        # produce a completely meaningless, blank-looking roadmap.
        if not all(isinstance(m[k], str) and m[k].strip() for k in text_keys):
            raise ValueError(f"A roadmap milestone has a required field that's empty or not real text: {m}")
    return parsed
 
 
def explain_listing_against_roadmap(anthropic_client, listing: dict, roadmap: list[dict], profile: dict) -> str:
    """Given a listing and the user's roadmap, explains in plain language
    which milestone(s) this listing advances, and why -- the actual
    'compares to your roadmap' feature.
    """
    roadmap_text = "\n".join(
        f"{m['stage']}. {m['title']}: {m['description']} (done when: {m.get('success_criteria', 'n/a')})"
        for m in roadmap
    )
    prompt = (
        f"User's roadmap toward their goal (\"{profile['northstar']}\"):\n{roadmap_text}\n\n"
        f"A listing they're considering: \"{listing['title']}\" at {listing['org']} "
        f"({listing['type']}), tags: {', '.join(listing.get('tags', []))}.\n\n"
        "In 1-2 sentences, explain which roadmap stage this listing advances "
        "and why, or state plainly if it doesn't fit the roadmap well. Be "
        "direct and concrete, no filler."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
