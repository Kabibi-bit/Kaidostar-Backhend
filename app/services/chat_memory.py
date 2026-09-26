"""Persistent chatbot memory.
 
Note on a design change from the original spec: the schema has a
pgvector `embedding` column for true semantic search, but that needs
a second API account (OpenAI or Voyage) just for embeddings. To get
you running today with only the accounts you already have, this
version retrieves memory by recency instead of similarity - it pulls
your last N remembered facts rather than the N most *relevant* ones.
 
That's a real trade-off: recency-based retrieval will occasionally
surface less-relevant memories than true semantic search would. It's
a reasonable MVP simplification, not a permanent design decision -
swap in real embeddings later by populating the `embedding` column
and switching the query below to `.order_by(ChatMemory.embedding.cosine_distance(...))`.
"""
from sqlalchemy.orm import Session
from sqlalchemy import desc
 
from app.models.db_models import ChatMemory
 
 
def summarize_conversation(anthropic_client, conversation: list[dict]) -> str:
    """Compresses a conversation into 1-3 durable facts worth remembering
    long-term - not a transcript, just what's actually worth keeping.
    """
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in conversation)
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                "Summarize any durable facts about this user's career goals, "
                "preferences, or circumstances worth remembering for future "
                "conversations. 1-3 short bullet points, no fluff. If nothing "
                "durable came up, respond with exactly: NONE.\n\n" + transcript
            ),
        }],
    )
    return "".join((b.text or "") for b in resp.content if b.type == "text").strip()
 
 
def store_memory(db: Session, user_id: str, summary: str):
    # Skip non-durable results: the AI is instructed to return exactly
    # "NONE" when nothing is worth keeping, but also guard against a
    # blank/whitespace-only or differently-cased "none" slipping through
    # and creating a useless memory row.
    if not summary or not summary.strip() or summary.strip().upper() == "NONE":
        return
    db.add(ChatMemory(user_id=user_id, summary=summary))
    db.commit()
 
 
def retrieve_relevant_memory(db: Session, user_id: str, top_k: int = 5) -> list[str]:
    """Returns the user's most recent remembered facts.
    See module docstring for the recency-vs-similarity trade-off.
    """
    rows = (
        db.query(ChatMemory)
        .filter(ChatMemory.user_id == user_id)
        .order_by(desc(ChatMemory.created_at))
        .limit(top_k)
        .all()
    )
    return [r.summary for r in rows]
 
