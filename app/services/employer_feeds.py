"""Employer career-site feeds: jobs read straight from the hiring systems employers
post them in - the same public feeds their own careers pages are built from.
 
Every source here is free, public and needs no key (USAJOBS needs a free one):
 
  Greenhouse       boards-api.greenhouse.io/v1/boards/{slug}/jobs        list, then one call per new job
  Lever            api.lever.co/v0/postings/{slug}?mode=json             paged, full text
  Ashby            api.ashbyhq.com/posting-api/job-board/{slug}          full text
  SmartRecruiters  api.smartrecruiters.com/v1/companies/{slug}/postings  list, then one call per new job
  Workable         www.workable.com/api/accounts/{slug}?details=true     full text
  Recruitee        {slug}.recruitee.com/api/offers/                      full text
  USAJOBS          data.usajobs.gov/api/search                           public-hiring federal jobs (free key)
 
Why these and not job boards: each job is the employer's own posting, with its
full text (so Proof Match reads every requirement), a direct apply link, and
the employer's own posting date. A board that no longer lists a job means the
job is closed - so closed jobs leave Kaidostar the next day.
 
Manners: robots.txt is read and obeyed for every host, requests to one host are
spaced out, every request names Kaidostar in its User-Agent, and a feed that
says "slow down" (429 / 503) is left alone for a while.
 
This module only fetches and reads. Storing, scheduling and the storage budget
live in feed_crawler.py; finding employers lives in employer_directory.py.
"""
import hashlib
import html as html_lib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit
 
from app.services.feed_common import TEXT_LIMIT
 
UA = "KaidostarBot/1.0 (+https://kaidostar-frontend.onrender.com; job search for candidates)"
UA_TOKEN = "KaidostarBot"
MAX_BYTES = int(os.getenv("FEED_MAX_RESPONSE_MB", "8")) * 1024 * 1024    # one response; a bigger board is skipped, not risked (512 MB plans)
HOST_GAP_S = 0.35                    # at least this long between two requests to the same host
HOST_GAPS = {"index.commoncrawl.org": 2.0, "data.usajobs.gov": 1.0}   # slower for shared public services
MAX_AGE_DAYS = int(os.getenv("FEED_MAX_AGE_DAYS", "90"))   # older postings are almost always stale or evergreen
LEVER_PAGE = 100
SR_PAGE = 100
USAJOBS_PAGE = 500
 
INTERN_RE = re.compile(r"(?<![a-z])(intern|interns|internship|internships|co-op|co-ops|coop)(?![a-z])", re.I)
 
 
# ------------------------------------------------------------------ text
_BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "ul", "ol", "table", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
               "blockquote", "pre", "dl", "dt", "dd", "figure", "main", "aside", "hr", "tbody", "thead"}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "head", "title"}
 
 
