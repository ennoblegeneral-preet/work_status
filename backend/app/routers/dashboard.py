from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import can_view_team, get_current_user, require_manager_or_admin, visible_employee_ids
from app.models import (
    DailyWorkLog,
    GoalStatus,
    LogStatus,
    Notification,
    ReportStatus,
    ReportType,
    Role,
    Task,
    TaskStatus,
    Team,
    TeamMember,
    User,
    WeeklyGoal,
    WeeklyReport,
    WorkLogItem,
)
from app.services.goals import goal_out, goals_query
from app.services.matching import similarity
from app.services.missing import missing_for_user
from app.services.progress import CLOSED_GOAL
from app.utils import get_org_settings, org_today, week_bounds

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _scope_users(db: Session, user: User, team_id: int | None) -> list[User]:
    if team_id:
        if not can_view_team(db, user, team_id):
            raise HTTPException(404, "Not found")
        q = select(User).join(TeamMember, TeamMember.user_id == User.id).where(TeamMember.team_id == team_id)
    else:
        ids = visible_employee_ids(db, user)
        q = select(User)
        if ids is not None:
            q = q.where(User.id.in_(ids - {user.id}) if user.role == Role.manager else User.id.in_(ids))
    return list(db.scalars(q.where(User.is_active.is_(True), User.role != Role.admin).order_by(User.full_name)))


@router.get("/me")
def my_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = org_today(db)
    ws, we = week_bounds(today)
    wd = get_org_settings(db).working_days
    goals = [goal_out(db, g, today, wd) for g in db.scalars(
        goals_query().where(WeeklyGoal.owner_id == user.id, WeeklyGoal.week_start == ws).order_by(WeeklyGoal.id))]
    active = [g for g in goals if g.status not in CLOSED_GOAL or g.status == GoalStatus.completed]
    recent = db.scalars(
        select(DailyWorkLog)
        .where(DailyWorkLog.employee_id == user.id, DailyWorkLog.status == LogStatus.confirmed)
        .order_by(DailyWorkLog.report_date.desc(), DailyWorkLog.id.desc())
        .limit(5)
    )
    report = db.scalar(
        select(WeeklyReport).where(
            WeeklyReport.report_type == ReportType.employee, WeeklyReport.employee_id == user.id, WeeklyReport.week_start == ws
        )
    )
    drafts = db.scalar(
        select(func.count(DailyWorkLog.id)).where(DailyWorkLog.employee_id == user.id, DailyWorkLog.status == LogStatus.draft)
    )
    cov = missing_for_user(db, user, ws, we)
    return {
        "today": today,
        "week_start": ws,
        "week_end": we,
        "goals": goals,
        "summary": {
            "goals": len(active),
            "completed": sum(1 for g in active if g.status == GoalStatus.completed),
            "average_progress": round(sum(g.progress for g in active) / len(active), 1) if active else 0,
            "at_risk": sum(1 for g in active if g.health in ("at_risk", "off_track")),
        },
        "submitted_today": cov["submitted_today"],
        "open_drafts": drafts,
        "coverage": cov,
        "recent_logs": [
            {"id": log.id, "report_date": log.report_date, "items": len(log.items), "total_hours": log.total_hours,
             "blockers": len(log.blockers or [])}
            for log in recent
        ],
        "report": {"id": report.id, "status": report.status} if report else None,
        "unread_notifications": db.scalar(
            select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))
        ),
    }


@router.get("/overview")
def overview(
    week_start: date | None = None,
    team_id: int | None = None,
    user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
):
    today = org_today(db)
    ws, we = week_bounds(week_start or today)
    wd = get_org_settings(db).working_days
    users = _scope_users(db, user, team_id)
    uids = [u.id for u in users] or [-1]

    goals = list(db.scalars(goals_query().where(WeeklyGoal.owner_id.in_(uids), WeeklyGoal.week_start == ws).order_by(WeeklyGoal.owner_id, WeeklyGoal.id)))
    goal_rows = [goal_out(db, g, today, wd) for g in goals]
    by_owner: dict[int, list] = defaultdict(list)
    for g in goal_rows:
        by_owner[g.owner_id].append(g)

    team_names: dict[int, list[str]] = defaultdict(list)
    for uid, name in db.execute(select(TeamMember.user_id, Team.name).join(Team).where(TeamMember.user_id.in_(uids))):
        team_names[uid].append(name)
    latest = dict(
        db.execute(
            select(DailyWorkLog.employee_id, func.max(DailyWorkLog.report_date))
            .where(DailyWorkLog.employee_id.in_(uids), DailyWorkLog.status == LogStatus.confirmed)
            .group_by(DailyWorkLog.employee_id)
        ).all()
    )

    rows, missing, expected_total, reported_total = [], [], 0, 0
    for u in users:
        cov = missing_for_user(db, u, ws, we)
        expected_total += cov["expected_days"]
        reported_total += cov["reported_days"]
        gs = by_owner.get(u.id, [])
        tasks = [t for g in gs for t in g.tasks]
        rows.append(
            {
                "employee_id": u.id,
                "name": u.full_name,
                "department": u.department,
                "teams": team_names.get(u.id, []),
                "goals_assigned": len([g for g in gs if g.status not in (GoalStatus.cancelled, GoalStatus.deferred)]),
                "goals_completed": sum(1 for g in gs if g.status == GoalStatus.completed),
                "pending_tasks": sum(1 for t in tasks if t.status in (TaskStatus.not_started, TaskStatus.in_progress)),
                "blocked_items": sum(1 for t in tasks if t.status == TaskStatus.blocked) + sum(1 for g in gs if g.status == GoalStatus.blocked),
                "average_progress": round(sum(g.progress for g in gs) / len(gs), 1) if gs else None,
                "latest_update": latest.get(u.id),
                "submitted_today": cov["submitted_today"],
                "missing_dates": cov["missing_dates"],
            }
        )
        if cov["missing_dates"]:
            missing.append({"employee_id": u.id, "name": u.full_name, "missing_dates": cov["missing_dates"],
                            "expected_days": cov["expected_days"], "reported_days": cov["reported_days"]})

    blockers = []
    for log in db.scalars(
        select(DailyWorkLog).where(
            DailyWorkLog.employee_id.in_(uids), DailyWorkLog.status == LogStatus.confirmed,
            DailyWorkLog.report_date >= ws, DailyWorkLog.report_date <= we,
        ).order_by(DailyWorkLog.report_date.desc())
    ):
        for b in log.blockers or []:
            blockers.append({"employee_id": log.employee_id, "name": log.employee.full_name, "date": log.report_date, "text": b, "log_id": log.id})

    active = [g for g in goal_rows if g.status not in (GoalStatus.cancelled, GoalStatus.deferred)]
    overdue = [g for g in active if g.status != GoalStatus.completed and (g.deadline or g.week_end) < today]
    pending_q = select(func.count(WeeklyReport.id)).where(WeeklyReport.status == ReportStatus.submitted, WeeklyReport.employee_id.in_(uids))
    return {
        "week_start": ws,
        "week_end": we,
        "cards": {
            "total_employees": len(users),
            "active_goals": len(active),
            "completed_goals": sum(1 for g in active if g.status == GoalStatus.completed),
            "in_progress_goals": sum(1 for g in active if g.status == GoalStatus.in_progress),
            "blocked_or_overdue": len({g.id for g in active if g.status == GoalStatus.blocked} | {g.id for g in overdue}),
            "submission_rate": round(reported_total / expected_total * 100) if expected_total else None,
            "reports_pending_review": db.scalar(pending_q),
        },
        "team_overview": rows,
        "goals": goal_rows,
        "missing_updates": missing,
        "blockers": blockers,
    }


