"""Auto's answer bank - your own answers to the questions application forms ask,
and the resolver that matches a form's questions to them.
 
The rule is "stop rather than guess". A question is only ever answered from
something you told Kaidostar yourself (the bank on the Auto page, or a custom
question/answer you added). Anything else - and anything Kaidostar never answers
for anyone (signatures and consent boxes, salary history, date of birth,
criminal-history or background-check questions) - is left for you, and an
automatic submission stops there. Voluntary equal-opportunity questions (gender,
race/ethnicity, veteran, disability) default to "I decline to self-identify"
when the form offers that choice; you can tell Kaidostar to leave them for you
or give your own answer.
 
Pure: no database, no network.
"""
from __future__ import annotations
 
import re
 
BANK_VERSION = 1
YESNO_KEYS = ("workAuth", "sponsorship", "citizen", "over18", "relocate", "onsite", "clearance")
TEXT_KEYS = ("startDate", "notice", "salary", "years", "location", "linkedin", "github", "portfolio", "website", "howHeard", "workCountry")
EEO_KEYS = ("gender", "race", "veteran", "disability")
TEXT_CHARS = 120
CUSTOM_CAP = 30
LABELS = {
    "workAuth": "work authorization", "sponsorship": "sponsorship", "citizen": "citizenship", "over18": "age 18+",
    "relocate": "relocation", "onsite": "on-site work", "clearance": "security clearance", "startDate": "start date",
    "notice": "notice period", "salary": "desired pay", "years": "years of experience", "location": "current location",
    "linkedin": "LinkedIn", "github": "GitHub", "portfolio": "portfolio", "website": "website", "howHeard": "how you heard about the job",
    "workCountry": "countries you can work in",
    "gender": "gender (voluntary)", "race": "race/ethnicity (voluntary)", "veteran": "veteran status (voluntary)", "disability": "disability (voluntary)",
}
# asked by almost every form ("Are you legally authorized to work in the United States?" needs to know which
# countries your answers are about) - Auto asks you for these before it relies on a form
CORE_KEYS = ("workAuth", "sponsorship", "workCountry")
CORE_LABELS = {"workAuth": "work authorization", "sponsorship": "sponsorship", "workCountry": "work-country"}
 
 
def default_bank() -> dict:
    return {
        "v": BANK_VERSION,
        **{k: "" for k in YESNO_KEYS},
        **{k: "" for k in TEXT_KEYS},
        "eeo": {k: "decline" for k in EEO_KEYS},
        "custom": [],
    }
 
 
def _clean(s, n=TEXT_CHARS) -> str:
    if not isinstance(s, str):
        return ""
    t = re.sub(r"\s+", " ", s).strip()
    return t[:n].strip()
 
 
def norm_bank(raw) -> dict:
    """Any stored or submitted bank -> the well-formed shape, every value bounded."""
    out = default_bank()
    r = raw if isinstance(raw, dict) else {}
    for k in YESNO_KEYS:
        v = r.get(k)
        out[k] = v if v in ("yes", "no") else ""
    for k in TEXT_KEYS:
        out[k] = _clean(r.get(k))
    for k in ("linkedin", "github", "portfolio", "website"):
        v = out[k]
        if v and not re.match(r"^https?://[^\s/$.?#].[^\s]*$", v, re.I):
            out[k] = ""
    eeo = r.get("eeo") if isinstance(r.get("eeo"), dict) else {}
    for k in EEO_KEYS:
        v = eeo.get(k)
        if v in ("decline", "ask"):
            out["eeo"][k] = v
        elif isinstance(v, str) and _clean(v, 60):
            out["eeo"][k] = _clean(v, 60)
        else:
            out["eeo"][k] = "decline"
    custom, seen = [], set()
    for c in (r.get("custom") if isinstance(r.get("custom"), list) else []):
        if not isinstance(c, dict):
            continue
        q, a = _clean(c.get("q"), 160), _clean(c.get("a"), 300)
        k = _norm(q)
        if len(k) < 6 or not a or k in seen:
            continue
        seen.add(k)
        custom.append({"q": q, "a": a})
        if len(custom) >= CUSTOM_CAP:
            break
    out["custom"] = custom
    return out
 
 
def missing_core(bank) -> list:
    """Human labels of the answers most forms ask for that the bank doesn't have yet."""
    b = norm_bank(bank)
    return [CORE_LABELS[k] for k in CORE_KEYS if not b.get(k)]
 
 
