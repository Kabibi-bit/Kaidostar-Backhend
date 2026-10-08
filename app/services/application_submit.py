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
import re
import os
 
_log = logging.getLogger("kaidostar")
 
# Text seen on a page that means "you must sign in / create an account first".
_LOGIN_MARKERS = ("sign in to apply", "log in to apply", "login to apply", "create an account to apply")
# Text/markup that means a CAPTCHA is present - we never try to defeat these.
_CAPTCHA_SELECTOR = "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha, .h-captcha, [data-sitekey]"
# Text that means the submission went through.
_CONFIRM_MARKERS = (
    # application-specific wording only: a newsletter or talent-community signup's "thanks, we'll be in
    # touch" must never read as a submitted application
    "thank you for applying", "thanks for applying", "thank you for your application", "thanks for your application",
    "application received", "received your application", "application submitted", "application was submitted",
    "application was successfully submitted", "application has been submitted", "application has been received",
    "application has been sent", "application was received", "submitted your application", "application complete",
    "application is complete", "successfully applied",
)
 
 
def _confirmation_line(text) -> str:
    """The confirming words as the page wrote them: the line holding the first confirmation phrase
    (just the phrase when that line is long) - kept as proof of the submission. '' when there is none."""
    text = text if isinstance(text, str) else ""
    for m in _CONFIRM_MARKERS:
        hit = re.search(re.escape(m), text, re.I)
        if not hit:
            continue
        start = text.rfind("\n", 0, hit.start()) + 1
        end = text.find("\n", hit.start())
        line = text[start:end if end >= 0 else len(text)].strip()
        return (line if len(line) <= 160 else hit.group(0))[:200]
    return ""
 
 
