"""Server-side Pathways Atlas engine.
 
The Roadmap page shows not one route but the whole terrain: a branching
graph of dozens of real pathways from where the person is now to their
goal, scored against what they care about, with the strongest route
recommended. The browser has a client engine for instant, offline use;
this is its authoritative server counterpart, grounded in REAL data:
 
  * skill-gap nodes come from tags that recur in the person's real ranked
    listings but aren't in their stated skills/goal,
  * supporting matches on a node are real listings (title / org / fit %),
  * the "apply" node names the person's real current top match,
  * the recommendation is computed by the same scoring model the client
    uses, so server and client agree.
 
Deliberately pure: no DB or SQLAlchemy imports. The caller passes an
already-ranked list of listing dicts (each with title/org/tags and a
score_pct), the profile dict, and the detected skill gaps. That keeps the
whole engine unit-testable on its own and impossible to break with a bad
query.
"""
from __future__ import annotations
 
import re
 
FAMILIES = {
    "credential": {"name": "Credential", "color": "#7BA9FF", "desc": "Courses, certs, structured programs."},
    "portfolio":  {"name": "Portfolio",  "color": "#5FE0B8", "desc": "Build public proof of the work."},
    "network":    {"name": "Network",    "color": "#F0B24E", "desc": "People, referrals, warm intros."},
    "internal":   {"name": "Internal",   "color": "#9B87F5", "desc": "Move up or across from where you are."},
    "sidedoor":   {"name": "Side-door",  "color": "#C98BE0", "desc": "Contract, agency, adjacent entry."},
}
FAM_KEYS = list(FAMILIES.keys())
 
LAYER_ORDER = ["start", "found", "proof", "access", "break", "goal"]
 
DEFAULT_CONSTRAINTS = {
    "priority": "balanced",   # balanced | speed | certainty | ceiling
    "timeWeeks": 52,
    "risk": 40,               # 0..100
    "budget": "free",         # free | low | any
    "families": {k: True for k in FAM_KEYS},
}
 
MAXW = 48.0
MAXCOST = 2.4
 
 
# ---------------------------------------------------------------- helpers
def _first_phrase(s):
    return re.split(r"[.,;]", str(s or ""))[0].strip()
 
 
def _weeks_from_speed(sp):
    return max(1, round(2 + (1 - sp) * 11))
 
 
_STOP = {"the", "a", "an", "to", "of", "in", "at", "for", "and", "or", "on", "with", "into", "your", "you"}
 
 
def _toks(s):
    return [w for w in re.split(r"[^a-z0-9+]+", str(s or "").lower()) if w and w not in _STOP and len(w) > 1]
 
 
def _match(tokens, tag):
    tag = str(tag or "").lower()
    if not tag:
        return False
    return any(t == tag or (len(t) > 3 and t in tag) or (len(tag) > 3 and tag in t) for t in tokens)
 
 
def _short_goal_word(goal):
    w = re.sub(r"^(break into|get into|become a|become an|land a|land an|a career in|work in)\s+", "", goal, flags=re.I).strip()
    return " ".join(w.split()[:3]) or "the role"
 
 
def _support(ranked, keywords, n=3):
    """Real listings whose tags match the node's keywords."""
    toks = _toks(keywords)
    out = []
    for l in ranked or []:
        tags = l.get("tags") or []
        if any(_match(toks, tag) for tag in tags):
            out.append({"title": l.get("title"), "org": l.get("org"), "pct": l.get("score_pct")})
        if len(out) >= n:
            break
    return out
 
 
