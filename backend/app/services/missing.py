"""Missing daily update detection.

An employee is expected to report on configured working days, excluding org
holidays, their own leave, days before their account existed and future days.
A missing update is reported as a data gap only - never as a performance signal.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyWorkLog, LogStatus, Role, TimeOff, User
from app.utils import daterange, get_org_settings, org_today


def expected_days(db: Session, user: User, start: date, end: date) -> list[date]:
    s = get_org_settings(db)
    today = org_today(db)
    end = min(end, today)
    joined = user.created_at.date() if user.created_at else start
    off = {
        r.day
        for r in db.scalars(
            select(TimeOff).where(
                TimeOff.day >= start, TimeOff.day <= end, (TimeOff.user_id == user.id) | (TimeOff.user_id.is_(None))
            )
        )
    }
    return [d for d in daterange(max(start, joined), end) if d.weekday() in s.working_days and d not in off]


def reported_days(db: Session, user_id: int, start: date, end: date) -> set[date]:
    return set(
        db.scalars(
            select(DailyWorkLog.report_date).where(
                DailyWorkLog.employee_id == user_id,
                DailyWorkLog.report_date >= start,
                DailyWorkLog.report_date <= end,
                DailyWorkLog.status == LogStatus.confirmed,
            )
        )
    )


def missing_for_user(db: Session, user: User, start: date, end: date, include_today: bool = False) -> dict:
    today = org_today(db)
    exp = expected_days(db, user, start, end)
    got = reported_days(db, user.id, start, end)
    if not include_today:
        # Today isn't "missing" until the day is over, but counts once reported.
        exp = [d for d in exp if d < today or d in got]
    missing = [d for d in exp if d not in got]
    return {
        "employee_id": user.id,
        "employee_name": user.full_name,
        "expected_days": len(exp),
        "reported_days": len([d for d in exp if d in got]),
        "missing_dates": missing,
        "submitted_today": today in got,
    }


def missing_report(db: Session, users: list[User], start: date, end: date) -> list[dict]:
    rows = []
    for u in users:
        if not u.is_active or u.role == Role.admin:
            continue
        rows.append(missing_for_user(db, u, start, end))
    return rows
