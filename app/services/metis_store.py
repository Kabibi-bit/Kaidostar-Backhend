"""Metis workspace store.
 
Backs the full Metis workspace (metis.html): saved conversation threads,
projects, schedule/task items, and the user's Metis customisation (settings).
One table (metis_items) and one set of CRUD endpoints serve all of them, keyed
by `kind` - the same generic, local-first pattern as the Career Studio's
workshop_items store.
 
The browser generates each item's `client_id`, so client and server agree on
identity without any id mapping, and a retried best-effort call upserts rather
than duplicating. Writes are best-effort from the client (it works fully
offline against localStorage and mirrors here when signed in), and the client
rehydrates from here on load so a user's Metis follows them across devices.
"""
import json
import uuid as uuid_module
 
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import MetisItem
from app.services.auth import require_auth_for_user
 
router = APIRouter(prefix="/metis", tags=["metis"])
 
# The only kinds the Metis workspace stores. Bounded so a caller can't spray
# arbitrary collections into the table.
ALLOWED_KINDS = {"conversation", "project", "schedule", "settings"}
 
# Per-kind byte budget for the JSONB row. A conversation holds a whole thread,
# so it gets a much larger allowance than the small structured records; every
# kind is still bounded so one row can't become an unbounded dumping ground.
MAX_DATA_BYTES = {
    "conversation": 300_000,
    "project": 20_000,
    "schedule": 8_000,
    "settings": 12_000,
}
_DEFAULT_MAX_BYTES = 20_000
 
 
def _require_uuid(user_id: str):
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
 
def _bound_data(kind: str, data: dict) -> dict:
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="data must be an object")
    if len(data) > 60:
        raise HTTPException(status_code=400, detail="too many fields")
    try:
        size = len(json.dumps(data))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="data is not JSON-serializable")
    if size > MAX_DATA_BYTES.get(kind, _DEFAULT_MAX_BYTES):
        raise HTTPException(status_code=400, detail="item is too large")
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
    """A user's Metis items, newest first, optionally one kind. Returns each
    item's browser-side id so the frontend rebuilds its local stores verbatim."""
    _require_uuid(user_id)
    q = db.query(MetisItem).filter(MetisItem.user_id == user_id)
    if kind is not None:
        if kind not in ALLOWED_KINDS:
            raise HTTPException(status_code=400, detail="unknown kind")
        q = q.filter(MetisItem.kind == kind)
    rows = q.order_by(desc(MetisItem.updated_at)).limit(1000).all()
    return [
        {
            "id": r.client_id,
            "kind": r.kind,
            "data": r.data or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]
 
 
@router.post("/{user_id}/items")
def create_item(user_id: str, payload: ItemIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Create or upsert one item. Upserting on (user, kind, client_id) means a
    retried best-effort call from the browser never duplicates a row - the same
    client id just refreshes the stored data."""
    _require_uuid(user_id)
    if payload.kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="unknown kind")
    _bound_data(payload.kind, payload.data)
    existing = (
        db.query(MetisItem)
        .filter(MetisItem.user_id == user_id, MetisItem.kind == payload.kind, MetisItem.client_id == payload.client_id)
        .first()
    )
    if existing:
        existing.data = payload.data
        db.commit()
        return {"status": "updated", "id": existing.client_id}
    item = MetisItem(user_id=user_id, kind=payload.kind, client_id=payload.client_id, data=payload.data)
    db.add(item)
    db.commit()
    return {"status": "created", "id": payload.client_id}
 
 
@router.delete("/{user_id}/items/{client_id}")
def delete_item(user_id: str, client_id: str, kind: str | None = None, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Delete one item the person removed in the workspace. Scoped to the
    caller's own rows (user_id is auth-checked), optionally narrowed to a kind.
    A no-match delete is a no-op, not an error, so a best-effort call for an
    item that only ever lived locally stays quiet."""
    _require_uuid(user_id)
    q = db.query(MetisItem).filter(MetisItem.user_id == user_id, MetisItem.client_id == client_id)
    if kind is not None:
        if kind not in ALLOWED_KINDS:
            raise HTTPException(status_code=400, detail="unknown kind")
        q = q.filter(MetisItem.kind == kind)
    deleted = q.delete()
    db.commit()
    return {"status": "deleted", "deleted_count": deleted}
 
 
@router.put("/{user_id}/singleton/{kind}")
def set_singleton(user_id: str, kind: str, payload: SingletonIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Replace the single item of a kind - used for the Metis `settings`
    customisation, which is one editable record rather than a list."""
    _require_uuid(user_id)
    if kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="unknown kind")
    _bound_data(kind, payload.data)
    client_id = payload.client_id or "singleton"
    existing = (
        db.query(MetisItem)
        .filter(MetisItem.user_id == user_id, MetisItem.kind == kind, MetisItem.client_id == client_id)
        .first()
    )
    if existing:
        existing.data = payload.data
        db.commit()
        return {"status": "updated", "id": client_id}
    item = MetisItem(user_id=user_id, kind=kind, client_id=client_id, data=payload.data)
    db.add(item)
    db.commit()
    return {"status": "created", "id": client_id}
 
