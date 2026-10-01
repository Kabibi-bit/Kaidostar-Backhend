"""Strong-password policy - the server-side source of truth.
 
The frontend shows a live strength meter and the same requirements, but THIS is
what's enforced: signup (and any future password change) runs validate_password
and refuses anything that fails. A real account needs a password that can't be
trivially guessed or reused from a breach list, so this checks length, character
variety, obvious-sequence/repeat patterns, a common-password blocklist, and
similarity to the user's own email.
 
Pure and dependency-free so it's unit-testable and identical in meaning to the
mirrored JS scorer in the login page.
"""
import re
 
MIN_LENGTH = 10
MAX_BYTES = 72  # bcrypt's hard limit (see services/auth.py)
 
# A compact blocklist of the passwords that show up at the very top of every
# breach corpus, plus obvious app-specific ones. Not exhaustive - the structural
# checks below catch the long tail - but it stops the worst offenders outright.
COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "123456", "1234567",
    "12345678", "123456789", "1234567890", "qwerty", "qwertyuiop", "qwerty123",
    "111111", "000000", "abc123", "abcd1234", "letmein", "welcome", "welcome1",
    "admin", "admin123", "iloveyou", "monkey", "dragon", "sunshine", "princess",
    "football", "baseball", "superman", "trustno1", "changeme", "default",
    "kaidostar", "kaidostar1", "kaidostar123",
}
 
_SEQUENCES = ["abcdefghijklmnopqrstuvwxyz", "0123456789", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
 
 
def _has_long_run_or_sequence(pw: str) -> bool:
    """True if the password is mostly a single repeated char or a keyboard/number
    run (e.g. 'aaaaaa', 'abcdefg', '123456') - low-entropy even if it's long."""
    low = pw.lower()
    # 4+ of the same character in a row
    if re.search(r"(.)\1{3,}", low):
        return True
    # a run of 5+ consecutive sequence characters (forwards or backwards)
    for seq in _SEQUENCES:
        rev = seq[::-1]
        for base in (seq, rev):
            for i in range(len(base) - 4):
                if base[i:i + 5] in low:
                    return True
    return False
 
 
def validate_password(password: str, email: str | None = None) -> tuple:
    """Return (ok, errors). ok is True only when errors is empty."""
    errors = []
    pw = password or ""
    if len(pw) < MIN_LENGTH:
        errors.append(f"Use at least {MIN_LENGTH} characters.")
    if len(pw.encode("utf-8")) > MAX_BYTES:
        errors.append("Too long - keep it under 72 bytes.")
    if not re.search(r"[a-z]", pw):
        errors.append("Add a lowercase letter.")
    if not re.search(r"[A-Z]", pw):
        errors.append("Add an uppercase letter.")
    if not re.search(r"[0-9]", pw):
        errors.append("Add a number.")
    if not re.search(r"[^A-Za-z0-9]", pw):
        errors.append("Add a symbol (e.g. ! ? # $).")
    if pw.lower() in COMMON_PASSWORDS:
        errors.append("That's a commonly used password - choose something more unique.")
    if _has_long_run_or_sequence(pw):
        errors.append("Avoid repeated characters or simple sequences like 'aaaa' or '12345'.")
    if email:
        local = str(email).split("@")[0].lower()
        if len(local) >= 3 and local in pw.lower():
            errors.append("Don't put your email or name in the password.")
    return (len(errors) == 0, errors)
 
 
def strength_score(password: str) -> dict:
    """A 0-4 score + label for the UI meter. Separate from validate_password:
    a password can be 'valid' yet only 'fair'. Mirrored in the login page JS."""
    pw = password or ""
    if not pw:
        return {"score": 0, "label": "Enter a password"}
    score = 0
    if len(pw) >= MIN_LENGTH:
        score += 1
    if len(pw) >= 14:
        score += 1
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if classes >= 3:
        score += 1
    if classes == 4 and len(pw) >= 12:
        score += 1
    if pw.lower() in COMMON_PASSWORDS or _has_long_run_or_sequence(pw):
        score = min(score, 1)
    score = max(0, min(4, score))
    label = ["Very weak", "Weak", "Fair", "Strong", "Very strong"][score]
    return {"score": score, "label": label}
 
