"""Auto's answer bank - your own answers to the questions application forms ask,
and the resolver that matches a form's questions to them.
 
The rule is "stop rather than guess". A question is only ever answered from
something you told Kaidostar yourself (the bank on the Auto page, or a custom
question/answer you added - or one you answered on a form and asked it to
remember). Anything else - and anything Kaidostar never answers for anyone
(signatures and consent boxes, salary history, date of birth, criminal-history
or background-check questions) - is left for you, and an automatic submission
stops there. Voluntary equal-opportunity questions (gender, race/ethnicity,
veteran, disability) default to "I decline to self-identify" when the form
offers that choice; you can tell Kaidostar to leave them for you or give your
own answer.
 
A question the rules below don't recognise can come with a "reading"
(question_reader.py): what an AI model, given only the question's own words,
says it asks, and which of its choices is true in each situation a person can be
in. A reading never supplies an answer. It names the bank question this is; the
same rules then answer that question from your bank - and the answer is used only
when it is the choice the second reading gives for your situation. Anything else
stays with you.
 
Pure: no database, no network.
"""
from __future__ import annotations
 
import re
 
BANK_VERSION = 1
YESNO_KEYS = ("workAuth", "sponsorship", "citizen", "over18", "relocate", "onsite", "clearance")
TEXT_KEYS = ("startDate", "notice", "salary", "years", "location", "linkedin", "github", "portfolio", "website", "howHeard", "workCountry")
EEO_KEYS = ("gender", "race", "veteran", "disability")
TEXT_CHARS = 120
CUSTOM_CAP = 100
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
        # let an AI model read the questions the rules don't recognise (it sees the employer's question, never your answers)
        "ai": True,
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
        # (one saved from a form keeps the form's whole question - it's matched word for word)
        q, a = _clean(c.get("q"), 300 if c.get("src") == "form" else 160), _clean(c.get("a"), 300)
        k = _norm(q)
        if len(k) < 6 or not a or k in seen:
            continue
        seen.add(k)
        item = {"q": q, "a": a}
        if c.get("src") == "form":
            # one you answered on a form and asked Kaidostar to remember: reused for that same question, word for word
            item["src"] = "form"
            org = _clean(c.get("org"), 80)
            if org:
                item["org"] = org
            if isinstance(c.get("at"), int) and not isinstance(c.get("at"), bool) and c["at"] > 0:
                item["at"] = c["at"]
            # the country of the job it was given for, and what Kaidostar read its question as (when it did)
            if isinstance(c.get("c"), str) and re.match(r"^[a-z][a-z ]{1,29}$", c["c"]):
                item["c"] = c["c"]
            if isinstance(c.get("k"), str) and re.match(r"^[A-Za-z:]{2,24}$", c["k"]):
                item["k"] = c["k"]
        custom.append(item)
        if len(custom) >= CUSTOM_CAP:
            break
    out["custom"] = custom
    out["ai"] = r.get("ai") is not False
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
    # what you're paid now or were paid before, however a form words it ("current CTC", "last drawn salary")
    "current ctc", "present ctc", "existing ctc", "last drawn", "current package", "current pay", "present salary", "existing salary",
    "current base", "current wage", "current wages", "previous compensation", "past compensation", "previous pay", "past pay", "prior pay",
    "pay history", "compensation history", "wage history", "earnings history", "current earnings",
    "references", "reference name", "password", "national insurance", "passport", "drivers license number", "license number",
    "social insurance", "national id", "aadhaar", "aadhar", "pan card", "pan number", "tax file number",
    "bank account", "credit card", "tax id", "sin number", "medical", "pregnant", "pregnancy", "pregnancies", "marital", "religion", "religious",
    "genetic", "workers compensation", "health condition", "illness", "injury", "injuries", "maiden name",
    "medication", "medications", "prescription", "prescriptions", "physical limitation", "physical limitations", "physical restriction",
    "physical restrictions", "diagnosed", "diagnosis", "mental health", "psychiatric", "hospitalized", "hospitalization", "vaccinated",
    "vaccination", "vaccine", "vaccines", "immunization", "immunizations",
    # can you do the job "with or without reasonable accommodation", do you need accommodations: disability questions in other words
    "reasonable accommodation", "reasonable accommodations", "essential functions", "with or without accommodation", "accommodation", "accommodations",
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
    # "Are you authorized, and do you need a visa?": a work permission and sponsorship in one question - one yes or no
    # can't answer both
    if _has(t, "authorized", "authorised", "authorization", "authorisation", "eligible", "eligibility", "permitted", "allowed", "legally", "lawfully"):
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
# Northern Ireland in the UK - and regions that hold one ("Latin America" is not America, North Korea not Korea)
_COUNTRY_INSIDE = ((re.compile(r"(?<![a-z0-9])(?:new mexico|new england)(?![a-z0-9])"), " united states "),
                   (re.compile(r"(?<![a-z0-9])new south wales(?![a-z0-9])"), " australia "),
                   (re.compile(r"(?<![a-z0-9])northern ireland(?![a-z0-9])"), " united kingdom "),
                   (re.compile(r"(?<![a-z0-9])(?:latin|south|central|north) america(?![a-z0-9])|(?<![a-z0-9])the americas(?![a-z0-9])"), " region "),
                   (re.compile(r"(?<![a-z0-9])north korea(?![a-z0-9])"), " region "))
 
