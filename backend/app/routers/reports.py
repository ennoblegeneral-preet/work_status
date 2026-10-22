from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from app.db import Session, get_db
from app.deps import (
    ai_rate_limit,
    can_manage_employee,
    can_view_employee,
    can_view_team,
    get_current_user,
    managed_team_ids,
    visible_employee_ids,
)
from app.models import ReportReview, ReportStatus, ReportType, Role, Team, User, WeeklyReport
from app.schemas import GenerateReportIn, ReportEditIn, ReportListItem, ReportOut, ReviewActionIn
from app.services import exports
from app.services import reports as svc
from app.services.notifications import managers_of, notify
from app.utils import audit, week_bounds

router = APIRouter(prefix="/reports", tags=["reports"])


def _load(db: Session, reports: list[WeeklyReport]) -> list[WeeklyReport]:
    db.preload(reports, "employee", "team", "reviews")
    db.preload([rv for r in reports for rv in r.reviews], "reviewer")
    return reports


def _out(r: WeeklyReport, cls=ReportOut):
    out = cls.model_validate(r)
    out.team_name = r.team.name if r.team else None
    return out


def _can_view(db: Session, user: User, r: WeeklyReport) -> bool:
    if r.report_type == ReportType.employee:
        return can_view_employee(db, user, r.employee_id)
    return can_view_team(db, user, r.team_id)


def _can_review(db: Session, user: User, r: WeeklyReport) -> bool:
    """Approve / return / edit as reviewer. Never the report's own subject."""
    if r.report_type == ReportType.employee:
        return can_manage_employee(db, user, r.employee_id)
    return user.role == Role.admin or (user.role == Role.manager and r.team_id in managed_team_ids(db, user))


def _get(db: Session, user: User, report_id: int) -> WeeklyReport:
    r = db.get(WeeklyReport, report_id)
    if r is None or not _can_view(db, user, r):
        raise HTTPException(404, "Not found")
    return _load(db, [r])[0]


def _review(db: Session, r: WeeklyReport, user: User, action: str, comment: str | None) -> None:
    db.add(ReportReview(report_id=r.id, reviewer_id=user.id, action=action, comment=comment))
    audit(db, user.id, f"report_{action}", "weekly_report", r.id, after={"status": r.status, "comment": comment})


@router.post("/generate", response_model=ReportOut, dependencies=[Depends(ai_rate_limit)])
def generate(data: GenerateReportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if bool(data.employee_id) == bool(data.team_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Provide exactly one of employee_id or team_id")
    if data.employee_id:
        emp = db.get(User, data.employee_id)
        if emp is None or not (emp.id == user.id or can_manage_employee(db, user, emp.id)):
            raise HTTPException(404, "Not found")
        r = svc.generate(db, user, data.week_start, employee=emp)
    else:
        team = db.get(Team, data.team_id)
        if team is None or not (user.role == Role.admin or team.manager_id == user.id):
            raise HTTPException(404, "Not found")
        r = svc.generate(db, user, data.week_start, team=team)
    db.commit()
    return _out(r)


@router.get("", response_model=list[ReportListItem])
def list_reports(
    week_start: date | None = None,
    report_type: ReportType | None = Query(None, alias="type"),
    status_: ReportStatus | None = Query(None, alias="status"),
    employee_id: int | None = None,
    team_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f: dict = {}
    if week_start:
        f["week_start"] = week_bounds(week_start)[0]
    if report_type:
        f["report_type"] = report_type
    if status_:
        f["status"] = status_
    if employee_id:
        f["employee_id"] = employee_id
    if team_id:
        f["team_id"] = team_id
    if user.role != Role.admin:
        ids = sorted(visible_employee_ids(db, user) or set())
        teams = managed_team_ids(db, user)
        f["$or"] = [{"employee_id": {"$in": ids}}, {"team_id": {"$in": teams}}]
    rows = db.find(WeeklyReport, f, sort=[("week_start", -1), ("report_type", 1), ("id", 1)], limit=500)
    db.preload(rows, "employee", "team")
    return [_out(r, ReportListItem) for r in rows]


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(_get(db, user, report_id))


@router.put("/{report_id}/content", response_model=ReportOut)
def edit_content(report_id: int, data: ReportEditIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _get(db, user, report_id)
    is_subject = r.report_type == ReportType.employee and r.employee_id == user.id
    if r.status == ReportStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Approved reports cannot be edited")
    if not (_can_review(db, user, r) or (is_subject and r.status in (ReportStatus.draft, ReportStatus.returned))):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot edit this report now")
    before = r.content_markdown
    r.content_markdown = data.content_markdown
    r.edited_by_human = True
    _review(db, r, user, "edit", data.comment)
    audit(db, user.id, "report_content_edit", "weekly_report", r.id, before={"content": before}, after={"content": r.content_markdown})
    db.commit()
    return _out(_get(db, user, report_id))


@router.post("/{report_id}/submit", response_model=ReportOut)
def submit(report_id: int, data: ReviewActionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _get(db, user, report_id)
    if r.report_type != ReportType.employee:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Team reports are approved directly by their manager or an admin")
    if r.employee_id != user.id and not _can_review(db, user, r):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot submit this report")
    if r.status not in (ReportStatus.draft, ReportStatus.returned):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A {r.status} report cannot be submitted")
    r.status = ReportStatus.submitted
    _review(db, r, user, "submit", data.comment)
    for m in managers_of(db, r.employee_id):
        notify(db, m, "report_review", f"Report to review: {r.employee.full_name}",
               f"report_review:{r.id}:{r.version}:{len(r.reviews)}:{m.id}", data.comment, f"/reports/{r.id}")
    db.commit()
    return _out(_get(db, user, report_id))


@router.post("/{report_id}/approve", response_model=ReportOut)
def approve(report_id: int, data: ReviewActionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _get(db, user, report_id)
    if not _can_review(db, user, r):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can approve this report")
    if r.status not in (ReportStatus.draft, ReportStatus.submitted):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A {r.status} report cannot be approved")
    svc.mark_approved(r, user)
    _review(db, r, user, "approve", data.comment)
    if r.employee:
        notify(db, r.employee, "report_status", "Your weekly report was approved", f"report_approved:{r.id}:{r.version}",
               data.comment, f"/reports/{r.id}")
    db.commit()
    return _out(_get(db, user, report_id))


@router.post("/{report_id}/return", response_model=ReportOut)
def return_report(report_id: int, data: ReviewActionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _get(db, user, report_id)
    if not _can_review(db, user, r):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can return this report")
    if r.status != ReportStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only submitted reports can be returned")
    if not (data.comment and data.comment.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Explain what needs to be corrected")
    r.status = ReportStatus.returned
    _review(db, r, user, "return", data.comment)
    if r.employee:
        notify(db, r.employee, "report_status", "Your weekly report needs changes",
               f"report_returned:{r.id}:{r.version}:{len(r.reviews)}", data.comment, f"/reports/{r.id}")
    db.commit()
    return _out(_get(db, user, report_id))


@router.get("/{report_id}/export")
def export(
    report_id: int,
    format: str = Query("md", pattern="^(md|pdf|xlsx)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = _get(db, user, report_id)
    if r.status != ReportStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only approved reports can be exported")
    if format == "md":
        body, mime = r.content_markdown.encode("utf-8"), "text/markdown; charset=utf-8"
    elif format == "pdf":
        body, mime = exports.to_pdf(r), "application/pdf"
    else:
        body, mime = exports.to_xlsx(r), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    name = exports.report_filename(r, format)
    return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})
