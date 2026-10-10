"""Auto, server side: the passes that prepare applications, the packages that
record exactly what each one contains, the delivery that sends them (or hands
them to you), follow-up reminders, and the tick that runs it all.
 
How a pass works (twice a day per person, or when they press "Run now"):
  1. the person's own Job Search matches (the same fits their cards show, every
     dealbreaker and filter they set) become Auto candidates;
  2. the shared planner (auto_engine.py - the page runs the identical JS) decides
     what to prepare now, what waits for a later day, and what to hold back, with
     a reason for every job;
  3. each job it takes becomes an application plus a "package": which of the
     person's own resumes it uses (a saved Resume Studio version when one fits
     better) with the posting's skills first, a cover letter only when the
     posting asks for one (or they asked for one always), the answers it can
     give from their answer bank, a referral note when they know someone there,
     and how it will be delivered.
 
Delivery never guesses: a job board that forbids automation, a missing consent,
a form question the answer bank doesn't cover, a job that closed or that no
longer clears their bar - each one stops the send and hands the person a
ready-to-submit kit instead, saying why. Nothing is ever marked sent without a
real send, and every real send keeps its proof.
 
Everything that touches the database is small and isolated per user and per
application, so one failure never stops the rest.
"""
from __future__ import annotations
 
import base64
import copy
import logging
import os
import re
import threading
import time
import uuid as uuid_module
from datetime import datetime, timedelta, timezone
 
from app.services import auto_answers as AA
from app.services import auto_engine as AE
from app.services.timeutil import to_naive_utc, utcnow
 
log = logging.getLogger("kaidostar")
 
PACKAGE_KIND, STATE_KIND, ANSWERS_KIND = "auto_package", "auto_state", "auto_answers"
SERVER_KINDS = (PACKAGE_KIND, STATE_KIND, ANSWERS_KIND)
 
 
def _env_int(name, default, lo, hi):
    try:
        v = int(os.getenv(name, str(default)))
    except ValueError:
        v = default
    return max(lo, min(hi, v))
 
 
TICK_MINUTES = _env_int("AUTO_TICK_MINUTES", 30, 10, 720)        # how often the tick runs
PASS_HOURS = _env_int("AUTO_PASS_HOURS", 12, 3, 72)              # how often each person's pass runs
TICK_BUDGET_S = _env_int("AUTO_TICK_BUDGET_S", 90, 15, 900)       # one tick's time budget for passes
SEND_MAX_AGE_DAYS = _env_int("AUTO_SEND_MAX_AGE_DAYS", 7, 1, 60)  # an approval this stale goes back for review
CANDIDATE_LIMIT = 40
CACHE_TTL_S = 600
CACHE_MAX = 120          # people whose candidates are kept warm (each ~40 jobs, a few hundred KB at most)
SENDING_STALE_MIN = 30
HISTORY_DAYS = 120
RUNS_KEPT = 20
ATTEMPTS_KEPT = 10
DAY_MS = 86400000
 
_tick_lock = threading.Lock()
_user_locks: dict = {}
_user_locks_guard = threading.Lock()
_cache: dict = {}
_cache_guard = threading.Lock()
_browser = {"at": 0.0, "ok": None}
 
 
def _ms(dt) -> int | None:
    dt = to_naive_utc(dt)
    if dt is None:
        return None
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
 
 
def _now_ms() -> int:
    return int(time.time() * 1000)
 
 
def _user_lock(uid):
    with _user_locks_guard:
        lk = _user_locks.get(str(uid))
        if lk is None:
            lk = _user_locks[str(uid)] = threading.Lock()
        return lk
 
 
# ------------------------------------------------------------------ small storage (workshop_items, server-only kinds)
def _W():
    from app.models.db_models import WorkshopItem
    return WorkshopItem
 
 
def _get_item(db, user_id, kind, client_id, locked=False):
    W = _W()
    q = db.query(W).filter(W.user_id == user_id, W.kind == kind, W.client_id == str(client_id))
    if locked:
        # (read, changed and written back by one request at a time - a second waits for the first to commit)
        q = q.with_for_update().populate_existing()
    return q.first()
 
 
def _items(db, user_id, kind, limit=1000):
    W = _W()
    return db.query(W).filter(W.user_id == user_id, W.kind == kind).limit(limit).all()
 
 
def _put_item(db, user_id, kind, client_id, data):
    """Upsert one record (the caller commits)."""
    row = _get_item(db, user_id, kind, client_id)
    if row is None:
        db.add(_W()(user_id=user_id, kind=kind, client_id=str(client_id), data=data))
        return
    row.data = data
    try:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(row, "data")
    except Exception:
        pass
 
 
def load_state(db, user_id) -> dict:
    row = _get_item(db, user_id, STATE_KIND, "singleton")
    d = copy.deepcopy(row.data) if row is not None and isinstance(row.data, dict) else {}
    d.setdefault("v", 1)
    d["runs"] = [r for r in (d.get("runs") if isinstance(d.get("runs"), list) else []) if isinstance(r, dict)][-RUNS_KEPT:]
    return d
 
 
def save_state(db, user_id, data):
    _put_item(db, user_id, STATE_KIND, "singleton", data)
 
 
def load_answers(db, user_id) -> dict:
    row = _get_item(db, user_id, ANSWERS_KIND, "singleton")
    b = AA.norm_bank(row.data if row is not None else None)
    at = row.data.get("updatedAt") if row is not None and isinstance(row.data, dict) else None
    if isinstance(at, int) and not isinstance(at, bool):
        b["updatedAt"] = at          # the version the Auto page saves against (see merge_answers)
    return b
 
 
def merge_answers(stored, incoming) -> dict:
    """The answer bank the Auto page saves, with any answer the extension remembered since the page loaded it (the page
    sends the version it loaded; an answer remembered after that, that the page doesn't have, is kept - one the page
    had and you removed stays removed)."""
    b = AA.norm_bank(incoming)
    base = incoming.get("updatedAt") if isinstance(incoming, dict) else None
    if not isinstance(base, int) or isinstance(base, bool):
        return b
    have = {AA._norm(c["q"]) for c in b["custom"]}
    later = [c for c in (stored or {}).get("custom") or [] if isinstance(c, dict) and c.get("src") == "form"
             and isinstance(c.get("at"), int) and c["at"] > base and AA._norm(c.get("q")) not in have]
    if later:
        out = b["custom"] + later
        while len(out) > AA.CUSTOM_CAP:
            # room is made the way remembering makes it: the oldest answer saved from a form goes - never one you wrote
            k = next((i for i, c in enumerate(out) if c.get("src") == "form"), None)
            if k is None:
                out = out[:AA.CUSTOM_CAP]
                break
            out.pop(k)
        b["custom"] = out
    return AA.norm_bank(b)
 
 
def save_answers(db, user_id, bank) -> dict:
    b = AA.norm_bank(bank)
    b["updatedAt"] = _now_ms()
    _put_item(db, user_id, ANSWERS_KIND, "singleton", b)
    return b
 
 
def load_package(db, user_id, app_id, locked=False):
    row = _get_item(db, user_id, PACKAGE_KIND, str(app_id), locked=locked)
    return copy.deepcopy(row.data) if row is not None and isinstance(row.data, dict) else None
 
 
def save_package(db, user_id, app_id, pkg):
    _put_item(db, user_id, PACKAGE_KIND, str(app_id), pkg)
 
 
def packages_for(db, user_id) -> dict:
    return {str(r.client_id): r.data for r in _items(db, user_id, PACKAGE_KIND, limit=2000) if isinstance(r.data, dict)}
 
 
def note_extension_seen(db, user_id):
    """The Kaidostar Apply extension just talked to us for this person (shown on the Auto page)."""
    try:
        st = load_state(db, user_id)
        st["extensionSeenAt"] = _now_ms()
        save_state(db, user_id, st)
        db.commit()
    except Exception:
        db.rollback()
 
 
# ------------------------------------------------------------------ settings + context
def _profile(db, user_id):
    from app.models.db_models import Profile
    return db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
 
 
def rules_of(profile) -> dict:
    if profile is None:
        return AE.defaults()
    return AE.norm_rules(getattr(profile, "auto_apply_rules", None), getattr(profile, "auto_apply_threshold", None))
 
 
def tier_daily_max(tier) -> int:
    return AE.TIER_DAILY_MAX.get(tier or "free", 0)
 
 
def _tz(rules):
    name = (rules or {}).get("tz") or ""
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone.utc
 
 
def _local_midnight_utc(now_naive, rules) -> datetime:
    tz = _tz(rules)
    local = now_naive.replace(tzinfo=timezone.utc).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).replace(tzinfo=None)
 
 
def browser_available() -> bool:
    """Can this server drive a browser to submit forms? Checked at most every 6 hours (launching
    Chromium is not free). AUTO_BROWSER=off skips it - the honest answer on a small free server."""
    if os.getenv("AUTO_BROWSER", "").strip().lower() in ("off", "0", "false", "no"):
        return False
    if _browser["ok"] is not None and time.time() - _browser["at"] < 6 * 3600:
        return bool(_browser["ok"])
    try:
        from app.services.application_submit import check_browser_available
        ok = bool(check_browser_available().get("available"))
    except Exception:
        ok = False
    _browser.update(at=time.time(), ok=ok)
    return ok
 
 
def email_ready() -> bool:
    """Can this server send email (a Resend key and a real, verified sending address)?"""
    try:
        from app.services import email_send as ES
        return bool(ES.RESEND_API_KEY) and "yourdomain.com" not in (ES.SEND_FROM_ADDRESS or "")
    except Exception:
        return False
 
 
_REGION_COUNTRY = {"US": "us", "CA": "canada", "UK": "uk", "EU": "eu", "IN": "india"}
# the job engine's metros outside the US (their "states" are country or province codes, some of which look
# like US states: Berlin "DE", Bengaluru "IN")
_METRO_COUNTRY = {"toronto": "canada", "vancouver": "canada", "london": "uk", "dublin": "ireland", "berlin": "germany",
                  "bangalore": "india", "singapore": "singapore", "sydney": "australia"}
 
 
# states and provinces written out in full: "Dublin, Ohio" is in the US, "London, Ontario" in Canada - a city's
# name alone never decides it ("Georgia" and "Victoria" are left out: each is also a country or another region's city)
_US_STATES = ("alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "district of columbia", "florida",
              "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
              "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york",
              "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
              "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming")
_REGION_NAMES = dict(
    [(s, "us") for s in _US_STATES]
    + [(p, "canada") for p in ("ontario", "quebec", "british columbia", "alberta", "manitoba", "saskatchewan", "nova scotia", "new brunswick",
                               "newfoundland", "labrador", "prince edward island", "yukon", "nunavut", "northwest territories")]
    + [(p, "australia") for p in ("new south wales", "queensland", "tasmania", "western australia", "south australia", "northern territory",
                                  "australian capital territory")]
    + [(p, "india") for p in ("karnataka", "maharashtra", "tamil nadu", "telangana", "kerala", "gujarat", "haryana", "uttar pradesh", "west bengal",
                              "andhra pradesh", "rajasthan")]
)
 
 
def _plain(text) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(text or ""))
    return AA._norm("".join(ch for ch in t if not unicodedata.combining(ch)))   # "Québec" -> "quebec"
 
 
def _regions_in(text) -> set:
    t = _plain(text)
    return {c for name, c in _REGION_NAMES.items() if AA._has(t, name)}
 
 
