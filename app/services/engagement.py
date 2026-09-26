"""Drafting a real, thoughtful engagement question for a specific
post - never scraping LinkedIn or posting on a person's behalf.
LinkedIn's own API Terms of Use explicitly prohibit both: automated
access to content outside their official APIs, and using any API
access to automate posting, commenting, or other engagement. So this
only ever works from a real post's text the person pastes in
themselves, and only ever drafts words for them to review and post
manually - it never touches LinkedIn directly. See EngagementSuggestion
in db_models.py for the full reasoning.
 
Two real, explicit considerations shape the actual drafting:
 
1. Optimized for genuine opportunity, not generic engagement - a
   thoughtful-sounding but content-free question is worse than no
   comment at all, so the prompt explicitly asks for a question that
   demonstrates real, specific understanding of the post's actual
   content and could plausibly open a real conversation.
 
2. Whether the poster looks like a smaller, more accessible
   decision-maker - a small-business owner, a solo founder, a
   manager at a small team - who might realistically read a comment
   personally and be in a position to actually offer something,
   versus a large-company executive whose posts get hundreds of
   comments a senior leader will never personally see. This doesn't
   change WHETHER a question gets drafted, only how the strategy
   note frames the realistic likely outcome.
"""
 
import json
 
 
def draft_engagement_suggestion(anthropic_client, profile: dict, post_content: str, poster_context: str | None) -> dict:
    """Drafts one real, thoughtful question grounded in the actual,
    real post text provided - never invents post content, never
    invents facts about the poster beyond what poster_context says.
    """
    poster_context = (poster_context or "").strip() or None
    poster_line = f'What the person knows about who posted this: "{poster_context}"' if poster_context else "No information given about who posted this beyond the text itself."
 
    prompt = f"""A candidate's real, stated goal: "{profile.get('northstar', 'not specified')}". Their real, stated skills: "{profile.get('skills', 'not specified')}".
 
A real post they found and want to engage with thoughtfully:
"{post_content}"
 
{poster_line}
 
Draft ONE real, specific, thoughtful question or comment this candidate could post themselves in reply - never something generic like "Great post!" or "Thanks for sharing," and never something that could apply to any post on any topic. It must demonstrate genuine, specific understanding of what THIS post actually says, and be the kind of question that could plausibly open a real conversation with the poster - not just perform engagement. Do not invent any fact about the poster, their company, or their situation beyond what's actually given above; if poster_context is empty, do not guess at who they are.
 
Also give an honest, realistic read on whether this poster looks like a smaller, more accessible decision-maker (e.g. a small-business owner, solo founder, or manager at a small team who might realistically read and personally respond to a thoughtful comment) versus someone at a large company whose posts likely get many comments a senior leader won't personally see. Base this only on what's actually stated in the post text and poster_context - if there's genuinely not enough information to tell, say so honestly rather than guessing.
 
Return a JSON object with exactly these three keys:
- drafted_question: the real, specific question/comment text, ready to post as-is (no quotes around it, no "Consider saying:" preamble)
- is_smaller_decision_maker: true only if the real, given information genuinely suggests a smaller, more accessible poster - false if it suggests a large organization, and false (not a guess) if there's genuinely not enough information either way
- reasoning: 1-2 honest sentences explaining why this specific question was chosen and what the realistic read on the poster is - visible to the person deciding whether to actually post this, not hidden reasoning
 
Return ONLY valid JSON, nothing else, no markdown fences, no commentary."""
 
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    except Exception as e:
        raise ValueError(f"Could not draft an engagement suggestion just now: {e}")
 
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Engagement suggestion response was not valid JSON: {e}")
    if not isinstance(parsed, dict):
        raise ValueError(f"Engagement suggestion response was not a JSON object: {type(parsed).__name__}")
 
    if not isinstance(parsed.get("drafted_question"), str) or not parsed["drafted_question"].strip():
        raise ValueError(f"Engagement suggestion response is missing a real drafted_question: {parsed}")
    if not isinstance(parsed.get("is_smaller_decision_maker"), bool):
        raise ValueError(f"Engagement suggestion response's is_smaller_decision_maker is not a real boolean: {parsed}")
    if not isinstance(parsed.get("reasoning"), str) or not parsed["reasoning"].strip():
        raise ValueError(f"Engagement suggestion response is missing real reasoning: {parsed}")
 
    return parsed
 