# every other country (and the world's regions): named in a work question, it's one Kaidostar can't check against your
# answers - so the question is left for you, never answered as if it were about the job's country
OTHER_PLACES = (
    "afghanistan", "albania", "algeria", "andorra", "angola", "antigua", "armenia", "azerbaijan", "bahamas", "bahrain", "barbados",
    "belarus", "belize", "benin", "bhutan", "bolivia", "bosnia", "herzegovina", "botswana", "brunei", "burkina faso", "burundi", "cambodia",
    "cameroon", "cape verde", "cabo verde", "central african republic", "chad", "comoros", "congo", "cuba", "djibouti", "dominica",
    "dominican republic", "east timor", "timor leste", "el salvador", "equatorial guinea", "eritrea", "eswatini", "swaziland", "ethiopia",
    "fiji", "gabon", "gambia", "georgia", "grenada", "guinea", "guinea bissau", "guyana", "haiti", "honduras", "iran", "iraq", "ivory coast",
    "cote d ivoire", "cote divoire", "jamaica", "jordan", "kazakhstan", "kiribati", "kosovo", "kuwait", "kyrgyzstan", "laos", "lebanon",
    "lesotho", "liberia", "libya", "liechtenstein", "madagascar", "malawi", "maldives", "mali", "marshall islands", "mauritania", "mauritius",
    "micronesia", "moldova", "monaco", "mongolia", "montenegro", "mozambique", "myanmar", "burma", "namibia", "nauru", "nicaragua", "niger",
    "north korea", "north macedonia", "macedonia", "oman", "palau", "palestine", "palestinian territories", "papua new guinea", "paraguay",
    "russia", "russian federation", "rwanda", "saint kitts", "st kitts", "saint lucia", "st lucia", "saint vincent", "st vincent", "samoa",
    "san marino", "sao tome", "senegal", "seychelles", "sierra leone", "solomon islands", "somalia", "south sudan", "sudan", "suriname",
    "syria", "tajikistan", "tanzania", "togo", "tonga", "trinidad", "tobago", "tunisia", "turkmenistan", "tuvalu", "uganda", "uzbekistan",
    "vanuatu", "vatican", "venezuela", "yemen", "zambia", "zimbabwe", "puerto rico", "guam", "american samoa", "virgin islands", "macau",
    "macao", "greenland", "faroe islands", "bermuda", "cayman islands", "gibraltar", "isle of man", "channel islands", "guernsey",
    # regions
    "region", "asia", "africa", "middle east", "apac", "emea", "latam", "americas", "caribbean", "oceania", "gcc", "gulf states", "nordics",
    "nordic countries", "scandinavia", "balkans", "mena", "sub saharan", "embargoed countries", "sanctioned countries",
)
 
 
def other_places_in(text) -> list:
    """The countries and regions a question names that Kaidostar can't check against your answers."""
    t = _norm(text)
    for rx, repl in _COUNTRY_INSIDE:
        t = rx.sub(repl, t)
    return [p for p in OTHER_PLACES if _has(t, p)]
 
 
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
    if _has(t, "sexual orientation", "orientation", "lgbt", "lgbtq", "lgbtqia", "transgender", "identify as", "how do you identify",
            "self identify", "self identification", "self identity"):
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
 
 
# A plain yes/no answer fits only the plain question. These words turn one into another question: "Are you under 18?",
# "Are you unwilling to relocate?", "Would commuting be a problem?", "Are you eligible to obtain a clearance?", "Are you a
# citizen of another country?" - each left for you (a "Yes" from your bank would say the opposite, or something else).
_REWORDED = {
    "over18": re.compile(r"(?<![a-z0-9])(?:under|younger|below|less than|minor|minors)(?![a-z0-9])"),
    "relocate": re.compile(r"(?<![a-z0-9])(?:unwilling|unable|reluctant|hesitant|problem|problems|issue|issues|difficult|difficulty|concern|concerns"
                           r"|prevent|prevents|objection|object|against|refuse|decline|already|currently live|reside)(?![a-z0-9])"),
    "onsite": re.compile(r"(?<![a-z0-9])(?:unwilling|unable|reluctant|hesitant|problem|problems|issue|issues|difficult|difficulty|concern|concerns"
                         r"|prevent|prevents|objection|object|against|refuse|decline|only|remote only|fully remote)(?![a-z0-9])"),
    "clearance": re.compile(r"(?<![a-z0-9])(?:obtain|obtaining|get|getting|eligible|eligibility|able|willing|apply|applying|acquire|pass|undergo|"
                            r"revoked|denied|suspended|ever|previously|past|former|lapsed|expired|sponsor|sponsored|level|type|which|what)(?![a-z0-9])"),
    "citizen": re.compile(r"(?<![a-z0-9])(?:non|noncitizen|noncitizens|other|another|besides|except|dual|multiple|second|only|following|sanction|"
                          r"sanctioned|sanctions|embargo|embargoed|ofac|former|previous|previously|ever|renounce|renounced|foreign|which|what)(?![a-z0-9])"),
    "citizenPR": re.compile(r"(?<![a-z0-9])(?:non|noncitizen|noncitizens|other|another|besides|except|dual|multiple|second|only|following|sanction|"
                            r"sanctioned|sanctions|embargo|embargoed|ofac|former|previous|previously|ever|renounce|renounced|foreign|which|what)(?![a-z0-9])"),
}
 
 
def _reworded(key, label) -> str:
    """Why a plain yes/no answer from your bank doesn't fit this wording of the question ('' when it does)."""
    rx = _REWORDED.get(key)
    if rx is None:
        return ""
    t = _norm(_question_part(label))
    if _negations(t) or rx.search(t):
        return "Worded so a plain yes or no from your answer bank might not fit - answer it yourself"
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
 
 
def resolve(question, bank, job_country=None, reading=None, org=None) -> dict:
    """One form question -> {key, answer, option, check, source} when your bank answers it,
    or {key, missing: True, why} when it doesn't (or it's one Kaidostar never answers).
    question: {label, type, options: [str], required: bool}. job_country: where the job is, when known
    ("us", "canada", "uk"...) - a work-authorization question that names no country is about that one.
    reading: what question_reader.py made of a question the rules don't recognise (see _resolve_read) -
    used only when the rules can't place the question themselves. org: the employer whose form this is (an answer you
    gave about one employer is used only on that employer's forms)."""
    r = _resolve_rules(question, bank, job_country, org)
    if reading and readable(r):
        got = _resolve_read(question, bank, job_country, reading, r)
        if got is not None:
            return got
    return r
 
 
