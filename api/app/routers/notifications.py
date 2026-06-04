"""In-app notification inbox (per user). No email — documented seam."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import Notification, User
from ..serialize import notification_out

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def inbox(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = (select(Notification).where(Notification.user_id == user.id)
         .order_by(Notification.read, Notification.created_at.desc()))
    return [notification_out(n) for n in db.scalars(q).all()]


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.get(Notification, notification_id)
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    if n.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your notification")
    n.read = True
    db.commit()
    return notification_out(n)