def coverage(bank) -> dict:
    b = norm_bank(bank)
    keys = list(YESNO_KEYS) + ["startDate", "salary", "years", "location", "linkedin", "howHeard"]
    have = [k for k in keys if b.get(k)]
    return {"have": len(have), "of": len(keys), "missing": [LABELS[k] for k in keys if not b.get(k)]}
 
 
# ------------------------------------------------------------------ classifying a question
def _norm(s) -> str:
    return re.sub(r"[^a-z0-9+]+", " ", (s or "").lower().replace("’", "'").replace("'", "")).strip()
 
 
def _has(t, *phrases) -> bool:
    return any(re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", t) for p in phrases)
 
 
NEVER = (
    "social security", "ssn", "date of birth", "birth date", "birthdate", "dob", "year of birth", "birth year", "how old are you", "your age",
    "criminal", "convicted", "conviction", "convictions", "felony", "felonies", "misdemeanor", "misdemeanors", "arrest", "arrested", "arrests",
    "crime", "crimes", "guilty", "offense", "offence", "offenses", "offences", "sentenced", "probation", "parole", "incarcerated",
    "incarceration", "charged with", "pending charges", "background check", "drug test", "drug screen",
    # signatures and statements you sign: certifications, attestations, declarations, consents
    "signature", "sign here", "e signature", "electronic signature", "digital signature", "esignature",
    "i agree", "you agree", "agree to the", "i certify", "certify that", "i attest", "attest", "i hereby", "hereby", "i declare", "declare that",
    "i affirm", "affirm", "i swear", "penalty of perjury", "true and complete", "true and correct", "true and accurate", "accurate and complete",
    "complete and accurate", "correct and complete", "i authorize", "i authorise", "authorize", "authorise", "i acknowledge", "acknowledge",
    "i confirm", "i understand", "i accept", "i have read", "read and understood", "by checking", "by clicking", "by submitting",
    "attestation", "attestations", "certification", "certifications", "declaration", "declarations", "acknowledgment", "acknowledgement",
    "acknowledgments", "acknowledgements", "affirmation", "signed statement", "statement of truth", "under penalty", "i warrant",
    "terms", "privacy policy", "privacy notice", "consent", "gdpr",
    "salary history", "current salary", "previous salary", "current compensation", "prior compensation", "past salary",
    "references", "reference name", "password", "national insurance", "passport", "drivers license number", "license number",
    "bank account", "credit card", "tax id", "sin number", "medical", "pregnant", "pregnancy", "pregnancies", "marital", "religion", "religious",
    "genetic", "workers compensation", "health condition", "illness", "injury", "injuries", "maiden name",
)
 
# A yes/no answer means something only for the question it was given for. "Without sponsorship" turns a
# work-authorization question into "authorized AND never needing sponsorship"; any other negation or a second
# clause ("authorized, or will you need a visa?") is a question Kaidostar can't read safely - it's left for you.
_NEG_RE = re.compile(r"(?<![a-z0-9])(?:not|no|without|never|unable|cannot|cant|dont|doesnt|wont|wouldnt|isnt|arent|neither|nor)(?![a-z0-9])")
_NEG_IGNORE_RE = re.compile(r"(?<![a-z0-9])(?:yes or no|yes no|y n|if not|if no|if yes|if so|or not)(?![a-z0-9])")
_SPONSOR_KIND = r"(?:(?:current or future|now or in the future|now or in future|future|any|visa|employer|employment|company|immigration|work visa|h 1b|h1b) )*"
_NO_SPONSOR_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    r"without (?:the |any )?(?:(?:need(?:ing)?|requirement) (?:for |of )?|requiring |require |needing )?" + _SPONSOR_KIND + r"sponsor(?:ship|ed)?"
    r"|(?:do|does|will|would|shall|can|could)(?: you| i)? not (?:now or in the future |now or in future |currently |ever |presently )?(?:require|need) "
    + _SPONSOR_KIND + r"sponsor(?:ship)?"
    r"|not (?:requiring|needing) " + _SPONSOR_KIND + r"sponsor(?:ship)?"
    r"|no (?:need (?:for|of) )?" + _SPONSOR_KIND + r"sponsorship(?: (?:required|needed|necessary))?"
    r"|(?:independent(?:ly)?|regardless) of " + _SPONSOR_KIND + r"sponsorship"
    r")(?![a-z0-9])")