def _learned_of(c) -> dict:
    """What an answer remembered from a form carries with it into a result (see answer_form)."""
    if c.get("src") != "form":
        return {}
    return {"learned": True, "learnedKind": c.get("k") or "", "uncountried": not c.get("c")}
 
 
def _resolve_rules(question, bank, job_country=None, org=None) -> dict:
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
        if other_places_in(label):
            return "Asks about a country or region Kaidostar can't check against your answers - answer it yourself"
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
        if c.get("src") == "form":
            # an answer you gave on a form: for that same question only, word for word - never a work-authorization one
            # (yours is in the bank, for the countries it's about), and one about the employer only on that employer's forms
            if not cq or cq != nl or key in WORK_KEYS:
                continue
            if c.get("org") and _employer_bound(c) and _norm(c.get("org")) != _norm(org or ""):
                continue
            # given for a job in one country: used for jobs in that country only (a question can be about working there
            # whatever its words) - one given where the country wasn't known is checked by answer_form
            if c.get("c") and c["c"] != job_country:
                continue
        elif not (cq and (cq in nl or (len(nl) >= 6 and nl in cq))):
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
            return dict({"key": "custom", "answer": opt, "option": opt, "source": "custom"}, **_learned_of(c))
        if qtype == "checkbox":
            return miss("custom", "A checkbox - you choose it yourself")
        return dict({"key": "custom", "answer": c["a"], "option": None, "source": "custom"}, **_learned_of(c))
    if not key:
        return miss("", "Not a question your answer bank covers")
    if key == "yearsSpecific":
        return miss(key, "Asks about years with something specific - left for you")
    if key in WORK_KEYS:
        why = country_issue()
        if why:
            return miss(key, why)
    rev = _reworded(key, label)
    if rev:
        return miss(key, rev)
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
 
 
def resolve_all(questions, bank, job_country=None, readings=None, org=None) -> list:
    """Every question on a form, resolved. A question the form had already answered by itself (a select
    with no "Select..." placeholder, a pre-checked radio, a pre-ticked box) is answered from your bank like
    any other; when your bank doesn't cover it, it is "blocking": nothing is submitted for you with an answer
    you didn't give - until you pick it yourself or say the form's answer is right. (Only "how did you hear
    about this job?" is left as the form has it.) readings: {question index: reading} from question_reader."""
    readings = readings if isinstance(readings, dict) else {}
    return [finish(i, q, resolve(q, bank, job_country, readings.get(i), org))
            for i, q in enumerate((questions if isinstance(questions, list) else [])[:80])]
 
 
def finish(i, q, r) -> dict:
    """One question's result as resolve_all gives it: its index, whether it's required - and, for an answer the form
    picked by itself that your bank doesn't give, "blocking" (see resolve_all)."""
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
    return r
 
 
