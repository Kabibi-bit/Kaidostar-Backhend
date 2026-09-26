"""Two features that are genuinely different from what any competitor
offers, because they require actually being honest about the match
score in the first place:
 
1. Confidence calibration - joins real Outcome records back to the
   Application's confidence_pct at the time it was sent, and reports
   whether high-confidence matches actually convert more often than
   low-confidence ones. Most products show a score and never check
   whether it means anything; this checks, using the user's own
   real results.
 
2. Rejection/ghost autopsy - a real, specific AI comparison of what
   was actually sent against what the listing asked for, instead of
   generic "keep trying" advice.
"""
import math
 
 
def _round_half_up(x: float) -> int:
    """JavaScript's Math.round rounds .5 UP; Python's round() uses banker's
    rounding (half to even). The frontend's compute calibration uses Math.round,
    so a rate landing exactly on N.5 (e.g. 1 positive of 8 -> 12.5%) rendered as
    13 on the frontend but 12 on the backend - a real 1-point FE/BE divergence on
    a user-facing honesty number. floor(x + 0.5) reproduces Math.round for the
    always-non-negative percentages here. Mirrors matching._round_half_up.
    """
    return math.floor(x + 0.5)
 
 
def compute_calibration(applications: list[dict], outcomes: list[dict]) -> dict:
    """applications: [{listing_id, confidence_pct}], outcomes: [{listing_id, status}].
    Buckets applications by confidence range and reports the real
    positive-outcome rate (interview/offer) within each bucket.
    """
    outcome_by_listing = {}
    for o in outcomes:
        # Keep the most recent/most advanced outcome per listing if there are multiples
        outcome_by_listing[o.get("listing_id")] = o.get("status")
 
    buckets = {
        "80-100%": {"range": (80, 101), "total": 0, "positive": 0},
        "60-79%": {"range": (60, 80), "total": 0, "positive": 0},
        "below 60%": {"range": (0, 60), "total": 0, "positive": 0},
    }
    positive_statuses = {"interview", "offer"}
 
    for app in applications:
        app_listing_id = app.get("listing_id")
        if app_listing_id not in outcome_by_listing:
            continue  # no real outcome logged yet for this one - excluded, not counted as a failure
        confidence = float(app.get("confidence_pct") or 0)
        outcome = outcome_by_listing[app_listing_id]
        for bucket in buckets.values():
            lo, hi = bucket["range"]
            if lo <= confidence < hi:
                bucket["total"] += 1
                if outcome in positive_statuses:
                    bucket["positive"] += 1
                break
 
    result = {}
    for label, b in buckets.items():
        rate = _round_half_up((b["positive"] / b["total"]) * 100) if b["total"] > 0 else None
        result[label] = {"total_with_outcomes": b["total"], "positive_rate_pct": rate}
    return result
 
 
def explain_outcome_deep(anthropic_client, listing: dict, application_draft: str, confidence_pct: float, outcome_status: str, profile: dict) -> str:
    """A real, specific analysis of why a rejected/ghosted application
    likely didn't land - grounded in the actual draft sent and the
    actual listing requirements, not generic advice.
    """
    prompt = (
        f"A candidate applied to \"{listing['title']}\" at {listing['org']}, tags: {', '.join(listing.get('tags', []))}. "
        f"The match confidence at the time was {confidence_pct}%. The outcome was: {outcome_status}.\n\n"
        f"The application they actually sent:\n\"{application_draft}\"\n\n"
        f"Candidate's stated goal: \"{profile.get('northstar','')}\". Skills: \"{profile.get('skills','')}\".\n\n"
        "Give a specific, honest hypothesis for what likely contributed to this outcome - compare the actual "
        "draft against the actual listing's requirements, don't give generic advice like 'keep trying' or "
        "'tailor your resume'. If the confidence score itself seems to have been wrong (too high or too low "
        "for what happened), say so directly. 3-4 sentences, concrete and specific."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=250,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
