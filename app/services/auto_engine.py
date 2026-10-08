"""Kaidostar Auto engine - the pure planner behind Auto (server side).
 
A line-for-line port of the browser's auto-engine.js. Given the jobs the Job
Search engine matched for a person (each already scored), their Auto rules and a
little context (what they already applied to, today's count, who they know
where), it decides - with a reason for every job - what Auto prepares now, what
waits for a later day and what it holds back. The Auto page runs the JS version
on the very candidate list this server sends it, so what the page previews is
exactly what the server does.
 
The defaults follow the evidence on what actually gets interviews: fewer,
better-fitting applications; one role per company at a time; fresh postings
first; the employer's own hiring site over job boards; never automate a site
that forbids it; stop rather than guess.
 
Pure: no database, no network, no clock (the time comes in ctx).
"""
from __future__ import annotations
 
import math
import re
 
VERSION = "1.0.0"
DAY = 86400000
STRONG = 70
ALWAYS_FLOOR = 55
FIT_MIN, FIT_MAX = 50, 97
TIER_DAILY_MAX = {"free": 0, "pro": 10, "max": 50}
DAILY_MAX, WEEKLY_MAX = 50, 250
DELAYS = [0, 30, 120, 720, 1440]
MAX_AGES = [0, 3, 7, 14, 21, 30, 60]
FOLLOWUPS = [0, 5, 7, 10, 14]
WINDOWS = [14, 30, 60, 90]
HOLD_DAYS = [1, 2, 3, 5, 7]
TYPES = ["job", "internship", "college"]
SIZES = ["startup", "small", "midmarket", "enterprise"]
LIST_KEYS = ["locations", "industries", "companySizes", "keywordsInclude", "keywordsExclude"]
LIST_CAP, ITEM_CHARS, COMPANY_CAP = 30, 80, 60
STRETCH_KEYS = {"years", "level"}
STRETCH_MIN_CAP = 64
FRESH_BONUS = {"new": 6, "fresh": 4, "recent": 2, "aging": 0, "old": -4, "unknown": -1}
WHAT_IF = [60, 65, 70, 75, 80, 85, 90]
SIZE_SIGNALS = {
    "startup": ["startup", "start-up", "seed", "series a", "series b", "early-stage", "early stage", "pre-seed"],
    "small": ["small business", "small team", "boutique", "smb"],
    "midmarket": ["mid-size", "midsize", "mid size", "scale-up", "scaleup", "growth-stage", "growth stage", "mid-market"],
    "enterprise": ["enterprise", "fortune 500", "publicly traded", "multinational", "global leader", "large organization"],
}
FREE_MAIL = ["gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com", "outlook.com", "live.com", "msn.com", "aol.com",
             "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com", "gmx.com", "gmx.net", "mail.com", "yandex.com", "zoho.com", "qq.com", "163.com"]
TYPE_NAMES = {"job": "jobs", "internship": "internships", "college": "fellowships & programs"}
BAND_NAMES = {"excellent": "Excellent", "strong": "Strong", "partial": "Partial", "weak": "Weak"}
HAY_MAX = 6000   # how much of a posting the keyword, field and size rules read (bounded: the page and the server both hold it)
 
 
def defaults() -> dict:
    return {
        "v": 2,
        "mode": "review",
        "minFit": 80,
        "allowStretch": False,
        "minConfidence": "any",
        "types": {"job": True, "internship": True, "college": False},
        "dailyCap": 5,
        "weeklyCap": 20,
        "perCompany": 1,
        "companyWindowDays": 30,
        "maxAgeDays": 14,
        "preferFresh": True,
        "skipGhost": "high",
        "skipAgencies": False,
        "skipReposts": False,
        "aggregators": "handoff",
        "remoteOnly": False,
        "locations": [], "industries": [], "companySizes": [], "keywordsInclude": [], "keywordsExclude": [],
        "salaryFloor": 0,
        "requireSalary": False,
        "deadlineMaxDays": 0,
        "companies": [],
        "avoidCurrentEmployer": True,
        "referral": "note",
        "referralHoldDays": 3,
        "coverLetter": "asked",
        "tailorResume": True,
        "delayMinutes": 720,
        "followUpDays": 7,
        "pausedUntil": None,
        "pauseOnInterview": False,
        "sendDays": "any",
        "tz": "",
        "outreach": False,
        "migratedFrom": 0,
    }
 
 
# ---------------------------------------------------------------- helpers
_WS = "[\t\n\v\f\r    -​    　﻿]"
_WS_RUN = re.compile(_WS + "+")
_NONWORD = re.compile(r"[\W_]+")
 
 
def clean(s, n=0) -> str:
    if not isinstance(s, str):
        return ""
    t = _WS_RUN.sub(" ", s).strip(" ")
    if n and len(t) > n:
        t = t[:n].rstrip(" ")
    return t
 
 
def lc(s) -> str:
    return ("" if s is None else str(s)).lower()
 
 
def num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v
 
 
def rnd(x) -> int:
    return int(math.floor(x + 0.5))
 
 
def int_in(v, lo, hi, d):
    x = num(v)
    if x is None:
        return d
    x = rnd(x)
    return lo if x < lo else (hi if x > hi else x)
 
 
def choice(v, lst, d):
    x = num(v)
    if x is None:
        return d
    x = rnd(x)
    return x if x in lst else d
 
 
