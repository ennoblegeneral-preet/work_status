import hmac
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, status
from app.ai.provider import get_provider
from app.config import get_settings
from app.db import Session, get_db
from app.deps import can_manage_employee, ensure_can_view_employee, get_current_user, require_admin, visible_employee_ids
from app.models import AuditLog, Notification, Role, TimeOff, User
from app.schemas import AuditLogOut, NotificationOut, OrgSettingsOut, OrgSettingsUpdate, TimeOffIn, TimeOffOut
from app.services.automation import run_automation
from app.utils import audit, daterange, get_org_settings

router = APIRouter(tags=["settings & notifications"])


def _settings_out(db: Session) -> OrgSettingsOut:
    out = OrgSettingsOut.model_validate(get_org_settings(db))
    out.ai_mode = get_provider().mode
    return out


@router.get("/settings", response_model=OrgSettingsOut)
def read_settings(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _settings_out(db)


@router.patch("/settings", response_model=OrgSettingsOut)
def update_settings(data: OrgSettingsUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = get_org_settings(db)
    changes = data.model_dump(exclude_unset=True)
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except Exception:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown time zone")
    before = {k: getattr(s, k) for k in changes}
    for k, v in changes.items():
        setattr(s, k, v)
    audit(db, actor.id, "update_settings", "org_settings", 1, before=before, after=changes)
    db.commit()
    return _settings_out(db)


@router.get("/time-off", response_model=list[TimeOffOut])
def list_time_off(
    start: date | None = None,
    end: date | None = None,
    user_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f: dict = {}
    ids = visible_employee_ids(db, user)
    if user_id:
        ensure_can_view_employee(db, user, user_id)
        f["user_id"] = {"$in": [user_id, None]}
    elif ids is not None:
        f["user_id"] = {"$in": [*sorted(ids), None]}
    day: dict = {}
    if start:
        day["$gte"] = start
    if end:
        day["$lte"] = end
    if day:
        f["day"] = day
    return db.find(TimeOff, f, sort=[("day", 1), ("id", 1)])


@router.post("/time-off", response_model=list[TimeOffOut], status_code=201)
def add_time_off(data: TimeOffIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    end = data.end or data.start
    if end < data.start or (end - data.start).days > 60:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid date range (max 60 days)")
    if data.user_id is None:
        if user.role != Role.admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can add organization holidays")
    elif data.user_id != user.id and not can_manage_employee(db, user, data.user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot add leave for this employee")
    rows = []
    for d in daterange(data.start, end):
        if not db.exists(TimeOff, {"day": d, "user_id": data.user_id}):
            row = TimeOff(user_id=data.user_id, day=d, reason=data.reason)
            db.add(row)
            rows.append(row)
    audit(db, user.id, "add_time_off", "time_off", None, after=data.model_dump(mode="json"))
    db.commit()
    return rows


@router.delete("/time-off/{row_id}", status_code=204)
def delete_time_off(row_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(TimeOff, row_id)
    if row is None:
        raise HTTPException(404, "Not found")
    allowed = user.role == Role.admin or (
        row.user_id is not None and (row.user_id == user.id or can_manage_employee(db, user, row.user_id))
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot remove this entry")
    audit(db, user.id, "delete_time_off", "time_off", row.id, before={"user_id": row.user_id, "day": row.day})
    db.delete(row)
    db.commit()


@router.get("/notifications", response_model=list[NotificationOut])
def my_notifications(unread_only: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f: dict = {"user_id": user.id}
    if unread_only:
        f["read_at"] = None
    return db.find(Notification, f, sort=[("id", -1)], limit=100)


@router.post("/notifications/{nid}/read", status_code=204)
def mark_read(nid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "Not found")
    n.read_at = n.read_at or datetime.now(timezone.utc)
    db.commit()


@router.post("/notifications/read-all", status_code=204)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    for n in db.find(Notification, {"user_id": user.id, "read_at": None}):
        n.read_at = now
    db.commit()


@router.post("/admin/run-automation")
def trigger_automation(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Run reminders / deadline checks / scheduled report generation now."""
    return run_automation(db)


@router.get("/cron/automation", include_in_schema=False)
def cron_automation(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Entry point for a platform scheduler (e.g. Vercel Cron Jobs) instead of the in-process scheduler."""
    secret = get_settings().cron_secret
    if not secret or not authorization or not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    return run_automation(db)


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
    limit: int = 200,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    f: dict = {}
    if entity_type:
        f["entity_type"] = entity_type
    if entity_id:
        f["entity_id"] = entity_id
    if actor_id:
        f["actor_id"] = actor_id
    return db.find(AuditLog, f, sort=[("id", -1)], limit=min(limit, 1000))
