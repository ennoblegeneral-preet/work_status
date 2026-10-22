from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from app.db import Session, get_db
from app.deps import ai_rate_limit, ensure_can_view_employee, get_current_user, visible_employee_ids
from app.models import AuditLog, DailyWorkLog, LogStatus, Role, User, WorkLogItem
from app.schemas import (
    AuditLogOut,
    ChatMessageIn,
    ConfirmIn,
    DailyLogOut,
    DraftOut,
    Page,
    ParseRequest,
    WorkLogItemOut,
    WorkLogItemUpdate,
)
from app.services import daily_updates as svc
from app.utils import audit

router = APIRouter(tags=["daily updates"])


def _own_draft(db: Session, user: User, log_id: int) -> DailyWorkLog:
    log = db.get(DailyWorkLog, log_id)
    # Only the author can work on their own draft.
    if log is None or log.employee_id != user.id:
        raise HTTPException(404, "Not found")
    return log


def _with_items(db: Session, logs: list[DailyWorkLog]) -> list[DailyWorkLog]:
    db.preload(logs, "items", "employee")
    return logs


@router.post("/daily-updates/parse", response_model=DraftOut, dependencies=[Depends(ai_rate_limit)])
def parse_update(data: ParseRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Parse pasted text or the first chat message into an editable draft. Nothing is saved as work yet."""
    log = svc.create_draft(db, user, data)
    db.commit()
    return svc.draft_out(db, log)


@router.get("/daily-updates/drafts", response_model=list[DraftOut])
def my_drafts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    logs = db.find(DailyWorkLog, {"employee_id": user.id, "status": LogStatus.draft}, sort=[("id", -1)], limit=10)
    return [svc.draft_out(db, log) for log in logs]


@router.get("/daily-updates/{log_id}/draft", response_model=DraftOut)
def get_draft(log_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.draft_out(db, _own_draft(db, user, log_id))


@router.post("/daily-updates/{log_id}/chat", response_model=DraftOut, dependencies=[Depends(ai_rate_limit)])
def chat(log_id: int, data: ChatMessageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = svc.chat_turn(db, _own_draft(db, user, log_id), user, data.message)
    db.commit()
    return svc.draft_out(db, log)


@router.put("/daily-updates/{log_id}/draft", response_model=DraftOut)
def save_draft(log_id: int, data: ConfirmIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = svc.save_draft_edits(db, _own_draft(db, user, log_id), data.draft)
    db.commit()
    return svc.draft_out(db, log)


@router.post("/daily-updates/{log_id}/confirm", response_model=DailyLogOut)
def confirm(log_id: int, data: ConfirmIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = svc.confirm(db, _own_draft(db, user, log_id), user, data.draft)
    db.commit()
    return log


@router.post("/daily-updates/{log_id}/discard", status_code=204)
def discard(log_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = _own_draft(db, user, log_id)
    if log.status != LogStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only drafts can be discarded")
    log.status = LogStatus.discarded
    audit(db, user.id, "discard_draft", "daily_work_log", log.id)
    db.commit()


# ---------------------------------------------------------------- history


@router.get("/work-logs", response_model=Page[DailyLogOut])
def list_logs(
    employee_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    page: int = 1,
    page_size: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page, page_size = max(1, page), min(max(1, page_size), 100)
    f: dict = {"status": LogStatus.confirmed}
    if employee_id:
        ensure_can_view_employee(db, user, employee_id)
        f["employee_id"] = employee_id
    else:
        ids = visible_employee_ids(db, user)
        if ids is not None:
            f["employee_id"] = {"$in": sorted(ids)}
    day: dict = {}
    if start:
        day["$gte"] = start
    if end:
        day["$lte"] = end
    if day:
        f["report_date"] = day
    total = db.count(DailyWorkLog, f)
    rows = db.find(DailyWorkLog, f, sort=[("report_date", -1), ("id", -1)], skip=(page - 1) * page_size, limit=page_size)
    return Page(items=_with_items(db, rows), total=total, page=page, page_size=page_size)


@router.get("/work-logs/{log_id}", response_model=DailyLogOut)
def get_log(log_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = db.get(DailyWorkLog, log_id)
    if log is None or log.status == LogStatus.discarded:
        raise HTTPException(404, "Not found")
    ensure_can_view_employee(db, user, log.employee_id)
    if log.status == LogStatus.draft and log.employee_id != user.id:
        raise HTTPException(404, "Not found")
    return log


@router.get("/work-logs/{log_id}/history", response_model=list[AuditLogOut])
def log_history(log_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = get_log(log_id, user, db)
    item_ids = [i.id for i in log.items]
    return db.find(
        AuditLog,
        {
            "$or": [
                {"entity_type": "daily_work_log", "entity_id": log.id},
                {"entity_type": "work_log_item", "entity_id": {"$in": item_ids}},
            ]
        },
    )


@router.patch("/work-log-items/{item_id}", response_model=WorkLogItemOut)
def edit_item(item_id: int, data: WorkLogItemUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(WorkLogItem, item_id)
    if item is None:
        raise HTTPException(404, "Not found")
    ensure_can_view_employee(db, user, item.employee_id)
    if item.employee_id != user.id and user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the employee (or an admin) can edit their work log")
    svc.update_item(db, item, data, user)
    db.commit()
    return item