# ---------------------------------------------------------------- build
def build_atlas(profile, ranked, skill_gaps):
    ranked = ranked or []
    skill_gaps = skill_gaps or []
    goal = _first_phrase(profile.get("northstar")) or "your goal"
    final = _first_phrase(profile.get("final_idea") or profile.get("finalidea")) or goal
    core_skill = (str(profile.get("skills") or "").split(",")[0] or "").strip()
    stage = str(profile.get("stage") or "")
    employed = bool(re.search(r"grad|working|employed|career|profess", stage, re.I) or
                    re.search(r"transfer|internal|current role", str(profile.get("northstar") or ""), re.I))
    top = ranked[0] if ranked else None
    role_word = "people already doing " + goal
    sgw = _short_goal_word(goal)
 
    nodes = []
 
    def add(n):
        fam = FAMILIES.get(n.get("family"), FAMILIES["portfolio"])
        n["color"] = fam["color"]
        if not n.get("weeks"):
            n["weeks"] = _weeks_from_speed(n.get("speed", 0.5))
        fit = 0.5
        if n.get("gap"):
            fit += 0.22
        if n.get("support"):
            fit += 0.12
        if n.get("goalTie"):
            fit += 0.12
        n["fit"] = max(0.15, min(1.0, fit + n.get("_fitAdj", 0)))
        # normalize optional keys so the client always has them
        for k in ("done_when", "first_action", "resource", "risk", "gap"):
            n.setdefault(k, None)
        n.setdefault("support", [])
        nodes.append(n)
        return n
 
    add({"id": "start", "layer": "start", "family": "portfolio", "cap": True, "title": "You today",
         "description": "Where you're starting from: " + (("strengths in " + core_skill + ", ") if core_skill else "") + "aiming at " + goal + ".",
         "speed": 1, "certainty": 1, "ceiling": 0.5, "cost": 0, "effort": 0, "weeks": 0})
 
    # ---- Foundation ----
    if len(skill_gaps) > 0:
        g = skill_gaps[0]
        add({"id": "f_gap1", "layer": "found", "family": "credential", "title": "Close your " + g + " gap", "gap": g,
             "description": '"' + g + '" shows up across your matches but isn\'t in your stated skills - the highest-leverage thing to fix first.',
             "done_when": "You can walk someone through one real example using " + g + ", not just claim it.",
             "first_action": "Today: do one hands-on exercise with " + g + " - build, don't just watch.",
             "resource": "A free course or official docs for " + g + ", paired with one real practice problem.",
             "risk": "Passively watching tutorials without producing an artifact.",
             "support": _support(ranked, g), "speed": 0.55, "certainty": 0.75, "ceiling": 0.55, "cost": 0.2, "effort": 0.6})
    if len(skill_gaps) > 1:
        g = skill_gaps[1]
        add({"id": "f_gap2", "layer": "found", "family": "credential", "title": "Pick up " + g, "gap": g,
             "description": "The second-most-common skill in your matches that you haven't claimed yet.",
             "done_when": "One small but real thing built with " + g + ".",
             "first_action": "Block 3 focused sessions this week on " + g + ".",
             "resource": "A free-tier tutorial plus one dataset/problem in " + g + ".",
             "risk": "Trying to learn it in the abstract instead of on a concrete task.",
             "support": _support(ranked, g), "speed": 0.5, "certainty": 0.7, "ceiling": 0.5, "cost": 0.2, "effort": 0.6})
    add({"id": "f_selfteach", "layer": "found", "family": "portfolio", "title": "Self-teach " + (core_skill or "the core skill") + " to a working level",
         "description": 'Go from "familiar" to "can ship with it" on the single skill ' + goal + " leans on most.",
         "done_when": "You've built one non-trivial thing end to end with it.",
         "first_action": "Choose one real problem you actually care about and start on it today.",
         "resource": "A project-based course or a well-scoped open dataset.",
         "risk": "Tutorial hell - no output to show.", "goalTie": True,
         "speed": 0.55, "certainty": 0.65, "ceiling": 0.6, "cost": 0.05, "effort": 0.7})
    add({"id": "f_cred", "layer": "found", "family": "credential", "title": "Earn a recognised " + sgw + " credential",
         "description": "A named certificate or structured program that signals baseline competence for " + goal + ".",
         "done_when": "Credential completed and on your profile/resume.",
         "first_action": "Compare two reputable programs this week; enrol in one.",
         "resource": "An industry-recognised certificate or a university-backed course.",
         "risk": "Chasing a credential no employer recognises - verify it appears in real job posts first.",
         "speed": 0.35, "certainty": 0.82, "ceiling": 0.5, "cost": 0.65, "effort": 0.55})
    add({"id": "f_bootcamp", "layer": "found", "family": "credential", "title": "Do an intensive bootcamp / cohort",
         "description": "A fast, structured, high-accountability route to job-ready skills - if you can afford the time and cost.",
         "done_when": "You finish with a capstone you can defend.",
         "first_action": "Shortlist cohorts with real outcome reports (not just testimonials).",
         "resource": "A cohort program with published placement data.",
         "risk": "Overpaying for a program whose outcomes don't hold up - demand real numbers.",
         "speed": 0.6, "certainty": 0.7, "ceiling": 0.65, "cost": 0.9, "effort": 0.85})
 
    # ---- Proof ----
    add({"id": "p_project", "layer": "proof", "family": "portfolio", "title": "Ship one flagship project for " + sgw,
         "description": "Something you chose and built that directly demonstrates " + goal + " - defensible in an interview.",
         "done_when": "A live link/repo/writeup you'd comfortably send a stranger.",
         "first_action": "Write the project idea in one sentence and pick the dataset/tool today.",
         "resource": "A public dataset or a real problem in your target domain.",
         "risk": "Scoping too big to finish - shrink it until a rough version fits a weekend.",
         "support": _support(ranked, goal + " " + (core_skill or "")), "goalTie": True,
         "speed": 0.6, "certainty": 0.6, "ceiling": 0.7, "cost": 0.05, "effort": 0.75})
    add({"id": "p_casestudy", "layer": "proof", "family": "portfolio", "title": "Publish a public case study",
         "description": "Turn the work into a written, shareable narrative - the thing hiring managers actually read.",
         "done_when": "A published post explaining the problem, approach and result.",
         "first_action": "Draft the three-sentence version: problem, what you did, outcome.",
         "resource": "A free blog/portfolio host; a peer to review the draft.",
         "risk": "Describing effort instead of impact - lead with the result.",
         "speed": 0.7, "certainty": 0.6, "ceiling": 0.6, "cost": 0, "effort": 0.45})
    add({"id": "p_freelance", "layer": "proof", "family": "network", "title": "Freelance / volunteer a real deliverable",
         "description": "Do the actual work for a real org, even unpaid at first - real stakes beat toy projects.",
         "done_when": "A real user/org has used what you made.",
         "first_action": "Offer one concrete deliverable to a nonprofit or small business this week.",
         "resource": "Your existing network; a volunteer-matching site.",
         "risk": "Scope creep with no deadline - agree a tight brief up front.",
         "speed": 0.65, "certainty": 0.55, "ceiling": 0.75, "cost": 0.05, "effort": 0.7})
    add({"id": "p_compete", "layer": "proof", "family": "portfolio", "title": "Place in a competition / hackathon",
         "description": "A time-boxed, credible signal you can point to - and a deadline that forces shipping.",
         "done_when": "You submitted and ideally ranked or were recognised.",
         "first_action": "Find one relevant competition closing in 4-8 weeks and register.",
         "resource": "A reputable competition platform in your domain.",
         "risk": "Treating it as all-or-nothing - a strong submission counts even without winning.",
         "speed": 0.7, "certainty": 0.5, "ceiling": 0.8, "cost": 0.05, "effort": 0.75})
 
    # ---- Access ----
    add({"id": "a_warm", "layer": "access", "family": "network", "title": "20 warm-intro conversations",
         "description": "Systematic informational chats with people already doing " + goal + " - the single biggest source of real offers.",
         "done_when": "20 real conversations logged, each ending in one referral or intro.",
         "first_action": "List 20 names today; send the first 3 messages.",
         "resource": "Alumni networks, LinkedIn, your Workshop networking tracker.",
         "risk": "Asking for a job instead of advice - lead with genuine curiosity.",
         "speed": 0.8, "certainty": 0.5, "ceiling": 0.85, "cost": 0, "effort": 0.6})
    add({"id": "a_cold", "layer": "access", "family": "network", "title": "Targeted cold outreach",
         "description": "Specific, researched messages to " + role_word + " - volume with real personalisation.",
         "done_when": "40 tailored messages out; a reply rate you can iterate on.",
         "first_action": "Draft one strong template in the Workshop and send 10 today.",
         "resource": "Workshop outreach drafting; a simple tracker.",
         "risk": "Generic blasts - one specific line about them beats ten about you.",
         "speed": 0.78, "certainty": 0.45, "ceiling": 0.7, "cost": 0.05, "effort": 0.6})
    add({"id": "a_apply", "layer": "access", "family": "sidedoor",
         "title": ("Apply to your top matches (" + top["title"] + " …)") if top else "Apply to your top matches",
         "description": ('Your current #1 is "' + top["title"] + '" at ' + str(top.get("org")) + " (" + str(top.get("score_pct")) + "% fit). Prioritise 65%+ matches over volume.") if top else "Run a scan first, then focus on the highest-fit roles rather than applying broadly.",
         "done_when": "Applied to 5+ roles scoring 60%+ and heard back from 1.",
         "first_action": ('Open "' + top["title"] + '" on Job Search and decide within 24h.') if top else "Go to Job Search and start the watch.",
         "resource": "Your Job Search watch, sorted by match %.",
         "risk": "Spraying low-fit applications - fit compounds, volume doesn't.",
         "support": ([{"title": top.get("title"), "org": top.get("org"), "pct": top.get("score_pct")}] if top else []),
         "goalTie": True, "speed": 0.75, "certainty": 0.5, "ceiling": 0.6, "cost": 0, "effort": 0.5})
    if employed:
        add({"id": "a_internal", "layer": "access", "family": "internal", "title": "Move to an adjacent role, then transfer",
             "description": "Get into the building via a role you can already win, then move toward " + goal + " internally - proven performance is the strongest signal there is.",
             "done_when": "You're in an adjacent seat with a named path to the target team.",
             "first_action": "Identify the one internal team nearest " + goal + " and who owns headcount.",
             "resource": "Your manager, an internal mentor, the internal jobs board.",
             "risk": "Getting stuck in the stepping-stone role - agree the transfer timeline up front.",
             "speed": 0.85, "certainty": 0.7, "ceiling": 0.6, "cost": 0, "effort": 0.5})
    add({"id": "a_recruiter", "layer": "access", "family": "sidedoor", "title": "Work specialist recruiters / agencies",
         "description": "Let people whose job is placement do part of the search - especially for contract entry points.",
         "done_when": "2-3 specialist recruiters actively sending you real roles.",
         "first_action": "Find recruiters who place " + sgw + " roles and send your one-pager.",
         "resource": "Niche recruiting firms in your field.",
         "risk": "Relying on them entirely - they work volume; you still drive the search.",
         "speed": 0.8, "certainty": 0.5, "ceiling": 0.45, "cost": 0, "effort": 0.35})
 
    # ---- Break-in ----
    add({"id": "b_loop", "layer": "break", "family": "network", "title": "Run the full interview loop to an offer",
         "description": "Convert access into a real offer through prepared, structured interviewing.",
         "done_when": "A signed offer, or final rounds at 2+ places.",
         "first_action": "Do one mock interview in Interview Prep this week.",
         "resource": "Interview Prep: mock interviews, STAR stories, question bank.",
         "risk": "Winging behavioural rounds - your stories need to be ready.",
         "speed": 0.6, "certainty": 0.55, "ceiling": 0.7, "cost": 0, "effort": 0.7})
    add({"id": "b_contract", "layer": "break", "family": "sidedoor", "title": "Contract-to-hire foot in the door",
         "description": "Take a shorter contract to prove yourself, then convert - lower bar in, real track record out.",
         "done_when": "A contract signed with a realistic conversion path.",
         "first_action": "Tell recruiters you're open to contract-to-hire.",
         "resource": "Agencies; companies hiring contractors in your field.",
         "risk": "No conversion clarity - ask what \"converting\" has looked like there.",
         "speed": 0.8, "certainty": 0.55, "ceiling": 0.5, "cost": 0, "effort": 0.55})
    if re.search(r"student|grad", stage, re.I):
        add({"id": "b_newgrad", "layer": "break", "family": "credential", "title": "New-grad / returnship program",
             "description": "Structured entry programs built exactly for people at your stage - designed to convert.",
             "done_when": "Accepted into a program with a full-time conversion track.",
             "first_action": "List programs with open or upcoming cohorts and their deadlines.",
             "resource": "Company early-careers pages; program deadline trackers.",
             "risk": "Missing deadlines - these run months ahead; calendar them now.",
             "speed": 0.55, "certainty": 0.7, "ceiling": 0.65, "cost": 0, "effort": 0.6})
    add({"id": "b_referral", "layer": "break", "family": "network", "title": "Referral-driven fast track",
         "description": "Convert one of your warm conversations into an internal referral that skips the resume pile.",
         "done_when": "A real employee submits you as a referral.",
         "first_action": 'Ask your strongest contact directly: "would you be comfortable referring me?"',
         "resource": "The relationships you built in Access.",
         "risk": "Asking before you've given them anything to vouch for.",
         "speed": 0.72, "certainty": 0.6, "ceiling": 0.8, "cost": 0, "effort": 0.4})
 
    add({"id": "goal", "layer": "goal", "family": "network", "cap": True, "title": final,
         "description": "The destination: " + goal + ".", "speed": 1, "certainty": 1, "ceiling": 1, "cost": 0, "effort": 0, "weeks": 0})
 
    layers = [
        {"id": "start", "name": "You today", "sub": "starting point"},
        {"id": "found", "name": "Foundation", "sub": "get ready"},
        {"id": "proof", "name": "Proof", "sub": "build evidence"},
        {"id": "access", "name": "Access", "sub": "get in front"},
        {"id": "break", "name": "Break-in", "sub": "land it"},
        {"id": "goal", "name": "Goal", "sub": (goal[:24] + "…") if len(goal) > 26 else goal},
    ]
    by_layer = {l["id"]: [n for n in nodes if n["layer"] == l["id"]] for l in layers}
    edges = []
    for n in by_layer["found"]:
        edges.append({"from": "start", "to": n["id"]})
    _link(by_layer["found"], by_layer["proof"], edges)
    _link(by_layer["proof"], by_layer["access"], edges)
    _link(by_layer["access"], by_layer["break"], edges)
    for n in by_layer["break"]:
        edges.append({"from": n["id"], "to": "goal"})
 
    return {"layers": layers, "nodes": nodes, "edges": edges, "byLayer": by_layer,
            "goal": goal, "final": final, "skill_gaps_used": skill_gaps}
 
 
