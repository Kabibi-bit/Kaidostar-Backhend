"""Best-effort REAL submission of a web-form job application via a headless
browser (Playwright/Chromium).
 
This is the honest version of "auto-apply to the job site". There is no universal
API to submit an arbitrary employer's application form, so the only real way to do
it is to drive a browser the way a person would. That is genuinely possible for
simple public forms - and genuinely NOT possible for a large share of real
postings (logins, CAPTCHAs, multi-step Workday-style flows, employer accounts).
This module is built to be honest about which case it hit, and - above all - to
NEVER submit a garbled or partial application under the user's name:
 
  Safety model (why this can't silently ruin an application):
    * It aborts (returns "needs_manual") the moment it detects a login/signup
      wall or a CAPTCHA - it does not try to bluff past them.
    * It fills only fields it can confidently map to the user's real data
      (name / email / phone / resume file / cover letter).
    * Before clicking Submit it re-checks EVERY required control on the form.
      If any required field is still empty (i.e. something it couldn't map),
      it aborts instead of submitting an incomplete/garbled application.
    * It only reports "submitted" when it can actually detect a confirmation
      after submitting. No confirmation -> it reports "needs_manual", never a
      fabricated success.
    * If Playwright or a browser binary isn't available in the runtime, it
      returns "unavailable" and the caller falls back to the manual hand-off -
      it never crashes the request.
 
Result status is one of:
    "submitted"    - the form was filled and a submission confirmation was seen.
    "needs_manual" - a real blocker (login/CAPTCHA), an unmappable required
                     field, or no detectable confirmation. Hand off to the user.
    "unavailable"  - no browser automation in this runtime.
    "error"        - an unexpected failure; caller falls back to the hand-off.
 
Deployment note: the deployed backend must have the `playwright` package AND its
Chromium binary installed (`playwright install chromium`). Without them this
returns "unavailable" and the app degrades to the manual hand-off - safe, just
not automatic.
"""
from __future__ import annotations
 
import logging
import os
 
_log = logging.getLogger("kaidostar")
 