# "authorized ... for any employer / without restrictions": yes only for someone who never needs sponsorship
_UNRESTRICTED_RE = re.compile(r"(?<![a-z0-9])(?:without (?:any )?(?:restrictions?|limitations?)|unrestricted|no restrictions?"
                              r"|(?:for )?any (?:(?:u s|us|american|united states) )?(?:employer|company|organization|organisation))(?![a-z0-9])")
# "permanently authorized", "permanent work authorization", "indefinitely": yes only for a citizen (a permanent resident,
# or someone on a temporary permit, answers it themselves - the bank doesn't say which they are)
_PERMANENT_RE = re.compile(r"(?<![a-z0-9])(?:permanent(?:ly)?|indefinite(?:ly)?|citizens?|citizenship|green card|green card holders?|lawful permanent)(?![a-z0-9])")
_SPONSOR_WORD_RE = re.compile(r"(?<![a-z0-9])(?:sponsor|sponsors|sponsored|sponsoring|sponsorship|visa|visas|h 1b|h1b)(?![a-z0-9])")
 
 
def _negations(t) -> int:
    return len(_NEG_RE.findall(_NEG_IGNORE_RE.sub(" ", t)))
 
 
def _without_match(t, rx):
    m = rx.search(t)
    return (t[:m.start()] + " " + t[m.end():]) if m else None
 
 
def _auth_kind(t) -> str:
    """A work-authorization question: plain ("authorized to work in the US?"), or "authorized without ever
    needing sponsorship" (the yes that only someone who never needs sponsorship can give), or "permanently
    authorized" (a citizen's yes), or unclear."""
    if _PERMANENT_RE.search(t):
        rest = _PERMANENT_RE.sub(" ", t)
        return "authUnclear" if (_negations(rest) or _SPONSOR_WORD_RE.search(rest)) else "authPermanent"
    rest = _without_match(t, _NO_SPONSOR_RE)
    if rest is not None or _UNRESTRICTED_RE.search(t):
        rest = _UNRESTRICTED_RE.sub(" ", t if rest is None else rest)
        if _negations(rest) or _SPONSOR_WORD_RE.search(rest):
            return "authUnclear"
        return "authNoSponsor"
    if _SPONSOR_WORD_RE.search(t) or _negations(t):
        return "authUnclear"     # authorization and sponsorship (or a "not") in one question
    return "workAuth"
 
 
def _sponsor_kind(t) -> str:
    """A sponsorship question: "will you require sponsorship?" (yes = you need it), its negation ("can you work
    without sponsorship?", "I do not require sponsorship": yes = you never need it), or unclear."""
    rest = _without_match(t, _NO_SPONSOR_RE)
    if rest is not None:
        return "sponsorUnclear" if (_negations(rest) or _SPONSOR_WORD_RE.search(rest)) else "authNoSponsor"
    if _negations(t):
        return "sponsorUnclear"
    # your answer is whether you NEED sponsorship - never "have you ever been sponsored?" or "are you on a
    # sponsored visa?", which ask something else
    if not _has(t, "require", "requires", "required", "requiring", "need", "needs", "needed", "needing"):
        return "sponsorUnclear"
    return "sponsorship"
 
 
# a free-text box takes a bare "Yes"/"No" only when it asks a yes/no question ("Are you...?", "Do you...?") -
# never "Which countries can you work in?" or "Work authorization status"
_YN_START_RE = re.compile(r"^(?:are|do|does|did|will|would|have|has|had|can|could|is|was|were|may|shall|should|i am|i will|i have|i do)(?![a-z0-9])")
_YN_NOT_RE = re.compile(r"(?<![a-z0-9])(?:what|which|where|when|why|how|who|whom|whose|list|explain|describe|specify|detail|details|provide|elaborate"
                        r"|if yes|if so|if no|if not|please state|tell us|type of|kind of)(?![a-z0-9])")
 
 
# a label that holds a note and a question ("This role is not eligible for sponsorship. Will you require
# sponsorship?") is classified by its question - the note's "not" is the employer's, not the question's
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"\u201c])")
 
 
def _question_part(label) -> str:
    s = str(label or "").strip()
    if "?" not in s:
        return s
    qs = [x for x in _SENTENCE_SPLIT.split(s) if "?" in x]
    return qs[0] if len(qs) == 1 else s
 
 
def _yes_no_question(t) -> bool:
    return bool(_YN_START_RE.match(t)) and not _YN_NOT_RE.search(t)
 
 