def _link(src, dst, edges):
    if not src or not dst:
        return
    for i, s in enumerate(src):
        picks = []
        same = next((j for j, d in enumerate(dst) if d["family"] == s["family"]), -1)
        if same >= 0:
            picks.append(same)
        k = 0
        while k < len(dst) and len(picks) < 3:
            idx = (i + k) % len(dst)
            if idx not in picks:
                picks.append(idx)
            k += 1
        for idx in picks:
            edges.append({"from": s["id"], "to": dst[idx]["id"]})
    for d in dst:
        if not any(e["to"] == d["id"] for e in edges):
            edges.append({"from": src[0]["id"], "to": d["id"]})
 
 
# ---------------------------------------------------------------- paths + scoring
def enumerate_paths(atlas, cap=400):
    adj = {}
    for e in atlas["edges"]:
        adj.setdefault(e["from"], []).append(e["to"])
    paths = []
 
    def walk(nid, acc):
        if len(paths) >= cap:
            return
        acc = acc + [nid]
        if nid == "goal":
            paths.append(acc)
            return
        for nx in adj.get(nid, []):
            walk(nx, acc)
 
    walk("start", [])
    return paths
 
 
def _priority_weights(c):
    base = {"fit": 0.28, "speed": 0.22, "certainty": 0.22, "ceiling": 0.18, "cost": 0.10}
    p = c.get("priority", "balanced")
    if p == "speed":
        base = {"fit": 0.22, "speed": 0.42, "certainty": 0.14, "ceiling": 0.12, "cost": 0.10}
    elif p == "certainty":
        base = {"fit": 0.22, "speed": 0.14, "certainty": 0.42, "ceiling": 0.12, "cost": 0.10}
    elif p == "ceiling":
        base = {"fit": 0.24, "speed": 0.14, "certainty": 0.12, "ceiling": 0.40, "cost": 0.10}
    r = c.get("risk", 40) / 100.0
    base["certainty"] *= (1.3 - 0.6 * r)
    base["ceiling"] *= (0.7 + 0.6 * r)
    return base
 
 
