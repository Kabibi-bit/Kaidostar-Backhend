"""Small shared pieces for jobs that come straight from employers' career sites.
 
Those jobs live in the same `listings` table as everything else (so saving,
dismissing, applying, Auto and alerts all work on them unchanged), with two
differences that keep a free 500 MB database able to hold a lot of them:
 
  * the posting text is stored zlib-compressed in `listings.body_z`, and
    `listings.description` is left empty - so anything that needs the text
    reads it through listing_text() below;
  * the older all-listings code paths (the v1 ranking, roadmap, chat, mission
    and similar) skip them with not_feed() - those paths load every listing
    into memory, which is fine for a few thousand board listings and would not
    be for a few hundred thousand employer jobs.
 
This module imports nothing heavy, so any route can use it.
"""
import zlib
from datetime import date, datetime, timedelta
 
# One `listings.source` value per employer hiring system we read.
FEED_SOURCES = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "usajobs")
 
# The most text either engine ever scores (job_search.DESC_LIMIT) - nothing past it is stored.
TEXT_LIMIT = 12000
 
 
def compress_text(text) -> bytes | None:
    if not isinstance(text, str) or not text:
        return None
    return zlib.compress(text[:TEXT_LIMIT].encode("utf-8"), 9)
 
 
def decompress_text(blob) -> str:
    """The stored posting text, or "" when there is none or it can't be read."""
    if blob is None:
        return ""
    try:
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        return zlib.decompress(bytes(blob)).decode("utf-8", "replace")
    except Exception:
        return ""
 
 
def is_feed_source(source) -> bool:
    return isinstance(source, str) and source.strip().lower() in FEED_SOURCES
 
 
def not_feed(listing_model):
    """A SQLAlchemy filter that keeps only listings that did NOT come from an
    employer feed: `db.query(Listing).filter(not_feed(Listing))`."""
    return listing_model.source.notin_(FEED_SOURCES)
 
 
def listing_text(db, listing) -> str:
    """The posting text of a Listing row, wherever it is stored. Employer-feed
    rows keep it compressed in body_z (not mapped on the model), so it is read
    with one small query; every other row has it in `description`."""
    if listing is None:
        return ""
    desc = getattr(listing, "description", None)
    if desc:
        return desc
    if not is_feed_source(getattr(listing, "source", None)) or db is None:
        return desc or ""
    try:
        from sqlalchemy import text
        # a savepoint: if the column isn't there yet (migration not run), only this read is undone -
        # never whatever the caller already has pending in the same session
        with db.begin_nested():
            blob = db.execute(text("SELECT body_z FROM listings WHERE id = :id"), {"id": str(listing.id)}).scalar()
        return decompress_text(blob)
    except Exception:
        return ""
 
 
def _skills_in(listing, text) -> list:
    """The skills the job engine reads in a posting's text - the same ones its card shows."""
    if not text:
        return []
    try:
        from app.services import job_engine as JE
        job = JE.parse_job({"id": str(getattr(listing, "id", "")), "title": getattr(listing, "title", "") or "", "org": getattr(listing, "org", "") or "",
                            "location": getattr(listing, "location", "") or "", "description": text, "type": getattr(listing, "type", "") or "job"})
        return [str(s.get("name") or "").lower() for s in (job.get("skills") or []) if s.get("name")][:25]
    except Exception:
        return []
 
 
def listing_tags(db, listing, text=None) -> list:
    """A listing's keyword tags. Board listings carry them from ingestion; employer-feed jobs
    don't (tagging hundreds of thousands of jobs with an AI call would cost real money), so for
    them the skills the job engine reads in the posting stand in - the same skills its card shows.
    Pass `text` when the posting text is already in hand, to save reading it twice."""
    tags = list(getattr(listing, "tags", None) or [])
    if tags or listing is None or not is_feed_source(getattr(listing, "source", None)):
        return tags
    body = text if isinstance(text, str) and text else listing_text(db, listing)
    return _skills_in(listing, body)
 
 