COUNTRIES = {
    # a visa or work-permit term that only exists in the US names the US too ("H-1B", "green card", "USCIS"...)
    "us": ("united states", "u s", "usa", "u s a", "america", "united states of america", "h 1b", "h1b", "green card", "uscis", "e verify", "everify"),
    "canada": ("canada",), "uk": ("united kingdom", "u k", "britain", "great britain", "england", "scotland", "wales"),
    "ireland": ("ireland",), "germany": ("germany",), "france": ("france",), "netherlands": ("netherlands", "holland"),
    "spain": ("spain",), "italy": ("italy",), "portugal": ("portugal",), "india": ("india",), "australia": ("australia",),
    "new zealand": ("new zealand",), "singapore": ("singapore",), "japan": ("japan",), "mexico": ("mexico",), "brazil": ("brazil",),
    "eu": ("eu", "european union", "europe", "eea"), "israel": ("israel",), "switzerland": ("switzerland",), "sweden": ("sweden",),
    "poland": ("poland",), "denmark": ("denmark",), "norway": ("norway",), "finland": ("finland",), "belgium": ("belgium",),
    "austria": ("austria",), "south africa": ("south africa",), "hong kong": ("hong kong",), "china": ("china",),
    "korea": ("south korea", "korea"), "philippines": ("philippines",), "nigeria": ("nigeria",), "uae": ("uae", "united arab emirates"),
    "pakistan": ("pakistan",), "bangladesh": ("bangladesh",), "sri lanka": ("sri lanka",), "nepal": ("nepal",), "colombia": ("colombia",),
    "argentina": ("argentina",), "chile": ("chile",), "peru": ("peru",), "ecuador": ("ecuador",), "uruguay": ("uruguay",), "costa rica": ("costa rica",),
    "panama": ("panama",), "guatemala": ("guatemala",), "egypt": ("egypt",), "morocco": ("morocco",), "kenya": ("kenya",), "ghana": ("ghana",),
    "turkey": ("turkey", "turkiye"), "greece": ("greece",), "czechia": ("czechia", "czech republic"), "slovakia": ("slovakia",), "hungary": ("hungary",),
    "romania": ("romania",), "bulgaria": ("bulgaria",), "croatia": ("croatia",), "slovenia": ("slovenia",), "serbia": ("serbia",), "ukraine": ("ukraine",),
    "lithuania": ("lithuania",), "latvia": ("latvia",), "estonia": ("estonia",), "luxembourg": ("luxembourg",), "malta": ("malta",), "cyprus": ("cyprus",),
    "iceland": ("iceland",), "saudi arabia": ("saudi arabia",), "qatar": ("qatar",), "indonesia": ("indonesia",), "malaysia": ("malaysia",),
    "thailand": ("thailand",), "vietnam": ("vietnam", "viet nam"), "taiwan": ("taiwan",),
}
 
 
COUNTRY_NAMES = {"us": "the US", "uk": "the UK", "eu": "the EU", "uae": "the UAE"}
EU_MEMBERS = ("germany", "france", "netherlands", "spain", "italy", "portugal", "ireland", "sweden", "poland", "denmark", "finland", "belgium", "austria",
              "greece", "czechia", "slovakia", "hungary", "romania", "bulgaria", "croatia", "slovenia", "lithuania", "latvia", "estonia", "luxembourg",
              "malta", "cyprus")
# what people type in their own list: "US", "UK", "EU" mean those countries there (in a question, "us" is just a word)
_BARE_COUNTRY = {"us": "us", "usa": "us", "u s": "us", "u s a": "us", "america": "us", "uk": "uk", "u k": "uk", "gb": "uk", "eu": "eu", "eea": "eu"}
 
 
def country_name(k) -> str:
    return COUNTRY_NAMES.get(k, k.title())
 
 
# places whose names hold another country's name: New Mexico is in the US, New South Wales in Australia,
# Northern Ireland in the UK
_COUNTRY_INSIDE = ((re.compile(r"(?<![a-z0-9])(?:new mexico|new england)(?![a-z0-9])"), " united states "),
                   (re.compile(r"(?<![a-z0-9])new south wales(?![a-z0-9])"), " australia "),
                   (re.compile(r"(?<![a-z0-9])northern ireland(?![a-z0-9])"), " united kingdom "))
 
 
