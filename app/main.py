import os
import uuid as _uuid
import traceback
from fastapi import FastAPI, Request, HTTPException as _HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
 
from app.services.scheduler import start_scheduler
 
load_dotenv()
 
app = FastAPI(title="Kaidostar API")
 
# CORS origins are configurable per environment via
# KAIDOSTAR_ALLOWED_ORIGINS (comma-separated). This replaces a wildcard
# "*", which would let any website on the internet make authenticated
# requests to this API on a logged-in user's behalf. Defaults cover
# local dev and the known frontend host; set the env var in
# production to your real domain(s).
_default_origins = "http://localhost:8000,http://localhost:5173,http://127.0.0.1:8000"
_allowed_origins = [
    o.strip()
    for o in os.getenv("KAIDOSTAR_ALLOWED_ORIGINS", _default_origins).split(",")
    if o.strip()
]
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    # Bearer tokens travel in the Authorization header, not cookies,
    # so credentialed CORS is not needed - and keeping it False is
    # what makes a strict origin allowlist meaningful.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
# Resilient router loading: import and include each router INDIVIDUALLY so that
# if any single module fails to import in a given environment, the app STILL
# starts and binds its port (instead of the whole process crashing), and the log
# shows exactly which module failed and why. A crash in one router must never
# take the entire API down at startup.
import importlib
import logging as _logging
import traceback as _tb
_startup_log = _logging.getLogger("kaidostar.startup")
 
_ROUTE_MODULES = [
    "auth", "users", "profile", "schools", "listings", "chat", "roadmap",
    "outcomes", "applications", "manual_listings", "saved_listings",
    "notifications", "career_discovery", "outreach", "social", "athletics",
    "market_research", "resume", "assistance", "strategy", "engagement",
    "dismissed_listings", "workshop", "ai_assist", "metis_store",
]
# Records the load result of every router so it can be inspected at
# /system/router-status in the browser - no need to dig through logs to see
# whether any router got skipped and why.
_ROUTER_STATUS = {"loaded": [], "failed": {}}
for _name in _ROUTE_MODULES:
    try:
        _mod = importlib.import_module(f"app.routes.{_name}")
        app.include_router(_mod.router)
        _ROUTER_STATUS["loaded"].append(_name)
    except Exception as _e:
        # Keep starting the app, but record + log exactly which router failed.
        _ROUTER_STATUS["failed"][_name] = f"{type(_e).__name__}: {_e}"
        _startup_log.error("ROUTER FAILED TO LOAD: app.routes.%s -> %s: %s",
                           _name, type(_e).__name__, _e)
        _tb.print_exc()
 
 
@app.get("/system/router-status")
def router_status():
    """Open this in a browser to see which routers loaded and which (if any)
    failed, with the real error. all_ok is True when nothing was skipped."""
    return {
        "all_ok": len(_ROUTER_STATUS["failed"]) == 0,
        "loaded_count": len(_ROUTER_STATUS["loaded"]),
        "failed_count": len(_ROUTER_STATUS["failed"]),
        "loaded": _ROUTER_STATUS["loaded"],
        "failed": _ROUTER_STATUS["failed"],
    }
 
# system.py is a small, purely diagnostic router (the
# /system/embeddings-status health check) - genuinely optional,
# unlike every router above. This import is deliberately isolated
# and guarded: without this try/except, a missing or broken
# system.py (a new file, easy to miss when applying a batch of
# changes - exactly what happened once already, taking the entire
# backend down for a single diagnostic endpoint) would crash this
# whole shared import statement, since it previously sat in the same
# line as every essential router. A purely diagnostic endpoint
# should never be able to take the rest of the app down with it.
try:
    from app.routes import system
    app.include_router(system.router)
except Exception as e:
    print(f"system router (embeddings-status diagnostic endpoint) failed to load, continuing without it: {e}")
 
 
# Catches only genuinely unexpected server errors. The full traceback
# is logged server-side (visible in Render's logs) for debugging, but
# the client receives only a generic message plus a correlation id -
# never the exception type, message, or stack trace, which could leak
# internal details (file paths, query structure, library versions) to
# an attacker. HTTPException is deliberately re-raised so intentional
# status codes from the app (e.g. 401/403 from the auth layer, 404s)
# reach the client unchanged instead of being masked as a 500.
@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    if isinstance(exc, _HTTPException):
        raise exc
    error_id = str(_uuid.uuid4())
    print(f"[unhandled error {error_id}] {type(exc).__name__}: {exc}")
    print(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred. Please try again.",
            "error_id": error_id,
        },
    )
 
 
@app.on_event("startup")
def on_startup():
    # The background scheduler must NEVER prevent the web server from starting.
    # If start_scheduler() throws (DB not reachable yet, APScheduler/env issue,
    # etc.), an unwrapped failure here aborts startup so the app never binds a
    # port -> Render reports "no open ports / timeout". Log and continue: the API
    # comes up regardless; the daily scan simply won't run until the cause is fixed.
    import logging
    try:
        start_scheduler()
    except Exception as e:
        logging.getLogger("kaidostar").warning("Scheduler failed to start (non-fatal, API still serving): %s", e)
 
 
@app.get("/health")
def health():
    return {"status": "ok"}
 