def tags_by_listing(db, listings) -> dict:
    """listing_tags for many listings at once ({listing id: tags}), reading every employer-feed
    job's text in one query rather than one query each."""
    out, feed = {}, []
    for l in listings or []:
        if l is None:
            continue
        tags = list(getattr(l, "tags", None) or [])
        if tags or not is_feed_source(getattr(l, "source", None)):
            out[str(l.id)] = tags
        else:
            feed.append(l)
    if feed:
        texts = {}
        if db is not None:
            try:
                from sqlalchemy import text as sql
                with db.begin_nested():
                    rows = db.execute(sql("SELECT id, body_z FROM listings WHERE id = ANY(CAST(:ids AS uuid[]))"),
                                      {"ids": [str(l.id) for l in feed]}).fetchall()
                texts = {str(r[0]): decompress_text(r[1]) for r in rows}
            except Exception:
                texts = {}
        for l in feed:
            out[str(l.id)] = _skills_in(l, texts.get(str(l.id), ""))
    return out
 
 
def _closed_info(closed_at, deadline):
    """{"at": when, "why": "unconfirmed" | "deadline"} for an employer-feed job Kaidostar can no
    longer vouch for as open, else None. Its closing date counts the way the job pool counts it - a
    day's grace for time zones - so a job hidden from the pool is never sent either."""
    if closed_at is not None:
        return {"at": closed_at, "why": "unconfirmed"}
    d = deadline.date() if isinstance(deadline, datetime) else deadline
    if isinstance(d, date) and d < (datetime.utcnow() - timedelta(days=1)).date():
        return {"at": d, "why": "deadline"}
    return None
 
 
def closed_note(info, sent=True) -> str:
    """What to tell a person about an application for a job that may have closed. sent=True: this is
    why it wasn't sent just now. sent=False: a standing heads-up that claims no cause (the
    application may have been handed back earlier for another reason)."""
    info = info if isinstance(info, dict) else {"at": info, "why": "unconfirmed"}
    at = info.get("at")
    when = f"{at:%b} {at.day}" if hasattr(at, "day") else ""
    if info.get("why") == "deadline":
        return (f"This job's closing date{' (' + when + ')' if when else ''} has passed"
                + (", so Kaidostar didn't send your application." if sent else " - check the posting before you submit."))
    since = f" since {when}" if when else ""
    if sent:
        return (f"Kaidostar hasn't been able to confirm this job is still open on the employer's site{since}, so it didn't send it. "
                "If the posting is still up, you can submit your application there yourself.")
    return (f"Heads up: Kaidostar hasn't been able to confirm this job is still open on the employer's site{since}. "
            "Check that the posting is still up before you submit.")
 
 
def closed_draft_message(info) -> str:
    """Why no new application is drafted for a job that may have closed."""
    if isinstance(info, dict) and info.get("why") == "deadline":
        return "This job's closing date has passed, so Kaidostar won't draft an application for it."
    return "Kaidostar can no longer confirm this job is open on the employer's site, so it won't draft an application for it."
 
 
def closed_by_listing(db, listings) -> dict:
    """{listing id: closed info (see _closed_info)} for the employer-feed jobs among `listings` that
    Kaidostar can no longer vouch for as open - one query for all of them; open jobs and every other
    listing are left out."""
    ids = [str(l.id) for l in listings or [] if l is not None and is_feed_source(getattr(l, "source", None))]
    if not ids or db is None:
        return {}
    try:
        from sqlalchemy import text
        with db.begin_nested():
            rows = db.execute(text("SELECT id, closed_at, deadline FROM listings WHERE id = ANY(CAST(:ids AS uuid[])) "
                                   "AND (closed_at IS NOT NULL OR deadline < :cut)"),
                              {"ids": ids, "cut": (datetime.utcnow() - timedelta(days=1)).date()}).fetchall()
        out = {}
        for r in rows:
            info = _closed_info(r[1], r[2])
            if info:
                out[str(r[0])] = info
        return out
    except Exception:
        return {}
 
 
def listing_closed(db, listing):
    """Closed info (see _closed_info) when Kaidostar can no longer vouch that an employer-feed job is
    open - its employer's feed stopped listing it, the feed couldn't be read for days, or its closing
    date passed - else None; always None for every other listing. (closed_at isn't mapped on the
    model, so it is read with one small query.)"""
    if listing is None or db is None or not is_feed_source(getattr(listing, "source", None)):
        return None
    try:
        from sqlalchemy import text
        with db.begin_nested():
            row = db.execute(text("SELECT closed_at, deadline FROM listings WHERE id = :id"), {"id": str(listing.id)}).fetchone()
        return _closed_info(row[0], row[1]) if row else None
    except Exception:
        return None
