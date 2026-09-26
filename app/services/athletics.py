"""Recruiting content guidance for student-athletes: how to structure
a highlight reel, and which drills/metrics are commonly evaluated for
their specific sport, level, and career direction.
 
generate_recruiting_content_plan() gives grounded GENERAL guidance -
it deliberately never claims to know what a specific named coach or
program wants, since without a real information source that would be
fabrication.
 
research_target_program() is different: it gives Claude the real,
first-party Anthropic web search tool, so it can actually search for
and cite real, current, public information about a SPECIFIC named
program - their recruiting page, coaching staff statements, recent
recruiting classes, roster needs. This is genuinely real search, not
invented knowledge - and it's explicitly instructed to say plainly
when search turns up nothing specific, rather than filling the gap
with a guess.
"""
 
 
def generate_recruiting_content_plan(anthropic_client, sport: str, level: str, career_direction: str, achievements: str) -> dict:
    direction_label = {
        "play-college": "playing at the college level",
        "go-pro": "going pro",
        "coach": "coaching",
        "sports-management": "a sports management career",
    }.get(career_direction, career_direction)
 
    prompt = (
        f"A student-athlete: sport \"{sport}\", current level {level}, career direction: {direction_label}. "
        f"Their stated achievements: \"{achievements}\".\n\n"
        "Give them real, specific guidance on how to structure recruiting content and what to practice - "
        "grounded in genuinely common recruiting patterns for their sport and level, not generic motivational "
        "advice. Do NOT claim to know what any specific named coach, program, or scout individually wants - "
        "frame everything as what is COMMONLY evaluated by recruiters/scouts at this level, since that's "
        "real, honest knowledge, not a claim about a specific person's preferences.\n\n"
        "Return a JSON object with exactly these four keys:\n"
        "- reel_structure: an array of 4-6 short strings, each describing one segment of a highlight reel in "
        "order (e.g. 'Open with your fastest recorded time or most explosive play - recruiters often stop "
        "watching in the first 10 seconds if it doesn't grab attention'). Be specific to this sport and "
        "position/role, not generic ('show your best plays').\n"
        "- commonly_evaluated: an array of 4-6 objects, each with 'skill_or_metric' (a specific thing "
        "commonly evaluated for this sport/level, e.g. '40-yard dash time', 'first-step quickness on "
        "defense') and 'why' (1 sentence on why recruiters at this level commonly weight it)\n"
        "- drills_to_practice: an array of 3-5 specific, real drills or practice routines relevant to "
        "closing the gap between their current level and their target level - name real, standard drills "
        "for this sport, not vague advice\n"
        "- content_checklist: an array of 3-4 concrete, practical dos for filming/presenting content (e.g. "
        "camera angle, what footage to prioritize keeping, length) - specific to this sport\n"
        "- coaching_insights: an array of 3-5 objects, each with 'principle' and 'how_to_show_it'. These "
        "capture what college coaches AT THIS LEVEL AND IN THIS SPORT commonly prioritize tactically and in "
        "player mentality (e.g. for soccer: 'defensive work rate off the ball', 'decision speed in tight "
        "spaces'; for basketball: 'help-defense rotations', 'playing without the ball'). Each 'principle' "
        "is a REAL, widely-recognized coaching priority for this sport/level - NOT a claim about any "
        "specific named coach or program. Each 'how_to_show_it' is one concrete way the athlete can "
        "demonstrate that quality in their film or play. CRITICAL: do NOT name specific coaches or attribute "
        "beliefs/tactics/quotes to any real individual - these are general, established tactical priorities "
        "for the sport, because that is honest knowledge; inventing what a named coach believes is not.\n"
        "- researching_specific_coaches: a single string (2-3 sentences) telling the athlete how to find a "
        "SPECIFIC target coach's actual philosophy for themselves - e.g. watch that team's game film for "
        "playing style, read the coach's real published interviews and press conferences, note their system "
        "(pace, formation, rotation) - and reminding them that Kaidostar's 'Research a program' tool pulls real, "
        "cited public statements rather than guesses. This is where specific-coach insight should come from: "
        "real research, never an AI's assumption.\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    plan = json.loads(text)
    if not isinstance(plan, dict):
        raise ValueError(f"content plan response was not a JSON object: {type(plan).__name__}")
    # Real shape validation - a syntactically valid but incomplete
    # response would otherwise pass through silently, mirrors the
    # exact fix just applied to the frontend's equivalent function.
    required_keys = ("reel_structure", "commonly_evaluated", "drills_to_practice", "content_checklist")
    if not all(isinstance(plan.get(k), list) for k in required_keys):
        raise ValueError(f"content plan response is missing one or more required list fields: {required_keys}")
    # coaching_insights is a list; researching_specific_coaches is a string. Both
    # are new grounded-tactics fields. Validate leniently - if the model omitted
    # them, default rather than failing the whole plan (they're additive).
    if not isinstance(plan.get("coaching_insights"), list):
        plan["coaching_insights"] = []
    if not isinstance(plan.get("researching_specific_coaches"), str):
        plan["researching_specific_coaches"] = (
            "To learn a specific coach's real philosophy, watch that team's recent game film for their "
            "playing style and system, read the coach's published interviews and press conferences, and "
            "use Kaidostar's 'Research a program' tool, which pulls real, cited public statements rather than guesses."
        )
    return plan
 
 
def research_target_program(anthropic_client, sport: str, level: str, program_name: str) -> dict:
    """Uses Claude's real web search tool to find and cite current,
    public information about a specific named program - what they
    say they're looking for, recent recruiting classes, coaching
    staff, roster needs. Returns what was actually found, and says so
    plainly if search doesn't surface anything specific - this does
    not fill gaps with invented detail.
    """
    prompt = (
        f"Search for real, current, publicly available information about the {sport} program at "
        f"\"{program_name}\" that would help a {level}-level recruit understand what this specific "
        "program looks for - their official recruiting/roster page, public statements from coaching "
        "staff about what they value, their recent recruiting classes, team needs by position, or "
        "similar. \n\n"
        "Report ONLY what you actually find through search - do not fill in gaps with generic assumptions "
        "about the sport in general, and do not invent specific claims about this program that search "
        "doesn't support. If you can't find anything specific and current about this program, say that "
        "plainly rather than guessing.\n\n"
        "Paraphrase what you find in your own words rather than quoting sources at length. Structure your "
        "answer as: what you found (with a brief note on where it came from), and then, only if genuinely "
        "supported by what you found, 2-3 concrete implications for how this recruit should tailor their "
        "content or approach to this specific program."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    findings = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
    # Surface which real sources were actually consulted, so the
    # person can verify this themselves rather than taking Claude's
    # synthesis on faith alone.
    sources = []
    for block in resp.content:
        if getattr(block, "type", None) == "web_search_tool_result":
            for item in getattr(block, "content", []) or []:
                url = getattr(item, "url", None)
                title = getattr(item, "title", None)
                if url:
                    sources.append({"url": url, "title": title or url})
 
    return {"program_name": program_name, "findings": findings, "sources": sources}
 
 
def draft_coach_outreach(anthropic_client, sport: str, level: str, career_direction: str, achievements: str, target_description: str) -> dict:
    """Drafts both an email and a cold-call script for reaching a
    coach or staff member. Same honest boundary as the candidate-side
    connection strategy: never invents a specific named person, only
    describes the TYPE of contact and gives real, usable scripts.
    """
    direction_label = {
        "play-college": "playing at the college level",
        "go-pro": "going pro",
        "coach": "coaching",
        "sports-management": "a sports management career",
    }.get(career_direction, career_direction)
 
    prompt = (
        f"A student-athlete: sport \"{sport}\", level {level}, career direction: {direction_label}. "
        f"Achievements: \"{achievements}\". They want to reach out about: \"{target_description}\".\n\n"
        "Help them make direct contact. Never invent a specific real named person - describe the TYPE of "
        "contact to look for, not a fabricated name.\n\n"
        "Return a JSON object with exactly these five keys:\n"
        "- who_to_contact: the specific type of person worth reaching out to (e.g. 'the assistant coach "
        "responsible for recruiting at their position/event', or 'the program's recruiting coordinator')\n"
        "- how_to_find: 1-2 concrete sentences on how to actually find that person - a real search approach, "
        "not 'network more'\n"
        "- email_subject: a short, specific email subject line\n"
        "- email_body: a genuine, specific 100-140 word email referencing their actual sport, achievements, "
        "and goal - no generic filler, no placeholder brackets\n"
        "- cold_call_script: a real, specific phone call opening and structure (2-3 sentences of what to "
        "actually say when the person picks up, plus 1-2 follow-up talking points) - written for someone "
        "who has never cold-called before, concrete and usable, not generic 'be confident' advice\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError(f"coach outreach response was not a JSON object: {type(result).__name__}")
    required_keys = ("who_to_contact", "how_to_find", "email_subject", "email_body", "cold_call_script")
    if not all(isinstance(result.get(k), str) for k in required_keys):
        raise ValueError(f"coach outreach response is missing one or more required string fields: {required_keys}")
    return result
 
 
def generate_clip_edit_plan(anthropic_client, sport: str, level: str, career_direction: str, clips_description: str, target_schools: str = "") -> dict:
    """Honest scope note: this does not edit or process any real video
    file - there is no video hosting or editing infrastructure
    connected anywhere in this stack. What this gives is a real,
    specific EDIT PLAN grounded in the athlete's own description of
    their actual raw footage - which clips to use, in what order,
    how to trim them, and what to caption - for them to execute in
    whatever video editor they already use.
 
    When target_schools is provided, the plan is TAILORED to those
    programs' level and typical priorities - a real text-reasoning
    enhancement (division, style, what programs at that level look
    for). It never invents specific claims about a named coach; it
    reasons from the program's level/type, which is honest.
    """
    direction_label = {
        "play-college": "playing at the college level",
        "go-pro": "going pro",
        "coach": "coaching",
        "sports-management": "a sports management career",
    }.get(career_direction, career_direction)
 
    schools_line = ""
    tailoring_instruction = ""
    if target_schools and target_schools.strip():
        schools_line = f"They are targeting these programs/schools: \"{target_schools.strip()}\".\n\n"
        tailoring_instruction = (
            "TAILOR the edit plan to the programs they're targeting: consider the typical division/level "
            "and playing style of those programs and what coaches at that level commonly prioritize, and "
            "order/emphasize clips accordingly (e.g. a program known for a high-pressing style rewards "
            "leading with defensive work-rate and recovery clips; a possession-based program rewards "
            "composure and decision-making in tight spaces). Reason from the program's LEVEL and TYPE - "
            "do NOT invent specific claims about what a named coach personally wants. Add a 'why for these "
            "schools' note to relevant sequence steps where the tailoring changes the choice.\n\n"
        )
 
    prompt = (
        f"A student-athlete: sport \"{sport}\", level {level}, career direction: {direction_label}.\n\n"
        f"{schools_line}"
        f"They described their available raw footage/clips as:\n\"{clips_description}\"\n\n"
        "Give them a real, specific edit plan for turning this into a strong highlight reel - based ONLY "
        "on the clips they actually described, not invented footage. If what they described is too thin "
        "to make a strong reel, say so honestly rather than pretending it's enough.\n\n"
        f"{tailoring_instruction}"
        "Return a JSON object with exactly these three keys:\n"
        "- edit_sequence: an array of objects, each with 'clip' (which described clip/moment this refers "
        "to, by their own description) and 'instruction' (specific guidance: where to trim it, how long "
        "to hold it, what to lead into next, and why it goes in this position)"
        + (", and optionally 'why_for_schools' (1 sentence on how this choice fits the targeted programs, only where relevant)" if target_schools and target_schools.strip() else "")
        + "\n"
        "- captions: an array of 2-4 short on-screen text suggestions tied to specific clips (e.g. a stat, "
        "a title card idea) - concrete, not generic\n"
        "- honest_assessment: 1-2 sentences on whether what they described is actually enough for a strong "
        "reel, and if not, what specific kind of footage they're missing\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    plan = json.loads(text)
    if not isinstance(plan, dict):
        raise ValueError(f"clip edit plan response was not a JSON object: {type(plan).__name__}")
    if not isinstance(plan.get("edit_sequence"), list) or not isinstance(plan.get("captions"), list) or not isinstance(plan.get("honest_assessment"), str):
        raise ValueError("clip edit plan response has an unexpected shape")
    return plan
 
 
def generate_athlete_roadmap(anthropic_client, sport: str, level: str, career_direction: str, achievements: str) -> dict:
    """The real backend roadmap generator for athletes - this never
    existed server-side before; the athlete roadmap has been
    frontend/localStorage-only up to this point. Built to the FULL
    rich standard (including if_it_works/if_it_stalls branching),
    which is actually more complete than the candidate roadmap's
    current backend, which doesn't have branching yet - only the
    candidate frontend does.
    """
    direction_label = {
        "play-college": "playing at the college level",
        "go-pro": "going pro",
        "coach": "coaching",
        "sports-management": "a sports management career",
    }.get(career_direction, career_direction)
 
    prompt = (
        f"A student-athlete: sport \"{sport}\", current level {level}, career direction: {direction_label}. "
        f"Their stated achievements: \"{achievements}\".\n\n"
        "Generate a REAL, actionable roadmap from where they are now to that goal.\n\n"
        "BANNED as too vague, do not use language like this anywhere: 'build skills', 'gain experience', "
        "'network more', 'stay consistent', 'work hard', or any milestone that doesn't name a specific "
        "artifact, action, or outcome. If a milestone could apply to any athlete in any sport, rewrite it "
        "until it could only apply to THIS athlete's specific sport, level, and direction.\n\n"
        "Return a JSON object with exactly two top-level keys:\n\n"
        "1. \"summary\": 2-3 sentences explaining the overall strategy - why these stages happen in this "
        "specific order, and what the single biggest risk to the whole plan is.\n\n"
        "2. \"milestones\": an array of 4-6 objects, each with exactly these nine keys:\n"
        "- title: a concrete action naming a real artifact or outcome specific to this sport and direction\n"
        "- description: 1-2 sentences on exactly what to do and why it matters for THIS athlete specifically\n"
        "- success_criteria: a specific, checkable outcome someone else could verify - not a feeling of readiness\n"
        "- estimated_timeframe: a realistic duration for this one step (e.g. '2-3 weeks', '1-2 months')\n"
        "- first_action: the literal, physical first thing to do TODAY to start this milestone\n"
        "- resource: ONE concrete, real category of resource to use (e.g. 'your school's athletic "
        "department', 'a public results/stats page for your league'). Never invent a specific named "
        "person, program, or URL that may not be real.\n"
        "- risk: the single most common way athletes fail or stall on THIS specific milestone, grounded "
        "and specific, not generic\n"
        "- if_it_works: 1 sentence on the real next move once this milestone succeeds\n"
        "- if_it_stalls: 1 sentence of honest, concrete guidance for what to do if this milestone doesn't "
        "pan out as hoped\n"
        "- stage: the order number, starting at 1\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    roadmap = json.loads(text)
    if not isinstance(roadmap, dict):
        raise ValueError(f"athlete roadmap response was not a JSON object: {type(roadmap).__name__}")
    # Real, thorough shape validation - the calling route does
    # unprotected dict-key access (m["stage"], m["title"]) on this
    # result immediately after deleting the person's existing
    # roadmap data, so an incomplete response here would surface as
    # a raw, unhandled error mid-way through that destructive
    # operation. Checks both the top-level shape and every required
    # key within each individual milestone.
    if not isinstance(roadmap.get("summary"), str) or not isinstance(roadmap.get("milestones"), list) or not roadmap["milestones"]:
        raise ValueError("athlete roadmap response has an unexpected top-level shape")
    required_milestone_keys = ("title", "description", "success_criteria", "estimated_timeframe",
                                "first_action", "resource", "risk", "if_it_works", "if_it_stalls", "stage")
    for m in roadmap["milestones"]:
        # Requires each milestone to genuinely be a dict (not e.g. a
        # raw string that happens to contain every key name as a
        # substring, which the old "k in m" check alone wouldn't
        # catch), and each required text field to genuinely be a
        # real, non-empty string - found via brutal testing that the
        # old check only verified key existence, so a response with
        # every key present but every value None would silently pass
        # and produce a completely meaningless roadmap.
        if not isinstance(m, dict) or not all(k in m for k in required_milestone_keys):
            raise ValueError(f"an athlete roadmap milestone is missing one or more required keys: {required_milestone_keys}")
        text_keys = [k for k in required_milestone_keys if k != "stage"]
        if not all(isinstance(m[k], str) and m[k].strip() for k in text_keys):
            raise ValueError("an athlete roadmap milestone has a required field that's empty or not real text")
    return roadmap
 