# Confirmation-specific URL tokens. Deliberately specific (not bare "complete"/
# "success"/"thank", which appear incidentally in real posting URLs and would
# falsely confirm) and only ever counted when the URL CHANGES after submit -
# i.e. a navigation TO a thank-you page, never the apply URL that was already open.
_CONFIRM_URL_MARKERS = ("thank-you", "thankyou", "thank_you", "/thanks", "confirmation", "/confirmed", "application-received", "application-submitted")
 
 
# The form's other questions (work authorization, sponsorship, start date, EEO...): read in the page
# and answered ONLY from the person's own answer bank (auto_answers.resolve_all). This JavaScript is
# the same, word for word, as the Kaidostar Apply extension's form_fill.js, so the server and the
# extension read and answer a form identically.
_QA_LIB = r"""
  /* @@QA_LIB_START@@ - the form's other questions, read so your answer bank can fill the ones it
   * covers. Shared word for word with the backend's application_submit.py, which runs it in its
   * own browser - so both delivery paths read and answer a form the same way. */
  function qaText(n) { return n ? String(n.innerText || n.textContent || '').replace(/\s+/g, ' ').trim() : ''; }
  function qaAttr(v) { return String(v).replace(/["\\]/g, '\\$&'); }
  function qaVisible(el) {
    try {
      if (!el || el.getClientRects().length === 0) return false;
      var cs = (el.ownerDocument.defaultView || window).getComputedStyle(el);
      return !(cs && (cs.visibility === 'hidden' || cs.visibility === 'collapse'));
    } catch (e) { return true; }
  }
  function qaSetValue(el, value) {
    try {
      var win = el.ownerDocument.defaultView || window;
      var proto = el.tagName === 'TEXTAREA' ? win.HTMLTextAreaElement.prototype : (el.tagName === 'SELECT' ? win.HTMLSelectElement.prototype : win.HTMLInputElement.prototype);
      var desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) desc.set.call(el, value); else el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    } catch (e) { return false; }
  }
  function qaEmptySelect(s) {
    var o = s.options[s.selectedIndex];
    if (!o) return true;
    var v = String(o.value || '').trim(), t = qaText(o).toLowerCase();
    return !v || /^(select|choose|please select|pick|--|\u2014|-)/.test(t);
  }
  function qaLabel(el, d) {
    var t = '';
    try {
      if (el.id) { var l = d.querySelector('label[for="' + qaAttr(el.id) + '"]'); if (l) t = qaText(l); }
      if (!t) { var by = el.getAttribute('aria-labelledby'); if (by) t = by.split(/\s+/).map(function (i) { return qaText(d.getElementById(i)); }).join(' ').trim(); }
      if (!t) t = String(el.getAttribute('aria-label') || '').trim();
      if (!t) { var p = el.closest('label'); if (p) t = qaText(p); }
      if (!t) { var fs = el.closest('fieldset'); if (fs) t = qaText(fs.querySelector('legend')); }
      if (!t) {
        var w = el.parentElement;
        for (var k = 0; k < 3 && w && !t; k++) {
          var cand = w.querySelector('label, legend, .label, [class*="label"], [class*="question"]');
          if (cand && !cand.contains(el) && !cand.querySelector('input, select, textarea')) t = qaText(cand);
          w = w.parentElement;
        }
      }
      if (!t) t = String(el.getAttribute('placeholder') || el.getAttribute('name') || '').trim();
    } catch (e) {}
    return t.slice(0, 300);
  }
  function qaOptionLabel(input, d) {
    var t = '';
    try {
      if (input.id) { var l = d.querySelector('label[for="' + qaAttr(input.id) + '"]'); if (l) t = qaText(l); }
      if (!t) { var p = input.closest('label'); if (p) t = qaText(p); }
      if (!t) t = String(input.getAttribute('aria-label') || input.value || '');
    } catch (e) {}
    return String(t).trim().slice(0, 200);
  }
  function qaGroupLabel(radio, d) {
    try {
      var fs = radio.closest('fieldset');
      if (fs) { var lg = qaText(fs.querySelector('legend')); if (lg) return lg.slice(0, 300); }
      var rg = radio.closest('[role="radiogroup"]');
      if (rg) {
        var t = String(rg.getAttribute('aria-label') || ''), by = rg.getAttribute('aria-labelledby');
        if (!t && by) t = by.split(/\s+/).map(function (i) { return qaText(d.getElementById(i)); }).join(' ');
        if (t.trim()) return t.trim().slice(0, 300);
      }
      var w = radio.parentElement;
      for (var k = 0; k < 6 && w; k++) {
        var cands = w.querySelectorAll('label, legend, .label, [class*="question"], p, span, div');
        for (var j = 0; j < cands.length; j++) {
          var c = cands[j];
          if (c.contains(radio) || c.querySelector('input, select, textarea')) continue;
          var tx = qaText(c);
          if (tx) return tx.slice(0, 300);
        }
        w = w.parentElement;
      }
    } catch (e) {}
    return String(radio.getAttribute('name') || '').slice(0, 300);
  }
  // what a select or radio group says right now (its chosen option's label), '' when nothing is chosen
  function qaCurrent(ref) {
    try {
      if (Array.isArray(ref)) {
        var on = ref.filter(function (r) { return r.checked; })[0];
        return on ? qaOptionLabel(on, on.ownerDocument) : '';
      }
      if (ref.tagName === 'SELECT') { var o = ref.options[ref.selectedIndex]; return o ? qaText(o).slice(0, 200) : ''; }
    } catch (e) {}
    return '';
  }
  var QA_SKIP = { hidden: 1, submit: 1, button: 1, reset: 1, image: 1, file: 1, password: 1, email: 1, tel: 1, search: 1 };
  // -> { questions: [{label, type, options, required}], refs: [element | [radio...]] }
  function collectQuestions(scope) {
    scope = scope || document;
    var d = scope.ownerDocument || scope, out = [], refs = [], seen = {};
    var els;
    try { els = scope.querySelectorAll('select, textarea, input'); } catch (e) { return { questions: [], refs: [] }; }
    for (var i = 0; i < els.length && out.length < 60; i++) {
      var el = els[i], tag = el.tagName, type = String(el.getAttribute('type') || 'text').toLowerCase();
      if (el.disabled) continue;
      if (type !== 'radio' && type !== 'checkbox' && !qaVisible(el)) continue;   // a styled radio/checkbox can hide its input
      var req = !!(el.required || el.getAttribute('aria-required') === 'true');
      if (tag === 'SELECT') {
        // a select the form already answered (no "Select..." placeholder) is still a question: a pre-picked
        // answer to "Will you need sponsorship?" is one you never gave
        var preset = !qaEmptySelect(el);
        var opts = [];
        for (var k = 0; k < el.options.length; k++) { var ot = qaText(el.options[k]); if (ot && String(el.options[k].value || '').trim()) opts.push(ot.slice(0, 200)); }
        out.push({ label: qaLabel(el, d), type: 'select', options: opts.slice(0, 60), required: req, preset: preset, current: preset ? qaCurrent(el) : '' }); refs.push(el);
      } else if (tag === 'TEXTAREA') {
        if (String(el.value || '').trim()) continue;
        out.push({ label: qaLabel(el, d), type: 'textarea', options: [], required: req }); refs.push(el);
      } else if (type === 'radio') {
        var key = el.name ? 'n:' + el.name : 'i:' + i;
        if (seen[key]) continue;
        seen[key] = 1;
        var group = el.name ? Array.prototype.filter.call(scope.querySelectorAll('input[type=radio]'), function (r) { return r.name === el.name; }) : [el];
        var on = group.some(function (r) { return r.checked; });
        var reqG = group.some(function (r) { return r.required || r.getAttribute('aria-required') === 'true'; });
        out.push({ label: qaGroupLabel(el, d), type: 'radio', options: group.map(function (r) { return qaOptionLabel(r, d); }), required: reqG, preset: on, current: on ? qaCurrent(group) : '' }); refs.push(group);
      } else if (type === 'checkbox') {
        // a required box is a question - and so is any box the form ticked by itself (a pre-ticked "I agree", an
        // opt-in): that is an answer you never gave. An optional box left unticked is left alone.
        if (!el.checked && !req) continue;
        out.push({ label: qaOptionLabel(el, d) || qaLabel(el, d), type: 'checkbox', options: [], required: req, preset: !!el.checked, current: el.checked ? 'ticked' : '' }); refs.push(el);
      } else if (!QA_SKIP[type]) {
        if (String(el.value || '').trim()) continue;
        if (/captcha|honeypot|bot-?field/i.test(String(el.name || '') + ' ' + String(el.id || ''))) continue;
        out.push({ label: qaLabel(el, d), type: ['number', 'date', 'url'].indexOf(type) >= 0 ? type : 'text', options: [], required: req }); refs.push(el);
      }
    }
    return { questions: out, refs: refs };
  }
  // answers: [{i, option, answer, check, missing}] from the server's resolver. Returns how many were filled.
  function applyAnswers(refs, answers) {
    var done = 0;
    (answers || []).forEach(function (a) {
      if (!a || a.missing || a.i == null || !refs[a.i]) return;
      var ref = refs[a.i];
      try {
        if (Array.isArray(ref)) {
          var d = ref[0].ownerDocument;
          var pick = ref.filter(function (r) { return qaOptionLabel(r, d) === a.option; })[0];
          if (!pick) return;
          pick.click();
          if (!pick.checked) { pick.checked = true; pick.dispatchEvent(new Event('change', { bubbles: true })); }
          ref.forEach(function (r) { r.setAttribute('data-kaido-answered', '1'); });
          done++;
        } else if (ref.tagName === 'SELECT') {
          var opt = Array.prototype.filter.call(ref.options, function (o) { return qaText(o).slice(0, 200) === a.option; })[0];
          if (!opt || !qaSetValue(ref, opt.value)) return;
          ref.setAttribute('data-kaido-answered', '1');
          done++;
        } else if (String(ref.getAttribute('type') || '').toLowerCase() === 'checkbox') {
          if (a.check && !ref.checked) ref.click();
          if (ref.checked) { ref.setAttribute('data-kaido-answered', '1'); done++; }
        } else if (a.answer && qaSetValue(ref, String(a.answer))) {
          ref.setAttribute('data-kaido-answered', '1');
          done++;
        }
      } catch (e) {}
    });
    return done;
  }
  /* @@QA_LIB_END@@ */
"""
_QA_COLLECT_JS = "(scope) => {" + _QA_LIB + " var r = collectQuestions(scope || document); window.__kaidoQaRefs = r.refs; return r.questions; }"
_QA_APPLY_JS = "(answers) => {" + _QA_LIB + " return applyAnswers(window.__kaidoQaRefs || [], answers); }"
 
 
def _answer_questions(ctx, scope, answer_bank, job_country=None) -> dict:
    """Fill the questions the answer bank covers. Never raises; returns what happened."""
    try:
        from app.services.auto_answers import resolve_all
        questions = scope.evaluate(_QA_COLLECT_JS) if scope is not ctx else ctx.evaluate(_QA_COLLECT_JS)
        if not isinstance(questions, list) or not questions:
            return {"asked": 0, "filled": 0, "missing": [], "given": [], "blocking": []}
        answers = resolve_all(questions, answer_bank, job_country)
        filled = ctx.evaluate(_QA_APPLY_JS, answers) or 0
 
        def label(a):
            q = questions[a["i"]] if 0 <= a["i"] < len(questions) and isinstance(questions[a["i"]], dict) else {}
            return str(q.get("label") or "")[:120]
        missing = [{"label": label(a), "why": a.get("why", "")} for a in answers if a.get("missing") and a.get("required")]
        blocking = [{"label": label(a), "why": a.get("why", "")} for a in answers if a.get("missing") and a.get("blocking")]
        given = [{"label": label(a), "answer": str(a.get("answer") or "")[:120]} for a in answers if not a.get("missing")]
        return {"asked": len(questions), "filled": int(filled), "missing": missing[:10], "given": given[:40], "blocking": blocking[:10]}
    except Exception as e:
        # the form's questions couldn't be read or answered: stop rather than submit unchecked answers
        _log.info("Answer filling failed - %s", e)
        return {"asked": 0, "filled": 0, "missing": [], "given": [], "blocking": [], "failed": True}
 
 
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
                    # A required dropdown is UNSATISFIED unless Kaidostar set it from the
                    # person's OWN answer bank (marked data-kaido-answered when filled).
                    # Many required selects are high-stakes - visa sponsorship, work
                    # authorization, EEO/veteran/disability status - and a <select> always
                    # has a default option, so trusting any other value would mean
                    # auto-submitting a GUESSED answer under the person's name.
                    if not c.evaluate("el => el.getAttribute('data-kaido-answered') === '1' && !!String(el.value || '').trim()"):
                        return False
                    continue
                type_attr = (c.get_attribute("type") or "").lower()
                if type_attr == "radio":
                    # one checked choice in the group answers it (the other options stay unchecked)
                    if not c.evaluate("el => el.name ? Array.prototype.some.call((el.form || el.ownerDocument).querySelectorAll('input[type=radio]'), function (r) { return r.name === el.name && r.checked; }) : el.checked"):
                        return False
                    continue
                if type_attr == "checkbox":
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
# Kaidostar submits on its own only on employers' hiring systems, where a page is one job's application
# (the job engine's list; the runner passes it). On a company's own site the person makes the final click.
_ATS_DOMAINS = ("greenhouse.io", "lever.co", "myworkdayjobs.com", "workday.com", "ashbyhq.com", "smartrecruiters.com", "icims.com", "jobvite.com", "bamboohr.com", "breezy.hr", "workable.com", "recruitee.com", "taleo.net", "successfactors.com", "paylocity.com", "ultipro.com", "rippling.com", "dover.com", "jazzhr.com", "applytojob.com", "teamtailor.com")
 
 
def _on_ats(url, domains=None) -> bool:
    m = re.match(r"^https?://([^/?#:]+)", str(url or ""), re.I)
    host = (m.group(1) if m else "").lower()
    return bool(host) and any(host == d or host.endswith("." + d) for d in (domains or _ATS_DOMAINS))
 
 
