"""Kaidostar Job Search v2 - "Proof Match" engine (server side).

A line-for-line mirror of kaidostar-frontend/job-engine.js. Both engines take
the same listing + profile + preferences and must return the same JSON, so a
job reads the same score in the browser, in auto-apply and in alerts. The
parity test (kaido_jobsearch_parity_test.py) runs both on hundreds of fuzzed
inputs and fails on any difference.

Every number here traces to a sentence in the posting and, where it rewards
you, a line from your own resume. Nothing is remapped to look better.

Pure functions: no DB, no network, no clock. Callers pass `now` in ms.
Output keys are camelCase on purpose - they are the same dicts the browser
engine produces, and the frontend renders them directly.
"""
import collections
import functools
import math
import re
import threading
from datetime import datetime, timezone

try:  # package import (FastAPI app) or flat import (tests run from repo root)
    from app.services import job_taxonomy as T
except Exception:  # pragma: no cover
    import job_taxonomy as T  # type: ignore

ENGINE_VERSION = "2.1.0"
DAY = 86400000


# --------------------------------------------------------------------- utils
def jsnum(v):
    """String(v) the way JavaScript prints numbers (2.0 -> '2')."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v) if abs(v) < 10 ** 21 else jsnum(float(v))
    if isinstance(v, float):
        if v != v:
            return "NaN"
        if v in (float("inf"), float("-inf")):
            return "Infinity" if v > 0 else "-Infinity"
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        return re.sub(r"e([+-])0*([0-9])", r"e\1\2", repr(v))
    return str(v)


_ODD_CH = re.compile("[\ufeff\x1c-\x1f\x85]")
_ODD_DROP = re.compile("[\ufeff\x1c-\x1f]")


def _js_string(v):
    """String(v) as JavaScript writes it."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (bool, int, float)):
        return jsnum(v)
    if isinstance(v, (list, tuple)):
        return ",".join(_js_string(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


def _s(v):
    # Text in. The BOM, the C0 separators and NEL are dropped/turned into a
    # newline here (and in str() in job-engine.js): they are the only
    # characters JS and Python disagree on as whitespace, so with them gone
    # every \s, trim() and strip() behaves identically in both engines.
    s = _js_string(v)
    if _ODD_CH.search(s):
        s = _ODD_DROP.sub("", s).replace("\x85", "\n")
    return s


def lc(v):
    return _s(v).lower()


def rhu(x):
    return math.floor(x + 0.5)


def round1(x):
    return math.floor(x * 10 + 0.5) / 10


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _prop_key(k):
    # the property name JS uses for a value in an object key ({}[k])
    return "null" if k is None else _js_string(k)


def uniq(arr):
    # keyed the way the JS engine keys it (String(k)), so [1, "1"] dedupes the same
    out, seen = [], set()
    for k in arr:
        pk = _prop_key(k)
        if pk not in seen:
            seen.add(pk)
            out.append(k)
    return out


_ESC = re.compile(r"([.*+?^${}()|\[\]\\/])")


def esc_re(s):
    return _ESC.sub(r"\\\1", s)


def _js_len(s):
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def _u16_before(s, i, n):
    """s[i-n:i] measured in UTF-16 units, like JS slice() (an emoji is 2)."""
    j, u = i, 0
    while j > 0:
        w = 2 if ord(s[j - 1]) > 0xFFFF else 1
        if u + w > n:
            break
        u += w
        j -= 1
    return s[j:i]


def _u16_after(s, i, n):
    """s[i:i+n] measured in UTF-16 units, like JS slice()."""
    j, u, L = i, 0, len(s)
    while j < L:
        w = 2 if ord(s[j]) > 0xFFFF else 1
        if u + w > n:
            break
        u += w
        j += 1
    return s[i:j]


def _js_slice(s, n):
    return s.encode("utf-16-le", "surrogatepass")[: 2 * n].decode("utf-16-le", errors="ignore")


_WS = re.compile(r"\s+")


def trunc(s, n):
    # normalise only a prefix that is surely long enough - same result as the whole string
    raw, lim = _s(s), n * 4 + 64
    s = _WS.sub(" ", raw[:lim] if len(raw) > lim else raw).strip()
    if len(raw) > lim and _js_len(s) <= n:
        s = _WS.sub(" ", raw).strip()
    if _js_len(s) > n:
        return re.sub(r"\s+\S*$", "", _js_slice(s, n - 1)) + "…"
    return s


B4 = r"(?<![A-Za-z0-9])"
AF = r"(?![A-Za-z0-9+#&])"


@functools.lru_cache(maxsize=8192)
def word_re(phrase):
    return re.compile(B4 + esc_re(phrase) + AF)


def has_word(text_lower, phrase):
    # the substring check is only a fast pre-filter: a whole-word hit is always a substring hit
    return phrase in text_lower and word_re(phrase).search(text_lower) is not None


def has_any_word(text_lower, lst):
    for p in lst:
        if has_word(text_lower, p):
            return p
    return None


_NT = [
    (re.compile(r"\r"), ""),
    (re.compile("[  \u0085]"), "\n"),
    (re.compile("[﻿\u001c-\u001f​]"), ""),
    (re.compile("[‘’‛′]"), "'"),
    (re.compile("[“”″]"), '"'),
    (re.compile("[–—−]"), "-"),
    (re.compile("[   \t]"), " "),
    (re.compile("[•●▪◦‣⁃·]"), "\n• "),
    (re.compile(" {2,}"), " "),
]


def norm_text(s):
    s = _s(s)
    for rx, rep in _NT:
        s = rx.sub(rep, s)
    return s


ISO_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]+))?)?)?\s*(Z|[+-][0-9]{2}:?[0-9]{2})?$")
_EPOCH = datetime(1970, 1, 1)


def parse_time(v):
    """ISO 8601 only; naive timestamps are UTC (same rule as the browser)."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        d = v - _EPOCH
        return d.days * DAY + d.seconds * 1000 + d.microseconds // 1000
    if isnum(v):
        return math.floor(v)
    if hasattr(v, "isoformat") and not isinstance(v, str):  # a date
        v = v.isoformat()
    m = ISO_RE.match(_s(v).strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4)) if m.group(4) else 0
    mi = int(m.group(5)) if m.group(5) else 0
    ss = int(m.group(6)) if m.group(6) else 0
    ms = int((m.group(7) + "00")[:3]) if m.group(7) else 0
    if mo < 1 or mo > 12 or d < 1 or d > 31 or hh > 23 or mi > 59 or ss > 60:
        return None
    # Date.UTC semantics: day overflow rolls into the next month
    try:
        base = datetime(y, mo, 1)
    except ValueError:
        return None
    delta = base - _EPOCH
    t = (delta.days + (d - 1)) * DAY + hh * 3600000 + mi * 60000 + ss * 1000 + ms
    tz = m.group(8)
    if tz and tz != "Z":
        sign = -1 if tz[0] == "-" else 1
        digits = tz[1:].replace(":", "")
        t -= sign * (int(digits[0:2]) * 60 + int(digits[2:4])) * 60000
    return t


# ------------------------------------------------------------ taxonomy index
TAX = {
    "skills": T.SKILLS, "roles": T.ROLES, "role_adj": T.ROLE_ADJ, "industries": T.INDUSTRIES, "metros": T.METROS,
    "us_states": T.US_STATES, "agency_names": T.AGENCY_NAMES, "agency_name_words": T.AGENCY_NAME_WORDS,
    "agency_phrases": T.AGENCY_PHRASES, "evergreen_phrases": T.EVERGREEN_PHRASES, "ats_domains": T.ATS_DOMAINS,
    "aggregator_domains": T.AGGREGATOR_DOMAINS, "vocab_common": T.VOCAB_COMMON,
}


def _len_alpha(a):
    return (-len(a), a)


class _Index:
    pass


_IDX = None


def idx():
    global _IDX
    if _IDX is not None:
        return _IDX
    I = _Index()
    I.skill, I.family, I.role, I.adj, I.ind, I.metro = {}, {}, {}, {}, {}, {}
    I.skill_i, I.role_i, I.ind_i = {}, {}, {}
    for i, s in enumerate(TAX["skills"]):
        I.skill[s["id"]] = s
        I.skill_i[s["id"]] = i
        if s.get("family"):
            I.family.setdefault(s["family"], []).append(s["id"])
    for i, r in enumerate(TAX["roles"]):
        I.role[r["id"]] = r
        I.role_i[r["id"]] = i
    for a, b, w in TAX["role_adj"]:
        I.adj[a + "|" + b] = w
        I.adj[b + "|" + a] = w
    for i, d in enumerate(TAX["industries"]):
        I.ind[d["id"]] = d
        I.ind_i[d["id"]] = i
    for m in TAX["metros"]:
        I.metro[m["id"]] = m
    alias_map, aliases = {}, []
    for s in TAX["skills"]:
        for a in s.get("aliases") or []:
            if a not in alias_map:
                alias_map[a] = s["id"]
                aliases.append(a)
    aliases.sort(key=_len_alpha)
    I.alias_map = alias_map
    I.alias_re = re.compile(B4 + "(" + "|".join(esc_re(a) for a in aliases) + ")" + AF)
    cs_map, cs_alt, cs = {}, {}, []
    # one spelling can carry two meanings ("DBT" the data tool, "DBT" the therapy): the context words decide
    for s in TAX["skills"]:
        for a in s.get("cs") or []:
            if a not in cs_map:
                cs_map[a] = s["id"]
                cs.append(a)
            elif cs_map[a] != s["id"]:
                cs_alt.setdefault(a, []).append(s["id"])
    cs.sort(key=_len_alpha)
    I.cs_map = cs_map
    I.cs_alt = cs_alt
    I.cs_re = re.compile(B4 + "(" + "|".join(esc_re(a) for a in cs) + ")" + AF)
    rmap, rpats = {}, []
    for r in TAX["roles"]:
        for p in r["patterns"]:
            if p not in rmap:
                rmap[p] = r["id"]
                rpats.append(p)
    rpats.sort(key=_len_alpha)
    I.role_map = rmap
    I.role_re = re.compile(B4 + "(" + "|".join(esc_re(p) for p in rpats) + ")" + AF)
    mmap, mal = {}, []
    for m in TAX["metros"]:
        for a in m["aliases"]:
            if a not in mmap:
                mmap[a] = m["id"]
                mal.append(a)
    mal.sort(key=_len_alpha)
    I.metro_map = mmap
    I.metro_re = re.compile(B4 + "(" + "|".join(esc_re(a) for a in mal) + ")" + AF)
    st_names = {}
    for k, v in TAX["us_states"].items():
        st_names[v] = k
    I.state_by_name = st_names
    snames = sorted(st_names.keys(), key=_len_alpha)
    I.state_name_re = re.compile(B4 + "(" + "|".join(esc_re(a) for a in snames) + ")" + AF)
    _IDX = I
    return I


# --------------------------------------------------------- text segmenting
H_PREF = re.compile(r"(nice to have|nice-to-have|preferred|bonus|pluses|plus points|a plus|desired|extra credit|good to have|would be great|ideally)")
H_REQ = re.compile(r"(requirement|qualification|must have|must-have|what you'll need|what you need|what we're looking for|what we are looking for|who you are|you have|you bring|about you|skills|experience|minimum|basic qualifications|required|you might be a fit|you're a fit|is this you)")
H_RESP = re.compile(r"(responsibilit|what you'll do|what you will do|the role|the job|day to day|day-to-day|your impact|in this role|duties|key tasks|you will|what you'll work on|the work)")
H_BEN = re.compile(r"(benefit|perks|compensation|salary|pay range|what we offer|why join|why you'll love|^why [a-z0-9&.' -]{2,40}$|equal employment|total rewards|equal opportunity|eeo|accommodation|our offer|pay transparency)")
H_ABOUT = re.compile(r"(about us|about the company|who we are|our mission|our story|company overview|about [a-z0-9&.' -]{2,40}$|the team|our team|life at)")
H_LOGI = re.compile(r"(location|schedule|hours|work model|work arrangement|where you'll work|where you will work)")
HEAD_LINE = re.compile(r"^(about (us|the (role|team|company|job|position|opportunity)|you|[a-z0-9&.' -]{2,40})|who we are|our (mission|story|team|values|culture|company)|the (role|team|opportunity|job|position)|company overview|role overview|position overview|overview|summary|job summary|position summary|job description|(key |primary |main |core )?(responsibilities|duties)( (&|and) (requirements|qualifications))?|what (you'll|you will) (do|be doing|work on|need)|what we're looking for|what we are looking for|what you (bring|need|have|'ll bring)|who you are|you (have|bring|are|might be a fit)|(minimum |basic |required |preferred |desired |additional |key )?(qualifications|requirements|skills|experience)( (&|and) (experience|skills|qualifications|requirements))?|(required|preferred|desired) skills( (&|and) experience)?|must[- ]haves?|nice[- ]to[- ]haves?|bonus( points)?|(preferred|required|desired|optional)|pluses|extra credit|(benefits|perks)( (&|and) (perks|benefits))?|compensation( (&|and) benefits)?|salary( range)?|pay( range| transparency)?|what we offer|why join( us)?|why you('ll| will) love [a-z0-9 ]+|total rewards|equal opportunity( employer)?|equal employment opportunity( employer| statement)?|eeo( statement)?|compensation (note|notes|details|information)|pay (note|details|information)|why [a-z0-9&.' -]{2,40}|location|work location|schedule|work model|work arrangement|our team|life at [a-z0-9&.' -]+|is this you\??|you might be a fit if)$")
CUE_PREF = re.compile(r"(a plus|nice to have|nice-to-have|is a bonus|a bonus|bonus points|preferred|preferably|ideally|plus if|is helpful|helpful but not required|not required|desirable|would be a plus|is a plus|are a plus|good to have|we'd love|we would love|(?<![a-z])optional(?![a-z]))")
CUE_REQ = re.compile(r"(required|must have|must be|you must|minimum of|at least|you'll need|you will need|requires|essential|mandatory|is a must|are a must)")
# A sentence carrying one of these is a requirement, never "about the company"
REQ_SIGNAL = re.compile(r"(required|must have|must be|you must|is a must|are a must|minimum of|at least|you'll need|you will need|requires|essential|mandatory|[0-9]+\s*\+?\s*((-|to)\s*[0-9]+\s*)?(years|yrs|year)\s+(of\s+)?([a-z/&-]+\s+){0,3}experience|sponsor|visa|citizen|clearance|authorized to work|eligible to work|work authorization)")
# The clause rules something OUT ("No Python needed", "does not require a clearance")
CUE_NEG = re.compile(r"((?<![a-z])(no|not|never|without)\s+(prior\s+|previous\s+|formal\s+|any\s+|professional\s+)?([a-z0-9+#./'& -]{1,40}?\s+)?(experience\s+|knowledge\s+|background\s+)?(is\s+|are\s+)?(needed|required|necessary|expected)(?![a-z])|(?<![a-z])(do|does|will)\s+not\s+(need|require)(?![a-z])|(?<![a-z])(don't|doesn't|won't)\s+(need|require)(?![a-z])|(?<![a-z])no need (to|for)(?![a-z])|(?<![a-z])not (a requirement|necessary|mandatory)(?![a-z])|(?<![a-z])we (do not|don't) use(?![a-z])|(?<![a-z])(will|does|do|can|may|shall|would)\s+not\s+(substitute|count|qualify|apply|be (considered|accepted|counted|substituted))(?![a-z])|(?<![a-z])(won't|doesn't|don't|can't|cannot)\s+(substitute|count|qualify|be (considered|accepted|counted|substituted))(?![a-z])|(?<![a-z])(is|are)\s+not\s+(accepted|considered|counted|a substitute|an acceptable substitute)(?![a-z])|(?<![a-z])not\s+(accepted|considered)\s+(in lieu|as a substitute)(?![a-z]))")
ROLE_MENTION = re.compile(r"(?<![a-z])(you|your|candidate|candidates|role|position|responsibilit[a-z]*|looking for|seeking|hiring|join us|join our|this job|the job)(?![a-z])")
COMPANY_OPEN = re.compile(r"^(we are|we're|founded|our mission|our team|at [a-z0-9&.' -]{2,40}, we|(?!(this|it|that|there|here|these|those|which) )[a-z0-9&.' -]{2,50} (is|are) (a|an|the|one of)(?![a-z]))")
COMPANY_VERB = re.compile(r"^([a-z&.'-]+\s+){0,2}(is|are|builds|makes|creates|provides|offers|develops|runs|operates|delivers|helps|powers|owns|designs|sells|connects|enables|serves|manages|was founded)(?![a-z])")
CLAUSE_ANCHOR = re.compile(r"([0-9]+\s*\+?\s*((-|to)\s*[0-9]+\s*)?(years|yrs|year)|degree|bachelor|master|required|must|license|licensure|certification|certified)")
LIST_CONJ = re.compile(r"(^|\s)(or|and|and/or|nor|&)(\s|$)|/")


def heading_section(h):
    t = re.sub(r"[:\s]+$", "", lc(h)).strip()
    if H_PREF.search(t):
        return "pref"
    if H_REQ.search(t):
        return "req"
    if H_RESP.search(t):
        return "resp"
    if H_BEN.search(t):
        return "benefits"
    if H_ABOUT.search(t):
        return "about"
    if H_LOGI.search(t):
        return "logistics"
    return None


def is_heading_line(h):
    t = re.sub(r"\s+", " ", re.sub(r"[:!.\s]+$", "", lc(h))).strip()
    return len(t) > 1 and HEAD_LINE.search(t) is not None


def _last_top_comma(p, end):
    """the last comma before `end` that is not inside parentheses: "(RMA, Omega) is a plus" keeps its list together"""
    depth, last = 0, -1
    for k in range(end):
        ch = p[k]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
        elif ch == "," and depth == 0:
            last = k
    return last


def split_clauses(s):
    """A "nice to have" at the end of a sentence covers only its own clause; a plain
    list that ends in "preferred" stays one clause."""
    parts = re.split(r";\s+", s)
    out = []
    for p in parts:
        # a negated parenthetical is its own clause: "corporate experience required (litigation experience will not substitute)"
        pn = re.search(r"\(([^()]{3,160})\)", p)
        if pn and CUE_NEG.search(lc(pn.group(1))) and len(p[:pn.start()].strip()) > 1:
            out.append(re.sub(r"\s+", " ", p[:pn.start()] + p[pn.end():]).strip())
            out.append(pn.group(1).strip())
            continue
        low = lc(p)
        cm = CUE_PREF.search(low)
        if cm and cm.start() > 0:
            ci = cm.start()
            op = p.rfind("(", 0, ci)
            if op > 0:
                close = p.find(")", op)
                # "(Python preferred)" is its own clause; "Python (preferred)" is not
                if (close == -1 or close > ci) and len(p[:op].strip()) > 1 and len(p[op + 1:ci].strip()) > 0:
                    out.append(p[:op].strip())
                    out.append(p[op + 1:].strip())
                    continue
            last_comma = _last_top_comma(p, ci)
            if last_comma > 0:
                left, right = p[:last_comma], p[last_comma + 1:]
                right_head = lc(p[last_comma + 1:ci])
                listy = all(len(re.split(r"\s+", it.strip())) <= 3 for it in p.split(","))
                if CLAUSE_ANCHOR.search(lc(left)) or (not listy and not LIST_CONJ.search(right_head)):
                    out.append(left.strip())
                    out.append(right.strip())
                    continue
        out.append(p.strip())
    return [x for x in out if len(x) > 0]


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"])")
_INLINE_HEAD = re.compile(r"^([A-Za-z' &/-]{3,40}):\s+(\S[\s\S]*)$")
# what the employer offers toward a credential ("we pay for the CPA review course") is a benefit, not a bar
SUPPORT_CUE = re.compile(r"(?<![a-z])((we|we'll|we will|the company will|our team will)\s+(actively\s+|fully\s+)?(support|supports|pay for|pays for|cover|covers|reimburse|reimburses|sponsor|sponsors|encourage|encourages|fund|funds)\s+([a-z0-9'&+-]+\s+){0,5}?(licensure|license|licenses|certification|certifications|exams?|review courses?|study|tuition|credentials?|candidates)|paid study (leave|time)|exam fees|licensure support|support (for|toward|towards) (your )?(licensure|certification|license))(?![a-z])")


# never split after "St." / "Dr." / "e.g." ("St. Louis", "Scott AFB near St. Louis")
_ABBR_END = re.compile(r"(?<![A-Za-z])(St|Mt|Ft|Dr|Mr|Mrs|Ms|Jr|Sr|vs|Ave|Blvd|Rd|Dept|approx|e\.g|i\.e|Lt|Col|Sgt|Capt|Gen|Gov)\.\Z")


def _sent_pieces(line):
    out = []
    for p in _SENT_SPLIT.split(line):
        if out and _ABBR_END.search(out[-1]):
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def segments(desc, org=""):
    text = norm_text(desc)
    lines = re.split(r"\n+", text)
    out, section = [], "none"
    org_name = norm_org(org or "")
    org_first = org_name.split(" ")[0] if org_name else ""
    if _js_len(org_first) < 5:
        org_first = ""
    for raw_line in lines:
        line = re.sub(r"^\(?[0-9]{1,2}[.)]\s+", "", re.sub(r"^[\s•*\->]+", "", raw_line)).strip()
        if not line:
            continue
        words = len(re.split(r"\s+", line))
        colon = line.find(":")
        line_sec = None
        if 0 < colon and _js_len(line[:colon]) < 70 and is_heading_line(line[:colon]):
            head, rest = line[:colon], line[colon + 1:].strip()
            hs = heading_section(head)
            if hs:
                if _js_len(rest) < 2:
                    section = hs
                    continue
                # "About Acme: we build payroll software." covers this line only
                if hs == "about":
                    line_sec = "about"
                else:
                    section = hs
                line = rest
        elif words <= 8 and is_heading_line(line):
            hs2 = heading_section(line)
            if hs2:
                section = hs2
                continue
        for sent in _sent_pieces(line):
            sent = sent.strip()
            if not sent:
                continue
            hm = _INLINE_HEAD.match(sent)
            sent_sec = line_sec
            if hm and is_heading_line(hm.group(1)):
                hs3 = heading_section(hm.group(1))
                if hs3:
                    if hs3 == "about":
                        sent_sec = "about"
                    else:
                        section = hs3
                    sent = hm.group(2)
            for s in split_clauses(sent):
                low = lc(s)
                cue = "pref" if CUE_PREF.search(low) else ("neg" if CUE_NEG.search(low) else ("req" if CUE_REQ.search(low) else None))
                sec = sent_sec or section
                if cue != "req" and SUPPORT_CUE.search(low):
                    sec = "benefits"
                if sec == "none" and not ROLE_MENTION.search(low):
                    if org_name and low.startswith(org_name):
                        pre = org_name
                    elif org_first and low.startswith(org_first):
                        pre = org_first
                    else:
                        pre = ""
                    starts_org = bool(pre) and COMPANY_VERB.search(re.sub(r"^[\s.,&'-]+", "", low[len(pre):])) is not None
                    if COMPANY_OPEN.search(low) or starts_org:
                        sec = "about"
                if sec == "about" and (REQ_SIGNAL.search(low) or CUE_PREF.search(low)):
                    sec = "none"
                out.append({"text": s, "low": low, "section": sec, "cue": cue})
    return out


def seg_importance(seg):
    if seg["section"] in ("about", "benefits", "logistics"):
        return None
    if seg["cue"] == "neg":
        return None
    if seg["cue"] == "pref":
        return "pref"
    if seg["cue"] == "req":
        return "req!"
    if seg["section"] == "pref":
        return "pref"
    if seg["section"] == "req":
        return "req!"
    return "req"


# ------------------------------------------------------------ skill finding
@functools.lru_cache(maxsize=512)
def _pre_re(word):
    return re.compile(r"(?<![a-z0-9])" + esc_re(word) + r"\s*[,/]?\s*$")


@functools.lru_cache(maxsize=512)
def _neg_re(word):
    return re.compile(r"^[\s-]+" + esc_re(word) + r"(?![a-z0-9])")


def _inside_not(low, hit, nots):
    """A hit inside one of the skill's "not" phrases is a different thing
    ("prospective audit and feedback" is antimicrobial stewardship, not an audit)."""
    if not nots:
        return False
    for p in nots:
        k = low.find(p, max(0, hit["end"] - len(p)))
        while k != -1 and k <= hit["at"]:
            if k + len(p) >= hit["end"]:
                return True
            k = low.find(p, k + 1)
    return False


BAR_RE = re.compile(r"(?<![a-z])(admission to|admitted to|admitted in|member of|membership in|good standing (?:with|of|in)|licensed in)( the)? (state of )?[a-z][a-z.]*( [a-z][a-z.]*){0,2} bar(?![a-z])")


# a shared word in a pair: "vendor and SOW management" names vendor management, "accounts payable and
# receivable" names accounts receivable, "unit and integration testing" names unit testing
COORD_TOK = re.compile(r"[a-z0-9][a-z0-9+#-]*|&|/")
COORD_CONJ = ("and", "or", "&", "/")
_COORD_ANY = re.compile(r"\s(and|or)\s|&|/")
_BLANK = re.compile(r"\s*\Z")


def _coord_hits(low, hits):
    if not _COORD_ANY.search(low):
        return
    I = idx()
    t = [(m.group(0), m.start(), m.end()) for m in COORD_TOK.finditer(low)]

    def tight(a, b):
        return _BLANK.match(low[t[a][2]:t[b][1]]) is not None
    i = 0
    while i + 3 < len(t):
        if tight(i, i + 1) and tight(i + 1, i + 2) and tight(i + 2, i + 3):
            w0, w1, w2, w3 = t[i][0], t[i + 1][0], t[i + 2][0], t[i + 3][0]
            cand = None
            if w1 in COORD_CONJ and w0 not in COORD_CONJ and w2 not in COORD_CONJ and w3 not in COORD_CONJ:
                cand = w0 + " " + w3          # right-shared: A and B C -> A C
            elif w2 in COORD_CONJ and w0 not in COORD_CONJ and w1 not in COORD_CONJ and w3 not in COORD_CONJ:
                cand = w0 + " " + w3          # left-shared: A B and C -> A C
            if cand is not None:
                sid = I.alias_map.get(cand)
                if sid:
                    hit = {"id": sid, "at": t[i][1], "end": t[i + 3][2]}
                    if not _inside_not(low, hit, I.skill[sid].get("not")):
                        hits.append(hit)
        i += 1


def find_skills(original):
    I = idx()
    original = _s(original)
    low = lc(original)
    hits = []
    for m in I.alias_re.finditer(low):
        hit = {"id": I.alias_map[m.group(1)], "at": m.start(), "end": m.start() + len(m.group(1))}
        if not _inside_not(low, hit, I.skill[hit["id"]].get("not")):
            hits.append(hit)
    # "admission to the Illinois bar", "member in good standing of the New York State bar"
    for m in BAR_RE.finditer(low):
        if "bar_admission" in I.skill:
            hits.append({"id": "bar_admission", "at": m.start(), "end": m.end()})
    _coord_hits(low, hits)
    for m in I.cs_re.finditer(original):
        for sid in [I.cs_map[m.group(1)]] + I.cs_alt.get(m.group(1), []):
            sk = I.skill[sid]
            ctx = sk.get("ctx") or []
            if ctx:
                ok = any(has_word(low, c) for c in ctx)
                pre = sk.get("pre") or []
                if not ok and pre:
                    before = _u16_before(low, m.start(), 25)
                    ok = any(_pre_re(p).search(before) for p in pre)
                if not ok:
                    continue
            neg = sk.get("neg") or []
            if neg:
                after = low[m.start() + len(m.group(1)):]
                if any(_neg_re(n).search(after) for n in neg):
                    continue
            hits.append({"id": sid, "at": m.start(), "end": m.start() + len(m.group(1))})
            break
    hits.sort(key=lambda h: (h["at"], h["id"]))
    return hits


# --------------------------------------------------------- listing normalize
_JS_WS = "\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_JS_DEC = re.compile(r"[+-]?(Infinity|([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?)")
_JS_RADIX = {"x": (16, re.compile(r"[0-9a-fA-F]+")), "o": (8, re.compile(r"[0-7]+")), "b": (2, re.compile(r"[01]+"))}


def _js_number(v):
    """Number(v) as JavaScript computes it, for the shapes a listing can carry
    ("85_000" and full-width digits are NaN there, "0x14C08" is 85000, [85000] is 85000)."""
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return float("nan")
    t = _js_string(v).strip(_JS_WS)
    if t == "":
        return 0.0
    if len(t) > 2 and t[0] == "0" and t[1].lower() in _JS_RADIX:
        base, rx = _JS_RADIX[t[1].lower()]
        return float(int(t[2:], base)) if rx.fullmatch(t[2:]) else float("nan")
    if _JS_DEC.fullmatch(t):
        return float(t)
    return float("nan")


def _to_num(v):
    if v is None or v == "" or isinstance(v, bool):
        return None
    n = _js_number(v)
    if not math.isfinite(n) or n <= 0:
        return None
    return int(n) if n.is_integer() else n


def _to_count(v, dflt):
    if v is None or v == "" or isinstance(v, bool):
        return dflt
    n = _js_number(v)
    if not math.isfinite(n) or n < 0:
        return dflt
    return int(math.floor(n)) if n < 1e21 else n


def _pick(l, a, b):
    v = l.get(a)
    return v if v is not None else l.get(b)


def norm_period(p):
    t = lc(p).strip()
    if not t:
        return None
    if re.match(r"^(hour|hourly|hr|per hour|an hour)$", t):
        return "hour"
    if re.match(r"^(year|yearly|annual|annually|annum|per year|yr|a year)$", t):
        return "year"
    if re.match(r"^(month|monthly|per month|mo)$", t):
        return "month"
    if re.match(r"^(week|weekly|per week|wk)$", t):
        return "week"
    if re.match(r"^(day|daily|per day)$", t):
        return "day"
    return "unknown"


def normalize_listing(l):
    l = l if isinstance(l, dict) else {}
    smin = _to_num(_pick(l, "salary_min", "salaryMin"))
    smax = _to_num(_pick(l, "salary_max", "salaryMax"))
    period = norm_period(l.get("salary_period") or l.get("salaryPeriod") or None)
    if smin is not None or smax is not None:
        ref = smax if smax is not None else smin
        if period == "unknown":
            period = "year" if ref >= 1000 else None
        elif not period:
            # no unit: big numbers are annual, an intern's "25" is hourly, anything
            # else under 1,000 could be hourly or thousands - we don't guess
            is_intern = lc(l.get("type")) == "internship" or re.search(r"(?<![a-z0-9_])intern", lc(l.get("title"))) is not None
            period = "year" if ref >= 1000 else ("hour" if (is_intern and ref < 100) else None)
        if not period:
            smin, smax = None, None
    pred = _pick(l, "salary_is_predicted", "salaryIsPredicted")
    tags = [_s(t) for t in l["tags"]] if isinstance(l.get("tags"), list) else []
    first = l.get("first_seen_at")
    if first is None:
        first = l.get("firstSeenAt")
    if first is None:
        first = l.get("fetched_at")
    if first is None:
        first = l.get("fetchedAt")
    return {
        "id": _s(l.get("id")),
        "title": _s(l.get("title")).strip(),
        "org": _s(l.get("org") or l.get("company")).strip(),
        "type": lc(l.get("type")) or "job",
        "location": _s(_pick(l, "location", "loc")).strip(),
        "description": _s(l.get("description")),
        "tags": tags,
        "salaryMin": smin, "salaryMax": smax, "salaryPeriod": period,
        "salaryPredicted": None if pred is None else bool(pred),
        "deadline": l.get("deadline") or None,
        "postedAt": parse_time(_pick(l, "posted_at", "postedAt")),
        "firstSeenAt": parse_time(first),
        "lastSeenAt": parse_time(_pick(l, "last_seen_at", "lastSeenAt")),
        "seenCount": _to_count(_pick(l, "seen_count", "seenCount"), None),
        "repostCount": _to_count(_pick(l, "repost_count", "repostCount"), 0),
        "employmentType": lc(l.get("employment_type") or l.get("employmentType")) or None,
        "contractType": lc(l.get("contract_type") or l.get("contractType")) or None,
        "applyUrl": _s(l.get("apply_url") or l.get("applyUrl")),
        "source": _s(l.get("source")),
    }


# ------------------------------------------------------------------ parsers
WORDNUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15}
WORDNUM_PAREN = re.compile(r"(?<![a-z])(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen)\s*\(([0-9]{1,2})\)")
WORDNUM_RE = re.compile(r"(?<![a-z])(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen)(?![a-z])(?=[^.]{0,16}(?<![a-z])(years|yrs|year)(?![a-z]))")
YRS_RE = re.compile(r"(?:(minimum|at least|min\.)\s*(?:of\s*)?)?([0-9]{1,2})(?:\s*(?:-|to)\s*([0-9]{1,2}))?\s*(\+|plus|or more)?\s*(years|yrs|year|yr)(?![a-z])")
YRS_TAIL_SKIP = re.compile(r"^\s*(old|of age|or older|or over|and older|and over|degree|college|program|ago|in a row|running|warranty|term|of service|of school|of high school|of university|of undergraduate|of coursework|of study|of college|cliff|vesting|with a one-year cliff)")
YRS_HEAD_SKIP = re.compile(r"((within|over the (past|last)|for over|for more than|for nearly|for almost|in the last|in the past|founded|established|nearly|almost|up to|no more than|not more than|less than|fewer than|under|at most|maximum of|max\.?|a maximum of|vests? over|vesting over|paid out over|spread over|every|each|first|initial|in your|within your|for the next|for the first|tenure is|tenure of|average tenure|averaging|in business for|operating for|been around for|serving for|for the past|for the last)\s*$)|([0-9]\s*-\s*$)")
YRS_EXP = re.compile(r"(experience|exp(?![a-z])|professional|industry|hands-on|track record|background|working|work in|work with|in a similar|in an? [a-z]+ (role|position|environment|setting)|building|managing|leading|developing|using|supporting|with |as an? |of [a-z][a-z-]* |in [a-z]+)")


def _js_regex_exec_all(rx, text):
    """JS while(rx.exec) loop over a global regex == finditer, except JS steps
    past empty matches the same way; our patterns never match empty."""
    return rx.finditer(text)


# "10+ years (8+ with a Master's)": a shorter bar for people with a degree
YRS_DEG_ALT = re.compile(r"(?<![0-9])([0-9]{1,2})\s*\+?\s*(?:years?|yrs?)?\s*(?:of\s+[a-z-]+\s+)?(?:experience\s+)?(?:with|w/|given|if you have|for candidates with|for those with)\s+(?:a\s+|an\s+)?(?:relevant\s+)?(master'?s|masters|m\.s\.|mba|ph\.?d\.?|doctorate|graduate degree|advanced degree|bachelor'?s|bachelors|b\.s\.|b\.a\.)(?![a-z])")


def deg_level(w):
    return 4 if re.match(r"(ph|doctorate)", w) else (3 if re.match(r"(master|m\.s|mba|graduate|advanced)", w) else 2)


def parse_years(segs):
    best, best_t = None, ""
    for seg in segs:
        if seg["section"] in ("about", "benefits") or seg["cue"] == "neg":
            continue
        seg_txt = None
        imp = seg_importance(seg)
        t = WORDNUM_PAREN.sub(lambda m: m.group(2), seg["low"])
        t = WORDNUM_RE.sub(lambda m: str(WORDNUM[m.group(1)]), t)
        for m in YRS_RE.finditer(t):
            n1 = int(m.group(2))
            n2 = int(m.group(3)) if m.group(3) is not None else None
            unit = m.group(5)
            end = m.end()
            tail = _u16_after(t, end, 60)
            head = _u16_before(t, m.start(), 25)
            if YRS_TAIL_SKIP.search(tail):
                continue
            if YRS_HEAD_SKIP.search(head):
                continue
            if re.search(r"^\s*-\s*(year|yr)", t[m.start() + len(str(n1)):]):
                continue
            if unit in ("year", "yr") and n1 > 1 and not re.search(r"^\s*(of\s+)?([a-z-]+\s+){0,3}experience", tail):
                continue
            strong = unit in ("years", "yrs") and (m.group(4) is not None or n2 is not None or m.group(1) is not None)
            if not strong and not YRS_EXP.search(tail) and "experience" not in seg["low"]:
                continue
            if n1 > 20 or (n2 is not None and (n2 > 25 or n2 < n1)):
                continue
            if seg_txt is None:
                seg_txt = trunc(seg["text"], 140)
            cand = {"min": n1, "max": n2, "text": seg_txt, "pref": imp == "pref"}
            if best is None or (cand["min"] > best["min"] if cand["pref"] == best["pref"] else not cand["pref"]):
                best, best_t = cand, t
    if best:
        am = YRS_DEG_ALT.search(best_t)
        if am and int(am.group(1)) < best["min"]:
            best["alt"] = {"min": int(am.group(1)), "edu": deg_level(am.group(2))}
    return best


LV_INTERN = re.compile(r"(?<![a-z])(intern|internship|co-op|coop|summer analyst|summer associate|apprenticeship)(?![a-z])")
LV_EXEC = re.compile(r"(?<![a-z])(vp|vice president|chief|cxo|ceo|cto|cfo|coo|cmo|svp|evp|president)(?![a-z])")
LV_DIR = re.compile(r"(?<![a-z])(director|head of)(?![a-z])")
LV_LEAD = re.compile(r"(?<![a-z])(staff (software |data |machine learning |ml |product |research |security |site reliability |frontend |front-end |backend |back-end |full[- ]stack |platform |infrastructure |applied |ux |mobile )(engineer|scientist|designer|developer|architect)|staff (designer|developer|architect)|principal|(?<!asbestos and )(?<!asbestos & )(?<!asbestos, )lead(?!\s*(gen|generation))(?![- ](based|abatement|paint|poisoning|inspector|inspection|hazard|safe|pipe|pipes|service line|exposure|testing|risk|and copper|and asbestos|& asbestos))|distinguished|architect)(?![a-z])")
# outside tech a "lead" is one step above staff (a lead RT, a lead teacher), not a staff/principal engineer
LV_LEAD_STRONG = re.compile(r"(?<![a-z])(staff (software |data |machine learning |ml |product |research |security |site reliability |frontend |front-end |backend |back-end |full[- ]stack |platform |infrastructure |applied |ux |mobile )(engineer|scientist|designer|developer|architect)|staff (designer|developer|architect)|principal|distinguished|architect)(?![a-z])")
LV_TECH = re.compile(r"(?<![a-z])(engineer|engineering|developer|software|data|scientist|designer|design|product|platform|infrastructure|security|devops|sre|qa|ux|ui|analytics|machine learning|ml|ai|technical|tech)(?![a-z])")
LV_MGR = re.compile(r"((?<![a-z])(engineering|people|team|general|district|regional|design|data science|analytics)\s+manager(?![a-z]))|^(senior\s+)?manager(,|\s+of|\s*$)|(?<![a-z])manager of(?![a-z])")
LV_SENIOR = re.compile(r"(?<![a-z])(senior|sr\.?|iii|level 3|l3)(?![a-z])")
LV_MID = re.compile(r"(?<![a-z])(ii|mid-level|mid level|intermediate|level 2)(?![a-z])")
LV_ENTRY = re.compile(r"(?<![a-z])(junior|jr\.?|entry-level|entry level|new grad|new graduate|graduate|early career|early-career|associate|apprentice|trainee|i)(?![a-z])")


LV_ASSIST = re.compile(r"(?<![a-z])(executive assistant|assistant to|administrative assistant|personal assistant|office assistant|business partner to|executive business partner|administrative business partner)(?![a-z])")
# who a role supports ("to the CEO", "Office of the President") is not the role's own level
LV_SUPPORTS = re.compile(r"(?<![a-z])(to the|office of the)\s+(ceo|cfo|coo|cto|cmo|president|founders?|chief [a-z]+ officer)(?![a-z])")
LV_FRONTLINE = re.compile(r"(?<![a-z])((shift|crew|floor|line|cashier|store|retail|warehouse|kitchen|front desk|sales floor) (lead|leader|supervisor)|lead (cashier|server|host|hostess|teller|associate|barista|cook|clerk|bartender))(?![a-z])")
LV_ASSOC_SENIOR = re.compile(r"(?<![a-z])associate (general counsel|professor|dean|partner|principal)(?![a-z])")


LV_LADDER = re.compile(r"(?<![a-z])(sdr|bdr|sales development (rep|representative)|business development (rep|representative)|customer service (rep|representative|agent)|call center (rep|representative|agent))(?![a-z])")


def title_level(title):
    """Titles whose level words mislead are read first: "Executive Assistant to the CEO" is
    not an executive, "Shift Lead" is not Lead/Staff, "Associate Professor" is not entry."""
    t = lc(title)
    if not t:
        return None
    if LV_INTERN.search(t):
        return 0
    # an entry ladder's own seniority ("Senior SDR") stays in the early-career band
    if LV_LADDER.search(t) and not LV_MGR.search(t) and not LV_DIR.search(t) and not LV_EXEC.search(t) and not re.search(r"(?<![a-z])manager(?![a-z])", t):
        return 2 if (LV_SENIOR.search(t) or LV_LEAD.search(t)) else 1.5
    if re.search(r"(?<![a-z])chief of staff(?![a-z])", t):
        return 4
    if LV_ASSIST.search(t):
        return 3 if LV_SENIOR.search(t) else (2 if re.search(r"(?<![a-z])(executive assistant|executive business partner|business partner to)(?![a-z])", t) else 1)
    t = LV_SUPPORTS.sub(" ", t)
    if re.search(r"(?<![a-z])(associate vice president|avp)(?![a-z])", t):
        return 5
    if re.search(r"(?<![a-z])associate director(?![a-z])", t):
        return 4
    if LV_ASSOC_SENIOR.search(t):
        return 3
    if LV_FRONTLINE.search(t):
        return 1.5
    if LV_EXEC.search(t):
        return 6
    if LV_DIR.search(t):
        return 5
    if LV_LEAD.search(t):
        return 3 if (not LV_LEAD_STRONG.search(t) and not LV_TECH.search(t)) else 4
    if LV_MGR.search(t):
        return 4
    if LV_SENIOR.search(t):
        return 3
    if LV_MID.search(t):
        return 2
    if LV_ENTRY.search(t):
        return 1
    return None


def level_from_years(y):
    if y is None:
        return None
    if y < 1:
        return 1
    if y < 3:
        return 1.5
    if y < 5:
        return 2
    if y < 8:
        return 3
    return 4  # years alone never make you a director - that's a title, not a tenure


LEVEL_LABELS = [(0, "Internship"), (1, "Entry level"), (1.5, "Early career"), (2, "Mid level"), (3, "Senior"), (4, "Lead / Staff"), (5, "Director"), (6, "Executive")]


def level_label(l):
    if l is None:
        return "Not stated"
    best = LEVEL_LABELS[0]
    for item in LEVEL_LABELS:
        if l >= item[0]:
            best = item
    return best[1]


def level_bucket(l):
    if l is None:
        return None
    if l < 0.5:
        return "intern"
    if l < 1.75:
        return "entry"
    if l < 2.5:
        return "mid"
    if l < 3.5:
        return "senior"
    if l < 4.5:
        return "lead"
    if l < 5.5:
        return "director"
    return "exec"


EDU = [
    (4, re.compile(r"(?<![a-z])(ph\.?d|doctorate|doctoral|doctor of)(?![a-z])")),
    (3, re.compile(r"(?<![a-z])(?<!scrum )(master's|masters (degree|in|of|program)|master of|ms degree|ms in|m\.s\.|mba|graduate degree|advanced degree|m\.a\.|mph|msc|m\.sc|msn|msw|mfa|m\.f\.a\.|meng|m\.eng|m\.ed\.)(?![a-z])")),
    (2, re.compile(r"(?<![a-z])(bachelor's|bachelors|bachelor of|ba/bs|bs/ba|b\.s\.|b\.a\.|bs degree|ba degree|bs in|ba in|undergraduate degree|bsn|bsc|b\.sc|bfa|b\.f\.a\.|bba|beng|b\.eng)(?![a-z])")),
    (1, re.compile(r"(?<![a-z])(associate's degree|associate degree|associates degree|2-year degree|two-year degree)(?![a-z])")),
    (0, re.compile(r"(?<![a-z])(high school diploma|ged|high school or equivalent|high school degree)(?![a-z])")),
]
EDU_GENERIC = re.compile(r"(?<![a-z])(4-year degree|four-year degree|college degree|university degree|degree in)(?![a-z])")
EDU_EQUIV = re.compile(r"(or equivalent|equivalent (practical |work |professional |combination of education and )?experience|or relevant experience|in lieu of a degree|degree not required|no degree required)")


def parse_education(segs):
    req, equiv, text = None, False, ""
    for seg in segs:
        imp = seg_importance(seg)
        if not imp:
            continue
        if EDU_EQUIV.search(seg["low"]):
            equiv = True
        if imp == "pref":
            continue
        lvls = [lv for lv, rx in EDU if rx.search(seg["low"])]
        if not lvls and EDU_GENERIC.search(seg["low"]):
            lvls = [2]
        if not lvls:
            continue
        mn = min(lvls)
        if req is None or mn > req:
            req = mn
            text = trunc(seg["text"], 140)
    return {"level": req, "equivalentOk": equiv, "text": text}


MODE_REMOTE_LOC = re.compile(r"(?<![a-z])(remote|work from home|wfh|anywhere)(?![a-z])")
MODE_HYBRID_LOC = re.compile(r"(?<![a-z])hybrid(?![a-z])")
MODE_ONSITE_LOC = re.compile(r"(?<![a-z])(on-site|onsite|in-office|in office|in-person|in person)(?![a-z])")
MODE_HYBRID_DESC = re.compile(r"((?<![a-z])hybrid(?![a-z])|(?<![0-9])[1-4]\s*days?\s*(a|per)\s*week\s*(in|at)\s*(the\s*|our\s*)?office|(?<![a-z])in[- ]office\s*[1-4]\s*days|(?<![0-9])[1-4]\s*days?\s*(in[- ]office|on-?site))")
MODE_REMOTE_DESC = re.compile(r"((?<![a-z])(fully remote|100% remote|remote-first|remote first|work from home|work from anywhere|remote position|remote role|this role is remote|this is a remote|remote within|remote in the|remote-friendly|remote opportunity|remote job|work remotely|working remotely|distributed team|distributed company)(?![a-z]))")
MODE_ONSITE_DESC = re.compile(r"((?<![a-z])(on-?site|in-person|in person|office-based|report to (our|the) office|this role is based in|must be able to commute|relocation required|must relocate|work in our office|in the office (five|5) days|5 days a week in (the|our) office|office (five|5) days (a|per) week|(five|5) days (a|per) week (on-?site|in-?office|in the office|in our office)|fully in-office|fully onsite)(?![a-z]))")
REGION_RE = re.compile(r"remote\s*[-(,:]?\s*(\(?\s*)(us|usa|u\.s\.|united states|us only|canada|uk|emea|europe|eu|latam|apac|india)(?![a-z])|(us|u\.s\.)[- ]based remote|remote within the (us|united states|u\.s\.)|must (be located|reside|live) in the (us|united states|u\.s\.)|(open to|available to) (candidates|applicants) (in|located in) the (us|united states)")


def region_code(s):
    s = lc(s)
    if re.search(r"(us|usa|u\.s\.|united states)", s):
        return "US"
    if "canada" in s:
        return "CA"
    if "uk" in s:
        return "UK"
    if re.search(r"(emea|europe|eu)", s):
        return "EU"
    if "latam" in s:
        return "LATAM"
    if "apac" in s:
        return "APAC"
    if "india" in s:
        return "IN"
    return None


_PLACE_SPLIT = re.compile(r";|\||\s+or\s+|\s+and\s+|\s*/\s*")
_CITY_ST = re.compile(r"^([a-z .'-]+?),\s*([a-z]{2})(?:\s*,\s*(us|usa|united states))?$")


def parse_places(loc_raw):
    I = idx()
    s = lc(loc_raw)
    places = []
    def clean(x):
        x = MODE_REMOTE_LOC.sub(" ", x, count=1)
        x = MODE_HYBRID_LOC.sub(" ", x, count=1)
        x = MODE_ONSITE_LOC.sub(" ", x, count=1)
        x = re.sub(r"[()\[\]]", " ", x)
        x = re.sub(r"(?<![0-9])[0-9]{5}(?:-[0-9]{4})?(?![0-9])", " ", x)
        x = re.sub(r"\s+", " ", x).strip()
        return re.sub(r"^[-,:\s]+|[-,:\s]+$", "", x)
    for raw in _PLACE_SPLIT.split(s):
        # "Covington, KY (Cincinnati metro)", "Mason, OH 45040": the city and state, without the note or the ZIP
        part, bare = clean(raw), clean(re.sub(r"\([^()]*\)|\[[^\[\]]*\]", " ", raw))
        if not part:
            continue
        bm = _CITY_ST.match(bare) if bare else None
        cm = bm or _CITY_ST.match(part)
        if bm:
            part = bare
        if cm:
            city, st = cm.group(1).strip(), cm.group(2).upper()
            mid = I.metro_map.get(city + ", " + cm.group(2)) or None
            if mid and st not in I.metro[mid]["states"]:
                mid = None
            if not mid:
                mid = I.metro_map.get(city) or None
            if mid and st not in I.metro[mid]["states"]:
                mid = None
            places.append({"metro": mid, "state": st if st in TAX["us_states"] else None, "label": part})
            continue
        m = I.metro_re.search(part)
        if m:
            found = I.metro_map[m.group(1)]
            places.append({"metro": found, "state": I.metro[found]["states"][0], "label": part})
            continue
        sm = I.state_name_re.search(part)
        if sm:
            places.append({"metro": None, "state": I.state_by_name[sm.group(1)], "label": part})
            continue
        code = re.search(r"(?<![a-z])([a-z]{2})$", part)
        if code and code.group(1).upper() in TAX["us_states"] and _js_len(part) <= 3:
            places.append({"metro": None, "state": code.group(1).upper(), "label": part})
            continue
        if re.match(r"^(us|usa|united states|u\.s\.|nationwide|national|multiple locations|various|online)$", part):
            continue
        places.append({"metro": None, "state": None, "label": part})
    return places


def parse_mode(loc_raw, segs):
    loc = lc(loc_raw)
    mode = src = region = None
    desc_all = " \n ".join(g["low"] for g in segs)
    lr, lh, lo = bool(MODE_REMOTE_LOC.search(loc)), bool(MODE_HYBRID_LOC.search(loc)), bool(MODE_ONSITE_LOC.search(loc))
    dh, dr, do = bool(MODE_HYBRID_DESC.search(desc_all)), bool(MODE_REMOTE_DESC.search(desc_all)), bool(MODE_ONSITE_DESC.search(desc_all))
    if lh:
        mode, src = "hybrid", "location"
    elif lr:
        mode, src = ("hybrid", "description") if dh else ("remote", "location")
    elif lo:
        mode, src = ("hybrid", "description") if dh else ("onsite", "location")
    elif dh:
        mode, src = "hybrid", "description"
    elif dr:
        mode, src = "remote", "description"
    elif do:
        mode, src = "onsite", "description"
    rm = REGION_RE.search(loc + " \n " + desc_all)
    if rm and (mode == "remote" or mode is None):
        region = region_code(rm.group(0))
    return {"mode": mode, "source": src, "region": region}


ET_TITLE = [
    ("internship", re.compile(r"(?<![a-z])(intern|internship|co-op|coop)(?![a-z])")),
    ("contract", re.compile(r"(?<![a-z])(contract|contractor|freelance|1099|c2c|contract-to-hire)(?![a-z])")),
    ("temporary", re.compile(r"(?<![a-z])(temp|temporary|seasonal)(?![a-z])")),
    ("part_time", re.compile(r"(?<![a-z])part[- ]time(?![a-z])")),
]
ET_DESC_CONTRACT = re.compile(r"(?<![a-z])([0-9]{1,2}[- ]month contract|contract role|contract position|contract-to-hire|contract to hire|w2 contract|1099|c2c|corp to corp|fixed[- ]term|contract assignment|temp-to-hire|temp to hire|duration of the contract)(?![a-z])")
ET_DESC_PART = re.compile(r"(?<![a-z])(part[- ]time)(?![a-z])")
ET_DESC_FULL = re.compile(r"(?<![a-z])(full[- ]time)(?![a-z])")
ET_DESC_TEMP = re.compile(r"(?<![a-z])(temporary position|temporary role|seasonal position|seasonal role)(?![a-z])")


def parse_employment_type(n, segs):
    f = n["employmentType"]
    if f in ("full_time", "part_time", "contract", "internship", "temporary"):
        if f == "full_time" and n["contractType"] == "contract":
            return {"type": "contract", "source": "listing"}
        return {"type": f, "source": "listing"}
    if n["contractType"] == "contract":
        return {"type": "contract", "source": "listing"}
    t = lc(n["title"])
    for name, rx in ET_TITLE:
        if rx.search(t):
            return {"type": name, "source": "title"}
    if n["type"] == "internship":
        return {"type": "internship", "source": "listing"}
    d = " \n ".join(g["low"] for g in segs if g["section"] != "about")
    if ET_DESC_CONTRACT.search(d):
        return {"type": "contract", "source": "description"}
    if ET_DESC_TEMP.search(d):
        return {"type": "temporary", "source": "description"}
    if ET_DESC_PART.search(d) and not ET_DESC_FULL.search(d):
        return {"type": "part_time", "source": "description"}
    if ET_DESC_FULL.search(d):
        return {"type": "full_time", "source": "description"}
    if n["contractType"] == "permanent":
        return {"type": "full_time", "source": "listing"}
    return {"type": None, "source": None}


AUTH_NOSPON = re.compile(r"((not|unable to|cannot|can't|won't|will not|do not|does not|don't|doesn't|are unable to|is unable to|no longer)\s+(currently\s+)?(be\s+)?(able to\s+)?(offer|provide|support|sponsor|consider|accommodate)(ing)?\s+(any\s+)?(employment\s+|immigration\s+)?(visa\s+|h-?1b\s+|work\s+)?(sponsor|sponsorship|visa)|sponsorship (is )?not (available|offered|provided|possible)|no (visa |h-?1b |immigration |employment )?sponsorship|without (the need for |requiring |needing )?(current or future |now or in the future |present or future )?(employer |visa |company |employment |immigration )?sponsorship|not eligible for (visa |immigration |employment |h-?1b )?sponsorship|sponsorship will not be|(does not|will not|cannot|can't|won't|unable to|not able to|do not|don't) sponsor(?![a-z])|now or in the future require sponsorship|not open to (visa |h-?1b |immigration )?sponsor|(cannot|can't|unable to|will not|won't|do not|don't|are not able to|is not able to) (consider|accept|hire|interview|employ) [a-z ,]{0,40}(require|need)[a-z ]{0,30}(sponsorship|visa)|(authorized|eligible) to work in the (u\.?s\.?|united states) (on a permanent basis|permanently))")
AUTH_SPONS = re.compile(r"(visa sponsorship (is )?available|(will|we|can|able to|happy to|willing to) sponsor (h-?1b|visas?|work visas?|employment visas?|immigration|international|qualified|candidates|the right candidate)|sponsorship (is )?available|open to sponsoring|h-?1b sponsorship (is )?available|provides? visa sponsorship|offers? visa sponsorship|sponsorship provided|sponsorship offered|will provide sponsorship|support (h-?1b|visa) (transfers|sponsorship))")
AUTH_CITIZEN = re.compile(r"(u\.?s\.? citizen(ship)? (is |are )?(required|only)|must be (a )?(u\.?s\.?|united states) citizens?|us citizens only|united states citizen(ship)? (is )?required|citizenship is required|requires? (u\.?s\.?|united states) citizenship|only (u\.?s\.?|united states) citizens|u\.?s\.? persons? (as defined|only|status)|(?<![a-z])itar(?![a-z]))")
AUTH_CITIZEN_PR = re.compile(r"(green card|permanent resident|lawful permanent|u\.?s\.? persons?|(?<![a-z])itar(?![a-z]))")
AUTH_CLEAR = re.compile(r"(security clearance|secret clearance|top secret (clearance|security clearance|/ ?sci|sci)|ts/sci|ts sci|public trust (clearance|position|background)|active clearance|clearance (is )?required|ability to obtain (a |an )?(security |government )?clearance|dod clearance|polygraph|obtain and maintain (a |an )?(security )?clearance)")
AUTH_CLEAR_OBTAIN = re.compile(r"(ability to obtain|able to obtain|eligible (to obtain|for) (a |an )?(security )?clearance|obtain and maintain|willing to obtain|must be able to obtain)")
AUTH_CLEAR_ACTIVE = re.compile(r"((active|current|existing|valid)[a-z /-]{0,30}(clearance|ts/sci|ts sci|top secret)|(must|need to|required to) (have|hold|possess) (a |an )?(active |current )?[a-z /-]{0,20}(clearance|ts/sci)|(clearance|ts/sci|ts sci)[a-z ,/-]{0,24}(with|and) (a )?(full[- ]scope |ci )?(poly|polygraph))")
QUESTION = re.compile(r"\?\s*$|^(will|do|are|would|can|have|does|is) you(?![a-z])")
# clearance levels: 1 Public Trust, 2 Secret (or DOE L), 3 Top Secret (or DOE Q), 4 TS/SCI
CLR_NAMES = ["", "Public Trust", "Secret", "Top Secret", "TS/SCI"]
_CLR4 = re.compile(r"(?<![a-z])(ts\s*/\s*sci|ts[- ]sci)(?![a-z])|top[- ]secret\s*/\s*sci|(?<![a-z])sci(?![a-z])")
_CLR3 = re.compile(r"top[- ]secret|(?<![a-z])q[- ](security\s+)?clearance")
_CLR2 = re.compile(r"(?<![a-z])secret(?![a-z])|(?<![a-z])l[- ](security\s+)?clearance")
_CLR1 = re.compile(r"public[- ]trust")


def clr_level_in(t):
    if _CLR4.search(t):
        return 4
    if _CLR3.search(t):
        return 3
    if _CLR2.search(t):
        return 2
    if _CLR1.search(t):
        return 1
    return 0


# what a posting only says you'd be ELIGIBLE for ("Secret (TS/SCI eligible)") isn't what it requires
CLR_ELIG = re.compile(r"\(?\s*(?:ts\s*/\s*sci|ts[- ]sci|top[- ]secret(?:\s*/\s*sci)?|secret|sci)\s+(?:eligible|eligibility)\s*\)?|(?:eligible|eligibility)\s+(?:for\s+)?(?:a\s+|an\s+)?(?:ts\s*/\s*sci|ts[- ]sci|top[- ]secret(?:\s*/\s*sci)?|sci|secret)")


def job_clr_level(low):
    """A clearance of unstated level reads as Secret, the most common."""
    return clr_level_in(CLR_ELIG.sub(" ", low)) or 2


# a clearance you hold, from your resume - never one you're only eligible for,
# are pursuing, or that has lapsed
CAND_CLR_CTX = re.compile(r"clearance|ts\s*/\s*sci|ts[- ]sci|top[- ]secret|cleared")
CAND_CLR = re.compile(r"(?<![a-z])(?:(ts\s*/\s*sci|ts[- ]sci|top[- ]secret(?:\s*/\s*sci)?|secret|public[- ]trust)(?:\s+(?:security\s+|government\s+)?clearance)?|(q|l)\s+(?:security\s+)?clearance)(?![a-z])")
CAND_CLR_NOT_BEFORE = re.compile(r"(?:eligible|eligibility|able to obtain|ability to obtain|willing to obtain|willingness to obtain|pursuing|obtaining|in process for|pending|apply for|applying for|expired|lapsed|inactive|former|formerly held|previously held|previous|no)\s+(?:for\s+)?(?:a\s+|an\s+|the\s+)?(?:active\s+|current\s+|dod\s+|doe\s+|government\s+|federal\s+)?$")
CAND_CLR_NOT_AFTER = re.compile(r"^\s*[(,:–-]?\s*(?:eligible|eligibility|pending|in process|in progress|expired|lapsed|inactive)(?![a-z])")


def cand_clearance(text):
    low = lc(text)
    if not CAND_CLR_CTX.search(low):
        return 0
    best = 0
    for m in CAND_CLR.finditer(low):
        lv = clr_level_in(m.group(1)) if m.group(1) else (3 if m.group(2) == "q" else 2)
        if lv <= best:
            continue
        if CAND_CLR_NOT_BEFORE.search(_u16_before(low, m.start(), 40)) or CAND_CLR_NOT_AFTER.search(_u16_after(low, m.end(), 30)):
            continue
        best = lv
    return best


def parse_auth(segs):
    r = {"noSponsorship": False, "sponsors": False, "citizenship": False, "citizenOrPR": False, "clearance": False,
         "clearanceObtainable": False, "clearanceActive": False, "clearanceLevel": 0, "clearancePreferred": False, "evidence": {}}
    for g in segs:
        if g["section"] == "about":
            continue
        if QUESTION.search(g["low"]):
            continue  # an application question states no policy
        if not r["noSponsorship"] and AUTH_NOSPON.search(g["low"]):
            r["noSponsorship"] = True
            r["evidence"]["noSponsorship"] = trunc(g["text"], 160)
        elif not r["sponsors"] and AUTH_SPONS.search(g["low"]) and not AUTH_NOSPON.search(g["low"]):
            r["sponsors"] = True
            r["evidence"]["sponsors"] = trunc(g["text"], 160)
        if g["cue"] == "neg":
            continue
        if not r["citizenship"] and not r["citizenOrPR"] and AUTH_CITIZEN.search(g["low"]):
            if AUTH_CITIZEN_PR.search(g["low"]):
                r["citizenOrPR"] = True
                r["evidence"]["citizenOrPR"] = trunc(g["text"], 160)
            else:
                r["citizenship"] = True
                r["evidence"]["citizenship"] = trunc(g["text"], 160)
        if not r["clearance"] and AUTH_CLEAR.search(g["low"]):
            # "Secret clearance preferred" / a Preferred section: a plus, never a requirement
            if seg_importance(g) == "pref":
                if not r["clearancePreferred"]:
                    r["clearancePreferred"] = True
                    r["evidence"]["clearancePreferred"] = trunc(g["text"], 160)
                continue
            r["clearance"] = True
            r["clearanceObtainable"] = AUTH_CLEAR_OBTAIN.search(g["low"]) is not None
            r["clearanceActive"] = (not r["clearanceObtainable"]) and AUTH_CLEAR_ACTIVE.search(g["low"]) is not None
            r["clearanceLevel"] = job_clr_level(g["low"])
            r["evidence"]["clearance"] = trunc(g["text"], 160)
    if r["noSponsorship"]:
        r["sponsors"] = False
    if r["citizenship"]:
        r["citizenOrPR"] = False
    return r


NUM_TOK = r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+(?:\.[0-9]+)?)"
SAL_RANGE = re.compile(r"\$\s?" + NUM_TOK + r"\s*(k)?\s*(?:-|to)\s*\$?\s?" + NUM_TOK + r"\s*(k)?(\s*(?:/|per|an|a)\s*(?:hour|hr|year|yr|annum|annually|month|mo|week|wk)(?![a-z]))?")  # run on lowercased text: no re.I
SAL_SINGLE = re.compile(r"\$\s?" + NUM_TOK + r"\s*(k)?(\s*(?:/|per|an|a)\s*(?:hour|hr|year|yr|annum|month|mo|week|wk)(?![a-z]))")
# a bonus, relocation or tuition figure is not the salary - unless the line also says it's pay
SAL_OTHER = re.compile(r"(bonus|sign-on|signing|relocation|tuition|stipend|reimburse|401\(?k\)?|referral|allowance|equity grant|rsus?(?![a-z])|retention|per diem|scholarship)")
SAL_WORD = re.compile(r"(salary|base pay|base salary|pay range|pay rate|pay scale|compensation|wage|hourly rate|annual pay|starting pay|pay:|rate:|/hr|/hour|per hour|an hour|hourly)")
SAL_EST = re.compile(r"(?<![a-z])(estimated|est\.|estimate)(?![a-z])")


def per_of(per, hi):
    if re.search(r"hour|hr", per):
        return "hour"
    if re.search(r"month|mo", per):
        return "month"
    if re.search(r"week|wk", per):
        return "week"
    if re.search(r"year|yr|annum|annual", per):
        return "year"
    return "hour" if hi < 300 else "year"


def _num_tok(s):
    v = float(s.replace(",", ""))
    return int(v) if v.is_integer() else v


def salary_from_text(segs):
    for g in segs:
        if SAL_OTHER.search(g["low"]) and not SAL_WORD.search(g["low"]):
            continue
        est = SAL_EST.search(g["low"]) is not None
        m = SAL_RANGE.search(g["low"])
        if m:
            k1, k2 = bool(m.group(2)), bool(m.group(4))
            lo, hi = _num_tok(m.group(1)), _num_tok(m.group(3))
            per = lc(m.group(5)) if m.group(5) else ""
            if k2 and not k1 and lo < 1000:
                k1 = True
            if k1:
                lo *= 1000
            if k2:
                hi *= 1000
            period = per_of(per, hi)
            if period == "year" and hi < 1000:
                continue
            if period == "hour" and (lo < 7 or hi > 500):
                continue
            if period == "year" and (lo < 15000 or hi > 1000000):
                continue
            if hi < lo:
                continue
            return {"min": lo, "max": hi, "period": period, "text": trunc(g["text"], 140), "est": est}
        m = SAL_SINGLE.search(g["low"])
        if m:
            v = _num_tok(m.group(1))
            if m.group(2):
                v *= 1000
            pr = per_of(lc(m.group(3)), v)
            if pr == "hour" and (v < 7 or v > 500):
                continue
            if pr == "year" and (v < 15000 or v > 1000000):
                continue
            return {"min": v, "max": v, "period": pr, "text": trunc(g["text"], 140), "est": est}
    return None


ANNUAL_X = {"hour": 2080, "day": 260, "week": 52, "month": 12, "year": 1}


def annualize(v, period):
    if v is None:
        return None
    return rhu(v * ANNUAL_X.get(period, 1))


def pay_ok(lo, hi):
    """Cents, typos and stipends aren't a salary."""
    return lo is not None and hi is not None and lo >= 5000 and hi <= 2000000