def countries_in(text) -> set:
    """The countries a question (or your list) names. "us" only counts as the United States after "the"/"in"."""
    t = _norm(text)
    for rx, repl in _COUNTRY_INSIDE:
        t = rx.sub(repl, t)
    out = set()
    for k, aliases in COUNTRIES.items():
        if _has(t, *aliases):
            out.add(k)
    if re.search(r"(?<![a-z0-9])(?:the|in) us(?![a-z0-9])", t):
        out.add("us")
    return out
 
 
def bank_countries(text) -> set:
    """The countries in your answer bank's list ("United States, Canada", "US / UK", "EU")."""
    out = set()
    for item in re.split(r"[,;/&|]+|(?<![a-z])(?:and|or)(?![a-z])", (text or "").lower()):
        n = _norm(item)
        if not n:
            continue
        if n in _BARE_COUNTRY:
            out.add(_BARE_COUNTRY[n])
        else:
            out |= countries_in(item)
    return out
 
 
def _covered(named, mine) -> bool:
    return bool(mine) and all(n in mine or (n in EU_MEMBERS and "eu" in mine) for n in named)
 
 
_GENERIC_YEARS = re.compile(r"^(?:total )?(?:number of )?years of (?:relevant |professional |work |industry )?experience(?: do you have)?$|"
                            r"^how many years of (?:relevant |professional |work |industry )?experience do you have$")
 
 
_AUTH_PHRASES = ("authorized to work", "authorised to work", "legally authorized", "legally authorised", "eligible to work",
                 "right to work", "work authorization", "work authorisation", "permitted to work", "legally able to work", "legally eligible")
# a note that tells you how to answer ("if you will need sponsorship, answer No") changes the question
_NOTE_COND_RE = re.compile(r"(?<![a-z0-9])(?:if|unless|only|when|except|whether)(?![a-z0-9])")
_NOTE_INSTR_RE = re.compile(r"(?<![a-z0-9])(?:answer|select|choose|pick|mark|check|tick|respond|reply|indicate|say|state|enter|only if|only when)(?![a-z0-9])")
 
 
def classify(label) -> str:
    t = _norm(label)
    if not t:
        return ""
    if _has(t, *NEVER):
        return "never"       # a signature, consent or sensitive question anywhere in it
    q = _question_part(label)
    note_unclear = False
    if q != str(label or "").strip():
        tq, rest = _norm(q), _norm(str(label).replace(q, " "))
        # the note is read with the question when it says how to answer, or brings visas or temporary permits into a
        # work-authorization question ("Do not include OPT or CPT") - then the whole label decides, and an unclear
        # one is left for you. Otherwise it's the employer's own note ("we don't sponsor") and the question decides.
        changes = _NOTE_INSTR_RE.search(rest) or (_has(tq, *_AUTH_PHRASES) and (
            _SPONSOR_WORD_RE.search(rest) or _has(rest, "opt", "cpt", "ead", "f 1", "j 1", "work permit", "temporary", "permanent", "permanently",
                                                  "citizen", "citizens", "citizenship", "green card", "permanent resident", "status", "i e", "e g")))
        if not changes:
            t = tq or t
        elif _NOTE_INSTR_RE.search(rest) and _NOTE_COND_RE.search(rest):
            # "answer Yes if you're on a TN visa", "select No unless...": a condition your answer bank can't check
            note_unclear = True
    if _has(t, "sexual orientation", "orientation", "lgbt", "lgbtq", "lgbtqia", "transgender"):
        return "eeo:other"
    if _has(t, "gender", "sex", "pronouns", "pronoun"):
        return "eeo:gender"
    if _has(t, "race", "ethnicity", "ethnic", "hispanic", "latino", "latinx", "latina"):
        return "eeo:race"
    if _has(t, "veteran", "protected veteran", "military service", "armed forces"):
        return "eeo:veteran"
    if _has(t, "disability", "disabled", "handicap"):
        return "eeo:disability"
    if _has(t, *_AUTH_PHRASES):
        return "authUnclear" if note_unclear else _auth_kind(t)
    if _has(t, "sponsor", "sponsors", "sponsored", "sponsoring", "sponsorship") or (
            _has(t, "visa", "h 1b", "h1b", "immigration") and _has(t, "require", "requires", "need", "needs", "requiring", "needing")):
        return "sponsorUnclear" if note_unclear else _sponsor_kind(t)
    if _has(t, "citizen", "citizenship"):
        return "citizenPR" if _has(t, "permanent resident", "green card", "lawful permanent") else "citizen"
    if _has(t, "18 years", "over 18", "at least 18", "18 or older", "age of 18", "18 years of age", "eighteen"):
        return "over18"
    if _has(t, "relocate", "relocation", "relocating"):
        return "relocate"
    if _has(t, "security clearance", "clearance"):
        return "clearance"
    if _has(t, "on site", "onsite", "in office", "in the office", "hybrid", "commute", "commuting", "report to the office", "work from our office"):
        return "onsite"
    if _has(t, "start date", "when can you start", "earliest start", "available to start", "availability to start", "date available",
            "earliest date", "when are you available"):
        return "startDate"
    if _has(t, "notice period"):
        return "notice"
    if _has(t, "salary expectation", "salary expectations", "expected salary", "desired salary", "salary requirement", "salary requirements",
            "compensation expectation", "compensation expectations", "expected compensation", "desired compensation", "pay expectation",
            "pay expectations", "desired pay", "expected pay", "salary range", "desired salary range", "target salary", "target compensation"):
        return "salary"
    if _has(t, "years of experience", "years experience", "years of relevant experience", "how many years"):
        # only the plain "how many years of experience" - never "years of experience with Python"
        return "years" if _GENERIC_YEARS.match(t) else "yearsSpecific"
    if _has(t, "linkedin"):
        return "linkedin"
    if _has(t, "github"):
        return "github"
    if _has(t, "portfolio"):
        return "portfolio"
    if _has(t, "website", "personal site", "personal url", "blog", "url"):
        return "website"
    if _has(t, "how did you hear", "where did you hear", "how did you find", "where did you find", "how did you learn", "referral source"):
        return "howHeard"
    if _has(t, "current location", "where are you located", "where do you live", "city of residence", "your location", "located in"):
        return "location"
    return ""
 
 
