from fastapi import APIRouter, Depends, HTTPException, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import desc
 
from app.db import get_db
from app.models.db_models import Notification
 
router = APIRouter(prefix="/notifications", tags=["notifications"])
 
 
class NotificationIn(BaseModel):
    user_id: str
    type: str = Field(max_length=50)  # short internal constant ("scan", "auto_apply", ...); bounded defensively
    title: str = Field(max_length=500)
    detail: str | None = Field(default=None, max_length=2000)
 
 
@router.post("")
def create_notification(payload: NotificationIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Records a real notification - this is what backs the frontend's
    Inbox page, which was previously only in browser localStorage.
    The scan scheduler (scheduler.py) already writes Notification
    rows directly into the same database session when a cycle finds
    new matches or auto-drafts something - via direct model
    instantiation, not by calling this HTTP endpoint, since that's
    the correct, efficient choice for internal server-side code. This
    endpoint exists for anything that genuinely needs to create a
    notification over HTTP instead.
 
    Checks the person's real, stated notification preferences before
    creating anything - the concrete answer to a documented complaint
    about receiving outreach a person never opted into. A type not
    yet listed in an older, stored preferences object still defaults
    to enabled, so this is opt-out, never opt-in-by-default.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    verify_token_belongs_to_user(payload.user_id, authorization)
 
    from app.models.db_models import Profile
    profile = db.query(Profile).filter(Profile.user_id == payload.user_id, Profile.is_current == True).first()  # noqa: E712
    prefs = (profile.notification_preferences if profile else None) or {}
    if prefs.get(payload.type, True) is False:
        return {"status": "skipped - muted by user preference"}
 
    note = Notification(user_id=payload.user_id, type=payload.type, title=payload.title, detail=payload.detail)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"status": "created", "notification_id": str(note.id)}
 
 
@router.get("/{user_id}")
def get_notifications(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(desc(Notification.created_at))
        .limit(50)
        .all()
    )
    return [
        {"id": str(n.id), "type": n.type, "title": n.title, "detail": n.detail, "is_read": n.is_read, "created_at": n.created_at.isoformat()}
        for n in rows
    ]
 
 
@router.post("/{notification_id}/read")
def mark_read(notification_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Notification not found")
    note = db.query(Notification).filter(Notification.id == notification_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Notification not found")
    # This route only has a notification_id, so verify the token
    # against the notification's real owner before mutating it.
    verify_token_belongs_to_user(str(note.user_id), authorization)
    note.is_read = True
    db.commit()
    return {"status": "marked read"}
 
 
@router.post("/{user_id}/mark-all-read")
def mark_all_read(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Bulk counterpart to mark_read above - mirrors the frontend's
    own markAllNotificationsRead() exactly. Genuine gap this closes:
    the frontend already offered this action, but the backend only
    ever supported marking one notification read at a time.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .update({"is_read": True})
    )
    db.commit()
    return {"status": "marked all read", "updated_count": updated}
 
 
@router.delete("/{user_id}")
def clear_notifications(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Mirrors the frontend's own clearNotifications() exactly - the
    same genuine gap as mark_all_read above, a real frontend action
    with no backend counterpart until now.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    deleted = db.query(Notification).filter(Notification.user_id == user_id).delete()
    db.commit()
    return {"status": "cleared", "deleted_count": deleted}
 
 
class NotificationPreferencesIn(BaseModel):
    preferences: dict[str, bool]
 
    @field_validator("preferences")
    @classmethod
    def _bound_preferences(cls, v: dict) -> dict:
        # dict[str, bool] bounds the VALUES but not the number of keys or their
        # length. These are merged into the profile's notification_preferences JSONB
        # (read on every scan), and only a handful of keys are ever read, so without
        # a bound a caller could bloat their own row with arbitrarily many/large junk
        # keys - an unbounded-storage vector. Cap both; real preference keys are few
        # and short.
        if len(v) > 20:
            raise ValueError("too many preference keys")
        for k in v:
            if len(str(k)) > 100:
                raise ValueError("preference key is too long")
        return v
 
 
@router.patch("/{user_id}/preferences")
def update_notification_preferences(user_id: str, body: NotificationPreferencesIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Lets a person mute specific notification types - the concrete
    fix for a documented complaint about receiving outreach a person
    never opted into. Merges into whatever's already stored rather
    than replacing it wholesale, so muting one type doesn't silently
    reset every other, real preference the person already set.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    from app.models.db_models import Profile
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    current = dict(profile.notification_preferences or {})
    current.update(body.preferences)
    profile.notification_preferences = current
    db.commit()
    db.refresh(profile)
    return {"preferences": profile.notification_preferences}
 