def parse_salary(n, segs):
    if n["salaryMin"] is not None or n["salaryMax"] is not None:
        per = n["salaryPeriod"] or "year"
        mn = n["salaryMin"] if n["salaryMin"] is not None else n["salaryMax"]
        mx = n["salaryMax"] if n["salaryMax"] is not None else n["salaryMin"]
        if mx < mn:
            mn, mx = mx, mn
        am, ax = annualize(mn, per), annualize(mx, per)
        if pay_ok(am, ax):
            return {"min": mn, "max": mx, "period": per, "annualMin": am, "annualMax": ax,
                    "source": "estimated" if n["salaryPredicted"] is True else "listed", "text": ""}
    p = salary_from_text(segs)
    if p:
        pm, px = annualize(p["min"], p["period"]), annualize(p["max"], p["period"])
        if pay_ok(pm, px):
            return {"min": p["min"], "max": p["max"], "period": p["period"], "annualMin": pm, "annualMax": px,
                    "source": "estimated" if p["est"] else "parsed", "text": p["text"]}
    return {"min": None, "max": None, "period": None, "annualMin": None, "annualMax": None, "source": None, "text": ""}


TRAVEL_RE = re.compile(r"(?:up to|approximately|about|around|~)?\s*([0-9]{1,3})\s*%\s*(?:of the time\s*)?(?:travel|travelling|traveling|domestic travel)|travel(?:ing)?\s*(?:required\s*)?(?:up to|of up to|approximately|about|around|~|:|-)?\s*([0-9]{1,3})\s*%")


def parse_travel(segs):
    for g in segs:
        m = TRAVEL_RE.search(g["low"])
        if m:
            v = int(m.group(1) or m.group(2))
            if 0 <= v <= 100:
                return v
    return None


def parse_industries(n, segs):
    intro, about_txt, acc = "", "", 0
    for g in segs:
        if g["section"] == "about":
            about_txt += " " + g["low"]
        if acc < 400:
            intro += " " + g["low"]
            acc += _js_len(g["low"])
    org = lc(n["org"])
    text = about_txt + " " + intro
    out = []
    for d in TAX["industries"]:
        hits, org_hit = [], False
        for k in d["keywords"]:
            if has_word(org, k):
                org_hit = True
                if k not in hits:
                    hits.append(k)
            elif has_word(text, k) and k not in hits:
                hits.append(k)
        if org_hit or len(hits) >= 2:
            out.append({"id": d["id"], "name": d["name"], "hits": hits[:4], "strength": len(hits) + (2 if org_hit else 0)})
    out.sort(key=lambda x: -x["strength"])
    return out[:2]


AGENCY_TAIL = re.compile(r"^(international|global|usa|us|americas|north america|technology|technologies|talent|talent solutions|staffing|staffing services|recruitment|recruiting|resources|workforce|consulting|services|solutions|it|professional|professionals|search)( (international|global|usa|us|technology|technologies|talent|solutions|staffing|recruitment|recruiting|resources|services|group))*$")
NEG_BEFORE = re.compile(r"(?<![a-z])(no|not|never|without|isn't|is not|aren't|are not)\s+(a\s+|an\s+|any\s+)?$")


def agency_name_of(org):
    """A staffing firm's name is the WHOLE company name ("Hays County" is not Hays)."""
    o = norm_org(org)
    if not o:
        return None
    for a in TAX["agency_names"]:
        if o == a:
            return a
        if o.startswith(a + " ") and AGENCY_TAIL.search(o[len(a) + 1:]):
            return a
    return None


@functools.lru_cache(maxsize=1024)
def _phrase_re(ph):
    return re.compile(B4 + esc_re(ph) + AF)


def phrase_hit(text, lst):
    """The first listed phrase present as whole words and not negated."""
    for ph in lst:
        if ph not in text:
            continue
        for m in _phrase_re(ph).finditer(text):
            if not NEG_BEFORE.search(_u16_before(text, m.start(), 16)):
                return ph
    return None


def parse_agency(n, segs):
    org = lc(n["org"])
    reasons = []
    nm = agency_name_of(n["org"])
    if nm:
        reasons.append('"' + n["org"] + '" is a staffing/recruiting firm')
    else:
        w = has_any_word(org, TAX["agency_name_words"])
        if w:
            reasons.append('company name contains "' + w + '"')
    all_text = " \n ".join(g["low"] for g in segs)
    ph = phrase_hit(all_text, TAX["agency_phrases"])
    if ph:
        reasons.append('posting says "' + ph + '"')
    return {"is": len(reasons) > 0, "reasons": reasons}


def parse_evergreen(n, segs):
    # only what the posting says about ITSELF - not company copy or the company's name
    all_text = lc(n["title"]) + " \n " + " \n ".join(g["low"] for g in segs if g["section"] != "about")
    ph = phrase_hit(all_text, TAX["evergreen_phrases"])
    return {"is": bool(ph), "phrase": ph or None}


def find_roles(text):
    I = idx()
    low = lc(text)
    out, seen = [], set()
    for m in I.role_re.finditer(low):
        rid = I.role_map[m.group(1)]
        if rid not in seen:
            seen.add(rid)
            out.append({"id": rid, "name": I.role[rid]["name"], "pattern": m.group(1), "len": len(m.group(1))})
    out.sort(key=lambda r: (-r["len"], I.role_i[r["id"]]))
    return [{"id": r["id"], "name": r["name"], "pattern": r["pattern"]} for r in out[:3]]


# ------------------------------------------------------------ canonical key
ORG_SUFFIX = re.compile(r"(?<![a-z0-9])(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|plc|gmbh|the|group|holdings)(?![a-z0-9])")


@functools.lru_cache(maxsize=20000)
def _norm_org_l(s):
    s = re.sub(r"^(.+?),\s*(the\s+)?(city|county|town|village|township|borough|state|commonwealth|district|port|parish) of\s*\Z", r"\3 of \1", s)
    s = s.replace("&", " and ")
    s = ORG_SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_org(org):
    # pure, and called for every list entry on every job - so each distinct name is normalised once
    return _norm_org_l(lc(org))


@functools.lru_cache(maxsize=20000)
def _kw_norm_l(s):
    return _qhyph(s.strip())


def kw_norm(k):
    return _kw_norm_l(lc(k))


def norm_title(title):
    s = lc(title)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"(?<![a-z])sr\.?(?![a-z])", "senior", s)
    s = re.sub(r"(?<![a-z])jr\.?(?![a-z])", "junior", s)
    s = re.sub(r"(?<![a-z])mgr\.?(?![a-z])", "manager", s)
    s = re.sub(r"(?<![a-z])asst\.?(?![a-z])", "assistant", s)
    s = re.sub(r"(?<![a-z0-9])(req|job|id|requisition)\s*#?\s*[a-z0-9-]*[0-9][a-z0-9-]*", " ", s)
    s = re.sub(r"#\s*[0-9]+", " ", s)
    s = re.sub(r"(?<![a-z])(remote|hybrid|onsite|on-site|in-office|us|usa|wfh)(?![a-z])", " ", s)
    s = re.sub(r"[^a-z0-9+#]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# No real company name: two such postings are never "the same job" (no merging, no repost count)
NO_ORG = re.compile(r"^(unknown|unknown employer|confidential|confidential employer|undisclosed|not disclosed|not specified|unspecified|n a|na|none|null|anonymous|private|private employer|stealth|stealth startup|stealth mode|stealth mode startup|hiring|employer|our client|client|various|multiple|multiple employers)\Z")


def canonical_key(job):
    org = norm_org(job["org"])
    if not org or NO_ORG.match(org):
        return "#" + _s(job["id"])
    if job["mode"] == "remote":
        place = "remote"
    elif job.get("places"):
        p0 = job["places"][0]
        place = p0["metro"] or p0["state"] or lc(p0["label"])
    else:
        place = lc(job["location"])
    return org + "|" + norm_title(job["title"]) + "|" + place


# ------------------------------------------------------------------ parseJob
ORLIST_ANY = re.compile(r"(?<![a-z])(or|and/or)(?![a-z])|[a-z0-9+#)]\s*/\s*[a-z(]")
_OR_AFTER = re.compile(r"^\s*\)?\s*,?\s*(or|and/or)\s")
_SLASH_AFTER = re.compile(r"^\s*/\s*\S")
_OR_BEFORE = re.compile(r"(^|[\s,(])(or|and/or)\s*$")
_SLASH_BEFORE = re.compile(r"\S\s*/\s*$")
_LIST_AFTER = re.compile(r"^((\s*,\s*[^,;.()]{1,40}){1,6})\s*,?\s*(or|and/or)\s")
_PREPS = re.compile(r"(?<![a-z])(in|with|using|for|of|on|to|at|by|from)(?![a-z])")


OR_GENERIC = re.compile(r"^\s*[()]?\s*,?\s*\(?\s*(or|and/or)\s+(a |an |any |some |other |another )?(similar|equivalent|comparable|related|other|another|alternative|like)(?![a-z])|^\s*/\s*(similar|equivalent|other)(?![a-z])|^\s*[a-z ]{0,30}?[()]?\s*,?\s*\(?\s*(or|and/or)\s+(at least |a minimum of |minimum of )?([0-9]+|one|two|three|four|five|six|seven|eight|nine|ten)\+?\s*(-\s*[0-9]+\s*)?(years?|yrs?)(?![a-z])")


def or_generic(low, h):
    """"Tableau or similar" offers a choice we can't see; "RN license or compact license" doesn't."""
    return OR_GENERIC.search(_u16_after(low, h["end"], 60)) is not None


def mask_org(text, org_low):
    """The employer's own name is not a skill ("Cardinal Payroll is hiring")."""
    if not org_low or _js_len(org_low) < 4:
        return text
    low = lc(text)
    if len(low) != len(text) or org_low not in low:
        return text
    out, frm = [], 0
    L = len(org_low)
    while True:
        at = low.find(org_low, frm)
        if at == -1:
            break
        pre = low[at - 1] if at > 0 else ""
        post = low[at + L] if at + L < len(low) else ""
        if re.match(r"[a-z0-9]", pre) or re.match(r"[a-z0-9+#&]", post):
            out.append(text[frm:at + 1])
            frm = at + 1
            continue
        out.append(text[frm:at] + " " * L)
        frm = at + L
    out.append(text[frm:])
    return "".join(out)


# "Bachelor's degree in Statistics, Economics or a related field" names a FIELD, not a skill
DEGREE_SUBJ = re.compile(r"(degree|bachelor's|bachelors|master's|masters|b\.s\.|b\.a\.|m\.s\.|bs|ba|ms|ma|phd|ph\.d\.|major|majoring|diploma|concentration)\s+(in|of)\s+")
DEGREE_STOP = re.compile(r"(required|preferred|or equivalent|or (a )?related|or (a )?similar|or other|with |experience|plus|including|and at least|[0-9]|;|\.(\s|$)|\(|:)")


def degree_spans(low):
    out = []
    if " in " not in low and " of " not in low:
        return out
    for m in DEGREE_SUBJ.finditer(low):
        if m.start() > 0 and re.match(r"[a-z0-9]", low[m.start() - 1]):
            continue
        st = m.end()
        rest = _u16_after(low, st, 100)
        sm = DEGREE_STOP.search(rest)
        out.append((st, st + (sm.start() if sm else len(rest))))
    return out


TEAM_ALIAS = re.compile(r"^(customer success|sales|marketing|product management|engineering|design|finance|legal|operations|customer support|support|data science|recruiting|hr|product|account management|supply chain|data analytics|user research|ux research|devops|quality assurance|business intelligence|people operations|procurement)$")
TEAM_AFTER = re.compile(r"^\s+(teams?|departments?|org|organization|leaders|leadership|stakeholders)(?![a-z])")
# "you will grow toward project management", "we'll train you in Civil 3D": where the job takes you, not what it asks for
GROWTH_BEFORE = re.compile(r"(?<![a-z])(grow (toward|towards|into)|growth (toward|towards|into)|path (to|toward|towards|into)|progress (toward|towards|into)|advance (toward|towards|into)|opportunit(y|ies) to (learn|grow|develop|gain|build|get)|(you will|you'll|you will be|you'll be) (learn|learning|trained|mentored|taught)|we('ll| will) (train|teach|mentor) you|(train|training|trained) you (in|on)|on-the-job training (in|on)|learn (to|how to)|(and|to|will|you('ll| will)|chance to|help you)\s+learn)[a-z ,&/-]{0,30}\Z")
INTEREST_BEFORE = re.compile(r"(?<![a-z])(interest in|interested in|passion for|passionate about|curiosity (about|for)|curious about|enthusiasm for|eager to learn|willing(ness)? to learn|desire to learn|excited (about|by)|appreciation for)[a-z ,&/-]{0,30}\Z")
COLLAB_ANY = re.compile(r"(partner|collaborat|work closely|working closely|works closely|liaise|liaising|coordinat|alongside|cross-functional)")
COLLAB_BEFORE = re.compile(r"(partner|partnering|partners|collaborate|collaborating|collaborates|work closely|working closely|works closely|liaise|liaising|coordinate|coordinating|alongside|cross-functionally|cross-functional)( with)?[a-z ,&/-]{0,60}$")


def or_flags(low, hits):
    res = [False] * len(hits)
    if not ORLIST_ANY.search(low):
        return res
    for i, h in enumerate(hits):
        # look only at the neighbourhood; \u0000 marks a cut-off window
        win = _u16_before(low, h["at"], 40)
        before = ("\u0000" if len(win) < h["at"] else "") + win
        after = _u16_after(low, h["end"], 300)
        if _OR_AFTER.search(after) or _SLASH_AFTER.search(after):
            res[i] = True
        elif _OR_BEFORE.search(before) or _SLASH_BEFORE.search(before):
            res[i] = True
        else:
            lm = _LIST_AFTER.search(after)
            if lm and not _PREPS.search(lm.group(1)):
                res[i] = True
    return res


ST_ZONE = {"CT": "ET", "DE": "ET", "DC": "ET", "FL": "ET", "GA": "ET", "IN": "ET", "KY": "ET", "ME": "ET", "MD": "ET", "MA": "ET", "MI": "ET", "NH": "ET", "NJ": "ET", "NY": "ET", "NC": "ET", "OH": "ET", "PA": "ET", "RI": "ET", "SC": "ET", "VT": "ET", "VA": "ET", "WV": "ET",
           "AL": "CT", "AR": "CT", "IL": "CT", "IA": "CT", "KS": "CT", "LA": "CT", "MN": "CT", "MS": "CT", "MO": "CT", "NE": "CT", "ND": "CT", "OK": "CT", "SD": "CT", "TN": "CT", "TX": "CT", "WI": "CT",
           "AZ": "MT", "CO": "MT", "ID": "MT", "MT": "MT", "NM": "MT", "UT": "MT", "WY": "MT", "CA": "PT", "NV": "PT", "OR": "PT", "WA": "PT", "AK": "AKT", "HI": "HT"}
ZONE_NAMES = {"ET": "Eastern", "CT": "Central", "MT": "Mountain", "PT": "Pacific", "AKT": "Alaska", "HT": "Hawaii"}
LIMIT_CUE = re.compile(r"(must (reside|live|be located|be based|be in)|(candidates|applicants|employees) (must )?(reside|live|be located|be based|located|residing|based)|open (only )?to (candidates|applicants|residents|people) (in|of|located in|residing in|based in)|only (considering|hiring|accepting|able to hire|open to) (candidates |applicants |people |residents )?(in|from|located in|residing in)|we (can|are able to|currently) (only )?hire (in|from)|residents of|eligible (states|locations)|remote (in|within|from) (the )?(following|these)|time ?zones?)")
EXCL_CUE = re.compile(r"(excluding|except( for)?|not (available|open|eligible) (in|to (residents of|candidates in))|(cannot|can't|unable to|are not able to) (hire|employ) (in|residents of|candidates in))\s+")
ZONE_RE = re.compile(r"(?<![a-z])(eastern|central|mountain|pacific)( standard)?( time)?(?![a-z])")
_ST_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])")


