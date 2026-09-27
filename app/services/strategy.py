from app.services.timeutil import utcnow
"""Genuine longitudinal career-strategy reasoning - understanding
someone's real, current position and how their actual actions
compound toward a result, rather than scoring one listing at a time
in isolation. Every other AI-calling function in this codebase
reasons about a single listing, a single application, or a single
outcome. Nothing synthesizes across a person's real, accumulated
history to answer the actual question a career platform should be
able to answer: given everything this person has genuinely done so
far, what's the single highest-leverage next move, and why does it
compound rather than just add one more independent task to a list?
 
The real, new risk this introduces that per-listing reasoning doesn't
have: inventing a plausible-sounding connection between two real but
actually-unrelated data points. A model asked to find compounding
connections has a genuine incentive to find one even where none
exists - two applications to unrelated fields can be narrated into a
"strategic thread" that isn't real. The prompt is explicit that a
genuinely disconnected set of actions should be reported as exactly
that, not stitched into a false narrative.
"""
 
 
def _format_applications_for_prompt(applications: list[dict]) -> str:
    if not applications:
        return "No applications sent yet."
    lines = []
    for a in applications:
        status = a.get("status") or "pending_review"
        outcome = f", real outcome: {a['outcome_status']}" if a.get("outcome_status") else ""
        lines.append(f"- \"{a.get('listing_title', 'Unknown role')}\" at {a.get('listing_org', 'unknown org')} "
                     f"(sent {a.get('created_at', 'unknown date')}, status: {status}{outcome})")
    return "\n".join(lines)
 
 
def _format_roadmap_for_prompt(milestones: list[dict]) -> str:
    if not milestones:
        return "No roadmap has been generated yet."
    lines = []
    for m in milestones:
        lines.append(f"- Stage {m.get('target_stage')}: \"{m.get('title', '')}\" - status: {m.get('status', 'planned')}")
    return "\n".join(lines)
 
 
def _format_engagement_for_prompt(engagement_activity: list[dict]) -> str:
    """Only ever includes suggestions the person genuinely accepted -
    a drafted-but-ignored or declined suggestion isn't a real signal
    about what they actually did, so including it would risk the
    model treating a hypothetical as if it were real activity.
    """
    accepted = [e for e in (engagement_activity or []) if e.get("status") == "accepted"]
    if not accepted:
        return "No real, accepted engagement activity yet."
    lines = []
    for e in accepted:
        log_note = f", follow-up: {e['communication_log'][-1]['note']}" if e.get("communication_log") else ""
        lines.append(f"- Genuinely posted a reply to a real post ({e.get('poster_context') or 'poster context not given'}){log_note}")
    return "\n".join(lines)
 
 
def _format_previous_analysis_for_prompt(previous: dict | None) -> str:
    if not previous:
        return ""
    return (f"Their position as read last time: \"{previous.get('current_position', '')}\"\n"
            f"The next move suggested last time: \"{(previous.get('next_move') or {}).get('action', '')}\"")
 
 
