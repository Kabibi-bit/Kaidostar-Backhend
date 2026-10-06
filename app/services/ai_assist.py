"""Generic, profile-grounded AI writing assistant.
 
One service backs every AI-powered tool in the Workshop and Interview Prep
pages: each `task` names a prompt builder, the candidate's real profile is
folded in for grounding, and a strict anti-fabrication instruction keeps the
model from inventing employers, numbers, or achievements the person never
stated. Every task returns plain text, so the route and the frontend stay
uniform - one endpoint, one render path, many tools.
"""
 
MODEL = "claude-sonnet-4-6"
 
_ANTI_FAB = (
    "Ground everything ONLY in what the candidate actually provided. Never invent employers, "
    "dates, numbers, job titles, or achievements they did not state. Where a specific is missing, "
    "write around it or leave a clearly marked [placeholder] for them to fill. Be specific and honest, "
    "never generic filler."
)
 
 
def _clip(v, n=6000):
    return str(v)[:n] if v is not None else ""
 
 
def _profile_line(profile):
    return (
        f"The candidate's stated goal: \"{profile.get('northstar') or 'not specified'}\". "
        f"Their skills: \"{profile.get('skills') or 'not specified'}\"."
    )
 
 
# Each builder: (inputs_dict, profile_dict) -> prompt string. All outputs are plain text.
def _b(task, i, profile):
    p = _profile_line(profile)
    g = lambda k, d="": _clip(i.get(k, d))
    bg = g("background")  # optional client-assembled resume context
    bg_line = f"\nTheir real background:\n{bg}\n" if bg else ""
 
    if task == "bullet_rewrite":
        return (f"Rewrite this resume bullet into 3 stronger versions: a strong action verb first, quantified only where "
                f"the candidate already gave a number, no filler. {_ANTI_FAB}\n\n{p}\n\nOriginal bullet: \"{g('bullet')}\"\n\n"
                "Return exactly 3 rewrites as a numbered list (1., 2., 3.) and nothing else.")
    if task == "pitch":
        return (f"Write a {g('length','30-second')} spoken elevator pitch for this candidate, first person, natural and "
                f"specific to their real goal and skills. {_ANTI_FAB}\n\n{p}{bg_line}\n\nReturn only the pitch text.")
    if task == "summary_line":
        return (f"Write a 2-3 sentence professional summary for the top of this candidate's resume. {_ANTI_FAB}\n\n{p}{bg_line}\n\n"
                "Return only the summary.")
    if task == "thank_you":
        return (f"Write a warm, specific {g('kind','post-interview')} thank-you note. Recipient: \"{g('name','the interviewer')}\", "
                f"about: \"{g('role','the role')}\". A specific detail to reference: \"{g('detail','none given')}\". "
                f"{_ANTI_FAB} Keep it under 130 words, ready to send, signed [Your name].\n\n{p}\n\nReturn only the note.")
    if task == "star_polish":
        return (f"Tighten this rough STAR interview story into a crisp, spoken answer (about 5-7 sentences) that clearly "
                f"separates situation, task, action, and result, keeping the candidate's real facts. {_ANTI_FAB}\n\n"
                f"Title: {g('title')}\nSituation: {g('s')}\nTask: {g('t')}\nAction: {g('a')}\nResult: {g('r')}\n\n"
                "Return only the polished story.")
    if task == "achievement_polish":
        return (f"Turn this achievement into one strong resume-ready line, leading with impact, keeping the candidate's "
                f"real metric if given. {_ANTI_FAB}\n\nAchievement: \"{g('text')}\"\nMetric/result: \"{g('metric','none given')}\"\n\n"
                "Return only the line, plus a one-sentence note on any number worth verifying.")
    if task == "cover_letter":
        return (f"Write a genuine, specific cover letter for \"{g('role','the role')}\"" +
                (f" at \"{g('company')}\"" if g('company') else "") +
                f". {_ANTI_FAB} Reference the candidate's real background; keep it to 3 short paragraphs.\n\n{p}{bg_line}" +
                (f"\nJob description:\n{g('jd')}\n" if g('jd') else "") +
                "\nReturn only the letter, signed [Your name].")
    if task == "linkedin_headline":
        return (f"Write 3 strong LinkedIn headline options (each under ~120 characters) for this candidate. {_ANTI_FAB}\n\n"
                f"{p}{bg_line}\n\nReturn a numbered list of 3 headlines only.")
    if task == "linkedin_about":
        return (f"Write a first-person LinkedIn 'About' section (3 short paragraphs) for this candidate - specific, warm, "
                f"not buzzword soup. {_ANTI_FAB}\n\n{p}{bg_line}\n\nReturn only the About text.")
    if task == "skills_gap":
        return (f"The candidate is targeting: \"{g('target_role','their goal role')}\". Compare it honestly to their real "
                f"skills. {_ANTI_FAB}\n\n{p}{bg_line}\n\nReturn: (1) 'Already strong' - skills they have that this role needs; "
                "(2) 'Gaps to close' - specific skills to build, most important first; (3) one concrete first step for the top gap. "
                "Use short headed sections.")
    if task == "jd_tailor":
        return (f"Given this job description, tell the candidate exactly how to tailor their resume for it - which of their real "
                f"experiences to lead with, which keywords to genuinely reflect, and 2-3 tailored bullet rewrites. {_ANTI_FAB}\n\n"
                f"{p}{bg_line}\n\nJob description:\n{g('jd')}\n\nReturn short headed sections.")
    if task == "outreach":
        return (f"Write a specific, non-generic outreach message to \"{g('name','a contact')}\" ({g('role','their role')}"
                + (f" at {g('company')}" if g('company') else "") + f"). Context: \"{g('context','none given')}\". "
                f"{_ANTI_FAB} Reference the candidate's real background, keep it 80-120 words, ask for something concrete "
                f"(a short chat or a referral).\n\n{p}\n\nReturn only the message.")
    # ---- Interview Prep tasks ----
    if task == "answer_feedback":
        return (f"You are a supportive but honest interviewer. The candidate was asked: \"{g('question')}\". They answered: "
                f"\"{g('answer')}\". Give specific feedback on THIS answer - what worked, what to improve, and a stronger way "
                f"to frame it. Reference what they actually said. {_ANTI_FAB}\n\nReturn: a 2-3 sentence assessment, then "
                "'Do more of:' and 'Tighten:' as short bullet lists.")
    if task == "tmays":
        return (f"Help this candidate craft a strong 60-90 second 'Tell me about yourself' answer - present, then relevant "
                f"past, then why this direction. First person, specific. {_ANTI_FAB}\n\n{p}{bg_line}\n\nReturn only the answer.")
    if task == "role_questions":
        return (f"List the 6-8 interview questions this candidate should most expect for \"{g('role','this role')}\""
                + (f" at \"{g('company')}\"" if g('company') else "") +
                f", grounded in the real demands of that role - a mix of behavioral, role-specific, and motivation. For each, add "
                f"a one-line note on what a strong answer shows. {_ANTI_FAB}\n\n{p}\n\nReturn a numbered list.")
    if task == "behavioral_story":
        return (f"Turn this rough experience into a strong STAR behavioral story the candidate can tell in an interview, keeping "
                f"their real facts. {_ANTI_FAB}\n\nThe experience: \"{g('experience')}\"\n\nReturn the story, then one line naming "
                "which common behavioral questions it answers well.")
    if task == "weakness_frame":
        return (f"Help the candidate answer 'what's your greatest weakness' honestly and well, using the real weakness they give - "
                f"name it plainly, then show the concrete steps they're taking. {_ANTI_FAB}\n\nTheir weakness: \"{g('weakness')}\"\n\n"
                "Return a strong 4-6 sentence answer.")
    if task == "why_us":
        return (f"Help the candidate answer 'why do you want to work here' for \"{g('company','this company')}\" and the role "
                f"\"{g('role','this role')}\". {_ANTI_FAB} Since real specifics about the company may not be provided, show the "
                f"structure of a strong answer and mark [research: ...] placeholders for them to fill with real facts.\n\n{p}\n\n"
                "Return the answer with placeholders.")
    if task == "post_interview_debrief":
        return (f"The candidate just finished an interview for \"{g('role','the role')}\""
                + (f" at \"{g('company')}\"" if g('company') else "") +
                f". Their notes on how it went: \"{g('notes','none given')}\". Give a short, honest debrief: what likely went well, "
                f"what to shore up for next time, and a brief follow-up thank-you note they could send now. {_ANTI_FAB}\n\nReturn "
                "short headed sections.")
    # ---- Job Search dashboard "AI Copilot" tasks ----
    # These reason over the candidate's live, ranked match set (passed in as a
    # compact text list the client assembles) plus their real profile.
    if task == "search_briefing":
        return (f"You are a job-search copilot. The candidate's current ranked matches:\n{g('matches')}\n\n{p}\n\n"
                f"Give a short daily briefing (5-6 sentences): the 2-3 themes across these matches, what to prioritise today, "
                f"and one thing to watch (a deadline, a ghost-risk, or a gap). {_ANTI_FAB} Ground every point in the listed "
                "matches. Plain prose, no preamble, no list.")
    if task == "search_triage":
        return (f"The candidate can only put real effort into a few applications. Their current matches:\n{g('matches')}\n\n{p}\n\n"
                f"Pick the 3-5 to apply to FIRST, strongest first, each with one honest reason (fit, freshness, deadline, or upside). "
                f"{_ANTI_FAB} Return a numbered list, each line: \"Title at Org - reason\".")
    if task == "search_skill_gaps":
        return (f"Across the candidate's current matches, these skills recur but are NOT in their stated skills: "
                f"\"{g('gaps','(none detected)')}\". Their matches:\n{g('matches')}\n\n{p}\n\nExplain which gap to close first and why, "
                f"with one concrete first step per gap (top 3 max). {_ANTI_FAB} Short headed sections.")
    if task == "search_strategy":
        return (f"The shape of the candidate's current search: {g('stats')}. {p}\n\nAdvise how to run the search over the next week: "
                f"whether to broaden or narrow, where to focus effort, and one thing to STOP doing. {_ANTI_FAB} Concrete, grounded in "
                "the numbers given. 4-6 sentences.")
    if task == "market_pulse":
        return (f"Across the candidate's current matches, the most common skills/tags are: {g('trend')}. {p}\n\nIn 4-5 sentences, tell "
                f"them what this says about what's in demand for their target and how to position themselves to match it. {_ANTI_FAB} "
                "Ground it only in the tags given.")
    if task == "search_next_action":
        return (f"The candidate's current search snapshot: {g('stats')}. Their top matches:\n{g('matches')}\n\n{p}\n\nName the single "
                f"most valuable thing they should do in the next hour, and exactly how to start it. {_ANTI_FAB} 2-3 sentences, "
                "imperative, no list.")
    if task == "search_answer":
        return (f"The candidate is looking at this match set:\n{g('matches')}\n\n{p}\n\nAnswer their question using ONLY these matches "
                f"and their real profile: \"{g('question')}\". {_ANTI_FAB} If the matches don't contain the answer, say so plainly. "
                "Be concise.")
    if task == "fit_read":
        return (f"Give an honest fit read of ONE role for this candidate. Role: \"{g('title')}\" at \"{g('org')}\" "
                f"({g('pct')}% modelled fit). Tags: {g('tags')}. Location: {g('loc','n/a')}. {p}{bg_line}\n\nCover what genuinely fits, "
                f"the real gaps, and end with a one-word verdict (Apply / Maybe / Skip) and a single reason. {_ANTI_FAB} 4-6 sentences, "
                "put the verdict on its own final line.")
    if task == "application_hook":
        return (f"Write ONE tailored opening line to start an application or outreach for \"{g('title')}\" at \"{g('org')}\" "
                f"(tags: {g('tags')}). It must connect the candidate's REAL background to this specific role - no invented facts. "
                f"{_ANTI_FAB}\n\n{p}{bg_line}\n\nReturn only the single line.")
    if task == "application_redflags":
        return (f"Before the candidate spends an application on \"{g('title')}\" at \"{g('org')}\" (tags: {g('tags')}; "
                f"ghost-risk: {g('ghost','unknown')}; signal: {g('signal','unknown')}; deadline: {g('deadline','none')}), name the real "
                f"risks or red flags and how to de-risk each. If it looks solid, say so plainly. {_ANTI_FAB} 3-5 short bullets.")
    if task == "role_prep":
        return (f"List the 5-6 interview questions the candidate should most expect for \"{g('title')}\" at \"{g('org')}\", grounded in "
                f"the real demands of that kind of role, each with a one-line note on what a strong answer shows. {_ANTI_FAB}\n\n{p}\n\n"
                "Return a numbered list.")
    if task == "salary_context":
        return (f"Give honest compensation context for \"{g('title')}\" in \"{g('loc','their market')}\""
                + (f" (the listing states a floor around {g('salary')})" if g('salary') else "") +
                f". {_ANTI_FAB} Do NOT invent specific numbers - use [research: typical range for this role/location] placeholders they "
                f"can fill, and give one concrete negotiation angle grounded in their real skills.\n\n{p}\n\nReturn short headed sections.")
    # ---- Mission control "Metis read-out": reads the whole dashboard snapshot
    # (every real stat the page computed) and distils it to a simple, prioritised
    # read-out. Grounded HARD in the snapshot - it must invent no metric. ----
    if task == "overview_briefing":
        return (f"You are Metis, the candidate's career copilot, reading their whole Mission Control dashboard. "
                f"Here is the real, current snapshot of their search - every number in it is genuine:\n\n{g('snapshot')}\n\n{p}\n\n"
                f"Distil this into a simple read-out that a busy person can act on. {_ANTI_FAB} Use ONLY the numbers and facts in the "
                f"snapshot above - never invent a statistic, deadline, company, or outcome, and never restate a number the snapshot "
                f"doesn't contain. Prioritise what actually moves their search forward. Return EXACTLY this structure and nothing else:\n"
                f"STATUS: <one plain-English sentence on where they stand overall right now>\n"
                f"KEY POINTS:\n- <one short sentence>\n- <one short sentence>\n- <one short sentence>\n"
                f"(3 to 5 key points - the most important signals in the snapshot, each grounded in a real number from it)\n"
                f"NEXT MOVES:\n- <imperative action tied to a real number in the snapshot>\n- <imperative action>\n"
                f"(up to 3, highest-leverage first)")
    # ---- Inbox copilot: triage the user's notifications/inbox and name the few
    # items that most deserve a response or action now. Grounded HARD in the real
    # items passed in - invents no message, company, deadline or number. ----
    if task == "inbox_triage":
        return (f"You are Metis, the candidate's copilot, triaging their Kaidostar inbox. Here are their current inbox "
                f"items (newest first), each with its kind, age, source and whether it's unread:\n\n{g('items')}\n\n{p}\n\n"
                f"Tell them which items most deserve a response or action RIGHT NOW, and why. {_ANTI_FAB} Use ONLY the items "
                f"above - never invent a message, company, deadline, percentage or outcome, and never reference an item that "
                f"isn't listed. Prioritise anything time-sensitive (a closing deadline, an undo window, a high-fit match) or "
                f"awaiting the user. Return EXACTLY this structure and nothing else:\n"
                f"TOP:\n- <the item's title> — <one short reason it's worth acting on now>\n- <...>\n"
                f"(1 to 3 items, most urgent first; if genuinely nothing needs action, write a single line: "
                f"'Nothing needs a response right now.')\n"
                f"THEN: <one short sentence on what to do with the rest - skim, archive, or ignore>")
    # ---- Explore: AI-reasoned career directions from the user's self-assessment.
    # Returns STRICT JSON so the frontend can render rich, structured cards and,
    # when the user commits to one, re-target the whole app to it. ----
    if task == "explore_directions":
        return (
            "You are Metis, a sharp, honest career guide. From this person's real self-assessment, propose the career "
            "directions that genuinely fit THEM - grounded in the specific evidence they gave, never generic categories.\n\n"
            f"Their assessment:\n{g('answers')}\n\n{p}\n\n{_ANTI_FAB} Propose 4 distinct directions, strongest fit first; "
            "tie each one concretely to what they actually wrote. Return ONLY a JSON array - no prose, no code fence - of 4 "
            "objects with EXACTLY these keys:\n"
            '[{"title": "short direction name", "description": "one sentence", "why_fits": "grounded in their specific '
            'answers", "day_to_day": "what the work actually looks like", "transferable_skills": ["skills they ALREADY '
            'showed evidence of"], "skills_to_build": ["honest gaps"], "typical_roles": ["2-4 real entry-level titles"], '
            '"outlook": "one honest sentence on demand/competition", "first_step": "one concrete action this week", '
            '"target_types": ["subset of job, internship, college"], "search_terms": ["3-6 keywords to find matching '
            'listings"], "fit": 0-100}]\n'
            "Never invent a credential, statistic or specific employer. Keep every string tight and specific to them."
        )
    # ---- Resume fast-path: read a pasted/uploaded resume and extract a profile
    # the whole app can act on, so the person can skip the questionnaire and go
    # straight to the job search. STRICT JSON out. Everything here is EXTRACTED
    # from their resume - never invented. raw_description must be copied verbatim
    # from the resume (their own words), so the resume-builder's honesty guards
    # downstream stay true. ----
    if task == "resume_profile":
        resume = _clip(i.get("resume", ""), 14000)
        return (
            "You are reading a person's real resume to set up their job search. Extract a structured profile and their "
            "real experience entries. Extract ONLY what is actually in the resume - never invent, infer a number, or add a "
            "skill, employer, title or date that isn't there. Copy experience text VERBATIM (their own words).\n\n"
            f"RESUME:\n{resume}\n\n"
            "Return ONLY a JSON object - no prose, no code fence - with EXACTLY these keys:\n"
            '{"northstar": "one line: the role/field this resume is aimed at (from their objective, most recent or most '
            'senior role); phrase as a goal", "finalidea": "" , "skills": "comma-separated real skills from the resume", '
            '"loc": "their city/location if present, else \\"\\"", "stage": "one of student, grad, switch, working", '
            '"timeframe": "now", "types": ["subset of job, internship, college"], "priorities": [], "dealbreakers": "", '
            '"fullName": "their name from the top of the resume, else \\"\\"", "phone": "their phone if present, else \\"\\"", '
            '"entries": [{"entry_type": "work|education|project", "title": "role or degree", "org": "employer/school", '
            '"start_date": "", "end_date": "", "raw_description": "the exact bullet/description text from the resume, '
            'verbatim"}]}\n'
            "If the text does not look like a resume, return the object with empty strings and an empty entries array. "
            "Leave any field you can't find as an empty string - never fill it with a guess."
        )
    # ---- Resume Studio (Workshop). All three are honesty-first: the frontend runs the
    # deterministic fabrication check on every output before it can be applied. ----
    if task == "metric_bullet":
        # Metric Miner / XYZ Coach: one bullet, rebuilt from the person's OWN answers.
        return (
            "Rewrite ONE resume bullet using the extra details this person just typed about it. "
            f"{_ANTI_FAB} Every number, tool, result and scope must come from the original bullet or their details - "
            "if a detail is vague, stay vague; never round, estimate, or add a figure. Strong past-tense action verb first, "
            "one line, under 30 words, no cliches, no first-person pronouns. Don't upgrade their role: if they took part, "
            "say they contributed, not that they led.\n\n"
            f"Original bullet: \"{g('bullet')}\"\nTheir details (their own words):\n{g('answers')}\n\n"
            "Return only the rewritten bullet - no quotes, no commentary."
        )
    if task == "career_translate":
        # Career-Switch Translator: same facts, the target field's vocabulary.
        return (
            f"This person is moving into {g('target', 'a new field')}. Rewrite each bullet so a hiring manager in that field "
            "instantly sees the transferable value - use that field's vocabulary for the SAME facts. You may rephrase and "
            "re-emphasize, but never add a responsibility, tool, number, title or outcome that isn't in the original. "
            f"{_ANTI_FAB}\n\nBullets (one per line):\n{g('bullets')}\n\n"
            "Return ONLY a JSON array - no prose, no code fence - with one object per bullet, in order: "
            '[{"original": "the bullet as given", "translated": "the rewrite", "terms": ["field vocabulary you used"]}]'
        )
    if task == "resume_review":
        # Scorecard: a recruiter's honest first-pass read of the whole resume.
        resume = _clip(i.get("resume", ""), 9000)
        return (
            f"You are an experienced recruiter screening for: {g('target', 'the role this person is targeting')}. Give the honest "
            f"first-pass read you'd give a friend. {_ANTI_FAB} Quote the resume exactly when you point at a line; never "
            "invent experience they could add.\n\n"
            f"RESUME:\n{resume}\n\n"
            "Format exactly:\nVERDICT: <one line - would you call them, and why>\n"
            "STRENGTHS:\n- <specific to this resume>\n- <...>\n- <...>\n"
            "FIX FIRST:\n- <highest-impact change, quoting the exact line>\n- <...>\n- <...>\n"
            "RISK: <one line - what a skeptical recruiter will question>"
        )
    raise ValueError(f"unknown task: {task}")
 
 