def states_in(text, low):
    I = idx()
    out = []
    for m in I.state_name_re.finditer(low):
        c = I.state_by_name.get(m.group(1))
        if c and c not in out:
            out.append(c)
    for m in _ST_CODE.finditer(text):
        if m.group(1) != "US" and m.group(1) in TAX["us_states"] and m.group(1) not in out:
            out.append(m.group(1))
    return out


TZ_PREF = re.compile(r"(?<![a-z])(preferred|preference|prefer|prefers|ideally|a plus|nice to have|bonus|helpful)(?![a-z])")
TZ_HOURS = re.compile(r"(?<![a-z])(hours|business hours|working hours|work hours|overlap|availability|available during|schedule|shifts?|meetings|core hours|coverage)(?![a-z])")


def clause_of(low, at):
    """The sentence clause around a cue (so "...; Spanish preferred" elsewhere doesn't soften it)."""
    a = max(low.rfind(".", 0, at + 1), low.rfind(";", 0, at + 1)) + 1
    m = re.search(r"[.;]", low[at:])
    return low[a:(len(low) if m is None else at + m.start())]


def soft_limit(low, lm):
    """"time zones preferred" is a wish; "Eastern time zone hours" is a schedule - but "must reside in
    the Central time zone (to overlap with the team)" is still a residency rule."""
    cl = clause_of(low, lm.start())
    return bool(TZ_PREF.search(cl)) or (re.fullmatch(r"time ?zones?", lm.group(0)) is not None and bool(TZ_HOURS.search(cl)))


def parse_remote_limit(segs, loc):
    """Remote, but only for some states or time zones."""
    r = {"states": [], "zones": [], "excluded": [], "text": ""}
    pool = [{"text": loc or "", "low": lc(loc), "section": "none"}] + list(segs)
    for g in pool:
        if g["section"] in ("about", "benefits"):
            continue
        lm, em, hit = LIMIT_CUE.search(g["low"]), EXCL_CUE.search(g["low"]), False
        if lm and soft_limit(g["low"], lm):
            lm = None
        if em:
            tail = _u16_after(g["text"], em.end(), 120)
            ex = states_in(tail, lc(tail))
            for c in ex:
                if c not in r["excluded"]:
                    r["excluded"].append(c)
            if ex:
                hit = True
        if lm:
            tl = _u16_after(g["text"], lm.end(), 160)
            tlow = lc(tl)
            cut = EXCL_CUE.search(tlow)
            if cut:
                tl, tlow = tl[:cut.start()], tlow[:cut.start()]
            for c in states_in(tl, tlow):
                if c not in r["states"] and c not in r["excluded"]:
                    r["states"].append(c)
                    hit = True
            zsrc = g["low"] if re.search(r"time ?zones?", lm.group(0)) else tlow
            for zm in ZONE_RE.finditer(zsrc):
                if re.search(r"time|zone", _u16_after(zsrc, zm.start(), 40)):
                    z = {"eastern": "ET", "central": "CT", "mountain": "MT", "pacific": "PT"}[zm.group(1)]
                    if z not in r["zones"]:
                        r["zones"].append(z)
                        hit = True
        if hit and not r["text"]:
            r["text"] = trunc(g["text"], 140)
    return r if (r["states"] or r["zones"] or r["excluded"]) else None


LIC_WORD = re.compile(r"(license|licensure|licensed|certificate|certification|credential|(?<![a-z])(lcsw|lscsw|licsw|lisw|lmsw|lpc|lpcc|lmhc|lmft)(?![a-z]))")
LIC_ACR = "lcsw|lscsw|licsw|lisw|lisw-s|lmsw|lpc|lpcc|lmhc|lmft|rn|lpn|aprn|pe|cpa"
LIC_NEAR = re.compile(r"(license|licensure|licensed|certificate|certification|credential)[^.;:]{0,40}?(in|from|by|of) (the state of )?\Z|(license|licensure|licensed|certificate|certification|credential|(?<![a-z])(" + LIC_ACR + r"))[^.;:]{0,60}?\s[-–—,:(]\s*(the state of )?\Z|(license|licensure|certificate|certification|credential|(?<![a-z])(" + LIC_ACR + r"))\s*[-–—,:(]\s*(the state of )?\Z")
# "not licensed in Kansas", "no license in Texas yet"
LIC_NEG_BEFORE = re.compile(r"(?<![a-z])(not|no|never|un|without|except|excluding)\s*(currently\s+|yet\s+|a\s+)?(licensed|license[ds]?|licensure|certified)[^.;:]{0,30}?\Z")
LIC_AFTER_ACR = re.compile(r"^\s*(state\s+)?(independent\s+)?(" + LIC_ACR + r")(?![a-z])")
LIC_AFTER_WORDS = re.compile(r"^\s*(state\s+)?([a-z-]+\s+){0,3}(license|licensure)(?![a-z])")
_LIC_AFTER = re.compile(r"^\s*(state\s+)?(01\s+)?(general\s+)?(board of nursing |rn |lpn |nursing |teaching |educator |professional educator |cpa |professional |pharmacist |pharmacy |medical |physical therapy |social work |counselor |real estate |journeyman electrician |master electrician |journeyman electrical |master electrical |electrical contractor |electrician |electrical |journeyman |master |plumbing |hvac )?(license|licensure|certificate|certification|credential)")
_LIC_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{2})\s+(RN |LPN |CPA |PE |teaching |nursing |professional |01 |journeyman electrician |master electrician |electrical |electrician |journeyman |master )?(license|licensure|certificate|certification|LCSW|LSCSW|LICSW|LISW|LMSW|LPC|LPCC|LMHC|LMFT)(?![A-Za-z])")


def license_states(text):
    """A license tied to a state ("Active RN license in Illinois", "Texas teaching certificate")."""
    low = lc(text)
    I = idx()
    out = []
    if not LIC_WORD.search(low):
        return out
    for m in I.state_name_re.finditer(low):
        after = _u16_after(low, m.end(), 64)
        before = _u16_before(low, m.start(), 70)
        if LIC_NEG_BEFORE.search(before):
            continue
        if LIC_AFTER_ACR.search(after) or LIC_AFTER_WORDS.search(after) or _LIC_AFTER.search(after) or LIC_NEAR.search(before):
            c = I.state_by_name.get(m.group(1))
            if c and c not in out:
                out.append(c)
    for m in _LIC_CODE.finditer(text):
        if m.group(1) in TAX["us_states"] and m.group(1) not in out and not LIC_NEG_BEFORE.search(lc(_u16_before(text, m.start(), 70))):
            out.append(m.group(1))
    return out


LIC_TRANSFER = re.compile(r"(?<![a-z])(reciprocity|by endorsement|licensure by endorsement|transfer (of )?(your |their |a |the )?licen[cs](e|ure)|licensed (at the [a-z ]+ level )?in another state|out[- ]of[- ]state licen[cs]|another state may apply|(obtain|get|secure|acquire|transfer)[a-z ]{0,40}licens(e|ure)[a-z ,]{0,40}within [0-9]+ (days|months)|eligible for (licensure|a license) in|(ability|able|willing(ness)?) to obtain [a-z ]{0,30}licens(e|ure))(?![a-z])")


def parse_license(segs):
    r = {"states": [], "compactOk": False, "transferOk": False, "text": ""}
    for g in segs:
        imp = seg_importance(g)
        if not imp or imp == "pref":
            continue
        ls = license_states(g["text"])
        if ls:
            for c in ls:
                if c not in r["states"]:
                    r["states"].append(c)
            if not r["text"]:
                r["text"] = trunc(g["text"], 140)
            if LIC_TRANSFER.search(g["low"]):
                r["transferOk"] = True
        if re.search(r"(compact|multistate|multi-state)", g["low"]) and LIC_WORD.search(g["low"]):
            r["compactOk"] = True
    return r if r["states"] else None


MGMT_REQ = re.compile(r"(?<![a-z])(people management|people manager|managing (a |the )?(team|teams|people|staff|direct reports|engineers|designers|analysts|nurses|associates|group)|managing ([a-z]+ ){1,3}(teams|staff|reps|representatives)|manage (a |the )?(team|teams|people|staff|direct reports|engineers|designers|analysts)|supervis(ing|ory) (experience|staff|employees|a team|others|teams)|direct reports|lead(ing)? (a |the )?teams? of|manage a team of|(people|team|staff) management|[0-9]+\+?\s*(years?|yrs?) (of )?(people |team )?(management|managing|supervisory|leadership) experience|[0-9]+\+?\s*(years?|yrs?) (of )?(formal|proven|direct|prior|progressive|nursing|clinical|operational|frontline|front-line|line) (people |team )?(management|supervisory|leadership) experience|[0-9]+\+?\s*(years?|yrs?) (of |in )?(an? )?([a-z]+ ){0,2}(leadership|management|managerial|supervisory) (role|position)s?)(?![a-z])")


# "required": the role involves managing people (what the "no management" filter reads).
# "asks": the posting asks for management EXPERIENCE you must already have - only that can
# cap your fit. "You'll lead a team of three" is the job, not a prerequisite, and
# "experience managing people or agencies" can be met without ever having had reports.
MGMT_EXP = re.compile(r"(?<![a-z])(experience (managing|leading|supervising|building and leading|building and managing|hiring and managing|as a (people )?manager)|(management|managerial|supervisory|leadership|people[- ]management) experience|(years?|yrs?) (of )?(experience )?(managing|leading|supervising)|(years?|yrs?) (of |in )?(an? )?([a-z]+ ){0,2}(leadership|management|managerial|supervisory) (role|position)s?|track record of (managing|leading|building)|proven (ability to (manage|lead)|(people )?(management|leadership))|(have|has|having) (previously )?(managed|led|supervised)|prior (people )?(management|managerial|supervisory))(?![a-z])")
MGMT_DUTY = re.compile(r"(?<![a-z])(you('ll| will| would)|will (lead|manage|oversee|supervise|build and lead|grow and lead)|this (role|person|position|hire) (will )?(leads?|manages?|oversees?|supervises?))(?![a-z])")
MGMT_ALT = re.compile(r"(?<![a-z])(people|teams?|staff|direct reports)\s+(or|and/or)\s+(an? )?(agenc(y|ies)|vendors?|contractors?|freelancers?|partners?|projects?|programs?|budgets?|clients?|accounts?)(?![a-z])|(?<![a-z])(agenc(y|ies)|vendors?|contractors?|freelancers?)\s+(or|and/or)\s+(people|teams?|staff)(?![a-z])")


# "leading a team without direct people management", "a non-supervisory role": management ruled OUT
MGMT_NEG = re.compile(r"(?<![a-z])(?:(?:without|no|not|never|zero)\s+(?:any\s+|direct\s+|formal\s+|official\s+|line\s+)*(?:people[- ]management|people[- ]managers?|management|managerial|supervisory|supervision|managing people|direct reports)(?:\s+(?:duties|responsibilit(?:y|ies)|experience|required|needed|expected))?|non[- ]?(?:management|managerial|supervisory)|individual[- ]contributor)(?![a-z])")


def parse_mgmt(segs):
    r = {"required": False, "asks": False, "text": ""}
    for g in segs:
        imp = seg_importance(g)
        if not imp or imp == "pref":
            continue
        low = MGMT_NEG.sub(" ", g["low"])
        if not MGMT_REQ.search(low):
            continue
        if not r["required"]:
            r["required"], r["text"] = True, trunc(g["text"], 140)
        if not MGMT_ALT.search(low) and (MGMT_EXP.search(low) or (imp == "req!" and not MGMT_DUTY.search(low))):
            r["asks"], r["text"] = True, trunc(g["text"], 140)
            break
    return r


ENROLL_REQ = re.compile(r"(?<![a-z])(currently enrolled|must be (currently )?enrolled|(currently|actively) pursuing (a |an |your )?(bachelor's|bachelors|master's|masters|undergraduate|graduate|degree|bs|ba|ms|phd|mba|b\.s\.|m\.s\.)|current(ly)? (a )?(student|undergraduate|graduate student)|returning to (school|campus|your studies)|rising (junior|senior|sophomore)s?|must be a (current )?(student|undergraduate|graduate student)|enrolled (full[- ]time )?in (an? )?(accredited )?(bachelor's|bachelors|master's|masters|undergraduate|graduate|degree|university|college|phd)|pursuing (a|an) (bachelor's|bachelors|master's|masters|undergraduate|graduate|degree|bs|ba|ms|phd))(?![a-z])")
GRAD_WIN = re.compile(r"graduat(?:e|es|ing|ion)(?: date)?(?: of)?[a-z ,:]{0,24}?(?:between |from )?((?:[a-z]+\.? )?[0-9]{4})\s*(?:and|-|to|through|or)\s*((?:[a-z]+\.? )?[0-9]{4})")
RETURNING = re.compile(r"(?<![a-z])(returning to (school|campus|your studies|university|college|classes)|return(ing)? to (school|campus|your studies) after|at least one (more )?(semester|quarter|term|year) (of (school|study|coursework) )?remaining|continu(e|ing) (your )?(studies|education|degree) after)(?![a-z])")
TERM_RE = re.compile(r"(?<![a-z])(summer|fall|autumn|spring|winter) (20[0-9][0-9])(?![0-9])")
TERM_END_MONTH = {"spring": 5, "summer": 8, "fall": 12, "autumn": 12, "winter": 3}
CLASS_OF = re.compile(r"(?<![a-z])class of (20[0-9][0-9])(?:\s*(?:or|and|/|-)\s*(20[0-9][0-9]))?")


def _term_end_of(low):
    tm = TERM_RE.search(low)
    return int(tm.group(2)) * 12 + TERM_END_MONTH[tm.group(1)] if tm else None


def parse_enroll(segs, title=None):
    """Internship / new-grad eligibility: "currently enrolled", "graduating Dec 2026 - Jun 2027"."""
    r = {"required": False, "gradFrom": None, "gradTo": None, "text": "", "returning": False, "termEnd": None}
    for g in segs:
        if g["section"] in ("about", "benefits") or g["cue"] == "neg":
            continue
        if not r["required"] and seg_importance(g) != "pref" and ENROLL_REQ.search(g["low"]):
            r["required"] = True
            r["text"] = trunc(g["text"], 140)
        if not r["returning"] and RETURNING.search(g["low"]):
            r["required"], r["returning"], r["text"] = True, True, trunc(g["text"], 140)
        if r["termEnd"] is None:
            r["termEnd"] = _term_end_of(g["low"])
        if r["gradFrom"] is None:
            m = GRAD_WIN.search(g["low"])
            if m:
                a, b = parse_month(m.group(1), 0), parse_month(m.group(2), 0)
                if a is not None and b is not None and b >= a:
                    r["gradFrom"] = a
                    r["gradTo"] = b + 11 if re.match(r"^[0-9]{4}$", m.group(2).strip()) else b
                    if not r["text"]:
                        r["text"] = trunc(g["text"], 140)
            else:
                c = CLASS_OF.search(g["low"])
                if c:
                    y1 = int(c.group(1))
                    y2 = int(c.group(2)) if c.group(2) else y1
                    if y2 >= y1:
                        r["gradFrom"], r["gradTo"] = y1 * 12 + 1, y2 * 12 + 12
                        if not r["text"]:
                            r["text"] = trunc(g["text"], 140)
    if r["termEnd"] is None and title:
        r["termEnd"] = _term_end_of(lc(title))   # "UX Research Intern, Summer 2027"
    return r


HIRE_CUE = re.compile(r"(?<![a-z])(we('re| are) (hiring|looking for|seeking)|(is|are) (hiring|looking for|seeking)|hiring (an?|our)|looking for (an?|our)|seeking (an?|our)|searching for (an?|our)|join (us|our team|the team) as|as (a|an|our)|(in )?the role of|position of|we need (an?|our)|you('ll| will) (join|be) (us |our team )?as)(?![a-z])")
NEWGRAD_RE = re.compile(r"(?<![a-z])(new grads?|new graduates?|recent graduates?|recent grads?|graduating (in|by|between)|class of 20[0-9][0-9]|entry[- ]level|early[- ]career|no (prior )?experience (needed|required|necessary)|no experience needed)(?![a-z])")


# a title's main part, before its qualifier: "Data Analyst - Marketing", "Manager, Engineering", "Engineer (Rust)"
CERT_SOFT = re.compile(r"(?<![a-z])([a-z+]+-eligible|(license|licensure|certification|board|exam|cpa|pe|rn) eligible|eligible to (sit|obtain|apply)|candidates? (welcome|encouraged|considered)|or (actively |currently )?(pursuing|working towards?|on track)|on track (to|for)|or (the )?ability to obtain|ability to obtain|obtain within|willingness to (obtain|earn|pursue)|within [0-9]+ (days|months|year|years) of (hire|start))(?![a-z])")
COMPLIANT_SETUP = re.compile(r"^[- ]compliant\s+([a-z-]+\s+){0,2}(home office|office space|workspace|work space|internet|connection|devices?|setup|set-up|room|computer|phone line)(?![a-z])")
QUAL_SOFT = re.compile(r"(?<![a-z])(encouraged|welcome|eligible|candidates?|a plus|preferred|track|support)(?![a-z])")
TITLE_QUAL = re.compile(r"\s+[-–—|]\s+|:\s+|\s*\(|,\s+")



# ------------------------------------------- open-vocabulary requirement matching
# The taxonomy can't name every tool, code and practice in every field. The posting's own requirement
# words - "HEC-RAS", "ASC 606", "FlowJo", "flow cytometry", "board portals" - checked against your resume
# as you wrote it, fill the gap. Codes and product names are matched whole; ordinary words are weighed by
# how specific they are (a word every posting uses - "experience", "team" - weighs nothing).
_VOCAB_W = None
_PLACE_TOK = None
MONTH_DAY = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
             "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun"]


def vocab_weight(w):
    global _VOCAB_W
    if _VOCAB_W is None:
        vw = {}
        vc = TAX.get("vocab_common") or {}
        for x in vc.get("mid") or []:
            vw[x] = 0.6
        for x in vc.get("low") or []:
            vw[x] = 0.3
        for x in vc.get("stop") or []:
            vw[x] = 0
        _VOCAB_W = vw
    v = _VOCAB_W.get(w)
    return 1 if v is None else v


def place_tok(w):
    global _PLACE_TOK
    if _PLACE_TOK is None:
        pt = set()
        for k in TAX["us_states"]:
            for t in re.split(r"[^a-z0-9]+", lc(TAX["us_states"][k])):
                if t:
                    pt.add(t)
        for m in TAX["metros"]:
            for t in re.split(r"[^a-z0-9]+", lc(m["name"])):
                if t:
                    pt.add(t)
        # suburbs and towns too ("Murfreesboro", "Olathe") - but not the everyday words some towns are named for ("enterprise", "mission")
        for m in TAX["metros"]:
            for a in m["aliases"]:
                for t in re.split(r"[^a-z0-9]+", a):
                    if _js_len(t) >= 4 and vocab_weight(t) == 1:
                        pt.add(t)
        pt.update(MONTH_DAY)
        _PLACE_TOK = pt
    return w in _PLACE_TOK


_IES = re.compile(r"ies\Z")
_ESX = re.compile(r"(sses|shes|ches|xes|zes)\Z")
_S_END = re.compile(r"s\Z")
_S_KEEP = re.compile(r"(ss|us|is|ys|as|os)\Z")


def v_stem(w):
    """plural -> singular, the same way on both sides ("meetings" ~ "meeting", "assays" ~ "assay", "SOPs" ~ "SOP")"""
    n = _js_len(w)
    if n > 4 and _IES.search(w):
        return w[:-3] + "y"
    if n > 4 and _ESX.search(w):
        return w[:-2]
    if n > 3 and _S_END.search(w) and not _S_KEEP.search(w):
        return w[:-1]
    return w


# codes and product names: "HEC-RAS", "ASC 606", "ISO 9001", "Civil 3D", "NetSuite", "qPCR", "LSCSW"
ORM_CODE = re.compile(r"(?<![A-Za-z0-9])((?:[A-Z]{3,}[a-z]?|[A-Z]{2}[0-9][A-Za-z0-9]*|[A-Z][a-z]+[A-Z][A-Za-z0-9]*|[a-z]{1,3}[A-Z][A-Za-z0-9]*|[A-Z][A-Za-z]*[0-9][A-Za-z0-9]*)(?:[-/&+][A-Za-z0-9]+)*(?:\s[0-9]{2,5}[A-Za-z]?)?|[A-Z]{2}-[A-Z0-9]+|[A-Z][a-z]+\s[0-9][A-Z])(?![A-Za-z0-9])")
# a product name in parentheses or after "with / using": "(Diligent, BoardEffect)", "experience with Epic"
ORM_PAREN = re.compile(r"\(([^()]{2,120})\)")
ORM_PROPER = re.compile(r"(?<![A-Za-z0-9])[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?(?![A-Za-z0-9])")
ORM_PAREN_LIST = re.compile(r",|\sor\s|\sand\s|/")
ORM_PAREN_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Z][a-z]+[A-Z][A-Za-z0-9]*|[A-Z]{3,})(?![A-Za-z0-9])")
ORM_PAREN_STOP = ["required", "preferred", "optional", "remote", "hybrid", "onsite", "contract", "temporary", "full", "part", "time", "plus", "bonus", "nice", "must", "none", "other", "etc", "including", "such", "example", "see", "note", "yes", "and", "or", "with", "the", "for", "level", "senior", "junior", "lead", "basic", "advanced", "expert", "strong", "preferred"]
ORM_PREP_PROPER = re.compile(r"(?<![A-Za-z])(?:with|using|via)\s+([A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?)(?![A-Za-z0-9])")
ORM_CODE_STOP = ["usa", "eeo", "eoe", "pto", "ceo", "cfo", "coo", "cto", "cmo", "cio", "cpo", "svp", "evp", "avp", "iii", "faq", "llc", "inc", "ltd", "corp", "asap", "tbd", "ada", "fmla", "401k", "403b", "kpi", "kpis", "roi", "eod", "pdf", "mba", "phd", "gpa", "ged", "dei", "nyc", "est", "cst", "pst", "mst", "edt", "pdt", "cdt", "mdt", "hsa", "fsa", "ppo", "hmo", "hdhp", "ote", "doe", "w2", "usd", "ssn", "and", "the", "for", "our", "you", "all", "new", "job", "one", "two", "its", "now", "per", "ii", "iv", "afb", "afs", "nas"]
ORM_CODE_SKIP = re.compile(r"(days (a|per) week|in[- ]office|on[- ]site|onsite|hybrid|remote|located|location|commute|parking|relocat|headquarter|campus|neighborhood|downtown|office (in|at|on|near))")
ORM_SKIP = re.compile(r"(equal (employment )?opportunity|without regard to|reasonable accommodation|e-verify|affirmative action|pay range|salary range|base salary|compensation|benefits|401\(k\)|paid time off|health insurance|visa|sponsor|authorized to work|work authorization|background check|drug (test|screen)|\$\s?[0-9])")
_ORM_ADDR = re.compile(r"\s(street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|square|plaza|park)\Z", re.I)
IMP_RANK = {"pref": 1, "req": 2, "req!": 3}


def orm_key(t):
    k = re.sub(r"[^a-z0-9]+", "", lc(t))
    if re.search(r"[A-Z0-9]s\Z", re.sub(r"\s", "", t)) and re.match(r"[A-Z]", t):
        k = re.sub(r"s\Z", "", k)
    return k


def orm_collect(acc, text, low, hits, imp, skip):
    if ORM_SKIP.search(low):
        return
    taken = []

    def in_hit(a, b):
        return any(a < h["end"] and b > h["at"] for h in hits)
    letters = re.sub(r"[^A-Za-z]", "", text)
    uppers = re.sub(r"[^A-Z]", "", text)
    shouting = len(letters) >= 12 and len(uppers) / len(letters) > 0.6

    def add_code(raw, at, end, named):
        k = orm_key(raw)
        if (_js_len(k) < 3 or re.fullmatch(r"[0-9]+", k) or k in ORM_CODE_STOP or place_tok(k) or place_tok(v_stem(k)) or k in skip
                or (_js_len(raw) == 2 and raw in TAX["us_states"])):
            return
        if not named and (vocab_weight(k) == 0 or vocab_weight(v_stem(k)) == 0):
            return
        if _ORM_ADDR.search(raw):
            return
        if in_hit(at, end):
            return
        taken.append((at, end))
        cur = acc["codes"].get(k)
        if not cur:
            acc["codes"][k] = {"t": raw, "imp": imp}
            acc["codeOrder"].append(k)
        elif IMP_RANK[imp] > IMP_RANK[cur["imp"]]:
            cur["imp"] = imp
    if not shouting and not ORM_CODE_SKIP.search(low) and len(re.split(r"\s+", text)) > 2:
        for m in ORM_CODE.finditer(text):
            add_code(re.sub(r"\s+", " ", m.group(1)), m.start(), m.start() + len(m.group(1)), False)
        for m in ORM_PAREN.finditer(text):
            # a list of product names ("Diligent, BoardEffect"): an ordinary word written as a name is a name there
            inner, base = m.group(1), m.start() + 1
            named = ORM_PAREN_LIST.search(inner) is not None and ORM_PAREN_CODE.search(inner) is not None and re.search(r"(?<![A-Za-z])(AFB|AFS|NAS|JB)(?![A-Za-z])", inner) is None
            for pm in ORM_PROPER.finditer(inner):
                fw = lc(pm.group(0)).split(" ")[0]
                if place_tok(fw):
                    continue
                if vocab_weight(fw) >= 1:
                    add_code(pm.group(0), base + pm.start(), base + pm.start() + len(pm.group(0)), False)
                elif named and fw not in ORM_PAREN_STOP:
                    add_code(pm.group(0), base + pm.start(), base + pm.start() + len(pm.group(0)), True)
        for m in ORM_PREP_PROPER.finditer(text):
            pn = m.group(1)
            pat = m.end() - len(pn)
            fw = lc(pn).split(" ")[0]
            if vocab_weight(fw) >= 1 and not place_tok(fw):
                add_code(pn, pat, pat + len(pn), False)
    # ordinary words, outside what the taxonomy and the codes already read
    chars = list(low)
    for h in hits:
        for c in range(h["at"], min(h["end"], len(chars))):
            chars[c] = " "
    for a, b in taken:
        for c in range(a, min(b, len(chars))):
            chars[c] = " "
    for w in re.split(r"[^a-z0-9]+", "".join(chars)):
        if _js_len(w) < 3 or re.fullmatch(r"[0-9]+", w) or place_tok(w) or w in skip:
            continue
        st = v_stem(w)
        wt = vocab_weight(w)
        if st != w and place_tok(st):
            continue
        if wt == 1 and st != w:
            wt = vocab_weight(st)
        if not wt:
            continue
        cur = acc["toks"].get(st)
        if not cur:
            acc["toks"][st] = {"w": wt, "imp": imp, "t": w}
            acc["tokOrder"].append(st)
        elif IMP_RANK[imp] > IMP_RANK[cur["imp"]]:
            cur["imp"] = imp


def orm_finish(acc, has_explicit):
    terms = []
    for k in acc["codeOrder"]:
        c = acc["codes"][k]
        terms.append({"key": k, "name": c["t"], "required": c["imp"] == "req!" or (c["imp"] == "req" and not has_explicit)})
    vocab = []
    for k in acc["tokOrder"]:
        c = acc["toks"][k]
        f = 1 if c["imp"] == "req!" else ((0.5 if has_explicit else 0.8) if c["imp"] == "req" else 0.5)
        vocab.append({"stem": k, "word": c["t"], "w": math.floor(c["w"] * f * 100 + 0.5) / 100})
    return {"terms": terms[:40], "vocab": vocab[:160]}


def orm_candidate(units):
    """your side: every word and code your skills and resume use (joined pairs catch "HEC RAS" ~ "HEC-RAS", "Civil 3D" ~ "civil3d")"""
    keys, stems = {}, {}
    for u in units:
        lvl = 2 if u["proven"] else 1
        toks = [t for t in re.split(r"[^a-z0-9]+", lc(u["text"])) if t]
        for i, t in enumerate(toks):
            k2 = t + toks[i + 1] if i + 1 < len(toks) else None
            k3 = t + toks[i + 1] + toks[i + 2] if i + 2 < len(toks) else None
            for k in (t, k2, k3, v_stem(t)):
                if k and keys.get(k, 0) < lvl:
                    keys[k] = lvl
            if _js_len(t) >= 3:
                st = v_stem(t)
                if stems.get(st, 0) < lvl:
                    stems[st] = lvl
    return {"keys": keys, "stems": stems}


# a bare title ("Staff Engineer", "Engineer II", "Principal Engineer, Payments") names no field - the posting's own
# words do: the role its duties and requirements name most often, when that role is the same kind of job
# ("... engineer"), never the firm's self-description ("a water-resources consulting firm")
TITLE_HEAD = re.compile(r"(?<![a-z])(engineer|developer|scientist|analyst|designer|technician|technologist|specialist|coordinator|administrator|consultant|manager|nurse|therapist|counselor|accountant|architect|planner|associate|officer|representative|advisor|assistant|clinician|researcher)\Z")
HEAD_FORMS = {"engineer": ["engineer", "engineering"], "developer": ["developer", "development"], "scientist": ["scientist", "science"], "analyst": ["analyst", "analytics", "analysis"],
              "designer": ["designer", "design"], "technician": ["technician", "tech"], "technologist": ["technologist"], "specialist": ["specialist"], "coordinator": ["coordinator"],
              "administrator": ["administrator", "administration"], "consultant": ["consultant", "consulting"], "manager": ["manager", "management"], "nurse": ["nurse", "nursing"],
              "therapist": ["therapist", "therapy"], "counselor": ["counselor", "counseling"], "accountant": ["accountant", "accounting"], "architect": ["architect"], "planner": ["planner", "planning"],
              "associate": ["associate"], "officer": ["officer"], "representative": ["representative", "rep"], "advisor": ["advisor", "adviser"], "assistant": ["assistant"], "clinician": ["clinician"],
              "researcher": ["researcher", "research"]}


def head_noun_roles(t_main, segs):
    hm = TITLE_HEAD.search(re.sub(r"[\s,]+(i{1,3}|iv|[1-4])\s*\Z", "", lc(t_main)).strip(_JS_WS))
    if not hm:
        return []
    I = idx()
    forms = HEAD_FORMS[hm.group(1)]
    cnt, first, pat, order = {}, {}, {}, []
    for gi, g in enumerate(segs):
        if g["section"] in ("about", "benefits"):
            continue
        for m in I.role_re.finditer(g["low"]):
            words = re.split(r"[\s/-]+", m.group(1))
            if words[-1] not in forms:
                continue
            rid = I.role_map[m.group(1)]
            if rid not in cnt:
                cnt[rid], first[rid], pat[rid] = 0, (gi, m.start()), m.group(1)
                order.append(rid)
            cnt[rid] += 1
    best = None
    for rid in order:
        if best is None or cnt[rid] > cnt[best] or (cnt[rid] == cnt[best] and first[rid] < first[best]):
            best = rid
    return [{"id": best, "name": I.role[best]["name"], "pattern": pat[best], "fromDescription": True}] if best else []


def title_main(t):
    t = _s(t)
    m = TITLE_QUAL.search(t)
    return t[:m.start()] if (m and m.start() > 0) else t


