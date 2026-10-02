"""Resume ingest - pure, dependency-light helpers for the "skip the survey,
just give us your resume" fast path.
 
The design mirrors the rest of the codebase: the messy, I/O-adjacent work
(text extraction, URL fetching, model-output parsing) lives here as small,
individually testable functions with NO fastapi import, so the route stays a
thin shell and every piece can be unit-tested dependency-free.
 
Anti-fabrication discipline is the whole point of the parser: the model is
asked to copy the person's own words verbatim, and parse_resume_profile_json
only keeps a known, bounded set of fields - it never adds, infers, or
"improves" a value. If the model returns something unparseable, we raise and
the caller falls back rather than inventing a profile.
"""
from __future__ import annotations
 
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
 
class ResumeIngestError(ValueError):
    """A deliberately user-safe failure message, written here to be shown to the
    person as-is (e.g. 'Couldn't read that PDF - paste the text instead'). It
    never carries internal detail (paths, library errors, tracebacks), so the
    route can surface .user_message to the client without leaking anything.
    """
    def __init__(self, message: str):
        super().__init__(message)
        self.user_message = message
 
 
# Caps - resume text handed to the model, and the largest file/URL we'll read.
MAX_RESUME_CHARS = 20000
MAX_FILE_BYTES = 4 * 1024 * 1024  # 4 MB
 
# The only values the rest of the app understands for these fields. Anything
# the model returns outside these sets is dropped, never coerced to a guess.
_ALLOWED_TYPES = ("job", "internship", "college", "admissions", "athletic")
_ALLOWED_STAGES = ("student", "grad", "switch", "working")
_ALLOWED_TIMEFRAMES = ("now", "6-12mo", "1-2yr", "2yr+")
_ALLOWED_PRIORITIES = ("pay", "learning", "brand", "flexibility", "mission")
_ALLOWED_ENTRY_TYPES = ("work", "education", "project")
 
_MAX_ENTRIES = 25
 
 
def _s(v, limit=600):
    """Coerce to a trimmed, length-capped string. Never raises."""
    if v is None:
        return ""
    try:
        out = str(v).strip()
    except Exception:
        return ""
    return out[:limit]
 
 
# ---------------------------------------------------------------------------
# File text extraction
# ---------------------------------------------------------------------------
def extract_resume_text(filename: str, raw: bytes) -> str:
    """Best-effort plain text from an uploaded resume file.
 
    PDF and DOCX use their own libraries (imported lazily so this module stays
    importable with neither installed - the dependency-free tests never hit
    these branches). Anything else is decoded as UTF-8. Raises ValueError with
    a user-safe message on a genuine parse failure so the caller can tell the
    person to paste the text instead, rather than 500-ing.
    """
    name = (filename or "").lower().strip()
    data = raw or b""
 
    if name.endswith(".pdf"):
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    # One unreadable page shouldn't lose the whole resume.
                    continue
            text = "\n".join(parts).strip()
            if not text:
                raise ValueError("empty")
            return text
        except Exception:
            raise ResumeIngestError("Couldn't read that PDF. Try pasting the text from your resume instead.")
 
    if name.endswith(".docx"):
        try:
            import io
            from docx import Document
            doc = Document(io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs).strip()
            if not text:
                raise ValueError("empty")
            return text
        except Exception:
            raise ResumeIngestError("Couldn't read that Word file. Try pasting the text from your resume instead.")
 
    if name.endswith(".doc"):
        # The old binary .doc format needs a heavier toolchain; be honest.
        raise ResumeIngestError("Old .doc files aren't supported - save as PDF or .docx, or paste the text.")
 
    # .txt, .md, or unknown: decode and hope. errors='ignore' never raises.
    return (data.decode("utf-8", errors="ignore")).strip()
 
 