# ------------------------------------------------------------------ a question the rules can't place, read by AI
# question_reader.py asks; this decides. A reading is
#   {"kind": a bank question below (or "never", "two", "other", "status"),
#    "country": the country the question names, as the model wrote it (or None), "negated": bool,
#    "table": {situation: the choice the second reading says is true for someone in it, or "UNSURE"},
#    "confirmed": the second reading says the question asks exactly for this detail (a text or voluntary question)}
YES_NO_KINDS = ("workAuth", "sponsorship", "authNoSponsor", "authPermanent", "citizen", "citizenPR", "over18", "relocate", "onsite", "clearance")
TEXT_READ_KINDS = ("startDate", "notice", "salary", "years", "location", "linkedin", "github", "portfolio", "website", "howHeard")
EEO_READ_KINDS = ("eeo:gender", "eeo:race", "eeo:veteran", "eeo:disability", "eeo:other")
READ_KINDS = YES_NO_KINDS + TEXT_READ_KINDS + EEO_READ_KINDS + ("status",)
WORK_READ_KINDS = ("workAuth", "sponsorship", "authNoSponsor", "authPermanent", "citizen", "citizenPR", "status")
 
# the plain question each bank question is, as the rules read it - a reading's kind is answered as this question
CANON = {
    "workAuth": "Are you legally authorized to work{in}?",
    "sponsorship": "Will you now or in the future require sponsorship for an employment visa{in}?",
    "authNoSponsor": "Are you legally authorized to work{in} without requiring sponsorship?",
    "authPermanent": "Are you permanently authorized to work{in}?",
    "citizen": "Are you a citizen{of}?",
    "citizenPR": "Are you a citizen or permanent resident{of}?",
    "over18": "Are you at least 18 years of age?",
    "relocate": "Are you willing to relocate?",
    "onsite": "Are you able to work on site?",
    "clearance": "Do you hold an active security clearance?",
    "startDate": "When are you available to start?",
    "notice": "What is your notice period?",
    "salary": "What are your salary expectations?",
    "years": "How many years of experience do you have?",
    "location": "What is your current location?",
    "linkedin": "LinkedIn profile",
    "github": "GitHub profile",
    "portfolio": "Portfolio link",
    "website": "Personal website",
    "howHeard": "How did you hear about this job?",
    "eeo:gender": "Gender",
    "eeo:race": "Race / ethnicity",
    "eeo:veteran": "Veteran status",
    "eeo:disability": "Disability status",
    "eeo:other": "Sexual orientation",
}
# what the panel and the proof say a question was read as
READ_AS = {
    "workAuth": "whether you're authorized to work", "sponsorship": "whether you'll need visa sponsorship",
    "authNoSponsor": "whether you can work without ever needing sponsorship", "authPermanent": "whether your work authorization is permanent",
    "citizen": "whether you're a citizen", "citizenPR": "whether you're a citizen or permanent resident", "status": "your citizenship status",
    "over18": "whether you're 18 or older", "relocate": "whether you'll relocate", "onsite": "whether you can work on site",
    "clearance": "whether you hold a security clearance", "startDate": "when you can start", "notice": "your notice period",
    "salary": "the pay you're asking for", "years": "your total years of experience", "location": "where you live",
    "linkedin": "your LinkedIn", "github": "your GitHub", "portfolio": "your portfolio", "website": "your website",
    "howHeard": "how you heard about the job", "eeo:gender": "a voluntary gender question", "eeo:race": "a voluntary race/ethnicity question",
    "eeo:veteran": "a voluntary veteran question", "eeo:disability": "a voluntary disability question", "eeo:other": "a voluntary self-identification question",
}
# the situations a person can be in, for the second reading of a work question ("this country": the one the question
# is about, or the job's country when it names none)
WORK_SITUATIONS = {
    "citizen": "is a citizen of this country",
    "pr": "is not a citizen of this country but a permanent resident there: may work there with no time limit, and never needs an employer to sponsor a visa",
    "visa_ok": "is neither a citizen nor a permanent resident of this country, but holds a temporary work permit or visa there that does not need an employer's sponsorship",
    "visa_sponsor": "may work in this country now, but needs an employer to sponsor a work visa, now or in the future",
    "not_authorized": "is not allowed to work in this country unless an employer sponsors a work visa",
}
_CANON_COUNTRY = {"us": "the United States", "uk": "the United Kingdom", "eu": "the European Union", "uae": "the United Arab Emirates",
                  "korea": "South Korea", "czechia": "the Czech Republic", "netherlands": "the Netherlands", "philippines": "the Philippines"}
# a choice that names someone's nationality ("Canadian citizen") names a country too
_DEMONYMS = {"american": "us", "canadian": "canada", "british": "uk", "english": "uk", "scottish": "uk", "welsh": "uk", "irish": "ireland",
             "german": "germany", "french": "france", "dutch": "netherlands", "spanish": "spain", "italian": "italy", "portuguese": "portugal",
             "indian": "india", "australian": "australia", "mexican": "mexico", "brazilian": "brazil", "israeli": "israel", "swiss": "switzerland",
             "swedish": "sweden", "polish": "poland", "danish": "denmark", "norwegian": "norway", "finnish": "finland", "belgian": "belgium",
             "austrian": "austria", "singaporean": "singapore", "japanese": "japan", "chinese": "china", "korean": "korea", "filipino": "philippines",
             "nigerian": "nigeria", "pakistani": "pakistan", "colombian": "colombia", "argentine": "argentina", "argentinian": "argentina",
             "chilean": "chile", "peruvian": "peru", "egyptian": "egypt", "moroccan": "morocco", "kenyan": "kenya", "turkish": "turkey",
             "greek": "greece", "ukrainian": "ukraine", "romanian": "romania", "new zealander": "new zealand", "south african": "south africa",
             "european": "eu", "emirati": "uae", "saudi": "saudi arabia", "indonesian": "indonesia", "malaysian": "malaysia", "thai": "thailand",
             "vietnamese": "vietnam", "taiwanese": "taiwan", "bangladeshi": "bangladesh", "sri lankan": "sri lanka", "nepali": "nepal"}