# A selector that means "an application form is present here" - used to find the
# right frame and to wait for a single-page-app form to finish rendering.
_FORM_PRESENT = (
    "input[type=email], input[type=file], input[name*=email i], "
    "input[name*=first i], input[name*='resume' i], textarea"
)
 
 
def _resolve_form_context(page, timeout_ms: int, job_title=None):
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
        # Otherwise, any frame (incl. the main page) that holds an actual application form - a
        # newsletter box on the outer page must not win over the application in an iframe.
        for f in [page.main_frame] + [fr for fr in page.frames if fr is not page.main_frame]:
            try:
                if f.locator(_FORM_PRESENT).count() > 0 and _resolve_application_form(f, job_title) is not None:
                    return f
            except Exception:
                continue
        try:
            page.wait_for_timeout(500)
        except Exception:
            break
    # nothing that looks like an application: the first frame with fields (the caller then finds no
    # application form there and stops without filling anything)
    for f in [page.main_frame] + [fr for fr in page.frames if fr is not page.main_frame]:
        try:
            if f.locator(_FORM_PRESENT).count() > 0:
                return f
        except Exception:
            continue
    return page
 
 
_TITLE_STOP = {"the", "and", "for", "with", "senior", "junior", "lead", "remote", "hybrid", "onsite", "level", "new", "grad", "full", "part", "time",
               "contract", "temporary", "temp", "entry", "associate", "staff", "principal", "sr", "jr"}
 
 
