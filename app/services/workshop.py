"""Career Studio (Workshop) generic item store.
 
Backs the frontend Workshop's new tools - STAR interview stories,
references, networking contacts, portfolio links, achievements (brag
sheet), target roles, and the elevator-pitch drafts (a singleton). One
table (workshop_items) and one set of CRUD endpoints serve all of them,
keyed by `kind`. The browser generates each item's `client_id`, so the
client and server agree on identity without any id mapping, and a
retried best-effort call upserts rather than duplicating.
"""
import json
import uuid as uuid_module
 
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import WorkshopItem
from app.services.auth import require_auth_for_user
 
router = APIRouter(prefix="/workshop", tags=["workshop"])
 
# The only kinds the Workshop stores. Bounded so a caller can't spray
# arbitrary collections into the table.
ALLOWED_KINDS = {
    "star_story", "reference", "contact", "portfolio",
    "achievement", "target_role", "pitch",
}
 
 
def _require_uuid(user_id: str):
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
 
def _bound_data(data: dict) -> dict:
    # Keep each JSONB row small and sane: these are short study-aid records,
    # never a place to park arbitrary bulk. Cap field count and total size.
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="data must be an object")
    if len(data) > 40:
        raise HTTPException(status_code=400, detail="too many fields")
    try:
        if len(json.dumps(data)) > 20000:
            raise HTTPException(status_code=400, detail="item is too large")
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="data is not JSON-serializable")
    return data
 
 
class ItemIn(BaseModel):
    kind: str = Field(max_length=40)
    client_id: str = Field(max_length=64)
    data: dict = Field(default_factory=dict)
 
 
class SingletonIn(BaseModel):
    client_id: str = Field(default="singleton", max_length=64)
    data: dict = Field(default_factory=dict)
 
 
@router.get("/{user_id}/items")
def list_items(user_id: str, kind: str | None = None, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """All of a user's Workshop items, newest first, optionally one kind.
    Returns each item's browser-side id, so the frontend can rebuild its
    local stores verbatim on hydrate."""
    _require_uuid(user_id)
    q = db.query(WorkshopItem).filter(WorkshopItem.user_id == user_id)
    if kind is not None:
        if kind not in ALLOWED_KINDS:
            raise HTTPException(status_code=400, detail="unknown kind")
        q = q.filter(WorkshopItem.kind == kind)
    rows = q.order_by(desc(WorkshopItem.created_at)).limit(500).all()
    return [
        {"id": r.client_id, "kind": r.kind, "data": r.data or {}, "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]
 
 
@router.post("/{user_id}/items")
def create_item(user_id: str, payload: ItemIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Create (or upsert) one item. Upserting on (user, kind, client_id)
    means a retried best-effort call from the browser never duplicates a
    row - the same client id just refreshes the stored data."""
    _require_uuid(user_id)
    if payload.kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="unknown kind")
    _bound_data(payload.data)
    existing = (
        db.query(WorkshopItem)
        .filter(WorkshopItem.user_id == user_id, WorkshopItem.kind == payload.kind, WorkshopItem.client_id == payload.client_id)
        .first()
    )
    if existing:
        existing.data = payload.data
        db.commit()
        return {"status": "updated", "id": existing.client_id}
    item = WorkshopItem(user_id=user_id, kind=payload.kind, client_id=payload.client_id, data=payload.data)
    db.add(item)
    db.commit()
    return {"status": "created", "id": payload.client_id}
 
 
@router.delete("/{user_id}/items/{client_id}")
def delete_item(user_id: str, client_id: str, kind: str | None = None, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Delete one item the person removed in the Workshop. Scoped to the
    caller's own rows (user_id is auth-checked), and optionally narrowed to
    a kind. A no-match delete is a no-op, not an error, so a best-effort
    call for an item that only ever lived locally stays quiet."""
    _require_uuid(user_id)
    q = db.query(WorkshopItem).filter(WorkshopItem.user_id == user_id, WorkshopItem.client_id == client_id)
    if kind is not None:
        q = q.filter(WorkshopItem.kind == kind)
    deleted = q.delete()
    db.commit()
    return {"status": "deleted", "deleted_count": deleted}
 
 
@router.put("/{user_id}/singleton/{kind}")
def set_singleton(user_id: str, kind: str, payload: SingletonIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Replace the single item of a kind - used for the elevator-pitch
    drafts, which are one editable record rather than a list."""
    _require_uuid(user_id)
    if kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="unknown kind")
    _bound_data(payload.data)
    db.query(WorkshopItem).filter(WorkshopItem.user_id == user_id, WorkshopItem.kind == kind).delete()
    item = WorkshopItem(user_id=user_id, kind=kind, client_id=(payload.client_id or "singleton"), data=payload.data)
    db.add(item)
    db.commit()
    return {"status": "saved", "id": payload.client_id or "singleton"}
 