ALLOWED_TASKS = {
    "bullet_rewrite", "pitch", "summary_line", "thank_you", "star_polish", "achievement_polish",
    "cover_letter", "linkedin_headline", "linkedin_about", "skills_gap", "jd_tailor", "outreach",
    "answer_feedback", "tmays", "role_questions", "behavioral_story", "weakness_frame", "why_us",
    "post_interview_debrief",
    # Job Search dashboard copilot
    "search_briefing", "search_triage", "search_skill_gaps", "search_strategy", "market_pulse",
    "search_next_action", "search_answer", "fit_read", "application_hook", "application_redflags",
    "role_prep", "salary_context",
    # Mission control read-out, Inbox triage, Explore directions, Resume import (free - Metis is free for every tier)
    "overview_briefing", "inbox_triage", "explore_directions", "resume_profile",
    # Resume Studio (Workshop): Metric Miner/XYZ rewrite, Career-Switch Translator, recruiter review
    "metric_bullet", "career_translate", "resume_review",
}
 
# The Interview Prep coaching tasks belong to a Pro feature (interview_prep).
# Gated server-side like the page itself, so a Free account can't reach them by
# calling the generic endpoint directly.
INTERVIEW_TASKS = {
    "answer_feedback", "tmays", "role_questions", "behavioral_story", "weakness_frame", "why_us",
    "post_interview_debrief",
}
 
# The Job Search "AI Copilot" tools are a Pro feature. These tasks are gated
# server-side by the ai_copilot flag so a Free account can't reach them by
# calling the generic endpoint directly (the UI panel is gated too).
COPILOT_TASKS = {
    "search_briefing", "search_triage", "search_skill_gaps", "search_strategy", "market_pulse",
    "search_next_action", "search_answer", "fit_read", "application_hook", "application_redflags",
    "role_prep", "salary_context",
}
 
 
DEMO_NOTE = ("\n\nNote: these listings are a demo set from fictional companies. Say so where it matters, and never "
             "present any of these companies as a real employer.")
 
 
def run_assist(anthropic_client, task: str, inputs: dict, profile: dict) -> str:
    prompt = _b(task, inputs or {}, profile or {})
    # the Job Search page's demo set: the model is told the companies are fictional
    if isinstance(inputs, dict) and inputs.get("demo") is True:
        prompt += DEMO_NOTE
    resp = anthropic_client.messages.create(
        model=MODEL, max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    if not text:
        raise ValueError("empty AI response")
    return text
 