def parse_job(listing):
    I = idx()
    n = normalize_listing(listing)
    segs = segments(n["description"], n["org"])
    occ, order, has_explicit = {}, [], False
    org_low = lc(n["org"]).strip()
    orm_acc = {"codes": {}, "codeOrder": [], "toks": {}, "tokOrder": []}
    # the company's own name and the title's initials ("our EBP") are not requirements
    orm_skip = set()
    org_w = [w for w in re.split(r"[^a-z0-9]+", org_low) if w]
    t_init = "".join(w[0] for w in re.split(r"[^a-z]+", lc(title_main(n["title"]))) if _js_len(w) > 1 and w not in ("of", "and", "the", "to", "for", "in"))
    if org_w and _js_len(org_w[0]) >= 4:
        orm_skip.add(org_w[0])
    if _js_len(t_init) >= 2:
        orm_skip.add(t_init)
    for i, seg in enumerate(segs):
        imp = seg_importance(seg)
        if not imp:
            continue
        seg_text = mask_org(seg["text"], org_low)
        hits = find_skills(seg_text)
        seg_low = seg["low"] if seg_text == seg["text"] else lc(seg_text)
        orm_collect(orm_acc, seg_text, seg_low, hits, imp, orm_skip)
        if not hits:
            continue
        # "partner with product and customer success" names teams, not skills you need
        if COLLAB_ANY.search(seg_low):
            hits = [x for x in hits if not (TEAM_ALIAS.match(seg_low[x["at"]:x["end"]]) and COLLAB_BEFORE.search(_u16_before(seg_low, x["at"], 80)))]
            if not hits:
                continue
        # "support our supply chain teams" names a team, not a skill you need
        hits = [x for x in hits if not (TEAM_ALIAS.match(seg_low[x["at"]:x["end"]]) and TEAM_AFTER.search(_u16_after(seg_low, x["end"], 30)))]
        if not hits:
            continue
        dsp = degree_spans(seg_low)
        if dsp:
            hits = [x for x in hits if not any(d[0] <= x["at"] < d[1] for d in dsp)]
            if not hits:
                continue
        hits = [x for x in hits if not COMPLIANT_SETUP.search(_u16_after(seg_low, x["end"], 60))]
        if not hits:
            continue
        cert_soft = CERT_SOFT.search(seg_low) is not None
        fl = or_flags(seg_low, hits)
        ev = trunc(seg["text"], 170)
        # duties only stop counting as the bar when a real requirements section names skills
        if not has_explicit and imp == "req!" and seg["section"] == "req" and any(I.skill[x["id"]]["kind"] != "soft" for x in hits):
            has_explicit = True
        gid = "g" + str(i)
        g_ids, g_hits = [], 0
        for a, h in enumerate(hits):
            if fl[a]:
                if h["id"] not in g_ids:
                    g_ids.append(h["id"])
                g_hits += 1
        if len(g_ids) >= 2:
            g_kind = "anyof"
        elif g_hits >= 2:
            g_kind = "none"
        elif g_hits == 1:
            g_kind = "alt"
        else:
            g_kind = "none"
        for k, h in enumerate(hits):
            o = {"imp": imp, "group": None, "ev": ev}
            if fl[k] and g_kind == "anyof":
                o["group"] = gid
            elif fl[k] and g_kind == "alt" and or_generic(seg_low, h):
                o["imp"] = "pref"
            if GROWTH_BEFORE.search(_u16_before(seg_low, h["at"], 60)):
                continue
            if o["imp"] != "pref" and INTEREST_BEFORE.search(_u16_before(seg_low, h["at"], 60)):
                o["imp"] = "pref"
            if o["imp"] != "pref" and cert_soft and I.skill[h["id"]]["kind"] == "cert":
                o["imp"] = "pref"
            if h["id"] not in occ:
                occ[h["id"]] = []
                order.append(h["id"])
            occ[h["id"]].append(o)
    by_skill = {}
    for sid in order:
        os_ = occ[sid]

        def f(pred):
            for o in os_:
                if pred(o):
                    return o
            return None
        pick = f(lambda o: o["imp"] == "req!" and not o["group"])
        if pick:
            required = True
        else:
            pick = f(lambda o: o["imp"] == "req!" and o["group"])
            if pick:
                required = True
            else:
                pick = f(lambda o: o["imp"] == "pref")
                if pick:
                    required = False
                else:
                    pick = f(lambda o: o["imp"] == "req" and not o["group"])
                    if pick:
                        required = True
                    else:
                        pick = os_[0]
                        required = True
        implied = pick["imp"] == "req" and has_explicit
        if implied:
            required = False
        by_skill[sid] = {"id": sid, "required": required, "implied": implied, "group": pick["group"], "evidence": pick["ev"], "from": "posting"}
    g_count = {}
    for sid in order:
        g = by_skill[sid]["group"]
        if g and I.skill[sid]["kind"] != "soft":
            g_count[g] = g_count.get(g, 0) + 1
    for sid in order:
        b = by_skill[sid]
        if b["group"] and g_count.get(b["group"], 0) < 2:
            b["group"] = None
            b["required"] = False
    # the title itself is a requirement source ("Python Developer"). Skills the title offers as
    # alternatives ("Ruby or Python Developer", "Python/Go Engineer") are ONE either-or
    # requirement - unless the posting itself requires each of them separately
    th = find_skills(n["title"])
    th_ids = uniq([x["id"] for x in th if I.skill[x["id"]]["kind"] != "soft"])
    t_low = lc(n["title"])
    title_group = None
    if len(th_ids) >= 2:
        or_word = re.search(r"(?<![a-z])(or|and/or)(?![a-z])", t_low) is not None
        slash = re.search(r"[a-z0-9+#)]\s*/\s*[a-z(]", t_low) is not None
        each_req = all((sid in by_skill) and by_skill[sid]["required"] and not by_skill[sid]["group"] for sid in th_ids)
        if or_word or (slash and not each_req):
            dg = [by_skill[sid]["group"] for sid in th_ids if sid in by_skill and by_skill[sid]["group"]]
            title_group = dg[0] if dg else "title"
    # ...but the posting has the last word: "logistics knowledge is a plus" stays a plus, and a business
    # domain in the title's qualifier ("Data Science Intern - Credit Risk") names the team, not the core skill
    t_main = title_main(n["title"])
    for x in th:
        grp = title_group if (title_group and x["id"] in th_ids) else None
        b = by_skill.get(x["id"])
        if b and not b["required"] and not b["implied"]:
            continue
        only_qual = all(y["id"] != x["id"] for y in find_skills(t_main))
        if only_qual and not (b and b["required"]) and (I.skill[x["id"]].get("domain") or I.skill[x["id"]]["kind"] == "cert" or QUAL_SOFT.search(lc(_s(n["title"])[len(t_main):]))):
            if not b:
                by_skill[x["id"]] = {"id": x["id"], "required": False, "implied": False, "group": None, "evidence": "In the job title: " + n["title"], "from": "title"}
                order.append(x["id"])
            continue
        if not b:
            by_skill[x["id"]] = {"id": x["id"], "required": True, "implied": False, "group": grp, "evidence": "In the job title: " + n["title"], "from": "title"}
            order.append(x["id"])
        else:
            b["required"] = True
            b["implied"] = False
            b["group"] = grp
    for tag in n["tags"]:
        for x in find_skills(tag):
            if x["id"] not in by_skill:
                by_skill[x["id"]] = {"id": x["id"], "required": True, "implied": False, "group": None, "evidence": "Listed as a key skill: " + tag, "from": "tag"}
                order.append(x["id"])
    skills, soft = [], []
    for sid in order:
        sk, b = I.skill[sid], by_skill[sid]
        if sk["kind"] == "soft":
            soft.append(sk["name"])
            continue
        skills.append({"id": sid, "name": sk["name"], "kind": sk["kind"], "family": sk.get("family") or None, "required": b["required"],
                       "implied": bool(b["implied"]), "group": b["group"], "evidence": b["evidence"], "from": b["from"]})
    skills.sort(key=lambda s: 0 if s["required"] else 1)
    years = parse_years(segs)
    tl = title_level(n["title"])
    level, level_source = tl, ("title" if tl is not None else None)
    # "Associate HR Business Partner ... 3+ years": a junior-sounding title doesn't beat the posting's own years floor
    if tl is not None and tl <= 1 and years and not years["pref"] and years["min"] >= 3:
        lfy = level_from_years(years["min"])
        if lfy > tl:
            level, level_source = lfy, "years"
    if level is None and years and not years["pref"]:
        level, level_source = level_from_years(years["min"]), "years"
    if level is None and n["type"] == "internship":
        level, level_source = 0, "type"
    et = parse_employment_type(n, segs)
    if level is None and et["type"] == "internship":
        level, level_source = 0, "type"
    if level is None:
        for g in segs:
            if g["section"] != "about" and NEWGRAD_RE.search(g["low"]):
                level, level_source = 1, "description"
                break
    salary = parse_salary(n, segs)
    # no level stated anywhere: modest pay is the clearest remaining signal
    if level is None and salary["source"] is not None and salary["source"] != "estimated" and salary["annualMax"] is not None and \
            ((salary["max"] <= 30) if salary["period"] == "hour" else (salary["annualMax"] <= 52000)):
        level, level_source = 1, "pay"
    mode_info = parse_mode(n["location"], segs)
    places = parse_places(n["location"])
    if mode_info["mode"] is None and places:
        mode_info["mode"], mode_info["source"] = "onsite", "inferred"
    # the role is what the title's main part names: "Inside Sales AE - Logistics Software" is a sales job
    roles = find_roles(t_main)
    if not roles:
        roles = find_roles(n["title"])
    if not roles:
        roles = head_noun_roles(t_main, segs)
    if not roles:
        intro = " ".join([g["low"] for g in segs if g["section"] != "about" and HIRE_CUE.search(g["low"])][:2])
        roles = [dict(r, fromDescription=True) for r in find_roles(intro)[:1]]
    job = {
        "id": n["id"], "title": n["title"], "org": n["org"], "type": n["type"], "location": n["location"], "description": n["description"],
        "applyUrl": n["applyUrl"], "source": n["source"], "deadline": n["deadline"], "tags": n["tags"],
        "postedAt": n["postedAt"], "firstSeenAt": n["firstSeenAt"], "lastSeenAt": n["lastSeenAt"], "seenCount": n["seenCount"], "repostCount": n["repostCount"],
        "roles": roles,
        "skills": skills, "soft": uniq(soft), "orm": orm_finish(orm_acc, has_explicit),
        "yearsMin": years["min"] if years else None, "yearsMax": years["max"] if years else None,
        "yearsText": years["text"] if years else "", "yearsPreferred": years["pref"] if years else False, "yearsAlt": years["alt"] if (years and years.get("alt")) else None,
        "level": level, "levelSource": level_source, "levelLabel": level_label(level),
        "education": parse_education(segs),
        "mode": mode_info["mode"], "modeSource": mode_info["source"], "remoteRegion": mode_info["region"], "places": places,
        "employmentType": et["type"], "employmentTypeSource": et["source"],
        "auth": parse_auth(segs),
        "salary": salary,
        "mgmt": parse_mgmt(segs),
        "enroll": parse_enroll(segs, n["title"]),
        "remoteLimit": parse_remote_limit(segs, n["location"]),
        "license": parse_license(segs),
        "travel": parse_travel(segs),
        "industries": parse_industries(n, segs),
        "agency": parse_agency(n, segs),
        "evergreen": parse_evergreen(n, segs),
        "richness": {"descChars": _js_len(re.sub(r"\s+", " ", n["description"]).strip()), "segments": len(segs), "sectioned": any(g["section"] != "none" for g in segs)},
    }
    job["canonicalKey"] = canonical_key(job)
    return job


# ----------------------------------------------------------- candidate side
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
SEASONS = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}


def _utc_ym(now_ms):
    d = datetime.utcfromtimestamp(math.floor(now_ms) / 1000.0) if now_ms is not None else datetime.utcfromtimestamp(0)
    return d.year, d.month


def parse_month(s, now_ms):
    t = re.sub(r"^(expected|anticipated|est\.?|exp\.?|graduating|graduation|class of)\s*:?\s*", "", lc(s).strip(), count=1)
    if not t:
        return None
    if re.match(r"^(present|current|now|today|ongoing)", t):
        y, mo = _utc_ym(now_ms)
        return y * 12 + mo
    m = re.match(r"^([0-9]{4})-([0-9]{1,2})", t)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    m = re.match(r"^([0-9]{1,2})/([0-9]{4})", t)
    if m:
        return int(m.group(2)) * 12 + int(m.group(1))
    m = re.match(r"^([a-z]+)\.?\s*'?([0-9]{4}|[0-9]{2})", t)
    if m:
        y = int(m.group(2))
        if y < 100:
            y += 2000
        key = "sept" if m.group(1)[:4] == "sept" else m.group(1)[:3]
        if key in MONTHS:
            return y * 12 + MONTHS[key]
        if m.group(1) in SEASONS:
            return y * 12 + SEASONS[m.group(1)]
        return None
    m = re.match(r"^([0-9]{4})$", t)
    if m:
        return int(m.group(1)) * 12 + 1
    return None


EDU_ENTRY = [
    (4, re.compile(r"(?<![a-z])(ph\.?d|doctor of|doctorate)(?![a-z])")),
    (3, re.compile(r"(?<![a-z])(master|m\.s\.|m\.a\.|ms in|ma in|mba|m\.eng|meng|mph|msc|m\.ed|msn|msw|mfa|m\.f\.a)(?![a-z])")),
    (2, re.compile(r"(?<![a-z])(bachelor|b\.s\.|b\.a\.|bs in|ba in|bs,|ba,|b\.eng|bsc|bba|bfa|b\.f\.a|bsn|undergraduate|b\.s|b\.a)(?![a-z])")),
    (1, re.compile(r"(?<![a-z])(associate of|associate's|associate degree|a\.a\.|a\.s\.)(?![a-z])")),
    (0, re.compile(r"(?<![a-z])(high school|ged|diploma)(?![a-z])")),
]


EDU_TITLE_SHORT = [(3, re.compile(r"^(ms|ma|msc|mfa|meng|mph)\s+[a-z]")), (2, re.compile(r"^(bs|ba|bsc|bfa|bba|beng)\s+[a-z]"))]


def edu_level_of(text, title=""):
    t = lc(text)
    for lv, rx in EDU_ENTRY:
        if rx.search(t):
            return lv
    tt = lc(title).strip()
    for lv, rx in EDU_TITLE_SHORT:
        if rx.search(tt):
            return lv
    return None


def exact_skill(item, ctx_low=None):
    t = lc(item).strip()
    if not t or _js_len(t) > 30:
        return None
    # "list" names only count as a skill when typed alone in a skills list ("analytics")
    found = [sk for sk in TAX["skills"] if any(lc(c) == t for c in (sk.get("cs") or []) + (sk.get("list") or []))]
    if not found:
        return None
    # "DBT" alone in a list of therapies is the therapy, in a list of data tools the data tool
    if len(found) > 1 and ctx_low:
        for sk in found:
            if any(c != t and has_word(ctx_low, c) for c in (sk.get("ctx") or [])):
                return sk["id"]
    return found[0]["id"]


def resume_industries(text):
    low = lc(text)
    return [d["id"] for d in TAX["industries"] if any(has_word(low, k) for k in d["keywords"])]


GOAL_NEG = re.compile(r"(?<![a-z])((do not|don't|dont|not|never|no longer|won't|will not)\s+(want|interested|looking|pursue|pursuing|considering|consider|going back|go back|return)|away from|anything but|rather than|instead of|avoid|avoiding|steer clear of|stay away from|no more|not another)(?![a-z])")
GOAL_PIVOT = re.compile(r"(?<![a-z])(but|so|instead|rather|i want|i'd like|i would like|i'm looking|i am looking|looking for|hoping|hope to|aiming|aim to|moving (in)?to|move (in)?to|transition(ing)? (in)?to|switch(ing)? (in)?to|pivot(ing)? (in)?to|focus(ing)? on|ideally|prefer|more like|something like|more of)(?![a-z])")
GOAL_FROM = re.compile(r"(?<![a-z])(from|out of|leave|leaving|after|beyond)\s+([a-z0-9 &/,'-]{2,60}?)\s+(to|into|toward|towards|for)(?![a-z])")


GOAL_REL = re.compile(r"\s(who|that|which|where|whose)\s")


def goal_roles(text):
    low = lc(text)
    frm = GOAL_FROM.search(low)
    roles = find_roles(text)
    # "a clinical nurse educator who trains new nurses": roles named after "who" are the work, not the goal
    rel = GOAL_REL.search(low)
    if rel and len(roles) > 1:
        I0 = idx()
        first_at = {}
        for m0 in I0.role_re.finditer(low):
            rid0 = I0.role_map[m0.group(1)]
            if rid0 not in first_at:
                first_at[rid0] = m0.start()
        before = [r for r in roles if first_at.get(r["id"]) is not None and first_at[r["id"]] < rel.start()]
        if before:
            roles = before
    # a role the goal rules out ("I do not want a quota-carrying sales role", "away from sales") is no target
    I1 = idx()
    negd, pos = {}, {}
    for m1 in I1.role_re.finditer(low):
        rid1 = I1.role_map[m1.group(1)]
        p1 = m1.start()
        cs1 = max(low.rfind(".", 0, p1 + 1), low.rfind(";", 0, p1 + 1), low.rfind("!", 0, p1 + 1), low.rfind("?", 0, p1 + 1)) + 1
        w1 = p1 - len(_u16_before(low, p1, 200))
        win1 = low[max(cs1, w1):p1]
        neg_end = -1
        for mn in GOAL_NEG.finditer(win1):
            neg_end = mn.end()
        if neg_end >= 0 and not GOAL_PIVOT.search(win1[neg_end:]):
            negd[rid1] = True
        else:
            pos[rid1] = True
    kept_n = [r for r in roles if not (negd.get(r["id"]) and not pos.get(r["id"]))]
    if kept_n:
        roles = kept_n
    if not frm:
        return roles
    fs, fe = frm.start(), frm.end()
    I = idx()
    in_from = {}
    for m in I.role_re.finditer(low):
        rid = I.role_map[m.group(1)]
        if m.start() >= fs and m.start() + len(m.group(1)) <= fe:
            in_from[rid] = in_from.get(rid, 0) + 1
        else:
            in_from[rid] = -999
    kept = [r for r in roles if not (in_from.get(r["id"], 0) > 0)]
    return kept if kept else roles


def split_skill_list(s):
    return [x.strip() for x in re.split(r"[,;\n|]+", _s(s)) if x.strip()]


def low_prior(level):
    return 2 if level == "proven" else (1 if level == "stated" else 0)


# a credential's status: one that lapsed is not held (it covers its whole certification entry); one you're
# still working toward ("eligible to sit for the PE exam", "CPA - in progress") counts for nothing on that line
CRED_LAPSED = re.compile(r"(?<![a-z])(lapsed|expired|inactive|not active|no longer active|did not (renew|recertify)|not renewed|not current)(?![a-z])")
CRED_FUTURE = re.compile(r"(?<![a-z])(in progress|pending|application submitted|applied for|applying for|awaiting|not (yet )?issued|under review|in process|planning to (sit|take|test)|scheduled to (sit|take|test)|preparing for|studying for|candidates?|candidacy|eligible to (sit|take|test)|eligible for (the )?(exam|licensure|license|certification)|not (yet )?(a )?licensed|not yet (certified|licensed|earned)|(will|to) (sit|test) for|exam scheduled|working toward|working towards|in pursuit of|passed [0-9]+ (of|out of) [0-9]+|[0-9]+ (of|out of) [0-9]+ (sections|parts|exams)|sections? (passed|remaining|left))(?![a-z])")
# a license still being applied for: its state is not yours yet
CRED_PENDING = re.compile(r"(?<![a-z])(pending|application submitted|applied for|applying for|awaiting|not (yet )?issued|under review|in process|in progress)(?![a-z])")
# "CPA Exam", "PE exam": an exam on the way to a license is not the license
CRED_EXAM_AFTER = re.compile(r"^[\s-]*(exam|examination|candidate|candidates|review|course|prep|eligible|eligibility|track)(?![a-z])")
BOARD_STATE = re.compile(r"^(?:the\s+)?([a-z]+(?: [a-z]+)?)(?: state)? (board|committee|department|division|commission|bureau|office)(?![a-z])")


ACTION_VERB = re.compile(r"(?<![a-z])(built|build|building|developed|develop|created|create|analy[sz]ed|analy[sz]ing|led|lead|managed|manage|designed|implemented|ran|run|used|using|wrote|write|automated|improved|delivered|launched|reduced|increased|migrated|maintained|deployed|trained|presented|conducted|owned|shipped|optimi[sz]ed|modeled|modelled|reported|tested|supported|coordinated|wrote|taught|cared|administered|prepared|reconciled|audited|negotiated|sold|closed|grew|drove|partnered|collaborated|mentored|supervised|handled|processed|tracked|monitored|researched|programmed|coded|configured|integrated|refactored|scaled|debugged|resolved|served|assisted|helped|organized|planned)(?![a-z])")
PART_TIME = re.compile(r"(?<![a-z])(part[- ]time|teaching assistant|graduate assistant|student (worker|assistant|employee|ambassador)|work[- ]study|resident assistant|peer tutor|undergraduate (researcher|research assistant|assistant))(?![a-z])")
MGMT_DONE = re.compile(r"(?<![a-z])((managed|led|supervised|oversaw|ran|built and led|hired and managed|hired and led) (a |an |the )?(team|staff|crew|group|squad|unit)( of)?|(managed|oversaw|ran|headed|supervised) (a |an |the )?([a-z&-]+ ){0,2}department|(manage|managed|managing|supervise|supervised|supervising|oversee|oversaw|overseeing|lead|led|leading) (a team of |teams of |a staff of )?[0-9]+(\s*-\s*[0-9]+)?\+? (people|engineers|employees|staff|reports|analysts|nurses|designers|associates|auditors|accountants|technicians|agents|representatives|reps|apprentices|electricians|developers|teachers|specialists|coordinators)|[0-9]+ direct reports|direct reports|people manager|people management)(?![a-z])")
PEOPLE_MGR_TITLE = re.compile(r"(?<![a-z])(manager|supervisor|director|head of|team lead|team leader|charge nurse|nurse manager|store manager|general manager|superintendent|foreman|vp|vice president|chief)(?![a-z])")
NOT_PEOPLE_MGR = re.compile(r"(?<![a-z])(product|project|program|account|marketing|social media|content|community|office|case|property|portfolio|brand|campaign|category|relationship|customer success|success|partner|channel|release|delivery|data|database|configuration|change) manager(?![a-z])")
LEADERSHIP_TITLE = re.compile(r"(?<![a-z])(manager|supervisor|director|head of|lead|leader|superintendent|foreman|owner|principal)(?![a-z])")
# words any title can carry - sharing one with your goal says nothing about the kind of job
TITLE_GENERIC = ["senior", "junior", "lead", "principal", "staff", "associate", "assistant", "intern", "internship", "interns", "trainee", "apprentice", "entry", "corporate", "global", "regional", "remote", "hybrid", "onsite", "on-site", "part-time", "full-time", "part", "time", "full", "contract", "temporary", "seasonal", "new", "grad", "graduate", "engineering", "engineer", "specialist", "coordinator", "officer", "representative", "professional", "team", "member", "program", "services", "service", "day", "night", "shift", "weekend"]
GOAL_STOP = ["the", "and", "for", "with", "into", "from", "that", "this", "want", "break", "become", "get", "job", "role", "work", "working", "company", "companies", "career", "eventually", "someday", "like", "some", "kind", "field", "industry", "position", "something", "where", "can", "about", "their", "them", "more", "less", "really", "very", "good", "great", "top", "best", "my", "our", "your", "who", "what", "which", "also", "focused", "driven", "based", "level", "entry", "senior", "junior", "year", "years", "next"]


CITIZEN_TXT = re.compile(r"(?<![a-z])(u\.?\s?s\.? citizen|united states citizen|american citizen)(?![a-z])")
NOT_CITIZEN_BEFORE = re.compile(r"(not|non|no|without|pending|applying for|eligible for|seeking|future)[\s-]*(a\s+|an\s+)?\Z")
CONTRACT_TITLE = re.compile(r"(?<![a-z])(contract|contractor|contract-to-hire|temporary|temp|freelance|freelancer|self-employed|independent consultant|per diem|prn|seasonal|locum|locums|travel nurse|traveling nurse)(?![a-z])")
CONTRACT_DESC = re.compile(r"(?<![a-z])(contract (role|position|assignment|basis|engagement)|on contract|as a contractor|freelance|self-employed|temporary (role|position|assignment)|temp (role|assignment)|per diem)(?![a-z])")


def _span(lst):
    tot, cs, ce = 0, None, None
    for x in lst:
        if cs is None:
            cs, ce = x["s"], x["e"]
        elif x["s"] <= ce + 1:
            if x["e"] > ce:
                ce = x["e"]
        else:
            tot += ce - cs + 1
            cs, ce = x["s"], x["e"]
    if cs is not None:
        tot += ce - cs + 1
    return tot


def build_candidate(profile, entries, prefs, now_ms):
    I = idx()
    profile = profile if isinstance(profile, dict) else {}
    entries = entries if isinstance(entries, list) else []
    prefs = prefs if isinstance(prefs, dict) else {}
    skills, custom = {}, []

    def add_skill(sid, level, evidence, source, via=None):
        cur = skills.get(sid)
        if not cur or low_prior(level) > low_prior(cur["level"]):
            skills[sid] = {"id": sid, "name": I.skill[sid]["name"], "level": level, "evidence": evidence, "source": source, "via": via or None}

    extra = prefs.get("extraSkills") or []
    skill_text = _s(profile.get("skills")) + ((", " + ", ".join(_s(x) for x in extra)) if extra else "")
    for item in split_skill_list(skill_text):
        hits = find_skills(item)
        if not hits:
            ex = exact_skill(item, lc(skill_text))
            if ex:
                hits = [{"id": ex}]
        if not hits:
            if 2 <= _js_len(item) <= 40:
                custom.append(item)
            continue
        not_held = CRED_LAPSED.search(lc(item)) is not None or CRED_FUTURE.search(lc(item)) is not None
        for h in hits:
            if not_held and I.skill[h["id"]]["kind"] == "cert":
                continue
            if I.skill[h["id"]].get("license") and h.get("end") is not None and CRED_EXAM_AFTER.search(_u16_after(lc(item), h["end"], 24)):
                continue
            add_skill(h["id"], "stated", 'Listed in your skills: "' + trunc(item, 60) + '"', "skills")
    work_months, held_titles, jobs_held, edu, inds, ind_order = [], [], [], None, {}, []
    orm_units = [{"text": skill_text, "proven": False}]
    # "U.S. citizen" written in the profile (and not "not a U.S. citizen")
    citizen_txt = False
    for tx in [skill_text, _s(profile.get("northstar")), _s(profile.get("finalidea") or profile.get("final_idea"))] + [(_s(e.get("title")) + " " + _s(e.get("raw_description") or e.get("description") or e.get("bullets") or "")) if isinstance(e, dict) else "" for e in entries]:
        lt = lc(tx)
        for cm2 in CITIZEN_TXT.finditer(lt):
            if not NOT_CITIZEN_BEFORE.search(_u16_before(lt, cm2.start(), 24)):
                citizen_txt = True
    permanent_now = False
    school, grad_at, mgmt, lic_states, lic_compact = [], None, None, [], False
    now_m = parse_month("present", now_ms)
    for c in license_states(_s(profile.get("skills"))):
        if c not in lic_states:
            lic_states.append(c)
    if re.search(r"(compact|multistate|multi-state)", lc(profile.get("skills"))) and LIC_WORD.search(lc(profile.get("skills"))):
        lic_compact = True
    # a security clearance you hold, read from your skills and resume (the highest level stated)
    clr, clr_from = 0, ""
    for item in split_skill_list(_s(profile.get("skills"))):
        lv = cand_clearance(item)
        if lv > clr:
            clr, clr_from = lv, 'Listed in your skills: "' + trunc(item, 60) + '"'
    for e in entries:
        if not isinstance(e, dict):
            continue
        et = lc(e.get("entry_type") or e.get("type") or "work")
        title, org = _s(e.get("title")), _s(e.get("org"))
        desc = _s(e.get("raw_description") or e.get("description") or e.get("bullets") or "")
        label = trunc(title + (" @ " + org if org else ""), 60)
        if et == "education":
            el = edu_level_of(title + " " + desc, title)
            end_m = parse_month(e.get("end_date") or e.get("endDate") or "", now_ms)
            start_m = parse_month(e.get("start_date") or e.get("startDate") or "", now_ms)
            if el is not None:
                in_prog = re.search(r"expected|candidate|in progress|anticipated|pursuing", lc(title + " " + desc + " " + _s(e.get("end_date")))) is not None or (end_m is not None and end_m > now_m)
                if not edu:
                    edu = {"level": None, "inProgress": None, "text": ""}
                if in_prog:
                    if edu["inProgress"] is None or el > edu["inProgress"]:
                        edu["inProgress"] = el
                elif edu["level"] is None or el > edu["level"]:
                    edu["level"] = el
                    edu["text"] = trunc(title, 60)
                if not edu["text"]:
                    edu["text"] = trunc(title, 60)
                if end_m is not None and (grad_at is None or end_m > grad_at):
                    grad_at = end_m
                # jobs held while studying for a first degree were (almost always) part-time
                if el <= 2 and start_m is not None and end_m is not None:
                    school.append({"s": start_m, "e": end_m})
        orm_units.append({"text": title + " \n " + org + " \n " + desc, "proven": et in ("work", "job", "experience", "internship", "volunteer", "project")})
        cred_entry = re.search(r"cert|licen|credential", et) is not None
        entry_lapsed = cred_entry and CRED_LAPSED.search(lc(title + " " + desc)) is not None
        entry_future = cred_entry and CRED_PENDING.search(lc(title + " " + desc)) is not None
        if cred_entry and not entry_lapsed and not entry_future and LIC_WORD.search(lc(title)):
            bm = BOARD_STATE.search(lc(org))
            if bm and I.state_by_name.get(bm.group(1)) and I.state_by_name[bm.group(1)] not in lic_states:
                lic_states.append(I.state_by_name[bm.group(1)])
        for g in segments(title + "\n" + desc):
            # a bare keyword list pasted into an entry isn't proof of use
            dump = et != "education" and len(re.split(r"[,;|/]", g["text"])) >= 4 and not ACTION_VERB.search(g["low"])
            line_not_held = entry_lapsed or CRED_LAPSED.search(g["low"]) is not None or CRED_FUTURE.search(g["low"]) is not None
            for h in find_skills(g["text"]):
                if I.skill[h["id"]]["kind"] == "soft":
                    continue
                if line_not_held and I.skill[h["id"]]["kind"] == "cert":
                    continue
                if I.skill[h["id"]].get("license") and CRED_EXAM_AFTER.search(_u16_after(g["low"], h["end"], 24)):
                    continue
                if et == "education":
                    add_skill(h["id"], "stated", 'From your education: "' + trunc(g["text"], 110) + '"', label)
                elif dump:
                    add_skill(h["id"], "stated", 'Listed in your resume (not shown in use): "' + trunc(g["text"], 100) + '"', label)
                else:
                    add_skill(h["id"], "proven", trunc(g["text"], 140), label)
            if not mgmt and et != "education" and MGMT_DONE.search(g["low"]):
                mgmt = {"source": trunc(g["text"], 120)}
            if not entry_lapsed and not entry_future and not CRED_PENDING.search(g["low"]):
                for c in license_states(g["text"]):
                    if c not in lic_states:
                        lic_states.append(c)
            if re.search(r"(compact|multistate|multi-state)", g["low"]) and LIC_WORD.search(g["low"]):
                lic_compact = True
            clv = cand_clearance(g["text"])
            if clv > clr:
                clr, clr_from = clv, trunc(g["text"], 100)
        if et in ("work", "job", "experience", "internship", "volunteer"):
            for d in resume_industries(org + " \n " + title + " \n " + desc):
                if d not in inds:
                    inds[d] = label
                    ind_order.append(d)
            s_m = parse_month(e.get("start_date") or e.get("startDate") or "", now_ms)
            e_m = parse_month(e.get("end_date") or e.get("endDate") or "", now_ms)
            if s_m is not None and e_m is None:
                e_m = now_m   # a start date and no end date: the job you're in now
            half = LV_INTERN.search(lc(title)) or et == "internship" or et == "volunteer" or PART_TIME.search(lc(title + " " + desc))
            if s_m is not None and e_m is not None and e_m >= s_m:
                work_months.append({"s": s_m, "e": e_m, "w": 0.5 if half else 1, "t": title})
            if title:
                held_titles.append(title)
            if title and et in ("work", "job", "experience"):
                jobs_held.append({"t": title, "s": s_m, "e": e_m})
            # the job you're in now is a permanent one (not a contract, temp, freelance or part-time job)
            if et in ("work", "job", "experience") and s_m is not None and e_m is not None and e_m >= now_m and not half and not CONTRACT_TITLE.search(lc(title)) and not CONTRACT_DESC.search(lc(desc)):
                permanent_now = True
            if not mgmt and et != "internship" and PEOPLE_MGR_TITLE.search(lc(title)) and not NOT_PEOPLE_MGR.search(lc(title)):
                mgmt = {"source": 'your title "' + trunc(title, 40) + '"'}
    for x in work_months:
        if x["w"] == 1 and any(x["s"] >= sc["s"] and x["e"] <= sc["e"] + 1 for sc in school):
            x["w"] = 0.5
    for sid in sorted(skills.keys()):
        sk, c = I.skill[sid], skills[sid]
        for t in sk.get("implies") or []:
            if t not in skills or low_prior(c["level"]) > low_prior(skills[t]["level"]):
                skills[t] = {"id": t, "name": I.skill[t]["name"], "level": c["level"], "evidence": c["evidence"], "source": c["source"], "via": sk["name"]}
    years, years_source = None, None
    if isnum(prefs.get("years")):
        years, years_source = prefs["years"], "you set it"
    elif work_months:
        work_months.sort(key=lambda x: (x["s"], x["e"]))
        full = [x for x in work_months if x["w"] == 1]
        half = [x for x in work_months if x["w"] != 1]
        months = _span(full) + _span(half) * 0.5
        years, years_source = round1(months / 12), "from your resume dates"
    elif profile.get("stage") in ("student", "grad"):
        years, years_source = 0, "from your stage (" + profile.get("stage") + ")"
    level, level_source = None, None
    st = profile.get("stage") or ""
    if st == "student":
        level, level_source = 0.5, "student"
    elif st == "grad":
        level, level_source = 1, "recent graduate"
    elif st == "switch":
        level, level_source = (1.5 if years is not None and years >= 3 else 1), "career switcher"
        # someone who has run teams elsewhere doesn't start over as a coordinator
        if years is not None and years >= 3 and any(LEADERSHIP_TITLE.search(lc(t)) for t in held_titles):
            level, level_source = (3 if years >= 8 else 2), "career switcher with leadership experience"
    elif st == "working":
        level = level_from_years(years) if years is not None else 2
        level_source = "years of experience" if years is not None else "working professional"
    elif years is not None:
        level, level_source = level_from_years(years), "years of experience"
    roles = []
    explicit = [r for r in (prefs.get("targetRoles") or []) if isinstance(r, str) and r in I.role]
    for r in explicit:
        roles.append({"id": r, "name": I.role[r]["name"], "from": "you chose it"})
    goal_text = _s(profile.get("northstar")) + " " + _s(profile.get("finalidea") or profile.get("final_idea"))
    if not roles:
        for r in goal_roles(goal_text):
            roles.append({"id": r["id"], "name": r["name"], "from": "your goal"})
    if level is not None and st == "working":
        # What you're titled NOW says more than a count of years. An older, more junior
        # title ("Audit Associate" four years ago) never pulls you down; it can only lift you.
        def _related(t):
            tr = find_roles(t)
            return (not roles) or any(any(role_sim(x["id"], y["id"]) >= 0.6 for y in roles) for x in tr)

        def _key(j):
            return (j["e"] if j["e"] is not None else -1, j["s"] if j["s"] is not None else -1)
        cur = None
        for j in jobs_held:
            if cur is None or _key(j) > _key(cur):
                cur = j
        cur_tl = title_level(cur["t"]) if cur else None
        if cur and cur_tl is not None and cur_tl != 0 and _related(cur["t"]):
            if cur_tl < level - 1:
                level, level_source = level - 1, 'your title "' + trunc(cur["t"], 40) + '" and your years'
            else:
                level, level_source = cur_tl, 'your title "' + trunc(cur["t"], 40) + '"'
        else:
            best, best_t = None, ""
            for t in held_titles:
                tl = title_level(t)
                if tl is None or tl == 0 or not _related(t):
                    continue
                if best is None or tl > best:
                    best, best_t = tl, t
            if best is not None and best > level:
                level, level_source = best, 'your title "' + trunc(best_t, 40) + '"'
    # the years you'd bring to the work you're aiming at - jobs in your target field or a close one - so years
    # waiting tables don't make an SDR "overqualified" for an AE role
    rel_years = None
    if years is not None and years_source == "from your resume dates" and roles:
        rel_w = [x for x in work_months if x.get("t") and any(any(role_sim(r["id"], y["id"]) >= 0.45 for y in roles) for r in find_roles(x["t"]))]
        rel_years = round1((_span([x for x in rel_w if x["w"] == 1]) + _span([x for x in rel_w if x["w"] != 1]) * 0.5) / 12)
    if isnum(prefs.get("level")):
        level, level_source = clamp(prefs["level"], 0, 6), "you set it"
    if prefs.get("education") is not None and isnum(prefs.get("education")):
        edu = {"level": prefs["education"], "inProgress": None, "text": "you set it"}
    if not edu:
        if st == "student":
            edu = {"level": 0, "inProgress": 2, "text": "assumed from student stage", "assumed": True}
        elif st == "grad":
            edu = {"level": 2, "inProgress": None, "text": "assumed from recent-graduate stage", "assumed": True}
    loc_src = prefs.get("locations") if (prefs.get("locations") is not None and _s(prefs.get("locations")).strip()) else profile.get("loc")
    loc = parse_user_location(loc_src)
    goal_tokens = uniq([w for w in re.findall(r"[a-z][a-z+#.-]{2,}", lc(goal_text)) if w not in GOAL_STOP])
    # the level your goal names, when it's above where you are now ("Senior Accountant", "a staff engineer")
    goal_level = None
    g_north = _s(profile.get("northstar"))
    g_fm = GOAL_FROM.search(lc(g_north))
    g_target = lc(_s(profile.get("finalidea") or profile.get("final_idea")).strip(_JS_WS) or (g_north[g_fm.end():] if g_fm else g_north))
    gl = 5 if re.search(r"(?<![a-z])(director|head of|vp|vice president)(?![a-z])", g_target) else (4 if re.search(r"(?<![a-z])(principal|staff)\s+[a-z]", g_target) else (3 if re.search(r"(?<![a-z])(senior|sr\.?)(?![a-z])", g_target) else None))
    if gl is not None and level is not None and gl > level and gl - level <= 1.5:
        goal_level = gl
    # the Filters switch "I hold an active security clearance" (no level given) meets any requirement
    if prefs.get("clearance") and clr < 4:
        clr, clr_from = 4, "you said you hold an active clearance"
    return {
        "skills": skills, "customSkills": custom[:20],
        "years": years, "yearsSource": years_source, "relatedYears": rel_years,
        "level": level, "levelSource": level_source, "levelLabel": level_label(level), "goalLevel": goal_level,
        "education": edu,
        "roles": roles, "goalText": goal_text.strip(), "goalTokens": goal_tokens,
        "industries": [{"id": d, "name": I.ind[d]["name"], "from": inds[d]} for d in ind_order],
        "location": loc,
        "needsSponsorship": bool(prefs.get("needsSponsorship")),
        "citizen": True if prefs.get("citizen") is True else (False if (prefs.get("citizen") is False or prefs.get("needsSponsorship")) else (True if citizen_txt else None)),
        "permanentResident": bool(prefs.get("permanentResident")) and not prefs.get("needsSponsorship"),
        "clearance": clr > 0, "clearanceLevel": clr, "clearanceFrom": clr_from,
        "mgmt": mgmt,
        "licenseStates": lic_states, "licenseCompact": lic_compact,
        "permanentNow": permanent_now,
        "orm": orm_candidate(orm_units),
        "stage": st,
        "enrolled": True if st == "student" else (True if (edu and edu.get("inProgress") is not None) else (False if (st in ("grad", "working", "switch") or (edu and edu.get("level") is not None)) else None)),
        "gradAt": grad_at,
        "provenCount": sum(1 for k in skills if skills[k]["level"] == "proven"),
        "statedCount": sum(1 for k in skills if skills[k]["level"] == "stated"),
    }


def parse_user_location(raw):
    s = lc(raw).strip()
    res = {"metros": [], "states": [], "remoteOk": False, "remoteOnly": False, "anywhere": False, "raw": _s(raw).strip()}
    if not s:
        return res
    if re.search(r"(?<![a-z])(remote|work from home|wfh)(?![a-z])", s):
        res["remoteOk"] = True
    if re.search(r"(?<![a-z])(anywhere|any location|open to relocat|willing to relocate|flexible)(?![a-z])", s):
        res["anywhere"] = True
    for p in parse_places(s):
        if p["metro"] and p["metro"] not in res["metros"]:
            res["metros"].append(p["metro"])
        if p["state"] and p["state"] not in res["states"]:
            res["states"].append(p["state"])
    res["remoteOnly"] = res["remoteOk"] and not res["metros"] and not res["states"] and not res["anywhere"]
    return res


# ------------------------------------------------------------------ scoring
def interp(x, knots):
    if x <= knots[0][0]:
        return knots[0][1]
    for i in range(1, len(knots)):
        if x <= knots[i][0]:
            a, b = knots[i - 1], knots[i]
            return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
    return knots[-1][1]


YEARS_KNOTS = [(0.5, 100), (1, 85), (2, 60), (3, 40), (5, 20)]


def yrs_have(y):
    """Plain words for experience: internships count half, so a summer
    internship is "under a year", not "0.1"."""
    if y <= 0:
        return "none on record"
    if y < 1:
        return "under a year"
    return "about " + jsnum(y) + (" year" if y == 1 else " years")
LEVEL_KNOTS = [(-3, 45), (-2, 65), (-1, 85), (-0.5, 100), (0.5, 100), (1, 70), (2, 40), (3, 15)]


def role_sim(a, b):
    I = idx()
    if a not in I.role or b not in I.role:
        return 0
    if a == b:
        return 1
    pa, pb = I.role[a].get("parent"), I.role[b].get("parent")
    if pa == b or pb == a:
        return 0.95
    if pa and pa == pb:
        return 0.7
    w = I.adj.get(a + "|" + b)
    if w is not None:
        return w
    w2 = I.adj.get((pa or a) + "|" + (pb or b))
    if w2 is not None:
        return rhu(w2 * 90) / 100
    if I.role[a]["group"] == I.role[b]["group"]:
        return 0.5
    return 0.15


def skill_credit(js, cand):
    I = idx()
    c = cand["skills"].get(js["id"])
    if c:
        return {"credit": 1 if c["level"] == "proven" else 0.85, "how": c["level"], "evidence": c["evidence"], "source": c["source"], "via": c["via"], "match": js["id"]}
    fam_id = js.get("family")
    if fam_id and fam_id in I.family:
        fam, pick = I.family[fam_id], None
        for p in range(2):
            if pick:
                break
            for k in fam:
                if k == js["id"]:
                    continue
                ck = cand["skills"].get(k)
                if ck and (p == 1 or ck["level"] == "proven"):
                    pick = ck
                    break
        if pick:
            return {"credit": 0.45, "how": "adjacent", "evidence": pick["evidence"], "source": pick["source"], "via": pick["name"], "match": pick["id"]}
    for t in I.skill[js["id"]].get("implies") or []:
        ci = cand["skills"].get(t)
        if ci:
            return {"credit": 0.3, "how": "related", "evidence": ci["evidence"], "source": ci["source"], "via": ci["name"], "match": t}
    return {"credit": 0, "how": "missing", "evidence": "", "source": "", "via": None, "match": None}