def _mids(atlas, path):
    node = {n["id"]: n for n in atlas["nodes"]}
    return [node[i] for i in path if i not in ("start", "goal")]
 
 
def path_stats(atlas, path):
    mids = _mids(atlas, path)
    weeks = sum(n.get("weeks", 0) for n in mids)
    avg_fit = (sum(n["fit"] for n in mids) / len(mids)) if mids else 0
    min_cert = min((n["certainty"] for n in mids), default=0)
    max_ceil = max((n["ceiling"] for n in mids), default=0)
    cost = sum(n.get("cost", 0) for n in mids)
    effort = (sum(n.get("effort", 0) for n in mids) / len(mids)) if mids else 0
    return {"weeks": weeks, "avgFit": avg_fit, "minCert": min_cert, "maxCeil": max_ceil, "cost": cost, "effort": effort}
 
 
def score_path(atlas, path, c):
    s = path_stats(atlas, path)
    w = _priority_weights(c)
    speed_score = 1 - min(1.0, s["weeks"] / MAXW)
    cost_score = 1 - min(1.0, s["cost"] / MAXCOST)
    score = (w["fit"] * s["avgFit"] + w["speed"] * speed_score + w["certainty"] * s["minCert"]
             + w["ceiling"] * s["maxCeil"] + w["cost"] * cost_score)
    budget_cap = 0.25 if c.get("budget") == "free" else (1.0 if c.get("budget") == "low" else 9)
    if s["cost"] > budget_cap:
        score -= 0.12 * (s["cost"] - budget_cap)
    bud_w = c.get("timeWeeks", 52)
    if s["weeks"] > bud_w:
        score -= 0.15 * min(1.0, (s["weeks"] - bud_w) / bud_w)
    fams = c.get("families") or {}
    if not all(fams.get(n["family"], True) for n in _mids(atlas, path)):
        return -1
    return score
 
 
