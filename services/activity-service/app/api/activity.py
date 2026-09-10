import uuid
import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/activity", tags=["activity"])


class ActivityEvent(BaseModel):
    user_id: str
    item_id: int | None = None
    activity_type: str
    session_id: str | None = None


@router.post("/track")
def track_activity(event: ActivityEvent, request: Request, db: Session = Depends(get_db)):
    session_id = event.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    db.execute(text("""
        INSERT INTO user_activity
            (user_id, item_id, activity_type, action, session_id, ip_address, created_at)
        VALUES (:uid, :iid, :type, :action, :session, :ip, NOW())
    """), {
        "uid": event.user_id,
        "iid": event.item_id,
        "type": event.activity_type,
        "action": event.activity_type.replace("_", " ").title(),
        "session": session_id,
        "ip": request.client.host,
    })
    db.commit()
    log.info("activity_tracked", user=event.user_id, type=event.activity_type)
    return {"tracked": True}


@router.get("/summary/{user_id}")
def activity_summary(user_id: str, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT activity_type, COUNT(*) as count
        FROM user_activity WHERE user_id = :uid
        GROUP BY activity_type ORDER BY count DESC
    """), {"uid": user_id}).fetchall()
    return {"user_id": user_id, "activity": [{"type": r[0], "count": r[1]} for r in rows]}


@router.get("/popular-items")
def popular_items(limit: int = 10, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT item_id, COUNT(*) as interactions
        FROM user_activity WHERE item_id IS NOT NULL
        GROUP BY item_id ORDER BY interactions DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    return [{"item_id": r[0], "interactions": r[1]} for r in rows]