def _title_words(t):
    return [w for w in re.split(r"[^a-z0-9+#]+", str(t or "").lower().replace("\u2019", "'").replace("\u2018", "'")) if len(w) >= 3 and w not in _TITLE_STOP]
 
 
def _title_on_page(ctx, title) -> bool:
    """Does the page name this job? (Most of its title's words appear on it.) True when there's no title to check.
    The extension's own check (titleSeen, in the shared block), run in the page."""
    if not _title_words(title):
        return True
    try:
        return bool(ctx.evaluate("(t) => {" + _FORMLESS_LIB + " return titleSeen(document, t); }", str(title)))
    except Exception:
        return False
 
 
def _resolve_application_form(ctx, job_title=None):
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
            has_file = f.locator("input[type=file]").count() > 0
            has_name = f.locator("input[name*=first i], input[name*='full_name' i], input[name*='full-name' i], input[name*=fullname i], input[name='name'], input[autocomplete='name'], input[autocomplete='given-name']").count() > 0
            has_email = f.locator("input[type=email], input[name*=email i], input[autocomplete='email']").count() > 0
            has_phone = f.locator("input[type=tel], input[name*=phone i]").count() > 0
            info = f.evaluate(_FORM_INFO_JS, str(job_title or "")) or {}
            button = str(info.get("button") or "")
            apply_btn = "appl" in button  # "apply" / "application"
            s = 3 * has_file + 2 * has_name + has_email + has_phone + 2 * apply_btn
            # an application asks for a resume or who you are - an email box alone is a newsletter or a contact form
            if not (has_file or (has_name and has_email) or apply_btn):
                continue
            # a form that says it's a sign-up or a general application isn't this job's, whatever its button says -
            # nor is one on a page whose title or heading says so ("Join our talent community")
            general_job = bool(_SIGNUP_PAGE.search(str(job_title or "")) or _OWN_SIGNUP.search(str(job_title or "")))
            if not general_job and ((_OWN_SIGNUP if apply_btn else _NOT_APPLICATION).search(str(info.get("own") or "").replace("\u2019", "'").replace("\u2018", "'"))
                                    or info.get("signup") or (apply_btn and _OWN_SIGNUP.search(str(info.get("sect") or "")))):
                continue
            # ... and an "apply" form among a general application's words ("Don't see the right role? Send us your CV")
            # counts only on a page that names the job
            if apply_btn and job_title and (_NOT_APPLICATION.search(str(info.get("own") or "")) or _NOT_APPLICATION.search(str(info.get("text") or ""))) \
                    and not _title_on_page(ctx, job_title):
                continue
            # ... nor one in such a section, unless its own button says "apply"
            if not apply_btn and (_NOT_APPLICATION_BTN.search(button.strip()) or _NOT_APPLICATION.search(str(info.get("text") or "").replace("\u2019", "'").replace("\u2018", "'"))):
                continue
            # ... and a form whose button doesn't say "apply" is this job's application only if the page names the job
            if not apply_btn and job_title and not _title_on_page(ctx, job_title):
                continue
        except Exception:
            continue
        if s > best_score:
            best_score = s
            best = f
    if best is None:
        try:
            if ctx.evaluate(_FORMLESS_JS, str(job_title or "")):
                return ctx.locator("[data-kaido-app-root='1']").first
        except Exception:
            pass
    return best
 
 