def analyze_strategic_position(
    anthropic_client,
    profile: dict,
    roadmap_milestones: list[dict],
    applications: list[dict],
    saved_listings: list[dict],
    previous_analysis: dict | None = None,
    engagement_activity: list[dict] | None = None,
) -> dict:
    """The real, new synthesis this app has never had: not "does this
    ONE listing fit", but "given everything this person has actually
    done, where do they genuinely stand, and what's the highest-
    leverage next move". Grounds the analysis in real, concrete data
    (real applications sent, real outcomes received, real roadmap
    progress) rather than generic career-stage advice.
 
    previous_analysis, when provided, is the most recent real result
    on record for this person - what makes this genuinely
    longitudinal rather than a single, isolated snapshot each time.
    The same anti-fabrication discipline that governs compounding
    connections governs this too: a model asked whether real progress
    happened has a genuine incentive to manufacture encouraging
    change even where none exists, so the prompt is explicit that
    "nothing has genuinely changed" is a valid, honest finding.
    """
    applications_text = _format_applications_for_prompt(applications)
    roadmap_text = _format_roadmap_for_prompt(roadmap_milestones)
    saved_text = ", ".join(f"\"{s.get('title', '')}\" at {s.get('org', '')}" for s in saved_listings[:10]) or "None saved yet."
    engagement_text = _format_engagement_for_prompt(engagement_activity)
    previous_text = _format_previous_analysis_for_prompt(previous_analysis)
    previous_block = f"\n{previous_text}\n" if previous_text else ""
    previous_instruction = (
        "\n\n4. Since you have a real record of their previous position above, explicitly compare it against their current, real situation. Has genuine, measurable progress happened since then (e.g. a new real outcome, a completed roadmap milestone, real movement on the next move suggested last time)? Or has nothing genuinely changed? Either is a valid, honest finding - if their real data shows no meaningful movement since the last check, say that plainly rather than manufacturing encouraging-sounding change that isn't actually there. Do not credit them with \"progress\" for actions that were already reflected in the previous read."
        if previous_text else ""
    )
    momentum_key_instruction = (
        "\n- momentum_since_last_check: an object with \"changed\" (true only if something real and specific genuinely changed since the previous position above) and \"summary\" (1-2 honest sentences - either naming the real, specific change, or plainly stating that nothing has genuinely moved since last time)"
        if previous_text else ""
    )
 
    prompt = f"""A candidate's real, stated goal: "{profile.get('northstar', 'not specified')}". What "made it" looks like to them: "{profile.get('final_idea', 'not specified')}". Their stated skills: "{profile.get('skills', 'not specified')}". What matters most to them: {', '.join(profile.get('priorities') or []) or 'not specified'}.
{previous_block}
Their real roadmap (their own stated plan):
{roadmap_text}
 
Their real applications actually sent, with real outcomes where known:
{applications_text}
 
Listings they've saved but not yet acted on: {saved_text}
 
Their real, genuine engagement activity (only suggestions they actually accepted and posted, never ones drafted but ignored):
{engagement_text}
 
You are synthesizing this person's REAL, accumulated history - not scoring one listing in isolation. Answer these things, grounded ONLY in what's actually here:
 
1. An honest, specific read on where they genuinely stand right now - their real momentum (or lack of it), based on the actual pattern of applications/outcomes/roadmap progress above, not a generic assessment of "early career" or similar. If the real data shows stalled momentum or no clear direction, say that plainly rather than finding false encouragement. Also explicitly check whether their real, actual applications align with their stated goal above - if their real behavior points somewhere genuinely different from what they said they want (e.g. their stated goal is one field but every real application sent is in a different one), name that honestly. This kind of real, checkable mismatch is one of the most valuable things this analysis can surface, so don't let a focus on "momentum" alone cause you to miss it.
 
2. Whether their real actions so far genuinely compound - do any of their actual applications, roadmap progress, saved listings, or real engagement activity build on each other in a real, specific way (e.g. an application to a smaller company in the same real domain as their stated goal genuinely builds real, checkable experience toward a saved listing at a bigger one, or a real, accepted engagement reply to someone at a company connects to a real application or saved listing there)? This must be a REAL, SPECIFIC connection between things that actually appear above - if their actions are genuinely disconnected from each other with no real compounding relationship, say that honestly rather than inventing a narrative thread that isn't there. Do not stitch together two unrelated actions into a false "strategy" - a genuine absence of connection is a real, useful finding, not a failure to find one. A real connection is something that has ALREADY happened - a real outcome, a real shared company, a real skill actually demonstrated in one place that a specific other listing actually requires. It is not two independent, still-pending applications in the same broad field that COULD matter to each other IF a future outcome goes a certain way - "if either produces an offer, it would create leverage" is speculation about a hypothetical future, not a real, existing compounding relationship, even when the underlying field matches. If the only relationship you can point to is that kind of hypothetical, treat it as no genuine connection rather than a real one.
 
3. Given all of the above, ONE specific, highest-leverage next move - not a generic "apply to more listings" but a specific action that genuinely compounds given their real, particular situation, and a concrete reason why THIS one, not something else.{previous_instruction}
 
Return a JSON object with exactly these four keys:
- current_position: 2-3 honest, specific sentences per point 1 above
- compounding_connections: an array of 0-3 strings, each describing one real, specific compounding relationship you found (empty array if genuinely none exist - do not force one)
- has_genuine_compounding: true only if compounding_connections is non-empty and each entry describes a real, specific, checkable relationship - false if their actions are genuinely disconnected
- next_move: an object with "action" (one specific, concrete thing to do) and "why_this_compounds" (1-2 sentences on why this specific move, given their real situation, builds on what already exists rather than starting a new, disconnected thread){momentum_key_instruction}
 
Return ONLY valid JSON, nothing else, no markdown fences, no commentary."""
 
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    except Exception as e:
        raise ValueError(f"Could not generate a strategic position analysis just now: {e}")
 
    import json
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Strategic position response was not valid JSON: {e}")
    if not isinstance(parsed, dict):
        raise ValueError(f"Strategic position response was not a JSON object: {type(parsed).__name__}")
 
    # Real shape validation, consistent with every other AI-JSON
    # function in this codebase - a malformed response must be
    # rejected explicitly here, not silently passed through to
    # whatever renders it.
    if not isinstance(parsed.get("current_position"), str) or not parsed["current_position"].strip():
        raise ValueError(f"Strategic position response is missing a real current_position: {parsed}")
    if not isinstance(parsed.get("compounding_connections"), list):
        raise ValueError(f"Strategic position response's compounding_connections is not a real list: {parsed}")
    if not all(isinstance(c, str) and c.strip() for c in parsed["compounding_connections"]):
        raise ValueError(f"Strategic position response has an empty or non-string compounding connection: {parsed}")
    if not isinstance(parsed.get("has_genuine_compounding"), bool):
        raise ValueError(f"Strategic position response's has_genuine_compounding is not a real boolean: {parsed}")
    next_move = parsed.get("next_move")
    if not isinstance(next_move, dict) or not isinstance(next_move.get("action"), str) or not next_move["action"].strip() \
       or not isinstance(next_move.get("why_this_compounds"), str) or not next_move["why_this_compounds"].strip():
        raise ValueError(f"Strategic position response has an incomplete next_move: {parsed}")
    if previous_analysis:
        momentum = parsed.get("momentum_since_last_check")
        if not isinstance(momentum, dict) or not isinstance(momentum.get("changed"), bool) \
           or not isinstance(momentum.get("summary"), str) or not momentum["summary"].strip():
            raise ValueError(f"Strategic position response has an incomplete momentum_since_last_check: {parsed}")
 
    # Honest consistency check between has_genuine_compounding and the
    # actual, real content of compounding_connections - a genuinely
    # plausible failure mode where the model states "true" while the
    # array is empty, which would otherwise silently render a
    # confident "yes, compounding" verdict with nothing behind it.
    if parsed["has_genuine_compounding"] and not parsed["compounding_connections"]:
        parsed["has_genuine_compounding"] = False
 
    return parsed
 
 