# a text question that only asks for a part of where you live, or asks it as yes/no, isn't "your current location"
_LOCATION_PART_RE = re.compile(r"(?<![a-z0-9])(?:country|state|province|zip|postal|postcode|post code|street|address|county|region|citizenship|nationality)(?![a-z0-9])")
_SALARY_NOW_RE = re.compile(r"(?<![a-z0-9])(?:current|currently|present|previous|previously|prior|past|last|existing|drawn|history|earned|earning|earnings|making|make now)(?![a-z0-9])")
_YEARS_GENERIC_WORDS = {"how", "many", "years", "year", "yrs", "of", "experience", "exp", "do", "you", "have", "total", "overall", "professional",
                        "relevant", "work", "working", "industry", "full", "time", "fulltime", "in", "the", "your", "number", "please", "enter", "state",
                        "indicate", "what", "is", "are", "combined", "post", "qualification", "since", "graduation", "career", "employment", "paid",
                        "experienced", "a", "an", "s", "approximately", "roughly"}
 
 
def readable(r) -> bool:
    """Is this a result of the rules that a reading may improve on: a question they don't recognise, one whose wording
    they can't read safely, or a yes/no question whose choices aren't a plain yes and no?"""
    if not isinstance(r, dict) or not r.get("missing"):
        return False
    k = str(r.get("key") or "")
    if k in ("", "unknown", "authUnclear", "sponsorUnclear"):
        return True
    # (resolve_all rewords the reason for a question the form had already answered by itself)
    return k in YES_NO_KINDS and "choices aren't a plain yes/no" in str(r.get("why") or "")
 
 
def canonical_label(kind, named) -> str | None:
    """The plain question a kind is, about the countries a question names - None when it can't be written so the
    rules read back exactly those countries."""
    t = CANON.get(kind)
    if t is None:
        return None
    names = [_CANON_COUNTRY.get(k, country_name(k)) for k in sorted(named or ())]
    place = " or ".join(names)
    lab = t.replace("{in}", (" in " + place) if place else "").replace("{of}", (" of " + place) if place else "")
    if countries_in(lab) != set(named or ()):
        return None
    return lab
 
 
def situations_for(kind) -> dict:
    """The situations the second reading is asked about for a question read as `kind`: {id: description}."""
    if kind in WORK_READ_KINDS:
        return dict(WORK_SITUATIONS)
    if kind in ("over18", "relocate", "onsite", "clearance"):
        return {"yes": "would answer Yes to the question “" + CANON[kind] + "”", "no": "would answer No to the question “" + CANON[kind] + "”"}
    return {}
 
 
def person_situations(kind, bank):
    """The situations your bank says you could be in, for a question read as `kind` (None when it doesn't say)."""
    b = norm_bank(bank)
    if kind in WORK_READ_KINDS:
        wa, sp, ci = b["workAuth"], b["sponsorship"], b["citizen"]
        mine = bank_countries(b["workCountry"])
        one = ci == "yes" and len(mine) == 1 and mine != {"eu"}   # a citizen of the one country your answers are about
        if wa == "no":
            return {"not_authorized"}
        if wa == "":
            if sp == "yes":
                return {"visa_sponsor", "not_authorized"}
            return {"citizen"} if one else None
        if sp == "yes":
            return {"visa_sponsor"}
        if one:
            return {"citizen"}
        rest = {"pr", "visa_ok"} if sp == "no" else {"pr", "visa_ok", "visa_sponsor"}
        return rest if ci == "no" else rest | {"citizen"}
    v = b.get(kind)
    return {v} if v in ("yes", "no") else None
 
 
def _choice_says(opt, want_word):
    """Does a choice say plainly that the person is `want_word` (e.g. a citizen) - with no "not", "non-", "other",
    "another", "dual" or "foreign" in it, and no country Kaidostar can't check?"""
    t = _norm(opt)
    return (_has(t, want_word, want_word + "s", want_word + "ship") and not _negations(t) and not other_places_in(opt)
            and not _has(t, "non", "non " + want_word, "non" + want_word, "other", "another", "dual", "foreign", "second", "former"))
 
 
def _choice_countries(opt) -> set:
    t = _norm(opt)
    out = set(countries_in(opt))
    for w, c in _DEMONYMS.items():
        if _has(t, w):
            out.add(c)
    return out
 
 