# ------------------------------------------------------------------ picking an option
DECLINE = ("decline", "prefer not", "dont wish", "do not wish", "choose not", "not to answer", "rather not", "dont want to answer",
           "not disclose", "not to disclose", "do not want to", "not wish to", "no answer", "prefer to not", "wish not")
 
 
def _yes_no(opt) -> str:
    t = _norm(opt)
    if re.match(r"^(yes|y|true)(?![a-z0-9])", t):
        return "yes"
    if re.match(r"^(no|n|false)(?![a-z0-9])", t):
        return "no"
    return ""
 
 
def _pick_yes_no(options, want) -> str | None:
    hits = [o for o in options if _yes_no(o) == want]
    return hits[0] if len(hits) == 1 else None
 
 
def _pick_decline(options) -> str | None:
    hits = [o for o in options if any(p in _norm(o) for p in DECLINE)]
    return hits[0] if len(hits) == 1 else None
 
 
def _pick_text(options, value) -> str | None:
    v = _norm(value)
    if not v:
        return None
    exact = [o for o in options if _norm(o) == v]
    if len(exact) == 1:
        return exact[0]
    hits = [o for o in options if v in _norm(o) or (_norm(o) and _norm(o) in v and len(_norm(o)) >= 3)]
    return hits[0] if len(hits) == 1 else None
 
 
def _range_of(opt):
    t = (opt or "").lower().replace("–", "-").replace("—", "-")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None
    if re.search(r"less than|under|fewer than|<", t):
        return (0.0, nums[0] - 1e-9)
    if re.search(r"\+|or more|and above|more than|over|at least", t):
        return (nums[0] + (1e-9 if re.search(r"more than|over", t) else 0.0), float("inf"))
    if len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    return (nums[0], nums[0])
 
 
def _pick_years(options, value):
    m = re.search(r"\d+(?:\.\d+)?", value or "")
    if not m:
        return None
    y = float(m.group(0))
    for o in options:
        r = _range_of(o)
        if r and r[0] <= y <= r[1]:
            return o
    return None
 
 
