"""
Safe Anthropic client access.
 
WHY THIS EXISTS: several route modules used to build
`anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))` at MODULE-LOAD
time. The Anthropic SDK RAISES at construction if the key is missing - so if
ANTHROPIC_API_KEY isn't set in the environment, importing those modules crashed
the whole app during startup, before it could bind a port (Render then reports
"no open ports detected" and times out).
 
A missing optional key must never prevent the server from starting. This module
builds the client LAZILY and defensively: the app always boots; only the actual
AI call fails (gracefully, per-request) when the key is absent - which the route
handlers already catch and turn into a clean 502.
"""
import os
 
_client = None
_tried = False
 
 
def get_client():
    """Return a shared Anthropic client, or None if it can't be built (e.g. no
    API key). Never raises - callers should handle a None client by returning a
    graceful error rather than crashing."""
    global _client, _tried
    if _client is not None:
        return _client
    if _tried:
        return None
    _tried = True
    try:
        import anthropic
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            return None
        _client = anthropic.Anthropic(api_key=key)
        return _client
    except Exception:
        return None
 
