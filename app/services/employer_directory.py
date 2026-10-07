"""Finding employers' job feeds - which companies to read, on which hiring system.
 
Three free ways, all automatic:
 
1. A small starter list (below) of well-known employers, so the first day isn't
   empty. Every entry is checked on its first read: a wrong one simply comes back
   "not found" and is never asked for again.
2. Links we already have: every apply link in the listings table and in the
   SimplifyJobs internship / new-grad lists that points at a hiring system
   (boards.greenhouse.io/<company>, jobs.lever.co/<company>, ...) names a feed.
3. The Common Crawl URL index - a free, public index of the web's pages - lists
   the career-page addresses on each hiring system, so every company with a
   public careers page there can be found. It is read a page at a time, slowly,
   in the background.
 
New employers wait as 'new' until the crawler reads them once; that first read
decides whether they're live, empty or gone.
"""
import json
import re
from datetime import datetime, timedelta
from urllib.parse import unquote
 
# ------------------------------------------------------------------ links -> feeds
_RESERVED = {
    "greenhouse": {"embed", "v1", "api", "jobs", "job_app", "careers", "static", "assets", "favicon.ico", "robots.txt", "sitemap.xml", "boards"},
    "lever": {"api", "v0", "v1", "jobs", "static", "assets", "favicon.ico", "robots.txt", "sitemap.xml", "search"},
    "ashby": {"api", "embed", "static", "assets", "favicon.ico", "robots.txt", "sitemap.xml", "jobs"},
    "workable": {"api", "j", "careers", "static", "assets", "favicon.ico", "robots.txt", "sitemap.xml", "jobs", "oauth"},
    "smartrecruiters": {"api", "oneclick-ui", "sr-jobs", "ui", "assets", "static", "favicon.ico", "robots.txt", "sitemap.xml", "jobs", "public"},
    "recruitee": {"www", "app", "api", "careers", "support", "blog", "help", "status", "docs", "cdn", "assets", "static", "mail", "go", "s3", "integrations", "marketplace"},
}
_URL_RES = [
    ("greenhouse", re.compile(r"(?:https?://)?(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/embed/job_(?:board|app)[^\s\"'<>)]*?[?&]for=([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"(?:https?://)?(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"(?:https?://)?jobs\.(eu\.)?lever\.co/([A-Za-z0-9._-]+)", re.I)),
    ("ashby", re.compile(r"(?:https?://)?jobs\.ashbyhq\.com/([^/?#\s\"'<>)]+)", re.I)),
    ("workable", re.compile(r"(?:https?://)?apply\.workable\.com/([A-Za-z0-9_-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:https?://)?(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
    ("recruitee", re.compile(r"(?:https?://)?([a-z0-9][a-z0-9-]{1,62})\.recruitee\.com", re.I)),
]
_SLUG_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._&'-]{0,99}$")
 
 
def clean_slug(ats, raw):
    """The feed name as the hiring system's API wants it, or None if it can't be one."""
    if not isinstance(raw, str):
        return None
    s = unquote(raw).strip().strip("/")
    if ats != "ashby":
        s = s.strip()
    if not s or not _SLUG_OK.match(s) or s.lower() in _RESERVED.get(ats, set()):
        return None
    if ats in ("greenhouse", "lever", "workable", "recruitee"):
        s = s.lower()
    if ats != "ashby" and " " in s:
        return None
    return s
 
 
def boards_in_text(text) -> set:
    """Every (hiring system, feed name) a piece of text links to."""
    found = set()
    if not isinstance(text, str) or not text:
        return found
    for ats, rx in _URL_RES:
        for m in rx.finditer(text):
            if ats == "lever":
                slug = clean_slug(ats, m.group(2))
                if slug:
                    found.add((ats, ("eu/" + slug) if m.group(1) else slug))
                continue
            slug = clean_slug(ats, m.group(1))
            if slug:
                found.add((ats, slug))
    return found
 
 
# ------------------------------------------------------------------ starter list
# Best-effort feed names of well-known US employers on each system. Verified on first read.
SEED = {
    "greenhouse": [
        "airbnb", "stripe", "coinbase", "robinhood", "lyft", "pinterest", "dropbox", "reddit", "discord", "figma", "databricks",
        "cloudflare", "gitlab", "twilio", "instacart", "asana", "squarespace", "gusto", "brex", "chime", "affirm", "sofi",
        "airtable", "mongodb", "datadog", "hashicorp", "elastic", "okta", "samsara", "rubrik", "peloton", "duolingo",
        "grammarly", "webflow", "roblox", "epicgames", "twitch", "spacex", "andurilindustries", "scaleai", "anthropic",
        "flexport", "faire", "carta", "checkr", "lattice", "mercury", "retool", "vanta", "verkada", "wealthfront",
        "betterment", "nerdwallet", "opendoor", "etsy", "toast", "klaviyo", "cockroachlabs", "confluent", "riotgames",
        "tripadvisor", "yext", "oscar", "noom", "headspace", "strava", "nextdoor", "thumbtack", "gopuff", "glossier",
        "allbirds", "warbyparker", "bombas", "renttherunway", "sweetgreen", "zocdoc", "betterup", "attentive", "braze",
        "amplitude", "mixpanel", "segment", "pagerduty", "newrelic", "sumologic", "fastly", "netlify", "postman", "sentry",
        "grafanalabs", "cohere", "huggingface", "runwayml", "jasper", "benchling", "tempus", "flatironhealth", "zipline",
        "nuro", "aurora", "waymo", "cruise", "rivian", "lucidmotors", "joby", "relativity", "axiomspace", "planetlabs",
        "astranis", "hermeus", "shieldai", "palantir", "aledade", "devoted", "cityblock", "included", "spotifyusa",
        "doordashusa", "block", "squareup", "nianticlabs", "unity3d", "zynga", "wbgames", "bungie", "neuralink",
    ],
    "lever": [
        "plaid", "palantir", "spotify", "netflix", "kraken", "eventbrite", "highspot", "outreach", "zoox", "shield-ai",
        "verily", "applied", "sigmacomputing", "dnb", "attentive", "atlassian", "matterport", "cars", "anyscale", "voleon",
        "wealthsimple", "ro", "headway", "tala", "aircall", "sword", "hive", "skydio", "relativityspace", "mux", "whoop",
        "levelai", "fivetran", "earnin", "brightwheel", "watershed", "rokt", "pipedrive", "jumpcloud", "found",
    ],
    "ashby": [
        "openai", "ramp", "notion", "linear", "vercel", "zapier", "replit", "deel", "posthog", "supabase", "clerk",
        "modal", "perplexity", "harvey", "mistral", "elevenlabs", "pinecone", "weaviate", "cursor", "anysphere",
        "sierra", "decagon", "hebbia", "glean", "writer", "character", "suno", "pika", "together-ai", "baseten",
        "fireworks-ai", "lambda", "crusoe", "coreweave", "chainguard", "snyk", "wiz", "vanta", "drata", "mercor",
    ],
    "smartrecruiters": [
        "Visa", "ServiceNow", "BoschGroup", "Equinox", "Ubisoft2", "WesternDigital", "Square", "Sephora", "Abercrombie",
        "Ulta", "Experian", "Colliers", "Wix", "Canva",
    ],
    "workable": [],
    "recruitee": [],
}
 
 
def seed_pairs() -> set:
    out = set()
    for ats, slugs in SEED.items():
        for s in slugs:
            c = clean_slug(ats, s)
            if c:
                out.add((ats, c))
    return out
 
 
# ------------------------------------------------------------------ SimplifyJobs lists
SIMPLIFY_LISTS = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
)
 
 
def boards_from_simplify(fetcher) -> set:
    found = set()
    for url in SIMPLIFY_LISTS:
        r = fetcher.get_text(url)
        if r.status == "ok" and isinstance(r.data, str):
            found |= boards_in_text(r.data)
    return found
 
 
# ------------------------------------------------------------------ Common Crawl URL index
CC_COLLINFO = "https://index.commoncrawl.org/collinfo.json"
CC_PATTERNS = (
    ("greenhouse", "boards.greenhouse.io/*"),
    ("greenhouse", "job-boards.greenhouse.io/*"),
    ("lever", "jobs.lever.co/*"),
    ("ashby", "jobs.ashbyhq.com/*"),
    ("workable", "apply.workable.com/*"),
    ("smartrecruiters", "jobs.smartrecruiters.com/*"),
    ("recruitee", "*.recruitee.com"),
)
CC_REFRESH_DAYS = 30
 
 
def cc_fresh_cursor(fetcher):
    """Start over on the newest crawl's index. None when the index can't be read now."""
    r = fetcher.get_json(CC_COLLINFO)
    if r.status != "ok" or not isinstance(r.data, list) or not r.data:
        return None
    newest = r.data[0] if isinstance(r.data[0], dict) else None
    if not newest or not newest.get("cdx-api"):
        return None
    return {"index": newest.get("id"), "api": newest["cdx-api"], "p": 0, "page": 0, "pages": None,
            "started": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "done": False, "found": 0}
 
 
def cc_due(cursor) -> bool:
    if not isinstance(cursor, dict) or not cursor.get("api"):
        return True
    if not cursor.get("done"):
        return True
    try:
        fin = datetime.strptime(cursor.get("finished") or "", "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return True
    return datetime.utcnow() - fin > timedelta(days=CC_REFRESH_DAYS)
 
 
def cc_step(fetcher, cursor, deadline_monotonic, now_monotonic):
    """Read index pages until the deadline. Returns (found pairs, new cursor). Never raises."""
    found = set()
    try:
        if cc_due(cursor) and (not isinstance(cursor, dict) or cursor.get("done") or not cursor.get("api")):
            cursor = cc_fresh_cursor(fetcher)
            if cursor is None:
                return found, None
        while not cursor.get("done") and now_monotonic() < deadline_monotonic:
            if cursor["p"] >= len(CC_PATTERNS):
                cursor["done"] = True
                cursor["finished"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                break
            ats, pattern = CC_PATTERNS[cursor["p"]]
            base = cursor["api"] + "?url=" + pattern + "&output=json&fl=url"
            if cursor.get("pages") is None:
                r = fetcher.get_text(base + "&showNumPages=true")
                if r.status != "ok":
                    break
                try:
                    cursor["pages"] = int(json.loads(r.data.strip().splitlines()[0]).get("pages") or 0)
                except (ValueError, IndexError, AttributeError):
                    cursor["pages"] = 0
                cursor["page"] = 0
            if cursor["page"] >= (cursor["pages"] or 0):
                cursor["p"] += 1
                cursor["pages"], cursor["page"] = None, 0
                continue
            r = fetcher.get_text(base + "&page=%d" % cursor["page"])
            if r.status == "dead":
                cursor["page"] += 1
                continue
            if r.status != "ok":
                break
            for line in r.data.splitlines():
                try:
                    url = json.loads(line).get("url")
                except (ValueError, AttributeError):
                    continue
                for pair in boards_in_text(url or ""):
                    if pair[0] == ats or ats == "lever" and pair[0] == "lever":
                        found.add(pair)
            cursor["page"] += 1
        cursor["found"] = int(cursor.get("found") or 0) + len(found)
        return found, cursor
    except Exception:
        return found, cursor
 