class _TextOut(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0
 
    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in _SKIP_TAGS:
            self.skip += 1
        elif self.skip:
            return
        elif t == "br":
            self.parts.append("\n")
        elif t == "li":
            self.parts.append("\n- ")
        elif t in _BLOCK_TAGS:
            self.parts.append("\n")
        elif t in ("td", "th"):
            self.parts.append(" ")
 
    def handle_startendtag(self, tag, attrs):
        if tag.lower() not in _SKIP_TAGS:
            self.handle_starttag(tag, attrs)
 
    def handle_endtag(self, tag):
        t = tag.lower()
        if t in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and (t in _BLOCK_TAGS or t == "li"):
            self.parts.append("\n")
 
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
 
 
def tidy_text(s) -> str:
    """Plain text with one line per block, "- " bullets, no runs of blank lines."""
    if not isinstance(s, str):
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ").replace("​", "")
    lines = []
    for raw in s.split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", raw).strip()
        line = re.sub(r"^[•●▪◦‣∙·]\s*", "- ", line)
        if line in ("-", "- "):
            continue
        lines.append(line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    # bullets of one list stay together, and a short heading sits right above what it heads
    out = re.sub(r"(?m)^(- [^\n]*)\n\n(?=- )", r"\1\n", out)
    out = re.sub(r"(?m)^(- [^\n]*)\n\n(?=- )", r"\1\n", out)
    out = re.sub(r"(?m)^([^\n.!?]{2,70}:?)\n\n(?=\S)", lambda m: m.group(1) + "\n" if not m.group(1).startswith("- ") else m.group(0), out)
    return out
 
 
def html_to_text(markup, escaped: bool = False) -> str:
    """HTML (Greenhouse sends it entity-escaped) to the plain text both engines read."""
    if not isinstance(markup, str) or not markup.strip():
        return ""
    if escaped:
        markup = html_lib.unescape(markup)
    p = _TextOut()
    try:
        p.feed(markup)
        p.close()
    except Exception:
        return tidy_text(re.sub(r"<[^>]+>", "\n", markup))
    return tidy_text("".join(p.parts))
 
 
def join_sections(parts) -> str:
    """[(heading or None, text)] -> one text, each section under its heading."""
    out = []
    for head, body in parts:
        body = tidy_text(body)
        if not body:
            continue
        out.append((head.strip() + "\n" + body) if head else body)
    return tidy_text("\n\n".join(out))[:TEXT_LIMIT]
 
 
# ------------------------------------------------------------------ values
def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""
 
 
def parse_dt(v, future_ok: bool = False):
    """A source timestamp as naive UTC, or None when it's missing, garbled, before 2000 or (unless
    future_ok - a closing date) in the future."""
    dt = None
    try:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            secs = v / 1000.0 if v > 1e11 else float(v)
            dt = datetime.fromtimestamp(secs, tz=timezone.utc)
        elif isinstance(v, str) and v.strip():
            t = v.strip()
            if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", t):
                dt = datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            else:
                t = t.replace("Z", "+00:00").replace("z", "+00:00")
                t = re.sub(r"(\.[0-9]{6})[0-9]+", r"\1", t)          # nanoseconds -> microseconds
                t = re.sub(r"([+-][0-9]{2})([0-9]{2})$", r"\1:\2", t)  # +0000 -> +00:00
                dt = datetime.fromisoformat(t)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.utcnow()
    if dt.year < 2000 or (dt > now + timedelta(days=1) and not future_ok) or dt.year > now.year + 5:
        return None
    return dt
 
 
_PERIODS = {
    "year": "year", "yearly": "year", "annual": "year", "annually": "year", "per-year-salary": "year", "1 year": "year", "salary": "year",
    "month": "month", "monthly": "month", "per-month-salary": "month", "1 month": "month",
    "week": "week", "weekly": "week", "per-week-salary": "week", "1 week": "week",
    "day": "day", "daily": "day", "per-day-wage": "day", "1 day": "day",
    "hour": "hour", "hourly": "hour", "per-hour-wage": "hour", "1 hour": "hour", "ph": "hour", "pa": "year", "pm": "month", "pw": "week", "pd": "day",
}
 
 
def pay(lo, hi, currency, period):
    """(min, max, period) in whole US dollars - or (None, None, None). Only USD,
    only a known period, never a guess."""
    if _s(currency).upper() not in ("USD", "US$", "$"):
        return None, None, None
    per = _PERIODS.get(_s(period).lower())
    if not per:
        return None, None, None
 
    def num(x):
        try:
            if isinstance(x, bool) or x is None:
                return None
            f = float(x)
            return int(round(f)) if f > 0 else None
        except (TypeError, ValueError):
            return None
    a, b = num(lo), num(hi)
    if a is not None and b is not None and a > b:
        a, b = b, a
    top = {"hour": 2000, "day": 20000, "week": 100000, "month": 400000, "year": 5000000}[per]
    a = a if (a is not None and a <= top) else None
    b = b if (b is not None and b <= top) else None
    if a is None and b is None:
        return None, None, None
    return a, b, per
 
 
def kind_of(title, employment_hint=""):
    """('job' | 'internship', employment_type, contract_type) from the title and the feed's own type field."""
    hint = _s(employment_hint).lower().replace("-", "").replace("_", "").replace(" ", "")
    intern = bool(INTERN_RE.search(_s(title))) or hint in ("intern", "internship", "internships", "traineeship", "coop")
    emp = con = None
    if "parttime" in hint:
        emp = "part_time"
    elif "fulltime" in hint:
        emp = "full_time"
    # "full-time" says nothing about permanence - only a word that does is used
    if any(k in hint for k in ("contract", "freelance", "temporary", "fixedterm", "seasonal")) and "permanent" not in hint:
        con = "contract"
    elif "permanent" in hint or hint == "regular":
        con = "permanent"
    return ("internship" if intern else "job"), emp, con
 
 
def sig_of(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p if isinstance(p, str) else json.dumps(p, sort_keys=True, default=str)).encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]
 
 
def pretty_company(slug) -> str:
    """A readable company name from a feed slug ("acme-robotics" -> "Acme Robotics") - used
    only when the feed itself doesn't say the name."""
    s = re.sub(r"[-_.]+", " ", _s(slug)).strip()
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    return " ".join(w if (w.isupper() and len(w) <= 4) else w.capitalize() for w in s.split()) or _s(slug)
 
 
# ------------------------------------------------------------------ US only
# Countries / regions: naming one rules a place out, even next to a US-looking city ("Cambridge, England") - but not
# a US state named after one ("New Mexico", "New England"), and not a US town named after one when the place ends in
# a US state that isn't that country's own code ("Holland, MI", "Peru, IN", "Mexico, MO" - see _us_state_tail).
_ABROAD_STRONG = re.compile(
    r"(?<![a-z])(canada|canadian|ontario|quebec|british columbia|alberta|manitoba|saskatchewan|nova scotia|united kingdom|uk|u\.k\.|"
    r"(?<!new )england|scotland|wales|northern ireland|britain|great britain|ireland|germany|deutschland|france|netherlands|holland|"
    r"belgium|spain|portugal|italy|italia|poland|sweden|denmark|norway|finland|iceland|switzerland|austria|czech republic|czechia|"
    r"slovakia|romania|hungary|greece|israel|india|singapore|japan|china|hong kong|taiwan|south korea|korea|australia|new zealand|"
    r"brazil|brasil|(?<!new )mexico|(?<!new )méxico|argentina|colombia|chile|peru|uruguay|costa rica|philippines|vietnam|indonesia|"
    r"malaysia|thailand|south africa|nigeria|kenya|egypt|morocco|uae|united arab emirates|saudi arabia|qatar|turkey|türkiye|"
    r"pakistan|bangladesh|sri lanka|ukraine|serbia|croatia|slovenia|bulgaria|estonia|latvia|lithuania|luxembourg|cyprus|malta|"
    r"russia|russian federation|belarus|kazakhstan|armenia|azerbaijan|uzbekistan|moldova|albania|bosnia|montenegro|"
    r"north macedonia|kosovo|iran|iraq|kuwait|bahrain|ghana|ethiopia|tanzania|uganda|rwanda|senegal|cameroon|algeria|tunisia|"
    r"nepal|cambodia|myanmar|ecuador|bolivia|paraguay|venezuela|guatemala|honduras|el salvador|nicaragua|dominican republic|"
    r"emea|apac|latam|europe|european union|eu|asia|asia pacific|africa|middle east|oceania|anz|dach|nordics|benelux|"
    r"latin americas?|south americas?|central americas?)(?![a-z])", re.I)
# Regions abroad: a place naming one is never a US town, whatever follows it.
_ABROAD_REGION = re.compile(r"(?<![a-z])(emea|apac|latam|europe|european union|eu|asia|asia pacific|africa|middle east|oceania|anz|"
                            r"dach|nordics|benelux|latin americas?|south americas?|central americas?)(?![a-z])", re.I)
# Big cities abroad: naming one rules a place out - unless the place also names a US metro, or ends in a US state
# that isn't that city's own country or region code ("Paris, TX", "Melbourne, FL", "Athens, GA", "Warsaw, IN" are
# US towns; "Munich, DE", "Pune, IN", "Perth, WA", "Chennai, TN" are not - see _CITY_HOME_CODES).
_ABROAD_CITY = re.compile(
    r"(?<![a-z])(toronto|vancouver|montreal|montréal|ottawa|calgary|edmonton|winnipeg|waterloo, on|kitchener|mississauga|"
    r"london|manchester|birmingham, uk|edinburgh|glasgow|bristol, uk|leeds|belfast|dublin|cork|galway|berlin|munich|münchen|"
    r"hamburg|frankfurt|cologne|köln|stuttgart|düsseldorf|dusseldorf|paris|lyon|marseille|toulouse|amsterdam|rotterdam|utrecht|"
    r"eindhoven|the hague|brussels|antwerp|madrid|barcelona|valencia|seville|lisbon|porto|milan|milano|rome|roma|turin|torino|"
    r"warsaw|krakow|kraków|wroclaw|wrocław|gdansk|stockholm|gothenburg|copenhagen|oslo|helsinki|zurich|zürich|geneva|basel|"
    r"vienna|wien|prague|bucharest|cluj|budapest|athens|sofia|belgrade|zagreb|tallinn|riga|vilnius|kyiv|kiev|lviv|istanbul|"
    r"tel aviv|jerusalem|haifa|bangalore|bengaluru|hyderabad|pune|mumbai|delhi|new delhi|gurgaon|gurugram|noida|chennai|"
    r"kolkata|ahmedabad|singapore|tokyo|osaka|seoul|shanghai|beijing|shenzhen|guangzhou|taipei|hong kong|manila|cebu|jakarta|"
    r"kuala lumpur|bangkok|ho chi minh|hanoi|sydney|melbourne|brisbane|perth|adelaide|auckland|wellington|são paulo|sao paulo|"
    r"rio de janeiro|buenos aires|bogota|bogotá|medellin|medellín|santiago|lima|mexico city|ciudad de méxico|guadalajara|"
    r"monterrey|cape town|johannesburg|lagos|nairobi|cairo|dubai|abu dhabi|riyadh|doha|karachi|lahore|dhaka|colombo)(?![a-z])", re.I)
_US_WORDS_LOC = re.compile(r"(?<![a-z])(united states|united states of america|u\.s\.a\.?|u\.s\.|usa|us|north america|americas|nationwide|anywhere in the us)(?![a-z])", re.I)
_US_WORDS_TEXT = re.compile(r"(?<![a-z])(united states|u\.s\.a\.?|u\.s\.|usa|us-based|u\.s\.-based|based in the us|within the us|in the us|us only|"
                            r"us citizens?|u\.s\. citizens?|us persons?|anywhere in the us|eastern time|pacific time|central time|mountain time)(?![a-z])", re.I)
_US_TZ = re.compile(r"(?<![A-Za-z])(EST|PST|CST|MST|EDT|PDT|CDT|MDT)(?![A-Za-z])")   # capitals only: French "est" is not a time zone
_ANYWHERE = re.compile(r"(?<![a-z])(anywhere|worldwide|global|work from anywhere)(?![a-z])", re.I)
_REMOTE_WORD = re.compile(r"(?<![a-z])(remote|remotely|work from home|wfh|distributed|telework|anywhere)(?![a-z])", re.I)
_US_CODES = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA", "U.S.", "U.S.A."}
_PART_SPLIT = re.compile(r"\s*(?:;|\||/|\bor\b|\n|\s-\s(?=[A-Z][a-z]+,))\s*")
# Two-letter codes that are a US state's AND the own country or region code of a place abroad named before them:
# after one of these names the code means the place abroad ("Munich, DE" is Germany, "Perth, WA" Western Australia,
# "Bogota, DC" Colombia's capital district, "Toronto, Ontario, CA" Canada). After any other foreign city's or
# country's name, a US state means a US town of that name ("Paris, TX", "Warsaw, IN", "Holland, MI").
_HOME_CODES = {
    "DE": ("berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne", "köln", "stuttgart", "düsseldorf", "dusseldorf",
           "germany", "deutschland"),
    "IN": ("bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "new delhi", "gurgaon", "gurugram", "noida",
           "chennai", "kolkata", "ahmedabad", "india"),
    "CA": ("toronto", "vancouver", "montreal", "montréal", "ottawa", "calgary", "edmonton", "winnipeg", "waterloo",
           "kitchener", "mississauga", "london", "canada", "canadian", "ontario", "quebec", "british columbia", "alberta",
           "manitoba", "saskatchewan", "nova scotia"),
    "CO": ("bogota", "bogotá", "medellin", "medellín", "cork", "colombia"),
    "DC": ("bogota", "bogotá"),
    "AR": ("buenos aires", "argentina"),
    "IL": ("tel aviv", "jerusalem", "haifa", "israel"),
    "ID": ("jakarta", "indonesia"),
    "WA": ("perth",),
    "TN": ("chennai", "tunisia"),
    "MI": ("milan", "milano"),
    "NH": ("amsterdam",),
    "UT": ("utrecht",),
    "CT": ("barcelona",),
    "MD": ("madrid", "moldova"),
    "MA": ("krakow", "kraków", "morocco"),
    "MT": ("malta",),
    "AL": ("albania",),
    "ME": ("montenegro",),
    "LA": ("lagos",),
    "AZ": ("abu dhabi", "azerbaijan"),
    "SD": ("karachi",),
}
_HOME_RES = {c: re.compile(r"(?<![a-z])(" + "|".join(map(re.escape, names)) + r")(?![a-z])", re.I) for c, names in _HOME_CODES.items()}
# ", ST" / ", State" at the end of a place, an optional ZIP after it
_STATE_TAIL = re.compile(r",\s*([A-Za-z][A-Za-z .]{0,30}?)\s*(?:\d{5}(?:-\d{4})?)?\s*$")
# a trailing note after the place: "(Hybrid)", "[Remote]", "- On-site", ", Hybrid", "• Remote", "(HQ)"
_MODE_WORD = r"(?:fully\s+)?(?:remote|hybrid|on-?site|in[- ]office|flexible)\b\.?"
_TAIL_NOTE = re.compile(r"(?:\s*[(\[][^()\[\]]*[)\]]|\s+[-–—]\s*" + _MODE_WORD + r"|\s*[,;:•·|]\s*" + _MODE_WORD + r")+\s*$", re.I)
# a place written inside brackets: "Hybrid (Dublin, OH)", "Remote [Holland, MI]"
_BRACKET_PLACE = re.compile(r"[(\[]([^()\[\]]*,[^()\[\]]*)[)\]]")
# US place names that contain a name from abroad - not a sign of a place abroad
_US_NAMES_LIKE_ABROAD = re.compile(r"(?<![a-z])la\s+ca[nñ]ada(?:\s+flintridge)?(?![a-z])", re.I)
_LATAM_PHRASE = re.compile(r"(?<![a-z])(?:latin|south|central)\s+americas?(?![a-z])", re.I)
 
 
def _engine():
    from app.services import job_engine as JE
    return JE
 
 
# The taxonomy also knows a few metros abroad, some with a code that is also a US state's
# (Berlin "DE", Bengaluru "IN") - never US places.
_ABROAD_METROS = {"toronto", "vancouver", "london", "dublin", "berlin", "bangalore", "singapore", "sydney"}
_US_STATE_SET = None
 
 
def _abroad_metro(mid) -> bool:
    global _US_STATE_SET
    if not mid:
        return False
    if mid in _ABROAD_METROS:
        return True
    try:
        I = _engine().idx()
        if _US_STATE_SET is None:
            _US_STATE_SET = set(_engine().TAX["us_states"])
        return any(s not in _US_STATE_SET for s in I.metro[mid]["states"])
    except Exception:
        return False
 
 
def _places_of(location) -> list:
    loc = _s(location)
    if not loc:
        return []
    try:
        return _engine().parse_places(loc)
    except Exception:
        return []
 
 
def _ws(v) -> str:
    """Runs of any whitespace (a no-break space too) as one plain space."""
    return re.sub(r"\s+", " ", _s(v)).strip()
 
 
def _state_of(t):
    """The US state the place `t` ends with ("Town, ST" / "Town, State"), or None (see _us_state_tail)."""
    m = _STATE_TAIL.search(t)
    if not m:
        return None
    head, tail = t[:m.start()], m.group(1).strip().rstrip(".")
    if not head.strip() or _ABROAD_REGION.search(head):
        return None
    try:
        states = _engine().TAX["us_states"]
    except Exception:
        return None
    flat = tail.replace(".", "").replace(" ", "")
    if len(flat) == 2 and flat.upper() in states:
        code = flat.upper()
        home = _HOME_RES.get(code)
        named = _US_NAMES_LIKE_ABROAD.sub(" ", head)
        if home and home.search(named) and not (code == "CA" and named.strip().lower() == "ontario"):   # Ontario, California
            return None
        return code
    low = re.sub(r"\s+", " ", tail.lower())
    return next((c for c, n in states.items() if n == low), None)
 
 
def _us_state_tail(part):
    """The US state a "Town, ST" / "Town, State" place ends with - also when a note follows it
    ("Dublin, OH, Hybrid", "Paris, TX (HQ)") or it sits in brackets ("Hybrid (Dublin, OH)"). None when
    it ends with no US state, when what comes before names a region abroad ("EMEA"), or when the two
    letters are the own country or region code of a place abroad named before them ("Munich, DE",
    "Toronto, Ontario, CA")."""
    t = _ws(part)
    for cand in [_TAIL_NOTE.sub("", t)] + [_ws(x) for x in _BRACKET_PLACE.findall(t)]:
        st = _state_of(cand)
        if st:
            return st
    return None
 
 
def _state_places(t, places, st) -> list:
    return [p for p in places if p.get("state") == st] or [{"metro": None, "state": st, "label": t.lower()}]
 
 
def _part_read(part):
    """One place in a location list -> (verdict, the US places it names): 'us', 'no' or 'unsure'
    (remote / unknown). The one reader behind both us_verdict and the place keys, so a job is never
    judged a US job and then left without the place it is in."""
    t = _ws(part)
    if not t:
        return "unsure", []
    # (the US named outright - "Latin America" is not "America")
    us_word = bool(_US_WORDS_LOC.search(_LATAM_PHRASE.sub(" ", t)))
    places = [p for p in _places_of(t) if not _abroad_metro(p.get("metro")) and (p.get("metro") or p.get("state"))]
    if _ABROAD_STRONG.search(_US_NAMES_LIKE_ABROAD.sub(" ", t)) and not us_word:
        st = _us_state_tail(t)   # a US town named after a country ("Holland, MI") - never "Cambridge, England"
        return ("us", _state_places(t, places, st)) if st else ("no", [])
    if any(p.get("metro") for p in places) or us_word:
        return "us", places
    if _ABROAD_CITY.search(t):
        st = _us_state_tail(t)
        return ("us", _state_places(t, places, st)) if st else ("no", [])
    if any(p.get("state") for p in places):
        return "us", places
    return "unsure", []
 
 
_PART_CAP = 2000
 
 
def _parts(location) -> list:
    """The places in a location list. A runaway field is read only up to _PART_CAP characters, and a
    place cut off at that point is dropped - "Mexico City, Me..." must never read as Maine."""
    raw = _s(location)
    loc = re.sub(r"[^\S\n]+", " ", raw[:_PART_CAP]).strip()    # one plain space, line breaks kept: they separate places
    parts = [_ws(p) for p in _PART_SPLIT.split(loc) if p and p.strip()] if loc else []
    if len(raw) > _PART_CAP and len(parts) > 1:
        parts = parts[:-1]
    return parts
 
 
def us_places(location) -> list:
    """The US places a location string names (metro / state), via the engine's own reader -
    leaving out every part of the string that names a place abroad."""
    out = []
    for part in _parts(location):
        out += _part_read(part)[1]
    return out
 
 
def _part_verdict(part) -> str:
    """One place in a location list: 'us', 'no' or 'unsure' (remote / unknown)."""
    return _part_read(part)[0]
 
 
def us_verdict(location, country=None, remote=None, text_head="") -> str:
    """'us' (clearly open to someone in the US), 'no' (clearly elsewhere) or 'unsure'.
    The feed's own country code decides first; then each place in the location list (any US
    one makes it a US job); 'unsure' (bare "Remote", no place) is settled by the posting's own
    words, then by the board (feed_crawler keeps an unsure job only when the same employer also
    lists clearly-US jobs)."""
    loc = _s(location)[:4000]                # (_parts reads at most _PART_CAP of it, in whole places)
    code = _s(country).upper()[:60]
    head = _ws(_s(text_head)[:3000])
    us_text = bool(_US_WORDS_TEXT.search(head) or _US_TZ.search(head))
    is_remote = bool(remote) or bool(_REMOTE_WORD.search(loc))
    if code in _US_CODES:
        return "us"
    if code:
        # based abroad: a remote job can still be open to the US, when it says so ("Latin America" doesn't)
        if is_remote and (_US_WORDS_LOC.search(_LATAM_PHRASE.sub(" ", loc)) or _US_TZ.search(loc) or _ANYWHERE.search(loc) or us_text):
            return "us"
        return "no"
    verdicts = [_part_verdict(p) for p in _parts(loc)]
    if "us" in verdicts:
        return "us"
    if verdicts and all(v == "no" for v in verdicts):
        return "no"
    if "no" in verdicts and not is_remote:
        return "no"
    # remote, no place, or nothing we can place: what the posting itself says
    if us_text:
        return "us"
    if (_ABROAD_STRONG.search(head) or _ABROAD_CITY.search(head)) and not _US_WORDS_TEXT.search(head) and not _us_metro_in(head):
        return "no"
    return "unsure"
 
 
def _us_metro_in(text) -> bool:
    """Does free text name a US metro ("our New York and London offices")?"""
    try:
        I = _engine().idx()
        for m in I.metro_re.finditer(_s(text).lower()):
            mid = I.metro_map.get(m.group(1))
            if mid and not _abroad_metro(mid):
                return True
    except Exception:
        return False
    return False
 
 
# ------------------------------------------------------------------ index for the pool
def feed_keys(title, org, location, text, mode_hint=None, kind="job") -> list:
    """The few keys the server uses to pick a candidate's jobs out of a large pool:
    r:<role family> (what the title says the job is, exactly as the engine reads it),
    m:<metro> / s:<state> (where), w:<remote|hybrid|onsite>, t:<job|internship>.
    Only for choosing what to send - every job sent is still scored in full."""
    JE = _engine()
    keys = []
    try:
        segs = JE.segments(text or "", org or "")
        t_main = JE.title_main(title or "")
        roles = JE.find_roles(t_main) or JE.find_roles(title or "") or JE.head_noun_roles(t_main, segs)
        if not roles:
            intro = " ".join([g["low"] for g in segs if g["section"] != "about" and JE.HIRE_CUE.search(g["low"])][:2])
            roles = JE.find_roles(intro)[:1]
        for r in roles:
            keys.append("r:" + r["id"])
        mode = JE.parse_mode(location or "", segs).get("mode")
    except Exception:
        mode = None
    for p in us_places(location)[:6]:
        if p.get("metro"):
            keys.append("m:" + p["metro"])
        if p.get("state"):
            keys.append("s:" + p["state"])
    m = mode or (mode_hint if mode_hint in ("remote", "hybrid", "onsite") else None)
    if m:
        keys.append("w:" + m)
    keys.append("t:" + (kind or "job"))
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out
 
 
def mode_hint_of(value, remote_flag=None) -> str | None:
    v = _s(value).lower().replace("-", "").replace("_", "").replace(" ", "")
    if v in ("remote", "fullyremote"):
        return "remote"
    if v == "hybrid":
        return "hybrid"
    if v in ("onsite", "inoffice", "office"):
        return "onsite"
    if remote_flag is True:
        return "remote"
    return None
 
 
# ------------------------------------------------------------------ robots.txt (RFC 9309)
class RobotsRules:
    """robots.txt as RFC 9309 reads it: the group for our product token (else '*'), the
    longest matching rule wins, Allow wins a tie, '*' and a final '$' are wildcards.
    (Python's urllib.robotparser takes the first matching rule instead - not the standard.)"""
 
    def __init__(self, text, token=UA_TOKEN):
        groups, cur, last_was_agent = [], None, False
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key, val = key.strip().lower(), val.strip()
            if key == "user-agent":
                if cur is None or not last_was_agent:
                    cur = {"agents": [], "rules": []}
                    groups.append(cur)
                cur["agents"].append(val.lower())
                last_was_agent = True
            elif key in ("allow", "disallow") and cur is not None:
                cur["rules"].append((key == "allow", val))
                last_was_agent = False
            else:
                last_was_agent = False
        tok = token.lower()
        mine = [g for g in groups if any(a != "*" and (a == tok or tok.startswith(a)) for a in g["agents"])]
        if not mine:
            mine = [g for g in groups if "*" in g["agents"]]
        self.rules = []
        for g in mine:
            for allow, pat in g["rules"]:
                if pat == "":
                    continue                      # "Disallow:" with nothing = allow everything
                self.rules.append((allow, pat, self._compile(pat)))
 
    @staticmethod
    def _compile(pat):
        end = pat.endswith("$")
        body = pat[:-1] if end else pat
        rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
        return re.compile("^" + rx + ("$" if end else ""))
 
    def allows(self, url) -> bool:
        parts = urlsplit(url)
        path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        best = None
        for allow, pat, rx in self.rules:
            if rx.match(path):
                key = (len(pat), allow)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]
 
 