@router.get("/analytics")
def analytics(
    weeks: int = 6,
    team_id: int | None = None,
    user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
):
    weeks = min(max(weeks, 1), 26)
    today = org_today(db)
    wd = get_org_settings(db).working_days
    users = _scope_users(db, user, team_id)
    uids = [u.id for u in users] or [-1]
    cur_ws = week_bounds(today)[0]
    first_ws = cur_ws - timedelta(days=7 * (weeks - 1))

    trend = []
    for i in range(weeks):
        ws = first_ws + timedelta(days=7 * i)
        we = ws + timedelta(days=6)
        gs = [goal_out(db, g, today, wd) for g in db.scalars(goals_query().where(WeeklyGoal.owner_id.in_(uids), WeeklyGoal.week_start == ws))]
        gs = [g for g in gs if g.status != GoalStatus.cancelled]
        exp = rep = 0
        for u in users:
            c = missing_for_user(db, u, ws, we)
            exp += c["expected_days"]
            rep += c["reported_days"]
        trend.append(
            {
                "week_start": ws,
                "goals": len(gs),
                "completed": sum(1 for g in gs if g.status == GoalStatus.completed),
                "completion_rate": round(sum(1 for g in gs if g.status == GoalStatus.completed) / len(gs) * 100) if gs else None,
                "average_progress": round(sum(g.progress for g in gs) / len(gs), 1) if gs else None,
                "submission_rate": round(rep / exp * 100) if exp else None,
            }
        )

    # recurring blockers: greedy grouping of similar blocker texts
    groups: list[dict] = []
    for log in db.scalars(
        select(DailyWorkLog).where(
            DailyWorkLog.employee_id.in_(uids), DailyWorkLog.status == LogStatus.confirmed, DailyWorkLog.report_date >= first_ws
        )
    ):
        for b in log.blockers or []:
            g = next((g for g in groups if similarity(g["text"], b) >= 0.6), None)
            if g is None:
                groups.append({"text": b, "count": 1, "employees": {log.employee.full_name}, "last_seen": log.report_date})
            else:
                g["count"] += 1
                g["employees"].add(log.employee.full_name)
                g["last_seen"] = max(g["last_seen"], log.report_date)
    recurring = sorted(
        [dict(g, employees=sorted(g["employees"])) for g in groups if g["count"] > 1], key=lambda g: -g["count"]
    )[:10]

    overdue = [
        goal_out(db, g, today, wd)
        for g in db.scalars(
            goals_query().where(
                WeeklyGoal.owner_id.in_(uids),
                WeeklyGoal.status.in_([GoalStatus.not_started, GoalStatus.in_progress, GoalStatus.blocked]),
                func.coalesce(WeeklyGoal.deadline, WeeklyGoal.week_end) < today,
            )
        )
    ]

    workload = []
    for u in users:
        items = db.scalar(
            select(func.count(WorkLogItem.id)).join(DailyWorkLog).where(
                WorkLogItem.employee_id == u.id, WorkLogItem.report_date >= first_ws, DailyWorkLog.status == LogStatus.confirmed
            )
        )
        hours = db.scalar(
            select(func.sum(DailyWorkLog.total_hours)).where(
                DailyWorkLog.employee_id == u.id, DailyWorkLog.report_date >= first_ws, DailyWorkLog.status == LogStatus.confirmed
            )
        )
        open_tasks = db.scalar(
            select(func.count(Task.id)).where(Task.owner_id == u.id, Task.status.in_([TaskStatus.not_started, TaskStatus.in_progress, TaskStatus.blocked]))
        )
        workload.append({"employee_id": u.id, "name": u.full_name, "work_items": items, "reported_hours": round(hours or 0, 1), "open_tasks": open_tasks})

    return {"weeks": trend, "recurring_blockers": recurring, "overdue_goals": overdue, "workload": workload}