# an application with no <form> element: found and marked in the page (the same function as the extension's)
_FORMLESS_LIB = r"""  /* @@FORMLESS_START@@ - some hiring systems render the application without a <form> element. Then the
   * application is the smallest block around the resume upload (or the name field) that also holds an email
   * box and an "apply" / "submit application" button - and no other form inside it. Also here: how a page that
   * is itself a sign-up is recognized, and which button submits an application. Shared word for word with
   * application_submit.py. */
  // the words of a sign-up, a newsletter or a general "send us your CV" form - never one job's application
  var NOT_APPLICATION = /talent (?:community|network|pool)|join our talent|newsletter|subscribe|job alerts?|stay in touch|sign up for|get notified|don'?t see (?:the right|a suitable|a matching|an? open|your)|general application|future (?:opportunities|openings|roles|positions)|share your (?:resume|cv)|keep (?:your resume|you) on file|expression of interest|open application|speculative application|no (?:current )?openings|not (?:quite )?the (?:right )?role/i;
  // ... and the words that, in a page's title or headings, make the whole page a sign-up whatever its buttons say
  // (a job's description may mention "future opportunities"; a job's page is not titled "Join our talent community")
  var SIGNUP_PAGE = /talent (?:community|network|pool)|join our talent|newsletter|job alerts?|general application|open application|speculative application|expression of interest/i;
  // ... and, in the text of a form whose button says "apply", the words that invite you to sign up (an application's
  // own privacy note may say it keeps you "in our talent pool" - that doesn't make it a sign-up)
  var OWN_SIGNUP = /join (?:our|the) talent|(?:sign up|subscribe) (?:for|to) (?:our )?(?:job alerts?|newsletter)|general application|open application|speculative application|expression of interest|don'?t see (?:the right|a suitable|a matching|an? open|your)|share your (?:resume|cv)/i;
  // a block's own words - without its sidebars, menus and footers, or the labels of its tick boxes and choices
  // ("Send me job alerts" is an opt-in on an application, a "Job alerts" sidebar is beside it - neither is what it is)
  function ownText(el) {
    var raw = String((el && (el.innerText || el.textContent)) || "");
    try {
      var cut = function (n) { var x = n ? String(n.innerText || n.textContent || "").trim() : ""; if (x) raw = raw.split(x).join(" "); };
      var side = el.querySelectorAll("aside, nav, footer");
      for (var s = 0; s < side.length && s < 20; s++) cut(side[s]);
      var boxes = el.querySelectorAll("input[type=checkbox], input[type=radio]");
      for (var i = 0; i < boxes.length && i < 60; i++) {
        cut(boxes[i].closest("label") || (boxes[i].id ? el.querySelector('label[for="' + String(boxes[i].id).replace(/["\\]/g, "\\$&") + '"]') : null));
      }
    } catch (e) {}
    return raw.replace(/[\u2019\u2018]/g, "'").slice(0, 6000);
  }
  // the words of the section a form sits in (its container - not the whole page): "Don't see the right role? Send us
  // your CV" just above an "Apply" button makes that form a general one
  function sectionText(el) {
    var pe = el && el.parentElement;
    if (!pe || /^(?:BODY|MAIN|HTML)$/.test(pe.tagName)) return "";
    return ownText(pe);
  }
  // the page's title and main headings, and the heading of the section the form sits in (the last heading before
  // it, when that heading's own container holds the form - never a sidebar's or a footer's)
  function pageHeads(docu, el) {
    var t = String((docu && docu.title) || ""), last = null;
    try {
      var hs = docu.querySelectorAll("h1, h2, h3, [role=heading]");
      for (var i = 0; i < hs.length && i < 80; i++) {
        var h = hs[i];
        if (h.tagName === "H1") t += " | " + String(h.innerText || h.textContent || "").slice(0, 200);
        if (el && !el.contains(h) && (h.compareDocumentPosition(el) & 4) && !h.closest("aside, nav, footer")) last = h;
      }
      if (last && last.parentElement && last.parentElement.contains(el)) t += " | " + String(last.innerText || last.textContent || "").slice(0, 200);
    } catch (e) {}
    return t.replace(/[\u2019\u2018]/g, "'");
  }
  // the job you chose is itself a general application or a talent community: then that form is the one you want
  function generalJob(jobTitle) { var t = String(jobTitle || ""); return SIGNUP_PAGE.test(t) || OWN_SIGNUP.test(t); }
  function signUpPage(docu, el, jobTitle) {
    if (generalJob(jobTitle)) return false;
    return SIGNUP_PAGE.test(pageHeads(docu, el));
  }
  // does the page name this job? (most of its title's words appear on it - true when there's no title to check)
  var TITLE_STOP = { the: 1, and: 1, for: 1, with: 1, senior: 1, junior: 1, lead: 1, remote: 1, hybrid: 1, onsite: 1, level: 1, new: 1, grad: 1,
    full: 1, part: 1, time: 1, contract: 1, temporary: 1, temp: 1, entry: 1, associate: 1, staff: 1, principal: 1, sr: 1, jr: 1 };
  function titleWords(t) {
    return String(t || "").toLowerCase().replace(/[\u2019\u2018]/g, "'").split(/[^a-z0-9+#]+/).filter(function (w) { return w.length >= 3 && !TITLE_STOP[w]; });
  }
  function titleSeen(docu, title) {
    var words = titleWords(title);
    if (!words.length) return true;
    var text = (String((docu && docu.title) || "") + " " + String((docu && docu.body && (docu.body.innerText || docu.body.textContent)) || "")).toLowerCase().slice(0, 30000);
    var hits = words.filter(function (w) { return new RegExp("(?:^|[^a-z0-9])" + w.replace(/[+#]/g, "\\$&") + "(?:[^a-z0-9]|$)").test(text); }).length;
    return hits >= Math.max(1, Math.ceil(words.length * 0.6));
  }
  var APP_NAME_SEL = "input[name*=first i], input[name*='full_name' i], input[name*='full-name' i], input[name*=fullname i], input[name='name'], input[autocomplete='name'], input[autocomplete='given-name']";
  var APP_EMAIL_SEL = "input[type=email], input[name*=email i], input[autocomplete='email']";
  function formlessApplication(docu, jobTitle) {
    try {
      var inputs = docu.querySelectorAll("input[type=file], " + APP_NAME_SEL);
      var anchor = null;
      for (var i = 0; i < inputs.length && !anchor; i++) if (!inputs[i].closest("form")) anchor = inputs[i];
      if (!anchor) return null;
      var el = anchor.parentElement;
      for (var k = 0; k < 12 && el && el !== docu.documentElement; k++, el = el.parentElement) {
        if (el.querySelector("form")) return null;   // a block that holds another form is the page, not the application
        if (!el.querySelector(APP_EMAIL_SEL)) continue;
        if (!(el.querySelector("input[type=file]") || el.querySelector(APP_NAME_SEL))) continue;
        var btns = el.querySelectorAll("button, input[type=submit], [role=button]");
        for (var j = 0; j < btns.length; j++) {
          var t = ((btns[j].innerText || btns[j].value || btns[j].textContent || "") + "").toLowerCase();
          // "Apply to join our talent community" isn't a job's application
          if (t.indexOf("appl") !== -1) {
            var own = ownText(el);
            if (!generalJob(jobTitle) && (OWN_SIGNUP.test(own) || OWN_SIGNUP.test(sectionText(el)) || signUpPage(docu, el, jobTitle))) return null;
            // a general "send us your CV" block counts only on a page that names the job
            return (jobTitle && NOT_APPLICATION.test(own) && !titleSeen(docu, jobTitle)) ? null : el;
          }
        }
      }
    } catch (e) {}
    return null;
  }
  // The button that sends the application: one that says submit / apply / send / finish - never "Save for
  // later", "Back", "Next", "Apply with LinkedIn" and the like (a saved draft is not an application sent, and a
  // multi-step form's "Next" is not its last step). The form's own submit button comes first.
  var SUBMIT_WORDS = /^(?:submit|apply|send|finish|complete)\b|\bsubmit\b/i;
  var SUBMIT_SKIP = /\b(?:save|saved|draft|later|back|previous|prev|cancel|reset|clear|preview|upload|attach|add|remove|delete|search|sign ?in|log ?in|login|next|continue|edit|print|share|subscribe|join|alerts?|notify|linkedin|indeed|google|facebook|github|dropbox|drive|seek|xing|autofill|auto-fill|manual|manually|import)\b/i;
  function shownEl(el) {
    try {
      if (!el || el.getClientRects().length === 0) return false;
      var cs = (el.ownerDocument.defaultView || window).getComputedStyle(el);
      return !(cs && (cs.visibility === "hidden" || cs.visibility === "collapse"));
    } catch (e) { return true; }
  }
  function pickSubmit(scope) {
    var els, later = null;
    try { els = scope.querySelectorAll("button, input[type=submit], input[type=button], [role=button]"); } catch (e) { return null; }
    for (var i = 0; i < els.length; i++) {
      var b = els[i];
      if (b.disabled || !shownEl(b)) continue;
      var t = String(b.innerText || b.value || b.textContent || b.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim();
      if (!t || t.length > 60 || !SUBMIT_WORDS.test(t) || SUBMIT_SKIP.test(t)) continue;
      if (String(b.type || "").toLowerCase() === "submit") return b;
      if (!later) later = b;
    }
    return later;
  }
  /* @@FORMLESS_END@@ */
"""
_FORMLESS_JS = "(jt) => {" + _FORMLESS_LIB + " var el = formlessApplication(document, jt); if (!el) return false; el.setAttribute('data-kaido-app-root', '1'); return true; }"
# the button that sends the application (pickSubmit - never "Save for later", "Next" or "Apply with LinkedIn"), marked
_PICK_SUBMIT_JS = ("(scope) => {" + _FORMLESS_LIB + " var old = document.querySelectorAll('[data-kaido-submit]'); for (var i = 0; i < old.length; i++) old[i].removeAttribute('data-kaido-submit');"
                   " var b = pickSubmit(scope); if (!b) return false; b.setAttribute('data-kaido-submit', '1'); return true; }")
 
 
