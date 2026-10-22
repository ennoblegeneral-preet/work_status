"""Scheduled automation. `run_automation` is a pure function of (db, now) so it
can be unit-tested; the APScheduler job just calls it periodically.

Every notification uses a dedupe key, so running the job repeatedly never sends
duplicates.
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import HTTPException

from app.config import get_settings
from app.db import SessionLocal
from app.models import DailyWorkLog, GoalStatus, LogStatus, Role, Task, TaskStatus, Team, TimeOff, User, WeeklyGoal
from app.services import reports as report_service
from app.services.goals import unfinished_goals
from app.services.notifications import managers_of, notify
from app.utils import get_org_settings, org_now, week_bounds

log = logging.getLogger("teamtrack.automation")


def _after(now: datetime, hhmm: str) -> bool:
    h, m = (int(x) for x in hhmm.split(":"))
    return (now.hour, now.minute) >= (h, m)


def _is_off(db, user_id: int, day) -> bool:
    return db.exists(TimeOff, {"day": day, "user_id": {"$in": [user_id, None]}})


def run_automation(db, now: datetime | None = None) -> dict:
    s = get_org_settings(db)
    now = now or org_now(db)
    today = now.date()
    counts = {"reminders": 0, "deadlines": 0, "overdue": 0, "reports": 0, "goal_reviews": 0}
    working_day = today.weekday() in s.working_days
    users = db.find(User, {"is_active": True, "role": {"$ne": Role.admin}})

    # 1. daily update reminders
    if s.reminders_enabled and working_day and _after(now, s.daily_reminder_time):
        for u in users:
            if _is_off(db, u.id, today):
                continue
            done = db.exists(DailyWorkLog, {"employee_id": u.id, "report_date": today, "status": LogStatus.confirmed})
            if not done and notify(
                db, u, "daily_reminder", "Add today's work update",
                f"reminder:{u.id}:{today.isoformat()}",
                "Paste your status or use the AI chat - it takes a minute.", "/update",
            ):
                counts["reminders"] += 1

    # 2. upcoming deadlines (due tomorrow) and overdue items
    tomorrow = today + timedelta(days=1)
    open_goal = [GoalStatus.not_started, GoalStatus.in_progress, GoalStatus.blocked]
    for g in db.find(WeeklyGoal, {"deadline": tomorrow, "status": {"$in": open_goal}}):
        if notify(db, g.owner, "deadline", f"Goal due tomorrow: {g.title}", f"deadline:goal:{g.id}:{g.deadline}", None, f"/goals/{g.id}"):
            counts["deadlines"] += 1
    for t in db.find(Task, {"due_date": tomorrow, "status": {"$nin": [TaskStatus.completed, TaskStatus.cancelled]}}):
        if notify(db, t.owner, "deadline", f"Task due tomorrow: {t.title}", f"deadline:task:{t.id}:{t.due_date}", None, "/goals"):
            counts["deadlines"] += 1
    for g in db.find(WeeklyGoal, {"deadline": {"$lt": today}, "status": {"$in": open_goal}}):
        for target in [g.owner, *managers_of(db, g.owner_id)]:
            if notify(
                db, target, "overdue", f"Overdue goal: {g.title}",
                f"overdue:goal:{g.id}:{g.deadline}:{target.id}", f"Owner: {g.owner.full_name}. Deadline was {g.deadline}.",
                f"/goals/{g.id}",
            ):
                counts["overdue"] += 1

    # 3. end-of-week: generate report drafts and ask for unfinished-goal review
    if today.weekday() == s.report_generation_day and _after(now, s.report_generation_time):
        ws, _ = week_bounds(today)
        if s.auto_generate_reports:
            for u in users:
                has_data = db.exists(WeeklyGoal, {"owner_id": u.id, "week_start": ws}) or db.exists(
                    DailyWorkLog, {"employee_id": u.id, "report_date": {"$gte": ws}}
                )
                if not has_data or report_service._find_report(db, "employee", ws, u.id, None):
                    continue
                try:
                    report_service.generate(db, None, ws, employee=u)
                    counts["reports"] += 1
                    notify(db, u, "report_ready", "Your weekly report draft is ready", f"report_ready:{u.id}:{ws}",
                           "Review it and submit it to your manager.", "/reports")
                except HTTPException:
                    pass
            for team in db.find(Team):
                if report_service._find_report(db, "team", ws, None, team.id):
                    continue
                try:
                    report_service.generate(db, None, ws, team=team)
                    counts["reports"] += 1
                    if team.manager:
                        notify(db, team.manager, "report_ready", f"Team report draft ready: {team.name}",
                               f"team_report_ready:{team.id}:{ws}", None, "/reports")
                except HTTPException:
                    pass
        pending = unfinished_goals(db, ws, None)
        owners = {g.owner_id for g in pending}
        reviewers = {m.id: m for oid in owners for m in managers_of(db, oid)}
        for m in reviewers.values():
            if notify(
                db, m, "goal_review", "Review unfinished goals for this week",
                f"goal_review:{ws}:{m.id}", "Decide what to carry forward, defer or close.", "/goals/review",
            ):
                counts["goal_reviews"] += 1
    db.commit()
    return counts


_scheduler: BackgroundScheduler | None = None


def _job() -> None:
    db = SessionLocal()
    try:
        counts = run_automation(db)
        if any(counts.values()):
            log.info("automation: %s", counts)
    except Exception:
        db.rollback()
        log.exception("automation job failed")
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler
    s = get_settings()
    if not s.scheduler_enabled or _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_job, "interval", minutes=s.scheduler_interval_minutes, next_run_time=datetime.now())
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