def _resolve_read(question, bank, job_country, reading, rules=None):
    """A question the rules can't place, answered as the bank question the reading says it is - by the rules, from
    your bank - and only when the second reading picks the same choice for your situation. None: the reading changes
    nothing (the rules' result stands). rules: what the rules made of it (a question they recognised but whose choices
    they couldn't read is read as that same question, or not at all)."""
    q = question if isinstance(question, dict) else {}
    if not isinstance(reading, dict):
        return None
    b = norm_bank(bank)
    if not b.get("ai", True):
        return None
    label = q.get("label") if isinstance(q.get("label"), str) else ""
    qtype = q.get("type") if isinstance(q.get("type"), str) else "text"
    options = [o for o in (q.get("options") if isinstance(q.get("options"), list) else []) if isinstance(o, str) and o.strip()][:60]
    has_options = qtype in ("select", "radio") and bool(options)
    nl = _norm(label)
    kind = str(reading.get("kind") or "")
    negated = reading.get("negated") is True
    table = reading.get("table") if isinstance(reading.get("table"), dict) else {}
 
    def miss(k, why):
        return {"key": k or "unknown", "missing": True, "why": why, "read": READ_AS.get(k, "")}
 
    disagree_why = "Kaidostar's two readings of this question didn't agree - answer it yourself"
    if kind == "never":
        return miss("never", "Kaidostar never answers this kind of question for you")
    if kind == "two":
        return miss("twoQuestions", "Asks two things in one question - answer it yourself")
    if negated and kind == "sponsorship":
        kind, negated = "authNoSponsor", False      # "Will you NOT need sponsorship?" is "can you work without it?"
    if kind not in READ_KINDS:
        return None
    rk = str((rules or {}).get("key") or "")
    if rk in READ_KINDS and kind != rk and not (kind == "status" and rk in WORK_READ_KINDS):
        # the rules recognised another question (a list of statuses is still "your status", not another question)
        return miss(rk, disagree_why)
    if negated:
        return miss(kind, "Worded the other way round from the usual question - answer it yourself")
    named = countries_in(label)
    if kind in WORK_READ_KINDS and other_places_in(label):
        return miss(kind, "Asks about a country or region Kaidostar can't check against your answers - answer it yourself")
    if kind in _REWORDED and _reworded(kind, label):
        return miss(kind, _reworded(kind, label))
    rc = reading.get("country")
    if isinstance(rc, str) and rc.strip() and rc.strip().lower() not in ("null", "none"):
        said = countries_in(rc) or bank_countries(rc)
        if not said or not said <= named:
            return miss(kind, "Asks about a country Kaidostar can't check - answer it yourself")
 
    def want_of(r2):
        if qtype == "checkbox":
            return "ticked" if r2.get("check") else None
        if has_options:
            return r2.get("option")
        return r2.get("answer")
 
    def agrees(k, r2):
        sits = person_situations(k, b)
        want = want_of(r2)
        if not sits or not want:
            return False
        vals = {table.get(s) for s in sits}
        return len(vals) == 1 and next(iter(vals)) == want
 
    disagree = disagree_why
    if kind == "status":
        # "Which best describes your status?": answered only for a citizen of the country it's about, with the choice that
        # says citizen - any other status is more than your bank says
        if not has_options:
            return miss("status", "Asks for your citizenship or visa status - answer it yourself")
        if person_situations("status", b) != {"citizen"}:
            return miss("status", "Asks for your exact citizenship or visa status, which your answers don't say - answer it yourself")
        lab = canonical_label("citizen", named)
        r_c = _resolve_rules({"label": lab, "type": "select", "options": ["Yes", "No"]}, b, job_country) if lab else None
        if not r_c or r_c.get("missing") or r_c.get("option") != "Yes":
            return miss("status", (r_c or {}).get("why") or "Asks for your citizenship status - answer it yourself")
        opt = table.get("citizen")
        mine = bank_countries(b["workCountry"])
        if opt not in options or not _choice_says(opt, "citizen") or not _choice_countries(opt) <= mine:
            return miss("status", disagree)
        return {"key": "status", "answer": opt, "option": opt, "source": "bank", "read": READ_AS["status"]}
    if (kind in TEXT_READ_KINDS or kind in EEO_READ_KINDS) and reading.get("confirmed") is not True:
        # a detail from your bank (or a "decline" choice) is used only when the second reading says the question asks
        # exactly for it
        return miss(kind, disagree)
    if kind in TEXT_READ_KINDS:
        if _yes_no_question(nl) and not has_options:
            return miss(kind, "Asks it as a yes/no question - answer it yourself")
        if kind == "location" and _LOCATION_PART_RE.search(nl):
            return miss(kind, "Asks for one part of where you live - answer it yourself")
        if kind == "salary" and _SALARY_NOW_RE.search(nl):
            return miss("never", "Kaidostar never answers what you're paid now or were paid before")
        if kind == "years" and (set(nl.split()) - _YEARS_GENERIC_WORDS):
            return miss("yearsSpecific", "Asks about years with something specific - left for you")
    lab = canonical_label(kind, named)
    if lab is None:
        return miss(kind, "Asks about a country Kaidostar can't check - answer it yourself")
    r2 = _resolve_rules({"label": lab, "type": qtype, "options": options, "required": bool(q.get("required"))}, b, job_country)
    r2["read"] = READ_AS.get(kind, "")
    if kind in YES_NO_KINDS and has_options and r2.get("missing") and r2.get("why") == "This form's choices aren't a plain yes/no":
        # choices that are statements ("I am authorized to work here", "I will need sponsorship"): the second reading's
        # choice for your situation - used only when its own words say what your bank says (no "not" in it for your yes,
        # a "not" for your no) and it names no other country
        yn = _resolve_rules({"label": lab, "type": "select", "options": ["Yes", "No"]}, b, job_country)
        if yn.get("missing"):
            yn["read"] = READ_AS.get(kind, "")
            return yn
        sits = person_situations(kind, b)
        vals = {table.get(s) for s in sits} if sits else set()
        opt = next(iter(vals)) if len(vals) == 1 else None
        if (opt not in options or bool(_negations(_norm(opt))) != (yn.get("option") == "No")
                or not _choice_countries(opt) <= (named or ({job_country} if job_country else set()) or bank_countries(b["workCountry"]))):
            return miss(kind, disagree)
        return {"key": kind, "answer": opt, "option": opt, "source": "bank", "read": READ_AS.get(kind, "")}
    if r2.get("missing"):
        return r2
    if kind in YES_NO_KINDS and not agrees(kind, r2):
        return miss(kind, disagree)
    return r2
 
 
