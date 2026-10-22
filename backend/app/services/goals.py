from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import GoalStatus, Task, TaskStatus, WeeklyGoal
from app.schemas import GoalOut, GoalReviewDecision
from app.services.progress import (
    CLOSED_GOAL,
    goal_health,
    goal_progress,
    last_activity,
    set_goal_status,
    set_task_status,
)
from app.utils import audit, get_org_settings, org_today, week_bounds


def goal_out(db: Session, goal: WeeklyGoal, today: date | None = None, working_days: list[int] | None = None) -> GoalOut:
    if today is None:
        today = org_today(db)
    if working_days is None:
        working_days = get_org_settings(db).working_days
    progress = goal_progress(goal)
    out = GoalOut.model_validate(goal)
    out.progress = progress
    out.health = goal_health(goal, today, working_days, progress)
    out.last_activity = last_activity(db, goal.id)
    return out


def goals_query():
    return select(WeeklyGoal).options(selectinload(WeeklyGoal.tasks), selectinload(WeeklyGoal.owner))


def employee_week_goals(db: Session, employee_id: int, any_day: date, include_closed: bool = True) -> list[WeeklyGoal]:
    ws, _ = week_bounds(any_day)
    q = goals_query().where(WeeklyGoal.owner_id == employee_id, WeeklyGoal.week_start == ws)
    if not include_closed:
        q = q.where(WeeklyGoal.status.not_in([GoalStatus.cancelled, GoalStatus.deferred]))
    return list(db.scalars(q.order_by(WeeklyGoal.id)))


def unfinished_goals(db: Session, week_start: date, employee_ids: set[int] | None) -> list[WeeklyGoal]:
    q = goals_query().where(
        WeeklyGoal.week_start == week_start,
        WeeklyGoal.status.not_in(list(CLOSED_GOAL)),
        WeeklyGoal.reviewed_at.is_(None),
    )
    if employee_ids is not None:
        q = q.where(WeeklyGoal.owner_id.in_(employee_ids))
    return list(db.scalars(q.order_by(WeeklyGoal.owner_id, WeeklyGoal.id)))


def review_goal(db: Session, goal: WeeklyGoal, decision: GoalReviewDecision, actor_id: int) -> WeeklyGoal | None:
    """End-of-week review of an unfinished goal. Never silently duplicates or resets.

    carry_forward: the original goal is closed as 'deferred' (history kept) and a new
    goal is created in the next week, linked via carried_from_goal_id, preserving the
    original deadline and the reason. Unfinished tasks are copied; completed ones stay.
    """
    from datetime import datetime, timezone

    if goal.status in CLOSED_GOAL:
        raise HTTPException(status.HTTP_409_CONFLICT, "This goal is already closed")
    now = datetime.now(timezone.utc)
    goal.reviewed_at = now
    new_goal = None

    if decision.action == "complete":
        set_goal_status(db, goal, GoalStatus.completed, actor_id, decision.reason)
    elif decision.action == "cancel":
        set_goal_status(db, goal, GoalStatus.cancelled, actor_id, decision.reason)
    elif decision.action == "defer":
        set_goal_status(db, goal, GoalStatus.deferred, actor_id, decision.reason)
    else:
        next_start = goal.week_start + timedelta(days=7)
        new_goal = WeeklyGoal(
            title=goal.title,
            description=goal.description,
            owner_id=goal.owner_id,
            team_id=goal.team_id,
            project=goal.project,
            week_start=next_start,
            week_end=next_start + timedelta(days=6),
            expected_outcome=goal.expected_outcome,
            success_criteria=goal.success_criteria,
            priority=goal.priority,
            start_date=next_start,
            deadline=decision.new_deadline or (goal.deadline + timedelta(days=7) if goal.deadline else None),
            original_deadline=goal.original_deadline or goal.deadline,
            status=GoalStatus.in_progress if goal.status != GoalStatus.not_started else GoalStatus.not_started,
            target_type=goal.target_type,
            target_value=goal.target_value,
            current_value=goal.current_value,
            unit=goal.unit,
            dependencies=goal.dependencies,
            blockers=goal.blockers,
            carried_from_goal_id=goal.id,
            carry_forward_reason=decision.reason,
            created_by_id=actor_id,
        )
        db.add(new_goal)
        db.flush()
        for t in goal.tasks:
            if t.status in (TaskStatus.completed, TaskStatus.cancelled):
                continue
            db.add(
                Task(
                    goal_id=new_goal.id,
                    owner_id=t.owner_id,
                    title=t.title,
                    description=t.description,
                    project=t.project,
                    status=TaskStatus.in_progress if t.status == TaskStatus.in_progress else TaskStatus.not_started,
                    priority=t.priority,
                    weight=t.weight,
                    due_date=t.due_date,
                    carried_from_task_id=t.id,
                    created_by_id=actor_id,
                )
            )
        set_goal_status(db, goal, GoalStatus.deferred, actor_id, f"Carried forward to G-{new_goal.id}: {decision.reason}")

    audit(db, actor_id, f"goal_review_{decision.action}", "weekly_goal", goal.id, after=decision.model_dump())
    return new_goal


def change_task_status(db: Session, task: Task, new_status: str, actor_id: int, reason: str | None) -> None:
    from app.services.progress import sync_goal_status_from_work

    set_task_status(db, task, new_status, actor_id, reason)
    if task.goal is not None:
        sync_goal_status_from_work(db, task.goal, actor_id)