# ------------------------------------------------------------------ HTTP with manners
class FetchResult:
    __slots__ = ("status", "code", "data", "error", "retry_after", "sig")
 
    def __init__(self, status, code=None, data=None, error=None, retry_after=None, sig=None):
        self.status, self.code, self.data, self.error, self.retry_after = status, code, data, error, retry_after
        self.sig = sig            # a fingerprint of the raw response: an unchanged board isn't parsed again
 
 
class Fetcher:
    """One HTTP client for a crawl pass: robots.txt obeyed per host, requests to a host
    spaced HOST_GAP_S apart, responses capped at MAX_BYTES. Thread-safe."""
 
    def __init__(self, timeout_s: float = 30.0):
        import httpx
        self._httpx = httpx
        self.client = httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"},
                                   timeout=httpx.Timeout(timeout_s, connect=10.0), follow_redirects=True)
        self._lock = threading.Lock()
        self._host_locks = {}
        self._host_next = {}
        self._robots = {}
        self.requests = 0
 
    def close(self):
        try:
            self.client.close()
        except Exception:
            pass
 
    def _host_lock(self, host):
        with self._lock:
            if host not in self._host_locks:
                self._host_locks[host] = threading.Lock()
            return self._host_locks[host]
 
    def _wait_turn(self, host):
        lk = self._host_lock(host)
        with lk:
            now = time.monotonic()
            nxt = self._host_next.get(host, 0.0)
            if nxt > now:
                time.sleep(nxt - now)
            self._host_next[host] = time.monotonic() + HOST_GAPS.get(host, HOST_GAP_S)
 
    def get_text(self, url, check_robots: bool = True, accept: str = "text/plain, */*") -> FetchResult:
        """Like get_json, for text (markdown lists, the crawl index's line-per-record JSON)."""
        if check_robots:
            ok = self.allowed(url)
            if ok is None:
                return FetchResult("error", error="couldn't read the site's robots.txt just now")
            if not ok:
                return FetchResult("blocked", error="robots.txt asks crawlers not to read this")
        host = urlsplit(url).netloc.lower()
        self._wait_turn(host)
        try:
            with self.client.stream("GET", url, headers={"Accept": accept}) as r:
                self.requests += 1
                if r.status_code in (404, 410):
                    return FetchResult("dead", r.status_code)
                if r.status_code >= 300:
                    ra = None
                    try:
                        ra = int(r.headers.get("retry-after", ""))
                    except ValueError:
                        ra = None
                    return FetchResult("error", r.status_code, error="status %d" % r.status_code, retry_after=ra)
                chunks, total = [], 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        return FetchResult("too_big", r.status_code, error="response too large")
                    chunks.append(chunk)
            return FetchResult("ok", 200, b"".join(chunks).decode("utf-8", "replace"))
        except self._httpx.TimeoutException:
            return FetchResult("error", error="timed out")
        except Exception as e:
            return FetchResult("error", error=type(e).__name__)
 
    def allowed(self, url):
        """robots.txt for the URL's host: True / False, or None when it couldn't be read just now.
        A missing file (4xx) allows everything; one that can't be read (5xx / network) means
        "not now" - never "yes" (RFC 9309)."""
        parts = urlsplit(url)
        host = parts.netloc.lower()
        with self._lock:
            hit = self._robots.get(host)
        if hit is None or hit[0] < time.monotonic():
            rules = "unknown"
            try:
                self._wait_turn(host)
                r = self.client.get(parts.scheme + "://" + host + "/robots.txt", headers={"Accept": "text/plain"})
                self.requests += 1
                if 400 <= r.status_code < 500:
                    rules = "allow"
                elif r.status_code < 300:
                    rules = RobotsRules(r.text[:500_000])
            except Exception:
                rules = "unknown"
            ttl = 24 * 3600 if rules != "unknown" else 600
            hit = (time.monotonic() + ttl, rules)
            with self._lock:
                self._robots[host] = hit
        rules = hit[1]
        if rules == "allow":
            return True
        if rules == "unknown":
            return None
        try:
            return bool(rules.allows(url))
        except Exception:
            return None
 
    def get_json(self, url, headers=None, check_robots: bool = True) -> FetchResult:
        if check_robots:
            ok = self.allowed(url)
            if ok is None:
                return FetchResult("error", error="couldn't read the site's robots.txt just now")
            if not ok:
                return FetchResult("blocked", error="robots.txt asks crawlers not to read this")
        host = urlsplit(url).netloc.lower()
        self._wait_turn(host)
        try:
            with self.client.stream("GET", url, headers=headers or None) as r:
                self.requests += 1
                code = r.status_code
                if code in (404, 410):
                    return FetchResult("dead", code)
                if code in (401, 403, 451):
                    return FetchResult("blocked", code, error="the feed refused access (%d)" % code)
                if code == 429 or code >= 500:
                    ra = None
                    try:
                        ra = int(r.headers.get("retry-after", ""))
                    except ValueError:
                        ra = None
                    return FetchResult("error", code, error="the feed said to slow down or failed (%d)" % code, retry_after=ra)
                if code >= 300:
                    return FetchResult("error", code, error="unexpected status %d" % code)
                chunks, total = [], 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        return FetchResult("too_big", code, error="the feed is larger than %d MB" % (MAX_BYTES // (1024 * 1024)))
                    chunks.append(chunk)
            body = b"".join(chunks)
            del chunks
            try:
                return FetchResult("ok", code, json.loads(body.decode("utf-8", "replace")) if body else None,
                                   sig=hashlib.sha1(body).hexdigest()[:20])
            except ValueError:
                return FetchResult("error", code, error="the feed did not return JSON")
        except self._httpx.TimeoutException:
            return FetchResult("error", error="timed out")
        except Exception as e:
            return FetchResult("error", error=type(e).__name__)
 
 
class DetailBudget:
    """How many one-job detail calls this pass may still make (shared by all workers),
    optionally drawing on a parent budget too (one board's share of the pass's)."""
 
    def __init__(self, n: int, parent=None, deadline=None):
        self._n, self._lock, self._parent, self._deadline = max(0, int(n)), threading.Lock(), parent, deadline
 
    def take(self) -> bool:
        with self._lock:
            if self._n <= 0:
                return False
            if self._deadline is not None and time.monotonic() > self._deadline:
                return False
            if self._parent is not None and not self._parent.take():
                return False
            self._n -= 1
            return True
 
    @property
    def left(self) -> int:
        with self._lock:
            return self._n
 
 
# ------------------------------------------------------------------ one board, one pass
class BoardJob:
    """What a worker needs to read one board: who it is and what we already hold."""
    __slots__ = ("id", "ats", "slug", "company", "known", "skips", "budget", "now", "last_sig")
 
    def __init__(self, id, ats, slug, company, known, skips, budget, now=None, last_sig=None):
        self.id, self.ats, self.slug, self.company = id, ats, slug, company
        self.known = known or {}      # external_id -> sig of the open jobs we hold
        self.skips = skips or {}      # external_id -> sig of jobs we read and decided not to keep
        self.budget = budget
        self.now = now or datetime.utcnow()
        self.last_sig = last_sig      # the raw-feed fingerprint of the last complete read
 
 
class BoardResult:
    __slots__ = ("status", "company", "listed", "seen", "rows", "skips", "pending", "complete", "error", "retry_after", "code",
                 "sig", "unchanged", "detail_errors")
 
    def __init__(self, status="ok"):
        self.sig = None               # fingerprint of the raw feed this read saw
        self.unchanged = False        # the feed is byte-for-byte what we last read in full: nothing to do
        self.detail_errors = 0        # one-job detail calls that failed (those jobs wait, with a back-off)
        self.status = status          # ok | dead | blocked | error | too_big
        self.company = None
        self.listed = 0               # jobs the board lists in total (any country)
        self.seen = {}                # external_id -> sig: every job we keep that is on the board right now
        self.rows = []                # new or changed jobs, ready to store
        self.skips = {}               # external_id -> sig: read in full and not kept (not US, too old)
        self.pending = 0              # new jobs left for the next pass (detail budget used up)
        self.complete = False         # the whole list was read, so jobs missing from it are closed
        self.error = None
        self.retry_after = None
        self.code = None
 
 
def _unchanged(job: BoardJob, res: BoardResult, sig) -> bool:
    """The feed hasn't changed since the last complete read: keep everything as it is."""
    res.sig = sig
    if sig and job.last_sig and sig == job.last_sig:
        res.unchanged, res.complete = True, True
        res.seen, res.skips, res.listed = dict(job.known), dict(job.skips), None
        return True
    return False
 
 
def _fail(res: BoardResult, fr: FetchResult) -> BoardResult:
    res.status, res.error, res.retry_after, res.code = fr.status, fr.error, fr.retry_after, fr.code
    return res
 
 
def fit_location(location, limit=288) -> str:
    """A location as stored: a long list of places is cut at a place boundary with its US places
    first ("...; +6 more"), so the job card, the place keys and a later re-index all still see where
    in the US the job is - a plain cut could keep only the offices abroad."""
    loc = _s(location)
    if len(loc) <= limit:
        return loc
    parts = list(dict.fromkeys(_parts(loc[:4000])))
    us = [p for p in parts if _part_verdict(p) == "us"]
    ordered = us + [p for p in parts if p not in us]
    out, n = [], 0
    for p in ordered:
        add = len(p) + (2 if out else 0)
        if n + add > limit - 12:
            break
        out.append(p)
        n += add
    if not out:
        return loc[:limit]
    left = len(ordered) - len(out)
    return ("; ".join(out) + ("; +%d more" % left if left else ""))[:limit]
 
 
def _row(job: BoardJob, ext_id, title, org, location, text, apply_url, posted_at, kind_hint="", country=None, remote=None,
         mode_hint=None, salary=(None, None, None), category=None, sig_extra=None):
    """A normalized job ready to store - or (None, reason) when it can't be kept."""
    title = _s(title)[:300]
    ext_id = _s(str(ext_id) if ext_id is not None else "")[:200]
    apply_url = _s(apply_url)[:1000]
    if not title or not ext_id or not apply_url.startswith(("http://", "https://")):
        return None, "incomplete"
    kind, emp, con = kind_of(title, kind_hint)
    text = _s(text)[:TEXT_LIMIT]
    if posted_at is not None and posted_at < job.now - timedelta(days=MAX_AGE_DAYS):
        return None, "old"
    org = _s(org)[:200] or pretty_company(job.slug)
    location = fit_location(location, 288)
    # the feed's own work-mode field (Lever / Ashby workplaceType...), written into the place where the job card,
    # the work-mode filter and a later re-index all read it - "New York, NY" from a remote role reads "(Remote)"
    if mode_hint in ("remote", "hybrid") and not re.search(r"(?<![a-z])(remote|hybrid)(?![a-z])", location, re.I):
        location = ((location[:288] + " (" + mode_hint.capitalize() + ")") if location else mode_hint.capitalize())
    lo, hi, per = salary
    row = {
        "source": job.ats, "external_id": ext_id, "title": title, "org": org, "type": kind, "location": location,
        "text": text, "apply_url": apply_url, "posted_at": posted_at,
        "salary_min": lo, "salary_max": hi, "salary_period": per,
        "employment_type": emp, "contract_type": con, "category": _s(category)[:120] or None,
        "verdict": us_verdict(location, country, remote, text[:3000]),
    }
    row["sig"] = sig_of(title, org, location, text, apply_url, posted_at, lo, hi, per, kind, emp, con, sig_extra)
    row["mode_hint"] = mode_hint
    return row, None
 
 
def finish_rows(job: BoardJob, res: BoardResult, rows, board_us=None):
    """Keep the US jobs (and the unsure remote ones of an employer that clearly hires in the US),
    index the new or changed ones, and remember the ones we read but don't keep.
    board_us: whether this employer lists clearly-US jobs (worked out from the whole board
    when only some jobs were read in full this pass)."""
    if board_us is None:
        board_us = any(r["verdict"] == "us" for r in rows)
    board_us = bool(board_us) or bool(job.known)
    from app.services.job_search import canonical_key_for
    for r in rows:
        keep = r["verdict"] == "us" or (r["verdict"] == "unsure" and board_us)
        ext, sig = r["external_id"], r["sig"]
        if not keep or (ext not in job.known and job.skips.get(ext) == sig):
            # not kept - or set aside earlier (made room for newer jobs) and unchanged since
            res.skips[ext] = sig
            continue
        res.seen[ext] = sig
        if job.known.get(ext) == sig:
            continue
        r["feed_keys"] = feed_keys(r["title"], r["org"], r["location"], r["text"], r.get("mode_hint"), r["type"])
        try:
            r["canonical_key"] = canonical_key_for({"org": r["org"], "title": r["title"], "location": r["location"]})
        except Exception:
            r["canonical_key"] = None
        res.rows.append(r)
 
 
# ---- Greenhouse
def read_greenhouse(f: Fetcher, job: BoardJob) -> BoardResult:
    res = BoardResult()
    base = "https://boards-api.greenhouse.io/v1/boards/" + quote(job.slug, safe="")
    fr = f.get_json(base + "/jobs")
    if fr.status != "ok":
        return _fail(res, fr)
    jobs = (fr.data or {}).get("jobs") if isinstance(fr.data, dict) else None
    if not isinstance(jobs, list):
        return _fail(res, FetchResult("error", error="unexpected feed shape"))
    if _unchanged(job, res, fr.sig):
        return res
    res.listed = len(jobs)
    company = job.company
    if not company:
        br = f.get_json(base)
        if br.status == "ok" and isinstance(br.data, dict):
            company = _s(br.data.get("name")) or None
    res.company = company
    rows, pending = [], 0
    board_us = False
    for j in jobs:
        if isinstance(j, dict) and isinstance(j.get("location"), dict) and us_verdict(_s(j["location"].get("name"))) == "us":
            board_us = True
            break
    for j in jobs:
        if not isinstance(j, dict) or j.get("id") is None:
            continue
        ext = str(j.get("id"))
        loc = _s((j.get("location") or {}).get("name")) if isinstance(j.get("location"), dict) else ""
        lsig = sig_of(_s(j.get("title")), loc, _s(j.get("updated_at")))
        if us_verdict(loc) == "no":
            res.skips[ext] = lsig
            continue
        if job.known.get(ext) == lsig:
            res.seen[ext] = lsig
            continue
        if job.skips.get(ext) == lsig:
            res.skips[ext] = lsig
            continue
        if not job.budget.take():
            pending += 1
            if ext in job.known:          # still on the board - keep what we have until we can re-read it
                res.seen[ext] = job.known[ext]
            continue
        d = f.get_json(base + "/jobs/" + quote(ext, safe="") + "?pay_transparency=true")
        if d.status != "ok" or not isinstance(d.data, dict):
            if d.status == "dead":         # listed a moment ago, gone now: it's being taken down
                continue
            pending += 1
            res.detail_errors += 1
            if ext in job.known:
                res.seen[ext] = job.known[ext]
            continue
        dd = d.data
        text = html_to_text(dd.get("content"), escaped=True)
        posted = parse_dt(dd.get("first_published"))
        sal = (None, None, None)
        for pr in dd.get("pay_input_ranges") or []:
            if not isinstance(pr, dict):
                continue
            lo_c, hi_c = pr.get("min_cents"), pr.get("max_cents")
            ref = hi_c if isinstance(hi_c, (int, float)) else lo_c
            if isinstance(ref, (int, float)) and not isinstance(ref, bool):
                per = "year" if ref >= 1_000_000 else ("hour" if ref <= 50_000 else None)   # $10k+ a year / $500- an hour; between: unclear
                if per:
                    sal = pay((lo_c or 0) / 100 if lo_c else None, (hi_c or 0) / 100 if hi_c else None, pr.get("currency_type"), per)
                    break
        dept = ""
        if isinstance(dd.get("departments"), list) and dd["departments"] and isinstance(dd["departments"][0], dict):
            dept = _s(dd["departments"][0].get("name"))
        r, why = _row(job, ext, dd.get("title") or j.get("title"), company or _s(dd.get("company_name")), loc, text,
                      dd.get("absolute_url") or j.get("absolute_url"), posted, salary=sal, category=dept)
        if r is None:
            res.skips[ext] = lsig
            continue
        r["sig"] = lsig            # Greenhouse changes are spotted from the list, so the list's fingerprint is what we keep
        rows.append(r)
    finish_rows(job, res, rows, board_us)
    res.pending = pending
    res.complete = True
    return res
 
 
# ---- Lever
def read_lever(f: Fetcher, job: BoardJob) -> BoardResult:
    res = BoardResult()
    slug = job.slug
    host = "https://api.lever.co/v0/postings/"
    if slug.startswith("eu/"):
        host, slug = "https://api.eu.lever.co/v0/postings/", slug[3:]
    items, skip, sigs = [], 0, []
    while True:
        fr = f.get_json(host + quote(slug, safe="") + "?mode=json&limit=%d&skip=%d" % (LEVER_PAGE, skip))
        if fr.status != "ok":
            # a later page failing means we don't have the whole list - nothing gets closed this time
            return _fail(res, fr if (skip == 0 or fr.status != "dead") else FetchResult("error", error="a page of the feed went missing"))
        page = fr.data if isinstance(fr.data, list) else None
        if page is None:
            return _fail(res, FetchResult("error", error="unexpected feed shape"))
        items.extend(page)
        sigs.append(fr.sig)
        if len(page) < LEVER_PAGE or skip > 20000:
            break
        skip += LEVER_PAGE
    # (a page without a fingerprint means the feed can't be told unchanged - it is read in full)
    if _unchanged(job, res, sig_of(*sigs) if all(sigs) else None):
        return res
    res.listed = len(items)
    res.company = job.company or pretty_company(slug)
    rows = []
    for p in items:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        cat = p.get("categories") if isinstance(p.get("categories"), dict) else {}
        locs = [x for x in (cat.get("allLocations") or []) if isinstance(x, str) and x.strip()] or ([cat.get("location")] if _s(cat.get("location")) else [])
        loc = "; ".join(dict.fromkeys(_s(x) for x in locs))
        parts = [(None, html_to_text(p.get("description")) or _s(p.get("descriptionPlain")))]
        for lst in p.get("lists") or []:
            if isinstance(lst, dict):
                parts.append((_s(lst.get("text")), html_to_text(lst.get("content"))))
        parts.append((None, html_to_text(p.get("additional")) or _s(p.get("additionalPlain"))))
        sr = p.get("salaryRange") if isinstance(p.get("salaryRange"), dict) else {}
        sal = pay(sr.get("min"), sr.get("max"), sr.get("currency"), sr.get("interval"))
        mode = mode_hint_of(p.get("workplaceType"))
        r, why = _row(job, p.get("id"), p.get("text"), res.company, loc, join_sections(parts), p.get("hostedUrl") or p.get("applyUrl"),
                      parse_dt(p.get("createdAt")), kind_hint=cat.get("commitment"), country=p.get("country"),
                      remote=(mode == "remote"), mode_hint=mode, salary=sal, category=cat.get("team") or cat.get("department"))
        if r is None:
            if why == "old":
                pass
            continue
        rows.append(r)
    finish_rows(job, res, rows)
    res.complete = True
    return res
 
 
# ---- Ashby
def read_ashby(f: Fetcher, job: BoardJob) -> BoardResult:
    res = BoardResult()
    fr = f.get_json("https://api.ashbyhq.com/posting-api/job-board/" + quote(job.slug, safe="") + "?includeCompensation=true")
    if fr.status != "ok":
        return _fail(res, fr)
    jobs = fr.data.get("jobs") if isinstance(fr.data, dict) else None
    if not isinstance(jobs, list):
        return _fail(res, FetchResult("error", error="unexpected feed shape"))
    if _unchanged(job, res, fr.sig):
        return res
    res.listed = len(jobs)
    res.company = job.company or pretty_company(job.slug)
    rows = []
    for j in jobs:
        if not isinstance(j, dict) or j.get("isListed") is False:
            continue
        ext = j.get("id") or (_s(j.get("jobUrl")).rstrip("/").rsplit("/", 1)[-1] if j.get("jobUrl") else None)
        addr = ((j.get("address") or {}).get("postalAddress") or {}) if isinstance(j.get("address"), dict) else {}
        locs = [_s(j.get("location"))]
        for sl in j.get("secondaryLocations") or []:
            if isinstance(sl, dict) and _s(sl.get("location")):
                locs.append(_s(sl.get("location")))
        loc = "; ".join(dict.fromkeys(x for x in locs if x))
        if addr and _s(addr.get("addressRegion")) and _s(addr.get("addressLocality")) and "," not in loc.split(";")[0]:
            loc = _s(addr.get("addressLocality")) + ", " + _s(addr.get("addressRegion")) + ("; " + loc if loc else "")
        text = html_to_text(j.get("descriptionHtml")) or tidy_text(j.get("descriptionPlain"))
        sal = (None, None, None)
        comp = j.get("compensation") if isinstance(j.get("compensation"), dict) else {}
        for c in comp.get("summaryComponents") or []:
            if isinstance(c, dict) and _s(c.get("compensationType")).lower() == "salary":
                sal = pay(c.get("minValue"), c.get("maxValue"), c.get("currencyCode"), c.get("interval"))
                if sal[0] or sal[1]:
                    break
        mode = mode_hint_of(j.get("workplaceType"), j.get("isRemote"))
        r, why = _row(job, ext, j.get("title"), res.company, loc, text, j.get("jobUrl") or j.get("applyUrl"), parse_dt(j.get("publishedAt")),
                      kind_hint=j.get("employmentType"), country=addr.get("addressCountry"), remote=(mode == "remote"),
                      mode_hint=mode, salary=sal, category=j.get("department") or j.get("team"))
        if r is not None:
            rows.append(r)
    finish_rows(job, res, rows)
    res.complete = True
    return res
 
 
# ---- SmartRecruiters
def read_smartrecruiters(f: Fetcher, job: BoardJob) -> BoardResult:
    res = BoardResult()
    base = "https://api.smartrecruiters.com/v1/companies/" + quote(job.slug, safe="") + "/postings"
    items, offset, sigs = [], 0, []
    while True:
        fr = f.get_json(base + "?limit=%d&offset=%d" % (SR_PAGE, offset))
        if fr.status != "ok":
            return _fail(res, fr)
        sigs.append(fr.sig)
        d = fr.data if isinstance(fr.data, dict) else {}
        page = d.get("content") if isinstance(d.get("content"), list) else None
        if page is None:
            return _fail(res, FetchResult("error", error="unexpected feed shape"))
        items.extend(page)
        total = d.get("totalFound") if isinstance(d.get("totalFound"), int) else 0
        offset += SR_PAGE
        if not page or offset >= total or offset > 20000:
            break
    if _unchanged(job, res, sig_of(*sigs) if all(sigs) else None):
        return res
    res.listed = len(items)
    rows, pending = [], 0
    company = job.company
 
    def where(p):
        lc_ = p.get("location") if isinstance(p.get("location"), dict) else {}
        city, region = _s(lc_.get("city")), _s(lc_.get("region"))
        loc = ", ".join(x for x in (city, region) if x) or _s(lc_.get("fullLocation"))
        remote = lc_.get("remote") is True
        if remote:
            loc = (loc + " (Remote)") if loc else "Remote"
        return loc, _s(lc_.get("country")), remote
    board_us = any(isinstance(p, dict) and us_verdict(*where(p)) == "us" for p in items)
    for p in items:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        ext = str(p.get("id"))
        company = company or _s((p.get("company") or {}).get("name") if isinstance(p.get("company"), dict) else "") or None
        loc, country, remote = where(p)
        lsig = sig_of(_s(p.get("name")), loc, country, _s(p.get("releasedDate")), _s(p.get("refNumber")))
        if us_verdict(loc, country, remote) == "no":
            res.skips[ext] = lsig
            continue
        if job.known.get(ext) == lsig:
            res.seen[ext] = lsig
            continue
        if job.skips.get(ext) == lsig:
            res.skips[ext] = lsig
            continue
        if not job.budget.take():
            pending += 1
            if ext in job.known:
                res.seen[ext] = job.known[ext]
            continue
        dr = f.get_json(base + "/" + quote(ext, safe=""))
        if dr.status != "ok" or not isinstance(dr.data, dict):
            if dr.status == "dead":
                continue
            pending += 1
            res.detail_errors += 1
            if ext in job.known:
                res.seen[ext] = job.known[ext]
            continue
        dd = dr.data
        secs = ((dd.get("jobAd") or {}).get("sections") or {}) if isinstance(dd.get("jobAd"), dict) else {}
        parts = []
        for key, head in (("companyDescription", "Company Description"), ("jobDescription", "Job Description"),
                          ("qualifications", "Qualifications"), ("additionalInformation", "Additional Information")):
            sec = secs.get(key) if isinstance(secs.get(key), dict) else {}
            parts.append((_s(sec.get("title")) or head, html_to_text(sec.get("text"))))
        emp = (p.get("typeOfEmployment") or {}).get("label") if isinstance(p.get("typeOfEmployment"), dict) else ""
        url = dd.get("postingUrl") or dd.get("applyUrl") or ("https://jobs.smartrecruiters.com/" + quote(job.slug, safe="") + "/" + quote(ext, safe=""))
        dept = (p.get("department") or {}).get("label") if isinstance(p.get("department"), dict) else ""
        r, why = _row(job, ext, p.get("name"), company, loc, join_sections(parts), url, parse_dt(p.get("releasedDate")),
                      kind_hint=emp, country=country, remote=remote, mode_hint=("remote" if remote else None), category=dept)
        if r is None:
            res.skips[ext] = lsig
            continue
        r["sig"] = lsig
        rows.append(r)
    res.company = company
    finish_rows(job, res, rows, board_us)
    res.pending = pending
    res.complete = True
    return res
 
 
# ---- Workable
def read_workable(f: Fetcher, job: BoardJob) -> BoardResult:
    res = BoardResult()
    fr = f.get_json("https://www.workable.com/api/accounts/" + quote(job.slug, safe="") + "?details=true")
    if fr.status != "ok":
        return _fail(res, fr)
    d = fr.data if isinstance(fr.data, dict) else {}
    jobs = d.get("jobs") if isinstance(d.get("jobs"), list) else None
    if jobs is None:
        return _fail(res, FetchResult("error", error="unexpected feed shape"))
    if _unchanged(job, res, fr.sig):
        return res
    res.listed = len(jobs)
    res.company = job.company or _s(d.get("name")) or pretty_company(job.slug)
    rows = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        ext = j.get("shortcode") or j.get("code") or j.get("id")
        locs, code = [], _s(j.get("country_code") or j.get("countryCode"))
        for l in j.get("locations") or []:
            if isinstance(l, dict) and not l.get("hidden"):
                part = ", ".join(x for x in (_s(l.get("city")), _s(l.get("region"))) if x)
                if part:
                    locs.append(part)
                code = code or _s(l.get("countryCode"))
        if not locs:
            part = ", ".join(x for x in (_s(j.get("city")), _s(j.get("state"))) if x)
            if part:
                locs.append(part)
        remote = j.get("telecommuting") is True or j.get("remote") is True
        loc = "; ".join(dict.fromkeys(locs))
        if remote:
            loc = (loc + " (Remote)") if loc else "Remote"
        parts = [(None, html_to_text(j.get("description"))), ("Requirements", html_to_text(j.get("requirements"))),
                 ("Benefits", html_to_text(j.get("benefits")))]
        country = code or _s(j.get("country"))
        r, why = _row(job, ext, j.get("title"), res.company, loc, join_sections(parts), j.get("url") or j.get("shortlink") or j.get("application_url"),
                      parse_dt(j.get("published_on") or j.get("created_at")), kind_hint=j.get("employment_type"), country=country,
                      remote=remote, mode_hint=("remote" if remote else None), category=j.get("department") or j.get("function"))
        if r is not None:
            rows.append(r)
    finish_rows(job, res, rows)
    res.complete = True
    return res
 
 
# ---- Recruitee
def read_recruitee(f: Fetcher, job: BoardJob) -> BoardResult:
    res = BoardResult()
    slug = re.sub(r"[^a-z0-9-]", "", job.slug.lower())
    if not slug:
        return _fail(res, FetchResult("dead"))
    fr = f.get_json("https://" + slug + ".recruitee.com/api/offers/")
    if fr.status != "ok":
        return _fail(res, fr)
    offers = fr.data.get("offers") if isinstance(fr.data, dict) else None
    if not isinstance(offers, list):
        return _fail(res, FetchResult("error", error="unexpected feed shape"))
    if _unchanged(job, res, fr.sig):
        return res
    res.listed = len(offers)
    rows = []
    company = job.company
    for o in offers:
        if not isinstance(o, dict) or (o.get("status") and _s(o.get("status")).lower() not in ("published", "")):
            continue
        company = company or _s(o.get("company_name")) or None
        loc = ", ".join(x for x in (_s(o.get("city")), _s(o.get("state_code")) or _s(o.get("state_name"))) if x) or _s(o.get("location"))
        remote = o.get("remote") is True
        mode = "remote" if remote else ("hybrid" if o.get("hybrid") is True else ("onsite" if o.get("on_site") is True else None))
        if remote:
            loc = (loc + " (Remote)") if loc else "Remote"
        s = o.get("salary") if isinstance(o.get("salary"), dict) else {}
        sal = pay(s.get("min"), s.get("max"), s.get("currency"), s.get("period"))
        parts = [(None, html_to_text(o.get("description"))), ("Requirements", html_to_text(o.get("requirements")))]
        r, why = _row(job, o.get("id"), o.get("title"), company or pretty_company(slug), loc, join_sections(parts),
                      o.get("careers_url") or o.get("careers_apply_url"), parse_dt(o.get("published_at") or o.get("created_at")),
                      kind_hint=o.get("employment_type_code"), country=o.get("country_code"), remote=remote, mode_hint=mode,
                      salary=sal, category=o.get("department"))
        if r is not None:
            rows.append(r)
    res.company = company or pretty_company(slug)
    finish_rows(job, res, rows)
    res.complete = True
    return res
 
 
# ---- USAJOBS (one "board": every federal job open to the public)
def usajobs_configured() -> bool:
    return bool(os.getenv("USAJOBS_API_KEY", "").strip() and os.getenv("USAJOBS_EMAIL", "").strip())
 
 
def read_usajobs_page(f: Fetcher, job: BoardJob, page: int):
    """One page of the public-hiring search: (BoardResult with this page's jobs, pages in total)."""
    res = BoardResult()
    key, email = os.getenv("USAJOBS_API_KEY", "").strip(), os.getenv("USAJOBS_EMAIL", "").strip()
    if not key or not email:
        return _fail(res, FetchResult("blocked", error="USAJOBS_API_KEY / USAJOBS_EMAIL are not set")), 0
    # jobs open to the public, posted in the last 60 days (one search returns at most 10,000)
    url = "https://data.usajobs.gov/api/search?HiringPath=public&DatePosted=60&ResultsPerPage=%d&Page=%d&Fields=full" % (USAJOBS_PAGE, page)
    fr = f.get_json(url, headers={"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}, check_robots=False)
    if fr.status != "ok":
        return _fail(res, fr), 0
    sr = (fr.data or {}).get("SearchResult") if isinstance(fr.data, dict) else None
    if not isinstance(sr, dict):
        return _fail(res, FetchResult("error", error="unexpected feed shape")), 0
    total = sr.get("SearchResultCountAll") if isinstance(sr.get("SearchResultCountAll"), int) else 0
    pages = max(1, -(-total // USAJOBS_PAGE)) if total else 1
    items = sr.get("SearchResultItems") if isinstance(sr.get("SearchResultItems"), list) else []
    res.listed = len(items)
    rows = []
    for it in items:
        m = it.get("MatchedObjectDescriptor") if isinstance(it, dict) else None
        if not isinstance(m, dict):
            continue
        det = ((m.get("UserArea") or {}).get("Details") or {}) if isinstance(m.get("UserArea"), dict) else {}
        paths = [(_s(x) if isinstance(x, str) else _s((x or {}).get("Name") if isinstance(x, dict) else "")).lower() for x in (det.get("HiringPath") or [])]
        if paths and not any("public" in p for p in paths):
            continue                       # only jobs anyone in the US can apply to - not internal federal postings
        locs, listed = [], [pl for pl in (m.get("PositionLocation") or []) if isinstance(pl, dict)]
        for pl in listed:
            if _s(pl.get("CountryCode")) in ("United States", "US", "USA", ""):
                part = ", ".join(x for x in (_s(pl.get("CityName")).split(",")[0], _s(pl.get("CountrySubDivisionCode"))) if x)
                if part:
                    locs.append(part)
        if listed and not locs:
            continue                       # every location is overseas
        if not locs and _s(m.get("PositionLocationDisplay")):
            locs = [_s(m.get("PositionLocationDisplay"))]
        def flag(v):
            return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes", "y"))
        tele, remote = flag(det.get("TeleworkEligible")), flag(det.get("RemoteIndicator"))
        loc = "; ".join(dict.fromkeys(locs[:6])) + (" (Remote)" if remote else "")
        duties = det.get("MajorDuties") if isinstance(det.get("MajorDuties"), list) else []
        who = det.get("WhoMayApply") if isinstance(det.get("WhoMayApply"), dict) else {}
        parts = [
            ("Summary", _s(det.get("JobSummary"))),
            ("Duties", "\n".join("- " + _s(x) for x in duties if _s(x))),
            ("Qualifications", _s(m.get("QualificationSummary"))),
            ("Requirements", _s(det.get("Requirements"))),
            ("Education", _s(det.get("Education"))),
            (None, ("Who may apply: " + _s(who.get("Name"))) if _s(who.get("Name")) else ""),
            (None, "Telework eligible." if tele else ""),
        ]
        pr = (m.get("PositionRemuneration") or [{}])[0] if isinstance(m.get("PositionRemuneration"), list) and m.get("PositionRemuneration") else {}
        sal = pay(pr.get("MinimumRange"), pr.get("MaximumRange"), "USD", _s(pr.get("RateIntervalCode")).lower()) if isinstance(pr, dict) else (None, None, None)
        sched = (m.get("PositionSchedule") or [{}])[0] if isinstance(m.get("PositionSchedule"), list) and m.get("PositionSchedule") else {}
        kind_hint = _s(sched.get("Name")) if isinstance(sched, dict) else ""
        offering = (m.get("PositionOfferingType") or [{}])[0] if isinstance(m.get("PositionOfferingType"), list) and m.get("PositionOfferingType") else {}
        if isinstance(offering, dict) and re.search(r"intern|student", _s(offering.get("Name")), re.I):
            kind_hint = "internship"
        org = _s(m.get("OrganizationName")) or _s(m.get("DepartmentName")) or "U.S. federal government"
        apply_uri = m.get("ApplyURI")
        url = _s(m.get("PositionURI")) or (_s(apply_uri[0]) if isinstance(apply_uri, list) and apply_uri else "")
        r, why = _row(job, it.get("MatchedObjectId") or m.get("PositionID"), m.get("PositionTitle"), org, loc, join_sections(parts),
                      url, parse_dt(m.get("PublicationStartDate")), kind_hint=kind_hint, country="US", remote=remote,
                      mode_hint=("remote" if remote else None), salary=sal, category=m.get("DepartmentName"),
                      sig_extra=_s(m.get("ApplicationCloseDate")))
        if r is None:
            continue
        r["deadline"] = parse_dt(m.get("ApplicationCloseDate"), future_ok=True)
        rows.append(r)
    res.company = "USAJOBS"
    finish_rows(job, res, rows)
    res.complete = False                   # one page is never the whole list - closing is done by the crawler
    return res, pages
 
 
READERS = {
    "greenhouse": read_greenhouse,
    "lever": read_lever,
    "ashby": read_ashby,
    "smartrecruiters": read_smartrecruiters,
    "workable": read_workable,
    "recruitee": read_recruitee,
}
 
 
def read_board(f: Fetcher, job: BoardJob) -> BoardResult:
    """Never raises: a feed that misbehaves gives an 'error' result for that board only."""
    reader = READERS.get(job.ats)
    if reader is None:
        r = BoardResult("error")
        r.error = "unknown hiring system"
        return r
    try:
        res = reader(f, job)
        if res.company:
            res.company = _s(res.company)[:200] or None
        return res
    except Exception as e:
        r = BoardResult("error")
        r.error = "could not read the feed (%s)" % type(e).__name__
        return r
 