# ------------------------------------------------------------------ a country as a job feed or a job page writes it
_ISO2 = {"US": "us", "CA": "canada", "GB": "uk", "UK": "uk", "IE": "ireland", "DE": "germany", "FR": "france", "NL": "netherlands", "ES": "spain",
         "IT": "italy", "PT": "portugal", "IN": "india", "AU": "australia", "NZ": "new zealand", "SG": "singapore", "JP": "japan", "MX": "mexico",
         "BR": "brazil", "IL": "israel", "CH": "switzerland", "SE": "sweden", "PL": "poland", "DK": "denmark", "NO": "norway", "FI": "finland",
         "BE": "belgium", "AT": "austria", "ZA": "south africa", "HK": "hong kong", "CN": "china", "KR": "korea", "PH": "philippines", "NG": "nigeria",
         "AE": "uae", "PK": "pakistan", "BD": "bangladesh", "LK": "sri lanka", "NP": "nepal", "CO": "colombia", "AR": "argentina", "CL": "chile",
         "PE": "peru", "EC": "ecuador", "UY": "uruguay", "CR": "costa rica", "PA": "panama", "GT": "guatemala", "EG": "egypt", "MA": "morocco",
         "KE": "kenya", "GH": "ghana", "TR": "turkey", "GR": "greece", "CZ": "czechia", "SK": "slovakia", "HU": "hungary", "RO": "romania",
         "BG": "bulgaria", "HR": "croatia", "SI": "slovenia", "RS": "serbia", "UA": "ukraine", "LT": "lithuania", "LV": "latvia", "EE": "estonia",
         "LU": "luxembourg", "MT": "malta", "CY": "cyprus", "IS": "iceland", "SA": "saudi arabia", "QA": "qatar", "ID": "indonesia", "MY": "malaysia",
         "TH": "thailand", "VN": "vietnam", "TW": "taiwan"}
_ISO3 = {"USA": "us", "GBR": "uk", "CAN": "canada", "IND": "india", "DEU": "germany", "FRA": "france", "AUS": "australia", "IRL": "ireland",
         "NLD": "netherlands", "ESP": "spain", "ITA": "italy", "MEX": "mexico", "BRA": "brazil", "ISR": "israel", "SGP": "singapore", "JPN": "japan",
         "CHE": "switzerland", "SWE": "sweden", "POL": "poland", "NZL": "new zealand", "ZAF": "south africa", "PRT": "portugal", "BEL": "belgium",
         "AUT": "austria", "DNK": "denmark", "NOR": "norway", "FIN": "finland", "PHL": "philippines", "ARE": "uae", "COL": "colombia",
         "ARG": "argentina", "CHL": "chile", "MAR": "morocco", "MLT": "malta", "IDN": "indonesia"}
# the two-letter codes of US states and territories: on a page (not a feed's country field) one of them is not trusted as a country
_US_STATE_CODES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
                   "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX",
                   "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "GU", "VI", "AS", "MP"}
 
 
def country_key(value, structured=True) -> str | None:
    """A country as a job feed or a job page writes it ("US", "USA", "United States of America", "gb") -> the key used
    here, or None. structured: a feed's own country field, where a two-letter code is the country's by definition;
    otherwise (a page's markup) a code that is also a US state's ("IN", "MA", "CA") isn't trusted."""
    s = str(value or "").strip()
    if not s or len(s) > 60:
        return None
    u = s.upper().replace(".", "").replace(" ", "")
    if len(u) <= 4:
        if u in ("US", "USA"):
            return "us"
        if u in ("UK", "GB", "GBR"):
            return "uk"
        if len(u) == 2:
            if not structured and u in _US_STATE_CODES:
                return None
            return _ISO2.get(u)
        if len(u) == 3:
            return _ISO3.get(u)
    got = countries_in(s)
    return next(iter(got)) if len(got) == 1 else None
 
 
 