def one_of(v, lst, d):
    return v if isinstance(v, str) and v in lst else d
 
 
def boolv(v, d):
    return True if v is True else (False if v is False else d)
 
 
def is_obj(v) -> bool:
    return isinstance(v, dict)
 
 
def arr(v) -> list:
    return v if isinstance(v, list) else []
 
 
def s_(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)
 
 
def _fmt_num(v) -> str:
    """A number the way JavaScript prints it in a string ("65", not "65.0")."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)
 
 
def plural(n, w, p=None) -> str:
    return _fmt_num(n) + " " + (w if n == 1 else (p or w + "s"))
 
 
def and_list(xs) -> str:
    xs = list(xs)
    return "".join(xs) if len(xs) <= 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
 
 
def norm_name(s) -> str:
    """'Acme, Inc.' -> 'acme inc': lower-case words of letters/digits, single spaces."""
    return _NONWORD.sub(" ", lc(s)).strip(" ")
 
 
def name_in(name, org) -> bool:
    """Whole-word containment: 'meta' is in 'meta platforms', 'apple' is not in 'pineapple express'."""
    a, b = norm_name(name), norm_name(org)
    if not a or not b:
        return False
    return (" " + a + " ") in (" " + b + " ")
 
 
def str_list(v, cap, chars) -> list:
    out, seen = [], set()
    for x in arr(v):
        if len(out) >= cap:
            break
        s = clean(x, chars)
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out
 
 
def company_list(v) -> list:
    out, seen = [], set()
    for c in arr(v):
        if len(out) >= COMPANY_CAP:
            break
        if not is_obj(c):
            continue
        name = clean(c.get("name"), ITEM_CHARS)
        rule = one_of(c.get("rule"), ["always", "never", "boost"], None)
        k = norm_name(name)
        if not name or not rule or not k or k in seen:
            continue
        seen.add(k)
        out.append({"name": name, "rule": rule})
    return out
 
 
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
 
 
def valid_date(s):
    if not isinstance(s, str) or not _DATE_RE.fullmatch(s):
        return None
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    if y < 2000 or y > 2100 or m < 1 or m > 12 or d < 1:
        return None
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    dim = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return s if d <= dim else None
 
 
def _days_from_civil(y, m, d) -> int:
    # days since 1970-01-01 (proleptic Gregorian), the same as Date.UTC / DAY
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468
 
 
def day_start(ymd) -> int:
    return _days_from_civil(int(ymd[0:4]), int(ymd[5:7]), int(ymd[8:10])) * DAY
 
 
_TZ_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}")
 
 
def valid_tz(s) -> str:
    return s if isinstance(s, str) and len(s) <= 64 and _TZ_RE.fullmatch(s) else ""
 
 
# ---------------------------------------------------------------- the rules
def norm_rules(raw, threshold=None) -> dict:
    """Every stored rule set - this version's, the previous Auto's, or a hand-edited
    one - comes out the same well-formed shape with every value in range.
    `threshold` is the legacy fit bar stored alongside (used when minFit is absent)."""
    d = defaults()
    r = raw if is_obj(raw) else {}
    v1 = not (num(r.get("v")) is not None and r.get("v") == 2) and len(r) > 0
    out = defaults()
    mf = r.get("minFit") if num(r.get("minFit")) is not None else (threshold if num(threshold) is not None else d["minFit"])
    out["minFit"] = int_in(mf, FIT_MIN, FIT_MAX, d["minFit"])
    if v1:
        mode = r.get("mode")
        out["mode"] = "review" if mode == "draft_only" else ("auto" if (mode == "auto_approve" or r.get("autonomous") is True) else d["mode"])
        out["delayMinutes"] = 0 if r.get("autonomous") is True else 30
        out["skipGhost"] = "off" if r.get("skipHighGhostRisk") is False else "high"
        out["minConfidence"] = "high" if r.get("requireStrongSignal") is True else "any"
        cap = num(r.get("dailyCap"))
        out["dailyCap"] = d["dailyCap"] if cap is None else (DAILY_MAX if rnd(cap) <= 0 else int_in(cap, 1, DAILY_MAX, d["dailyCap"]))
        out["outreach"] = boolv(r.get("outreach"), False)
        out["migratedFrom"] = 1
    else:
        out["mode"] = one_of(r.get("mode"), ["review", "auto"], d["mode"])
        out["delayMinutes"] = choice(r.get("delayMinutes"), DELAYS, d["delayMinutes"])
        out["skipGhost"] = one_of(r.get("skipGhost"), ["high", "elevated", "off"], d["skipGhost"])
        out["minConfidence"] = one_of(r.get("minConfidence"), ["any", "medium", "high"], d["minConfidence"])
        out["dailyCap"] = int_in(r.get("dailyCap"), 1, DAILY_MAX, d["dailyCap"])
        out["outreach"] = boolv(r.get("outreach"), d["outreach"])
        out["migratedFrom"] = int_in(r.get("migratedFrom"), 0, 1, 0)
    t = r.get("types") if is_obj(r.get("types")) else {}
    out["types"] = {k: boolv(t.get(k), d["types"][k]) for k in TYPES}
    out["allowStretch"] = boolv(r.get("allowStretch"), d["allowStretch"])
    out["weeklyCap"] = int_in(r.get("weeklyCap"), 0, WEEKLY_MAX, d["weeklyCap"])
    out["perCompany"] = int_in(r.get("perCompany"), 1, 3, d["perCompany"])
    out["companyWindowDays"] = choice(r.get("companyWindowDays"), WINDOWS, d["companyWindowDays"])
    out["maxAgeDays"] = choice(r.get("maxAgeDays"), MAX_AGES, d["maxAgeDays"])
    out["preferFresh"] = boolv(r.get("preferFresh"), d["preferFresh"])
    out["skipAgencies"] = boolv(r.get("skipAgencies"), d["skipAgencies"])
    out["skipReposts"] = boolv(r.get("skipReposts"), d["skipReposts"])
    out["aggregators"] = one_of(r.get("aggregators"), ["handoff", "skip"], d["aggregators"])
    out["remoteOnly"] = boolv(r.get("remoteOnly"), d["remoteOnly"])
    for k in LIST_KEYS:
        out[k] = str_list(r.get(k), LIST_CAP, ITEM_CHARS)
    out["companySizes"] = [s for s in (x.lower() for x in out["companySizes"]) if s in SIZES]
    out["salaryFloor"] = int_in(r.get("salaryFloor"), 0, 1000, d["salaryFloor"])
    out["requireSalary"] = boolv(r.get("requireSalary"), d["requireSalary"])
    out["deadlineMaxDays"] = int_in(r.get("deadlineMaxDays"), 0, 365, d["deadlineMaxDays"])
    out["companies"] = company_list(r.get("companies"))
    out["avoidCurrentEmployer"] = boolv(r.get("avoidCurrentEmployer"), d["avoidCurrentEmployer"])
    out["referral"] = one_of(r.get("referral"), ["note", "hold", "off"], d["referral"])
    out["referralHoldDays"] = choice(r.get("referralHoldDays"), HOLD_DAYS, d["referralHoldDays"])
    out["coverLetter"] = one_of(r.get("coverLetter"), ["asked", "always", "never"], d["coverLetter"])
    out["tailorResume"] = boolv(r.get("tailorResume"), d["tailorResume"])
    out["followUpDays"] = choice(r.get("followUpDays"), FOLLOWUPS, d["followUpDays"])
    out["pausedUntil"] = valid_date(r.get("pausedUntil"))
    out["pauseOnInterview"] = boolv(r.get("pauseOnInterview"), d["pauseOnInterview"])
    out["sendDays"] = one_of(r.get("sendDays"), ["any", "weekdays"], d["sendDays"])
    out["tz"] = valid_tz(r.get("tz"))
    return out
 
 
# ---------------------------------------------------------------- candidates
def is_stretch(s) -> bool:
    if not s or s.get("fit") is None or s["fit"] >= STRONG or s.get("fitUncapped") is None or s["fitUncapped"] < STRONG:
        return False
    any_ = False
    for c in arr(s.get("caps")):
        if not c or c.get("cap", 0) >= STRONG:
            continue
        if c.get("key") in STRETCH_KEYS and c.get("cap", 0) >= STRETCH_MIN_CAP:
            any_ = True
            continue
        return False
    return any_
 
 
_COVER_RE = re.compile(r"(?<![a-z])cover(?:ing)?[ -]letters?(?![a-z])")
_SP = "[ \t\n\r\f\v\u00a0]"
_NO_COVER_RE = re.compile(r"(?<![a-z])(?:no|without|not (?:required|necessary|needed)[^.]{0,20})" + _SP + r"*(?:a" + _SP + r"+)?cover[ -]letters?|cover[ -]letters?" + _SP + r"+(?:is|are)" + _SP + r"+(?:not|optional)")
_EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,24}")
# "send your resume to", "apply by email", "to apply, email", "applications should be sent to" - said about THIS address
_APPLY_VERB = r"(?:send(?:ing)?|e-?mail(?:ing)?|submit(?:ting)?|forward(?:ing)?|mail(?:ing)?|direct(?:ing)?)"
_DOC_NOUN = r"(?:resumes?|résumés?|cvs?|applications?|cover" + _SP + r"+letters?)"
_APPLY_RE = re.compile(r"(?<![a-z])(?:" + _APPLY_VERB + r"(?:" + _SP + r"+[a-z']{1,12}){0,3}" + _SP + r"+" + _DOC_NOUN
                       + r"|apply" + _SP + r"+(?:by|via|through|with)" + _SP + r"+e-?mail"
                       + r"|to" + _SP + r"+apply[,:]?" + _SP + r"+(?:please" + _SP + r"+)?(?:send|e-?mail|contact|write|reach)"
                       + r"|" + _DOC_NOUN + _SP + r"+(?:should|can|may|must|will)" + _SP + r"+be" + _SP + r"+(?:sent|e-?mailed|submitted|forwarded|directed)"
                       + r")(?![a-z])")
# ... and not an accommodations / questions / "please don't" sentence, nor one asking for things Kaidostar can't attach
_NOT_APPLY_RE = re.compile(r"(?<![a-z])(?:accommodat[a-z]*|accessib[a-z]*|disabilit[a-z]*|assistance|questions?|inquir[a-z]*|enquir[a-z]*|difficult[a-z]*"
                           r"|trouble|problems?|unable|privacy|eeo|references?|portfolios?|samples?|transcripts?|unsolicited|agenc(?:y|ies)|recruiters?"
                           r"|do" + _SP + r"+not|don't|dont|never)(?![a-z])")
_TRAIL_RE = re.compile(r"[.\-]+$")
_SENTENCE_ENDS = (". ", "! ", "? ", "; ", "\n")
EMAIL_SKIP = ["accommodation", "accommodations", "accessibility", "ada", "privacy", "dpo", "gdpr", "legal", "compliance", "security", "abuse",
 "support", "help", "helpdesk", "reply", "webmaster", "eeo", "eeoc", "benefits", "payroll", "press", "media", "billing", "invoice",
 "invoices", "feedback", "unsubscribe", "ethics", "accounts", "accounting", "finance", "orders", "newsletter", "notifications", "alerts",
 "admin", "postmaster", "hostmaster", "marketing", "sales"]
 
 
def _email_skip(local) -> bool:
    """An address that is plainly not where applications go (accommodations@, privacy@, no-reply@...)."""
    flat = re.sub(r"[^a-z]", "", local)
    if "noreply" in flat or "donotreply" in flat:
        return True
    return any(tok in EMAIL_SKIP for tok in re.split(r"[^a-z]+", local))
 
 
def posting_email(text) -> str:
    """The address a posting itself says to send applications to, or ''. Only when the same sentence
    says to apply/send your resume there - never an accommodations, questions or privacy address."""
    t = lc(text).replace("\u2019", "'").replace("\u2018", "'")   # "don’t send" is "don't send"
    for m in _EMAIL_RE.finditer(t):
        addr = _TRAIL_RE.sub("", m.group(0))
        if _email_skip(addr.split("@")[0]):
            continue
        before = t[:m.start()]
        cut = max(before.rfind(e) for e in _SENTENCE_ENDS)
        clause = before[cut + 1:]
        if _APPLY_RE.search(clause) and not _NOT_APPLY_RE.search(clause):
            return addr
    return ""
 
 
def _domain_of(email) -> str:
    i = email.rfind("@")
    return email[i + 1:] if i >= 0 else ""
 
 
MULTI_SUFFIX = ["co.uk", "org.uk", "ac.uk", "gov.uk", "ltd.uk", "plc.uk", "me.uk", "net.uk", "com.au", "net.au", "org.au", "edu.au", "gov.au", "co.nz",
 "org.nz", "net.nz", "co.jp", "ne.jp", "or.jp", "co.in", "net.in", "org.in", "com.br", "net.br", "org.br", "com.mx", "org.mx", "co.za",
 "org.za", "com.sg", "edu.sg", "com.hk", "org.hk", "com.cn", "net.cn", "org.cn", "co.kr", "or.kr", "com.tw", "com.tr", "com.ar", "com.co",
 "com.pe", "com.ph", "com.my", "co.id", "co.il", "co.th", "com.vn", "com.pk", "com.ng", "com.eg", "com.sa", "co.ke", "com.ua", "co.at",
 "or.at", "com.pl", "co.ve", "com.ec", "com.uy", "com.do", "com.gt", "com.bd", "com.np", "com.lk", "com.qa", "com.kw", "com.bh", "com.om",
 "co.ug", "co.tz", "com.gh"]
# platforms that host many companies' sites and hiring pages: sharing one says nothing about who owns an address
SHARED_HOSTS = ["github.io", "gitlab.io", "herokuapp.com", "netlify.app", "vercel.app", "pages.dev", "web.app", "firebaseapp.com", "wixsite.com",
 "squarespace.com", "wordpress.com", "blogspot.com", "weebly.com", "webflow.io", "notion.site", "carrd.co", "myworkdayjobs.com",
 "greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com", "workable.com", "recruitee.com", "bamboohr.com", "jobvite.com",
 "icims.com", "taleo.net", "breezy.hr", "applytojob.com", "jazzhr.com", "teamtailor.com", "personio.de", "ultipro.com", "dayforcehcm.com",
 "freshteam.com", "zohorecruit.com", "pinpointhq.com", "trakstar.com", "comeet.com"]
ORG_LEGAL = ["inc", "llc", "ltd", "corp", "corporation", "incorporated", "limited", "the", "and", "group", "company", "co", "plc", "gmbh", "ag", "sa",
 "llp", "lp", "holdings"]
ORG_GENERIC = ["global", "international", "solutions", "services", "systems", "technologies", "technology", "tech", "labs", "health", "healthcare",
 "partners", "consulting", "capital", "bank", "financial", "digital", "media", "network", "networks", "software", "data", "analytics",
 "careers", "jobs", "talent", "staffing", "recruiting", "agency", "associates", "enterprises", "industries", "foundation", "university",
 "college", "school", "institute", "center", "centre", "hospital", "medical", "energy", "world", "online", "apps", "cloud", "design",
 "studio", "studios", "games", "marketing", "american", "national", "united", "first"]
 
 
def registrable(domain) -> str:
    """'careers.acme.co.uk' -> 'acme.co.uk', 'jobs.acme.com' -> 'acme.com'."""
    parts = [x for x in s_(domain).strip(".").split(".") if x]
    if len(parts) <= 2:
        return ".".join(parts)
    last2 = ".".join(parts[-2:])
    return ".".join(parts[-3:]) if (last2 in MULTI_SUFFIX or last2 in SHARED_HOSTS) else last2
 
 
def email_trusted(c) -> bool:
    """A posting's own address is used only when it plainly belongs to the company: never a free mail
    provider or a shared platform, and either on the same site as the posting or named after the company."""
    e = s_(c.get("emailTo"))
    if not e:
        return False
    dom = _domain_of(e)
    if not dom or dom in FREE_MAIL or ".".join(dom.split(".")[-2:]) in SHARED_HOSTS:
        return False
    reg = registrable(dom)
    if len(reg.split(".")) < 2:
        return False
    host = lc(c.get("host"))
    if host and ".".join(host.split(".")[-2:]) not in SHARED_HOSTS and registrable(host) == reg:
        return True
    label = reg.split(".")[0]
    core = [w for w in norm_name(c.get("org")).split(" ") if w and w not in ORG_LEGAL]
    flat = "".join(core)
    if len(flat) >= 3 and label == flat:
        return True
    return any(len(w) >= 4 and w not in ORG_GENERIC and label == w for w in core)
 
 
def _text_slice(v, n) -> str:
    t = s_(v)
    return t[:n] if len(t) > n else t
 
 
def candidate_from(it, norm_org=None) -> dict:
    """One job as Auto reads it - built from a Job Search analysis item (the same on the page and the server)."""
    j, s, o = it["job"], it["score"], it["opp"]
    ids = [s_(j.get("id"))]
    for d in arr(j.get("duplicates")):
        if d and d.get("id") is not None and s_(d.get("id")) not in ids:
            ids.append(s_(d.get("id")))
    desc = s_(j.get("description"))
    skills = [x for x in (s_(sk.get("name") if sk else None) for sk in arr(j.get("skills"))) if x][:20]
    hay = _text_slice(lc(s_(j.get("title")) + " \n " + ", ".join(skills) + " \n " + desc), HAY_MAX)
    ok = norm_org(j.get("org")) if norm_org else norm_name(j.get("org"))
    dl = lc(desc)
    cover = bool(_COVER_RE.search(dl)) and not _NO_COVER_RE.search(dl)
    sal = j.get("salary") or None
    cap_applied = s.get("capApplied")
    return {
        "id": s_(j.get("id")), "ids": ids,
        "title": clean(s_(j.get("title")), 200), "org": clean(s_(j.get("org")), 120), "orgKey": ok or ("#" + s_(j.get("id"))),
        "type": s_(j.get("type")), "location": clean(s_(j.get("location")), 160), "mode": j.get("mode") or None,
        "fit": s.get("fit"), "fitUncapped": s.get("fitUncapped"), "band": s.get("band"), "confidence": s.get("confidence"),
        "stretch": is_stretch(s), "capWhy": clean(s_(cap_applied.get("why")), 160) if cap_applied else "",
        "positives": [clean(s_(p.get("text") if p else None), 160) for p in arr(s.get("positives"))[:3]],
        "gaps": [clean(s_(g.get("text") if g else None), 160) for g in arr(s.get("gaps"))[:2]],
        "ageDays": o.get("ageDays"), "freshness": o.get("freshness"), "ghost": o.get("ghost"),
        "ghostReasons": [clean(s_(x), 120) for x in arr(o.get("ghostReasons"))[:3]],
        "repostCount": o.get("repostCount") or 0, "route": o.get("applyRoute"), "host": _text_slice(o.get("applyHost"), 120),
        "applyUrl": _text_slice(j.get("applyUrl"), 600),
        "agency": bool(j.get("agency") and j["agency"].get("is")), "evergreen": bool(j.get("evergreen") and j["evergreen"].get("is")),
        "salaryMin": sal.get("annualMin") if sal else None, "salaryMax": sal.get("annualMax") if sal else None,
        "salarySource": (sal.get("source") or None) if sal else None,
        "deadline": s_(j.get("deadline"))[:10] if j.get("deadline") else None,
        "skills": skills, "coverAsked": cover, "emailTo": posting_email(desc), "source": s_(j.get("source")),
        "hay": hay,
    }
 
 
# ---------------------------------------------------------------- the plan
def days_left(deadline, now):
    ymd = valid_date(s_(deadline)[:10])
    if not ymd or num(now) is None:
        return None
    today = math.floor(now / DAY) * DAY
    return math.floor((day_start(ymd) - today) / DAY)
 
 
def _company_rule(rules, org, rule):
    for c in rules["companies"]:
        if c["rule"] == rule and name_in(c["name"], org):
            return c
    return None
 
 
def _current_employer(rules, ctx, org):
    if not rules["avoidCurrentEmployer"]:
        return None
    for x in arr(ctx.get("currentEmployers")):
        if name_in(x, org) or name_in(org, x):
            return x
    return None
 
 
def _contacts_at(ctx, c) -> list:
    m = ctx.get("contacts") if is_obj(ctx.get("contacts")) else {}
    out = []
    for company in sorted(m.keys()):
        if name_in(company, c["org"]) or name_in(c["org"], company):
            for n in arr(m[company]):
                if s_(n) not in out:
                    out.append(s_(n))
    return out[:5]
 
 
def _salary_top(c):
    a, b = num(c.get("salaryMin")), num(c.get("salaryMax"))
    if a is None and b is None:
        return None
    return max(0 if a is None else a, 0 if b is None else b)
 
 
_REMOTE_RE = re.compile(r"(?<![a-z])remote(?![a-z])")
 
 
def _is_remote(c) -> bool:
    return c.get("mode") == "remote" or bool(_REMOTE_RE.search(lc(c.get("location"))))
 
 
def _age_text(n) -> str:
    return "Posted today" if n == 0 else ("Posted yesterday" if n == 1 else f"Posted {n} days ago")
 
 
def _close_text(n) -> str:
    return "Closes today" if n == 0 else ("Closes tomorrow" if n == 1 else f"Closes in {n} days")
 
 
def evaluate(c, rules, ctx, skip_fit=False) -> dict:
    now = num(ctx.get("now")) or 0
    res = {"state": "ok", "key": "", "why": "", "always": False, "boost": False, "stretch": False, "dl": days_left(c.get("deadline"), now)}
 
    def out(state, key, why):
        res["state"], res["key"], res["why"] = state, key, why
        return res
    if num(c.get("fit")) is None:
        return out("excluded", "unscored", "The posting says too little to score")
    taken = ctx.get("taken") if is_obj(ctx.get("taken")) else {}
    for i in c["ids"]:
        if taken.get(i):
            return out("excluded", "applied", "You already have an application for this job")
    if res["dl"] is not None and res["dl"] < 0:
        return out("excluded", "closed", "Its closing date has passed")
    never = _company_rule(rules, c["org"], "never")
    if never:
        return out("excluded", "never", "On your never-apply list (" + never["name"] + ")")
    cur = _current_employer(rules, ctx, c["org"])
    if cur:
        return out("excluded", "current_employer", "Your current employer (" + s_(cur) + ")")
    always = _company_rule(rules, c["org"], "always")
    res["always"] = bool(always)
    res["boost"] = bool(_company_rule(rules, c["org"], "boost"))
    if rules["types"].get(c.get("type")) is False:
        return out("held", "type", "You turned off " + TYPE_NAMES.get(c.get("type"), s_(c.get("type"))))
    fit = c["fit"]
    floor = min(rules["minFit"], ALWAYS_FLOOR) if always else rules["minFit"]
    if not skip_fit and fit < floor:
        if c.get("stretch") and rules["allowStretch"] and not always:
            res["stretch"] = True
        else:
            return out("held", "fit", "Fit " + _fmt_num(fit) + " - below your " + _fmt_num(floor))
    elif c.get("stretch"):
        res["stretch"] = True   # clears your bar, but it's a level or years stretch: Auto still asks you first
    conf = c.get("confidence")
    if rules["minConfidence"] == "high" and conf != "high":
        return out("held", "confidence", "Kaidostar is only " + s_(conf) + "-confidence in this fit")
    if rules["minConfidence"] == "medium" and conf == "low":
        return out("held", "confidence", "Kaidostar is only low-confidence in this fit")
    if c.get("evergreen") and not always:
        return out("held", "evergreen", 'A standing "talent pool" post, not a specific opening')
    g = c.get("ghost")
    if (rules["skipGhost"] == "high" and g == "high") or (rules["skipGhost"] == "elevated" and g in ("high", "elevated")):
        gr = arr(c.get("ghostReasons"))
        return out("held", "ghost", "May not be a live opening (" + ((gr[0] if gr else "") or "ghost-job signals") + ")")
    if rules["skipAgencies"] and c.get("agency"):
        return out("held", "agency", "Posted by a staffing agency")
    if rules["skipReposts"] and (num(c.get("repostCount")) or 0) >= 1:
        return out("held", "repost", "Reposted " + plural(c["repostCount"], "time"))
    hay = c.get("hay") or ""
    for w in rules["keywordsExclude"]:
        if w.lower() in hay:
            return out("held", "keyword_excluded", 'Mentions "' + w + '" (on your exclude list)')
    if rules["aggregators"] == "skip" and c.get("route") == "aggregator":
        return out("held", "aggregator", "Only on a job board (" + (c.get("host") or "unknown site") + ") - you chose to skip those")
    if not always:
        age = c.get("ageDays")
        if rules["maxAgeDays"] > 0 and num(age) is not None and age > rules["maxAgeDays"]:
            return out("held", "age", "Posted " + _fmt_num(age) + " days ago - older than your " + str(rules["maxAgeDays"]) + "-day limit")
        if rules["remoteOnly"] and not _is_remote(c):
            return out("held", "remote", "Not remote")
        if rules["locations"]:
            loc = lc(c.get("location"))
            ok_loc = False
            for term in rules["locations"]:
                term = term.lower()
                if (_is_remote(c) if term == "remote" else term in loc):
                    ok_loc = True
                    break
            if not ok_loc:
                return out("held", "location", "Not in your target locations")
        if rules["industries"] and not any(x.lower() in hay for x in rules["industries"]):
            return out("held", "industry", "Not in your target fields")
        if rules["companySizes"] and not any(any(w in hay for w in SIZE_SIGNALS.get(sz, [])) for sz in rules["companySizes"]):
            return out("held", "size", "Company size not stated as one you picked")
        if rules["keywordsInclude"] and not any(x.lower() in hay for x in rules["keywordsInclude"]):
            return out("held", "keyword_missing", "Has none of your must-have keywords")
        top = _salary_top(c)
        if rules["salaryFloor"] > 0 and top is not None and top < rules["salaryFloor"] * 1000:
            return out("held", "salary", ("Estimated to pay" if c.get("salarySource") == "estimated" else "Pays") + " up to $" + str(rnd(top / 1000)) + "k - under your $" + str(rules["salaryFloor"]) + "k floor")
        if rules["requireSalary"] and top is None:
            return out("held", "salary_missing", "Doesn’t state pay (you asked for jobs that do)")
        if rules["deadlineMaxDays"] > 0 and (res["dl"] is None or res["dl"] > rules["deadlineMaxDays"]):
            return out("held", "deadline", "Not closing within " + str(rules["deadlineMaxDays"]) + " days")
    return res
 
 
def delivery_for(c, rules, ctx) -> dict:
    route, host = c.get("route"), c.get("host") or ""
    if route == "aggregator":
        return {"method": "handoff", "key": "aggregator", "why": (host or "This") + " is a job board - Kaidostar never applies for you on job boards, so you’ll get a ready-to-submit kit"}
    if route not in ("employer", "company_site"):
        return {"method": "handoff", "key": "no_link", "why": "No standard application link - you’ll get a ready-to-submit kit"}
    if not ctx.get("consent"):
        return {"method": "handoff", "key": "consent", "why": "You haven’t let Kaidostar submit for you - you’ll get a ready-to-submit kit"}
    # by email only where the posting says so on the company's own site (an employer's hiring system has its
    # form for that), and only when this server can send email
    if c.get("emailTo") and route == "company_site" and ctx.get("emailReady"):
        if email_trusted(c):
            return {"method": "email", "key": "email", "why": "Emailed on your behalf to " + c["emailTo"] + " (the address the posting gives) with your resume attached - replies go to you"}
        return {"method": "handoff", "key": "email_untrusted", "why": "The posting asks for email to " + c["emailTo"] + ", which doesn’t look like the company’s own address - check it yourself"}
    if route == "company_site":
        # a company's own site may hold other forms (a general "send us your CV"): never submitted on its own
        return {"method": "extension", "key": "extension", "why": "On the company’s own careers site - the Kaidostar Apply extension fills it and you click submit (or use the kit)"}
    if ctx.get("browserAvailable"):
        return {"method": "auto_submit", "key": "auto_submit", "why": "Kaidostar fills and submits it on " + (host or "the employer’s hiring system") + ", and stops if anything needs you"}
    return {"method": "extension", "key": "extension", "why": "Ready for one-click submit in the Kaidostar Apply extension (or the kit) - this server can’t open a browser"}
 
 
def _id_key(c):
    return c["id"]
 
 
def plan(cands, rules, ctx) -> dict:
    """The plan for this moment: what Auto prepares now, what waits, what it holds back - every job with a reason."""
    rules = norm_rules(rules)
    ctx = ctx if is_obj(ctx) else {}
    now = num(ctx.get("now")) or 0
    excluded = {"applied": 0, "closed": 0, "never": 0, "current_employer": 0, "unscored": 0}
    held, held_counts, ok, what_if_ok = [], {}, [], []
    for c in arr(cands):
        if not is_obj(c) or not isinstance(c.get("ids"), list):
            continue
        ev = evaluate(c, rules, ctx, False)
        if ev["state"] == "excluded":
            excluded[ev["key"]] = excluded.get(ev["key"], 0) + 1
            continue
        evw = evaluate(c, rules, ctx, True) if ((ev["state"] == "held" and ev["key"] == "fit") or ev["stretch"]) else ev
        if evw["state"] == "ok":
            what_if_ok.append({"fit": c["fit"], "always": evw["always"]})
        if ev["state"] == "held":
            held.append({"c": c, "key": ev["key"], "why": ev["why"]})
            held_counts[ev["key"]] = held_counts.get(ev["key"], 0) + 1
            continue
        ok.append({"c": c, "ev": ev})
    for x in ok:
        c, ev = x["c"], x["ev"]
        p = c["fit"]
        if rules["preferFresh"]:
            p += FRESH_BONUS.get(c.get("freshness"), 0) if isinstance(c.get("freshness"), str) else 0
        if ev["always"]:
            p += 8
        if ev["boost"]:
            p += 5
        if c.get("route") == "employer":
            p += 2
        elif c.get("route") == "company_site":
            p += 1
        if ev["dl"] is not None and ev["dl"] <= 7:
            p += 3
        if ev["stretch"]:
            p -= 6
        if c.get("ghost") == "elevated":
            p -= 2
        x["p"] = p
    ok.sort(key=lambda x: (-x["p"], -x["c"]["fit"], 1e9 if x["c"].get("ageDays") is None else x["c"]["ageDays"], x["c"]["id"]))
    since = now - rules["companyWindowDays"] * DAY
    recent, last_at = {}, {}
    for h in arr(ctx.get("history")):
        if not is_obj(h) or h.get("status") == "undone" or num(h.get("at")) is None or h["at"] < since:
            continue
        k = s_(h.get("orgKey"))
        if not k:
            continue
        recent[k] = recent.get(k, 0) + 1
        if not last_at.get(k) or h["at"] > last_at[k]:
            last_at[k] = h["at"]
    planned, accepted = {}, []
    for x in ok:
        k = x["c"]["orgKey"]
        have = recent.get(k, 0) + planned.get(k, 0)
        if have >= rules["perCompany"]:
            if planned.get(k) and not recent.get(k):
                why = "A better-fitting " + x["c"]["org"] + " role is already in this plan (one per company)"
            else:
                days = max(0, math.floor((now - (last_at.get(k) or now)) / DAY))
                why = "Applied to " + x["c"]["org"] + " " + str(days) + " days ago - one role per company every " + str(rules["companyWindowDays"]) + " days"
            held.append({"c": x["c"], "key": "company_limit", "why": why})
            held_counts["company_limit"] = held_counts.get("company_limit", 0) + 1
            continue
        planned[k] = planned.get(k, 0) + 1
        accepted.append(x)
    held.sort(key=lambda h: (-h["c"]["fit"], h["c"]["id"]))
    paused = ""
    if rules["pausedUntil"] and now < day_start(rules["pausedUntil"]):
        paused = "until"
    elif rules["pauseOnInterview"] and (num(ctx.get("interviewsActive")) or 0) > 0:
        paused = "interview"
    tier_max = int_in(ctx.get("tierMax"), 0, DAILY_MAX, 0)
    cap = min(rules["dailyCap"], tier_max)
    made_today = max(0, int_in(ctx.get("madeToday"), 0, 100000, 0))
    made_week = max(0, int_in(ctx.get("madeWeek"), 0, 100000, 0))
    remaining_today = max(0, cap - made_today)
    remaining_week = max(0, rules["weeklyCap"] - made_week) if rules["weeklyCap"] > 0 else None
    slots = 0 if paused else (remaining_today if remaining_week is None else min(remaining_today, remaining_week))
    queue, waiting = [], []
    for i, x in enumerate(accepted):
        c, ev = x["c"], x["ev"]
        reasons = ["Fit " + _fmt_num(c["fit"]) + " · " + BAND_NAMES.get(c.get("band"), "Scored")]
        if num(c.get("ageDays")) is not None:
            reasons.append(_age_text(c["ageDays"]))
        else:
            reasons.append("Posting date unknown")
        if c.get("route") == "employer":
            reasons.append("On the employer’s own hiring site")
        elif c.get("route") == "company_site":
            reasons.append("On the company’s careers site")
        if ev["always"]:
            reasons.append("On your always list")
        if ev["boost"]:
            reasons.append("A company you prioritized")
        if ev["dl"] is not None and ev["dl"] <= 7:
            reasons.append(_close_text(ev["dl"]))
        if i >= slots:
            if paused:
                wk = "paused"
            else:
                wk = "cap_week" if (remaining_week is not None and remaining_week <= remaining_today and i >= remaining_week) else "cap_today"
            waiting.append({"c": c, "p": x["p"], "key": wk, "reasons": reasons, "position": i - slots + 1})
            continue
        needs = []
        if ev["stretch"]:
            needs.append({"key": "stretch", "why": "A stretch role (" + (c.get("capWhy") or "a level or years gap") + ") - Auto always asks you first"})
        contacts = _contacts_at(ctx, c)
        hold = ({"days": rules["referralHoldDays"], "contact": contacts[0],
                 "why": "Waits " + plural(rules["referralHoldDays"], "day") + " so you can ask " + contacts[0] + " for a referral first"}
                if (contacts and rules["referral"] == "hold") else None)
        dv = delivery_for(c, rules, ctx)
        missing = [s_(m) for m in arr(ctx.get("answersMissing"))]
        if dv["method"] in ("auto_submit", "extension") and missing:
            needs.append({"key": "answers", "why": "Add your " + and_list(missing) + " answers so forms can be finished"})
        status = "send" if (rules["mode"] == "auto" and not needs) else "review"
        queue.append({"c": c, "p": x["p"], "reasons": reasons, "needs": needs, "hold": hold, "delivery": dv, "status": status,
                      "contacts": [] if rules["referral"] == "off" else contacts})
    what_if = []
    for t in WHAT_IF:
        n = 0
        for w in what_if_ok:
            if w["fit"] >= (min(t, ALWAYS_FLOOR) if w["always"] else t):
                n += 1
        what_if.append({"minFit": t, "n": n})
    return {
        "version": VERSION, "queue": queue, "waiting": waiting, "held": held, "heldCounts": held_counts, "excluded": excluded,
        "paused": paused, "considered": len(arr(cands)),
        "capacity": {"cap": cap, "tierMax": tier_max, "madeToday": made_today, "remainingToday": remaining_today,
                     "weeklyCap": rules["weeklyCap"], "madeWeek": made_week, "remainingWeek": remaining_week, "slots": slots},
        "whatIf": what_if,
    }
 
 
def plan_summary(p) -> dict:
    """A small, JSON-friendly digest of a plan for the run log."""
    return {
        "queued": [{"id": q["c"]["id"], "title": q["c"]["title"], "org": q["c"]["org"], "fit": q["c"]["fit"], "status": q["status"],
                    "delivery": q["delivery"]["method"]} for q in p["queue"]],
        "waiting": len(p["waiting"]), "held": len(p["held"]), "heldCounts": dict(p["heldCounts"]), "excluded": dict(p["excluded"]),
        "paused": p["paused"], "considered": p["considered"], "capacity": dict(p["capacity"]),
    }
 