# cities whose locations are often written with a 2-letter code that is also a US state's ("Mumbai, IN", "Munich, DE",
# "Tel Aviv, IL") - or with a US state's own code ("Perth, WA"). Their name, with no code or with their own country's
# code, says the country; with another code it's unclear (Melbourne, FL is in Florida).
_FOREIGN_CITIES = {
    "india": ("mumbai", "bombay", "delhi", "new delhi", "gurgaon", "gurugram", "noida", "hyderabad", "pune", "chennai", "kolkata", "ahmedabad",
              "kochi", "jaipur", "bengaluru", "bangalore", "chandigarh", "indore", "coimbatore", "thiruvananthapuram"),
    "germany": ("munich", "munchen", "hamburg", "frankfurt", "cologne", "koln", "stuttgart", "dusseldorf", "duesseldorf", "leipzig", "dresden",
                "nuremberg", "nurnberg", "hannover", "bremen", "karlsruhe", "mannheim", "bonn"),
    "israel": ("tel aviv", "tel aviv yafo", "jerusalem", "haifa", "herzliya", "petah tikva", "raanana", "beer sheva", "netanya", "rehovot"),
    "colombia": ("bogota", "medellin", "cali", "barranquilla"),
    "argentina": ("buenos aires", "rosario", "mendoza"),
    "canada": ("ottawa", "montreal", "calgary", "edmonton", "winnipeg", "waterloo", "kitchener", "quebec city", "halifax", "mississauga", "markham", "burnaby"),
    "australia": ("melbourne", "brisbane", "perth", "adelaide", "canberra"),
    "indonesia": ("jakarta", "bandung", "surabaya"),
    "morocco": ("casablanca", "rabat"),
    "malta": ("valletta", "sliema"),
    "georgia (the country)": ("tbilisi",),
    "azerbaijan": ("baku",),
    "tunisia": ("tunis", "sfax"),
    "vietnam": ("ho chi minh", "ho chi minh city", "saigon", "hanoi", "da nang"),
}
# the state codes a city in India or Australia is written with ("Chennai, TN", "Perth, WA")
_LOCAL_STATE_CODES = {"india": ("KA", "UP", "KL", "GJ", "TG", "TS", "MH", "DL", "RJ", "TN", "AP", "WB", "HR", "PB", "MP", "OD", "BR", "CH", "GA"),
                      "australia": ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT")}
# the 2-letter codes that are both a US state's and a country's ("Mumbai, IN", "Munich, DE"), the codes that name a
# Canadian province, and other countries' codes as people write them after a city
_ISO_OF = {"IN": "india", "DE": "germany", "IL": "israel", "CO": "colombia", "AR": "argentina", "CA": "canada", "ID": "indonesia",
           "MA": "morocco", "MT": "malta", "AZ": "azerbaijan", "TN": "tunisia"}
_RISKY_CODES = ("IN", "DE", "IL", "CO", "AR", "ID", "MA", "MT")   # a state code alone that could as well be the country's
_PROVINCE_CODES = ("ON", "BC", "QC", "AB", "MB", "NS", "NB")
_COUNTRY_CODES = {"US": "us", "USA": "us", "UK": "uk", "GB": "uk", "NL": "netherlands", "FR": "france", "ES": "spain", "IT": "italy",
                  "PT": "portugal", "IE": "ireland", "SE": "sweden", "PL": "poland", "DK": "denmark", "FI": "finland", "BE": "belgium",
                  "AT": "austria", "CH": "switzerland", "NO": "norway", "AU": "australia", "NZ": "new zealand", "SG": "singapore",
                  "JP": "japan", "MX": "mexico", "BR": "brazil"}
_PLACE_SPLIT = re.compile(r"\s*(?:;|\||/|\n|•|\s[-–—]\s|\s(?:or|and|&)\s)\s*", re.I)
_CODE_RE = re.compile(r"^([A-Za-z]{2,3})(?:\s+(\d{4,5})(?:-\d{4})?)?$")
# the ZIP codes of the states whose codes are also countries': "Hopkinton, MA 01748" is in Massachusetts (Morocco's
# postcodes never start with 0, India's have six digits...) - the first three digits, as numbers
_STATE_ZIPS = {"MA": ((10, 27), (55, 55)), "IN": ((460, 479),), "IL": ((600, 629),), "CO": ((800, 816),), "AR": ((716, 729),),
               "ID": ((832, 838),), "MT": ((590, 599),), "DE": ((197, 199),), "AZ": ((850, 865),), "TN": ((370, 385),)}
 
 
def _zip_in_state(zip5, code) -> bool:
    if not zip5 or len(zip5) != 5 or not zip5.isdigit():
        return False
    p = int(zip5[:3])
    return any(lo <= p <= hi for lo, hi in _STATE_ZIPS.get(code, ()))
# what a place says about the work, not where it is: "Seattle, WA (Hybrid)", "Chicago, IL, Remote"
_PAREN_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_WORK_MODE_RE = re.compile(r"^(?:remote|hybrid|on-?site|in-?office|in office|office|hq|headquarters|field(?:-based)?|flexible|fully remote"
                           r"|remote[- ]first|remote[- ]friendly|work from home|wfh)$", re.I)
 
 
def _split_places(loc) -> list:
    """The places a location lists ("New York, NY; London, UK", "Seattle, WA / Remote") - never splitting inside
    brackets ("Los Angeles, CA (Hybrid, 3 days/week)" is one place)."""
    out, buf, depth = [], [], 0
    for ch in str(loc or ""):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        buf.append("\x00" if (depth == 0 and ch in ";|/\n•") else ch)
    flat = "".join(buf)
    pieces = []
    for chunk in flat.split("\x00"):
        # " - ", " or ", " and ", " & " between places, outside brackets
        depth, start, i = 0, 0, 0
        while i < len(chunk):
            ch = chunk[i]
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth = max(0, depth - 1)
            elif depth == 0:
                m = re.match(r"\s(?:[-–—]|or|and|&)\s", chunk[i:], re.I)
                if m:
                    pieces.append(chunk[start:i])
                    i += m.end()
                    start = i
                    continue
            i += 1
        pieces.append(chunk[start:])
    return [x.strip() for x in pieces if x and x.strip()]
 
 
def _place_parts(p) -> list:
    parts = [x.strip() for x in _PAREN_RE.sub(" ", p).split(",") if x.strip()]
    return [x for x in parts if not _WORK_MODE_RE.match(x)] or parts
# the states whose codes are also countries' - written out in a posting's text, they settle "X, IN" (Indiana or India?)
_RISKY_STATE = {"IN": "indiana", "DE": "delaware", "IL": "illinois", "CO": "colorado", "AR": "arkansas", "ID": "idaho",
                "MA": "massachusetts", "MT": "montana"}
# a city name alone that is both a US city the job engine knows and a well-known city elsewhere: never decides by itself
_AMBIGUOUS_CITIES = ("cambridge", "durham", "worcester", "birmingham", "manchester", "richmond", "hamilton", "kingston", "paris", "dublin",
                     "perth", "athens", "rome", "naples", "florence", "valencia", "toledo", "newcastle", "plymouth", "bristol", "oxford", "york",
                     "lancaster", "reading", "dover", "windsor", "waterloo", "brighton", "exeter", "norwich", "stamford", "aberdeen", "glasgow",
                     "alexandria", "cairo", "lima", "moscow", "odessa", "hanover", "amsterdam", "delhi", "lebanon", "london", "berlin", "victoria",
                     "vancouver", "sydney", "melbourne", "santiago", "milan", "venice", "geneva", "vienna", "warsaw", "belfast", "surrey",
                     "wellington", "brisbane", "cordoba", "salisbury", "canterbury", "chester", "peterborough", "guildford", "sheffield", "leeds")
 
 
# newspaper-style state abbreviations ("Boston, Mass.", "New York, N.Y.")
_AP_STATES = ("ala", "ariz", "ark", "calif", "colo", "conn", "del", "fla", "ga", "ill", "ind", "kan", "kans", "ky", "la", "md", "mass", "mich",
              "minn", "miss", "mo", "mont", "neb", "nebr", "nev", "n h", "n j", "n m", "n y", "n c", "n d", "okla", "ore", "pa", "penn", "r i", "s c",
              "s d", "tenn", "tex", "vt", "va", "wash", "w va", "wis", "wisc", "wyo", "d c")
 
 
def _us_qualifier(part, us_states) -> bool:
    """Does what follows a US city's name ("MA", "Massachusetts", "Mass.", "Georgia", "USA") say the US?"""
    m = _CODE_RE.match(part)
    if m and m.group(1).upper() in us_states:
        return True
    n = AA._norm(part)
    return (_regions_in(part) == {"us"} or AA.countries_in(part) == {"us"} or n == "georgia" or n in _AP_STATES
            or (n in AA._BARE_COUNTRY and AA._BARE_COUNTRY[n] == "us"))
 
 
def _place_country(p, JE, us_states, desc="", unclear=None):
    """One place a posting lists -> its country, "?" when it's unclear, or None when it says nothing.
    What decides, strongest first: a country named ("Remote - US", "Paris, France", "Amsterdam, NL") or a state
    or province written in the place's region ("Dublin, Ohio", "London, Ontario", "Toronto, ON"); then the city
    (a metro the job engine knows, or a city from the list above), checked against the code after it ("Munich, DE"
    yes, "Perth, WA" unclear); then a US state code alone - unless it's one that is also a country's ("X, IN"), when the
    place's own ZIP code or the posting's own text has to say which (it gives the town's address, or names Indiana, or
    India). desc: the posting's text, normalized. unclear: a list that gets (town, code) for each place only that
    question leaves open (see job_country_info)."""
    parts = _place_parts(p)
    if not parts:
        return None
    tail = parts[-1]
    zm = re.match(r"^(\d{5})(?:-\d{4})?$", tail) if len(parts) >= 3 else None
    if zm and _CODE_RE.match(parts[-2]):
        # "Hopkinton, MA, 01748": the ZIP code on its own after the state's
        parts = parts[:-1]
        tail = parts[-1]
    m = _CODE_RE.match(tail) if len(parts) >= 2 else None
    code = m.group(1).upper() if m else ""
    zip5 = ((m.group(2) or "") if m else "") or (zm.group(1) if (zm and m) else "")
    strong, weak = set(AA.countries_in(p)), set()
    words = AA._norm(p).split()
    for w in (words[:1] + words[-1:]) if words else []:     # "Remote - US", "US Remote", "Toronto, ON, Canada"
        if w in AA._BARE_COUNTRY:
            strong.add(AA._BARE_COUNTRY[w])
    by_code = None
    if code in _COUNTRY_CODES:
        by_code = _COUNTRY_CODES[code]
    if code in _PROVINCE_CODES:
        by_code = "canada"
    for i, part in enumerate(parts):
        # a state's name in the city's own slot ("Ontario, CA", "Indiana, PA") is a city named like it - weak
        (weak if (i == 0 and len(parts) > 1) else strong).update(_regions_in(part))
    places = []
    try:
        places = [pl for pl in (JE.parse_job({"id": "p", "title": "", "org": "", "location": p, "description": "", "type": "job"}).get("places") or [])
                  if isinstance(pl, dict)]
    except Exception:
        places = []
    medium = set()
    state_only = False
    for pl in places:
        if pl.get("metro") in _METRO_COUNTRY:
            medium.add(_METRO_COUNTRY[pl["metro"]])
        elif pl.get("metro") and pl.get("state") in us_states:
            medium.add("us")          # a US metro the job engine knows (Boston, Chicago, the Inland Empire...)
        elif pl.get("state") in us_states:
            state_only = True
    city = _plain(parts[0])
    gaz = None
    for c, names in _FOREIGN_CITIES.items():
        if any(city == n or city.startswith(n + " ") for n in names):
            medium.add(c)
            gaz = c
    if gaz and code in _LOCAL_STATE_CODES.get(gaz, ()):
        return gaz                    # "Chennai, TN", "Perth, WA": the city's own state's code
    if by_code:
        if gaz and gaz != by_code and not strong:
            return "?"                # "Ho Chi Minh City, SG": a code that isn't the city's country
        strong.add(by_code)
    if strong:
        if len(strong) > 1:
            return "?"
        c = next(iter(strong))
        if len(places) > 1 and medium - {c}:
            return "?"                # two cities in one place, one of them elsewhere
        if code in us_states and c != "us" and _ISO_OF.get(code) != c:
            return "?"                # "Alberta, VA": the code says a US state
        return c                      # a city's name alone (London, Dublin, Sydney...) never overrides what the place says
    if medium:
        if len(medium) > 1:
            return "?"
        c = next(iter(medium))
        if code in us_states and c != "us" and _ISO_OF.get(code) != c:
            return "?"                # "Perth, WA", "Melbourne, FL": unclear
        if c == "us":
            # a US city's name is decided by what follows it: "Cambridge, MA" yes; "Cambridge, Cambridgeshire" or
            # a bare "Cambridge" (England too) unclear
            if len(parts) >= 2 and not _us_qualifier(parts[-1], us_states):
                return "?"
            if len(parts) == 1 and city in _AMBIGUOUS_CITIES:
                return "?"
        return c                      # "Munich, DE", "Tel Aviv, IL", "Boston, MA", "Ontario, CA" (the Inland Empire)
    if code in us_states or state_only:
        if code in _RISKY_CODES:
            # "X, IN" with a city Kaidostar doesn't know: Indiana or India? The place's own ZIP code in that state's range
            # says Indiana; else the posting's own text decides - the city named with its state or its country
            # ("Bloomington, Indiana", "Mysore, India"), or its street address with the state's ZIP ("Hopkinton, MA
            # 01748") - or nothing does (a US company's boilerplate names its home state and the US anywhere)
            if _zip_in_state(zip5, code):
                return "us"
            says_us = bool(desc) and bool(city) and (AA._has(desc, city + " " + _RISKY_STATE[code]) or any(
                _zip_in_state(z, code) for z in re.findall(r"(?<![a-z0-9])" + re.escape(city) + " " + code.lower() + r" (\d{5})(?![0-9])", desc)))
            says_there = bool(desc) and bool(city) and AA._has(desc, city + " " + _ISO_OF[code])
            if says_us and not says_there:
                return "us"
            if says_there and not says_us:
                return _ISO_OF[code]
            if unclear is not None and city and not says_us and not says_there:
                unclear.append((city, code))
            return "?"
        if weak and weak != {"us"}:
            return "?"
        return "us"
    if weak:
        return "?"
    return None
 
 
def job_country_of(db, listing, page=None):
    """Where a job is ("us", "canada", "uk"...), when the posting says so clearly; else None (see job_country_info)."""
    return job_country_info(db, listing, page)["country"]
 
 
def _feed_country(db, listing):
    """The country the employer's own hiring system gives for the job (a structured field its job feed has - Lever,
    Ashby, SmartRecruiters, Workable, Recruitee, USAJOBS), kept with the job as a "c:" key; None when it gave none."""
    lid = getattr(listing, "id", None)
    if db is None or lid is None:
        return None
    try:
        from sqlalchemy import text
        # (in a savepoint: a database without the feeds' columns must not undo the caller's work)
        with db.begin_nested():
            row = db.execute(text("SELECT feed_keys FROM listings WHERE id = CAST(:id AS uuid)"), {"id": str(lid)}).fetchone()
        keys = [k for k in ((row[0] if row else None) or []) if isinstance(k, str) and k.startswith("c:")]
        got = {k[2:] for k in keys if k[2:] in AA.COUNTRIES}
        return next(iter(got)) if len(got) == 1 else None
    except Exception:
        return None
 
 
_TITLE_STOP = {"the", "and", "for", "with", "senior", "junior", "lead", "remote", "hybrid", "onsite", "level", "new", "grad", "full", "part", "time",
               "contract", "temporary", "temp", "entry", "associate", "staff", "principal", "sr", "jr"}
 
 
def _title_words(t) -> list:
    return [w for w in re.split(r"[^a-z0-9+#]+", str(t or "").lower().replace("’", "'")) if len(w) >= 3 and w not in _TITLE_STOP]
 
 
def _same_job(page_title, title) -> bool:
    """Is the job a page's structured data describes this one (most of its title's words, both ways)?"""
    a, b = _title_words(title), set(_title_words(page_title))
    if not a or not b:
        return False
    hits = sum(1 for w in a if w in b)
    back = sum(1 for w in b if w in set(a))
    return hits >= max(1, -(-len(a) * 3 // 5)) and back >= max(1, -(-len(b) * 3 // 5))
 
 
def _page_country(page, listing):
    """The country the job's own page states in its structured data (schema.org JobPosting: the address of each place the
    job is, or where a remote job's applicants must be) - only when that data is about this job and names one country.
    None: the page says nothing usable; "?": it names more than one."""
    if not isinstance(page, dict) or page.get("n") != 1 or listing is None:
        return None
    if not _same_job(page.get("title"), getattr(listing, "title", "")):
        return None
    got = set()
    for v in (page.get("countries") or [])[:20] + (page.get("remote") or [])[:20]:
        if not isinstance(v, str) or not v.strip():
            continue
        k = AA.country_key(v, structured=False)
        if not k:
            return None                 # one it can't read: nothing from the page is used
        got.add(k)
    if not got:
        return None
    return next(iter(got)) if len(got) == 1 else "?"
 
 
def job_country_info(db, listing, page=None) -> dict:
    """Where a job is, when the posting says so clearly: {"country": "us" | "canada" | "uk"... or None, "unclear": [(town,
    code)], "by": what said it}. A form's "are you authorized to work here?" is about this country - and when it isn't
    clear, it's left for you.
    Every place the posting lists has to agree. In each, a country named or a state or province written out
    ("Dublin, Ohio", "London, Ontario") decides it - unless the place's own state code disagrees ("Ontario, CA");
    a city's name decides only when nothing else does; then a remote job's stated region. A place written with a code
    that is a US state's and a country's ("Hopkinton, MA": Massachusetts or Morocco?) is settled by its ZIP code or the
    posting's text - or by what the employer's own hiring system says: the country its job feed gives, or the job page's
    structured data (page: what the extension or the server's browser read there). Any of those that contradicts a place
    leaves the country unclear. "unclear": the towns only such a code leaves open (settle_places can check them)."""
    out = {"country": None, "unclear": [], "by": ""}
    if listing is None:
        return out
    loc = getattr(listing, "location", "") or ""
    try:
        from app.services import job_engine as JE
        from app.services.feed_common import listing_text
        us_states = set(JE.TAX.get("us_states") or [])
        try:
            text = (listing_text(db, listing) or "")[:4000]
        except Exception:
            text = str(getattr(listing, "description", "") or "")[:4000]
        desc = _plain(text)
        got, unclear, n_unclear = set(), [], 0
        for p in _split_places(loc)[:12]:
            if p and p.strip():
                before = len(unclear)
                c = _place_country(p.strip(), JE, us_states, desc, unclear)
                if c is not None:
                    got.add(c)
                if c == "?" and len(unclear) == before:
                    n_unclear += 1          # unclear for another reason ("Cambridge" alone): no place check settles that
        stated = [(by, c) for by, c in (("feed", _feed_country(db, listing)), ("page", _page_country(page, listing))) if c]
        said = {c for _, c in stated}
        if "?" in said or len(said) > 1:
            return out                     # the employer's own data names more than one country
        if got:
            definite = got - {"?"}
            if len(definite) > 1:
                return out                 # places in more than one country
            if "?" not in got:
                c = next(iter(definite))
                if said and said != {c}:
                    return out             # what the employer's system says contradicts the place
                out.update(country=c, by="place")
                return out
            if said and (not definite or definite == said):
                out.update(country=next(iter(said)), by=stated[0][0])
                return out
            out["unclear"] = list(dict.fromkeys(unclear)) if not n_unclear else []
            out["definite"] = sorted(definite)
            return out
        if said:
            out.update(country=next(iter(said)), by=stated[0][0])
            return out
        job = JE.parse_job({"id": str(listing.id), "title": listing.title or "", "org": listing.org or "", "location": loc,
                            "description": text, "type": listing.type or "job"})
        if not (job.get("places") or []) and _REGION_COUNTRY.get(job.get("remoteRegion")):
            out.update(country=_REGION_COUNTRY[job["remoteRegion"]], by="remote")
    except Exception:
        pass
    return out
 
 
def settle_places(db, info, client) -> str | None:
    """The job's country once the towns only an ambiguous code left open are checked (question_reader.place_countries):
    each one has to come out on one side, and every place of the job in the same country. None otherwise."""
    pairs = [(c, k) for c, k in (info.get("unclear") or []) if k in _RISKY_STATE and k in _ISO_OF]
    if not pairs or client is None or len(pairs) != len(info.get("unclear") or []):
        return None
    from app.services import question_reader as QR
    names = {"india": "India", "germany": "Germany", "israel": "Israel", "colombia": "Colombia", "argentina": "Argentina",
             "indonesia": "Indonesia", "morocco": "Morocco", "malta": "Malta"}
    got = QR.place_countries([(c, k, _RISKY_STATE[k].title(), names.get(_ISO_OF[k], _ISO_OF[k].title()), _ISO_OF[k]) for c, k in pairs], client, db)
    found = set(info.get("definite") or [])
    for c, k in pairs:
        v = got.get((c, k))
        if not v:
            return None
        found.add(v)
    return next(iter(found)) if len(found) == 1 else None
 
 
_COUNTRY_UNKNOWN = "Kaidostar can't tell which country this job is in - answer it yourself"
 
 
def answer_form(db, user_id, listing, questions, page=None, client=None, metered=False) -> list:
    """A form's questions answered from the person's own answer bank - by the rules, then (for what the rules can't
    place) with the AI's readings of the questions - about the job's country as the posting, the employer's own
    systems and (when only an ambiguous code leaves it open) a place check say. The extension's /answers and the
    server's own browser both use this, so a form is answered the same way whichever path delivers it. metered: the
    caller already counted this form against the person's daily AI-reading limit."""
    from app.services import question_reader as QR
    bank = load_answers(db, user_id)
    info = job_country_info(db, listing, page)
    country = info["country"]
    qs = questions if isinstance(questions, list) else []
    org = getattr(listing, "org", None) if listing is not None else None
    rules = AA.resolve_all(qs, bank, country, None, org)
    use_ai = client is not None and bank.get("ai", True)
    readings = QR.read_form(qs, rules, bank, client, db, None if metered else user_id) if use_ai else {}
    final = AA.resolve_all(qs, bank, country, readings, org) if readings else rules
    if use_ai and country is None and info.get("unclear") and any(a.get("missing") and a.get("why") == _COUNTRY_UNKNOWN for a in final):
        settled = settle_places(db, info, client)
        if settled:
            final = AA.resolve_all(qs, bank, settled, readings, org)
            for a in final:
                if not a.get("missing") and a.get("key") in AA.WORK_KEYS + ("status",):
                    a["country_by"] = "place check"
    return withhold_learned(final, qs, db)
 
 
def withhold_learned(final, qs, db=None) -> list:
    """An answer you gave on another form is never reused for a question read as one Kaidostar doesn't remember answers to
    (work authorization, citizenship, a voluntary or never-answered question) - whatever its words; and one given where
    the job's country wasn't known, only once its question has been read as none of those. Never raises (when it can't
    check, no remembered answer is used)."""
    from app.services import question_reader as QR
    qs = qs if isinstance(qs, list) else []
    for k, a in enumerate(final):
        if not (isinstance(a, dict) and a.get("learned") and not a.get("missing")):
            continue
        q = qs[k] if k < len(qs) else {}
        why = "Kaidostar can't check the answer you gave on another form just now - answer it yourself"
        try:
            kind = str(a.get("learnedKind") or QR.cached_kind(q, db) or "")
            why = None
            if kind in AA.WORK_READ_KINDS or kind in ("never", "two") or kind.startswith("eeo:"):
                why = "An answer you gave on another form isn't reused for this kind of question - answer it yourself"
            elif a.get("uncountried") and not kind:
                why = "Kaidostar can't tell whether the answer you gave on another form holds where this job is - answer it yourself"
        except Exception:
            pass
        if why:
            final[k] = AA.finish(k, q, {"key": "custom", "missing": True, "why": why})
    return final
 
 
_PRESENT = re.compile(r"^\s*(present|current|now|today|ongoing|-)?\s*$", re.I)
 
 
def build_ctx(db, user_id, profile, rules, tier, now_ms=None, bank=None, state=None) -> dict:
    """Everything the planner needs to know about this person besides the jobs."""
    from app.models.db_models import Application, Listing, Outcome, ResumeEntry
    from app.services import job_engine as JE
    from app.services.tiers import tier_has_feature
    now_ms = now_ms or _now_ms()
    now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    rows = (db.query(Application.listing_id, Application.status, Application.created_at, Application.auto_generated, Listing.org)
            .join(Listing, Application.listing_id == Listing.id)
            .filter(Application.user_id == user_id).all())
    taken, history = {}, []
    start_today = _local_midnight_utc(now, rules)
    week_ago = now - timedelta(days=7)
    made_today = made_week = 0
    for lid, status, created, auto, org in rows:
        taken[str(lid)] = True
        created = to_naive_utc(created)
        if created is not None and created >= now - timedelta(days=HISTORY_DAYS):
            history.append({"orgKey": JE.norm_org(org or "") or "", "at": _ms(created), "status": status or ""})
        if auto and created is not None:
            if created >= start_today:
                made_today += 1
            if created >= week_ago:
                made_week += 1
    current = []
    try:
        for e in db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all():
            if (getattr(e, "entry_type", "") or "work") == "work" and (e.org or "").strip() and _PRESENT.match(e.end_date or ""):
                current.append(e.org.strip())
    except Exception:
        db.rollback()
    contacts = {}
    try:
        for it in _items(db, user_id, "contact", limit=500):
            d = it.data if isinstance(it.data, dict) else {}
            co, nm = str(d.get("company") or "").strip(), str(d.get("name") or "").strip()
            if co and nm:
                contacts.setdefault(co[:120], []).append(nm[:80])
    except Exception:
        db.rollback()
    interviews = 0
    try:
        latest = {}
        for o in db.query(Outcome).filter(Outcome.user_id == user_id).all():
            at = to_naive_utc(o.updated_at)
            k = str(o.listing_id)
            if k not in latest or (at and latest[k][0] and at > latest[k][0]):
                latest[k] = (at, o.status)
        interviews = sum(1 for at, st in latest.values() if st == "interview" and at and at >= now - timedelta(days=45))
    except Exception:
        db.rollback()
    bank = bank if bank is not None else load_answers(db, user_id)
    return {
        "now": now_ms, "tierMax": tier_daily_max(tier), "madeToday": made_today, "madeWeek": made_week,
        "taken": taken, "history": history[-500:], "currentEmployers": current[:10], "contacts": contacts,
        "interviewsActive": interviews,
        "consent": bool(getattr(profile, "auto_submit_consent", False)) and tier_has_feature(tier, "auto_submit"),
        "browserAvailable": browser_available(), "emailReady": email_ready(), "answersMissing": AA.missing_core(bank),
    }
 
 
# ------------------------------------------------------------------ candidates (the person's own Job Search matches)
def invalidate(user_id):
    with _cache_guard:
        _cache.pop(str(user_id), None)
 
 
def candidates_for(db, user_id, profile, rows=None, fresh=False):
    """The jobs Auto may consider, in the shape both planners read: the person's visible Job Search
    matches (every filter and dealbreaker they set already applied), best first, that can still clear
    the lowest possible bar, minus anything they already have an application for. (list, as-of ms)."""
    key = str(user_id)
    if not fresh and rows is None:
        with _cache_guard:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return hit[1], hit[2]
    from app.services import job_engine as JE
    from app.services import job_search as JS
    res = JS.analyze_for_user(db, key, profile, rows=rows, best_first=True, feed_limit=JS.FEED_SERVER_LIMIT)
    taken = JS.applied_listing_ids(db, key, include_undone=True)
    out = []
    for it in res["visible"]:
        fit = it["score"]["fit"]
        if fit is None or fit < AE.FIT_MIN:
            continue
        if taken and any(i in taken for i in JS._group_ids(it)):
            continue
        out.append(AE.candidate_from(it, JE.norm_org))
        if len(out) >= CANDIDATE_LIMIT:
            break
    at = _now_ms()
    with _cache_guard:
        now = time.time()
        for k in [k for k, v in _cache.items() if now - v[0] >= CACHE_TTL_S]:
            _cache.pop(k, None)
        if len(_cache) >= CACHE_MAX:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:len(_cache) - CACHE_MAX + 1]:
                _cache.pop(k, None)
        _cache[key] = (now, out, at)
    return out, at
 
 
# ------------------------------------------------------------------ resumes: the person's own, the best one for the job
_STOP = {"and", "the", "for", "with", "of", "to", "in", "a", "an", "on", "at", "senior", "junior", "lead", "intern", "ii", "iii", "i"}
 
 
def _words(s) -> set:
    return {w for w in re.findall(r"[a-z0-9+#]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}
 
 
def _skill_in(skill, text) -> bool:
    s = (skill or "").strip().lower()
    if not s:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", text) is not None
 
 
def _split_skills(raw) -> list:
    out, seen = [], set()
    for s in re.split(r"[,;\n|]+", raw or ""):
        s = re.sub(r"\s+", " ", s).strip(" .-•*")
        if s and len(s) <= 60 and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:60]
 
 
def _bullets(raw) -> list:
    out = []
    for line in (raw or "").split("\n"):
        line = re.sub(r"^[\s\-•*·]+", "", line).strip()
        if line:
            out.append(line)
    return out[:12]
 
 
def resume_sources(db, user_id, profile) -> list:
    """Every resume the person has: their saved Resume Studio versions and their current resume.
    Each as {source, id, name, at, summary, skills, entries:[{type,title,org,dates,bullets}]}."""
    from app.models.db_models import ResumeDocument, ResumeEntry
    out = []
    try:
        for it in _items(db, user_id, "resume_version", limit=60):
            d = it.data if isinstance(it.data, dict) else {}
            r = d.get("resume") if isinstance(d.get("resume"), dict) else None
            if not r:
                continue
            entries = []
            for e in (r.get("entries") if isinstance(r.get("entries"), list) else [])[:40]:
                if not isinstance(e, dict):
                    continue
                entries.append({"type": str(e.get("type") or "work")[:20], "title": str(e.get("title") or "")[:200], "org": str(e.get("org") or "")[:200],
                                "dates": " - ".join(x for x in [str(e.get("start") or "").strip(), str(e.get("end") or "").strip()] if x),
                                "bullets": [str(b)[:600] for b in (e.get("bullets") if isinstance(e.get("bullets"), list) else []) if isinstance(b, str) and b.strip()][:12]})
            skills = [str(s)[:60] for s in (r.get("skills") if isinstance(r.get("skills"), list) else []) if isinstance(s, str) and s.strip()][:60]
            if not entries and not skills:
                continue
            out.append({"source": "version", "id": str(d.get("id") or it.client_id)[:80], "name": str(d.get("name") or "Saved version")[:80],
                        "at": str(d.get("updated_at") or d.get("created_at") or "")[:40], "summary": str(r.get("summary") or "")[:800],
                        "skills": skills, "entries": entries})
    except Exception:
        db.rollback()
    try:
        rows = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
        rows = sorted(rows, key=lambda e: (getattr(e, "display_order", 0) or 0))
        types = {str(e.id): (e.entry_type or "work") for e in rows}
        doc = db.query(ResumeDocument).filter(ResumeDocument.user_id == user_id).first()
        entries = []
        if doc is not None and isinstance(doc.polished_entries, list) and doc.polished_entries:
            for e in doc.polished_entries[:40]:
                if not isinstance(e, dict):
                    continue
                entries.append({"type": types.get(str(e.get("entry_id")), "work"), "title": str(e.get("title") or "")[:200], "org": str(e.get("org") or "")[:200],
                                "dates": str(e.get("dates") or "")[:60], "bullets": [str(b)[:600] for b in (e.get("bullets") or []) if isinstance(b, str) and b.strip()][:12]})
            summary = str(doc.summary_line or "")[:800]
        else:
            for e in rows[:40]:
                entries.append({"type": e.entry_type or "work", "title": (e.title or "")[:200], "org": (e.org or "")[:200],
                                "dates": " - ".join(x for x in [e.start_date or "", e.end_date or ""] if x), "bullets": _bullets(e.raw_description)})
            summary = ""
        skills = _split_skills(getattr(profile, "skills", "") or "")
        if entries or skills:
            out.append({"source": "document" if (doc is not None and entries and isinstance(doc.polished_entries, list) and doc.polished_entries) else "entries",
                        "id": "current", "name": "Your current resume", "at": "", "summary": summary, "skills": skills, "entries": entries})
    except Exception:
        db.rollback()
    return out
 
 
def _source_text(src) -> str:
    parts = [src.get("summary") or "", ", ".join(src.get("skills") or [])]
    for e in src.get("entries") or []:
        parts += [e.get("title") or "", e.get("org") or ""] + list(e.get("bullets") or [])
    return "\n".join(parts).lower()
 
 
def choose_resume(sources, c, tailor=True) -> dict:
    """Which of the person's own resumes goes with this job, and how its skills line is ordered.
    Never adds a skill or a line: only picks among what they wrote and puts the posting's skills first."""
    job_skills = [s for s in (c.get("skills") or []) if isinstance(s, str) and s.strip()][:20]
    if not sources:
        return {"source": "none", "versionId": None, "versionName": None, "skillsFirst": [], "moved": [], "coverage": {"have": 0, "of": len(job_skills)},
                "changes": ["No resume on file yet - add one in Resume Studio; most application forms require it."]}
    title_words = _words(c.get("title"))
    scored = []
    for i, src in enumerate(sources):
        text = _source_text(src)
        have = [s for s in job_skills if _skill_in(s, text)]
        # a skill named in the skills line itself counts extra: it's what a recruiter's scan (and an ATS
        # keyword match) sees first
        line = ", ".join(src.get("skills") or []).lower()
        listed = [s for s in have if _skill_in(s, line)]
        overlap = len(title_words & _words(" ".join([src.get("name") or ""] + [e.get("title") or "" for e in src.get("entries") or []])))
        # ties go to the current resume (the newest), then the order versions were listed
        scored.append((len(have) * 10 + len(listed) * 4 + overlap * 3 + (1 if src.get("id") == "current" else 0), -i, src, have))
    if not tailor:
        cur = [x for x in scored if x[2].get("id") == "current"]
        best = cur[0] if cur else max(scored, key=lambda x: (x[0], x[1]))
    else:
        best = max(scored, key=lambda x: (x[0], x[1]))
    _, _, src, have = best
    skills = list(src.get("skills") or [])
    moved = []
    if tailor and job_skills:
        wanted = [s for s in skills if any(s.strip().lower() == j.strip().lower() or _skill_in(j, s.lower()) for j in job_skills)]
        if wanted and skills[:len(wanted)] != wanted:
            moved = wanted
        skills = wanted + [s for s in skills if s not in wanted]
    changes = []
    others = [x for x in scored if x[2] is not src]
    if src.get("source") == "version":
        line = "Used your saved version “" + src["name"] + "” - it covers " + str(len(have)) + " of the " + str(len(job_skills)) + " skills this posting names"
        if others:
            line += " (the next best covers " + str(max(len(x[3]) for x in others)) + ")"
        changes.append(line + ".")
    else:
        changes.append("Used your current resume - it covers " + str(len(have)) + " of the " + str(len(job_skills)) + " skills this posting names.")
    if moved:
        changes.append("Skills line now leads with " + ", ".join(moved[:5]) + " - the ones this posting asks for. Nothing was added.")
    missing = [s for s in job_skills if s not in have]
    if missing:
        changes.append("Not on your resume, so not claimed: " + ", ".join(missing[:5]) + ".")
    return {"source": src.get("source"), "versionId": src.get("id"), "versionName": src.get("name"), "skillsFirst": skills[:60], "moved": moved[:10],
            "coverage": {"have": len(have), "of": len(job_skills)}, "changes": changes}
 
 
def resume_docx(db, user_id, profile, pkg_resume) -> bytes | None:
    """The .docx that goes with an application: the chosen resume, its skills in the chosen order.
    Rebuilt from the person's own records at send time (so an edit since is never lost)."""
    try:
        from app.models.db_models import User
        from app.services.resume_docx import generate_resume_document
        sources = resume_sources(db, user_id, profile)
        want = (pkg_resume or {}).get("versionId") or "current"
        src = next((s for s in sources if s.get("id") == want), None) or next((s for s in sources if s.get("id") == "current"), None)
        if src is None:
            return None
        order = [s for s in ((pkg_resume or {}).get("skillsFirst") or []) if s in (src.get("skills") or [])]
        skills = order + [s for s in (src.get("skills") or []) if s not in order]
        user = db.query(User).filter(User.id == user_id).first()
        head = [x for x in [(getattr(profile, "full_name", "") or "").strip(), (user.email if user else "") or "", (getattr(profile, "phone", "") or "").strip()] if x]
        entries = [{"entry_type": {"education": "education", "project": "project", "projects": "project"}.get((e.get("type") or "work").lower(), "work"),
                    "title": e.get("title") or "", "org": e.get("org") or "", "dates": e.get("dates") or "", "bullets": e.get("bullets") or []}
                   for e in src.get("entries") or []]
        return generate_resume_document("  ·  ".join(head), src.get("summary") or None, entries, skills)
    except Exception as e:
        log.warning("Auto: couldn't build a resume file - %s", e)
        return None
 
 
def candidate_identity(db, user_id, profile) -> dict:
    from app.models.db_models import User
    user = db.query(User).filter(User.id == user_id).first()
    full = ((getattr(profile, "full_name", "") or "") if profile else "").strip()
    parts = full.split()
    return {"full_name": full, "first_name": parts[0] if parts else "", "last_name": parts[-1] if len(parts) > 1 else "",
            "email": (user.email if user else "") or "", "phone": ((getattr(profile, "phone", "") or "") if profile else "").strip()}
 
 
# ------------------------------------------------------------------ preparing one application
def _listing(db, listing_id):
    from app.models.db_models import Listing
    return db.query(Listing).filter(Listing.id == listing_id).first()
 
 
def listing_closed_info(db, listing):
    """Closed info when Kaidostar can't vouch the job is still open: an employer feed stopped listing it,
    or its closing date has passed (a day's grace for time zones). Else None."""
    from app.services.feed_common import listing_closed
    info = listing_closed(db, listing)
    if info is not None:
        return info
    d = getattr(listing, "deadline", None)
    d = d.date() if isinstance(d, datetime) else d
    if d is not None and hasattr(d, "year") and d < (utcnow() - timedelta(days=1)).date():
        return {"at": d, "why": "deadline"}
    return None
 
 
def _factor_snapshot(db, profile, listing, text):
    """The older scorer's factor breakdown, kept with each application so Kaidostar can learn which
    signals predict your interviews. No embedding call (cheap). None + dealbreaker flag on a conflict."""
    try:
        from app.services.feed_common import listing_tags
        from app.services.matching import score_listing
        m = score_listing(
            {"type": listing.type, "tags": listing_tags(db, listing, text=text), "title": listing.title, "org": listing.org,
             "location": listing.location, "deadline": listing.deadline.isoformat() if getattr(listing, "deadline", None) else None,
             "description": text, "embedding": None},
            {"northstar": profile.northstar, "final_idea": profile.final_idea or "", "skills": profile.skills or "",
             "dealbreakers": profile.dealbreakers or "", "priorities": profile.priorities or [], "location_pref": profile.location_pref or "",
             "embedding": None})
        if m is None:
            return None, True
        return {**m["factors"], "signal_strength": m.get("signal_strength"), "factors_engaged": m.get("factors_engaged"), "data_quality": m.get("data_quality")}, False
    except Exception:
        return None, False
 
 
def cover_letter_for(db, client, user_id, profile, listing, c, rules, force=False) -> dict:
    """A cover letter only when the posting asks for one (or the person asked for one always, or
    clicked "write one"). Written from the posting and their own words, checked for invented claims."""
    policy = rules.get("coverLetter", "asked")
    if not force and (policy == "never" or (policy == "asked" and not c.get("coverAsked"))):
        return {"text": "", "flagged": [], "generated": False,
                "note": "No cover letter - the posting doesn't ask for one." if policy == "asked" else "No cover letter - you turned them off."}
    if client is None:
        return {"text": "", "flagged": [], "generated": False, "failed": True, "note": "Couldn't write a cover letter just now (AI isn't available)."}
    from app.models.db_models import ResumeEntry
    from app.services.auto_apply import draft_application
    from app.services.feed_common import listing_tags, listing_text
    from app.services.rate_limit import rate_limit_by_tier
    rate_limit_by_tier(db, str(user_id), "application-draft", per_action_limit=200)
    text = listing_text(db, listing)
    entries = [{"title": e.title, "org": e.org, "raw_description": e.raw_description}
               for e in db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()]
    r = draft_application(client, {"title": listing.title, "org": listing.org, "description": text,
                                   "tags": listing_tags(db, listing, text=text), "skill_match_tags": list(c.get("skills") or [])[:12]},
                          {"northstar": profile.northstar, "skills": profile.skills or ""}, entries)
    if "error" in r:
        return {"text": "", "flagged": [], "generated": False, "failed": True, "note": "Couldn't write a cover letter just now."}
    return {"text": r["text"], "flagged": list(r.get("flagged_terms") or []), "generated": True,
            "note": "Cover letter written because " + ("you asked for one" if force else ("the posting asks for one" if policy == "asked" else "you want one with every application")) + "."}
 
 
def send_time(now, rules, extra_days=0) -> datetime:
    """When an approved application goes out: after the person's delay (plus any referral hold),
    moved to Monday 9am their time if they only send on weekdays."""
    t = now + timedelta(minutes=int(rules.get("delayMinutes") or 0), days=int(extra_days or 0))
    if rules.get("sendDays") == "weekdays":
        tz = _tz(rules)
        local = t.replace(tzinfo=timezone.utc).astimezone(tz)
        if local.weekday() >= 5:
            local = (local + timedelta(days=7 - local.weekday())).replace(hour=9, minute=0, second=0, microsecond=0)
            t = local.astimezone(timezone.utc).replace(tzinfo=None)
    return t
 
 
def create_auto_application(db, client, user_id, profile, q, rules, bank, sources, now=None) -> dict:
    """Turns one planned job into an application + its package. Returns {"application_id", "status", ...}
    or {"error": why} (nothing written)."""
    from app.models.db_models import Application
    from app.services.feed_common import listing_text
    from sqlalchemy.exc import IntegrityError
    now = now or utcnow()
    c = q["c"]
    listing = _listing(db, c["id"])
    if listing is None:
        return {"error": "listing_not_found"}
    if listing_closed_info(db, listing) is not None:
        return {"error": "closed"}
    if db.query(Application).filter(Application.user_id == user_id, Application.listing_id == listing.id).first() is not None:
        return {"error": "exists"}
    text = listing_text(db, listing)
    snapshot, dealbreaker = _factor_snapshot(db, profile, listing, text)
    if dealbreaker:
        return {"error": "dealbreaker"}
    try:
        cover = cover_letter_for(db, client, user_id, profile, listing, c, rules)
    except Exception as e:   # a spent daily allowance (429) or a failed call: prepare it without, held for review
        log.info("Auto: cover letter skipped for %s - %s", user_id, e)
        cover = {"text": "", "flagged": [], "generated": False, "failed": True, "note": "Couldn't write a cover letter just now (today's allowance may be used up)."}
    needs = [dict(n) for n in q.get("needs") or []]
    if cover.get("failed"):
        needs.append({"key": "cover_letter", "why": "The posting asks for a cover letter and Kaidostar couldn't write one just now - add one or ask it to try again"})
    if cover.get("flagged"):
        needs.append({"key": "flagged", "why": "The cover letter mentions " + ", ".join(cover["flagged"][:3]) + ", which isn't in the posting or your profile - check it"})
    hold = q.get("hold")
    if rules["mode"] == "auto" and q.get("status") == "send" and not needs:
        status = "approved"
        sendable_at = send_time(now, rules, (hold or {}).get("days") or 0)
    else:
        status, sendable_at = "pending_review", None
    resume = choose_resume(sources, c, rules.get("tailorResume", True))
    if resume["source"] == "none":
        needs.append({"key": "resume", "why": "No resume on file - add one in Resume Studio before this can go out"})
        status, sendable_at = "pending_review", None
    app_id = uuid_module.uuid4()
    app = Application(id=app_id, user_id=user_id, listing_id=listing.id, draft_content=cover["text"], confidence_pct=c["fit"],
                      status=status, sendable_at=sendable_at, auto_generated=True, factors_snapshot=snapshot,
                      counterfactual_confidence_pct=None, draft_flagged_terms=cover["flagged"] or None)
    pkg = {
        "v": 1, "appId": str(app_id), "listingId": str(listing.id), "title": c["title"], "org": c["org"], "orgKey": c["orgKey"],
        "route": c.get("route"), "host": c.get("host"), "applyUrl": listing.apply_url or c.get("applyUrl"), "emailTo": c.get("emailTo") or "",
        "fit": c["fit"], "band": c.get("band"), "confidence": c.get("confidence"), "stretch": bool(c.get("stretch")),
        "ageDays": c.get("ageDays"), "freshness": c.get("freshness"), "ghost": c.get("ghost"),
        "reasons": list(q.get("reasons") or []), "needs": needs, "hold": hold, "contacts": list(q.get("contacts") or []),
        "delivery": dict(q.get("delivery") or {}), "mode": rules["mode"], "delayMinutes": rules["delayMinutes"],
        "resume": resume, "coverLetter": bool(cover["text"]), "coverPolicy": rules.get("coverLetter"), "coverAsked": bool(c.get("coverAsked")),
        "coverNote": cover.get("note", ""), "answersMissing": AA.missing_core(bank),
        "createdAt": _ms(now), "sendAt": _ms(sendable_at), "attempts": [], "sentAt": None, "proof": None,
        "followUp": {"dueAt": None, "notifiedAt": None, "doneAt": None},
    }
    try:
        db.add(app)
        db.add(_W()(user_id=user_id, kind=PACKAGE_KIND, client_id=str(app_id), data=pkg))   # a brand-new record: no lookup needed
        db.commit()
    except IntegrityError:
        db.rollback()   # lost a race with another prepare (or a click) for the same job
        return {"error": "exists"}
    return {"application_id": str(app_id), "status": status, "title": c["title"], "org": c["org"], "sendAt": pkg["sendAt"], "needs": needs}
 
 
# ------------------------------------------------------------------ one pass for one person
def _notify(db, user_id, profile, title, detail=None):
    from app.models.db_models import Notification
    prefs = (getattr(profile, "notification_preferences", None) or {}) if profile is not None else {}
    if prefs.get("auto_apply", True) is False:
        return
    db.add(Notification(user_id=user_id, type="auto_apply", title=title[:250], detail=(detail or None)))
 
 
def _fmt_time(ms, rules) -> str:
    if not ms:
        return ""
    local = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(_tz(rules))
    h = local.hour % 12 or 12
    return f"{local:%a} {h}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"
 
 
def run_pass(db, client, user_id, reason="schedule", now=None, rows=None) -> dict:
    """Prepare what the plan says to prepare now, for one person. Never raises."""
    lock = _user_lock(user_id)
    if not lock.acquire(blocking=False):
        return {"skipped": "busy"}
    try:
        return _run_pass(db, client, str(user_id), reason, now or utcnow(), rows)
    except Exception as e:
        log.exception("Auto pass failed for %s", user_id)
        try:
            db.rollback()
            st = load_state(db, user_id)
            st["lastError"] = type(e).__name__
            st["lastRunAt"] = _now_ms()
            save_state(db, user_id, st)
            db.commit()
        except Exception:
            db.rollback()
        return {"error": type(e).__name__}
    finally:
        lock.release()
 
 
def _run_pass(db, client, user_id, reason, now, rows):
    from app.services.tiers import get_user_tier
    profile = _profile(db, user_id)
    if profile is None or not getattr(profile, "auto_apply_enabled", False):
        return {"skipped": "off"}
    if getattr(profile, "is_athlete", False):
        return {"skipped": "athlete"}
    tier = get_user_tier(db, user_id)
    if tier_daily_max(tier) <= 0:
        st = load_state(db, user_id)   # remembered, so the tick doesn't rebuild the job pool for this person every half hour
        st["lastRunAt"] = _ms(now)
        st["lastSkip"] = "tier"
        save_state(db, user_id, st)
        db.commit()
        return {"skipped": "tier"}
    rules = rules_of(profile)
    bank = load_answers(db, user_id)
    now_ms = _ms(now)
    cands, _ = candidates_for(db, user_id, profile, rows=rows, fresh=True)
    ctx = build_ctx(db, user_id, profile, rules, tier, now_ms, bank)
    plan = AE.plan(cands, rules, ctx)
    sources = resume_sources(db, user_id, profile) if plan["queue"] else []
    made, errors = [], {}
    for q in plan["queue"]:
        try:
            r = create_auto_application(db, client, user_id, profile, q, rules, bank, sources, now)
        except Exception as e:
            db.rollback()
            log.warning("Auto: preparing %s failed - %s", q["c"].get("id"), e)
            r = {"error": "failed"}
        if r.get("error"):
            errors[r["error"]] = errors.get(r["error"], 0) + 1
        else:
            made.append(r)
    if made and rules.get("outreach") and client is not None:
        _auto_outreach(db, client, user_id, made)
    review = [m for m in made if m["status"] == "pending_review"]
    approved = [m for m in made if m["status"] == "approved"]
    summary = AE.plan_summary(plan)
    run = {"at": now_ms, "reason": reason, "created": len(made), "review": len(review), "approved": len(approved),
           "errors": errors, "waiting": summary["waiting"], "held": summary["held"], "heldCounts": summary["heldCounts"],
           "excluded": summary["excluded"], "paused": summary["paused"], "considered": summary["considered"],
           "capacity": summary["capacity"], "titles": [m["title"] + " - " + m["org"] for m in made][:10]}
    st = load_state(db, user_id)
    st["runs"] = (st.get("runs") or [])[-(RUNS_KEPT - 1):] + [run]
    st["lastRunAt"] = now_ms
    st["lastError"] = None
    save_state(db, user_id, st)
    if made:
        parts = []
        if review:
            parts.append(f"{len(review)} wait{'s' if len(review) == 1 else ''} for your review on the Auto page")
        if approved:
            first = min((m["sendAt"] or 0) for m in approved)
            parts.append(f"{len(approved)} approved - going out from {_fmt_time(first, rules)} (undo until then)")
        _notify(db, user_id, profile, f"Auto prepared {len(made)} application{'s' if len(made) != 1 else ''}",
                " · ".join(parts) + ". " + "; ".join(run["titles"][:3]))
    db.commit()
    invalidate(user_id)
    return {"created": len(made), "review": len(review), "approved": len(approved), "errors": errors, "plan": summary}
 
 
def _auto_outreach(db, client, user_id, made):
    """Optional: draft (never send) a referral email per prepared application - the person's choice."""
    from app.services.auto_apply import draft_outreach_for_match
    from app.services.rate_limit import rate_limit_by_tier
    for m in made[:5]:
        try:
            rate_limit_by_tier(db, user_id, "outreach-draft", per_action_limit=40)
            app_listing = _listing_id_of(db, m["application_id"])
            if app_listing:
                draft_outreach_for_match(db, client, user_id, app_listing, auto_generated=True)
        except Exception:
            db.rollback()
            break
 
 
def note_person_approved(db, app_record, send_at=None):
    """You approved this one yourself: what you approved stands (its fit, its letter, a stretch) - the
    unattended send won't hand it back for those again. Best-effort; the caller commits."""
    try:
        pkg = load_package(db, app_record.user_id, app_record.id)
        if pkg is None:
            return
        pkg["approvedAt"] = _now_ms()
        autopilot_release(pkg)       # (approved again: whatever Autopilot was doing with it no longer counts)
        if send_at is not None:
            pkg["sendAt"] = _ms(send_at)
        pkg["needs"] = [n for n in (pkg.get("needs") or []) if isinstance(n, dict) and n.get("key") not in ("fit_dropped", "flagged", "stretch")]
        save_package(db, app_record.user_id, app_record.id, pkg)
    except Exception:
        pass
 
 
def _listing_id_of(db, app_id):
    from app.models.db_models import Application
    a = db.query(Application).filter(Application.id == app_id).first()
    return str(a.listing_id) if a is not None else None
 
 
# ------------------------------------------------------------------ delivery
def _http(url) -> bool:
    return isinstance(url, str) and url.lower().startswith(("http://", "https://"))
 
 
def route_of(url) -> tuple:
    """(route, host) for an apply link - the same classification the engines use."""
    from app.services import job_engine as JE
    m = re.match(r"^https?://([^/?#]+)", url or "", re.I)
    host = (m.group(1) if m else "").lower()
    if not host:
        return "unknown", ""
 
    def on(domains):
        return any(host == d or host.endswith("." + d) for d in domains)
    if on(JE.TAX.get("ats_domains") or []):
        return "employer", host
    if on(JE.TAX.get("aggregator_domains") or []):
        return "aggregator", host
    return "company_site", host
 
 
def _attempt(pkg, channel, status, note, proof=None):
    if pkg is None:
        return
    a = {"at": _now_ms(), "channel": channel, "status": status, "note": (note or "")[:400]}
    if proof:
        a["proof"] = proof
    pkg["attempts"] = (pkg.get("attempts") or [])[-(ATTEMPTS_KEPT - 1):] + [a]
 
 
def mark_sent_package(pkg, rules, sent_ms, proof=None, channel=None):
    if pkg is None:
        return
    pkg["sentAt"] = sent_ms
    if proof:
        pkg["proof"] = proof
    if channel:
        pkg["sentChannel"] = channel
    days = int((rules or {}).get("followUpDays") or 0)
    fu = pkg.get("followUp") if isinstance(pkg.get("followUp"), dict) else {}
    fu.update({"dueAt": sent_ms + days * DAY_MS if days else None, "notifiedAt": None, "doneAt": fu.get("doneAt")})
    pkg["followUp"] = fu
 
 
def _claim(db, app_record, prev) -> bool:
    """Take the application for sending, atomically - so the tick and a click can't both send it."""
    from app.models.db_models import Application
    # sendable_at doubles as "when sending started", so an interrupted send can be told from one in flight
    n = (db.query(Application)
         .filter(Application.id == app_record.id, Application.status == prev)
         .update({Application.status: "sending", Application.sendable_at: utcnow()}, synchronize_session=False))
    db.commit()
    try:
        db.refresh(app_record)
    except Exception:
        pass
    return n == 1
 
 
def deliver_application(db, app_record, listing, client=None, unattended=False, prefer_extension=False) -> dict:
    """The one real delivery path for an approved application - the tick's unattended send and the
    person's own "Send" both come here. Never marks anything sent without a real send; every outcome
    that isn't a send becomes a ready-to-submit hand-off (or a return to review) with the reason.
    prefer_extension: the Kaidostar Apply extension is asking (Autopilot) - a form on an employer's hiring system goes to
    it, to fill in the person's own browser, rather than to this server's browser."""
    prev = app_record.status
    if prev not in ("approved", "ready_to_submit"):
        return {"status": prev, "skipped": True, "reasoning": "This application isn't approved for sending."}
    if prev == "ready_to_submit":
        ho = (load_package(db, app_record.user_id, app_record.id) or {}).get("handoff") or {}
        if isinstance(ho, dict) and ho.get("possiblySent"):
            # it may already have reached the employer: never sent again until you say it didn't go through
            return {"status": prev, "skipped": True, "auto_submit_possibly_sent": True,
                    "reasoning": "This application may already have gone through - check before sending it again."}
    if not _claim(db, app_record, prev):
        return {"status": app_record.status, "skipped": True, "reasoning": "This application is already being sent."}
    uid = app_record.user_id
    pkg = load_package(db, uid, app_record.id)
    box = {"dispatched": False}   # set the moment an email or a form submission actually leaves
    try:
        res = _deliver_claimed(db, app_record, listing, pkg, unattended, box, prefer_extension)
    except Exception as e:
        log.warning("Auto: delivery crashed for %s - %s", app_record.id, e)
        db.rollback()
        if box["dispatched"]:
            res = _handoff(db, app_record, listing, pkg, "error", "Something went wrong right after sending - it may have gone through. Check with the employer before you send it again.",
                           possibly_submitted=True)
        else:
            res = _handoff(db, app_record, listing, pkg, "error", "Something went wrong while sending - here's the finished application to submit yourself.")
    return res
 
 
def _finish(db, app_record, pkg):
    if pkg is not None:
        save_package(db, app_record.user_id, app_record.id, pkg)
    db.commit()
 
 
def _manual_pkg(app_record, listing):
    """A small record for an application Auto didn't prepare, so a may-have-gone-through warning is kept."""
    return {"v": 1, "manual": True, "appId": str(app_record.id), "listingId": str(app_record.listing_id),
            "title": getattr(listing, "title", "") or "", "org": getattr(listing, "org", "") or "", "attempts": [], "sentAt": None, "proof": None,
            "followUp": {"dueAt": None, "notifiedAt": None, "doneAt": None}}
 
 
def _handoff(db, app_record, listing, pkg, key, reasoning, **flags):
    app_record.status = "ready_to_submit"
    app_record.sent_channel = "web"
    if pkg is None and flags.get("possibly_submitted"):
        pkg = _manual_pkg(app_record, listing)
    _attempt(pkg, "handoff", key, reasoning)
    if pkg is not None:
        pkg["handoff"] = {"key": key, "why": reasoning, "possiblySent": bool(flags.get("possibly_submitted")), "at": _now_ms()}
        if flags.get("for_autopilot"):
            pkg["handoff"]["autopilot"] = True      # handed to Autopilot (it said so): the only kind it ever takes
    _finish(db, app_record, pkg)
    out = {"status": "ready_to_submit", "channel": "web", "apply_url": listing.apply_url if listing is not None else None,
           "draft_content": app_record.draft_content, "reasoning": reasoning, "handoff": key}
    if flags.get("for_autopilot"):
        out["for_autopilot"] = True
    if flags.get("posting_closed"):
        out["posting_closed"] = True
    if flags.get("pro_only"):
        out["auto_submit_pro_only"] = True
    if flags.get("consent_needed"):
        out["auto_submit_consent_needed"] = True
    if flags.get("auto_note"):
        out["auto_submit_note"] = flags["auto_note"]
    if flags.get("possibly_submitted"):
        out["auto_submit_possibly_sent"] = True
    if flags.get("email_error"):
        out["email_error"] = True
    return out
 
 
def _back_to_review(db, app_record, pkg, key, why):
    app_record.status = "pending_review"
    app_record.sendable_at = None
    _attempt(pkg, "check", key, why)
    if pkg is not None:
        pkg["needs"] = [n for n in (pkg.get("needs") or []) if n.get("key") != key] + [{"key": key, "why": why}]
    _finish(db, app_record, pkg)
    return {"status": "pending_review", "reasoning": why, "returned": key}
 
 
def _sent(db, app_record, pkg, rules, channel, proof, extra=None):
    now = utcnow()
    app_record.status = "sent"
    app_record.sent_at = now
    app_record.sent_channel = channel
    if channel == "email" and proof and proof.get("to"):
        app_record.sent_to_address = proof["to"]
    _attempt(pkg, channel, "sent", "Sent", proof)
    mark_sent_package(pkg, rules, _ms(now), proof, channel)
    _finish(db, app_record, pkg)
    out = {"status": "sent", "channel": channel, "sent_at": now.isoformat()}
    out.update(extra or {})
    return out
 
 
def _deliver_claimed(db, app_record, listing, pkg, unattended, box=None, prefer_extension=False):
    from app.services.feed_common import closed_note, listing_text
    from app.services.job_search import HAND_ADDED_SOURCES
    from app.services.tiers import get_user_tier, tier_has_feature
    uid = app_record.user_id
    profile = _profile(db, uid)
    rules = rules_of(profile)
    if listing is None:
        return _handoff(db, app_record, listing, pkg, "missing", "This posting is no longer in Kaidostar - check it yourself before applying.")
    if unattended and (getattr(listing, "source", None) or "") in HAND_ADDED_SOURCES:
        return _handoff(db, app_record, listing, pkg, "hand_added",
                        "This listing was added by hand rather than found by a job source, so Kaidostar doesn't send it for you - submit it at the posting.")
    closed = listing_closed_info(db, listing)
    if closed is not None:
        return _handoff(db, app_record, listing, pkg, "closed", closed_note(closed), posting_closed=True)
    # approved by Auto itself (you never looked at it): if its fit fell well below what it was prepared at,
    # your profile or the posting changed - it comes back to you instead of going out
    if unattended and app_record.auto_generated and not (pkg or {}).get("approvedAt") and profile is not None and not getattr(profile, "is_athlete", False):
        ref = (pkg or {}).get("fit")
        if ref is None and app_record.confidence_pct is not None:
            ref = float(app_record.confidence_pct)
        if ref is not None:
            fit = _fit_now(db, uid, profile, listing)
            if fit is None or fit < float(ref) - 5:
                return _back_to_review(db, app_record, pkg, "fit_dropped",
                                       "Its fit is now " + ("unknown" if fit is None else AE._fmt_num(fit)) + " - it was " + AE._fmt_num(ref) + " when prepared, so your profile or the posting changed. Approve it again if you still want it sent.")
    route, host = (pkg.get("route"), pkg.get("host")) if pkg and pkg.get("route") else route_of(listing.apply_url)
    if route == "aggregator":
        return _handoff(db, app_record, listing, pkg, "aggregator",
                        (host or "This") + " is a job board, and Kaidostar never applies for you on job boards - your application is ready to submit yourself.")
    if not _http(listing.apply_url):
        return _handoff(db, app_record, listing, pkg, "no_link", "There's no standard application link - your application is ready to submit yourself.")
    tier = get_user_tier(db, str(uid))
    if not tier_has_feature(tier, "auto_submit"):
        return _handoff(db, app_record, listing, pkg, "pro_only", "Kaidostar submits applications for you on Pro and Max - here's the finished application to submit yourself.", pro_only=True)
    if not (profile is not None and getattr(profile, "auto_submit_consent", False)):
        return _handoff(db, app_record, listing, pkg, "consent", "You haven't let Kaidostar submit applications for you, so it's ready for you to submit.",
                        consent_needed=True, auto_note="Give Kaidostar permission to submit applications for you to turn on automatic submission.")
    # by email only where the posting says so on the company's own site, and only when this server can send it
    if route == "company_site" and email_ready():
        from app.services.job_search import DESC_LIMIT
        # read from the posting now, by today's rules - the same text the plan read (so a preview that said
        # "you click submit" never turns into an email at send time)
        email_to = AE.posting_email((listing_text(db, listing) or "")[:DESC_LIMIT])
        if email_to:
            if not AE.email_trusted({"emailTo": email_to, "org": listing.org, "host": host}):
                return _handoff(db, app_record, listing, pkg, "email_untrusted",
                                "The posting asks for applications by email to " + email_to + ", which doesn't look like the company's own address - check it before you send anything.")
            return _send_by_email(db, app_record, listing, pkg, profile, rules, email_to, box)
    if route != "employer":
        # a company's own careers site may hold other forms (a general "send us your CV", a talent community):
        # Kaidostar never submits there on its own - the extension fills it and you click
        return _handoff(db, app_record, listing, pkg, "extension",
                        "On the company's own careers site, so you make the final click: open it with the Kaidostar Apply extension (it fills the form), or submit it at the posting.")
    if prefer_extension or (not browser_available() and autopilot_live(load_autopilot(db, uid))):
        return _handoff(db, app_record, listing, pkg, "extension", AUTOPILOT_TAKES_WHY, for_autopilot=True)
    if not browser_available():
        return _handoff(db, app_record, listing, pkg, "extension",
                        "Ready for one click: open it with the Kaidostar Apply extension (it fills the form in your browser), or submit it at the posting.")
    return _submit_in_browser(db, app_record, listing, pkg, profile, rules, box)
 
 
AUTOPILOT_TAKES_WHY = ("Handed to Kaidostar Apply's Autopilot, which applies to it on its own in your browser - submitting only if every "
                       "rule passes. To do it yourself instead, open it with the extension (then it's yours), or submit it at the posting "
                       "and click I submitted it.")
 
 
def _fit_now(db, user_id, profile, listing):
    try:
        from app.services.job_search import v2_fit_for_listing
        return v2_fit_for_listing(db, str(user_id), profile, listing)
    except Exception:
        return None
 
 
def _ats_list() -> list:
    from app.services import job_engine as JE
    return [str(d) for d in (JE.TAX.get("ats_domains") or [])]
 
 
def _maybe_delivered(e) -> bool:
    """Did a failed email call possibly reach the provider anyway - a timeout or a dropped connection after
    the request went out, or a server error at the mail service or a gateway in front of it (a 502 or 504
    can come back after the message was accepted)? A refusal (4xx), a bad address, a connection that never
    opened or a missing key never sent anything."""
    try:
        import httpx
        if isinstance(e, httpx.HTTPStatusError):
            code = getattr(getattr(e, "response", None), "status_code", 0) or 0
            return code >= 500
        if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
            return False
        return isinstance(e, (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError))
    except Exception:
        return False
 
 
def _send_by_email(db, app_record, listing, pkg, profile, rules, to, box=None):
    from app.services.email_send import send_email
    from app.services.rate_limit import rate_limit_by_tier
    uid = app_record.user_id
    ident = candidate_identity(db, uid, profile)
    try:
        rate_limit_by_tier(db, str(uid), "application-email", per_action_limit=10)
    except Exception:
        return _handoff(db, app_record, listing, pkg, "email_limit", "You've reached today's limit for applications sent by email - it's ready for you to send yourself.")
    name = ident["full_name"] or ident["email"]
    subject = re.sub(r"[\r\n]+", " ", "Application: " + (listing.title or "the open role") + (" - " + name if name else ""))[:200]
    letter = (app_record.draft_content or "").strip()
    body = ("Hello,\n\n" + (letter + "\n\n" if letter else "I'd like to apply for the " + (listing.title or "open") + " role at " + (listing.org or "your company") + ". My resume is attached.\n\n")
            + "Best regards,\n" + "\n".join(x for x in [ident["full_name"], ident["email"], ident["phone"]] if x))
    attachments = []
    data = resume_docx(db, uid, profile, (pkg or {}).get("resume"))
    if data:
        attachments.append({"filename": (re.sub(r"[^A-Za-z0-9]+", "_", ident["full_name"]).strip("_") or "Resume") + "_Resume.docx",
                            "content": base64.b64encode(data).decode("ascii")})
    if not attachments:
        return _handoff(db, app_record, listing, pkg, "no_resume", "No resume file could be built to attach - add one in Resume Studio, then send it yourself.")
    try:
        if box is not None:
            box["dispatched"] = True
        resp = send_email(to, subject, body, reply_to=ident["email"] or None, attachments=attachments)
    except Exception as e:
        log.warning("Auto: application email failed - %s", e)
        if _maybe_delivered(e):
            return _handoff(db, app_record, listing, pkg, "email_error", "The email may have gone out - the mail service didn't confirm it. Check with the employer before sending it again.",
                            email_error=True, possibly_submitted=True)
        return _handoff(db, app_record, listing, pkg, "email_error", "Couldn't send the email just now - here's the finished application to send yourself.", email_error=True)
    # the provider said yes (2xx): sent, whatever shape its reply had
    rid = resp.get("id") if isinstance(resp, dict) else ""
    proof = {"to": to, "provider_id": str(rid or "")[:80], "subject": subject[:200], "attachment": attachments[0]["filename"]}
    return _sent(db, app_record, pkg, rules, "email", proof, {"to_address": to, "address_is_guess": False})
 
 
# the steps on an employer's site that are only ever yours, and what the hand-off says
PERSON_STEPS = {
    "captcha": "This form has a CAPTCHA - a check that a real person is applying, which only you can do. Open it with the Kaidostar Apply "
               "extension: it fills everything else, waits while you do the check, then you click Submit.",
    "login": "The employer's site asks you to sign in (or create an account) first, which only you can do. Open it with the Kaidostar Apply "
             "extension and sign in - it carries on and fills the application when it appears.",
}
 
 
def _submit_in_browser(db, app_record, listing, pkg, profile, rules, box=None):
    import tempfile
    from app.services.application_submit import submit_application_via_browser
    from app.services.rate_limit import rate_limit_by_tier
    uid = app_record.user_id
    try:
        rate_limit_by_tier(db, str(uid), "application-autosubmit", per_action_limit=40)
    except Exception:
        return _handoff(db, app_record, listing, pkg, "submit_limit", "You've reached today's limit for automatic submissions - it's ready for you to submit.")
    ident = candidate_identity(db, uid, profile)
    data = resume_docx(db, uid, profile, (pkg or {}).get("resume"))
    path = None
    if data:
        fd, path = tempfile.mkstemp(suffix=".docx")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    try:
        if box is not None:
            box["dispatched"] = True     # unknown until the submitter says what it did
        try:
            from app.services.ai_client import get_client
            reader = get_client()
        except Exception:
            reader = None
 
        def answer_fn(questions, page_job):
            # the same answers the extension gets: the bank by the rules, the AI's readings, the job's country
            return answer_form(db, uid, listing, questions, page_job, reader)
        result = submit_application_via_browser(listing.apply_url, ident, resume_path=path, cover_letter=app_record.draft_content or None,
                                                answer_bank=load_answers(db, uid), job_country=job_country_of(db, listing), job_title=listing.title or None,
                                                ats_domains=_ats_list(), answer_fn=answer_fn)
        if box is not None:   # it stopped before submitting (a CAPTCHA, a question it won't guess): nothing went out
            box["dispatched"] = bool(result.get("status") == "submitted" or result.get("submitted_unconfirmed"))
    except Exception as e:
        result = {"status": "error", "reason": str(e)[:200], "submitted_unconfirmed": True}
    finally:
        if path:
            try:
                os.remove(path)
            except Exception:
                pass
    if result.get("status") == "submitted":
        return _sent(db, app_record, pkg, rules, "web_auto", result.get("proof") or {"url": listing.apply_url},
                     {"apply_url": listing.apply_url, "auto_submit_note": result.get("reason", "")})
    if result.get("status") == "unavailable":
        _browser.update(at=time.time(), ok=False)
        return _handoff(db, app_record, listing, pkg, "extension",
                        "Ready for one click: open it with the Kaidostar Apply extension, or submit it at the posting.")
    if result.get("person_step") in PERSON_STEPS and not result.get("submitted_unconfirmed"):
        # a CAPTCHA or a sign-in: a step only you can do - the extension fills the rest and waits for you
        return _handoff(db, app_record, listing, pkg, "person_step", PERSON_STEPS[result["person_step"]], auto_note=result.get("reason", ""))
    if result.get("submitted_unconfirmed"):
        return _handoff(db, app_record, listing, pkg, "needs_you",
                        "Kaidostar submitted the form but didn't see the employer's confirmation - check the posting (or your email) before you submit it again.",
                        auto_note=result.get("reason", ""), possibly_submitted=True)
    return _handoff(db, app_record, listing, pkg, "needs_you", "Kaidostar stopped before submitting: " + (result.get("reason") or "the form needs you") + ".",
                    auto_note=result.get("reason", ""))
 
 
# ------------------------------------------------------------------ Autopilot: the extension applying on its own
# Kaidostar Apply (the extension) can apply for the person by itself, in their own browser: every so often it asks for
# the next application it may take, applies to it in a window of its own - filling the form from the person's profile,
# resume and answer bank, submitting only when every rule passes (an employer's hiring system, no question it would
# have to guess, no CAPTCHA it can find, no sign-in, Kaidostar told first) - and reports what happened. Anything that
# needs the person is left on the Auto page with the reason. One application is the extension's ("leased", with a token
# only that browser holds) while it applies, so two browsers never take the same one; the server's own record of each
# submit attempt stops a second send whatever happens. It only ever takes applications handed to it while it was on -
# never an older kit the person was told to submit themselves (they may have).
AUTOPILOT_KIND_ID = "autopilot"            # (its record: the auto_state kind, a row of its own)
AUTOPILOT_LEASE_MS = 20 * 60 * 1000        # how long one application is the extension's while it applies
AUTOPILOT_TRIES = 2                        # tries on its own before an application is left for the person
AUTOPILOT_PER_DAY = 40                     # applications taken on its own per day (as the server's own browser)
AUTOPILOT_LEASES_PER_DAY = 100             # ... and an absolute ceiling for every plan (a browser in a loop stops there)
AUTOPILOT_RUN_STALE_MS = 2 * 3600 * 1000   # a run that hasn't ended by then is summed up anyway (the browser closed)
AUTOPILOT_LIVE_MS = 2 * 3600 * 1000        # Autopilot counts as running in a browser when it checked in this recently
# what can happen to one it took: sent; left for the person (needs_you - or a submit whose result it never saw,
# unconfirmed); its tab closed (stopped); out of time (timeout); couldn't open it (failed); the person has it open
# themselves, or took it over (yours); never opened after all - Autopilot was stopped first, or couldn't reach it (released)
AUTOPILOT_OUTCOMES = ("sent", "needs_you", "unconfirmed", "stopped", "timeout", "failed", "yours", "released")
AUTOPILOT_STEPS = ("captcha", "login", "account", "question", "site", "page")
YOURS_WHY = "Open in Kaidostar Apply in your browser - finish it there, or submit it at the posting (then click I submitted it)."
UNSURE_WHY = ("Kaidostar Apply clicked submit but didn't see the employer's confirmation - check the posting (or your email) "
              "before you submit it again.")
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
 
 
def _ap_text(v, n=300) -> str:
    return _CTRL.sub(" ", str(v or "")).strip()[:n]
 
 
def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0
 
 
def autopilot_lease_held(pkg, now_ms=None, token=None) -> bool:
    """Is this application Autopilot's right now (it was given it, its time isn't up - and, with token, it's this
    browser's lease)? Only then may the extension open it, or submit it, on its own."""
    lease = pkg.get("autopilot") if isinstance(pkg, dict) and isinstance(pkg.get("autopilot"), dict) else {}
    at = _int(lease.get("leasedAt"))
    if not (at > 0 and (now_ms if now_ms is not None else _now_ms()) - at < AUTOPILOT_LEASE_MS):
        return False
    return token is None or (bool(lease.get("token")) and str(token) == str(lease.get("token")))
 
 
def autopilot_take_over(pkg) -> bool:
    """You opened it yourself (in the extension): it's yours - Autopilot never takes it again, and one it was applying to
    is no longer submitted on its own (its next step, Kaidostar's note of the click, is refused). -> changed"""
    if not isinstance(pkg, dict):
        return False
    changed = False
    lease = pkg.get("autopilot") if isinstance(pkg.get("autopilot"), dict) else None
    if lease is not None and lease.get("leasedAt"):
        lease.pop("leasedAt", None)
        lease.pop("token", None)
        changed = True
    ho = pkg.get("handoff") if isinstance(pkg.get("handoff"), dict) else None
    if ho is not None and ho.get("key") == "extension" and not ho.get("possiblySent"):
        pkg["handoff"] = {"key": "extension_opened", "why": YOURS_WHY, "possiblySent": False, "at": _now_ms()}
        changed = True
    return changed
 
 
def autopilot_release(pkg) -> bool:
    """Its lease is over (you approved it again, say): nothing Autopilot does with it afterwards counts. -> changed"""
    lease = pkg.get("autopilot") if isinstance(pkg, dict) and isinstance(pkg.get("autopilot"), dict) else None
    if lease is None or not lease.get("leasedAt"):
        return False
    lease.pop("leasedAt", None)
    lease.pop("token", None)
    return True
 
 
# Hiring systems whose job page has the application on a page of its own, at a fixed address: Autopilot (and you)
# go straight to it - the same employer, the same job (anything else is opened as it is).
_FORM_URL_RULES = (
    (re.compile(r"^(https://jobs(?:\.eu)?\.lever\.co/[^/?#]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?([?#].*)?$", re.I), "/apply"),
    (re.compile(r"^(https://jobs\.ashbyhq\.com/[^/?#]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?([?#].*)?$", re.I), "/application"),
    (re.compile(r"^(https://apply\.workable\.com/[^/?#]+/j/[0-9A-Za-z]{6,16})/?([?#].*)?$"), "/apply/"),
)
 
 
def application_form_url(apply_url) -> str:
    """The address of a job's application form when its hiring system keeps it on a page of its own ("" if not known)."""
    u = str(apply_url or "").strip()
    for rx, tail in _FORM_URL_RULES:
        m = rx.match(u)
        if m:
            q = m.group(2) or ""
            return m.group(1) + tail + (q.split("#")[0] if q.startswith("?") else "")
    return ""
 
 
def load_autopilot(db, user_id) -> dict:
    row = _get_item(db, user_id, STATE_KIND, AUTOPILOT_KIND_ID)
    return copy.deepcopy(row.data) if row is not None and isinstance(row.data, dict) else {}
 
 
def autopilot_enabled(ap, now_ms=None) -> bool:
    """Autopilot is on for this person: it checked in and was allowed to apply, and hasn't been turned off since."""
    on = _int((ap or {}).get("onSince"))
    return on > 0 and _int((ap or {}).get("offAt")) <= on
 
 
def autopilot_live(ap, now_ms=None) -> bool:
    """On, and running in a browser right now (it checked in lately and was allowed to apply)."""
    ap = ap or {}
    ok = _int(ap.get("okAt"))
    now_ms = now_ms if now_ms is not None else _now_ms()
    return autopilot_enabled(ap) and ok > 0 and now_ms - ok < AUTOPILOT_LIVE_MS and _int(ap.get("offAt")) <= ok
 
 
def autopilot_status(ap, now_ms=None) -> dict:
    """What the Auto page shows: when it last checked in, whether it's applying (and since when it takes applications),
    why not when it isn't, and its last run."""
    ap = ap or {}
    live = autopilot_live(ap, now_ms)
    return {"seenAt": ap.get("seenAt"), "okAt": ap.get("okAt"), "offAt": ap.get("offAt"), "live": bool(live),
            "onSince": ap.get("onSince") if autopilot_enabled(ap) else None, "note": ap.get("note"),
            "last": ap.get("last") if isinstance(ap.get("last"), dict) else None, "maxAgeDays": SEND_MAX_AGE_DAYS}
 
 
def autopilot_will_take(ap, pkg, route, now_ms=None) -> bool:
    """Will Autopilot take this kit on its own? Only one handed to it (its reason said so) while it was on - an
    employer's hiring system, never one that may have gone through - within the days an approval stays fresh."""
    ho = pkg.get("handoff") if isinstance(pkg, dict) and isinstance(pkg.get("handoff"), dict) else {}
    if ho.get("key") != "extension" or ho.get("autopilot") is not True or ho.get("possiblySent") or route != "employer" or not autopilot_enabled(ap):
        return False
    at = _int(ho.get("at"))
    now_ms = now_ms if now_ms is not None else _now_ms()
    return at >= _int(ap.get("onSince")) and now_ms - at <= SEND_MAX_AGE_DAYS * DAY_MS
 
 
def autopilot_step(db, user_id, result=None, run=None, more=True, off=False, on=True) -> dict:
    """What happened to the application Autopilot last applied to (result: {application_id, outcome, reason, step,
    lease}), and the next one it may apply to on its own: an approved application on an employer's hiring system that
    was handed to the extension while Autopilot was on - never one that may already have gone through, one you opened
    yourself, one leased to another browser, or one it has already tried twice. Due approvals are moved along first (to
    the extension, not this server's browser). more=False: only the result - the run is over. off: you turned
    Autopilot off. -> {"next": {"application_id", "title", "org", "lease"} | None, "note": why there's none (when it
    isn't just "nothing ready")}"""
    lock = _user_lock("autopilot:" + str(user_id))
    if not lock.acquire(timeout=20):
        return {"next": None, "note": "Busy - try again in a moment.", "busy": True}
    try:
        return _autopilot_step(db, str(user_id), result, run, more, off or not on)
    except Exception as e:
        log.warning("Autopilot step failed for %s - %s", user_id, e)
        db.rollback()
        return {"next": None, "note": "Something went wrong - it will try again later.", "busy": True}
    finally:
        lock.release()
 
 
def _autopilot_step(db, uid, result, run, more=True, off=False):
    from app.services.tiers import get_user_tier, tier_has_feature
    now = _now_ms()
    profile = _profile(db, uid)
    ap = load_autopilot(db, uid)
    ap.pop("run", None)                          # (a record from before runs were kept per browser)
    runs = ap.get("runs") if isinstance(ap.get("runs"), dict) else {}
    # a run that never ended (its browser closed) is summed up now
    for rid in [k for k, v in runs.items() if not isinstance(v, dict) or now - _int(v.get("at")) > AUTOPILOT_RUN_STALE_MS]:
        _ap_summary(db, uid, profile, ap, runs.pop(rid))
    run_id = _ap_text(run, 40) or "-"
    cur = runs.get(run_id)
    if not isinstance(cur, dict):
        cur = runs[run_id] = {"at": now, "sent": 0, "needs": 0, "unsure": 0, "taken": 0}
    while len(runs) > 6:
        oldest = min(runs, key=lambda k: _int(runs[k].get("at")))
        if oldest == run_id:
            break
        _ap_summary(db, uid, profile, ap, runs.pop(oldest))
    ap["runs"] = runs
    if isinstance(result, dict):
        _ap_result(db, uid, result, cur)
    ap["seenAt"] = now
    if off:
        # (after whatever turned it on - also within the same millisecond)
        ap["offAt"] = max(now, _int(ap.get("onSince")) + 1, _int(ap.get("okAt")) + 1)
    # what happened is saved first: nothing that goes wrong afterwards loses it
    _put_item(db, uid, STATE_KIND, AUTOPILOT_KIND_ID, ap)
    db.commit()
    note = None
    if off:
        note = "Autopilot is off."
    elif profile is None:
        note = "There's no profile to apply with yet."
    elif not tier_has_feature(get_user_tier(db, uid), "auto_submit"):
        note = "Applying for you is part of Pro and Max."
    elif not getattr(profile, "auto_submit_consent", False):
        note = "Let Kaidostar submit applications for you first (Auto page, Settings)."
    elif not getattr(profile, "auto_apply_enabled", False):
        note = "Auto is off - turn it on on the Auto page."
    if note is None:
        if not autopilot_enabled(ap):
            ap["onSince"] = max(now, _int(ap.get("offAt")) + 1)   # (on - again: it takes what's handed to it from now on)
        ap["okAt"] = max(now, _int(ap.get("onSince")))
    ap["note"] = note
    nxt = None
    if note is None and more:
        try:
            _ap_deliver_due(db, uid, profile, ap)
        except Exception as e:
            db.rollback()
            log.info("Autopilot: moving due approvals along failed - %s", e)
        nxt = _ap_pick(db, uid, now, ap)
        if nxt is not None:
            try:
                from app.services.rate_limit import rate_limit, rate_limit_by_tier
                rate_limit(db, uid, "autopilot-lease", limit_per_day=AUTOPILOT_LEASES_PER_DAY)
                rate_limit_by_tier(db, uid, "application-autosubmit", per_action_limit=AUTOPILOT_PER_DAY)
            except Exception as e:
                why = getattr(e, "detail", None)
                nxt, note = None, ("Today's limit is reached - " + str(why).rstrip(".") + "." if isinstance(why, str) and why else
                                   "Today's limit for applications sent for you is reached - the rest wait for tomorrow.")
                ap["note"] = note
        if nxt is not None:
            # (the limits committed: read it again, held until this step commits, and only lease it if it's still free)
            a, l, _ = nxt
            pkg = load_package(db, uid, a.id, locked=True)
            if not _ap_free(pkg, now):
                nxt = None
            else:
                nxt = (a, l, pkg)
    if nxt is not None:
        a, l, pkg = nxt
        lease = pkg.get("autopilot") if isinstance(pkg.get("autopilot"), dict) else {}
        token = uuid_module.uuid4().hex[:24]
        pkg["autopilot"] = {"leasedAt": now, "tries": _int(lease.get("tries")) + 1, "token": token, "run": run_id}
        _attempt(pkg, "web_ext", "autopilot", "Kaidostar Apply is applying to it on its own (Autopilot)")
        save_package(db, uid, a.id, pkg)
        cur["taken"] = _int(cur.get("taken")) + 1
    else:
        _ap_summary(db, uid, profile, ap, runs.pop(run_id, None))   # the run is over: one notification for all of it
    _put_item(db, uid, STATE_KIND, AUTOPILOT_KIND_ID, ap)
    db.commit()
    if nxt is None:
        return {"next": None, "note": note}
    a, l, _ = nxt
    return {"next": {"application_id": str(a.id), "title": l.title or "", "org": l.org or "", "lease": pkg["autopilot"]["token"]}}
 
 
def _ap_result(db, uid, result, cur):
    """Record what happened to one application Autopilot was given - only the one this browser holds (its lease token)."""
    from app.models.db_models import Application
    try:
        aid = str(uuid_module.UUID(str(result.get("application_id") or "")))
    except ValueError:
        return
    a = db.query(Application).filter(Application.id == aid, Application.user_id == uid).first()
    if a is None:
        return
    pkg = load_package(db, uid, a.id, locked=True)
    if not isinstance(pkg, dict):
        return
    lease = pkg.get("autopilot") if isinstance(pkg.get("autopilot"), dict) else {}
    if not lease.get("leasedAt") or not result.get("lease") or str(result.get("lease")) != str(lease.get("token") or ""):
        return                        # not one this browser holds (reported already, or another browser has it now)
    lease.pop("leasedAt", None)
    lease.pop("token", None)
    pkg["autopilot"] = lease
    outcome = str(result.get("outcome") or "")
    if outcome not in AUTOPILOT_OUTCOMES:
        outcome = "failed"
    if outcome == "yours" or (outcome == "released" and not result.get("tried")):
        # it never really tried this one: that isn't one of its tries
        lease["tries"] = max(0, _int(lease.get("tries")) - 1)
    ho = pkg.get("handoff") if isinstance(pkg.get("handoff"), dict) else {}
    if outcome == "sent" and a.status == "sent":
        cur["sent"] = _int(cur.get("sent")) + 1
    elif a.status != "ready_to_submit":
        pass                          # sent another way (you marked it submitted), approved again, or discarded
    elif outcome in ("sent", "unconfirmed") or ho.get("possiblySent"):
        # its submit was clicked and its result never seen (or never recorded): "may have gone through" stays - or is
        # set - for the person to check; never taken or sent again until they say it didn't go through
        if not ho.get("possiblySent"):
            pkg["handoff"] = {"key": "extension_clicked", "why": UNSURE_WHY, "possiblySent": True, "at": _now_ms(), "by": "autopilot"}
            _attempt(pkg, "web_ext", "unconfirmed", UNSURE_WHY)
        cur["unsure"] = _int(cur.get("unsure")) + 1
    elif outcome == "released":
        pass                          # never opened (stopped first, or no connection): back in line as it was
    elif outcome == "yours":
        # open in a tab of yours, or you took it over: yours to finish - Autopilot never takes it again
        if ho.get("key") == "extension":
            pkg["handoff"] = {"key": "extension_opened", "why": YOURS_WHY, "possiblySent": False, "at": _now_ms()}
    else:
        step = str(result.get("step") or "")
        step = step if step in AUTOPILOT_STEPS else ""
        reason = _ap_text(result.get("reason")) or {"timeout": "the page didn't finish in time", "stopped": "its tab was closed"}.get(outcome, "the form needs you")
        why = ("Kaidostar Apply stopped before submitting: " + reason.rstrip(".") + ". Open it with the extension to finish it "
               "(it fills the rest), or submit it at the posting.")
        pkg["handoff"] = {"key": "person_step" if step in ("captcha", "login", "account") else "needs_you", "why": why,
                          "possiblySent": False, "by": "autopilot", "step": step, "at": _now_ms()}
        _attempt(pkg, "web_ext", "needs_you", why)
        cur["needs"] = _int(cur.get("needs")) + 1
    save_package(db, uid, a.id, pkg)
 
 
def _ap_free(pkg, now) -> bool:
    """Still Autopilot's to take: handed to it, not one that may have gone through, not leased right now."""
    if not isinstance(pkg, dict):
        return False
    ho = pkg.get("handoff") if isinstance(pkg.get("handoff"), dict) else {}
    return ho.get("key") == "extension" and ho.get("autopilot") is True and not ho.get("possiblySent") and not autopilot_lease_held(pkg, now)
 
 
def _ap_pick(db, uid, now, ap):
    """The next application Autopilot may take (oldest first): (application, listing, package) or None. Read from the
    person's packages in one query: only kits handed to it while it was on, within the days an approval stays fresh."""
    from app.models.db_models import Application, Listing
    from app.services.feed_common import closed_note
    on_since = _int(ap.get("onSince"))
    if on_since <= 0:
        return None
    ids = []
    for app_id, p in packages_for(db, uid).items():
        ho = p.get("handoff") if isinstance(p.get("handoff"), dict) else {}
        if ho.get("key") != "extension" or ho.get("autopilot") is not True or ho.get("possiblySent"):
            continue                  # (only one handed to Autopilot - never a kit you were told to submit yourself)
        at = _int(ho.get("at"))
        if at < on_since or now - at > SEND_MAX_AGE_DAYS * DAY_MS:
            continue                  # handed over before Autopilot was on (it was yours to submit), or too long ago
        if autopilot_lease_held(p, now):
            continue                  # another browser has it right now
        ids.append(app_id)
    if not ids:
        return None
    rows = (db.query(Application, Listing).join(Listing, Application.listing_id == Listing.id)
            .filter(Application.user_id == uid, Application.status == "ready_to_submit", Application.id.in_(ids[:500]))
            .order_by(Application.created_at.asc()).limit(50).all())
    for a, l in rows:
        # only on an employer's hiring system, where it may submit on its own (elsewhere the click is the person's)
        if not _http(l.apply_url) or route_of(l.apply_url)[0] != "employer":
            continue
        pkg = load_package(db, uid, a.id)
        if not _ap_free(pkg, now):
            continue
        lease = pkg.get("autopilot") if isinstance(pkg.get("autopilot"), dict) else {}
        if _int(lease.get("tries")) >= AUTOPILOT_TRIES:
            # tried on its own twice without finishing (the browser closed, the page never opened): left for the person
            why = "Kaidostar Apply tried this on its own twice and couldn't finish it. Open it with the extension to finish it, or submit it at the posting."
            lease.pop("leasedAt", None)
            lease.pop("token", None)
            pkg["autopilot"] = lease
            pkg["handoff"] = {"key": "needs_you", "why": why, "possiblySent": False, "by": "autopilot", "step": "page", "at": now}
            _attempt(pkg, "web_ext", "needs_you", why)
            save_package(db, uid, a.id, pkg)
            continue
        closed = listing_closed_info(db, l)
        if closed is not None:
            # the posting closed since it was handed over: never applied to
            why = closed_note(closed)
            pkg["handoff"] = {"key": "closed", "why": why, "possiblySent": False, "at": now}
            _attempt(pkg, "check", "closed", why)
            save_package(db, uid, a.id, pkg)
            continue
        return a, l, pkg
    return None
 
 
def _ap_deliver_due(db, uid, profile, ap, limit=5, budget_s=12.0):
    """This person's approvals whose undo window has passed, moved along now (as the tick would) - a form on an
    employer's hiring system goes to the extension that's asking; you're told about the rest as the tick tells you."""
    from app.models.db_models import Application
    t0 = time.monotonic()
    now = utcnow()
    stale_before = now - timedelta(days=SEND_MAX_AGE_DAYS)
    due = (db.query(Application)
           .filter(Application.user_id == uid, Application.status == "approved", Application.sendable_at.isnot(None), Application.sendable_at <= now)
           .order_by(Application.sendable_at.asc()).limit(limit).all())
    c = {"sent": 0, "handoff": 0, "closed": 0, "stale": 0, "review": 0}
    for a in due:
        if time.monotonic() - t0 > budget_s:
            break
        due_at = to_naive_utc(a.sendable_at)
        if due_at is not None and due_at < stale_before:
            continue                  # approved long ago: the tick sends it back for review instead
        res = deliver_application(db, a, _listing(db, a.listing_id), None, unattended=True, prefer_extension=True)
        _count_delivery(c, res, ap)
    _notify_deliveries(db, uid, profile, c)
    db.commit()
 
 
def _ap_summary(db, uid, profile, ap, cur):
    """The end of a run: what it did, kept for the Auto page, and one notification for it."""
    if not isinstance(cur, dict):
        return
    s, n, u = _int(cur.get("sent")), _int(cur.get("needs")), _int(cur.get("unsure"))
    if not (s or n or u):
        return
    ap["last"] = {"at": _now_ms(), "sent": s, "needs": n, "unsure": u}
    if s:
        title = "Kaidostar Apply applied to %d job%s for you" % (s, "" if s == 1 else "s")
    else:
        title = "Kaidostar Apply couldn't finish %d application%s on its own" % (n + u, "" if n + u == 1 else "s")
    parts = []
    if s:
        parts.append("Each one's proof is on the Auto page (Sent).")
    if n:
        parts.append("%d need%s you - the reason is on each one (Needs you)." % (n, "s" if n == 1 else ""))
    if u:
        parts.append("%d may have gone through - check the posting before submitting again." % u)
    _notify(db, uid, profile, title, " ".join(parts))
 
 
# ------------------------------------------------------------------ the tick
def _recover_stuck(db) -> int:
    """An application left "sending" by a crash or restart: never resent blind - handed back, flagged."""
    from app.models.db_models import Application
    cutoff = utcnow() - timedelta(minutes=SENDING_STALE_MIN)
    n = 0
    for a in db.query(Application).filter(Application.status == "sending").limit(200).all():
        started = to_naive_utc(a.sendable_at)
        if started is not None and started > cutoff:
            continue   # still within a normal send's time - may be in flight
        try:
            pkg = load_package(db, a.user_id, a.id) or _manual_pkg(a, _listing(db, a.listing_id))
            a.status = "ready_to_submit"
            a.sent_channel = "web"
            _attempt(pkg, "check", "interrupted", "Sending was interrupted - check the posting before you resubmit, it may have gone through.")
            if pkg is not None:
                pkg["handoff"] = {"key": "interrupted", "why": "Sending was interrupted - it may have gone through. Check before resubmitting.", "possiblySent": True}
            _finish(db, a, pkg)
            n += 1
        except Exception:
            db.rollback()
    return n
 
 
def deliver_due(db, client=None, budget_s=60.0) -> dict:
    """Send approved applications whose undo window has passed (oldest first, within the time budget).
    One that came due long ago goes back for review instead - the posting may be gone, the person may
    have moved on."""
    from app.models.db_models import Application, Profile
    t0 = time.monotonic()
    now = utcnow()
    due = (db.query(Application)
           .filter(Application.status == "approved", Application.sendable_at.isnot(None), Application.sendable_at <= now)
           .order_by(Application.sendable_at.asc()).limit(200).all())
    counts = {}
    aps = {}
    stale_before = now - timedelta(days=SEND_MAX_AGE_DAYS)
    for a in due:
        if time.monotonic() - t0 > budget_s:
            break
        try:
            db.refresh(a)
            if a.status != "approved":
                continue
            uid = a.user_id
            c = counts.setdefault(uid, {"sent": 0, "handoff": 0, "closed": 0, "stale": 0, "review": 0})
            due_at = to_naive_utc(a.sendable_at)
            if due_at is not None and due_at < stale_before:
                a.status = "pending_review"
                a.sendable_at = None
                db.commit()
                c["stale"] += 1
                continue
            if uid not in aps:
                aps[uid] = load_autopilot(db, uid)
            lst = _listing(db, a.listing_id)
            if (autopilot_enabled(aps[uid]) and not browser_available() and lst is not None and _http(lst.apply_url)
                    and route_of(lst.apply_url)[0] == "employer"):
                # Autopilot is on: it moves this one along itself, in the person's browser, the next time it runs
                c["waiting"] = c.get("waiting", 0) + 1
                if due_at is not None and (now - due_at).total_seconds() > AUTOPILOT_WAIT_NOTE_H * 3600:
                    c["waitingLong"] = c.get("waitingLong", 0) + 1
                continue
            res = deliver_application(db, a, _listing(db, a.listing_id), client, unattended=True)
            _count_delivery(c, res, aps[uid])
        except Exception as e:
            db.rollback()
            log.warning("Auto: sending %s skipped - %s", getattr(a, "id", "?"), e)
    if counts:
        try:
            profiles = {str(p.user_id): p for p in db.query(Profile).filter(Profile.user_id.in_(list(counts)), Profile.is_current == True).all()}  # noqa: E712
            for uid, c in counts.items():
                _notify_deliveries(db, uid, profiles.get(str(uid)), c)
                if c.get("waitingLong") and not autopilot_live(aps.get(uid)):
                    _note_autopilot_waiting(db, uid, profiles.get(str(uid)), aps.get(uid) or {}, c["waiting"])
            db.commit()
        except Exception:
            db.rollback()
    return {uid_str: v for uid_str, v in ((str(k), v) for k, v in counts.items())}
 
 
AUTOPILOT_WAIT_NOTE_H = 12      # approvals waiting this long for an Autopilot that isn't running: you're told (once a day)
 
 
def _note_autopilot_waiting(db, uid, profile, ap, n):
    """Approved applications waiting for Autopilot, which hasn't run lately: you're told, at most once a day."""
    now = _now_ms()
    if now - _int(ap.get("waitNotedAt")) < 20 * 3600 * 1000:
        return
    row = _get_item(db, uid, STATE_KIND, AUTOPILOT_KIND_ID, locked=True)     # (its latest, never an old copy)
    fresh = copy.deepcopy(row.data) if row is not None and isinstance(row.data, dict) else {}
    if now - _int(fresh.get("waitNotedAt")) < 20 * 3600 * 1000:
        return
    fresh["waitNotedAt"] = ap["waitNotedAt"] = now
    _put_item(db, uid, STATE_KIND, AUTOPILOT_KIND_ID, fresh)
    _notify(db, uid, profile, f"{n} approved application{'s are' if n != 1 else ' is'} waiting for Autopilot",
            "Kaidostar Apply's Autopilot applies to them on its own while Chrome is open and you're signed in to the extension - "
            "or turn Autopilot off (in the extension, or on the Auto page) to get them as ready-to-submit kits.")
 
 
def _count_delivery(c, res, ap=None):
    """One delivery's outcome, counted for the notification - one Autopilot will take on its own isn't "ready for you"."""
    if res.get("status") == "sent":
        c["sent"] += 1
    elif res.get("posting_closed"):
        c["closed"] += 1
    elif res.get("status") == "ready_to_submit":
        if res.get("for_autopilot"):
            c["autopilot"] = c.get("autopilot", 0) + 1      # Autopilot takes it on its own: not "ready for you"
        else:
            c["handoff"] += 1
    elif res.get("status") == "pending_review":
        c["review"] += 1
 
 
def _notify_deliveries(db, uid, p, c):
    if c.get("sent"):
        _notify(db, uid, p, f"Auto sent {c['sent']} application{'s' if c['sent'] != 1 else ''}", "Each one's proof is on the Auto page (Sent).")
    if c.get("handoff"):
        _notify(db, uid, p, f"{c['handoff']} application{'s are' if c['handoff'] != 1 else ' is'} ready for you to submit",
                "Kaidostar stopped short of sending (the site, a question or a setting needs you) - the reason and a ready kit are on the Auto page.")
    if c.get("review"):
        _notify(db, uid, p, f"{c['review']} approved application{'s' if c['review'] != 1 else ''} came back for your review",
                "Its fit dropped or its cover letter needs a check - see the Auto page.")
    if c.get("stale"):
        _notify(db, uid, p, f"{c['stale']} approved application{'s' if c['stale'] != 1 else ''} need{'' if c['stale'] != 1 else 's'} your OK again",
                f"Approved more than {SEND_MAX_AGE_DAYS} days ago and never sent - check the posting is still open, then approve again.")
    if c.get("closed"):
        _notify(db, uid, p, f"{c['closed']} approved application{'s' if c['closed'] != 1 else ''} not sent: the job may have closed",
                "Kaidostar can no longer confirm the posting is open, so nothing was sent.")
 
 
def follow_ups_due(db, user_id, profile=None) -> int:
    """One reminder per sent application when its follow-up date arrives (you send the note yourself)."""
    from app.models.db_models import Application, Outcome
    now_ms = _now_ms()
    rows = [r for r in _items(db, user_id, PACKAGE_KIND, limit=2000) if isinstance(r.data, dict)]
    due = []
    for r in rows:
        fu = r.data.get("followUp") if isinstance(r.data.get("followUp"), dict) else {}
        if fu.get("dueAt") and fu["dueAt"] <= now_ms and not fu.get("notifiedAt") and not fu.get("doneAt"):
            due.append(r)
    if not due:
        return 0
    outcomes = {}
    for o in db.query(Outcome).filter(Outcome.user_id == user_id).all():
        outcomes[str(o.listing_id)] = o.status
    n = 0
    names = []
    for r in due:
        d = copy.deepcopy(r.data)
        st = outcomes.get(str(d.get("listingId")))
        d["followUp"]["notifiedAt"] = now_ms
        if st and st != "applied":   # they already heard back - no nudge needed
            d["followUp"]["doneAt"] = now_ms
        else:
            n += 1
            names.append((d.get("title") or "a role") + " at " + (d.get("org") or "the company"))
        r.data = d
        try:
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(r, "data")
        except Exception:
            pass
    if n:
        _notify(db, user_id, profile if profile is not None else _profile(db, user_id),
                f"Time to follow up on {n} application{'s' if n != 1 else ''}", "; ".join(names[:3]) + " - a ready note is on the Auto page (Sent).")
    db.commit()
    return n
 
 
def users_due(db, now_ms=None) -> list:
    """People with Auto on whose last pass is older than PASS_HOURS, oldest first."""
    from app.models.db_models import Profile
    now_ms = now_ms or _now_ms()
    ids = [p.user_id for p in db.query(Profile).filter(Profile.is_current == True, Profile.auto_apply_enabled == True).all()  # noqa: E712
           if not getattr(p, "is_athlete", False)]
    if not ids:
        return []
    W = _W()
    last = {}
    for r in db.query(W).filter(W.kind == STATE_KIND, W.client_id == "singleton", W.user_id.in_(ids)).all():
        d = r.data if isinstance(r.data, dict) else {}
        last[str(r.user_id)] = d.get("lastRunAt") or 0
    due = [(last.get(str(u), 0) or 0, str(u)) for u in ids if (last.get(str(u), 0) or 0) <= now_ms - PASS_HOURS * 3600 * 1000]
    return [u for _, u in sorted(due)]
 
 
def run_tick(budget_s=None, session_factory=None) -> dict:
    """One Auto tick: recover interrupted sends, send what's due, follow-up reminders, then passes for
    the people who are due one (oldest first) within the time budget. Never raises."""
    if not _tick_lock.acquire(blocking=False):
        return {"ran": False, "reason": "a tick is already running"}
    db = None
    out = {"ran": True}
    try:
        if session_factory is None:
            from app.db import SessionLocal
            session_factory = SessionLocal
        db = session_factory()
        budget = float(budget_s or TICK_BUDGET_S)
        t0 = time.monotonic()
        from app.services.ai_client import get_client
        client = get_client()
        try:
            out["recovered"] = _recover_stuck(db)
        except Exception:
            db.rollback()
        try:
            out["delivered"] = deliver_due(db, client, budget_s=budget * 0.5)
        except Exception as e:
            db.rollback()
            log.warning("Auto: delivery pass failed - %s", e)
        passes = 0
        try:
            due = users_due(db)
        except Exception:
            db.rollback()
            due = []
        rows = None
        if due:
            try:   # the shared listing pool, built once for every pass in this tick
                from app.services.job_search import pool_dicts
                rows = pool_dicts(db)
            except Exception:
                db.rollback()
                rows = None
        for uid in due:
            if time.monotonic() - t0 > budget:
                break
            try:
                follow_ups_due(db, uid)
            except Exception:
                db.rollback()
            run_pass(db, client, uid, reason="schedule", rows=rows)
            passes += 1
        out["passes"] = passes
        out["waiting"] = max(0, len(due) - passes)
        return out
    except Exception as e:
        log.exception("Auto tick failed")
        out.update(ran=False, error=type(e).__name__)
        return out
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        _tick_lock.release()
 