# ------------------------------------------------------------------ answers you gave on a form, remembered
LEARN_MAX = 40
# a question about the employer ("Have you worked for us before?", "Why do you want to work here?"), or a written answer
# (an essay names the employer): reused only on that employer's own forms
_EMPLOYER_WORDS = re.compile(r"(?<![a-z0-9])(?:us|our|we|here|this company|this organization|this organisation|this role|this position|this job|"
                             r"the company|the organization|the organisation|the team|our team|our company|join)(?![a-z0-9])")
# work authorization, sponsorship, citizenship, residency: kept in your answer bank (for the countries your answers are
# about), never remembered from one form for the next
_WORK_WORDS = re.compile(r"(?<![a-z0-9])(?:authorized|authorised|authorization|authorisation|eligible|eligibility|sponsor|sponsorship|sponsored|visa|"
                         r"visas|citizen|citizens|citizenship|nationality|national|nationals|resident|residency|residence|permit|permits|immigration|"
                         r"green card|right to work|legally|lawfully|work in|country|countries|restriction|restrictions|restricted|unrestricted|"
                         r"limitation|limitations|employment|employable|employ|work for|able to work|allowed to work|permitted to work|"
                         r"entitled to work|any employer|work rights|work pass|passport|everify|e verify|i 9|i9|h 1b|h1b|opt|cpt|ead|tn|"
                         r"us person|u s person|itar|export)(?![a-z0-9])")
 
 
def _employer_bound(c) -> bool:
    return bool(_EMPLOYER_WORDS.search(_norm(c.get("q")))) or (not _yes_no(c.get("a")) and len(str(c.get("a") or "")) > 40)
 
 
def learn(bank, given, org="", now_ms=None, country=None) -> tuple:
    """Answers you gave on a form yourself, saved to your bank for those same questions, word for word:
    -> (the bank with them, how many were saved, [{label, why}] for each one that wasn't). Never a question Kaidostar
    doesn't answer for anyone, a voluntary equal-opportunity one, a tick box, or a choice the form doesn't offer.
    An answer you saved before to the same question is replaced; when the bank is full, the oldest answers saved
    from forms make room (never the ones you wrote yourself)."""
    b = norm_bank(bank)
    custom = [dict(c) for c in b["custom"]]
    skipped, new_qs = [], []
    for g in (given if isinstance(given, list) else [])[:LEARN_MAX]:
        if not isinstance(g, dict):
            continue
        label, ans = _clean(g.get("label"), 300), _clean(g.get("answer"), 300)
        qtype = str(g.get("type") or "text")
        n = _norm(label)
 
        def skip(why):
            skipped.append({"label": label[:120], "why": why})
        if len(n) < 6 or not ans:
            skip("no question or no answer")
            continue
        if qtype not in ("select", "radio", "text", "textarea", "number", "date", "url"):
            skip("Kaidostar doesn't save tick boxes")
            continue
        key = classify(label)
        if key == "never" or str(g.get("read") or "") == "never":
            skip("Kaidostar never answers this kind of question for you")
            continue
        if key.startswith("eeo:") or str(g.get("read") or "").startswith("eeo:"):
            skip("Voluntary equal-opportunity answers are set in your answer bank")
            continue
        if key in WORK_KEYS or key in ("authUnclear", "sponsorUnclear", "twoQuestions") or _WORK_WORDS.search(n) \
                or str(g.get("read") or "") in WORK_READ_KINDS:
            skip("Work-authorization answers live in your answer bank, for the countries they're about")
            continue
        if str(g.get("read") or "") == "two":
            skip("Asks two things in one question - Kaidostar doesn't remember answers to those")
            continue
        opts = [_clean(o, 300) for o in (g.get("options") if isinstance(g.get("options"), list) else []) if isinstance(o, str)]
        if qtype in ("select", "radio") and opts and ans not in opts:
            skip("Not one of the form's choices")
            continue
        custom = [c for c in custom if _norm(c["q"]) != n]
        item = {"q": label, "a": ans, "src": "form", "at": int(now_ms or 0)}
        if _clean(org, 80):
            item["org"] = _clean(org, 80)
        if isinstance(country, str) and country:
            item["c"] = country                       # (reused for jobs in this country only)
        if str(g.get("read") or ""):
            item["k"] = str(g.get("read"))            # what its question was read as
        custom.append(item)
        new_qs.append(n)
    while len(custom) > CUSTOM_CAP:
        # the oldest answer saved from a form makes room - never one you wrote yourself
        old = next((k for k, c in enumerate(custom) if c.get("src") == "form" and _norm(c["q"]) not in new_qs), None)
        if old is None:
            old = next((k for k, c in enumerate(custom) if c.get("src") == "form"), None)
        if old is None:
            break
        custom.pop(old)
    b["custom"] = custom
    out = norm_bank(b)
    kept = {_norm(c["q"]) for c in out["custom"] if c.get("src") == "form"}
    saved = sum(1 for n in new_qs if n in kept)
    if saved < len(new_qs):
        skipped.append({"label": "", "why": "Your answer bank is full - remove some saved answers on the Auto page"})
    return out, saved, skipped
 