REGION_NAMES = {"US": "the US", "CA": "Canada", "UK": "the UK", "EU": "Europe / EMEA", "LATAM": "Latin America", "APAC": "Asia-Pacific", "IN": "India"}


def mode_word(m):
    return "on-site" if m == "onsite" else m


def _ci(word):
    """An ASCII word matched case-insensitively the way a JS /i regex does it.
    (Python's re.I also folds unicode look-alikes - 'ſ', the Kelvin sign - so
    we spell the cases out instead.)"""
    return "".join("[" + c.lower() + c.upper() + "]" if ("a" <= c <= "z" or "A" <= c <= "Z") else re.escape(c) for c in word)


_ONSITE_CI = _ci("on") + "-?" + _ci("site")
_CLEANLOC_PAREN = re.compile(r"[(\[]\s*(" + "|".join([_ci("hybrid"), _ci("remote"), _ONSITE_CI, _ci("in-office"), _ci("in office")]) + r")[^)\]]*[)\]]")
_CLEANLOC_WORD = re.compile(r"(?<![A-Za-z])(" + _ci("hybrid") + "|" + _ONSITE_CI + r")(?![A-Za-z])")
_URL_HOST = re.compile("^" + _ci("http") + "[sS]?://([^/?#]+)")


def clean_loc(loc):
    s = _CLEANLOC_PAREN.sub(" ", _s(loc))
    s = _CLEANLOC_WORD.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\s,-]+|[\s,-]+$", "", s)
    return s.strip()


def mode_loc_score(job, cand, prefs):
    modes = prefs.get("modes") if isinstance(prefs.get("modes"), list) else []
    P = cand["location"]
    if job["mode"] is None and not job["places"]:
        return None
    outside = mode_miss = False
    if job["mode"] == "remote":
        if job["remoteRegion"] and cand.get("country") and job["remoteRegion"] != cand.get("country"):
            return {"v": 25, "why": "Remote, but only for candidates in " + (REGION_NAMES.get(job["remoteRegion"]) or job["remoteRegion"]), "outside": True, "modeMiss": False}
        if modes and "remote" not in modes:
            return {"v": 60, "why": "Remote — you said you’d rather work " + " or ".join(mode_word(m) for m in modes), "outside": False, "modeMiss": True}
        return {"v": 100, "why": "Remote" + ((" (" + (REGION_NAMES.get(job["remoteRegion"]) or job["remoteRegion"]) + ")") if job["remoteRegion"] else ""), "outside": False, "modeMiss": False}
    kind = "Hybrid" if job["mode"] == "hybrid" else "On-site"
    place_txt = clean_loc(job["location"]) or " / ".join(p["label"] for p in job["places"])
    if not P["metros"] and not P["states"]:
        if P["remoteOnly"]:
            base = 70 if prefs.get("relocate") else 20
            why = kind + " in " + place_txt + " — you said remote"
            outside = not prefs.get("relocate")
        else:
            base = 85
            why = kind + " in " + place_txt + " (add where you live to check the commute)"
    else:
        in_metro = any(p["metro"] and p["metro"] in P["metros"] for p in job["places"])
        in_state = (not in_metro) and any(p["state"] and p["state"] in P["states"] and not (p["metro"] and P["metros"]) for p in job["places"])
        if in_metro:
            base, why = 100, kind + " in your area (" + place_txt + ")"
        elif in_state:
            base, why = 80, kind + " in your state (" + place_txt + ")"
        elif prefs.get("relocate") or P["anywhere"]:
            base, why = 70, kind + " in " + place_txt + " — you’re open to relocating"
        else:
            base, why, outside = 20, kind + " in " + place_txt + " — outside your area", True
    want = modes if modes else (["remote"] if P["remoteOnly"] else [])
    if want and job["mode"] and job["mode"] not in want:
        mode_miss = True
        cap = 55 if job["mode"] == "hybrid" else 45
        if base > cap:
            base = cap
            why += " — you prefer " + " or ".join(mode_word(m) for m in want)
    return {"v": base, "why": why, "outside": outside, "modeMiss": mode_miss}


# open-vocabulary weights: a posting term counts ORM_TERM_W of a taxonomy skill; its specific words together count
# up to ORM_BETA_MAX skills (one per ORM_BETA_DIV of word weight) once there are at least ORM_VMIN of them
ORM_TERM_W, ORM_BETA_MAX, ORM_BETA_DIV, ORM_VMIN, ORM_THIN, ORM_VREF = 0.4, 2, 6, 3, 3, 0.55
DEFAULT_WEIGHTS = {"skills": 45, "level": 20, "role": 30, "industry": 5}
def cand_states(cand):
    L = cand.get("location")
    out = []
    if not L:
        return out
    for c in L.get("states") or []:
        if c not in out:
            out.append(c)
    for m in L.get("metros") or []:
        me = idx().metro.get(m)
        if me:
            for c in me["states"]:
                if c not in out:
                    out.append(c)
    return out


