"""Cover letter generation - grounded only in the person's real,
existing resume entries and profile, never inventing a connection,
location, or experience they don't actually have.
 
This directly answers a real, documented, verified failure in a
competing product: their cover letter generator produced a line
claiming "your reputation for delivering exceptional commercial
spaces in dynamic markets like Chicago and Phoenix strongly
resonates with my track record" for a person with no track record
in commercial real estate and no connection to either city. That's
not a hypothetical risk - it's a confirmed, reported output.
 
Mirrors generate_resume_summary's exact two-layer discipline: prompt
instructions telling the model not to invent things, plus a second,
independent, deterministic check afterward that doesn't just trust
the prompt worked. _find_fabricated_numbers already catches invented
metrics; _find_unverifiable_claims below is a genuinely different,
complementary check for the specific failure mode above - an invented
place, market, or specific claim that appears nowhere in the
person's real, actual source material.
"""
 
import re
 
 
def _find_unverifiable_claims(source_text: str, letter_text: str, listing_org: str) -> list[str]:
    """Flags proper-noun-shaped phrases (capitalized words, or runs of
    them) that appear in the generated letter but nowhere in the
    person's own real source text - the actual shape the documented
    "Chicago and Phoenix" fabrication took. The target company's own
    name is deliberately excluded, since naming the real company
    being applied to is expected and correct, not a fabrication.
 
    This is a heuristic, not a certainty - flags candidates for a
    human to glance at, exactly like flagged_numbers does, rather
    than silently rewriting or blocking the letter. A flagged phrase
    that turns out to be genuinely fine (a real skill name that
    happens to be capitalized, like "Python") is a false positive
    worth a two-second glance, which is a far smaller cost than a
    fabricated personal connection slipping through unflagged.
    """
    proper_noun_pattern = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")
    source_phrases = set(proper_noun_pattern.findall(source_text))
    letter_phrases = proper_noun_pattern.findall(letter_text)
 
    org_words = set((listing_org or "").split())
    _starters = ("I", "The", "This", "A", "My", "It", "In", "As", "With", "For", "To", "Your", "Their", "Our", "We", "You", "That", "These", "Given")
    flagged = []
    seen = set()
    for phrase in letter_phrases:
        # The greedy pattern can glob a leading sentence-starter onto a
        # real proper noun ("The Chicago", "My Stanford"). Strip a
        # leading starter word so the genuine fabrication surfaces
        # cleanly ("Chicago") instead of a muddied phrase - and so a
        # bare starter ("The") still drops out to nothing.
        words = phrase.split()
        while len(words) > 1 and words[0] in _starters:
            words = words[1:]
        phrase = " ".join(words)
        if not phrase or phrase in _starters:
            continue
        if phrase in seen:
            continue
        seen.add(phrase)
        if phrase in source_phrases:
            continue
        if phrase in org_words or phrase == (listing_org or ""):
            continue
        flagged.append(phrase)
    return flagged
 
 
def generate_cover_letter(anthropic_client, profile: dict, entries: list[dict], listing: dict) -> dict:
    """A real cover letter grounded only in the person's own, real
    entries and stated goal, tailored to one specific listing. Never
    invents a specific connection, achievement, or location the
    person hasn't actually stated - see _find_unverifiable_claims
    above for why that specific failure mode gets its own check.
    """
    if not entries and not profile.get("northstar"):
        return {"letter": "", "flagged_numbers": [], "flagged_claims": []}
 
    entry_lines = [
        f'- {e["title"]}' + (f' at {e["org"]}' if e.get("org") else '') + (f': {e["raw_description"]}' if e.get("raw_description") else '')
        for e in entries[:6]
    ]
    prompt = (
        f'A candidate\'s real, stated career goal: "{profile.get("northstar", "")}". Their real, stated skills: "{profile.get("skills", "")}".\n\n'
        + ("Their real experience entries:\n" + "\n".join(entry_lines) + "\n\n" if entry_lines else "\n")
        + f'A real listing they want to apply to: "{listing.get("title", "")}" at {listing.get("org", "")}. '
        f'Real tags on this listing: {", ".join(listing.get("tags", []))}. '
        f'Real listing description: "{listing.get("description", "")[:600]}"\n\n'
        "Write a real, honest cover letter (3-4 short paragraphs) connecting this candidate's ACTUAL, real experience "
        "above to this specific role. Ground every claim in what's actually stated above - do not invent a specific "
        "achievement, metric, location, market, client, or personal connection to the company that isn't genuinely "
        "implied by the real entries or goal given. If the real material is thin, write a shorter, honest letter that "
        "doesn't overreach - a genuine, modest letter is far better than a padded, fabricated one. No cliches, no "
        "generic template language like \"I am excited to apply\" as an opening line - write like a specific, real "
        "person who actually read the listing.\n\n"
        "Return ONLY the letter text, nothing else, no subject line, no \"Dear Hiring Manager\" salutation preamble "
        "explanation."
    )
 
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    letter = "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
    from app.services.resume_builder import _find_fabricated_numbers
    source_text = f'{profile.get("northstar") or ""} ' + " ".join(f'{e.get("org") or ""} {e.get("raw_description") or ""}' for e in entries)
    flagged_numbers = _find_fabricated_numbers(source_text, letter)
    flagged_claims = _find_unverifiable_claims(source_text, letter, listing.get("org", ""))
 
    return {"letter": letter, "flagged_numbers": flagged_numbers, "flagged_claims": flagged_claims}
 
