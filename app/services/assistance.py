"""Real, live web search for credible tutors or coaches - grounded in
an actual skill gap or athletic need and a real, stated budget, not
generic "how to find a tutor" advice. Mirrors research_company's
exact pattern in market_research.py: report only what's genuinely
found through search, say plainly when nothing credible turns up
within budget rather than inventing an option or a price.
"""
 
 
def find_assistance_options(anthropic_client, need_description: str, budget: str, location_context: str = "") -> dict:
    location_line = f' Location/context: "{location_context}".' if location_context else ""
    prompt = (
        f'Search the web for real, credible tutors or coaches who could genuinely help with: '
        f'"{need_description}".\nBudget: "{budget}".{location_line}\n\n'
        "Find real people, services, or platforms (e.g. real tutoring marketplaces, real coaching "
        "services, real individual tutors/coaches with an online presence) that genuinely fit this "
        "specific need and budget - not generic advice about \"how to find a tutor.\" If you find "
        "genuinely relevant, real options, list up to 4, each with: their name, what makes them a real "
        "fit for this specific need, and their real, approximate cost if you can find it. If you "
        "genuinely cannot find real, credible options that fit the stated budget, say so honestly "
        "rather than suggesting something that doesn't actually fit - do not invent options or prices "
        "you have not found. Keep it concise."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=800,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    # getattr (not b.type directly), matching the sources loop below: a content
    # block without a .type attribute would otherwise crash this extraction with
    # an AttributeError while the sources loop stayed safe - an inconsistency,
    # and needless fragility for a shared helper.
    findings = "".join(
        (getattr(b, "text", "") or "")
        for b in resp.content
        if getattr(b, "type", None) == "text"
    ).strip()
 
    sources = []
    for block in resp.content:
        if getattr(block, "type", None) == "web_search_tool_result":
            for item in getattr(block, "content", []) or []:
                url = getattr(item, "url", None)
                title = getattr(item, "title", None)
                if url:
                    sources.append({"url": url, "title": title or url})
 
    return {"findings": findings, "sources": sources}
 