# ---------------------------------------------------------------------------
# URL fetch (the "link your resume" path) - with SSRF guards
# ---------------------------------------------------------------------------
def is_blocked_ip(ip_str: str) -> bool:
    """True if an IP must never be fetched server-side - loopback, private,
    link-local (incl. the 169.254.169.254 cloud metadata endpoint), reserved,
    multicast, or unspecified. Fail closed: an unparseable address is blocked.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )
 
 
def is_safe_public_url(url: str) -> bool:
    """Static (no-DNS) first line of defence for a user-supplied URL: must be
    http(s), have a hostname, not be a plainly-local name, and - if the host is
    an IP literal - not be a blocked IP. Hostnames are additionally re-checked
    against their resolved IPs at fetch time (see fetch_url_text).
    """
    try:
        p = urllib.parse.urlparse((url or "").strip())
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").strip().lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return False
    # If the host is an IP literal, vet it directly.
    try:
        ipaddress.ip_address(host)
        return not is_blocked_ip(host)
    except ValueError:
        pass  # it's a domain name - resolved-IP check happens at fetch time
    return True
 
 
def _strip_html(html: str) -> str:
    """Crude HTML -> text for the link path. Drops script/style, unwraps tags,
    collapses whitespace. Good enough to feed the model; not a real parser.
    """
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"[ \t\r\f\v]+", " ", html)
    html = re.sub(r"\n\s*\n\s*\n+", "\n\n", html)
    return html.strip()
 
 
def fetch_url_text(url: str, timeout: float = 10.0) -> str:
    """Fetch a user-supplied resume URL and return extracted text.
 
    Guards against SSRF: scheme/host vetting up front, then every resolved IP
    is checked before the request goes out. Caps the read at MAX_FILE_BYTES.
    Raises ValueError (user-safe message) on anything that isn't a clean,
    public, readable document.
    """
    if not is_safe_public_url(url):
        raise ResumeIngestError("That link can't be fetched. Paste your resume text or upload the file instead.")
    p = urllib.parse.urlparse(url.strip())
    host = p.hostname or ""
    # Resolve and vet every address the host maps to (defeats a domain that
    # resolves to a private/loopback/metadata IP).
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80))
    except Exception:
        raise ResumeIngestError("Couldn't reach that link. Paste your resume text or upload the file instead.")
    for info in infos:
        ip = info[4][0]
        if is_blocked_ip(ip):
            raise ResumeIngestError("That link resolves to a blocked address and wasn't fetched.")
 
    req = urllib.request.Request(url.strip(), headers={"User-Agent": "KaidostarResumeBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (scheme vetted above)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read(MAX_FILE_BYTES + 1)
    except ValueError:
        raise
    except Exception:
        raise ResumeIngestError("Couldn't read that link. Paste your resume text or upload the file instead.")
    if len(raw) > MAX_FILE_BYTES:
        raise ResumeIngestError("That document is too large. Paste the text or upload a smaller file.")
 
    if "application/pdf" in ctype or url.lower().endswith(".pdf"):
        return extract_resume_text("resume.pdf", raw)
    if "wordprocessingml" in ctype or url.lower().endswith(".docx"):
        return extract_resume_text("resume.docx", raw)
    text = raw.decode("utf-8", errors="ignore")
    if "<html" in text.lower() or "<body" in text.lower() or "text/html" in ctype:
        text = _strip_html(text)
    return text.strip()
 
 
# ---------------------------------------------------------------------------
# Model output -> a normalized profile patch + verbatim resume entries
# ---------------------------------------------------------------------------
def _coerce_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        return [x.strip() for x in v.split(",") if x.strip()]
    return []
 
 
def parse_resume_profile_json(model_text: str):
    """Parse the resume_profile model output into (profile_dict, entries_list).
 
    Only a known, bounded set of fields survives - the function never adds a
    value the model didn't return, and clamps every enum-like field to the
    app's allowed set (an out-of-set value is dropped, not guessed). Robust to
    a code fence or stray prose around the JSON object. Raises ValueError if no
    JSON object can be recovered, so the caller falls back instead of shipping
    an empty profile as if it were real.
    """
    if not model_text or not str(model_text).strip():
        raise ValueError("empty model output")
    t = str(model_text).strip()
    # Strip a ```json ... ``` fence if present.
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    # Narrow to the outermost object.
    a0, a1 = t.find("{"), t.rfind("}")
    if a0 >= 0 and a1 > a0:
        t = t[a0:a1 + 1]
    try:
        raw = json.loads(t)
    except Exception:
        raise ValueError("could not parse resume JSON")
    if not isinstance(raw, dict):
        raise ValueError("resume JSON was not an object")
 
    profile = {}
    profile["northstar"] = _s(raw.get("northstar"), 500)
    profile["finalidea"] = _s(raw.get("finalidea"), 500)
    profile["skills"] = _s(raw.get("skills"), 1500)
    profile["loc"] = _s(raw.get("loc"), 200)
    profile["dealbreakers"] = _s(raw.get("dealbreakers"), 500).lower()
    profile["fullName"] = _s(raw.get("fullName") or raw.get("full_name"), 200)
    profile["phone"] = _s(raw.get("phone"), 60)
 
    stage = _s(raw.get("stage"), 40).lower()
    if stage in _ALLOWED_STAGES:
        profile["stage"] = stage
 
    tf = _s(raw.get("timeframe"), 20).lower()
    profile["timeframe"] = tf if tf in _ALLOWED_TIMEFRAMES else "now"
 
    types = [x for x in (_s(x, 20).lower() for x in _coerce_list(raw.get("types"))) if x in _ALLOWED_TYPES]
    # De-dup while preserving order; default to an actionable job search.
    seen = set()
    types = [x for x in types if not (x in seen or seen.add(x))]
    profile["types"] = types or ["job", "internship"]
 
    prios = [x for x in (_s(x, 20).lower() for x in _coerce_list(raw.get("priorities"))) if x in _ALLOWED_PRIORITIES]
    seen = set()
    profile["priorities"] = [x for x in prios if not (x in seen or seen.add(x))][:2]
 
    entries = []
    for e in (raw.get("entries") or [])[: _MAX_ENTRIES * 2]:
        if not isinstance(e, dict):
            continue
        title = _s(e.get("title"), 300)
        raw_desc = _s(e.get("raw_description") or e.get("description"), 5000)
        # An entry with neither a title nor a description carries no real
        # information - drop it rather than store an empty shell.
        if not title and not raw_desc:
            continue
        etype = _s(e.get("entry_type"), 40).lower()
        if etype not in _ALLOWED_ENTRY_TYPES:
            etype = "work"
        entries.append({
            "entry_type": etype,
            "title": title or "(untitled)",
            "org": _s(e.get("org"), 300),
            "start_date": _s(e.get("start_date"), 50),
            "end_date": _s(e.get("end_date"), 50),
            "raw_description": raw_desc,
        })
        if len(entries) >= _MAX_ENTRIES:
            break
 
    return profile, entries
 