def _compute_input_signature(roadmap_milestones: list[dict], applications: list[dict], saved_listings: list[dict], engagement_activity: list[dict] | None = None) -> str:
    """A cheap, real signature of the person's current, actual data
    shape - not a hash of the full content, just enough to detect a
    genuine change: how many of each thing exist, and the most
    recent real timestamp/status seen. Adding a new application,
    getting a new outcome, or completing a roadmap milestone all
    change this signature, correctly forcing a fresh analysis. Two
    calls with the exact same real data produce the exact same
    signature, correctly reusing the cache.
    """
    import hashlib
    roadmap_sig = "|".join(f"{m.get('target_stage')}:{m.get('status')}" for m in roadmap_milestones)
    apps_sig = "|".join(f"{a.get('status')}:{a.get('outcome_status')}:{a.get('created_at')}" for a in applications)
    saved_sig = "|".join(f"{s.get('title')}:{s.get('org')}" for s in saved_listings)
    engagement_sig = "|".join(
        f"{e.get('status')}:{len(e.get('communication_log') or [])}" for e in (engagement_activity or [])
    )
    raw = f"{roadmap_sig}||{apps_sig}||{saved_sig}||{engagement_sig}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
 
 
def get_or_analyze_strategic_position(
    db,
    anthropic_client,
    user_id,
    profile: dict,
    roadmap_milestones: list[dict],
    applications: list[dict],
    saved_listings: list[dict],
    engagement_activity: list[dict] | None = None,
) -> dict:
    """Checks the real cache before ever making a real, billed API
    call - without this, a person opening the overview page twice in
    a row, or refreshing after reading the result, would trigger the
    same real analysis call again for no real reason. Unlike company
    leadership research, staleness here is content-based rather than
    time-based: this person's own real applications/roadmap/saved
    listings can genuinely change within minutes, so a fixed time
    window would risk returning a stale read right after they took a
    real, new action and immediately re-checked their position.
    """
    from app.models.db_models import StrategicPositionCache, StrategicPositionHistory
    from datetime import datetime
 
    signature = _compute_input_signature(roadmap_milestones, applications, saved_listings, engagement_activity)
    cached = db.query(StrategicPositionCache).filter(StrategicPositionCache.user_id == user_id).first()
    if cached and cached.input_signature == signature:
        return {**cached.result, "cached": True}
 
    previous_entry = (
        db.query(StrategicPositionHistory)
        .filter(StrategicPositionHistory.user_id == user_id)
        .order_by(StrategicPositionHistory.analyzed_at.desc())
        .first()
    )
    previous_analysis = previous_entry.result if previous_entry else None
 
    fresh = analyze_strategic_position(
        anthropic_client, profile, roadmap_milestones, applications, saved_listings,
        previous_analysis=previous_analysis, engagement_activity=engagement_activity,
    )
 
    if cached:
        cached.input_signature = signature
        cached.result = fresh
        cached.analyzed_at = utcnow()
        db.add(StrategicPositionHistory(user_id=user_id, input_signature=signature, result=fresh))
        db.commit()
    else:
        from sqlalchemy.exc import IntegrityError
        db.add(StrategicPositionCache(user_id=user_id, input_signature=signature, result=fresh))
        db.add(StrategicPositionHistory(user_id=user_id, input_signature=signature, result=fresh))
        try:
            db.commit()
        except IntegrityError:
            # Concurrent first-time analysis for this user won the row (user_id is the
            # PRIMARY KEY of the strategic-position cache), so this bare insert would
            # otherwise 500. Roll back and return this run's freshly computed analysis
            # (the winner cached this same user's equally-valid result) rather than
            # erroring - same check-then-insert race the rest of the codebase guards.
            db.rollback()
 
    return {**fresh, "cached": False}
 