def resolve(question, bank, job_country=None) -> dict:
    """One form question -> {key, answer, option, check, source} when your bank answers it,
    or {key, missing: True, why} when it doesn't (or it's one Kaidostar never answers).
    question: {label, type, options: [str], required: bool}. job_country: where the job is, when known
    ("us", "canada", "uk"...) - a work-authorization question that names no country is about that one."""
    q = question if isinstance(question, dict) else {}
    label = q.get("label") if isinstance(q.get("label"), str) else ""
    qtype = q.get("type") if isinstance(q.get("type"), str) else "text"
    options = [o for o in (q.get("options") if isinstance(q.get("options"), list) else []) if isinstance(o, str) and o.strip()][:60]
    b = norm_bank(bank)
    key = classify(label)
    has_options = qtype in ("select", "radio") and bool(options)
 
    def miss(k, why):
        return {"key": k or "unknown", "missing": True, "why": why}
 
    if key == "never":
        return miss("never", "Kaidostar never answers this kind of question for you")
    if key == "authUnclear":
        return miss(key, "Asks about work authorization and sponsorship in one question - answer it yourself")
    if key == "sponsorUnclear":
        return miss(key, "Kaidostar can't read this sponsorship question safely - answer it yourself")
    nl = _norm(label)
 
    def country_issue():
        """Why a work-authorization answer from your bank can't be used for this question's country ('' when it can)."""
        named = countries_in(label)
        mine = bank_countries(b["workCountry"])
        if named:
            if not _covered(named, mine):
                return "Asks about working in " + ", ".join(country_name(n) for n in sorted(named)) + " - add it to the countries in your answer bank, or answer it yourself"
            return ""
        # a question that names no country is about the job's country - answered only when that's known
        # and it's one your answers cover
        if not mine:
            return "Add the countries your answers cover (Answer bank) - Kaidostar won't assume one"
        if not job_country:
            return "Kaidostar can't tell which country this job is in - answer it yourself"
        if not _covered({job_country}, mine):
            return "This job is in " + country_name(job_country) + ", and your answers are about " + ", ".join(country_name(n) for n in sorted(mine)) + " - answer it yourself"
        return ""
    # your own custom answers come first (after the never-list) - for the question they were written for:
    # a "not" in one and not the other ("Do you NOT require sponsorship?") is a different question
    for c in b["custom"]:
        cq = _norm(c["q"])
        if not (cq and (cq in nl or (len(nl) >= 6 and nl in cq))):
            continue
        if bool(_negations(cq)) != bool(_negations(nl)):
            continue
        if key in WORK_KEYS:
            # your answer is for the country it names (or, naming none, for the countries in your bank) - never
            # for a question about another country
            cn = countries_in(c["q"])
            if cn:
                qn = countries_in(label) or ({job_country} if job_country else set())
                if not qn or not _covered(qn, cn):
                    continue
            elif country_issue():
                continue
        if has_options:
            opt = _pick_text(options, c["a"]) or (_pick_yes_no(options, _yes_no(c["a"])) if _yes_no(c["a"]) else None)
            if opt is None:
                return miss("custom", "Your saved answer doesn't match any of this form's choices")
            return {"key": "custom", "answer": opt, "option": opt, "source": "custom"}
        if qtype == "checkbox":
            return miss("custom", "A checkbox - you choose it yourself")
        return {"key": "custom", "answer": c["a"], "option": None, "source": "custom"}
    if not key:
        return miss("", "Not a question your answer bank covers")
    if key == "yearsSpecific":
        return miss(key, "Asks about years with something specific - left for you")
    if key in WORK_KEYS:
        why = country_issue()
        if why:
            return miss(key, why)
    if key in ("citizen", "citizenPR", "authPermanent"):
        # "a citizen of that country" means one country: with several in your bank - or "the EU", which is many -
        # Kaidostar can't tell which (an EU citizen isn't a citizen of Germany)
        mine = bank_countries(b["workCountry"])
        if len(mine) != 1 or (mine == {"eu"} and countries_in(label) != {"eu"}):
            return miss(key, "Your answers cover several countries, so Kaidostar can't tell which you're a citizen of - answer it yourself")
        if key == "citizen" and b["citizen"] == "yes" and b["sponsorship"] == "yes":
            return miss(key, "Your answers say you're a citizen but need sponsorship - answer it yourself")
    if key.startswith("eeo:"):
        k = key[4:]
        pref = "decline" if k == "other" else b["eeo"].get(k, "decline")
        if pref == "ask":
            return miss(key, "You chose to answer this yourself")
        if not has_options:
            return miss(key, "A voluntary question with no 'decline' choice - left for you")
        opt = _pick_decline(options) if pref == "decline" else _pick_text(options, pref)
        if opt is None:
            return miss(key, "None of this form's choices matches your answer")
        return {"key": key, "answer": opt, "option": opt, "source": "eeo"}
    want = None
    if key == "authNoSponsor":
        if b["workAuth"] == "yes" and b["sponsorship"] == "no":
            want = "yes"
        elif b["workAuth"] == "no" or b["sponsorship"] == "yes":
            want = "no"
        else:
            return miss(key, "Add your work-authorization and sponsorship answers")
    elif key == "citizenPR":
        if b["citizen"] == "yes" and b["sponsorship"] != "yes":
            want = "yes"
        else:
            return miss(key, "Citizen-or-permanent-resident questions are left for you unless you're a citizen")
    elif key == "authPermanent":
        if b["citizen"] == "yes" and b["sponsorship"] != "yes":
            want = "yes"
        elif b["workAuth"] == "no":
            want = "no"
        else:
            return miss(key, "Asks whether your work authorization is permanent - answer it yourself (your bank doesn't say)")
    elif key in YESNO_KEYS:
        if not b[key]:
            return miss(key, "Add your answer for " + LABELS[key])
        want = b[key]
    if want is not None:
        if has_options:
            opt = _pick_yes_no(options, want)
            if opt is None:
                return miss(key, "This form's choices aren't a plain yes/no")
            return {"key": key, "answer": opt, "option": opt, "source": "bank"}
        if qtype == "checkbox":
            # a single "I am authorized to work..." box: ticked only when your answer is yes
            if key in ("workAuth", "over18", "relocate", "onsite", "authNoSponsor", "authPermanent") and want == "yes":
                return {"key": key, "answer": "yes", "option": None, "check": True, "source": "bank"}
            return miss(key, "A checkbox - you choose it yourself")
        if qtype in ("number", "date", "url") or not _yes_no_question(nl):
            return miss(key, "This box asks for more than a yes or no - answer it yourself")
        return {"key": key, "answer": "Yes" if want == "yes" else "No", "option": None, "source": "bank"}
    # text answers
    val = b.get(key) or ""
    if not val:
        return miss(key, "Add your answer for " + LABELS.get(key, key))
    if has_options:
        opt = _pick_years(options, val) if key == "years" else _pick_text(options, val)
        if opt is None:
            return miss(key, "None of this form's choices matches your answer")
        return {"key": key, "answer": opt, "option": opt, "source": "bank"}
    if qtype == "checkbox":
        return miss(key, "A checkbox - you choose it yourself")
    if qtype == "number":
        digits = re.sub(r"[$,\s]", "", val)
        if not re.match(r"^\d+(?:\.\d+)?$", digits):
            return miss(key, "This box takes a number - your saved answer isn't one")
        val = digits
    if qtype == "date" and not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
        return miss(key, "This box takes a date - your saved answer isn't one")
    return {"key": key, "answer": val, "option": None, "source": "bank"}
 
 
