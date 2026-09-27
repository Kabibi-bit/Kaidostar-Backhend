"""Real semantic matching, on top of (not instead of) the existing
keyword/synonym scoring. Keyword and synonym matching has a real
ceiling: "reduced customer churn through better onboarding" and "led
retention strategy" describe the same real skill with almost no words
in common. No amount of synonym-group tuning closes that gap - it
needs an actual embedding model that understands meaning, not just
shared vocabulary.
 
Uses Voyage AI's voyage-4-lite model, explicitly pinned to 512
output dimensions (matching this project's existing pgvector schema,
which hardcodes vector(512) - see db/schema_additions_embeddings.sql).
Verified directly against Voyage's own current pricing documentation
before choosing this: the older voyage-3.x generation this project
originally used no longer receives any free token allocation at all,
which directly conflicts with this project's established "stay
within a real free tier" design throughout - voyage-4-lite is both
the current generation's cheapest model and part of the 200M-free-
token allocation Voyage currently offers on signup. Pricing and free-
tier terms can and do change; docs.voyageai.com/docs/pricing is the
source of truth, not this comment.
 
Honest scope note: this is additive. Every function here degrades
gracefully to "no semantic signal" (returns None) when VOYAGE_API_KEY
isn't configured or a listing hasn't been embedded yet - matching now
works exactly as it did before this file existed, just without this
one extra factor, rather than breaking. See check_embeddings_status()
below for a real, actionable answer to "is this actually working
right now" - the previous version of this file had no such function,
so whether the key was set, and whether calls to Voyage were actually
succeeding, was invisible without reading raw server logs.
"""
import os
import math
 
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")
EMBEDDING_MODEL = "voyage-4-lite"
EMBEDDING_DIMENSIONS = 512
 
 
def is_configured() -> bool:
    return bool(VOYAGE_API_KEY)
 
 
def check_embeddings_status() -> dict:
    """A real, actionable answer to "is this actually working right
    now" - not just whether the key is present, but whether a real
    call to Voyage actually succeeds with it. Safe to call from a
    route without side effects: uses a single short, throwaway string
    and doesn't touch the database. Distinguishes "not configured"
    from "configured but the call is failing" (bad key, network
    issue, model name changed upstream, etc.) since those need
    different fixes and were previously indistinguishable from the
    outside - both looked identical (silent zero contribution) from
    the matching engine's point of view.
    """
    if not VOYAGE_API_KEY:
        return {"configured": False, "working": False, "detail": "VOYAGE_API_KEY is not set in this environment."}
    try:
        import voyageai
        client = voyageai.Client(api_key=VOYAGE_API_KEY)
        result = client.embed(["status check"], model=EMBEDDING_MODEL, input_type="document", output_dimension=EMBEDDING_DIMENSIONS)
        vec = result.embeddings[0]
        if len(vec) != EMBEDDING_DIMENSIONS:
            return {"configured": True, "working": False, "detail": f"Key is valid and the call succeeded, but returned {len(vec)} dimensions, not the expected {EMBEDDING_DIMENSIONS} - the pgvector column (vector(512)) would reject this. Check EMBEDDING_DIMENSIONS and the schema match."}
        return {"configured": True, "working": True, "detail": f"VOYAGE_API_KEY is set and a real test call to {EMBEDDING_MODEL} succeeded."}
    except Exception as e:
        return {"configured": True, "working": False, "detail": f"VOYAGE_API_KEY is set, but a real test call failed: {e}"}
 
 
def generate_embedding(text: str, input_type: str = "document") -> list[float] | None:
    """Returns a 512-dim embedding vector, or None if not configured
    or the call fails - callers must handle None gracefully, never
    assume this succeeds. input_type is "document" for listings,
    "query" for a candidate's stated goal - Voyage's API uses this to
    optimize the embedding for which side of the comparison it's on,
    which measurably improves retrieval quality over embedding both
    sides identically. output_dimension is passed explicitly rather
    than relying on the model's default, since voyage-4-lite defaults
    to 1024 dimensions, not 512 - without this, embeddings would
    silently come back the wrong size for the existing vector(512)
    database column.
    """
    if not VOYAGE_API_KEY or not text or not text.strip():
        return None
    try:
        import voyageai
        client = voyageai.Client(api_key=VOYAGE_API_KEY)
        result = client.embed([text[:8000]], model=EMBEDDING_MODEL, input_type=input_type, output_dimension=EMBEDDING_DIMENSIONS)
        return result.embeddings[0]
    except Exception as e:
        print(f"Embedding generation failed (falling back to keyword-only matching): {e}")
        return None
 
 
def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Standard cosine similarity, -1 to 1. Pure math, no external
    dependency - this is the part of the pipeline that's fully
    testable without any live API or database.
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
 
 
def semantic_similarity_factor(listing_embedding: list[float] | None, profile_embedding: list[float] | None, tag_count: int = 4) -> float:
    """Converts a cosine similarity into a scoring contribution.
 
    The cap scales with tag_count (at goal_fit's own per-tag rate,
    verified by direct calculation - not just a number that sounded
    proportional: an earlier, more conservative multiplier looked
    reasonable but a maxed-out semantic score still landed at the
    scoring floor when actually computed through the full formula)
    rather than staying flat at 4.0. Found by directly testing a
    real, verified-zero-overlap scenario: a listing whose tags share
    literally no tokens with the stated goal, but whose embedding is
    a near-perfect semantic match (cosine similarity high enough to
    rescale to a maxed-out contribution) still landed at the scoring
    floor under the old flat cap, because goal_fit's denominator term
    (len(tags)*3) scales with tag count while semantic_fit's ceiling
    never did - the richer the listing's tag set, the more thoroughly
    a maxed-out semantic signal got drowned out, precisely in the
    scenario the curated synonym system's coverage gaps make this
    factor exist for in the first place. Floors at 4.0 so thin-tag
    listings aren't made worse off than before.
 
    Returns 0.0 (no contribution, not an error) whenever either
    embedding is missing - the honest degrade-gracefully path.
 
    Real embeddings rarely score below ~0.3 cosine similarity even
    for loosely related text, so this rescales the practically
    useful 0.3-0.9 range into the scoring contribution rather than
    wasting most of the range on similarities that never occur.
    """
    if listing_embedding is None or profile_embedding is None:
        return 0.0
    similarity = cosine_similarity(listing_embedding, profile_embedding)
    rescaled = max(0.0, min(1.0, (similarity - 0.3) / 0.6))  # 0.3->0.0, 0.9->1.0, capped both ends
    cap = max(4.0, tag_count * 4.0)
    return round(rescaled * cap, 2)
 