# Text seen on a page that means "you must sign in / create an account first".
_LOGIN_MARKERS = ("sign in to apply", "log in to apply", "login to apply", "create an account to apply")
# Text/markup that means a CAPTCHA is present - we never try to defeat these.
_CAPTCHA_SELECTOR = "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha, .h-captcha, [data-sitekey]"
# Text that means the submission went through.
_CONFIRM_MARKERS = (
    "thank you for applying", "thanks for applying", "application received",
    "received your application", "application submitted", "successfully submitted",
    "we have received", "we've received", "we'll be in touch", "thank you for your application",
    "your application has been", "application complete",
)
# Confirmation-specific URL tokens. Deliberately specific (not bare "complete"/
# "success"/"thank", which appear incidentally in real posting URLs and would
# falsely confirm) and only ever counted when the URL CHANGES after submit -
# i.e. a navigation TO a thank-you page, never the apply URL that was already open.
_CONFIRM_URL_MARKERS = ("thank-you", "thankyou", "thank_you", "/thanks", "confirmation", "/confirmed", "application-received", "application-submitted")
 
 
def check_browser_available() -> dict:
    """Post-deploy health check: can Pro auto-submit actually drive a browser in
    THIS runtime? Reports the honest state so the team can verify a deploy without
    submitting a real application. Distinguishes 'the playwright package is
    missing' from 'the package is here but the Chromium binary/its OS libs are
    not' - which need different fixes (add the dep vs. `playwright install
    --with-deps chromium`). Never raises."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"available": False, "reason": f"playwright package not installed: {e}",
                "fix": "add playwright to requirements and redeploy"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ver = browser.version
            finally:
                browser.close()
        return {"available": True, "chromium_version": ver}
    except Exception as e:
        return {"available": False, "reason": f"browser could not launch: {e}",
                "fix": "run `playwright install --with-deps chromium` in the deploy (or use the Dockerfile)"}
 
 
def _fill_first(scope, selectors, value) -> bool:
    """Fill the first visible, editable control matching any selector. Returns
    True if something was filled. Never raises - a missing field just returns False.
 
    Iterates EVERY match of each selector, not just `.first`: a hidden or disabled
    field that matches an early selector must not shadow a visible one matching the
    same selector (taking only `.first` and finding it hidden would skip straight to
    the next selector and miss the real field). `scope` may be a page/frame or a
    single <form> locator."""
    if not value:
        return False
    for sel in selectors:
        try:
            loc = scope.locator(sel)
            n = loc.count()
        except Exception:
            continue
        for i in range(n):
            try:
                el = loc.nth(i)
                if el.is_visible() and el.is_editable():
                    el.fill(str(value), timeout=3000)
                    return True
            except Exception:
                continue
    return False
 
 
def _required_controls_all_satisfied(scope) -> bool:
    """True only if every REQUIRED form control has a value / a file. This is the
    core anti-garbage guard: if we couldn't map some required field, we must not
    submit. Fails safe to False (do not submit) on any uncertainty. `scope` is the
    application form (or the whole context) - scoping it to the real form keeps a
    required field in an unrelated form (a newsletter's email) from blocking."""
    try:
        controls = scope.locator(
            "input[required]:not([type=hidden]):not([type=submit]):not([type=button]), "
            "textarea[required], select[required], "
            "[aria-required='true']"
        )
        n = controls.count()
        for i in range(n):
            c = controls.nth(i)
            try:
                if not c.is_visible():
                    continue
                tag = (c.evaluate("el => el.tagName") or "").upper()
                if tag == "SELECT":
                    # A required dropdown is treated as UNSATISFIED because the
                    # submitter never chooses dropdown answers. Many required
                    # selects are materially high-stakes - visa sponsorship, work
                    # authorization, EEO/veteran/disability status - and a <select>
                    # always has a default option, so trusting its value would mean
                    # auto-submitting a GUESSED answer to a question like "Do you
                    # require sponsorship?" under the user's name. That is exactly
                    # the kind of fabrication this must never do, so hand off instead.
                    return False
                type_attr = (c.get_attribute("type") or "").lower()
                if type_attr in ("checkbox", "radio"):
                    # Required consent/eligibility box we didn't knowingly check -
                    # treat as unsatisfied so we don't auto-agree to something.
                    if not c.is_checked():
                        return False
                    continue
                if type_attr == "file":
                    # A required file with nothing attached => unsatisfied.
                    files_val = c.evaluate("el => el.files ? el.files.length : 0")
                    if not files_val:
                        return False
                    continue
                val = (c.input_value() if hasattr(c, "input_value") else c.evaluate("el => el.value")) or ""
                if not str(val).strip():
                    return False
            except Exception:
                return False  # can't verify -> don't risk a bad submit
        return True
    except Exception:
        return False
 
 
def _confirmation_text_present(page, ctx=None) -> bool:
    """True if a specific confirmation PHRASE is visible in the body of the form
    context or the page. The phrases are specific ('thank you for applying',
    'application received', ...), so incidental words don't trip it - but see
    the caller: this is only treated as confirmation when it appears AFTER submit
    having NOT been present before (so instructional text like 'once your
    application is received...' can't produce a false positive)."""
    for c in (ctx, page):
        if c is None:
            continue
        try:
            body = (c.locator("body").inner_text(timeout=3000) or "").lower()
            if any(m in body for m in _CONFIRM_MARKERS):
                return True
        except Exception:
            continue
    return False
 
 
def _looks_confirmed(page, ctx=None, pre_url: str = "", pre_text: bool = False) -> bool:
    """A submission is confirmed only by a CHANGE after clicking submit - never by
    text or a URL that was already there. This is the safety-critical guard: a
    false positive (marking an application 'sent' that wasn't) is the worst
    outcome, so confirmation requires either (a) the URL navigated to a
    confirmation-specific page, or (b) a confirmation phrase newly appeared."""
    try:
        post_url = (page.url or "")
        if post_url != pre_url and any(m in post_url.lower() for m in _CONFIRM_URL_MARKERS):
            return True
        if _confirmation_text_present(page, ctx) and not pre_text:
            return True
        return False
    except Exception:
        return False
 
 
# Markers in a frame URL that identify a known applicant-tracking system embed.
_ATS_FRAME_MARKERS = (
    "greenhouse", "lever", "ashby", "workday", "myworkdayjobs", "icims",
    "smartrecruiters", "jobvite", "bamboohr", "workable", "/embed", "job_app", "/apply",
)
# A selector that means "an application form is present here" - used to find the
# right frame and to wait for a single-page-app form to finish rendering.
_FORM_PRESENT = (
    "input[type=email], input[type=file], input[name*=email i], "
    "input[name*=first i], input[name*='resume' i], textarea"
)
 
 
def _resolve_form_context(page, timeout_ms: int):
    """Return the frame (or the page) that actually holds the application form.
 
    Real postings break the naive "everything is on page" assumption two ways:
    company career pages EMBED the ATS in an iframe, and modern ATSes (Greenhouse,
    Ashby, Lever) render the form client-side, so it isn't in the DOM at initial
    load. This polls every frame until a form appears, preferring a frame whose URL
    is a known ATS embed. Falls back to the page so callers always get a context."""
    import time
    # Bound the wait: a real ATS form renders within a few seconds. Polling the
    # full request timeout here (e.g. 25s) would hang an inline request on any
    # page that simply has no fillable form ("apply on our website" postings), so
    # cap this at ~8s regardless of the overall timeout.
    deadline = time.time() + max(3.0, min(8.0, timeout_ms / 1000.0))
    # First, give a known ATS iframe a chance to be the answer.
    while time.time() < deadline:
        for f in page.frames:
            try:
                if f is page.main_frame:
                    continue
                if any(m in (f.url or "").lower() for m in _ATS_FRAME_MARKERS):
                    if f.locator(_FORM_PRESENT).count() > 0:
                        return f
            except Exception:
                continue
        # Otherwise, any frame (incl. the main page) that has form fields.
        for f in [page.main_frame] + [fr for fr in page.frames if fr is not page.main_frame]:
            try:
                if f.locator(_FORM_PRESENT).count() > 0:
                    return f
            except Exception:
                continue
        try:
            page.wait_for_timeout(500)
        except Exception:
            break
    return page
 
 
def _resolve_application_form(ctx):
    """Within the form context, pick the <form> that looks like the job application
    - scored by a résumé file input, a name field, an email/phone field, and an
    'apply'/'application' submit - so a newsletter/search form on the same page
    can't capture our fills, satisfy the required-field check, or be the submit
    target. Returns a Locator for that form, or None to fall back to the whole
    context (many ATSes don't wrap their fields in a <form> at all). Mirrors the
    browser extension's applicationForm() so both delivery paths behave the same."""
    try:
        forms = ctx.locator("form")
        n = forms.count()
    except Exception:
        return None
    best, best_score = None, 1  # require a minimal signal (> 1) to claim a form
    for i in range(n):
        f = forms.nth(i)
        s = 0
        try:
            if f.locator("input[type=file]").count() > 0:
                s += 3
            if f.locator("input[name*=first i], input[name*='full_name' i], input[name*='full-name' i], input[name*=fullname i], input[name='name'], input[autocomplete='name'], input[autocomplete='given-name']").count() > 0:
                s += 2
            if f.locator("input[type=email], input[name*=email i], input[autocomplete='email']").count() > 0:
                s += 1
            if f.locator("input[type=tel], input[name*=phone i]").count() > 0:
                s += 1
            if f.locator("button:has-text('appl'), input[type=submit][value*='appl' i]").count() > 0:
                s += 2  # "apply" / "application"
        except Exception:
            continue
        if s > best_score:
            best_score = s
            best = f
    return best
 
 
def submit_application_via_browser(
    apply_url: str,
    candidate: dict,
    resume_path: str | None = None,
    cover_letter: str | None = None,
    timeout_ms: int = 25000,
) -> dict:
    """Attempt a real submission at apply_url. See module docstring for the
    status contract and the safety model. candidate keys used (all optional):
    full_name, first_name, last_name, email, phone."""
    if not apply_url or not str(apply_url).startswith(("http://", "https://")):
        return {"status": "needs_manual", "reason": "no real application URL to open"}
 
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"status": "unavailable", "reason": "browser automation is not available in this environment"}
 
    candidate = candidate or {}
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                return {"status": "unavailable", "reason": f"could not launch a browser: {e}"}
            try:
                page = browser.new_page()
                page.set_default_timeout(8000)
                page.goto(apply_url, timeout=timeout_ms, wait_until="domcontentloaded")
                # Real ATS forms render client-side and/or inside an iframe, so let
                # the page settle, then resolve the actual form context (a frame or
                # the page). All field work below runs against that context.
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                ctx = _resolve_form_context(page, timeout_ms)
 
                # 1) Never try to bluff past a CAPTCHA or a login wall (check the
                #    whole page AND the form context - the wall may be in either).
                for c in (page, ctx):
                    try:
                        if c.locator(_CAPTCHA_SELECTOR).count() > 0:
                            return {"status": "needs_manual", "reason": "the posting is protected by a CAPTCHA"}
                    except Exception:
                        pass
                try:
                    body_lower = (page.locator("body").inner_text(timeout=4000) or "").lower()
                except Exception:
                    body_lower = ""
                has_password = False
                for c in (page, ctx):
                    try:
                        if c.locator("input[type=password]").count() > 0:
                            has_password = True
                            break
                    except Exception:
                        continue
                if any(m in body_lower for m in _LOGIN_MARKERS) or has_password:
                    return {"status": "needs_manual", "reason": "the posting requires signing in or creating an account first"}
 
                # Operate within the actual application form when one is identifiable,
                # so on a page with several forms (a newsletter signup, a site search)
                # we never fill a decoy's field, let a decoy's required field block us,
                # or submit the wrong form. Falls back to the whole context otherwise.
                scope = _resolve_application_form(ctx) or ctx
 
                # 2) Fill only what we can confidently map to real user data. Selectors
                #    cover generic markup plus the real field-name conventions of the
                #    major ATSes (Greenhouse's job_application[...] brackets, Lever's
                #    bare name/email/phone/resume, Ashby/Workable label-driven fields).
                _fill_first(scope, [
                    "input[type=email]", "input[name*=email i]", "input[id*=email i]",
                    "input[placeholder*=email i]", "input[aria-label*=email i]",
                    "input[name='job_application[email]']", "input[autocomplete='email']",
                ], candidate.get("email"))
                full_name = candidate.get("full_name") or " ".join(x for x in [candidate.get("first_name"), candidate.get("last_name")] if x).strip()
                filled_full = _fill_first(scope, [
                    "input[name*='full_name' i]", "input[name*='full-name' i]", "input[name*='full name' i]", "input[name*=fullname i]",
                    "input[id*='full_name' i]", "input[id*=fullname i]",
                    "input[placeholder*='full name' i]", "input[aria-label*='full name' i]",
                    "input[autocomplete='name']",
                    "input[name='name']", "input[id='name']", "input[name*='your_name' i]", "input[name*=applicant i]",
                ], full_name)
                if not filled_full:
                    _fill_first(scope, [
                        "input[name='job_application[first_name]']", "input[autocomplete='given-name']",
                        "input[name*=first i]", "input[id*=first i]", "input[placeholder*='first name' i]", "input[aria-label*='first name' i]",
                    ], candidate.get("first_name"))
                    _fill_first(scope, [
                        "input[name='job_application[last_name]']", "input[autocomplete='family-name']",
                        "input[name*=last i]", "input[id*=last i]", "input[placeholder*='last name' i]", "input[aria-label*='last name' i]",
                    ], candidate.get("last_name"))
                _fill_first(scope, [
                    "input[type=tel]", "input[name='job_application[phone]']", "input[autocomplete='tel']",
                    "input[name*=phone i]", "input[id*=phone i]", "input[placeholder*=phone i]", "input[aria-label*=phone i]",
                ], candidate.get("phone"))
                if cover_letter:
                    _fill_first(scope, [
                        "textarea[name*=cover i]", "textarea[id*=cover i]", "textarea[name*=message i]", "textarea[name*=letter i]",
                        "textarea[placeholder*='cover letter' i]", "textarea[aria-label*='cover letter' i]",
                        "textarea[name='job_application[cover_letter_text]']", "textarea",
                    ], cover_letter)
 
                # 3) Resume upload (Greenhouse and most ATSes REQUIRE it). Playwright
                #    sets files even on a hidden/custom-styled file input.
                if resume_path and os.path.exists(resume_path):
                    try:
                        file_input = scope.locator("input[type=file]").first
                        if file_input.count() > 0:
                            # A real browser file-set can transiently hang; a bounded
                            # retry improves the success rate without ever blocking
                            # for long. If it still fails and the file is required,
                            # the required-field guard below aborts safely.
                            for _attempt in range(2):
                                try:
                                    file_input.set_input_files(resume_path, timeout=5000)
                                    break
                                except Exception:
                                    if _attempt == 1:
                                        raise
                    except Exception:
                        pass
 
                # 4) ANTI-GARBAGE GUARD: only proceed if every required control is
                #    satisfied. If we couldn't map a required field, hand off.
                if not _required_controls_all_satisfied(scope):
                    return {"status": "needs_manual", "reason": "the form has required fields this couldn't fill safely"}
 
                # Capture pre-submit state so confirmation is judged by what CHANGES
                # after submit, not by text/URL that was already present (the fix for
                # a false "sent" when the apply URL or page incidentally contains a
                # confirmation word).
                pre_url = page.url or ""
                pre_text = _confirmation_text_present(page, ctx)
 
                # 5) Submit (within the resolved application form).
                submit = None
                for sel in ["button[type=submit]", "input[type=submit]",
                            "button:has-text('Submit application')", "button:has-text('Submit Application')",
                            "button:has-text('Submit')", "button:has-text('Apply')",
                            "button:has-text('Send application')", "button:has-text('Send')"]:
                    try:
                        loc = scope.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            submit = loc
                            break
                    except Exception:
                        continue
                if submit is None:
                    return {"status": "needs_manual", "reason": "couldn't find a submit button on the form"}
                try:
                    submit.click(timeout=6000)
                except Exception as e:
                    return {"status": "needs_manual", "reason": f"couldn't click submit: {e}"}
                # Bounded wait for the post-submit navigation/confirmation. Capped
                # (not the full request timeout) so a page that never goes network-
                # idle - long-polling, websockets, analytics beacons - can't hang
                # the request; 8s is ample to see a redirect or an inline confirmation.
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
 
                # 6) Only claim success on a real, detectable confirmation - a change
                #    after submit (new URL, or a confirmation phrase that wasn't there
                #    before), never text/URL that was already present.
                if _looks_confirmed(page, ctx, pre_url=pre_url, pre_text=pre_text):
                    return {"status": "submitted", "reason": "submission confirmed by the posting"}
                # We DID click submit but couldn't detect a confirmation. This is
                # materially different from the aborts above (login/CAPTCHA/required
                # field), where we never submitted: the application may well have
                # gone through. Flag it so the caller warns the user to verify rather
                # than silently offering a retry that could double-submit to the
                # employer.
                return {
                    "status": "needs_manual",
                    "reason": "submitted the form but couldn't confirm it went through - verify at the posting before resubmitting",
                    "submitted_unconfirmed": True,
                }
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        _log.warning("Browser auto-submit failed for %s - %s", apply_url, e)
        return {"status": "error", "reason": str(e)}
 