# the questions whose answers are about working in a country (checked against your countries and the job's)
WORK_KEYS = ("workAuth", "sponsorship", "authNoSponsor", "authPermanent", "citizen", "citizenPR")
# the one question where a form's own default is left as it is when your bank doesn't match it: how you heard
# about the job. Any other answer the form picked by itself - known question or not - is one you never gave.
FORM_DEFAULT_OK = ("howHeard",)
 
 
def resolve_all(questions, bank, job_country=None) -> list:
    """Every question on a form, resolved. A question the form had already answered by itself (a select
    with no "Select..." placeholder, a pre-checked radio, a pre-ticked box) is answered from your bank like
    any other; when your bank doesn't cover it, it is "blocking": nothing is submitted for you with an answer
    you didn't give - until you pick it yourself or say the form's answer is right. (Only "how did you hear
    about this job?" is left as the form has it.)"""
    out = []
    for i, q in enumerate((questions if isinstance(questions, list) else [])[:80]):
        r = resolve(q, bank, job_country)
        r["i"] = i
        q = q if isinstance(q, dict) else {}
        required = bool(q.get("required"))
        if q.get("preset"):
            r["preset"] = True
            if r.get("missing"):
                if str(r.get("key") or "") in FORM_DEFAULT_OK:
                    required = False   # the form's own default for how you heard about the job - left as it is
                else:
                    cur = _clean(q.get("current"), 80)
                    r["blocking"] = True
                    required = True
                    picked = ("this box ticked" if q.get("type") == "checkbox"
                              else ("“" + cur + "”" if cur else "an answer") + " picked")
                    why = str(r.get("why") or "answer it yourself")
                    if not why.startswith("Kaidostar"):
                        why = why[:1].lower() + why[1:]
                    r["why"] = "The form already has " + picked + " here, and Kaidostar never submits an answer you didn't give - " + why
        r["required"] = required
        out.append(r)
    return out
 