# the words around a form that collects sign-ups, not applications - and the buttons such forms have
# (the same rules as the extension's applicationForm)
_NOT_APPLICATION = re.compile(r"talent (?:community|network|pool)|join our talent|newsletter|subscribe|job alerts?|stay in touch|sign up for|get notified|don'?t see (?:the right|a suitable|a matching|an? open|your)|general application|future (?:opportunities|openings|roles|positions)|share your (?:resume|cv)|keep (?:your resume|you) on file|expression of interest|open application|speculative application|no (?:current )?openings|not (?:quite )?the (?:right )?role", re.I)
_NOT_APPLICATION_BTN = re.compile(r"^(?:join|subscribe|sign ?up|notify me|get (?:job )?alerts?|create (?:an? )?alert|keep me posted)", re.I)
# the plain sign-up words: all that counts in the text of a form whose button says "apply" (an application's own privacy
# note may mention "future positions") - the same as the extension's SIGNUP_PAGE
_SIGNUP_PAGE = re.compile(r"talent (?:community|network|pool)|join our talent|newsletter|job alerts?|general application|open application|speculative application|expression of interest", re.I)
_OWN_SIGNUP = re.compile(r"join (?:our|the) talent|(?:sign up|subscribe) (?:for|to) (?:our )?(?:job alerts?|newsletter)|general application|open application|speculative application|expression of interest|don'?t see (?:the right|a suitable|a matching|an? open|your)|share your (?:resume|cv)", re.I)
# a form's own words plus the section around it and the page title, its first button's words - and whether the
# page itself is a sign-up (its title or the heading the form sits under says so)
_FORM_INFO_JS = "(f, jt) => {" + _FORMLESS_LIB + """
  var t = ownText(f), pe = f.parentElement;
  for (var k = 0; k < 2 && pe; k++) { t += ' ' + ownText(pe).slice(0, 4000); pe = pe.parentElement; }
  var sub = pickSubmit(f) || f.querySelector('button[type=submit], input[type=submit], button');
  return { own: ownText(f), text: (t + ' ' + String(document.title || '')).slice(0, 12000),
           button: sub ? String(sub.innerText || sub.value || '').trim().toLowerCase() : '', signup: signUpPage(document, f, jt), sect: sectionText(f) };
}"""
 
 
def submit_application_via_browser(
    apply_url: str,
    candidate: dict,
    resume_path: str | None = None,
    cover_letter: str | None = None,
    timeout_ms: int = 25000,
    answer_bank: dict | None = None,
    job_country: str | None = None,
    job_title: str | None = None,
    ats_domains: list | None = None,
) -> dict:
    """Attempt a real submission at apply_url. See module docstring for the
    status contract and the safety model. candidate keys used (all optional):
    full_name, first_name, last_name, email, phone. answer_bank: the person's
    own answers (auto_answers) - other questions are answered only from it.
    On "submitted" the result carries proof: the page and the words that
    confirmed it."""
    if not apply_url or not str(apply_url).startswith(("http://", "https://")):
        return {"status": "needs_manual", "reason": "no real application URL to open"}
 
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"status": "unavailable", "reason": "browser automation is not available in this environment"}
 
    candidate = candidate or {}
    clicked = {"done": False}
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
                ctx = _resolve_form_context(page, timeout_ms, job_title)
 
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
 
                # Operate only within the actual application form, so on a page with several
                # forms (a newsletter signup, a talent-community form, a site search) we never
                # fill a decoy's field, let a decoy's required field block us, or submit the
                # wrong form. No identifiable application form: nothing is filled or submitted.
                scope = _resolve_application_form(ctx, job_title)
                if scope is None:
                    return {"status": "needs_manual", "reason": "couldn't identify the application form on the page"}
                # only on an employer's hiring system: a company's own site may hold other forms
                # (a general "send us your CV", a talent community) - there the person makes the final click
                ctx_url = getattr(ctx, "url", "") or page.url or ""
                if not _on_ats(ctx_url, ats_domains):
                    return {"status": "needs_manual", "reason": "the form is on the company's own site, where Kaidostar leaves the final click to you"}
 
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
                        "textarea[name='job_application[cover_letter_text]']",
                        # (never "any textarea": an essay question must not receive the cover letter)
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
 
                # 3b) The form's other questions, answered only from the person's own bank.
                qa = _answer_questions(ctx, scope, answer_bank, job_country) if answer_bank is not None else {"asked": 0, "filled": 0, "missing": [], "given": [], "blocking": []}
 
                # 3c) A sensitive question the form answered by itself (a pre-picked "No" to sponsorship)
                #     that the person's bank doesn't cover: never submitted as if it were their answer.
                if qa.get("failed"):
                    return {"status": "needs_manual", "reason": "Kaidostar couldn't read the form's questions safely"}
                if qa.get("blocking"):
                    return {"status": "needs_manual", "reason": "the form already had an answer you didn't give picked or ticked (" + "; ".join(m["label"] for m in qa["blocking"][:3] if m["label"]) + ") - Kaidostar never submits those for you", "missing": qa["blocking"]}
 
                # 4) ANTI-GARBAGE GUARD: only proceed if every required control is
                #    satisfied. If we couldn't map a required field, hand off.
                if not _required_controls_all_satisfied(scope):
                    if qa["missing"]:
                        return {"status": "needs_manual", "reason": "the form asks something your answer bank doesn't cover (" + "; ".join(m["label"] for m in qa["missing"][:3] if m["label"]) + ")", "missing": qa["missing"]}
                    return {"status": "needs_manual", "reason": "the form has required fields this couldn't fill safely"}
 
                # Capture pre-submit state so confirmation is judged by what CHANGES
                # after submit, not by text/URL that was already present (the fix for
                # a false "sent" when the apply URL or page incidentally contains a
                # confirmation word).
                pre_url = page.url or ""
                pre_text = _confirmation_text_present(page, ctx)
 
                # 5) Submit (within the resolved application form) - only a button that says it sends the
                #    application, never "Save for later", "Next" or "Apply with LinkedIn" (the same choice as the extension's)
                submit = None
                try:
                    if scope.evaluate(_PICK_SUBMIT_JS):
                        loc = scope.locator("[data-kaido-submit='1']").first
                        if loc.count() > 0:
                            submit = loc
                except Exception:
                    submit = None
                if submit is None:
                    return {"status": "needs_manual", "reason": "couldn't find the button that submits the application (a multi-step form, or one that only saves a draft)"}
                try:
                    # don't wait for the page to navigate inside the click: a slow submit must not
                    # look like a click that never happened (the wait below covers the navigation)
                    submit.click(timeout=6000, no_wait_after=True)
                except Exception as e:
                    return {"status": "needs_manual", "reason": f"couldn't click submit: {e}"}
                clicked["done"] = True
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
                    phrase = ""
                    for c in (ctx, page):
                        try:
                            phrase = _confirmation_line(c.locator("body").inner_text(timeout=3000) or "")
                            if phrase:
                                break
                        except Exception:
                            continue
                    return {"status": "submitted", "reason": "submission confirmed by the posting",
                            "proof": {"url": (page.url or "")[:500], "phrase": phrase, "answered": qa["filled"], "answers": qa.get("given") or []}}
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
        if clicked["done"]:
            # the form was submitted before something failed: it may well have gone through
            return {"status": "needs_manual", "reason": "submitted the form but couldn't confirm it went through - verify at the posting before resubmitting",
                    "submitted_unconfirmed": True}
        return {"status": "error", "reason": str(e)}
 
