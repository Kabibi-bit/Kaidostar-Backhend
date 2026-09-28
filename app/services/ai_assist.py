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
    raise ValueError(f"unknown task: {task}")
 
 
ALLOWED_TASKS = {
    "bullet_rewrite", "pitch", "summary_line", "thank_you", "star_polish", "achievement_polish",
    "cover_letter", "linkedin_headline", "linkedin_about", "skills_gap", "jd_tailor", "outreach",
    "answer_feedback", "tmays", "role_questions", "behavioral_story", "weakness_frame", "why_us",
    "post_interview_debrief",
}
 
 
def run_assist(anthropic_client, task: str, inputs: dict, profile: dict) -> str:
    prompt = _b(task, inputs or {}, profile or {})
    resp = anthropic_client.messages.create(
        model=MODEL, max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
    if not text:
        raise ValueError("empty AI response")
    return text
 
