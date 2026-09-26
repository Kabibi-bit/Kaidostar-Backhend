"""Career discovery for people who don't yet know what direction to
aim at. Mirrors the frontend's client-side scoring exactly, so the
demo and the real backend behave identically once connected. Unlike
typical career-quiz products, every suggested direction is checked
against real stored listings (how many currently relate to it), and
the deep explanation is a genuine Claude call grounded in the
person's actual answers, not a canned description per direction.
"""
import re
from app.services.matching import _word_boundary_contains
 
# Words too broad and common to be treated as meaningful when they
# happen to be a literal prefix of a tag (see the prefix rule in
# score_career_directions below) - found via sweeping common words
# against every real tag: "people" genuinely prefixes "peopleops"
# but is generic enough to apply to nearly any people-facing role,
# not specifically HR.
_GENERIC_PREFIX_EXCLUSIONS = {
    "people", "team", "work", "help", "time", "life", "good", "great", "thing", "love", "like",
    # Found via a broader sweep against real listing tags (not just
    # the curated 16-direction list): "lead" as a common job-title
    # suffix ("Support Lead") doesn't genuinely mean "leadership" as
    # an abstract trait, and "position" as a generic word for a job
    # doesn't mean "positioning" as a specific marketing concept -
    # both would have over-matched almost any listing tagged with
    # the longer word, regardless of real relevance.
    "lead", "position",
    # Found by systematically testing candidate generic words against
    # every real tag in CAREER_DIRECTIONS, the same sweep that found
    # the entries above: "business" is a genuine, literal prefix of
    # "businessdevelopment", but someone typing "I want a career in
    # business" is extremely common, vague phrasing that applies just
    # as plausibly to finance, product strategy, or marketing as it
    # does to sales specifically - the same over-broad-match problem
    # "people" was excluded for, not a genuinely sales-specific signal.
    "business",
}
 