MON_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def ym_label(ym):
    return MON_NAMES[(ym - 1) % 12] + " " + str((ym - 1) // 12)
EDU_NAMES = ["high school diploma", "associate degree", "bachelor’s degree", "master’s degree", "PhD"]
TYPE_NAMES = {"full_time": "Full-time", "part_time": "Part-time", "contract": "Contract", "internship": "Internship", "temporary": "Temporary"}


def band_of(score):
    if score is None:
        return {"key": "unknown", "label": "Not enough info"}
    if score >= 85:
        return {"key": "excellent", "label": "Excellent match"}
    if score >= 70:
        return {"key": "strong", "label": "Strong match"}
    if score >= 55:
        return {"key": "partial", "label": "Partial match"}
    if score >= 40:
        return {"key": "weak", "label": "Weak match"}
    return {"key": "poor", "label": "Poor match"}


def pay_up_to(job):
    """A job board's own estimate is never stated as what the employer pays."""
    return "Estimated to pay up to $" if job["salary"]["source"] == "estimated" else "Pays up to $"


def fmt_k(v):
    if v is None:
        return "?"
    if v >= 1000:
        out = jsnum(rhu(v / 100) / 10)
        return (out[:-2] if out.endswith(".0") else out) + "k"
    return jsnum(v)


def _w(prefs):
    W = {}
    pw = prefs.get("weights") if isinstance(prefs.get("weights"), dict) else {}
    for k, dflt in DEFAULT_WEIGHTS.items():
        v = pw.get(k) if isnum(pw.get(k)) else dflt
        W[k] = clamp(v, 0, 100)
    return W


def score_job(job, cand, prefs, opts=None):
    I = idx()
    prefs = prefs or {}
    opts = opts or {}
    qr = [r for r in (opts.get("queryRoles") or []) if isinstance(r, str) and r in I.role]
    targets = qr if qr else [r["id"] for r in cand["roles"]]
    W = _w(prefs)
    caps, positives, gaps = [], [], []
    units, unit_by_group, detail = [], {}, []
    for s in job["skills"]:
        c = skill_credit(s, cand)
        d = {"id": s["id"], "name": s["name"], "kind": s["kind"], "required": s["required"], "implied": bool(s.get("implied")), "group": s.get("group") or None,
             "credit": c["credit"], "how": c["how"], "evidence": c["evidence"], "source": c["source"], "via": c["via"], "jobEvidence": s["evidence"]}
        detail.append(d)
        if s.get("group"):
            u = unit_by_group.get(s["group"])
            if not u:
                u = unit_by_group[s["group"]] = {"members": [], "required": False, "credit": 0}
                units.append(u)
            u["members"].append(d)
            if s["required"]:
                u["required"] = True
            if c["credit"] > u["credit"]:
                u["credit"] = c["credit"]
        else:
            units.append({"members": [d], "required": s["required"], "credit": c["credit"]})
    for u in units:
        for d in u["members"]:
            d["unitCredit"] = u["credit"]
            d["alternatives"] = [x["name"] for x in u["members"]] if len(u["members"]) > 1 else None
    req_u = [u for u in units if u["required"]]
    prf_u = [u for u in units if not u["required"]]
    req_sum = 0
    for u in req_u:
        req_sum += u["credit"]
    prf_sum = 0
    for u in prf_u:
        prf_sum += u["credit"]
    cov_req = req_sum / len(req_u) if req_u else None
    cov_pref = prf_sum / len(prf_u) if prf_u else None
    if cov_req is None:
        x = cov_pref
    elif cov_pref is None:
        x = cov_req
    else:
        x = 0.75 * cov_req + 0.25 * cov_pref
    # the posting's own terms (open vocabulary): its codes and product names, and its specific words
    om = job.get("orm") or {"terms": [], "vocab": []}
    co = cand.get("orm") or {"keys": {}, "stems": {}}
    t_req = t_prf = 0
    t_req_n = t_prf_n = 0
    t_hit, t_miss = [], []
    for t in om["terms"]:
        lv = co["keys"].get(t["key"], 0)
        cr = 1 if lv == 2 else (0.85 if lv == 1 else 0)
        if t["required"]:
            t_req += cr
            t_req_n += 1
        else:
            t_prf += cr
            t_prf_n += 1
        (t_hit if cr else t_miss).append(t)
    v_w = v_got = 0
    v_hit, v_miss = [], []
    for v in om["vocab"]:
        lv = co["stems"].get(v["stem"], 0)
        cr = 1 if lv == 2 else (0.85 if lv == 1 else 0)
        v_w += v["w"]
        v_got += v["w"] * cr
        (v_hit if cr else v_miss).append(v)
    # a strong match shares about ORM_VREF of a posting's weighted words (postings say far more than any resume does)
    V = min(1, v_got / v_w / ORM_VREF) if v_w >= ORM_VMIN else None
    t_cov_req = t_req / t_req_n if t_req_n else None
    t_cov_prf = t_prf / t_prf_n if t_prf_n else None
    x_t = t_cov_prf if t_cov_req is None else (t_cov_req if t_cov_prf is None else 0.75 * t_cov_req + 0.25 * t_cov_prf)
    n_t = 0 if x_t is None else ORM_TERM_W * (t_req_n + t_prf_n)
    n_v = 0 if V is None else min(ORM_BETA_MAX, v_w / ORM_BETA_DIV)
    n_o = n_t + n_v
    x_o = (((0 if x_t is None else n_t * x_t) + (0 if V is None else n_v * V)) / n_o) if n_o > 0 else None
    n_x = len(req_u) + len(prf_u)
    if x_o is not None:
        x = x_o if x is None else (n_x * x + n_o * x_o) / (n_x + n_o)
    S = None
    sk_caution = ""
    n_s = n_x + n_o
    n_named = n_x + t_req_n + t_prf_n
    if x is not None:
        raw = 100 * (1 - math.pow(1 - x, 1.4))
        S = rhu((n_s * raw + 1.5 * 55) / (n_s + 1.5))
        # few named skills = less evidence, so the score is pulled toward the middle; say so
        if abs(S - rhu(raw)) >= 3:
            sk_caution = " · scored cautiously: only " + jsnum(n_named) + (" requirement is" if n_named == 1 else " requirements are") + " named"
    if len(req_u) >= 2 and cov_req < 0.5:
        caps.append({"cap": 59, "key": "skills", "why": "Covers under half of the required skills"})
    elif len(req_u) == 1 and cov_req == 0:
        caps.append({"cap": 59, "key": "skills", "why": "Missing its one required skill: " + " or ".join(d["name"] for d in req_u[0]["members"])})
    # "Excellent" means every required skill is covered (proven or listed), not just most of them
    weak_req = [u for u in req_u if u["credit"] < 0.85]
    if weak_req:
        caps.append({"cap": 84, "key": "skills_gap", "why": "Not every required skill is covered (" + ", ".join(" or ".join(d["name"] for d in u["members"]) for u in weak_req[:2]) + (", …" if len(weak_req) > 2 else "") + ") - so not Excellent"})
    # nothing the posting asks for could be read: a title match can't be "Excellent"
    if S is None:
        caps.append({"cap": 69, "key": "title_only", "why": "The posting names no skills Kaidostar can check - this is a title match only"})
    elif n_s <= ORM_THIN:
        caps.append({"cap": 84, "key": "thin_reqs", "why": "Only " + jsnum(n_named) + " of the posting’s requirements could be checked - so it can’t count as Excellent"})
    elif cand["provenCount"] == 0 and req_u:
        caps.append({"cap": 84, "key": "evidence", "why": "None of your skills are backed by a resume line yet - add one to be rated above Strong"})
    for u in req_u:
        # a required certification or license is held or it isn't: a related one
        # (Security+ for OSCP, a journeyman license for a master's) never stands in for it
        if (u["credit"] < 0.4 and any(d["kind"] == "cert" for d in u["members"])) or (u["credit"] == 0 and any(d["kind"] == "lang" for d in u["members"])):
            if any(I.skill.get(d["id"], {}).get("license") for d in u["members"]):
                caps.append({"cap": 49, "key": "license", "why": "Requires " + " or ".join(d["name"] for d in u["members"]) + " — a license or credential you don’t list"})
            else:
                caps.append({"cap": 60, "key": "cert", "why": "Requires " + " or ".join(d["name"] for d in u["members"]) + " — not found in your profile"})
    # the skill a job is named for ("Backend Engineer (Rust)", "Salesforce Administrator") is its core:
    # without it - or at least a close relative of it - it can't be more than a partial match
    title_ids = [h["id"] for h in find_skills(job["title"]) if h["id"] in I.skill and I.skill[h["id"]]["kind"] != "soft"]
    if title_ids:
        core_u = [u for u in req_u if any(d["id"] in title_ids for d in u["members"])]
        if core_u and all(u["credit"] < 0.4 for u in core_u):
            caps.append({"cap": 59, "key": "title_skill", "why": "Missing the skill this job is named for: " + " or ".join(d["name"] for d in core_u[0]["members"])})
    ys = ls = es = gap = dlev = None
    y_min, y_alt_txt = job["yearsMin"], ""
    if job["yearsMin"] is not None and cand["years"] is not None and not job["yearsPreferred"]:
        # with the degree it names, the posting's shorter bar is the one you're held to
        y_min, ya, y_alt_txt = job["yearsMin"], job.get("yearsAlt"), ""
        ced = cand.get("education")
        if ya and ya["min"] < y_min and ced and ced.get("level") is not None and ced["level"] >= ya["edu"]:
            y_min, y_alt_txt = ya["min"], " with a " + EDU_NAMES[ya["edu"]]
        gap = round1(y_min - cand["years"])
        ys = interp(gap, YEARS_KNOTS)
        if job["level"] is not None and job["level"] <= 1.5 and cand["years"] >= y_min + 5:
            ys = min(ys, 75)
        # "Excellent" means you clear the posting's own bar: a year or more short of it can't
        # be, two short is a stretch, three short is a long shot
        y_why = "Asks for " + jsnum(y_min) + "+ years" + y_alt_txt + "; you have " + yrs_have(cand["years"])
        if gap >= 3:
            caps.append({"cap": 50, "key": "years", "why": y_why})
        elif gap >= 2:
            caps.append({"cap": 64, "key": "years", "why": y_why})
        elif gap >= 1:
            caps.append({"cap": 79, "key": "years", "why": y_why})
        if y_min >= 2 and cand["years"] < y_min / 2 and gap < 2:
            caps.append({"cap": 69, "key": "years", "why": y_why + " - under half of what it asks"})
    elif job["yearsMin"] is not None and not job["yearsPreferred"] and cand["years"] is None:
        caps.append({"cap": 84, "key": "unverified", "why": "Asks for " + jsnum(job["yearsMin"]) + "+ years - add dated work history so Kaidostar can check"})
    if job["level"] is not None and cand["level"] is not None:
        dlev = job["level"] - cand["level"]
        ls = interp(dlev, LEVEL_KNOTS)
        # over-qualification needs proof the posting is junior - its title, its pay or a years RANGE
        # (a minimum is a floor, not a ceiling) - and a count of years alone never makes you more than senior
        # (a level read from the posting's years is judged by the years-range rule below, on your related years)
        junior_proof = job["levelSource"] != "years"
        d_over = job["level"] - (3 if (cand.get("levelSource") == "years of experience" and cand["level"] > 3) else cand["level"])
        if dlev >= 2:
            caps.append({"cap": 60, "key": "level", "why": job["levelLabel"] + " role; you read as " + cand["levelLabel"].lower()})
        elif dlev >= 1.5:
            caps.append({"cap": 69, "key": "level", "why": job["levelLabel"] + " role; you read as " + cand["levelLabel"].lower() + " - a stretch"})
        elif junior_proof and d_over <= -2:
            caps.append({"cap": 69, "key": "overqualified", "why": job["levelLabel"] + " role - well below your experience (" + cand["levelLabel"].lower() + ")"})
        elif junior_proof and d_over <= -1.5:
            caps.append({"cap": 69, "key": "overqualified", "why": job["levelLabel"] + " role - below your experience (" + cand["levelLabel"].lower() + ")"})
    # a years RANGE you're far past ("2-5 years" with 13, "0-2 years" with 6) is a step down, whatever the title says
    # counted on the years in your field (a career switcher starts fresh in the new one)
    ry = None if cand.get("stage") == "switch" else (cand["relatedYears"] if cand.get("relatedYears") is not None else cand["years"])
    if job["yearsMax"] is not None and ry is not None and not job["yearsPreferred"] and ry >= job["yearsMax"] + (4 if job["yearsMax"] <= 3 else 5) and not any(c["key"] == "overqualified" for c in caps):
        caps.append({"cap": 69, "key": "overqualified", "why": "Asks for " + ((jsnum(job["yearsMin"]) + "–") if job["yearsMin"] is not None else "up to ") + jsnum(job["yearsMax"]) + " years; you have " + yrs_have(ry) + (" in this line of work" if ry != cand["years"] else "")})
    if job.get("mgmt") and job["mgmt"].get("asks") and not cand.get("mgmt"):
        caps.append({"cap": 64, "key": "management", "why": "Asks for people-management experience; none shows in your resume"})
    en = job.get("enroll")
    if en and en["required"] and cand.get("enrolled") is False:
        caps.append({"cap": 40, "key": "eligibility", "why": "For current students - you’ve finished your degree"})
    if en and en.get("returning") and en.get("termEnd") is not None and cand.get("gradAt") is not None and cand["gradAt"] <= en["termEnd"] and cand.get("enrolled") is not False:
        caps.append({"cap": 40, "key": "eligibility", "why": "For students returning to school after it; you graduate " + ym_label(cand["gradAt"])})
    if en and en["gradFrom"] is not None and cand.get("gradAt") is not None and (cand["gradAt"] < en["gradFrom"] or cand["gradAt"] > en["gradTo"]):
        caps.append({"cap": 40, "key": "eligibility", "why": "For people graduating " + ym_label(en["gradFrom"]) + "–" + ym_label(en["gradTo"]) + "; your graduation date is " + ym_label(cand["gradAt"])})
    er = job["education"]["level"]
    if er is not None and cand["education"]:
        have, prog = cand["education"]["level"], cand["education"]["inProgress"]
        if have is not None and have >= er:
            es = 100
        elif prog is not None and prog >= er:
            es = 95 if (job["type"] == "internship" or (job["level"] is not None and job["level"] <= 1)) else 75
        elif job["education"]["equivalentOk"]:
            es = 70
        else:
            es = 35
        if es == 35:
            caps.append({"cap": 60 if er >= 3 else 68, "key": "education", "why": "Requires a " + EDU_NAMES[er] + " you don’t list"})
    elif er is not None and not cand["education"] and not job["education"]["equivalentOk"]:
        caps.append({"cap": 84, "key": "unverified", "why": "Asks for a " + EDU_NAMES[er] + " - add your education so Kaidostar can check"})
    parts = [v for v in (ys, ls, es) if v is not None]
    L = None
    if parts:
        mn = min(parts)
        mean = sum(parts) / len(parts)
        L = rhu(0.6 * mn + 0.4 * mean)
    R, role_why, best_pair = None, "", None
    if targets and job["roles"]:
        best = -1
        for t in targets:
            for jr in job["roles"]:
                sm = role_sim(t, jr["id"])
                if sm > best:
                    best, best_pair = sm, [t, jr["id"]]
        R = rhu(best * 100)
        role_why = I.role[best_pair[1]]["name"] + (" — your target role" if best_pair[0] == best_pair[1] else " vs your target " + I.role[best_pair[0]]["name"])
    elif cand["goalTokens"] and not targets:
        tt = [w for w in re.findall(r"[a-z][a-z+#.-]{2,}", lc(job["title"])) if w not in GOAL_STOP and w not in TITLE_GENERIC]
        ov = uniq([w for w in tt if w in cand["goalTokens"]])
        R = 75 if len(ov) >= 2 else (55 if len(ov) == 1 else 25)
        role_why = ('Title shares "' + '", "'.join(ov[:2]) + '" with your goal') if ov else "Title doesn’t echo your goal"
    elif targets and not job["roles"]:
        # the title names no role family we know: judge it by the words it shares with your goal and targets
        tw = uniq([w for w in re.findall(r"[a-z][a-z+#.-]{2,}", lc(job["title"])) if w not in GOAL_STOP and w not in TITLE_GENERIC])
        mine = uniq(list(cand["goalTokens"]) + [w for t in targets for w in re.findall(r"[a-z][a-z+#.-]{2,}", lc(I.role[t]["name"]))])
        shared = [w for w in tw if w in mine]
        R = 70 if len(shared) >= 2 else (50 if len(shared) == 1 else 25)
        role_why = ('Role family unclear; the title shares "' + '", "'.join(shared[:2]) + '" with your goal') if shared else "Role family unclear, and the title doesn’t echo your goal"
        caps.append({"cap": 79, "key": "role_unknown", "why": "Couldn’t tell what kind of role this is from its title - so it can’t count as Excellent"})
    # a title we can't place and no skills to check: there's nothing to rate it on beyond your level
    if not job["roles"] and n_x == 0 and not t_hit:
        caps.append({"cap": 54, "key": "unplaced", "why": "Kaidostar couldn’t place this title or find any skills to check in the posting - too little to rate it higher"})
    if R is not None and R <= 20:
        caps.append({"cap": 39, "key": "role", "why": "Different field from your target roles"})
    Dx, ind_why = None, ""
    if job["industries"]:
        have_ind = None
        for ji in job["industries"]:
            for ci in cand["industries"]:
                if ci["id"] == ji["id"]:
                    have_ind = ci
                    break
            if have_ind:
                break
        if have_ind:
            Dx, ind_why = 100, "You’ve worked in " + have_ind["name"].lower() + " (" + have_ind["from"] + ")"
        else:
            Dx, ind_why = 60, job["industries"][0]["name"] + " — a new industry for you"
    if cand["needsSponsorship"] and job["auth"]["noSponsorship"]:
        caps.append({"cap": 25, "key": "auth", "why": "States it won’t sponsor visas; you said you need sponsorship"})
    if job["auth"]["citizenship"] and cand["citizen"] is False:
        caps.append({"cap": 25, "key": "auth", "why": "Requires U.S. citizenship"})
    if job["auth"].get("citizenOrPR") and cand["citizen"] is False and not cand.get("permanentResident"):
        caps.append({"cap": 25, "key": "auth", "why": "Open only to U.S. citizens and permanent residents"})
    if job["auth"]["clearance"] and (cand.get("clearanceLevel") or 0) < (job["auth"].get("clearanceLevel") or 2):
        # you hold one, but a lower level than the posting asks for: say both
        cl0, need = cand.get("clearanceLevel") or 0, CLR_NAMES[job["auth"].get("clearanceLevel") or 2]
        cl_why = ("Requires a " + need + " clearance; you list " + CLR_NAMES[cl0]) if cl0 else "Requires a security clearance you don’t list"
        if not cl0 and (cand["citizen"] is False or cand["needsSponsorship"]):
            caps.append({"cap": 25, "key": "auth", "why": "Requires a security clearance (generally U.S. citizens only)"})
        elif job["auth"].get("clearanceActive"):
            caps.append({"cap": 35, "key": "clearance", "why": ("Requires an active " + need + " clearance; you list " + CLR_NAMES[cl0]) if cl0 else "Requires an active security clearance you don’t list"})
        elif job["auth"]["clearanceObtainable"]:
            caps.append({"cap": 79 if (cl0 or cand.get("citizen") is True) else 65, "key": "clearance", "why": cl_why + (" (they may sponsor the upgrade)" if cl0 else (" (they may sponsor one, and as a U.S. citizen you can be cleared)" if cand.get("citizen") is True else " (they may sponsor one)"))})
        else:
            caps.append({"cap": 50, "key": "clearance", "why": cl_why})
    if job["mode"] == "remote" and job["remoteRegion"] and cand.get("country") and job["remoteRegion"] != cand.get("country"):
        caps.append({"cap": 30, "key": "region", "why": "Remote, but only for candidates in " + _s(REGION_NAMES.get(job["remoteRegion"]))})
    rl, cst = job.get("remoteLimit"), cand_states(cand)
    if job["mode"] == "remote" and rl and cst:
        czones = [ST_ZONE.get(c) for c in cst]
        in_state = bool(rl["states"]) and any(c in rl["states"] for c in cst)
        in_zone = bool(rl["zones"]) and any(z in rl["zones"] for z in czones)
        if (rl["states"] or rl["zones"]) and not in_state and not in_zone:
            caps.append({"cap": 30, "key": "region", "why": "Remote, but only for people in " + ", ".join(rl["states"] + [ZONE_NAMES[z] + " time" for z in rl["zones"]])})
        elif rl["excluded"] and all(c in rl["excluded"] for c in cst):
            caps.append({"cap": 30, "key": "region", "why": "Remote, but not open to people in " + ", ".join(cst)})
    lic = job.get("license")
    lic_move = False
    if lic and cand.get("licenseStates") and not any(c in lic["states"] for c in cand["licenseStates"]) and not (lic["compactOk"] and cand.get("licenseCompact")):
        # the posting itself lets you transfer yours (reciprocity, endorsement, "within 90 days of hire"): a step, not a bar
        if lic.get("transferOk"):
            lic_move = True
        else:
            caps.append({"cap": 60, "key": "license_state", "why": "Requires a license in " + " or ".join(lic["states"]) + "; your resume shows " + ", ".join(cand["licenseStates"])})
    dims = {"skills": S, "level": L, "role": R, "industry": Dx}
    wsum = acc = 0
    for k in DEFAULT_WEIGHTS:
        if dims[k] is not None and W[k] > 0:
            wsum += W[k]
            acc += W[k] * dims[k]
    fit_raw = acc / wsum if wsum > 0 else None
    fit = None if fit_raw is None else rhu(fit_raw)
    cap_applied = None
    if fit is not None:
        for c in caps:
            if c["cap"] < fit and (cap_applied is None or c["cap"] < cap_applied["cap"]):
                cap_applied = c
    final_fit = None if fit is None else (cap_applied["cap"] if cap_applied else fit)
    pitems = []
    flags = {"outsideArea": False, "modeMismatch": False, "belowFloor": False, "typeMismatch": False, "avoidIndustry": False}
    ml = mode_loc_score(job, cand, prefs)
    if ml:
        pitems.append({"key": "location", "score": ml["v"], "ok": ml["v"] >= 80, "text": ml["why"]})
        flags["outsideArea"] = ml["outside"]
        flags["modeMismatch"] = ml["modeMiss"]
    types = prefs.get("types") if isinstance(prefs.get("types"), list) else []
    if types and job["employmentType"]:
        tok = job["employmentType"] in types
        pitems.append({"key": "type", "score": 100 if tok else 30, "ok": tok, "text": TYPE_NAMES[job["employmentType"]] + ("" if tok else " — not a type you picked")})
        flags["typeMismatch"] = not tok
    elif not types and cand.get("permanentNow") and job["employmentType"] in ("contract", "temporary"):
        # you haven't said which job types you'd take, and the job you have now is permanent: a contract ranks a little lower
        pitems.append({"key": "type", "score": 60, "ok": False, "text": TYPE_NAMES[job["employmentType"]] + " \u2014 you\u2019re in a permanent job now; add Contract to your job types if you\u2019d take one"})
    top = job["salary"]["annualMax"] if job["salary"]["annualMax"] is not None else job["salary"]["annualMin"]
    F = prefs.get("salaryFloor") if isnum(prefs.get("salaryFloor")) else None
    Tg = prefs.get("salaryTarget") if isnum(prefs.get("salaryTarget")) else None
    if top is not None and (F is not None or Tg is not None):
        if F is not None and Tg is not None and Tg > F:
            sv = 100 if top >= Tg else (60 + 40 * (top - F) / (Tg - F) if top >= F else 25)
        elif F is not None:
            sv = 100 if top >= F else 25
        else:
            sv = 100 if top >= Tg else (75 if top >= 0.85 * Tg else 45)
        sv = rhu(sv)
        if sv == 25:
            tail = " — below your $" + fmt_k(F) + " floor"
        elif sv == 100:
            tail = " — meets your " + ("target" if Tg is not None else "floor")
        else:
            tail = " — under your $" + fmt_k(Tg) + " target"
        pitems.append({"key": "salary", "score": sv, "ok": sv >= 60, "text": pay_up_to(job) + fmt_k(top) + tail})
        flags["belowFloor"] = sv == 25
    want = prefs.get("industries") if isinstance(prefs.get("industries"), list) else []
    avoid = prefs.get("avoidIndustries") if isinstance(prefs.get("avoidIndustries"), list) else []
    if (want or avoid) and job["industries"]:
        ji = [d["id"] for d in job["industries"]]
        av = [d for d in ji if d in avoid]
        wa = [d for d in ji if d in want]
        if av:
            pitems.append({"key": "industry", "score": 10, "ok": False, "text": I.ind[av[0]]["name"] + " — an industry you want to avoid"})
            flags["avoidIndustry"] = True
        elif wa:
            pitems.append({"key": "industry", "score": 100, "ok": True, "text": I.ind[wa[0]]["name"] + " — an industry you picked"})
        elif want:
            pitems.append({"key": "industry", "score": 45, "ok": False, "text": I.ind[ji[0]]["name"] + " — not one of your picked industries"})
    # the level your goal names ("Senior Accountant"): a job at or below where you are now is a sideways step
    if cand.get("goalLevel") is not None and job.get("level") is not None and cand.get("level") is not None:
        if job["level"] >= cand["goalLevel"] - 0.5:
            pitems.append({"key": "level", "score": 100, "ok": True, "text": job["levelLabel"] + " \u2014 the level you\u2019re aiming for"})
        elif job["level"] <= cand["level"] - 0.75:
            pitems.append({"key": "level", "score": 15, "ok": False, "text": job["levelLabel"] + " \u2014 below where you are now"})
        else:
            pitems.append({"key": "level", "score": 40, "ok": False, "text": job["levelLabel"] + " \u2014 below the level you\u2019re aiming for (" + lc(level_label(cand["goalLevel"])) + ")"})
    pref_score = rhu(sum(p["score"] for p in pitems) / len(pitems)) if pitems else None
    pts, creasons = 0, []
    dc = job["richness"]["descChars"]
    if dc >= 1500:
        pts += 2
    elif dc >= 500:
        pts += 1
    else:
        creasons.append(("the posting is short (" + jsnum(dc) + " characters)") if dc else "the posting has no description")
    n_sk = len(units)
    if n_sk >= 5:
        pts += 2
    elif n_sk >= 2:
        pts += 1
    else:
        creasons.append("few concrete requirements could be read from it")
    if job["richness"]["sectioned"]:
        pts += 1
    if cand["provenCount"] >= 3:
        pts += 2
    elif cand["statedCount"] + cand["provenCount"] >= 3:
        pts += 1
        if cand["provenCount"] == 0:
            creasons.append("your skills are listed but not yet backed by resume lines")
    else:
        creasons.append("we know little about your experience yet")
    if job["level"] is not None and cand["level"] is not None:
        pts += 1
    if R is not None:
        pts += 1
    conf = "high" if pts >= 7 else ("medium" if pts >= 4 else "low")
    sorted_det = sorted(detail, key=lambda d: (-int(bool(d["required"])), -d["credit"]))
    for d in sorted_det:
        if d["credit"] >= 0.85 and len(positives) < 4:
            positives.append({"kind": "skill", "text": ("Requires " if d["required"] else "Prefers ") + d["name"] + " — " + ("you’ve used it" if d["how"] == "proven" else "in your skills list"), "evidence": d["evidence"], "source": d["source"]})
    for u in units:
        if not u["required"]:
            continue
        names = " or ".join(d["name"] for d in u["members"])
        if u["credit"] == 0:
            gaps.append({"kind": "missing", "text": "Missing: " + names, "evidence": u["members"][0]["jobEvidence"]})
        elif u["credit"] < 0.85:
            best_m = sorted(u["members"], key=lambda d: -d["credit"])[0]
            gaps.append({"kind": "partial", "text": best_m["name"] + " — " + (("you have " + _s(best_m["via"]) + " (similar)") if best_m["how"] == "adjacent" else ("you know " + _s(best_m["via"]) + ", " + best_m["name"] + " builds on it")), "evidence": best_m["jobEvidence"]})
    t_req_miss = [t for t in t_miss if t["required"]]
    if t_req_miss:
        gaps.append({"kind": "terms", "text": "Also asks for " + ", ".join(t["name"] for t in t_req_miss[:4]) + (", …" if len(t_req_miss) > 4 else "") + " - not in your resume"})
    if gap is not None and gap > 0.5:
        gaps.append({"kind": "years", "text": "Asks for " + jsnum(y_min) + "+ years" + y_alt_txt + "; you have " + yrs_have(cand["years"]), "evidence": job["yearsText"]})
    if lic_move:
        gaps.append({"kind": "license", "text": "Needs a license in " + " or ".join(job["license"]["states"]) + " - the posting lets you transfer yours (" + ", ".join(cand["licenseStates"]) + ") after you\u2019re hired", "evidence": job["license"]["text"]})
    shared = [t["name"] for t in t_hit] + [v["word"] for v in sorted(v_hit, key=lambda v: -v["w"]) if v["w"] >= 0.6]
    if len(shared) >= 2 and len(positives) < 5:
        positives.append({"kind": "terms", "text": "Your resume uses the posting\u2019s own terms: " + ", ".join(shared[:5])})
    if R is not None and R >= 70:
        positives.append({"kind": "role", "text": role_why})
    if L is not None and L >= 85:
        positives.append({"kind": "level", "text": job["levelLabel"] + " — right for where you are"})
    if Dx == 100:
        positives.append({"kind": "industry", "text": ind_why})
    band = band_of(final_fit)
    if S is None:
        skills_note = "No concrete skills could be read from this posting"
    elif req_u:
        skills_note = jsnum(rhu(cov_req * 100)) + "% of required skills covered" + ((", " + jsnum(rhu(cov_pref * 100)) + "% of nice-to-haves") if prf_u else "") + sk_caution
    else:
        skills_note = jsnum(rhu((cov_pref or 0) * 100)) + "% of listed skills covered" + sk_caution
    if L is None:
        level_note = "Level not stated or unknown for you"
    else:
        bits = [
            (("Asks for " + jsnum(y_min) + "+ yrs" + y_alt_txt + "; you have " + yrs_have(cand["years"])) if gap > 0.5 else "Years requirement met") if gap is not None else None,
            (job["levelLabel"] + " vs you: " + cand["levelLabel"]) if dlev is not None else None,
            ("Degree requirement met" if es >= 95 else ("Degree in progress / equivalent ok" if es >= 70 else "Degree requirement not met")) if es is not None else None,
        ]
        level_note = " · ".join(b for b in bits if b)
    return {
        "fit": final_fit, "fitUncapped": fit, "band": band["key"], "bandLabel": band["label"],
        "dims": dims, "weights": W,
        "dimNotes": {
            "skills": skills_note,
            "level": level_note,
            "role": (role_why or "Tell us your target roles to score this") if R is None else role_why,
            "industry": "Industry not clear from the posting" if Dx is None else ind_why,
        },
        "caps": caps, "capApplied": cap_applied,
        "pref": {"score": pref_score, "items": pitems, "flags": flags},
        "skillDetail": detail, "coverage": {"required": cov_req, "preferred": cov_pref, "reqCount": len(req_u), "prefCount": len(prf_u)},
        "terms": {"matched": [t["name"] for t in t_hit], "missing": [t["name"] for t in t_miss], "missingRequired": [t["name"] for t in t_miss if t["required"]],
                  "vocab": None if V is None else rhu(V * 100), "vocabShared": [v["word"] for v in sorted(v_hit, key=lambda v: -v["w"])[:8]],
                  "vocabMissing": [v["word"] for v in sorted(v_miss, key=lambda v: -v["w"])[:8]]},
        "yearsGap": gap, "levelGap": dlev, "educationScore": es,
        "roleMatch": {"target": best_pair[0], "job": best_pair[1]} if best_pair else None,
        "confidence": conf, "confidenceReasons": creasons, "confidencePoints": pts,
        "positives": positives, "gaps": gaps,
    }


# ----------------------------------------------------- opportunity quality
def _host_of(url):
    m = _URL_HOST.match(_s(url))
    return lc(m.group(1)) if m else ""


def _dom_match(host, d):
    return host == d or host[-(len(d) + 1):] == "." + d


Y2000 = 946684800000
SAMPLED_SOURCES = ("adzuna", "web_search_scholarship")   # search APIs: each pull is a sample, not the whole feed


def _plausible(t, now_ms):
    """A date in the future or before 2000 is a data error, not an age."""
    return t is not None and t >= Y2000 and not (now_ms > 0 and t > now_ms + 2 * DAY)


def assess_opportunity(job, now_ms):
    pa = job["postedAt"] if _plausible(job["postedAt"], now_ms) else None
    fs = job["firstSeenAt"] if _plausible(job["firstSeenAt"], now_ms) else None
    base = pa if pa is not None else fs
    age_source = "posted" if pa is not None else ("first_seen" if fs is not None else None)
    age_days = max(0, (now_ms - base) // DAY) if base is not None else None
    if age_days is not None:
        age_days = int(age_days)
    if age_days is None:
        fresh = "unknown"
    elif age_days <= 1:
        fresh = "new"
    elif age_days <= 3:
        fresh = "fresh"
    elif age_days <= 10:
        fresh = "recent"
    elif age_days <= 30:
        fresh = "aging"
    else:
        fresh = "old"
    pts, reasons = 0, []
    age_word = "first seen " if age_source == "first_seen" else "posted "
    if age_days is not None and age_days > 60:
        pts += 4
        reasons.append(age_word + jsnum(age_days) + " days ago")
    elif age_days is not None and age_days > 30:
        pts += 2
        reasons.append(age_word + jsnum(age_days) + " days ago")
    if job["evergreen"]["is"]:
        pts += 3
        reasons.append('reads like a standing "talent pool" post ("' + _s(job["evergreen"]["phrase"]) + '")')
    rc = job.get("repostCount") or 0
    if rc >= 2:
        pts += 2
        reasons.append("reposted " + jsnum(rc) + " times")
    elif rc == 1:
        pts += 1
        reasons.append("reposted once")
    orig = job.get("originalPostedAt") if _plausible(job.get("originalPostedAt"), now_ms) else None
    if rc >= 1 and orig is not None and (now_ms - orig) // DAY > 30:
        pts += 1
        reasons.append("first posted " + jsnum(int((now_ms - orig) // DAY)) + " days ago")
    if job["agency"]["is"]:
        pts += 1
        reasons.append("posted by a staffing agency")
    if job["richness"]["descChars"] < 200 and job["salary"]["source"] is None:
        pts += 1
        reasons.append("very little detail and no pay listed")
    last_seen_days = int(max(0, (now_ms - job["lastSeenAt"]) // DAY)) if _plausible(job["lastSeenAt"], now_ms) else None
    # only a source that re-lists its whole feed on every pull can say a job stopped appearing; a search API returns a
    # sample per query, so a live job can simply miss today's sample
    if last_seen_days is not None and last_seen_days > 7 and lc(_s(job.get("source"))).strip() not in SAMPLED_SOURCES:
        pts += 2
        reasons.append("not seen live in " + jsnum(last_seen_days) + " days")
    ghost = "high" if pts >= 4 else ("elevated" if pts >= 2 else "low")
    fresh_mult = {"new": 1, "fresh": 1, "recent": 0.96, "aging": 0.88, "old": 0.75, "unknown": 0.92}[fresh]
    ghost_mult = {"low": 1, "elevated": 0.9, "high": 0.72}[ghost]
    host = _host_of(job["applyUrl"])
    if not host:
        route = "unknown"
    elif any(_dom_match(host, d) for d in TAX["ats_domains"]):
        route = "employer"
    elif any(_dom_match(host, d) for d in TAX["aggregator_domains"]):
        route = "aggregator"
    else:
        route = "company_site"
    st = job["salary"]["source"]
    return {
        "ageDays": age_days, "ageSource": age_source, "freshness": fresh, "lastSeenDays": last_seen_days,
        "ghost": ghost, "ghostPoints": pts, "ghostReasons": reasons,
        "quality": fresh_mult * ghost_mult, "freshMult": fresh_mult, "ghostMult": ghost_mult,
        "salaryTransparency": "disclosed" if st in ("listed", "parsed") else ("estimated" if st == "estimated" else "none"),
        "applyRoute": route, "applyHost": host,
        "repostCount": rc, "originalPostedAt": orig,
    }


# --------------------------------------------------------------------- prefs
UNION_KEYS = ["excludeKeywords", "excludePhrases", "excludeRoles", "keywords", "blockedCompanies", "dreamCompanies", "avoidIndustries", "mustSkills", "skillsMore", "skillsAvoid", "excludeSkills", "excludePlaces", "companies", "rankKeywords", "excludeModes", "excludeLevels", "excludeTypes"]
PREF_LIST_CAP = 200   # the longest list the page lets you build for one filter (and what the server stores)
# what a search asks for beats a standing "never" for the same thing, and the other way round
PREF_CONFLICTS = [("modes", "excludeModes"), ("levels", "excludeLevels"), ("types", "excludeTypes"), ("companies", "blockedCompanies"), ("industries", "avoidIndustries"), ("mustSkills", "excludeSkills")]


def _js_same(a, b):
    """a === b as JavaScript sees it."""
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def compose_prefs(base, patch):
    """A search layers its constraints over saved preferences: exclusion lists
    add up, everything else is overridden - and a search never contradicts a
    standing filter for the same thing."""
    out = merge_prefs(base, None)
    if not isinstance(patch, dict):
        return out
    over = {}
    for k, v in patch.items():
        if k not in out:
            continue
        if k in UNION_KEYS and isinstance(v, list):
            u = uniq(out[k] + v)
            over[k] = uniq(v + out[k])[:PREF_LIST_CAP] if len(u) > PREF_LIST_CAP else u  # the search's own values always make it in
        else:
            over[k] = v
    res = merge_prefs(out, over)
    for pos, neg in PREF_CONFLICTS:
        org = pos == "companies"

        def same(x, y, org=org):
            return norm_org(x) == norm_org(y) if org else _js_same(x, y)
        pp = patch.get(pos) if isinstance(patch.get(pos), list) and patch.get(pos) else None
        pn = patch.get(neg) if isinstance(patch.get(neg), list) and patch.get(neg) else None
        if pp:
            res[neg] = [x for x in res[neg] if not any(same(x, y) for y in pp)]
        elif pn:
            res[pos] = [x for x in res[pos] if not any(same(x, y) for y in pn)]
    if isnum(res.get("salaryFloor")) and isnum(res.get("salaryCeiling")) and res["salaryFloor"] > res["salaryCeiling"]:
        if isnum(patch.get("salaryCeiling")) and not isnum(patch.get("salaryFloor")):
            res["salaryFloor"] = None
        elif isnum(patch.get("salaryFloor")) and not isnum(patch.get("salaryCeiling")):
            res["salaryCeiling"] = None
    return res


def _qhyph(x):
    return x if "-" not in x else re.sub(r"\s+", " ", x.replace("-", " "))


def phrase_in(low_n, k):
    """Whole words; a hyphen is a space; a plural "s" either way ("night shift" ~ "night-shifts")."""
    if not k:
        return False
    if has_word(low_n, k):
        return True
    n, last = _js_len(k), k[-1]
    if re.fullmatch(r"[a-z]", last) and last != "s" and has_word(low_n, k + "s"):
        return True
    if n >= 6 and last == "s" and k[-2] != "s" and has_word(low_n, k[:-1]):
        return True
    return False


def _place_set(lst):
    o = {"metros": [], "states": []}
    for x in (lst if isinstance(lst, list) else []):
        P = parse_user_location(x)
        if P["metros"]:
            for m in P["metros"]:
                if m not in o["metros"]:
                    o["metros"].append(m)
        else:
            for st in P["states"]:
                if st not in o["states"]:
                    o["states"].append(st)
    return o


def default_prefs():
    return {
        "v": 1,
        "targetRoles": [], "years": None, "education": None, "level": None, "extraSkills": [],
        "needsSponsorship": False, "citizen": None, "permanentResident": False, "clearance": False,
        "modes": [], "modeRule": "rank", "locations": "", "relocate": False, "locationRule": "rank",
        "salaryFloor": None, "salaryTarget": None, "salaryRule": "rank", "hideNoSalary": False,
        "levels": [], "levelRule": "rank", "maxYears": None, "yearsRule": "rank",
        "types": [], "typeRule": "rank", "authRule": "hide",
        "postedWithin": None, "hideReposts": False, "ghostRule": "rank", "hideAgencies": False, "hideEvergreen": True, "hideThin": False,
        "blockedCompanies": [], "dreamCompanies": [],
        "industries": [], "industryRule": "rank", "avoidIndustries": [],
        "mustSkills": [], "mustSkillsMode": "any", "skillsMore": [], "skillsAvoid": [],
        "excludeKeywords": [], "excludeIn": "title", "excludePhrases": [], "excludeRoles": [], "keywords": [],
        "salaryCeiling": None, "excludeSkills": [], "excludePlaces": [], "companies": [], "rankKeywords": [], "avoidManagement": False, "onlyRoles": [], "onlyRolesRule": "hide",
        "excludeModes": [], "excludeLevels": [], "excludeTypes": [],
        "maxTravel": None, "minFit": 0,
        "weights": {"skills": 45, "level": 20, "role": 30, "industry": 5},
        "prefWeight": 25, "freshness": 50, "diversity": True, "sort": "best",
    }


def merge_prefs(base, patch):
    out = default_prefs()
    for src in (base, patch):
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            if k not in out:
                continue
            if k == "weights" and isinstance(v, dict):
                out["weights"] = {wk: (clamp(v[wk], 0, 100) if isnum(v.get(wk)) else out["weights"][wk]) for wk in out["weights"]}
                continue
            if isinstance(out[k], list):
                if isinstance(v, list):
                    out[k] = v[:PREF_LIST_CAP]
                continue
            out[k] = v
    return out


# ------------------------------------------------------------------- filters
PREF_KEYS = ["mode", "location", "salary", "type", "industry"]
# "rank lower" has to be felt: a pay or place miss also lowers the preference score, so these stay moderate
SOFT_PEN = {"mode": 0.8, "location": 0.8, "salary": 0.7, "type": 0.9, "industry": 0.9}
RULE_PEN = {"mode": 0.8, "location": 0.75, "salary": 0.8, "level": 0.8, "years": 0.8, "type": 0.85, "auth": 0.5, "industry": 0.85, "onlyrole": 0.75}


def org_match(job, lst):
    o = norm_org(job["org"])
    if not o:
        return None
    for x in lst or []:
        nx = norm_org(x)
        if nx and o == nx:
            return x
    return None


def evaluate_filters(job, sc, opp, prefs, learned, ctx=None):
    I = idx()
    hide, pen, boost, soft = [], [], [], []
    ctx = ctx or {}

    # sub names which of a key's rules fired (pay floor / ceiling / no pay
    # listed), so each rule's count is its own
    def rule(r, key, why, sub=None):
        if r == "hide":
            e = {"key": key, "why": why}
            hide.append(e)
        elif key not in PREF_KEYS:
            e = {"key": key, "why": why, "mult": RULE_PEN.get(key, 0.85)}
            pen.append(e)
        else:
            # a "rank lower" preference really ranks lower; listed so the card
            # and the filter counts can say so
            e = {"key": key, "why": why, "mult": SOFT_PEN[key]}
            soft.append(e)
        if sub:
            e["sub"] = sub

    if org_match(job, prefs.get("blockedCompanies") or []):
        hide.append({"key": "company", "why": "You blocked " + job["org"]})
    only = prefs.get("companies") or []
    if only and not org_match(job, only):
        hide.append({"key": "onlyco", "why": "Not at " + " or ".join(_js_string(x) for x in only[:3]) + ((" (or " + jsnum(len(only) - 3) + " more)") if len(only) > 3 else "")})
    title_l = lc(job["title"])
    all_l = lc(job["title"] + " " + job["org"] + " " + job["description"])
    norm_cache = {}

    def t_n():
        if "t" not in norm_cache:
            norm_cache["t"] = _qhyph(title_l)
        return norm_cache["t"]

    def a_n():
        if "a" not in norm_cache:
            norm_cache["a"] = _qhyph(all_l)
        return norm_cache["a"]
    for k in prefs.get("excludeKeywords") or []:
        kl = kw_norm(k)
        if not kl:
            continue
        anywhere = prefs.get("excludeIn") == "anywhere"
        if phrase_in(a_n() if anywhere else t_n(), kl):
            hide.append({"key": "keyword", "why": 'Mentions "' + _s(k) + '"' + ("" if anywhere else " in the title")})
    for k in prefs.get("excludePhrases") or []:
        kl = kw_norm(k)
        if not kl:
            continue
        if phrase_in(a_n(), kl):
            hide.append({"key": "phrase", "why": 'Mentions "' + _s(k) + '"'})
    # a role you never want: judged by the job's main role, so "Sales Data Analyst" isn't a sales job
    xr = prefs.get("excludeRoles") or []
    if xr and job["roles"] and job["roles"][0]["id"] in xr:
        hide.append({"key": "role", "why": job["roles"][0]["name"] + " — a role you excluded"})
    for k in prefs.get("keywords") or []:
        kl = kw_norm(k)
        if not kl:
            continue
        if not phrase_in(a_n(), kl):
            hide.append({"key": "mention", "why": "Doesn’t mention \"" + _s(k) + '"'})
    qr = [r for r in (ctx.get("queryRoles") or []) if isinstance(r, str) and r in I.role]
    if qr:
        ok = any(any(role_sim(q, jr["id"]) >= 0.6 for q in qr) for jr in job["roles"])
        if not ok:
            hide.append({"key": "search", "why": "Not a " + " / ".join(I.role[r]["name"] for r in qr) + " role"})
    else:
        # a role filter you kept from a search (a new search's roles replace it while it's on)
        oroles = [r for r in (prefs.get("onlyRoles") or []) if isinstance(r, str) and r in I.role]
        if oroles and not any(any(role_sim(q, jr["id"]) >= 0.6 for q in oroles) for jr in job["roles"]):
            onames = " / ".join(I.role[r]["name"] for r in oroles[:3]) + ((" (+" + jsnum(len(oroles) - 3) + ")") if len(oroles) > 3 else "")
            rule("rank" if prefs.get("onlyRolesRule") == "rank" else "hide", "onlyrole", (job["roles"][0]["name"] if job["roles"] else "This role") + " — not one of your roles (" + onames + ")")
    modes = prefs.get("modes") or []
    if modes and job["mode"] and job["mode"] not in modes:
        label = "On-site" if job["mode"] == "onsite" else job["mode"][0].upper() + job["mode"][1:]
        rule(prefs.get("modeRule"), "mode", label + " — you want " + " or ".join(mode_word(m) for m in modes))
    xm = prefs.get("excludeModes") or []
    if xm and job["mode"] and job["mode"] in xm:
        hide.append({"key": "xmode", "why": mode_name(job["mode"]) + " — you said no " + mode_word(job["mode"]) + " jobs"})
    if job["mode"] != "remote" and sc["pref"]["flags"]["outsideArea"]:
        rule(prefs.get("locationRule"), "location", ("Hybrid" if job["mode"] == "hybrid" else "On-site") + " in " + (clean_loc(job["location"]) or "another area") + " — outside where you want to work")
    xp = ctx.get("xPlaces") or _place_set(prefs.get("excludePlaces"))
    if (xp["metros"] or xp["states"]) and job["mode"] != "remote" and job["places"] and all(
            (p.get("metro") and p["metro"] in xp["metros"]) or (p.get("state") and p["state"] in xp["states"]) for p in job["places"]):
        lead = "Hybrid in " if job["mode"] == "hybrid" else ("On-site in " if job["mode"] == "onsite" else "In ")
        hide.append({"key": "place", "why": lead + (clean_loc(job["location"]) or job["places"][0]["label"]) + " — a place you excluded"})
    top = job["salary"]["annualMax"] if job["salary"]["annualMax"] is not None else job["salary"]["annualMin"]
    if isnum(prefs.get("salaryFloor")) and top is not None and top < prefs["salaryFloor"]:
        rule(prefs.get("salaryRule"), "salary", pay_up_to(job) + fmt_k(top) + " — under your $" + fmt_k(prefs["salaryFloor"]) + " floor", "floor")
    bottom = job["salary"]["annualMin"] if job["salary"]["annualMin"] is not None else job["salary"]["annualMax"]
    if isnum(prefs.get("salaryCeiling")) and bottom is not None and bottom > prefs["salaryCeiling"]:
        rule(prefs.get("salaryRule"), "salary", ("Estimated to start at $" if job["salary"]["source"] == "estimated" else "Starts at $") + fmt_k(bottom) + " — above your $" + fmt_k(prefs["salaryCeiling"]) + " limit", "ceiling")
    if prefs.get("hideNoSalary") and top is None:
        hide.append({"key": "salary", "why": "No pay listed", "sub": "nopay"})
    lvls = prefs.get("levels") or []
    bucket = level_bucket(job["level"])
    if lvls and bucket and bucket not in lvls:
        rule(prefs.get("levelRule"), "level", job["levelLabel"] + " — outside the levels you picked")
    xl = prefs.get("excludeLevels") or []
    if xl and bucket and bucket in xl:
        hide.append({"key": "xlevel", "why": job["levelLabel"] + " — a level you excluded"})
    if isnum(prefs.get("maxYears")) and job["yearsMin"] is not None and not job["yearsPreferred"] and job["yearsMin"] > prefs["maxYears"]:
        rule(prefs.get("yearsRule"), "years", "Asks for " + jsnum(job["yearsMin"]) + "+ years (your max: " + jsnum(prefs["maxYears"]) + ")")
    types = prefs.get("types") or []
    if types and job["employmentType"] and job["employmentType"] not in types:
        rule(prefs.get("typeRule"), "type", TYPE_NAMES[job["employmentType"]] + " — not a type you picked")
    xty = prefs.get("excludeTypes") or []
    if xty and job["employmentType"] and job["employmentType"] in xty:
        hide.append({"key": "xtype", "why": TYPE_NAMES[job["employmentType"]] + " — a job type you excluded"})
    auth_bad = [c for c in sc["caps"] if (c["key"] == "auth" and c["cap"] <= 25) or c["key"] == "region"]
    if auth_bad:
        rule(prefs.get("authRule"), "auth", auth_bad[0]["why"])
    pw = prefs.get("postedWithin")
    if isnum(pw) and pw > 0 and opp["ageDays"] is not None and opp["ageDays"] > pw:
        hide.append({"key": "fresh", "why": "Posted " + jsnum(opp["ageDays"]) + " days ago (you want ≤ " + jsnum(pw) + ")"})
    if prefs.get("hideReposts") and opp["repostCount"] >= 1:
        hide.append({"key": "repost", "why": "Reposted " + jsnum(opp["repostCount"]) + (" time" if opp["repostCount"] == 1 else " times")})
    if prefs.get("ghostRule") == "hide" and opp["ghost"] == "high":
        hide.append({"key": "ghost", "why": "High ghost-job risk: " + "; ".join(opp["ghostReasons"][:2])})
    if prefs.get("hideAgencies") and job["agency"]["is"]:
        hide.append({"key": "agency", "why": "Staffing agency post (" + job["agency"]["reasons"][0] + ")"})
    if prefs.get("hideEvergreen") and job["evergreen"]["is"]:
        hide.append({"key": "evergreen", "why": "Standing talent-pool post, not a specific opening"})
    if prefs.get("hideThin") and job["richness"]["descChars"] < 300:
        hide.append({"key": "thin", "why": "Almost no description"})
    ji = [d["id"] for d in job["industries"]]
    av = [d for d in (prefs.get("avoidIndustries") or []) if d in ji]
    if av:
        hide.append({"key": "industry", "why": I.ind[av[0]]["name"] + " — an industry you avoid" if av[0] in I.ind else _s(av[0]), "sub": "avoid"})
    picked = prefs.get("industries") or []
    if picked and prefs.get("industryRule") == "only" and not any(d in picked for d in ji):
        hide.append({"key": "industry", "why": "Not in your picked industries", "sub": "only"})
    must = prefs.get("mustSkills") or []
    if must:
        have = [m for m in must if any(s["id"] == m or m in (I.skill[s["id"]].get("implies") or []) for s in job["skills"])]
        passed = len(have) == len(must) if prefs.get("mustSkillsMode") == "all" else len(have) > 0
        if not passed:
            missing = [m for m in must if m not in have]
            joiner = " and " if prefs.get("mustSkillsMode") == "all" else " or "
            hide.append({"key": "skills", "why": "Doesn’t use " + joiner.join((I.skill[m]["name"] if m in I.skill else _s(m)) for m in missing)})
    for sid in prefs.get("excludeSkills") or []:
        hit = next((s for s in job["skills"] if s["required"] and (_js_same(s["id"], sid) or any(_js_same(x, sid) for x in ((I.skill.get(s["id"]) or {}).get("implies") or [])))), None)
        if hit:
            alt = "" if _js_same(hit["id"], sid) else " (" + (I.skill[sid]["name"] if isinstance(sid, str) and sid in I.skill else _js_string(sid)) + ")"
            hide.append({"key": "xskill", "why": "Requires " + hit["name"] + alt + " — a skill you excluded"})
    if prefs.get("avoidManagement") is True:
        if PEOPLE_MGR_TITLE.search(title_l) and not NOT_PEOPLE_MGR.search(title_l):
            hide.append({"key": "management", "why": '"' + trunc(job["title"], 60) + '" is a people-manager role'})
        elif job.get("mgmt") and job["mgmt"].get("required"):
            hide.append({"key": "management", "why": "Asks you to manage people" + ((': "' + trunc(job["mgmt"]["text"], 90) + '"') if job["mgmt"].get("text") else "")})
    mt = prefs.get("maxTravel")
    if isnum(mt) and job["travel"] is not None and job["travel"] > mt:
        hide.append({"key": "travel", "why": "Up to " + jsnum(job["travel"]) + "% travel (your max: " + jsnum(mt) + "%)"})
    mf = prefs.get("minFit")
    if isnum(mf) and mf > 0 and sc["fit"] is not None and sc["fit"] < mf:
        hide.append({"key": "minfit", "why": "Fit " + jsnum(sc["fit"]) + " is below your minimum of " + jsnum(mf)})
    for sid in prefs.get("skillsAvoid") or []:
        hit = next((s for s in job["skills"] if s["id"] == sid and s["required"]), None)
        if hit:
            pen.append({"key": "avoid_skill", "why": "Requires " + hit["name"] + ", which you want less of", "mult": 0.85})
    for sid in prefs.get("skillsMore") or []:
        hit = next((s for s in job["skills"] if s["id"] == sid), None)
        if hit:
            boost.append({"key": "more_skill", "why": "Uses " + hit["name"] + ", which you want more of", "mult": 1.05})
    if org_match(job, prefs.get("dreamCompanies") or []):
        boost.append({"key": "dream", "why": job["org"] + " is on your dream list", "mult": 1.08})
    for k in prefs.get("rankKeywords") or []:
        kl = kw_norm(k)
        if kl and phrase_in(a_n(), kl):
            boost.append({"key": "rankkw", "why": 'Mentions "' + _s(k) + '" — a word you rank up', "mult": 1.1})
    if prefs.get("needsSponsorship") is True and job.get("auth") and job["auth"].get("sponsors"):
        boost.append({"key": "sponsor", "why": "Says it sponsors visas", "mult": 1.1})
    for r in (learned if isinstance(learned, list) else []):
        if not isinstance(r, dict) or r.get("active") is False:
            continue
        eff = learned_effect(r, job)
        if eff == "hide":
            hide.append({"key": "learned", "why": r.get("label"), "rule": r.get("id")})
        elif eff is not None and eff < 1:
            pen.append({"key": "learned", "why": r.get("label"), "mult": eff, "rule": r.get("id")})
        elif eff is not None and eff > 1:
            boost.append({"key": "learned", "why": r.get("label"), "mult": eff, "rule": r.get("id")})
    # a "rank lower" miss (place, mode, pay, type) already lowers the rank through
    # your preference score, so here it counts at half strength (x0.9 for a place
    # outside your area, not x0.8 on top) - in full only when preferences don't
    # count toward rank at all (weight 0). Never the whole penalty twice.
    soft_full = isnum(prefs.get("prefWeight")) and prefs["prefWeight"] <= 0
    pm = 1
    for p in pen:
        pm *= p["mult"]
    for p in soft:
        pm *= p["mult"] if soft_full else 1 - (1 - p["mult"]) / 2
    pm = max(0.4, pm)
    bm = 1
    for b in boost:
        bm *= b["mult"]
    bm = min(1.2, bm)
    return {"hidden": len(hide) > 0, "hide": hide, "penalties": pen, "boosts": boost, "soft": soft, "mult": pm * bm}


# ------------------------------------------------------------------ learning
def learned_effect(r, job):
    kind, val = r.get("kind"), r.get("value")
    if kind == "block_company":
        return "hide" if norm_org(job["org"]) == val else None
    if kind == "level_above":
        return 0.85 if job["level"] is not None and isnum(val) and job["level"] >= val else None
    if kind == "level_below":
        return 0.85 if job["level"] is not None and isnum(val) and job["level"] <= val else None
    if kind == "avoid_place":
        return 0.85 if job["mode"] != "remote" and any(p["metro"] == val or (not p["metro"] and p["state"] == val) for p in job["places"]) else None
    if kind == "salary_floor":
        top = job["salary"]["annualMax"] if job["salary"]["annualMax"] is not None else job["salary"]["annualMin"]
        return 0.85 if top is not None and isnum(val) and top < val else None
    if kind == "avoid_role":
        return 0.8 if any(x["id"] == val for x in job["roles"]) else None
    if kind == "avoid_skill":
        return 0.88 if any(s["id"] == val and s["required"] for s in job["skills"]) else None
    if kind == "like_role":
        return 1.04 if any(x["id"] == val for x in job["roles"]) else None
    if kind == "avoid_type":
        return 0.85 if job["employmentType"] == val else None
    return None


def learn_from_dismiss(job, reason, sc=None, now_ms=0):
    I = idx()
    r = None
    if reason == "too_senior" and job["level"] is not None:
        r = {"kind": "level_above", "value": job["level"], "label": "Rank " + level_label(job["level"]).lower() + "+ roles lower"}
    elif reason == "too_junior" and job["level"] is not None:
        r = {"kind": "level_below", "value": job["level"], "label": "Rank " + level_label(job["level"]).lower() + " and below lower"}
    elif reason == "location" and job["mode"] != "remote" and job["places"]:
        p = job["places"][0]
        v = p["metro"] or p["state"]
        if v:
            r = {"kind": "avoid_place", "value": v, "label": "Rank on-site roles in " + (I.metro[p["metro"]]["name"] if p["metro"] else p["state"]) + " lower"}
    elif reason == "salary":
        top = job["salary"]["annualMax"] if job["salary"]["annualMax"] is not None else job["salary"]["annualMin"]
        if top is not None:
            fl = math.ceil((top + 1) / 5000) * 5000
            r = {"kind": "salary_floor", "value": fl, "label": "Rank roles paying under $" + fmt_k(fl) + " lower"}
    elif reason == "not_my_field" and job["roles"]:
        r = {"kind": "avoid_role", "value": job["roles"][0]["id"], "label": "Rank " + job["roles"][0]["name"] + " roles lower"}
    elif reason == "company" and norm_org(job["org"]):
        r = {"kind": "block_company", "value": norm_org(job["org"]), "label": "Hide jobs at " + job["org"]}
    elif reason == "skills" and sc and sc.get("skillDetail"):
        miss = next((d for d in sc["skillDetail"] if d["required"] and d["credit"] == 0), None)
        if miss:
            r = {"kind": "avoid_skill", "value": miss["id"], "label": "Rank roles requiring " + miss["name"] + " lower"}
    elif reason == "type" and job["employmentType"]:
        r = {"kind": "avoid_type", "value": job["employmentType"], "label": "Rank " + TYPE_NAMES[job["employmentType"]].lower() + " roles lower"}
    if not r:
        return None
    r["id"] = r["kind"] + ":" + _s(r["value"])
    r["active"] = True
    r["createdAt"] = now_ms or 0
    r["source"] = {"title": job["title"], "org": job["org"], "reason": reason}
    return r


def learn_from_save(job, now_ms=0):
    if not job["roles"]:
        return None
    r0 = job["roles"][0]
    return {"id": "like_role:" + r0["id"], "kind": "like_role", "value": r0["id"], "label": "Rank " + r0["name"] + " roles a little higher (you saved one)",
            "active": True, "createdAt": now_ms or 0, "source": {"title": job["title"], "org": job["org"], "reason": "saved"}}


def merge_learned(lst, rule):
    lst = list(lst) if isinstance(lst, list) else []
    if not rule:
        return lst
    for i, x in enumerate(lst):
        if isinstance(x, dict) and x.get("id") == rule["id"]:
            lst[i] = dict(x, active=True, source=rule.get("source"))
            return lst
    lst.append(rule)
    return lst[-40:]


# ------------------------------------------------------------ pool & ranking
# -------------------------------------------------------------------- levers
def _with_proven_skill(cand, sid):
    I = idx()
    sk = I.skill[sid]
    skills = dict(cand["skills"])
    skills[sid] = {"id": sid, "name": sk["name"], "level": "proven", "evidence": "what-if", "source": "what-if", "via": None}
    for t in sk.get("implies") or []:
        if t in I.skill and (t not in skills or low_prior(skills[t]["level"]) < 2):
            skills[t] = {"id": t, "name": I.skill[t]["name"], "level": "proven", "evidence": "what-if", "source": "what-if", "via": sk["name"]}
    out = dict(cand)
    out["skills"] = skills
    return out


def score_levers(job, cand, prefs, opts=None, base=None):
    """What would actually move this score: re-score with one skill proven
    (only skills the posting asks for). Years and degrees are never levers."""
    I = idx()
    base = base or score_job(job, cand, prefs, opts)
    if base["fit"] is None:
        return {"fit": None, "levers": []}
    out, seen = [], set()
    for d in base["skillDetail"]:
        if d["credit"] >= 1 or d["id"] in seen or d["id"] not in I.skill:
            continue
        seen.add(d["id"])
        s2 = score_job(job, _with_proven_skill(cand, d["id"]), prefs, opts)
        gain = (s2["fit"] or 0) - base["fit"]
        if gain <= 0:
            continue
        lifts = bool(base["capApplied"] and not (s2["capApplied"] and s2["capApplied"]["key"] == base["capApplied"]["key"]))
        out.append({"id": d["id"], "name": d["name"], "required": bool(d["required"]), "now": d["how"], "gain": gain, "fit": s2["fit"], "liftsCap": lifts})
    out.sort(key=lambda x: (-x["gain"], x["id"]))
    return {"fit": base["fit"], "levers": out[:6]}


def skill_unlocks(items, cand, prefs, opts=None):
    """Across a set of jobs: which skill you don't yet prove would lift the most
    of them into Strong (70+)? Exact re-scores, not guesses."""
    I = idx()
    req, order = {}, []
    for it in items or []:
        if not it or not it.get("score") or it["score"]["fit"] is None:
            continue
        for d in it["score"]["skillDetail"]:
            if d["credit"] >= 1 or d["id"] not in I.skill or I.skill[d["id"]].get("kind") == "soft":
                continue
            if d["id"] not in req:
                req[d["id"]] = []
                order.append(d["id"])
            if not any(x is it for x in req[d["id"]]):
                req[d["id"]].append(it)
    order.sort(key=lambda a: (-len(req[a]), I.skill_i[a]))
    res = []
    for sid in order[:10]:
        c2 = _with_proven_skill(cand, sid)
        gains, to_strong, ids = 0, 0, []
        for it in req[sid]:
            s2 = score_job(it["job"], c2, prefs, opts)
            gains += (s2["fit"] or 0) - it["score"]["fit"]
            if it["score"]["fit"] < 70 and s2["fit"] is not None and s2["fit"] >= 70:
                to_strong += 1
                ids.append(it["job"]["id"])
        cs = cand["skills"].get(sid)
        have = cs["level"] if cs else "missing"
        if not cs:
            cr = skill_credit({"id": sid, "family": I.skill[sid].get("family")}, cand)
            if cr["how"] in ("adjacent", "related"):
                have = cr["how"]
        res.append({"id": sid, "name": I.skill[sid]["name"], "have": have, "jobs": len(req[sid]),
                    "avgGain": round1(gains / len(req[sid])), "toStrong": to_strong, "toStrongIds": ids[:20]})
    res = [x for x in res if x["avgGain"] > 0]
    res.sort(key=lambda x: (-x["toStrong"], -x["avgGain"], -x["jobs"], x["id"]))
    return res


def _dup_loose_key(j):
    """The same posting under two titles and two write-ups (a job board's summary
    of the employer's ad): same employer, same place, the same stated pay."""
    ck = _s(j.get("canonicalKey"))
    if not ck or ck[0] == "#":
        return None
    sal = j.get("salary") or {}
    if sal.get("annualMin") is None or not sal.get("source") or sal.get("source") == "estimated":
        return None
    p = ck.split("|")
    return p[0] + "|" + "|".join(p[2:]) + "|" + jsnum(sal["annualMin"]) + "-" + (jsnum(sal["annualMax"]) if sal.get("annualMax") is not None else "")


DUP_SHIFT = re.compile(r"(?<![a-z])(nights?|days|evenings?|overnights?|weekends?|night shift|day shift|evening shift|prn|per diem)(?![a-z])")


def _dup_title_words(t):
    return uniq(re.findall(r"[a-z]{2,}", DUP_SHIFT.sub(" ", norm_title(t))))


DUP_BOILER = re.compile(r"(equal (employment )?opportunity|without regard to|reasonable accommodation|e-verify|affirmative action|pay range|veteran status|protected (veteran|class)|eeo|drug[- ]free)")


def _dup_word_set(t):
    # the employer's legal boilerplate is the same on every one of its postings - it says nothing about the job
    kept = [ln for ln in re.split(r"\n+|(?<=[.!?])\s+", lc(t)) if not DUP_BOILER.search(ln)]
    return set(re.findall(r"[a-z0-9]{3,}", " \n ".join(kept)))


def _dup_same_job(a, b):
    """Titles that share almost every word and mostly the same words in the text."""
    A, B = _dup_title_words(a["title"]), _dup_title_words(b["title"])
    if not A or not B:
        return False
    both = sum(1 for w in A if w in B)
    if both / min(len(A), len(B)) < 0.8:
        return False
    wa, wb = _dup_word_set(a.get("description")), _dup_word_set(b.get("description"))
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def dedupe_pool(jobs):
    groups, order = {}, []
    for j in jobs:
        k = j["canonicalKey"]
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(j)
    by_loose, kept = {}, []
    for k in order:
        j0 = groups[k][0]
        lk = _dup_loose_key(j0)
        if lk is None:
            kept.append(k)
            continue
        seen = by_loose.setdefault(lk, [])
        merged = False
        for sk in seen:
            if _dup_same_job(groups[sk][0], j0):
                groups[sk] = groups[sk] + groups[k]
                merged = True
                break
        if not merged:
            seen.append(k)
            kept.append(k)
    order = kept
    out = []
    for k in order:
        g = groups[k]
        g = sorted(g, key=functools.cmp_to_key(_dup_cmp))
        rep = g[0]
        if len(g) > 1:
            days = sorted(set(x["postedAt"] // DAY for x in g if x["postedAt"] is not None))
            clusters, last = 0, None
            for d in days:
                if last is None or d - last > 7:
                    clusters += 1
                last = d
            extra = max(0, clusters - 1)
            rep = dict(rep)
            rep["duplicates"] = [{"id": x["id"], "source": x["source"], "postedAt": x["postedAt"], "applyUrl": x["applyUrl"]} for x in g[1:]]
            rep["repostCount"] = max(rep.get("repostCount") or 0, extra)
            rep["firstPostedAt"] = days[0] * DAY if days else rep["postedAt"]
            if extra > 0 and rep["postedAt"] is not None and days:
                rep["originalPostedAt"] = days[0] * DAY
        out.append(rep)
    return out


def _dup_cmp(a, b):
    d = b["richness"]["descChars"] - a["richness"]["descChars"]
    if d:
        return d
    d = (b["postedAt"] or 0) - (a["postedAt"] or 0)
    if d:
        return d
    return -1 if a["id"] < b["id"] else (1 if a["id"] > b["id"] else 0)


def is_expired(job, now):
    if not job.get("deadline") or not now:
        return False
    t = parse_time(job["deadline"])
    if t is None:
        return False
    return t + DAY <= now


def _deadline_key(job):
    t = parse_time(job.get("deadline"))
    return 9e15 if t is None else t


def _age_key(it):
    a = it["opp"]["ageDays"]
    return 1e9 if a is None else a


def _cmp_id(a, b):
    return -1 if a["job"]["id"] < b["job"]["id"] else (1 if a["job"]["id"] > b["job"]["id"] else 0)


def _sort_cmp(sort):
    def cmp(a, b):
        if sort == "fit":
            d = (b["score"]["fit"] or 0) - (a["score"]["fit"] or 0)
        elif sort == "newest":
            d = _age_key(a) - _age_key(b)
        elif sort == "salary":
            d = ((b["job"]["salary"]["annualMax"] or b["job"]["salary"]["annualMin"] or 0) - (a["job"]["salary"]["annualMax"] or a["job"]["salary"]["annualMin"] or 0))
        elif sort == "closing":
            d = _deadline_key(a["job"]) - _deadline_key(b["job"])
        else:
            d = b["rank"] - a["rank"]
        if d:
            return -1 if d < 0 else 1
        d = (b["score"]["fit"] or 0) - (a["score"]["fit"] or 0)
        if d:
            return -1 if d < 0 else 1
        d = _age_key(a) - _age_key(b)
        if d:
            return -1 if d < 0 else 1
        return _cmp_id(a, b)
    return cmp


def sort_items(arr, sort):
    arr.sort(key=functools.cmp_to_key(_sort_cmp(sort)))
    return arr


def diversify(arr, per_org, window):
    res, deferred, count = [], [], {}
    for i, it in enumerate(arr):
        o = norm_org(it["job"]["org"]) or it["job"]["id"]
        if count.get(o, 0) >= per_org and len(res) < window:
            deferred.append((i, it))
            continue
        count[o] = count.get(o, 0) + 1
        res.append((i, it))
    if not deferred:
        return arr
    head = res[:window]
    tail = sorted(res[window:] + deferred, key=lambda x: x[0])
    return [x[1] for x in head + tail]


_PARSE_CACHE = collections.OrderedDict()
_PARSE_CACHE_MAX = 5000            # a few pools' worth; least recently used goes first
_PARSE_CACHE_LOCK = threading.Lock()


def _cache_key(listing):
    # everything the parse reads EXCEPT when we last saw it live: a scan that only
    # marks listings as seen must not force 800 re-parses
    tags = listing.get("tags")
    return (_s(listing.get("id")), _s(listing.get("title")), hash(_s(listing.get("description"))), _s(listing.get("salary_min")), _s(listing.get("salary_max")),
            _s(listing.get("salary_is_predicted")), _s(listing.get("salary_period")), _s(listing.get("posted_at")), _s(listing.get("first_seen_at")), _s(listing.get("fetched_at")),
            _s(listing.get("repost_count")), _s(listing.get("location")), _s(listing.get("org")), _s(listing.get("type")),
            _s(listing.get("employment_type")), _s(listing.get("contract_type")), _s(listing.get("deadline")), _s(listing.get("apply_url")),
            _s(listing.get("source")), tuple(_s(t) for t in tags) if isinstance(tags, list) else None)


def parse_job_cached(listing):
    """Server-side cache: a listing's text is parsed once - re-scoring for every
    user then costs only the scoring. The "last seen live" fields are filled in
    fresh on every lookup (a shallow copy - cached jobs are never mutated)."""
    if not isinstance(listing, dict):
        return parse_job(listing)
    key = _cache_key(listing)
    with _PARSE_CACHE_LOCK:
        hit = _PARSE_CACHE.get(key)
        if hit is not None:
            _PARSE_CACHE.move_to_end(key)
    if hit is None:
        hit = parse_job(listing)
        with _PARSE_CACHE_LOCK:
            _PARSE_CACHE[key] = hit
            while len(_PARSE_CACHE) > _PARSE_CACHE_MAX:
                _PARSE_CACHE.popitem(last=False)
        return hit
    last_seen = parse_time(_pick(listing, "last_seen_at", "lastSeenAt"))
    seen = _to_count(_pick(listing, "seen_count", "seenCount"), None)
    if hit["lastSeenAt"] != last_seen or hit["seenCount"] != seen:
        hit = dict(hit, lastSeenAt=last_seen, seenCount=seen)
    return hit


def _js_truthy(x):
    if x is None or x is False:
        return False
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return x == x and x != 0
    if isinstance(x, str):
        return x != ""
    return True


def _id_set(v):
    if isinstance(v, (list, tuple, set)):
        return {_s(x) for x in v}
    if isinstance(v, dict):
        return {_s(k) for k, x in v.items() if _js_truthy(x)}
    return set()


def analyze_pool(listings, profile, entries, prefs, learned, opts=None):
    opts = opts or {}
    now = opts.get("now") if isnum(opts.get("now")) else 0
    prefs = merge_prefs(prefs, None)
    cand = build_candidate(profile, entries, prefs, now)
    cand["country"] = opts.get("country") or "US"
    dismissed = _id_set(opts.get("dismissed"))
    applied = _id_set(opts.get("applied"))
    learned = learned if isinstance(learned, list) else []
    types = opts.get("types") if isinstance(opts.get("types"), list) and opts.get("types") else None
    parsed, type_skipped, expired = [], {}, 0
    cache = opts.get("parsedCache") or {}
    use_cache = bool(opts.get("useServerCache"))
    for l in listings or []:
        if not _js_truthy(l):
            continue
        j = cache.get(_s(l.get("id"))) if isinstance(l, dict) else None
        if j is None:
            j = parse_job_cached(l) if use_cache else parse_job(l)
        # left out, and counted - so what's shown + hidden + left out always adds up to what was scanned
        if types and j["type"] not in types:
            type_skipped[j["type"]] = type_skipped.get(j["type"], 0) + 1
            continue
        if is_expired(j, now):
            expired += 1
            continue
        parsed.append(j)
    merged = dedupe_pool(parsed)
    # dismissed / applied: the whole duplicate group goes, so the same job can't sneak back from another site
    pool = [j for j in merged if not (j["id"] in dismissed or j["id"] in applied
                                      or any(d["id"] in dismissed or d["id"] in applied for d in (j.get("duplicates") or [])))]
    qr = [r for r in (opts.get("queryRoles") or []) if isinstance(r, str) and r in idx().role]
    ctx = {"queryRoles": qr, "xPlaces": _place_set(prefs.get("excludePlaces"))}
    fw = clamp(prefs["freshness"] if isnum(prefs.get("freshness")) else 50, 0, 100) / 100
    pw = clamp(prefs["prefWeight"] if isnum(prefs.get("prefWeight")) else 25, 0, 100) / 100
    items = []
    for job in pool:
        sc = score_job(job, cand, prefs, {"queryRoles": qr})
        opp = assess_opportunity(job, now)
        fl = evaluate_filters(job, sc, opp, prefs, learned, ctx)
        qf = 1 - fw + fw * opp["quality"]
        pf = 1 - pw + pw * (1 if sc["pref"]["score"] is None else sc["pref"]["score"] / 100)
        rank = 0 if sc["fit"] is None else sc["fit"] * pf * qf * fl["mult"]
        items.append({"job": job, "score": sc, "opp": opp, "filters": fl, "rank": math.floor(rank * 100 + 0.5) / 100,
                      "qualityFactor": math.floor(qf * 1000 + 0.5) / 1000, "prefFactor": math.floor(pf * 1000 + 0.5) / 1000})
    visible = [it for it in items if not it["filters"]["hidden"]]
    hidden = [it for it in items if it["filters"]["hidden"]]
    sort = prefs.get("sort") or "best"
    sort_items(visible, sort)
    if prefs.get("diversity") is not False and sort == "best":
        visible = diversify(visible, 2, 10)

    def hid_cmp(a, b):
        d = (b["score"]["fit"] or 0) - (a["score"]["fit"] or 0)
        if d:
            return -1 if d < 0 else 1
        return _cmp_id(a, b)
    hidden.sort(key=functools.cmp_to_key(hid_cmp))
    hide_counts = {}
    for it in hidden:
        for h in it["filters"]["hide"]:
            hide_counts[h["key"]] = hide_counts.get(h["key"], 0) + 1
    return {"candidate": cand, "prefs": prefs, "items": items, "visible": visible, "hidden": hidden, "hideCounts": hide_counts,
            "scanned": len(listings or []), "deduped": len(parsed) - len(merged), "poolSize": len(pool),
            "typeSkipped": type_skipped, "expired": expired, "excluded": len(merged) - len(pool)}


# ---------------------------------------------------- natural-language search
# Plain English in, editable chips out. Chips are rebuilt FROM the patch
# (chips_from_patch), so a chip always says what is really applied. "No X",
# "not X or Y", "anything but X" and "I don't want X" never turn into "only X";
# words we can't place only rank (never hide); "quoted words" must appear.
Q_STOP = ["requirements", "requirement", "required", "requiring", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "jobs", "job", "roles", "role", "positions", "position", "opportunities", "opportunity", "in", "at", "for", "a", "an", "the", "and", "or", "with", "near", "paying", "that", "pay", "pays", "salary", "find", "me", "show", "looking", "want", "i", "work", "working", "company", "companies", "openings", "opening", "hiring", "of", "to", "on", "who", "my", "some", "any", "please", "which", "where", "like", "something", "based", "around", "only", "just", "least", "more", "than", "over", "above", "under", "per", "year", "annually", "is", "are", "be", "can", "could", "would", "should", "get", "good", "great", "best", "new", "next", "within", "days", "day", "week", "posted", "type", "level", "from", "all", "it", "its", "help", "need", "needs", "having", "have", "has", "them", "they", "you", "your", "also", "into", "out", "up", "via", "as", "by", "k", "usd",
          "but", "non", "uses", "use", "using", "nothing", "older", "newer", "weeks", "months", "month", "hours", "hour", "ote", "thanks", "thank", "wanted", "prefer", "preferably", "ideally", "ok", "okay", "open", "interested", "experience", "experienced", "exp", "yoe", "years", "yrs", "listings", "listing", "posts", "postings", "post", "stuff", "things", "thing", "anything", "everything", "kind", "sort", "types", "similar", "related", "etc", "very", "really", "mostly", "mainly", "preferred", "required", "require", "requires", "needed", "ideal", "ones", "one", "those", "these", "this", "there", "here", "what", "when", "how", "do", "does", "doing", "will", "am", "was", "were", "been", "not", "no", "nor", "then", "too", "so", "such", "other", "others", "else", "either", "both", "each", "every", "few", "many", "much", "lots", "lot", "search", "searching", "seeking", "seek", "apply", "applying", "hire", "hired", "currently", "now", "asap", "immediately", "start", "starting", "available", "ever", "yet", "still", "most", "less", "fewer", "max", "min", "maximum", "minimum", "about", "roughly", "approximately", "between", "among", "without", "except", "excluding", "exclude", "avoid", "skip", "never", "zero", "minus", "old", "recent", "recently", "today", "must", "want", "wants", "id", "im", "ive"]
Q_STOP_SET = frozenset(Q_STOP)
LEVEL_ORDER = ["intern", "entry", "mid", "senior", "lead", "director", "exec"]
Q_LEVEL_WORDS = [
    ("intern", r"internships?|interns?|co-?ops?"),
    ("entry", r"entry-level|junior|juniors|jr\.?|new grads?|new graduates?|early[- ]career|graduate programs?|grad programs?|recent grads?|recent graduates?"),
    ("mid", r"mid-level|mid[- ]career|intermediate"),
    ("senior", r"senior|seniors|sr\.?"),
    ("lead", r"staff|principal|lead(?!\s*gen)"),
    ("director", r"directors?|head of"),
    ("exec", r"vp|vps|vice presidents?|svp|evp|c-suite|c-level|chief [a-z]+ officer"),
]
Q_TYPE_WORDS = [
    ("full_time", r"full-time|permanent|fte"),
    ("part_time", r"part-time|per diem|prn"),
    ("contract", r"contract[- ]to[- ]hire|contracts?|contractors?|contracting|c2h|freelance|freelancers?|freelancing|1099|gigs?"),
    ("temporary", r"temp[- ]to[- ]hire|temps?|temporary|seasonal"),
]
Q_MODE_WORDS = [("remote", r"remote|remotely"), ("hybrid", r"hybrid"), ("onsite", r"onsite")]
Q_LEVEL_RE = [(k, re.compile(r"(?<![a-z])(" + b + r")(?![a-z])"), re.compile(r"(?:" + b + r")(?:[- ]level)?")) for k, b in Q_LEVEL_WORDS]
Q_TYPE_RE = [(k, re.compile(r"(?<![a-z])(" + b + r")(?![a-z])"), re.compile(r"(?:" + b + r")(?: work)?")) for k, b in Q_TYPE_WORDS]
Q_MODE_RE = [(k, re.compile(r"(?<![a-z])(" + b + r")(?![a-z])"), re.compile(r"(?:" + b + r")(?: work| only| first| schedule)?")) for k, b in Q_MODE_WORDS]
Q_LEVEL_UP = {"intern": ["intern"], "entry": ["intern", "entry"], "mid": ["mid"], "senior": ["senior", "lead", "director", "exec"], "lead": ["lead", "director", "exec"], "director": ["director", "exec"], "exec": ["exec"]}
# words that say the same thing a few ways become one token first
Q_CANON = [
    (re.compile(r"(?<![a-z])(?:fully[- ]remote|100% remote|remote[- ]first|work(?:ing)?[- ]from[- ]home|wfh|telecommut(?:e|ing)|telework(?:ing)?)(?![a-z])"), "remote"),
    (re.compile(r"(?<![a-z])(?:on[- ]site|in[- ]office|in[- ]person|office[- ]based)(?![a-z])"), "onsite"),
    (re.compile(r"(?<![a-z])full[- ]?time(?![a-z])"), "full-time"),
    (re.compile(r"(?<![a-z])part[- ]?time(?![a-z])"), "part-time"),
    (re.compile(r"(?<![a-z])entry[- ]level(?![a-z])"), "entry-level"),
    (re.compile(r"(?<![a-z])mid[- ]level(?![a-z])"), "mid-level"),
]
Q_NORM = [
    (re.compile(r"(?<![a-z])w/o(?![a-z])"), "without"),
    (re.compile(r"(?<![a-z])no-(?=[a-z])"), "no "),
    # "I don't need sponsorship" is about you, not a filter
    (re.compile(r"(?<![a-z])(?:i\s+|we\s+)?(?:really\s+)?(?:do\s+not|don'?t|won'?t|will\s+not)\s+(?:need|require)\s+(?:a\s+|any\s+)?(?:visa\s+|h-?1b\s+)?(?:sponsorship|sponsor|visa)(?![a-z])"), " "),
    (re.compile(r"(?<![a-z])(?:no|without|not)\s+(?:needing\s+|requiring\s+)?(?:visa\s+|h-?1b\s+)?sponsorship(?:\s+(?:needed|required|necessary))?(?![a-z])"), " "),
    (re.compile(r"(?<![a-z])neither\s+"), " no "),
    (re.compile(r"(?<![a-z0-9])(?:four|4)[- ]day\s+(?:work\s*)?(?:weeks?|workweeks?)(?![a-z])"), " 4-day "),
    (re.compile(r"(?<![a-z])(?:i\s+|we\s+)?(?:really\s+)?(?:do\s+not|don'?t|won'?t|will\s+not|would\s+not|wouldn'?t)\s+(?:want|like|do|consider|take|accept)(?:\s+to\s+(?:work|be|do)(?:\s+(?:in|on|at|for|with|as))?)?(?:\s+(?:any|a|an))?\s+"), " no "),
    (re.compile(r"(?<![a-z])(?:that\s+|which\s+|who\s+)?(?:do\s+not|does\s+not|don'?t|doesn'?t)\s+(?:need|require|requires|ask\s+for|involve|include|use|mention)(?:\s+(?:any|a|an))?\s+"), " no "),
    (re.compile(r"(?<![a-z])(?:i'?m\s+|i\s+am\s+|am\s+)?not\s+(?:interested\s+in|into|looking\s+for|a\s+fan\s+of|keen\s+on|open\s+to)\s+"), " no "),
    (re.compile(r"(?<![a-z])(?:i\s+|we\s+)?(?:hate|dislike|loathe|despise)\s+"), " no "),
    (re.compile(r"(?<![a-z])(?:anything|everything|any\s+jobs?|anywhere|any\s+place|any\s+location|any\s+industry|any\s+company|any\s+role)\s+(?:but|except(?:\s+for)?|other\s+than|outside(?:\s+of)?|besides|apart\s+from)\s+"), " no "),
    (re.compile(r"(?<![a-z])(?:other\s+than|apart\s+from|aside\s+from|besides|except\s+for)\s+"), " no "),
    # "nothing in sales", "none in sales or marketing", "nothing to do with healthcare"
    (re.compile(r"(?<![a-z])(?:nothing|none)\s+(?:at\s+all\s+)?(?:in|to\s+do\s+with|related\s+to|involving|with|from|at)\s+"), " no "),
    # "stay away from sales", "steer clear of agencies", "keep me away from night shifts"
    (re.compile(r"(?<![a-z])(?:stay|keep(?:\s+me)?|steer)\s+(?:far\s+)?(?:away\s+from|clear\s+of)\s+"), " no "),
    # "no jobs that require relocation", "no roles requiring travel", "no jobs posted by staffing agencies"
    (re.compile(r"(?<![a-z])(?:no|not|without|exclude|excluding|avoid|avoiding|never|skip)\s+(?:jobs?|roles?|positions?|openings?|work|listings?|posts?|postings?|anything)\s+(?:that\s+|which\s+)?(?:require|requires|requiring|need|needs|needing|involve|involves|include|includes|including|mention|mentions|mentioning|posted\s+by|offered\s+by|listed\s+by)\s+(?:a\s+|an\s+|any\s+)?"), " no "),
]
Q_RELOC_PERK = re.compile(r"(?<![a-z])(?:(?:relocation|relo)\s+(?:assistance|package|support|bonus|stipend|help|benefits?|paid|covered)|(?:paid|covered)\s+relocation)(?![a-z])")
Q_RELOC_NO = re.compile(r"(?<![a-z])(?:(?:i\s+|we\s+)?(?:am\s+|'m\s+)?(?:no|not|never|without|don'?t\s+want\s+to|do\s+not\s+want\s+to|won'?t|will\s+not|can'?t|cannot|unable\s+to|not\s+willing\s+to|not\s+able\s+to|not\s+open\s+to|unwilling\s+to)\s+(?:to\s+)?(?:relocat(?:e|ing|ion)|move|moving))(?![a-z])")
Q_RELOC_YES = re.compile(r"(?<![a-z])(?:(?:open\s+to|willing\s+to|happy\s+to|can|will|able\s+to|ready\s+to|okay\s+with|ok\s+with|fine\s+with)\s+(?:relocat(?:e|ing|ion)|move|moving)|relocation\s+(?:is\s+)?(?:ok|okay|fine))(?![a-z])")
Q_NO_DEGREE = re.compile(r"(?<![a-z])(?:no\s+(?:a\s+|an\s+|any\s+)?(?:college\s+|4-year\s+|four-year\s+|bachelor'?s\s+|university\s+)?degrees?(?:\s+(?:required|needed|necessary))?|without\s+(?:a\s+)?degree|degree\s+not\s+(?:required|needed|necessary))(?![a-z])")
Q_NO_COMMUTE = re.compile(r"(?<![a-z])no\s+commut(?:e|ing)(?![a-z])")
Q_IC = re.compile(r"(?<![a-z])(?:individual[- ]contributor(?:\s+(?:roles?|positions?|jobs?|track|only))?|ic\s+(?:roles?|positions?|jobs?|track|only)|non[- ]management|non[- ]managerial|non[- ]manager)(?![a-z])")
# we can't tell a company's size from a posting - say so instead of guessing
Q_URL = re.compile(r'(?:https?://|www\.)[^\s"]+')   # a pasted link
Q_SIZE = re.compile(r"(?<![a-z])(?:big|large|huge|small|tiny|mid-?sized?|medium-?sized?|fortune\s+500|enterprise-?size[d]?)\s+(?:companies|company|firms?|employers?|orgs?|organi[sz]ations?|businesses|corporations?)(?![a-z])")
Q_GENERIC_ORG = frozenset(["inc", "llc", "ltd", "co", "corp", "corporation", "company", "group", "holdings", "labs", "lab", "solutions", "technologies", "technology", "tech", "systems", "services", "global", "international", "partners", "consulting", "software", "digital", "health", "care", "healthcare", "media", "studio", "studios", "network", "networks", "enterprises", "industries", "america", "americas", "usa", "the", "and", "remote", "remotely", "hybrid", "onsite", "office", "senior", "junior", "staff", "lead", "principal", "intern", "interns", "internship", "internships", "entry", "mid", "director", "head", "executive", "contract", "contractor", "freelance", "temp", "temporary", "seasonal", "permanent", "part", "full", "time", "confidential", "unknown", "stealth", "startup", "private", "employer", "anonymous", "client", "agency", "staffing", "recruiting", "talent", "careers", "people", "team", "national", "american", "united", "general", "capital", "financial", "bank", "insurance", "foundation", "institute", "university", "college", "school", "hospital", "medical", "center", "clinic", "city", "county", "state", "department", "data", "analytics", "cloud", "smart", "first", "one", "world", "worldwide", "sales", "marketing", "design", "engineering"])
Q_ORG_CUE = re.compile(r"(?:^|\s)(?:at|@|for|with|from|join|joining|no|not|without|exclude|excluding|except|avoid|avoiding|never|skip|minus)\s+\Z")
Q_ROLE_SHORT_OK = re.compile(r"(sdr|bdr|csm|tpm|apm|pmm|swe|sde|sre|ae|rn|lpn|cna|emt|ux|hr)")
Q_ROLE_ALIAS = {"pm": "product_manager", "pms": "product_manager", "np": "nurse", "nps": "nurse"}
Q_TITLE_NOUNS = ["analyst", "engineer", "designer", "scientist", "researcher"]
Q_POS_GROUP_WORDS = ["sales", "marketing", "operations", "ops", "hr", "human resources", "engineering", "design", "legal", "admin", "administrative", "trades", "skilled trades", "writing", "research", "data"]
X_GROUPS = {"sales": "sales", "marketing": "marketing", "engineering": "engineering", "software engineering": "engineering", "design": "design", "operations": "operations", "ops": "operations", "hr": "people", "human resources": "people", "customer service": "customer", "customer support": "customer", "admin": "admin", "administrative": "admin", "trades": "trades", "skilled trades": "trades", "legal": "legal", "writing": "content", "research": "research", "data": "data"}
GROUP_LABEL = {"engineering": "engineering", "physical_engineering": "hardware engineering", "data": "data", "finance": "finance", "product": "product", "operations": "operations", "design": "design", "marketing": "marketing", "sales": "sales", "customer": "customer service", "legal": "legal", "people": "HR", "consulting": "consulting", "admin": "admin", "it": "IT", "healthcare": "healthcare", "education": "education", "content": "writing", "research": "research", "trades": "skilled trades", "service": "service", "athletics": "coaching", "programs": "fellowship", "quality": "QA testing", "security": "security", "public_safety": "public safety", "nonprofit": "nonprofit", "real_estate": "real estate", "public_sector": "public sector"}
Q_INDUSTRY_NAMES = {"fintech": "fintech", "finance": "fintech", "banking": "fintech", "insurance": "fintech", "healthcare": "healthcare", "health care": "healthcare", "health tech": "healthcare", "healthtech": "healthcare", "digital health": "healthcare", "biotech": "biotech", "pharma": "biotech", "life sciences": "biotech", "edtech": "edtech", "education": "edtech", "e-commerce": "ecommerce", "ecommerce": "ecommerce", "retail": "ecommerce", "saas": "saas", "b2b saas": "saas", "enterprise software": "saas", "ai": "ai", "artificial intelligence": "ai", "ai startups": "ai", "media": "media", "entertainment": "media", "gaming": "gaming", "video games": "gaming", "government": "government", "public sector": "government", "nonprofit": "nonprofit", "non-profit": "nonprofit", "nonprofits": "nonprofit", "social impact": "nonprofit", "climate": "climate", "climate tech": "climate", "energy": "climate", "clean energy": "climate", "sustainability": "climate", "logistics": "logistics", "supply chain": "logistics", "manufacturing": "manufacturing", "real estate": "real_estate", "proptech": "real_estate", "hospitality": "hospitality", "travel": "hospitality", "consulting": "consulting", "cybersecurity": "security", "consumer tech": "consumer_tech", "telecom": "telecom", "legal tech": "legal_services", "food": "food", "sports": "sports", "fitness": "sports"}
CLEARANCE_PHRASES = ["security clearance", "clearance required", "ts/sci", "top secret"]
Q_ST_BAD_POS = ["in", "or", "me", "oh", "ok", "hi", "id", "us"]
Q_ST_BAD_NEG = ["in", "or", "me", "oh", "ok", "hi", "id", "us", "co", "de", "al", "ms", "ma", "pa", "mo", "md", "mt", "ar", "ga", "la"]
Q_NUMWORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a couple of": 2, "a couple": 2, "couple of": 2, "a few": 3, "few": 3}
NUMW = r"([0-9]{1,3}|a couple of|a couple|couple of|a few|few|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|an|a)"


def _numv(t):
    return int(t) if re.fullmatch(r"[0-9]+", t) else (Q_NUMWORDS.get(t) or None)


# freshness
Q_FRESH_N = re.compile(r"(?<![a-z])(?:(?:nothing|no|not|none)\s+older\s+than|(?:posted\s+)?(?:with)?in\s+(?:the\s+)?(?:last|past)|(?:posted\s+)?within|(?:in\s+|over\s+|from\s+)?the\s+(?:last|past)|last|past|(?:less|fewer)\s+than|under|at\s+most|up\s+to|no\s+more\s+than)\s+" + NUMW + r"\s+(hours?|hrs?|days?|weeks?|wks?|months?)(?:\s+old)?(?![a-z])")
Q_FRESH_OLDER = re.compile(r"(?<![a-z])older\s+than\s+" + NUMW + r"\s+(?:hours?|hrs?|days?|weeks?|wks?|months?)(?![a-z])")
Q_FRESH = [
    (1, re.compile(r"(?<![a-z])(today|last 24 hours|past 24 hours|past day|last day)(?![a-z])")),
    (3, re.compile(r"(?<![a-z])(last (3|three) days|past (3|three) days|just posted|newly posted)(?![a-z])")),
    (7, re.compile(r"(?<![a-z])(this week|last week|past week|last 7 days|past 7 days|last seven days|recently posted|posted recently)(?![a-z])")),
    (14, re.compile(r"(?<![a-z])(last (2|two) weeks|past (2|two) weeks|last 14 days)(?![a-z])")),
    (30, re.compile(r"(?<![a-z])(this month|last month|past month|last 30 days)(?![a-z])")),
]
# years of experience
Q_YRS = r"(?:years?|yrs?|yoe)"
Q_EXPW = r"(?:\s+(?:of\s+)?(?:(?:work|professional|relevant|industry|prior|previous|related)\s+)?(?:experience|exp)(?![a-z]))"
Q_YRS_ZERO = re.compile(r"(?<![a-z0-9.])(?:(?:no|zero|without)\s+(?:prior\s+|previous\s+|work\s+|professional\s+|relevant\s+)?(?:experience|exp)(?:\s+(?:needed|required|necessary))?|0\s+(?:years?|yrs?)(?:\s+(?:of\s+)?experience)?|experience\s+not\s+(?:needed|required|necessary))(?![a-z])")
Q_YRS_MIN = re.compile(r"(?<![a-z])(?:no\s+less\s+than|not\s+less\s+than|at\s+least|minimum(?:\s+of)?|min\.?|over|(?<!no\s)(?<!not\s)more\s+than)\s+" + NUMW + r"\s*\+?\s*" + Q_YRS + r"(?![a-z])" + Q_EXPW + "?")
Q_YRS_RANGE = re.compile(r"(?<![0-9.])([0-9]{1,2})\s*(?:-|to)\s*([0-9]{1,2})\s*\+?\s*" + Q_YRS + r"(?![a-z])" + Q_EXPW + "?")
Q_YRS_CEIL = re.compile(r"(?<![a-z])(less\s+than|fewer\s+than|under|below|at\s+most|no\s+more\s+than|not\s+more\s+than|up\s+to|max(?:imum)?(?:\s+of)?|<=?)\s*" + NUMW + r"\s*\+?\s*" + Q_YRS + r"(?![a-z])" + Q_EXPW + "?")
Q_YRS_POST = re.compile(r"(?<![a-z0-9])" + NUMW + r"\s*\+?\s*" + Q_YRS + r"(?![a-z])" + Q_EXPW + r"?\s+(?:or\s+less|or\s+fewer|or\s+under|max(?:imum)?|at\s+most|tops)(?![a-z])")
Q_YRS_HAVE = re.compile(r"(?<![a-z])(?:i\s+have|i've\s+got|i\s+have\s+got|with|have|having)\s+(?:about\s+|around\s+|roughly\s+|~\s*)?" + NUMW + r"\s*\+?\s*" + Q_YRS + r"(?![a-z])" + Q_EXPW + "?")
Q_YRS_BARE = re.compile(r"(?<![a-z0-9])" + NUMW + r"\s*\+?\s*" + Q_YRS + r"(?![a-z])" + Q_EXPW)
# travel
Q_TRAVEL_W = r"(?:travel|traveling|travelling)"
Q_TRAVEL = [
    (re.compile(r"(?<![a-z])(?:no|zero|without|not)\s+(?:any\s+)?" + Q_TRAVEL_W + r"(?:\s+(?:required|needed|necessary|involved))?(?=\s*(?:$|[,;.]|(?:and|or|but|please|jobs?|roles?|positions?|work)(?![a-z])))"), 0),
    (re.compile(r"(?<![a-z])(?:little\s+to\s+no|little\s+or\s+no|minimal|minimum|little|light|limited|low|rare|infrequent)\s+" + Q_TRAVEL_W + r"(?![a-z])"), 10),
    (re.compile(r"(?<![a-z])(?:occasional|some|moderate)\s+" + Q_TRAVEL_W + r"(?![a-z])"), 25),
]
Q_TRAVEL_PCT = re.compile(r"(?<![a-z0-9])(?:(?:less\s+than|under|below|up\s+to|at\s+most|no\s+more\s+than|max(?:imum)?(?:\s+of)?|<=?)\s*([0-9]{1,3})\s*%\s*(?:of\s+(?:the\s+)?time\s+)?" + Q_TRAVEL_W + r"|" + Q_TRAVEL_W + r"\s*(?:of\s+)?(?:less\s+than|under|below|up\s+to|at\s+most|no\s+more\s+than|max(?:imum)?(?:\s+of)?|<=?)\s*([0-9]{1,3})\s*%|([0-9]{1,3})\s*%\s*" + Q_TRAVEL_W + r"(?:\s+(?:or\s+less|max|at\s+most))?)(?![a-z])")
# distance: "within 50 miles of Austin" -> near Austin (metro areas already cover the commute belt)
Q_NEAR = re.compile(r"(?<![a-z])(?:(?:within|in)\s+(?:a\s+)?(?:[0-9]{1,3}|one|two|three|four|five|ten|fifteen|twenty|thirty|forty|fifty|sixty)\s*(?:miles?|mi|km|kms|kilometers?|kilometres?|minutes?|mins?|hours?|hrs?)\s+(?:drive\s+time\s+|drive\s+|commute\s+|radius\s+)?(?:of|from|around|to)|[0-9]{1,3}\s*(?:miles?|mi|km)\s+(?:radius\s+of|radius\s+around|of|from|around)|(?:commutable|commuting\s+distance|driving\s+distance|close|nearby|near)\s+(?:to|of|from))\s+")
# pay
Q_SAL_FLOOR = r"no\s+less\s+than|not\s+less\s+than|not\s+below|not\s+under|nothing\s+below|nothing\s+under|no\s+lower\s+than|at\s+least|min(?:imum)?(?:\s+of)?|more\s+than|starting\s+at|starting\s+from|starts\s+at|north\s+of|upwards\s+of|in\s+excess\s+of|over|above|from|>=?"
Q_SAL_CEIL = r"no\s+more\s+than|not\s+more\s+than|not\s+above|not\s+over|nothing\s+above|nothing\s+over|no\s+higher\s+than|less\s+than|lower\s+than|south\s+of|at\s+most|up\s+to|max(?:imum)?(?:\s+of)?|under|below|<=?"
Q_SAL_POSTF = r"\+|plus|or\s+more|or\s+above|or\s+higher|and\s+up|and\s+above|minimum|min|at\s+least"
Q_SAL_POSTC = r"or\s+less|or\s+below|or\s+lower|or\s+under|and\s+under|and\s+below|max(?:imum)?|at\s+most|tops"
Q_SAL_FLOOR_ONLY = re.compile(r"(?:" + Q_SAL_FLOOR + r")")
Q_SAL_POSTF_ONLY = re.compile(r"(?:" + Q_SAL_POSTF + r")")
Q_SAL_HR = re.compile(r"(?<![a-z0-9.$])(?:(" + Q_SAL_FLOOR + "|" + Q_SAL_CEIL + r")\s*)?(\$?)\s?([0-9]{1,3}(?:\.[0-9]{1,2})?)(?:\s*(?:-|to)\s*\$?\s?([0-9]{1,3}(?:\.[0-9]{1,2})?))?\s*(?:/\s*|per\s+|an\s+|a\s+)(?:hour|hr|h)(?![a-z])(?:\s*(" + Q_SAL_POSTF + "|" + Q_SAL_POSTC + r")(?![a-z]))?")
Q_SAL_RANGE = re.compile(r"(?<![a-z0-9.$])(between\s+)?\$?\s?([0-9]{2,3}(?:\.[0-9])?)\s*(k|,000|000)?\s*(-|to|and)\s*\$?\s?([0-9]{2,3}(?:\.[0-9])?)\s*(k|,000|000)(?![0-9a-z])")
Q_SAL_ONE = re.compile(r"(?<![a-z0-9.$])(?:(" + Q_SAL_FLOOR + "|" + Q_SAL_CEIL + r")\s*)?(\$?)\s?([0-9]{2,3}(?:\.[0-9])?)\s*(k|,000|000)(?![0-9a-z])(?:\s*(" + Q_SAL_POSTF + "|" + Q_SAL_POSTC + r")(?![a-z]))?")
Q_SAL_SIX = re.compile(r"(?<![a-z])(?:(" + Q_SAL_FLOOR + "|" + Q_SAL_CEIL + r")\s*)?(?:a\s+)?(?:six|6)[- ]figures?(?:\s+(?:salary|income|pay))?(?![a-z])")
# "no X" scopes
Q_EXCL_LEAD = re.compile(r"(?<![a-z])(no|not|without|exclude|excluding|avoid|avoiding|never|skip|except)\s+(?:jobs?|roles?|positions?|openings?|work|listings?|posts?|postings?)\s+(at|in|with|from|for|as|on|involving)\s+")
# "not at Amazon": a name after "at" is an employer even when no listing has it
# yet - unless it's a kind of employer or a time
Q_ORG_KIND = re.compile(r"(?:(?:big|large|small|tiny|early[- ]stage|late[- ]stage|public|private|federal|local|tech)\s+)?(?:start-?ups?|agenc(?:y|ies)|banks?|tech|big\s+tech|faang|maang|non-?profits?|charit(?:y|ies)|government|hospitals?|clinics?|schools?|universit(?:y|ies)|colleges?|consultanc(?:y|ies)|consulting(?:\s+firms?)?|firms?|compan(?:y|ies)|corporations?|corporates?|enterprises?|retailers?|restaurants?|stores?|warehouses?|home|night|nights|weekends?|all|scale|random|once|first|least|most|times?)")
Q_NEG_RE = re.compile(r"(?<![a-z])(?:no|not|without|exclude|excluding|except|minus|skip|avoid|avoiding|never|zero)\s+")
Q_ITEM_PRE = re.compile(r"(?:(?:in|at|for|with|any|a|an|the|too|very|so|really|more|much|many|of|to|be|being|doing)\s+)*")
Q_WORD = "[a-z0-9§][a-z0-9&.+#'/§-]*"
Q_ITEM_STOPW = r"(?:and|or|nor|but|in|at|with|near|over|under|above|below|paying|that|which|who|posted|from|for|remote|hybrid|onsite|no|not|without|exclude|excluding|except|never|avoid|avoiding|skip|minus|zero|please|only|just|is|are)"
Q_ITEM = re.compile(Q_WORD + r"(?:\s+(?!" + Q_ITEM_STOPW + r"(?![a-z0-9]))" + Q_WORD + r"){0,5}")
Q_SEP = re.compile(r"\s*(?:,\s*(?:(and/or|and|or|nor)\s+)?|(and/or|and|or|nor)\s+)")
Q_ITEM_POST = re.compile(r"\s+(?:jobs?|roles?|positions?|openings?|work|companies|company|industry|industries|stuff|things|please|anymore|related|heavy|focused|oriented|people|listings?|posts?|postings?|types?|requirements?|required|requiring)\Z")
Q_POS_KINDS = {"mode", "level", "type", "location"}
Q_SPECIAL = [
    ("agencies", re.compile(r"(?:(?:staffing|recruiting|recruitment)\s+)?(?:agenc(?:y|ies)|recruiters?|headhunters?|staffing(?:\s+(?:agencies|firms|companies))?|third[- ]party(?:\s+recruiters?)?|3rd[- ]party(?:\s+recruiters?)?)")),
    ("reposts", re.compile(r"(?:reposts?|re-?posted(?:\s+(?:jobs|posts|listings))?)")),
    ("ghost", re.compile(r"(?:ghost(?:\s+(?:jobs|posts|listings))?|ghosts|stale(?:\s+(?:jobs|posts|listings))?|old\s+(?:posts|listings|jobs)|fake(?:\s+(?:jobs|posts|listings))?)")),
    ("evergreen", re.compile(r"(?:evergreen(?:\s+(?:posts|jobs|listings|roles))?|talent\s+pools?|talent\s+communit(?:y|ies))")),
    ("travel", re.compile(r"(?:travel|traveling|travelling)")),
    ("clearance", re.compile(r"(?:(?:security|government|active|secret|top\s+secret)\s+)?clearances?(?:\s+required)?|(?:ts/sci|top\s+secret)")),
    ("management", re.compile(r"(?:(?:people|team|staff)\s+)?management(?:\s+roles?)?|(?:managing(?:\s+(?:people|a\s+team|teams|others))?|managers?|manager\s+roles?|people\s+managers?|direct\s+reports|supervis(?:ing|ory|ion)(?:\s+roles?)?|leading\s+(?:a\s+)?teams?)")),
]
Q_PHRASE_SPECIAL = re.compile(r"(?:cold\s+call(?:ing|s)?|commission(?:[- ]only|\s+based|\s+heavy)?|door[- ]to[- ]door|mlm|multi[- ]level\s+marketing)")
Q_MODE_OFFICE = re.compile(r"(?:office|offices|the\s+office|office\s+jobs)")
_Q_CS_LOW = None


def _q_stop(w):
    return w in Q_STOP_SET


def _q_cs_low():
    # case-sensitive skill words ("Excel", "Spark", "SAS") are plain in a lower-case search box
    global _Q_CS_LOW
    if _Q_CS_LOW is not None:
        return _Q_CS_LOW
    o = {}
    for sk in TAX["skills"]:
        if sk.get("kind") == "soft":
            continue
        for a in sk.get("cs") or []:
            l = lc(a)
            if (_js_len(l) >= 3 or l == "js") and l not in o:
                o[l] = sk["id"]
    _Q_CS_LOW = o
    return o


def _q_parser_word(t):
    I = idx()
    return bool(t in I.role_map or t in I.alias_map or t in _q_cs_low() or t in Q_INDUSTRY_NAMES or t in X_GROUPS
                or t in I.metro_map or t in I.state_by_name or _q_stop(t) or t in Q_GENERIC_ORG)


def _q_distinctive(form):
    for t in re.split(r"[^a-z0-9]+", form):
        if _js_len(t) >= 3 and not re.fullmatch(r"[0-9]+", t) and not _q_parser_word(t):
            return True
    return False


def _title_case(nm):
    return re.sub(r"(^| )[a-z]", lambda m: m.group(0).upper(), nm)


def _cap_first(x):
    return x[0].upper() + x[1:] if x else x


def mode_name(m):
    return "On-site" if m == "onsite" else _cap_first(m)


def _q_place_of(w, bad):
    I = idx()
    mid = I.metro_map.get(w)
    if mid:
        return I.metro[mid]["name"]
    if w in I.state_by_name:
        return _title_case(w)
    if re.fullmatch(r"[a-z]{2}", w) and w.upper() in TAX["us_states"] and w not in bad:
        return w.upper()
    return None


def _q_skill_of(w):
    I = idx()
    sid = I.alias_map.get(w) or _q_cs_low().get(w) or None
    if not sid and _js_len(w) > 3 and w[-1] == "s":
        sid = I.alias_map.get(w[:-1]) or None
    return sid if (sid and sid in I.skill and I.skill[sid].get("kind") != "soft") else None


def _q_role_of(w):
    I = idx()
    a = Q_ROLE_ALIAS.get(w)
    if a:
        return a
    r = I.role_map.get(w) or (I.role_map.get(w[:-1]) if (_js_len(w) > 3 and w[-1] == "s") else None)
    return r or None


def _q_group_ids(g):
    return [r["id"] for r in TAX["roles"] if r.get("group") == g]


@functools.lru_cache(maxsize=16)
def _q_noun_ids_t(n):
    rx = re.compile(r"(?<![a-z])" + n + r"(?![a-z])")
    return tuple(r["id"] for r in TAX["roles"] if rx.search(lc(r["name"])))


def _q_noun_ids(n):
    return list(_q_noun_ids_t(n))


def _q_noun_of(w):
    for n in Q_TITLE_NOUNS:
        if w == n or w == n + "s":
            return n
    return None


def _q_org_for(w, orgs):
    if not isinstance(orgs, list):
        return None
    nw = norm_org(w)
    for o in orgs:
        o = _s(o).strip()
        if o and (lc(o) == w or (nw and norm_org(o) == nw)):
            return o
    return None


def _q_classify(w, found, orgs):
    """What "no X" most likely means, most specific first."""
    ph = re.fullmatch("§([0-9]+)§", w)
    if ph:
        return {"kind": "company", "org": found[int(ph.group(1))]}
    for name, rx in Q_SPECIAL:
        if rx.fullmatch(w):
            return {"kind": "special", "what": name}
    if Q_PHRASE_SPECIAL.fullmatch(w):
        return {"kind": "phrase", "w": w}
    for k, _r, full in Q_MODE_RE:
        if full.fullmatch(w):
            return {"kind": "mode", "v": k}
    if Q_MODE_OFFICE.fullmatch(w):
        return {"kind": "mode", "v": "onsite"}
    for k, _r, full in Q_LEVEL_RE:
        if full.fullmatch(w):
            return {"kind": "level", "v": k}
    for k, _r, full in Q_TYPE_RE:
        if full.fullmatch(w):
            return {"kind": "type", "v": k}
    org = _q_org_for(w, orgs)
    if org:
        return {"kind": "company", "org": org}
    pl = _q_place_of(w, Q_ST_BAD_NEG)
    if pl:
        return {"kind": "location", "v": pl}
    ind = Q_INDUSTRY_NAMES.get(w)
    if ind:
        return {"kind": "industry", "v": ind}
    grp = X_GROUPS.get(w)
    if grp:
        return {"kind": "role", "ids": _q_group_ids(grp)}
    rid = _q_role_of(w)
    if rid:
        return {"kind": "role", "ids": [rid]}
    noun = _q_noun_of(w)
    if noun:
        return {"kind": "role", "ids": _q_noun_ids(noun)}
    sid = _q_skill_of(w)
    if sid:
        return {"kind": "skill", "v": sid}
    if _js_len(w) >= 3 and not _q_stop(w) and re.search(r"[a-z]", w):
        return {"kind": "phrase", "w": w}
    return {"kind": "none"}


def _q_continues(pk, k, sep):
    if sep == "comma":
        return pk == k and k not in Q_POS_KINDS and k != "phrase" and k != "none"
    if sep == "and":
        return pk == k
    if pk == k:
        return True
    return k not in Q_POS_KINDS and pk not in Q_POS_KINDS


def _q_clean_item(w):
    w = re.sub(r"[.']+\Z", "", w).strip()
    for _ in range(3):
        w2 = Q_ITEM_POST.sub("", w, count=1)
        if w2 == w or not w2:
            break
        w = w2
    return w


def _q_list_end(s, pos):
    """'no sales, marketing or design' is one list: look ahead for the word that closes it."""
    for _ in range(8):
        pm = Q_ITEM_PRE.match(s, pos)
        if pm:
            pos += len(pm.group(0))
        im = Q_ITEM.match(s, pos)
        if not im:
            return None
        pos += len(im.group(0))
        sm = Q_SEP.match(s, pos)
        if not sm:
            return None
        w = sm.group(1) or sm.group(2)
        if w:
            return "and" if w == "and" else "or"
        pos += len(sm.group(0))
    return None


def _q_cut(raw, n):
    # first n UTF-16 units, never ending on half an emoji (same as the browser)
    b = raw.encode("utf-16-le", "surrogatepass")
    if len(b) <= 2 * n:
        return raw
    cut = n
    cu = b[2 * (n - 1)] | (b[2 * (n - 1) + 1] << 8)
    if 0xD800 <= cu <= 0xDBFF:
        cut = n - 1
    return b[:2 * cut].decode("utf-16-le", "surrogatepass")


def _q_numf(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def parse_query(q, opts=None):
    opts = opts or {}
    I = idx()
    raw = _s(q).strip()
    raw_cut = _q_cut(raw, 400)
    patch, roles, ignored, hard, rank, ignored_why = {}, [], [], [], [], {}
    orgs_opt = opts.get("orgs")

    def add_to(key, vals):
        patch[key] = uniq((patch.get(key) or []) + list(vals))

    def add_roles(ids):
        for r in ids:
            if r not in roles:
                roles.append(r)

    low0 = re.sub("[–—−]", "-", re.sub("[“”″]", '"', re.sub("[‘’‛′]", "'", lc(raw_cut))))
    # a pasted link isn't a search: its words (".../greenhouse.io/...") would read as skills or places
    url_n = [0]

    def _drop_url(m):
        if url_n[0] < 3:
            t = trunc(m.group(0), 60)
            if t not in ignored:
                ignored.append(t)
                ignored_why[t] = "url"
        url_n[0] += 1
        return " "
    low0 = Q_URL.sub(_drop_url, low0)
    # "exact words" in quotes must appear in the posting
    for qm in re.finditer(r'"([^"]{2,60})"', low0):
        qt = re.sub(r"\s+", " ", qm.group(1)).strip()
        if _js_len(qt) >= 2 and qt not in hard:
            hard.append(qt)
    s = " " + re.sub(r"\s+", " ", re.sub("[!?\"§]+", " ", re.sub(r'"([^"]{2,60})"', " ", low0))) + " "
    for rx, rep in Q_NORM:
        s = rx.sub(rep, s)
    for rx, rep in Q_CANON:
        s = rx.sub(rep, s)
    s = re.sub(r"\s+", " ", s)
    # things that read like "no X" but aren't exclusions
    if Q_RELOC_PERK.search(s):
        rank.append("relocation")
        s = Q_RELOC_PERK.sub(" ", s)
    if Q_RELOC_NO.search(s):
        patch["relocate"] = False
        patch["locationRule"] = "hide"
        s = Q_RELOC_NO.sub(" ", s)
    elif Q_RELOC_YES.search(s):
        patch["relocate"] = True
        s = Q_RELOC_YES.sub(" ", s)
    if Q_NO_DEGREE.search(s):
        rank.append("no degree")
        s = Q_NO_DEGREE.sub(" ", s)
    s = Q_NO_COMMUTE.sub(" remote ", s)
    if Q_IC.search(s):
        patch["avoidManagement"] = True
        s = Q_IC.sub(" ", s)
    for szm in Q_SIZE.finditer(s):
        ignored.append(szm.group(0).strip())
        ignored_why[szm.group(0).strip()] = "size"
    s = Q_SIZE.sub(" ", s)
    # company names from the pool first - "Senior Helpers" is a company, not a level
    found = []
    if isinstance(orgs_opt, list):
        forms, seen_f = [], set()
        for oi, o in enumerate(orgs_opt):
            o = _s(o).strip()
            if not o:
                continue
            lo = re.sub(r"\s+", " ", re.sub("[–—−]", "-", lc(o)))
            for f in (lo, re.sub(r"[^a-z0-9)]+\Z", "", lo), norm_org(o)):
                f = f.strip()
                if _js_len(f) < 3 or re.fullmatch(r"[0-9]+", f) or _q_stop(f) or f in seen_f:
                    continue
                seen_f.add(f)
                forms.append((f, o, oi))
        forms.sort(key=lambda x: (-_js_len(x[0]), x[0].encode("utf-16-be", "surrogatepass"), x[2]))
        for f, o, _oi in forms:
            if f not in s:
                continue
            safe = (_q_distinctive(f) and f not in I.role_map and f not in I.alias_map and f not in Q_INDUSTRY_NAMES
                    and f not in I.metro_map and f not in I.state_by_name and f not in X_GROUPS)
            out, last = "", 0
            for m in re.finditer(B4 + esc_re(f) + AF, s):
                if not safe and not Q_ORG_CUE.search(s[:m.start()]):
                    continue
                if o not in found:
                    found.append(o)
                n = found.index(o)
                out += s[last:m.start()] + " §" + str(n) + "§ "
                last = m.end()
            if last:
                s = re.sub(r"\s+", " ", out + s[last:])
    # pay
    floors, ceils, target, hourly = [], [], None, False
    for mm in Q_SAL_HR.finditer(s):
        hv = float(mm.group(3))
        hv2 = float(mm.group(4)) if mm.group(4) else None
        if not (7 <= hv <= 500):
            continue
        hourly = True
        hceil = bool((mm.group(1) and not Q_SAL_FLOOR_ONLY.fullmatch(mm.group(1))) or (mm.group(5) and not Q_SAL_POSTF_ONLY.fullmatch(mm.group(5))))
        if hv2 is not None and hv2 > hv and hv2 <= 500:
            floors.append(rhu(hv * 2080))
            target = rhu(hv2 * 2080)
            ceils.append(rhu(hv2 * 2080))
        elif hceil:
            ceils.append(rhu(hv * 2080))
        else:
            floors.append(rhu(hv * 2080))
        s = s.replace(mm.group(0), " ", 1)
    for mm in Q_SAL_RANGE.finditer(s):
        if mm.group(4) == "and" and not mm.group(1):
            continue
        lo = float(mm.group(2)) * 1000
        hi = float(mm.group(5)) * 1000
        if not (lo >= 15000 and hi > lo and hi <= 900000):
            continue
        floors.append(_q_numf(lo))
        target = _q_numf(hi)
        ceils.append(_q_numf(hi))
        s = s.replace(mm.group(0), " ", 1)
        break
    for mm in Q_SAL_ONE.finditer(s):
        v = float(mm.group(3)) * 1000
        if not mm.group(2) and mm.group(3) == "401" and mm.group(4) == "k":
            continue  # a 401(k), not a salary
        if not (15000 <= v <= 900000):
            continue
        if (mm.group(1) and not Q_SAL_FLOOR_ONLY.fullmatch(mm.group(1))) or (mm.group(5) and not Q_SAL_POSTF_ONLY.fullmatch(mm.group(5))):
            ceils.append(_q_numf(v))
        else:
            floors.append(_q_numf(v))
        s = s.replace(mm.group(0), " ", 1)
    for mm in Q_SAL_SIX.finditer(s):
        if mm.group(1) and not Q_SAL_FLOOR_ONLY.fullmatch(mm.group(1)):
            ceils.append(100000)
        else:
            floors.append(100000)
        s = s.replace(mm.group(0), " ", 1)
    fl = max(floors) if floors else None
    ce = min(ceils) if ceils else None
    if fl is not None and ce is not None and ce < fl:
        ce = None
    if fl is not None:
        patch["salaryFloor"] = fl
        if target is not None and target > fl:
            patch["salaryTarget"] = target
    if ce is not None:
        patch["salaryCeiling"] = ce
    if fl is not None or ce is not None:
        patch["salaryRule"] = "hide"
        if hourly:
            patch["salaryUnit"] = "hour"
    # years of experience
    if Q_YRS_ZERO.search(s):
        patch["maxYears"] = 0
        patch["yearsRule"] = "hide"
        s = Q_YRS_ZERO.sub(" ", s)
    ym = Q_YRS_MIN.search(s)
    if ym:
        ignored.append(ym.group(0).strip())
        ignored_why[ym.group(0).strip()] = "years_min"
        s = s.replace(ym.group(0), " ", 1)
    if patch.get("maxYears") is None:
        ym = Q_YRS_RANGE.search(s)
        if ym:
            y1, y2 = int(ym.group(1)), int(ym.group(2))
            if y2 >= y1 and y2 <= 30:
                patch["maxYears"] = y2
                patch["yearsRule"] = "hide"
            s = s.replace(ym.group(0), " ", 1)
        else:
            ym = Q_YRS_CEIL.search(s)
            if ym:
                yc = _numv(ym.group(2))
                if yc is not None and yc <= 30:
                    strict = bool(re.match(r"(less|fewer|under|below|<)", ym.group(1))) and "<=" not in ym.group(1)
                    patch["maxYears"] = max(0, yc - 1) if strict else yc
                    patch["yearsRule"] = "hide"
                s = s.replace(ym.group(0), " ", 1)
            else:
                ym = Q_YRS_POST.search(s)
                if ym:
                    yp = _numv(ym.group(1))
                    if yp is not None and yp <= 30:
                        patch["maxYears"] = yp
                        patch["yearsRule"] = "hide"
                    s = s.replace(ym.group(0), " ", 1)
                else:
                    ym = Q_YRS_HAVE.search(s) or Q_YRS_BARE.search(s)
                    if ym:
                        yh = _numv(ym.group(1))
                        if yh is not None and yh <= 30:
                            patch["maxYears"] = yh
                            patch["yearsRule"] = "rank"
                        s = s.replace(ym.group(0), " ", 1)
    # travel
    for rx, val in Q_TRAVEL:
        if rx.search(s):
            if patch.get("maxTravel") is None:
                patch["maxTravel"] = val
            s = rx.sub(" ", s)
    tm = Q_TRAVEL_PCT.search(s)
    if tm:
        tv = int(tm.group(1) or tm.group(2) or tm.group(3))
        if tv <= 100 and patch.get("maxTravel") is None:
            patch["maxTravel"] = tv
        s = s.replace(tm.group(0), " ", 1)
    # freshness
    fm = Q_FRESH_N.search(s)
    if fm:
        fnum, unit = _numv(fm.group(1)), fm.group(2)
        if fnum:
            days = math.ceil(fnum / 24) if unit.startswith("h") else (fnum * 7 if unit.startswith("w") else (fnum * 30 if unit.startswith("m") else fnum))
            patch["postedWithin"] = min(365, max(1, days))
        s = s.replace(fm.group(0), " ", 1)
    fo2 = Q_FRESH_OLDER.search(s)
    if fo2:
        ignored.append(fo2.group(0).strip())
        ignored_why[fo2.group(0).strip()] = "older"
        s = s.replace(fo2.group(0), " ", 1)
    if patch.get("postedWithin") is None:
        for days, rx in Q_FRESH:
            if rx.search(s):
                patch["postedWithin"] = days
                s = rx.sub(" ", s)
                break
    s = re.sub(r"\s+", " ", Q_NEAR.sub(" near ", s))
    # exclusions: a negation covers a whole "X, Y or Z" list
    s = Q_EXCL_LEAD.sub(lambda m: m.group(1) + (" at " if m.group(2) == "at" else " "), s)
    neg_modes, neg_levels, neg_types, cuts = [], [], [], []

    def org_cased(w):
        """An employer named after "at", in the casing it was typed."""
        at = lc(raw_cut).find(w)
        o = raw_cut[at:at + len(w)] if at >= 0 else ""
        return o if (o and lc(o) == w and o != w) else _title_case(w)

    def at_org(c, w):
        return {"kind": "company", "org": org_cased(w)} if (c["kind"] == "phrase" and not Q_ORG_KIND.fullmatch(w)) else c
    pos0 = 0
    while True:
        nm = Q_NEG_RE.search(s, pos0)
        if not nm:
            break
        start, pos = nm.start(), nm.end()
        items, end, prev_kind = [], pos, None
        pm0 = Q_ITEM_PRE.match(s, pos)
        if pm0:
            pos += len(pm0.group(0))
        at_list = bool(pm0 and re.fullmatch(r"at\s+", pm0.group(0)))
        im = Q_ITEM.match(s, pos)
        if im:
            w0 = _q_clean_item(im.group(0))
            c0 = _q_classify(w0, found, orgs_opt)
            if at_list:
                c0 = at_org(c0, w0)
            items.append(c0)
            prev_kind = c0["kind"]
            end = pos + len(im.group(0))
            for _ in range(12):
                sm = Q_SEP.match(s, end)
                if not sm:
                    break
                wsep = sm.group(1) or sm.group(2)
                sep = ("and" if wsep == "and" else "or") if wsep else "comma"
                if sep == "comma":
                    sep = _q_list_end(s, end + len(sm.group(0))) or "comma"
                j = end + len(sm.group(0))
                pm1 = Q_ITEM_PRE.match(s, j)
                if pm1:
                    j += len(pm1.group(0))
                im2 = Q_ITEM.match(s, j)
                if not im2:
                    break
                w2 = _q_clean_item(im2.group(0))
                c2 = _q_classify(w2, found, orgs_opt)
                if at_list:
                    c2 = at_org(c2, w2)
                if not _q_continues(prev_kind, c2["kind"], sep):
                    break
                items.append(c2)
                prev_kind = c2["kind"]
                end = j + len(im2.group(0))
        for c in items:
            k = c["kind"]
            if k == "company":
                add_to("blockedCompanies", [c["org"]])
            elif k == "special":
                w = c["what"]
                if w == "agencies":
                    patch["hideAgencies"] = True
                elif w == "reposts":
                    patch["hideReposts"] = True
                elif w == "ghost":
                    patch["ghostRule"] = "hide"
                elif w == "evergreen":
                    patch["hideEvergreen"] = True
                elif w == "travel":
                    if patch.get("maxTravel") is None:
                        patch["maxTravel"] = 0
                elif w == "clearance":
                    add_to("excludePhrases", CLEARANCE_PHRASES)
                elif w == "management":
                    patch["avoidManagement"] = True
            elif k == "mode":
                if c["v"] not in neg_modes:
                    neg_modes.append(c["v"])
            elif k == "level":
                for x in Q_LEVEL_UP[c["v"]]:
                    if x not in neg_levels:
                        neg_levels.append(x)
                if c["v"] == "intern" and "internship" not in neg_types:
                    neg_types.append("internship")
            elif k == "type":
                if c["v"] not in neg_types:
                    neg_types.append(c["v"])
            elif k == "location":
                add_to("excludePlaces", [c["v"]])
            elif k == "industry":
                add_to("avoidIndustries", [c["v"]])
            elif k == "role":
                add_to("excludeRoles", c["ids"])
            elif k == "skill":
                add_to("excludeSkills", [c["v"]])
            elif k == "phrase":
                add_to("excludePhrases", [c["w"]])
        cuts.append((start, end))
        pos0 = max(end, nm.end())
    for a, b in reversed(cuts):
        s = s[:a] + " " + s[b:]
    s = re.sub(r"\s+", " ", s)
    # what's left is what you DO want
    if re.search(r"(?<![a-z])(visa sponsorship|sponsors?\s+visas?|sponsorships?|sponsors?|sponsoring|h-?1b|stem opt|opt|cpt)(?![a-z])", s):
        patch["needsSponsorship"] = True
        patch["authRule"] = "hide"
        s = re.sub(r"(?<![a-z])(?:that\s+|who\s+|which\s+)?(?:offers?\s+|provides?\s+|with\s+|will\s+|can\s+)?(?:visa sponsorship|sponsors?\s+visas?|sponsorships?|sponsors?|sponsoring|h-?1b|stem opt|opt|cpt)(?![a-z])", " ", s)
    for pm2 in re.finditer("§([0-9]+)§", s):
        add_to("companies", [found[int(pm2.group(1))]])
    s = re.sub("§[0-9]+§", " ", s)
    or_remote = bool(re.search(r"(?<![a-z])remote\s+or\s+(?:in\s+|near\s+|around\s+)?[a-z]", s) or re.search(r"[a-z.]\s+or\s+remote(?![a-z])", s))
    pos_modes = []
    for k, rx, _f in Q_MODE_RE:
        if rx.search(s):
            pos_modes.append(k)
            s = rx.sub(" ", s)
    # places
    locs = []
    s2 = s
    for lm2 in I.metro_re.finditer(s2):
        alias = lm2.group(1)
        if _js_len(alias) <= 2 and not re.search(r"(?<![a-z])(in|near|around|at)\s+\Z", s2[:lm2.start()]):
            continue
        mid = I.metro_map[alias]
        if I.metro[mid]["name"] not in locs:
            locs.append(I.metro[mid]["name"])
        s = re.sub(B4 + "(?:in |near |around )?" + esc_re(alias) + AF, " ", s, count=1)
    for stm in I.state_name_re.finditer(s):
        nm_s = _title_case(stm.group(1))
        if nm_s not in locs:
            locs.append(nm_s)
    s = I.state_name_re.sub(" ", s)
    s4 = s
    for cm2 in re.finditer(r"(?<![a-z])(?:in|near|around|at)\s+([a-z]{2})(?![a-z])", s4):
        code = cm2.group(1)
        if code.upper() not in TAX["us_states"] or code in Q_ST_BAD_POS or code in I.metro_map:
            continue
        if code.upper() not in locs:
            locs.append(code.upper())
        s = s.replace(cm2.group(0), " ", 1)
    # "remote or Seattle": remote jobs anywhere plus jobs in Seattle - not remote-only
    if or_remote and locs and "remote" in pos_modes:
        locs.append("Remote")
        if len(pos_modes) == 1:
            pos_modes = []
    if locs:
        patch["locations"] = "; ".join(locs)
        patch["locationRule"] = "hide"
    # roles: "senior PM", "RN", "sales jobs" (a whole family)
    lv_from_roles, found_pats = [], []
    s3 = s
    for rm in I.role_re.finditer(s3):
        pat = rm.group(1)
        if _js_len(pat) <= 3 and not Q_ROLE_SHORT_OK.fullmatch(pat):
            continue
        g = X_GROUPS.get(pat) if pat in Q_POS_GROUP_WORDS else None
        add_roles(_q_group_ids(g) if g else [I.role_map[pat]])
        found_pats.append(pat)
    for p in found_pats:
        for k, rx, _f in Q_LEVEL_RE:
            if rx.search(p) and k not in lv_from_roles:
                lv_from_roles.append(k)
        s = re.sub(B4 + esc_re(p) + "s?" + AF, " ", s, count=1)
    s5 = s
    for am in re.finditer(r"(?<![a-z0-9])(pms?|nps?)(?![a-z0-9])", s5):
        if re.search(r"[0-9]\s?\Z", _u16_before(s5, am.start(), 2)):
            continue  # "5 pm"
        add_roles([Q_ROLE_ALIAS[am.group(1)]])
        s = re.sub(B4 + am.group(1) + AF, " ", s, count=1)
    # levels and job types
    pos_levels = list(lv_from_roles)
    for k, rx, _f in Q_LEVEL_RE:
        if rx.search(s):
            if k not in pos_levels:
                pos_levels.append(k)
            s = rx.sub(" ", s)
    pos_types = []
    for k, rx, _f in Q_TYPE_RE:
        if rx.search(s):
            pos_types.append(k)
            s = rx.sub(" ", s)
    md = [x for x in pos_modes if x not in neg_modes]
    if md:
        patch["modes"] = md
        patch["modeRule"] = "hide"
    if neg_modes:
        patch["excludeModes"] = neg_modes
    lv = [x for x in pos_levels if x not in neg_levels]
    if lv:
        patch["levels"] = lv
        patch["levelRule"] = "hide"
    if neg_levels:
        patch["excludeLevels"] = neg_levels
    tp = [x for x in pos_types if x not in neg_types]
    if tp:
        patch["types"] = tp
        patch["typeRule"] = "hide"
    elif "intern" in lv and "internship" not in neg_types:
        patch["types"] = ["internship"]
    if neg_types:
        patch["excludeTypes"] = neg_types
    # industries -> rank
    inds, ind_only = [], False
    for k in sorted(Q_INDUSTRY_NAMES.keys(), key=lambda a: (-len(a), a)):
        if has_word(s, k):
            iid = Q_INDUSTRY_NAMES[k]
            if iid not in inds:
                inds.append(iid)
            # "only fintech", "fintech companies only": hide the rest, don't just prefer
            if re.search(r"(?<![a-z])(?:only|just|strictly|exclusively)\s+(?:in\s+|at\s+)?(?:the\s+)?" + esc_re(k) + AF + "|" + B4 + esc_re(k) + r"(?:\s+(?:companies|company|industry|sector|space|roles|jobs|firms))?\s+only" + AF, s):
                ind_only = True
            s = re.sub(B4 + esc_re(k) + AF, " ", s)
    if inds:
        patch["industries"] = inds
        patch["industryRule"] = "only" if ind_only else "rank"
    # skills -> "uses"
    sk = uniq([h["id"] for h in find_skills(s)])
    csl = _q_cs_low()
    for a in sorted(csl.keys(), key=lambda x: (-len(x), x)):
        if has_word(s, a) and csl[a] not in sk:
            sk.append(csl[a])
    for a in ("Go", "R", "C"):
        m3 = re.search(B4 + a + AF, raw_cut)
        if not m3 or not has_word(s, lc(a)):
            continue
        after = _u16_after(raw_cut, m3.end(), 12)
        before = lc(_u16_before(raw_cut, m3.start(), 12))
        if (after.startswith("-") or (a == "C" and re.search(r"(series|class|grade|vitamin|type|tier|plan|level|section)\s+\Z", before))
                or (a == "Go" and re.match(r"\s+(to|live|beyond|above|after|back|out|through|get)(?![a-z])", after, re.I))):
            continue
        sid = I.cs_map.get(a)
        if sid and sid not in sk:
            sk.append(sid)
    sk = [x for x in sk if x in I.skill and I.skill[x].get("kind") != "soft"]
    if sk:
        patch["mustSkills"] = sk
        patch["mustSkillsMode"] = "any"
        for sid in sk:
            for a in (I.skill[sid].get("aliases") or []) + (I.skill[sid].get("cs") or []):
                s = re.sub(B4 + esc_re(lc(a)) + AF, " ", s)
    # a whole family: "sales jobs", "design roles", "analyst roles"
    for k in sorted(Q_POS_GROUP_WORDS, key=lambda a: (-len(a), a)):
        if has_word(s, k):
            add_roles(_q_group_ids(X_GROUPS[k]))
            s = re.sub(B4 + esc_re(k) + AF, " ", s)
    for n in Q_TITLE_NOUNS:
        rx = re.compile(B4 + n + "s?" + AF)
        if rx.search(s):
            add_roles(_q_noun_ids(n))
            s = rx.sub(" ", s)
    # leftovers rank, never hide: runs of 1-2 words stay a phrase, longer runs split into words
    runs, cur = [], []
    for tk in re.finditer(r"[a-z0-9][a-z0-9&.+#'/-]*|[,;:.()\[\]{}]", s):
        w = re.sub(r"^['\-/&.]+|['\-/&.]+\Z", "", tk.group(0))
        if not w or re.fullmatch(r"[,;:.()\[\]{}]", tk.group(0)) or _q_stop(w) or re.fullmatch(r"[0-9.]+", w) or _js_len(w) < 3:
            if cur:
                runs.append(cur)
                cur = []
            continue
        cur.append(w)
    if cur:
        runs.append(cur)
    for r in runs:
        for x in ([" ".join(r)] if len(r) <= 2 else r):
            if x not in rank:
                rank.append(x)
    if hard:
        patch["keywords"] = hard
    if rank:
        patch["rankKeywords"] = rank[:6]
    for x in rank[6:]:   # said, not silently dropped
        ignored.append(x)
        ignored_why[x] = "overflow"
    return {"raw": raw, "chips": chips_from_patch(patch, roles), "patch": patch, "roles": roles, "keywords": list(hard),
            "rankKeywords": list(patch.get("rankKeywords") or []), "ignored": ignored, "ignoredWhy": ignored_why}


LEVEL_CHIP = {"intern": "Internship", "entry": "Entry level", "mid": "Mid level", "senior": "Senior", "lead": "Lead / Staff", "director": "Director", "exec": "Executive"}


def _q_money(v, hr):
    return "$" + jsnum(rhu(v / 2080 * 100) / 100) + "/hr" if hr else "$" + fmt_k(v)


def _q_group_chips(ids, neg):
    """A whole family collapses into one chip ("Sales roles", "No analyst roles")."""
    I = idx()
    out, used, gm = [], set(), {}
    for r in TAX["roles"]:
        gm.setdefault(r.get("group"), []).append(r["id"])

    def free(lst):
        return len(lst) > 1 and all((x in ids) and (x not in used) for x in lst)
    for rid in ids:
        if rid in used or rid not in I.role:
            continue
        done = False
        for n in Q_TITLE_NOUNS:
            fam = _q_noun_ids(n)
            if rid in fam and free(fam):
                used.update(fam)
                out.append({"value": fam, "label": ("No " + n + " roles") if neg else (_cap_first(n) + " roles")})
                done = True
                break
        if done:
            continue
        g = I.role[rid].get("group")
        allg = gm.get(g) or []
        if free(allg):
            used.update(allg)
            gl = GROUP_LABEL.get(g) or g
            out.append({"value": list(allg), "label": ("No " + gl + " roles") if neg else (_cap_first(gl) + " roles")})
        else:
            used.add(rid)
            out.append({"value": [rid], "label": ("No " + I.role[rid]["name"] + " roles") if neg else I.role[rid]["name"]})
    return out


def _q_level_ranges(lv):
    out, cur = [], []
    for x in LEVEL_ORDER:
        if x in lv:
            cur.append(x)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _q_level_range_label(rg):
    if len(rg) == 1:
        return "No internships" if rg[0] == "intern" else "No " + LEVEL_CHIP[rg[0]].lower() + " roles"
    if rg[-1] == "exec":
        return "No " + LEVEL_CHIP[rg[0]].lower() + " or above"
    if rg[0] == "intern":
        return "No " + LEVEL_CHIP[rg[-1]].lower() + " or below"
    return "No " + ", ".join(LEVEL_CHIP[x].lower() for x in rg)


def chips_from_patch(patch, roles):
    """One chip per thing the patch applies, in a fixed order; each knows how to undo itself."""
    I = idx()
    p = patch if isinstance(patch, dict) else {}
    out = []

    def arr(k):
        v = p.get(k)
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def add(kind, key, value, label, also=None):
        c = {"kind": kind, "key": key, "value": value, "label": label}
        if also:
            c["alsoTypes"] = also
        out.append(c)

    def soft(rk):
        return " (preferred)" if p.get(rk) == "rank" else ""
    role_ids = [r for r in roles if isinstance(r, str)] if isinstance(roles, list) else []
    for c in _q_group_chips(role_ids, False):
        add("role", "role", c["value"], c["label"])
    for o in arr("companies"):
        add("company", "companies", [o], "At " + o)
    loc_str = _s(p.get("locations")).strip() if p.get("locations") is not None else ""
    if loc_str:
        add("location", "locations", loc_str, " or ".join(x for x in re.split(r"\s*;\s*", loc_str) if x) + soft("locationRule"))
    if p.get("relocate") is False and p.get("locationRule") == "hide" and not loc_str:
        add("location", "relocate", False, "Near you only (no relocation)")
    elif p.get("relocate") is True:
        add("location", "relocate", True, "Open to relocating")
    if arr("modes"):
        add("mode", "modes", list(arr("modes")), " or ".join(mode_name(m) for m in arr("modes")) + soft("modeRule"))
    lvp, tps = arr("levels"), arr("types")
    also_t = "intern" in lvp and len(tps) == 1 and tps[0] == "internship"
    if lvp:
        add("level", "levels", list(lvp), " or ".join(LEVEL_CHIP.get(x) or x for x in lvp) + soft("levelRule"), ["internship"] if also_t else None)
    if tps and not also_t:
        add("type", "types", list(tps), " or ".join(TYPE_NAMES.get(t) or t for t in tps) + soft("typeRule"))
    F = p["salaryFloor"] if isnum(p.get("salaryFloor")) else None
    T_ = p["salaryTarget"] if isnum(p.get("salaryTarget")) else None
    C = p["salaryCeiling"] if isnum(p.get("salaryCeiling")) else None
    hu = p.get("salaryUnit") == "hour"
    sl = None
    if F is not None and C is not None:
        sl = _q_money(F, hu) + "–" + _q_money(C, hu)
    elif F is not None and T_ is not None and T_ > F:
        sl = _q_money(F, hu) + "–" + _q_money(T_, hu)
    elif F is not None:
        sl = _q_money(F, hu) + "+"
    elif C is not None:
        sl = "Up to " + _q_money(C, hu)
    if sl:
        add("salary", "salary", F if F is not None else C, sl + soft("salaryRule"))
    if isnum(p.get("maxYears")):
        my = p["maxYears"]
        add("years", "maxYears", my, ("No experience needed" if my == 0 else "Asks ≤ " + jsnum(my) + (" year" if my == 1 else " years")) + soft("yearsRule"))
    if isnum(p.get("postedWithin")) and p["postedWithin"] > 0:
        pw = p["postedWithin"]
        add("fresh", "postedWithin", pw, "Posted ≤ " + jsnum(pw) + (" day" if pw == 1 else " days"))
    if isnum(p.get("maxTravel")):
        mt = p["maxTravel"]
        add("travel", "maxTravel", mt, "No travel" if mt == 0 else "Travel ≤ " + jsnum(mt) + "%")
    for d in arr("industries"):
        if d in I.ind:
            add("industry", "industries", [d], I.ind[d]["name"] + ("" if p.get("industryRule") == "only" else " (preferred)"))
    ms = [x for x in arr("mustSkills") if x in I.skill]
    if ms:
        add("skills", "mustSkills", list(ms), "Uses " + (" and " if p.get("mustSkillsMode") == "all" else " or ").join(I.skill[x]["name"] for x in ms))
    if p.get("needsSponsorship") is True:
        add("auth", "needsSponsorship", True, "Ranks “no sponsorship” posts lower" if p.get("authRule") == "rank" else "Hides “no sponsorship” posts")
    for o in arr("blockedCompanies"):
        add("exclude", "blockedCompanies", [o], "Not at " + o)
    for c in _q_group_chips(arr("excludeRoles"), True):
        add("exclude", "excludeRoles", c["value"], c["label"])
    for d in arr("avoidIndustries"):
        if d in I.ind:
            add("exclude", "avoidIndustries", [d], "Not in " + I.ind[d]["name"])
    for x in arr("excludeSkills"):
        if x in I.skill:
            add("exclude", "excludeSkills", [x], "Doesn’t require " + I.skill[x]["name"])
    for x in arr("excludePlaces"):
        add("exclude", "excludePlaces", [x], "Not in " + x)
    for m in arr("excludeModes"):
        add("exclude", "excludeModes", [m], "No " + mode_word(m))
    xt = arr("excludeTypes")
    x_intern_chip = False
    for rg in _q_level_ranges(arr("excludeLevels")):
        also = "intern" in rg and "internship" in xt
        if also:
            x_intern_chip = True
        add("exclude", "excludeLevels", rg, _q_level_range_label(rg), ["internship"] if also else None)
    for t in xt:
        if t == "internship" and x_intern_chip:
            continue
        add("exclude", "excludeTypes", [t], "No " + (TYPE_NAMES.get(t) or t).lower() + " roles")
    if p.get("hideAgencies") is True:
        add("exclude", "hideAgencies", True, "No agencies")
    if p.get("hideReposts") is True:
        add("exclude", "hideReposts", True, "No reposts")
    if p.get("ghostRule") == "hide":
        add("exclude", "ghostRule", "hide", "No ghost-risk posts")
    if p.get("hideEvergreen") is True:
        add("exclude", "hideEvergreen", True, "No talent-pool posts")
    if p.get("avoidManagement") is True:
        add("exclude", "avoidManagement", True, "No people management")
    ph = arr("excludePhrases")
    if all(x in ph for x in CLEARANCE_PHRASES):
        add("exclude", "excludePhrases", list(CLEARANCE_PHRASES), "No clearance roles")
        ph = [x for x in ph if x not in CLEARANCE_PHRASES]
    for x in ph:
        add("exclude", "excludePhrases", [x], 'Not "' + x + '"')
    for k in arr("keywords"):
        add("keyword", "keywords", [k], '"' + k + '"')
    for k in arr("rankKeywords"):
        add("boost", "rankKeywords", [k], '"' + k + '"')
    return out


# ----------------------------------------------------------------- insights
def pctl(sorted_vals, q):
    if not sorted_vals:
        return None
    return sorted_vals[math.floor((len(sorted_vals) - 1) * q)]


def market_pulse(items, cand):
    I = idx()
    n = len(items)
    skill_count, skill_req, sal = {}, {}, []
    modes = {"remote": 0, "hybrid": 0, "onsite": 0, "unknown": 0}
    levels, orgs, org_name = {}, {}, {}
    new_week = no_spon = spons = 0
    for it in items:
        j = it["job"]
        for sid in uniq([s["id"] for s in j["skills"]]):
            skill_count[sid] = skill_count.get(sid, 0) + 1
        for s in j["skills"]:
            if s["required"]:
                skill_req[s["id"]] = skill_req.get(s["id"], 0) + 1
        if j["salary"]["source"] in ("listed", "parsed"):
            if j["salary"]["annualMin"] is not None and j["salary"]["annualMax"] is not None:
                mid = (j["salary"]["annualMin"] + j["salary"]["annualMax"]) / 2
            else:
                mid = j["salary"]["annualMax"] or j["salary"]["annualMin"]
            if mid:
                sal.append(rhu(mid))
        mk = j["mode"] or "unknown"
        modes[mk] = modes.get(mk, 0) + 1
        b = level_bucket(j["level"]) or "unknown"
        levels[b] = levels.get(b, 0) + 1
        o = norm_org(j["org"])
        if o:
            orgs[o] = orgs.get(o, 0) + 1
            org_name[o] = org_name.get(o) or j["org"]
        if it["opp"]["ageDays"] is not None and it["opp"]["ageDays"] <= 7:
            new_week += 1
        if j["auth"]["noSponsorship"]:
            no_spon += 1
        if j["auth"]["sponsors"]:
            spons += 1
    ids = [sid for sid in skill_count if I.skill[sid]["kind"] != "soft"]
    ids.sort(key=lambda sid: (-skill_count[sid], I.skill_i[sid]))
    top_skills = []
    for sid in ids[:12]:
        c = cand["skills"].get(sid) if cand else None
        have = c["level"] if c else "missing"
        if not c and cand:
            cr = skill_credit({"id": sid, "family": I.skill[sid].get("family")}, cand)
            if cr["how"] in ("adjacent", "related"):
                have = cr["how"]
        top_skills.append({"id": sid, "name": I.skill[sid]["name"], "count": skill_count[sid], "required": skill_req.get(sid, 0),
                           "pct": rhu(100 * skill_count[sid] / n) if n else 0, "have": have})
    sal.sort()
    comp = sorted(orgs.keys(), key=lambda o: (-orgs[o], o))[:8]
    return {"n": n, "topSkills": top_skills,
            "salary": {"n": len(sal), "p25": pctl(sal, 0.25), "median": pctl(sal, 0.5), "p75": pctl(sal, 0.75), "min": sal[0] if sal else None, "max": sal[-1] if sal else None},
            "modes": modes, "levels": levels, "companies": [{"org": org_name[o], "count": orgs[o]} for o in comp],
            "newThisWeek": new_week, "noSponsorship": no_spon, "sponsors": spons}


def score_audit(items):
    bands = {"excellent": 0, "strong": 0, "partial": 0, "weak": 0, "poor": 0, "unknown": 0}
    hist = [0] * 10
    fits, caps = [], {}
    conf = {"high": 0, "medium": 0, "low": 0}
    for it in items:
        s = it["score"]
        bands[s["band"]] = bands.get(s["band"], 0) + 1
        conf[s["confidence"]] += 1
        if s["fit"] is not None:
            fits.append(s["fit"])
            hist[min(9, math.floor(s["fit"] / 10))] += 1
        if s["capApplied"]:
            k = s["capApplied"]["key"]
            caps[k] = caps.get(k, 0) + 1
    fits.sort()
    avg = rhu(sum(fits) / len(fits)) if fits else None
    return {"n": len(items), "bands": bands, "histogram": hist, "avg": avg, "median": pctl(fits, 0.5), "capsApplied": caps, "confidence": conf,
            "over90": len([f for f in fits if f >= 90])}


def to_legacy_match(it):
    """The shape the rest of the app (and auto-apply) already reads."""
    I = idx()
    j, s, o = it["job"], it["score"], it["opp"]
    jid = j["id"]
    jid_out = int(jid) if re.fullmatch(r"-?[0-9]{1,15}", jid) else jid
    return {
        "id": jid_out, "type": j["type"], "title": j["title"], "org": j["org"], "loc": j["location"] or ("Remote" if j["mode"] == "remote" else ""),
        "deadline": j["deadline"] or "", "description": j["description"], "tags": [x["name"].lower() for x in j["skills"]][:8],
        "pct": 0 if s["fit"] is None else s["fit"], "band": s["bandLabel"], "confidence": s["confidence"],
        "matchedSkill": [d["name"].lower() for d in s["skillDetail"] if d["credit"] >= 0.85],
        "matchedGoal": [I.role[s["roleMatch"]["job"]]["name"].lower()] if s["roleMatch"] else [],
        "missingSkills": [d["name"] for d in s["skillDetail"] if d["required"] and d["credit"] == 0],
        "signalStrength": "high" if s["confidence"] == "high" else ("moderate" if s["confidence"] == "medium" else "low"),
        "signalScore": rhu(it["rank"]), "signalBand": s["bandLabel"], "ghostRisk": o["ghost"], "freshness": o["freshness"], "ageDays": o["ageDays"],
        "salaryMin": rhu(j["salary"]["annualMin"] / 1000) if j["salary"]["annualMin"] is not None else None,
        "salaryMax": rhu(j["salary"]["annualMax"] / 1000) if j["salary"]["annualMax"] is not None else None,
        "salaryIsPredicted": j["salary"]["source"] == "estimated", "mode": j["mode"], "employmentType": j["employmentType"], "applyUrl": j["applyUrl"],
        "factors": {"skills": s["dims"]["skills"], "level": s["dims"]["level"], "role": s["dims"]["role"], "industry": s["dims"]["industry"], "preferences": s["pref"]["score"]},
        "engine": "proof-v2",
    }
