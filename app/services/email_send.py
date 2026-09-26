"""Real outbound email sending, and best-guess contact address
generation.
 
Honest technical note: since the app deliberately never fabricates a
real named person (see connect_strategy in listings.py), there is no
specific individual's email to "find" - guessing a pattern like
firstname.lastname@company.com requires a real name we don't have and
won't invent. What this CAN honestly produce is a plausible general
company contact address (careers@, hr@, jobs@) built from a guessed
domain - useful, but explicitly a guess, never presented as verified.
 
Sending itself is real: this uses Resend (resend.com) once
RESEND_API_KEY is set. Until that key is added, send_email() raises a
clear error rather than silently pretending to send.
"""
import os
import re
import httpx
 
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_API_URL = "https://api.resend.com/emails"
SEND_FROM_ADDRESS = os.getenv("SEND_FROM_ADDRESS", "outreach@yourdomain.com")
 
COMMON_CONTACT_PREFIXES = ["careers", "jobs", "hr", "talent", "recruiting"]
 
 
def guess_company_domain(org_name: str) -> str:
    """Best-effort domain guess from a company name - strips common
    suffixes and punctuation, lowercases, joins words. This is a
    guess, not a lookup - real companies often use a different domain
    than their literal name would suggest.
    """
    org_name = org_name or ""
    cleaned = re.sub(r"\b(inc|llc|ltd|corp|corporation|co)\b\.?", "", org_name, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", cleaned).strip().lower()
    slug = re.sub(r"\s+", "", cleaned)
    return f"{slug}.com" if slug else None
 
 
def guess_contact_emails(org_name: str) -> dict:
    """Returns a small set of plausible general-contact addresses for
    a company, clearly marked as an unverified guess. Never claims to
    have found a specific person.
    """
    domain = guess_company_domain(org_name)
    if not domain:
        return {"domain_guessed": None, "candidates": [], "verified": False}
    candidates = [f"{prefix}@{domain}" for prefix in COMMON_CONTACT_PREFIXES]
    return {
        "domain_guessed": domain,
        "candidates": candidates,
        "verified": False,
        "note": "This is a pattern-based guess at a general company contact address, not a verified or specific person's email. Confirm it looks right before sending.",
    }
 
 
def send_email(to_address: str, subject: str, body: str, html_body: str | None = None) -> dict:
    """Actually sends an email via Resend. Raises a clear error if
    RESEND_API_KEY isn't configured, rather than silently no-op'ing.
    html_body is optional - every existing caller keeps working
    exactly as before with plain text only; passing it adds a real,
    properly-formatted HTML version alongside the text one, which
    Resend's own API already supports in the same request.
    """
    # Recipient sanity check, centralized here so every send path is
    # covered at once. Blocks a missing/blank address, control
    # characters (newline/carriage-return header-injection attempts),
    # and comma/semicolon-separated multi-address "blasts" - none of
    # which a legitimate single-recipient outreach email ever needs.
    if not to_address or not isinstance(to_address, str):
        raise ValueError("A recipient email address is required.")
    to_address = to_address.strip()
    if any(ch in to_address for ch in ["\n", "\r", ",", ";", " "]):
        raise ValueError("Recipient address must be a single, valid email address.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to_address):
        raise ValueError("Recipient address is not a valid email address.")
 
    if not RESEND_API_KEY:
        raise RuntimeError(
            "RESEND_API_KEY is not set - sign up at resend.com, get an API key, "
            "and add it to your Render environment variables to enable real sending."
        )
    payload = {
        "from": SEND_FROM_ADDRESS,
        "to": [to_address],
        "subject": subject,
        "text": body,
    }
    if html_body:
        payload["html"] = html_body
    headers = {"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"}
    resp = httpx.post(RESEND_API_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()
 