CAREER_DIRECTIONS = [
    {"id": "product-strategy", "title": "Product & Business Strategy", "description": "Deciding what gets built and why - balancing user needs, data, and business goals.", "dims": {"people": 2, "data": 2, "creative": 1, "structure": 2}, "listing_tags": ["product", "roadmap", "stakeholder", "strategy"]},
    {"id": "data-analytics", "title": "Data & Analytics", "description": "Finding patterns in information to answer real questions and guide decisions.", "dims": {"people": 0, "data": 3, "creative": 0, "structure": 2}, "listing_tags": ["sql", "python", "analytics", "data", "dashboards"]},
    {"id": "software-engineering", "title": "Software Engineering", "description": "Building the systems and tools other people and businesses run on.", "dims": {"people": 0, "data": 2, "creative": 1, "structure": 2}, "listing_tags": ["python", "backend development", "ml", "testing"]},
    {"id": "ux-design", "title": "UX & Design", "description": "Shaping how something looks, feels, and works for the people using it.", "dims": {"people": 2, "data": 0, "creative": 3, "structure": 0}, "listing_tags": ["figma", "user research", "prototyping", "ux"]},
    {"id": "marketing-comms", "title": "Marketing & Communications", "description": "Telling a story clearly enough that the right people actually hear it.", "dims": {"people": 2, "data": 1, "creative": 2, "structure": 0}, "listing_tags": ["marketing", "writing", "positioning", "growth"]},
    {"id": "healthcare-science", "title": "Healthcare & Life Sciences", "description": "Working directly on human health, from clinical care to research.", "dims": {"people": 3, "data": 1, "creative": 0, "structure": 2}, "listing_tags": ["sports medicine", "athletic training", "injury prevention", "research"]},
    {"id": "education-teaching", "title": "Education & Teaching", "description": "Helping other people learn something you understand well.", "dims": {"people": 3, "data": 0, "creative": 1, "structure": 1}, "listing_tags": ["mentorship", "leadership", "coaching", "training"]},
    {"id": "skilled-trades", "title": "Skilled Trades & Hands-on Work", "description": "Building or fixing real, physical things - work you can see the result of.", "dims": {"people": 1, "data": 0, "creative": 1, "structure": 1}, "listing_tags": ["operations", "process", "training", "conditioning"]},
    {"id": "creative-media", "title": "Creative & Media", "description": "Making things - writing, video, design, or content people actually engage with.", "dims": {"people": 1, "data": 0, "creative": 3, "structure": 0}, "listing_tags": ["writing", "positioning", "figma", "prototyping"]},
    {"id": "social-impact", "title": "Social Impact & Nonprofit", "description": "Working on a mission-driven problem where the impact matters more than the paycheck.", "dims": {"people": 3, "data": 1, "creative": 1, "structure": 1}, "listing_tags": ["policy", "ethics", "mentorship", "leadership"]},
    {"id": "finance-ops", "title": "Finance & Operations", "description": "Keeping the numbers, processes, and logistics of an organization actually working.", "dims": {"people": 0, "data": 2, "creative": 0, "structure": 3}, "listing_tags": ["finance", "excel", "operations", "reporting"]},
    {"id": "sports-athletics", "title": "Sports & Athletics", "description": "A career built around competition, coaching, or the business of sport.", "dims": {"people": 2, "data": 0, "creative": 1, "structure": 1}, "listing_tags": ["athletics", "coaching", "sports management", "training"]},
    {"id": "sales-bizdev", "title": "Sales & Business Development", "description": "Building relationships and making the case for why someone should say yes - to a product, a partnership, or an idea.", "dims": {"people": 3, "data": 1, "creative": 1, "structure": 1}, "listing_tags": ["sales", "businessdevelopment", "accountexecutive", "growth"]},
    {"id": "hr-people", "title": "HR & People Operations", "description": "Building the systems and relationships that help an organization's people actually thrive.", "dims": {"people": 3, "data": 0, "creative": 0, "structure": 2}, "listing_tags": ["hr", "humanresources", "recruiting", "peopleops"]},
    {"id": "customer-success", "title": "Customer Success & Support", "description": "Making sure the people who already chose a product or service actually get real value from it.", "dims": {"people": 3, "data": 1, "creative": 0, "structure": 1}, "listing_tags": ["customersuccess", "customersupport", "accountmanagement", "clientsuccess"]},
    {"id": "legal-compliance", "title": "Legal & Compliance", "description": "Making sure an organization's decisions actually hold up - to regulation, contracts, and real-world risk.", "dims": {"people": 1, "data": 1, "creative": 0, "structure": 3}, "listing_tags": ["legal", "compliance", "regulatory", "paralegal"]},
]
 
 
def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z\-]{2,}", (text or "").lower())
 
 
def score_career_directions(answers: dict, all_listing_tags: list[list[str]]) -> list[dict]:
    """answers: {people, data, creative, structure} each 0-3, plus free_text.
    all_listing_tags: the .tags list of every listing currently stored,
    used to compute a real 'related opportunities' count per direction.
    """
    free_text_tokens = _tokenize(answers.get("free_text", ""))
    # Coerce each work-style dimension to a real number (default 1): a missing key
    # already defaulted to 1, but an explicit JSON null (an unanswered slider) made
    # answers.get(k, 1) return None, and abs(dim - None) raised a TypeError. This
    # keeps the missing->1 behavior and additionally makes null/garbage safe.
    def _dim(v):
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else 1
    ans_people, ans_data = _dim(answers.get("people")), _dim(answers.get("data"))
    ans_creative, ans_structure = _dim(answers.get("creative")), _dim(answers.get("structure"))
    results = []
    for direction in CAREER_DIRECTIONS:
        dim_diff = (
            abs(direction["dims"]["people"] - ans_people)
            + abs(direction["dims"]["data"] - ans_data)
            + abs(direction["dims"]["creative"] - ans_creative)
            + abs(direction["dims"]["structure"] - ans_structure)
        )
        max_diff = 12
        pct = round((1 - (dim_diff / max_diff)) * 100)
        # Word-boundary match catches genuine whole-word matches and
        # multi-word tags ("injury prevention"). The prefix check
        # separately catches this file's compound tags
        # (customersuccess, humanresources, businessdevelopment) -
        # concatenated as single tokens elsewhere in this codebase
        # too, so word-boundary matching alone can't recognize
        # "customer" as a real word inside "customersuccess" the same
        # way it correctly refuses to treat "brand" as a real word
        # inside "branding". Minimum 4 characters and must start at
        # position 0, not appear mid-tag - checked against every real
        # tag in CAREER_DIRECTIONS before adding this, specifically
        # to avoid recreating the exact class of bug this replaced:
        # "event" matching inside "injury prevention" (via
        # "prEVENTion") and "our" matching inside "humanresources"
        # (via "resOURces") were both real, found by direct testing,
        # and neither is a genuine prefix of its tag - only a
        # substring buried mid-word - so this stays correctly
        # excluded under the new rule.
        #
        # _GENERIC_PREFIX_EXCLUSIONS handles a separate, real problem
        # found by sweeping common words against every tag: "people"
        # is a genuine, literal prefix of "peopleops", but it's broad
        # enough to apply to almost any people-facing role, not
        # specifically HR - matching it would over-credit one
        # direction just because of how its tag happens to be
        # spelled, not because of real semantic specificity like
        # "customer" genuinely has. A targeted exclusion, not a
        # length threshold - raising the minimum length would have
        # also excluded genuinely good matches like "client" (6
        # chars, same length as "people").
        def _tag_matches(tag, tok):
            if _word_boundary_contains(tag, tok) or _word_boundary_contains(tok, tag):
                return True
            if len(tok) >= 4 and tok not in _GENERIC_PREFIX_EXCLUSIONS and tag.startswith(tok):
                return True
            return False
        text_matches = [t for t in direction["listing_tags"] if any(_tag_matches(t, tok) for tok in free_text_tokens)]
        pct = min(97, pct + (len(text_matches) * 6))
        pct = max(20, pct)
        related_count = sum(1 for tags in all_listing_tags if any(t in direction["listing_tags"] for t in tags))
        results.append({**direction, "pct": pct, "text_matches": text_matches, "related_count": related_count})
    # Secondary sort key on evidence count, not just pct - found a
    # real tie in the curated data itself (Social Impact & Nonprofit
    # and Sales & Business Development share identical dims values),
    # which combined with the 97 ceiling meant two directions with
    # genuinely different amounts of supporting free-text evidence
    # could display the same score and then rank in arbitrary
    # insertion order. This breaks ties using real evidence instead,
    # without changing any displayed percentage - a person with more
    # text_matches toward one direction sees it ranked first, not
    # whichever happened to be defined earlier in the list.
    return sorted(results, key=lambda d: (-d["pct"], -len(d["text_matches"])))
 
 
def explain_direction_deep(anthropic_client, direction: dict, answers: dict) -> str:
    prompt = (
        f"Someone doesn't yet know what career direction to pursue. They described what energizes them: "
        f"people-facing work rated {answers.get('people')}/3, data/analytical work rated {answers.get('data')}/3, "
        f"creative work rated {answers.get('creative')}/3, structured/process work rated {answers.get('structure')}/3. "
        f"They also said, in their own words: \"{answers.get('free_text', '')}\".\n\n"
        f"A suggested direction: \"{direction['title']}\" - {direction['description']}\n\n"
        "Write a genuine, specific 3-4 sentence case for why this direction could fit THEM based on what "
        "they described - reference their actual words where relevant. Then give one concrete, low-commitment "
        "first step they could take this week to test whether it actually fits (not 'research the field' - "
        "something specific and doable). Be honest about the real fit, even if that means saying it's a poor "
        "match, not just a partial one - the rating scale behind this can genuinely produce a weak match, and "
        "straining to find something positive to say when the honest answer is that it doesn't fit well "
        "would be worse than just saying so plainly."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