def recommend(atlas, constraints=None):
    c = dict(DEFAULT_CONSTRAINTS)
    if constraints:
        c.update(constraints)
    all_paths = enumerate_paths(atlas)
    viable = [p for p in all_paths if score_path(atlas, p, c) > -1]
    if not viable:
        return {"viable_path_count": 0, "best": None, "constraints_used": c}
    scored = sorted(([p, score_path(atlas, p, c), path_stats(atlas, p)] for p in viable), key=lambda x: -x[1])
    fastest = min(viable, key=lambda p: path_stats(atlas, p)["weeks"])
    safest = max(viable, key=lambda p: path_stats(atlas, p)["minCert"])
    ceiling = max(viable, key=lambda p: path_stats(atlas, p)["maxCeil"])
    return {
        "viable_path_count": len(viable),
        "best": scored[0][0], "best_stats": scored[0][2],
        "fastest": fastest, "safest": safest, "ceiling": ceiling,
        "top": [{"ids": p, "stats": st} for (p, sc, st) in scored[:6]],
        "constraints_used": c,
    }
 
 
# ---------------------------------------------------------------- public
def generate_pathways(profile, ranked, skill_gaps, constraints=None):
    """Full atlas + authoritative recommendation. Everything the client
    needs to render the diagram and the 'what we believe' summary."""
    atlas = build_atlas(profile, ranked, skill_gaps)
    rec = recommend(atlas, constraints)
    return {
        "generated_by": "engine",
        "goal": atlas["goal"], "final": atlas["final"],
        "layers": atlas["layers"],
        "nodes": atlas["nodes"],
        "edges": atlas["edges"],
        "families": FAMILIES,
        "skill_gaps_used": atlas["skill_gaps_used"],
        "recommendation": rec,
    }
 
