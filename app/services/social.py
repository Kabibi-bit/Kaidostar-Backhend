"""Waypoint: a private progress journal, not a social feed.
 
Generalized to work across all 4 roles, not just candidates. This
used to include connection suggestions and a cross-user feed ranked
by goal relevance. That was cut deliberately: a feed and a connection
system only have real value once there are enough real users for
either to mean something, and a connection feature between real
people carries a genuine moderation/safety workload (spam, fake
profiles, harassment, abuse reports) that isn't worth taking on for a
feature with no real users behind it yet.
 
What's left, and what this file does:
1. reflect_on_journal_entry() - a real, specific reflection on ONE
   entry.
2. reflect_on_entry_pattern() - the more valuable piece: a real
   reflection across SEVERAL recent entries at once. A single-entry
   reflection can only restate what was just written back at the
   person; a pattern across entries can surface something they
   wouldn't have noticed themselves.
 
Both take a generic `focus` (the person's stated goal) and
`context_summary` (a roadmap summary) - kept generic from when this
briefly supported other roles, though candidate is genuinely the
only one left now.
"""
 
 
def reflect_on_journal_entry(anthropic_client, focus: str, context_summary: str | None, entry_body: str, tag_label: str | None) -> str:
    tag_line = f"They tagged this entry to: \"{tag_label}\".\n" if tag_label else ""
    prompt = (
        f"A person's goal or focus: \"{focus}\". Their current strategy or context: \"{context_summary or 'none stated yet'}\".\n"
        f"{tag_line}\n"
        f"A journal entry they just wrote about their progress:\n\"{entry_body or ''}\"\n\n"
        "In 2-3 sentences, give an honest, specific reflection - does this genuinely represent progress "
        "toward their stated goal, is there a real risk or blind spot worth naming, or a concrete next "
        "step implied by what they wrote? Reference their actual goal or tag by name. Avoid generic "
        "encouragement like 'great job' or 'keep it up' - be specific or say nothing complimentary at all."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
 
def reflect_on_entry_pattern(anthropic_client, focus: str, context_summary: str | None, entries: list[dict]) -> str:
    """entries: list of {"body": str, "tag_label": str | None}, most
    recent first. The genuinely more valuable reflection - looks
    across several entries together instead of one at a time.
    """
    entries_text = "\n".join(
        f"{i+1}. {'[' + e['tag_label'] + '] ' if e.get('tag_label') else ''}{e.get('body') or ''}"
        for i, e in enumerate(entries)
    )
    prompt = (
        f"A person's goal or focus: \"{focus}\". Their current strategy or context: \"{context_summary or 'none stated yet'}\".\n\n"
        f"Their last {len(entries)} journal entries, most recent first:\n{entries_text}\n\n"
        "Look across ALL of these entries together - not one at a time - and give an honest, specific "
        "pattern reflection in 3-4 sentences. Is there a recurring blocker or theme they may not have "
        "noticed themselves? Is progress actually happening, stalling, or scattered across unrelated "
        "things? Reference specific entries or their actual goal by name. Do not just summarize what they "
        "wrote - say something they couldn't have gotten from re-reading their own entries."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=250,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
