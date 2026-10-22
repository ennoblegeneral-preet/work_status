"""Deterministic goal progress and health rules.

Progress is never inferred from "worked on it": it comes from completed tasks,
a numeric target, or an explicit completed status.
"""

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    GoalStatus,
    GoalStatusHistory,
    TargetType,
    Task,
    TaskStatus,
    TaskStatusHistory,
    WeeklyGoal,
    WorkLogItem,
)

CLOSED_GOAL = {GoalStatus.completed, GoalStatus.cancelled, GoalStatus.deferred}


def goal_progress(goal: WeeklyGoal) -> float:
    if goal.status == GoalStatus.completed:
        return 100.0
    if goal.target_type == TargetType.number:
        if goal.target_value and goal.current_value is not None:
            return round(min(100.0, max(0.0, goal.current_value / goal.target_value * 100)), 1)
        return 0.0
    if goal.target_type == TargetType.boolean:
        return 0.0
    tasks = [t for t in goal.tasks if t.status != TaskStatus.cancelled]
    total = sum(t.weight for t in tasks)
    if not total:
        return 0.0
    done = sum(t.weight for t in tasks if t.status == TaskStatus.completed)
    return round(done / total * 100, 1)


def _working_days_between(start: date, end: date, working_days: list[int]) -> int:
    if end < start:
        return 0
    return sum(1 for i in range((end - start).days + 1) if (start.toordinal() + i) % 7 in _ord_days(working_days))


def _ord_days(working_days: list[int]) -> set[int]:
    # date.toordinal() % 7: Monday == 1 ... Sunday == 0
    return {(d + 1) % 7 for d in working_days}


def goal_health(goal: WeeklyGoal, today: date, working_days: list[int], progress: float | None = None) -> str:
    """on_track / at_risk / off_track (Asana-style), plus terminal states."""
    if goal.status == GoalStatus.completed:
        return "completed"
    if goal.status in (GoalStatus.cancelled, GoalStatus.deferred):
        return goal.status
    if goal.status == GoalStatus.blocked:
        return "off_track"
    start = goal.start_date or goal.week_start
    end = goal.deadline or goal.week_end
    if today < start:
        return "not_started"
    if today > end:
        return "off_track"
    total = _working_days_between(start, end, working_days) or 1
    elapsed = _working_days_between(start, today, working_days)
    expected = elapsed / total
    p = (goal_progress(goal) if progress is None else progress) / 100
    if goal.target_type == TargetType.boolean:
        # No measurable intermediate progress: only flag risk near the deadline.
        return "at_risk" if expected >= 0.8 else "on_track"
    if p >= expected - 0.2:
        return "on_track"
    if p >= expected - 0.45:
        return "at_risk"
    return "off_track"


def last_activity(db: Session, goal_id: int) -> date | None:
    return db.scalar(select(func.max(WorkLogItem.report_date)).where(WorkLogItem.goal_id == goal_id))


def set_task_status(
    db: Session,
    task: Task,
    new_status: str,
    actor_id: int | None,
    reason: str | None = None,
    work_log_item_id: int | None = None,
) -> bool:
    if task.status == new_status:
        return False
    db.add(
        TaskStatusHistory(
            task_id=task.id,
            from_status=task.status,
            to_status=new_status,
            changed_by_id=actor_id,
            reason=reason,
            work_log_item_id=work_log_item_id,
        )
    )
    task.status = new_status
    task.completed_at = datetime.now(timezone.utc) if new_status == TaskStatus.completed else None
    return True


def set_goal_status(db: Session, goal: WeeklyGoal, new_status: str, actor_id: int | None, reason: str | None = None) -> bool:
    if goal.status == new_status:
        return False
    db.add(
        GoalStatusHistory(
            goal_id=goal.id, from_status=goal.status, to_status=new_status, changed_by_id=actor_id, reason=reason
        )
    )
    goal.status = new_status
    return True


def sync_goal_status_from_work(db: Session, goal: WeeklyGoal, actor_id: int | None) -> None:
    """Automatic, rule-based goal transitions after work is logged or tasks change.

    - not_started -> in_progress when any work is recorded or a task moves
    - -> completed only when the goal is task-based, has tasks, and all
      non-cancelled tasks are completed (the defined success rule)
    - completed task-based goal -> in_progress if a task is reopened
    """
    db.flush()
    db.refresh(goal)
    if goal.status in (GoalStatus.cancelled, GoalStatus.deferred):
        return
    tasks = [t for t in goal.tasks if t.status != TaskStatus.cancelled]
    has_work = bool(db.scalar(select(func.count(WorkLogItem.id)).where(WorkLogItem.goal_id == goal.id)))
    any_moved = any(t.status != TaskStatus.not_started for t in tasks)

    if goal.target_type == TargetType.tasks and tasks:
        all_done = all(t.status == TaskStatus.completed for t in tasks)
        if all_done and goal.status != GoalStatus.completed:
            set_goal_status(db, goal, GoalStatus.completed, actor_id, "All tasks completed")
            return
        if not all_done and goal.status == GoalStatus.completed:
            set_goal_status(db, goal, GoalStatus.in_progress, actor_id, "A task was reopened")
            return
    if goal.target_type == TargetType.number and goal.target_value and (goal.current_value or 0) >= goal.target_value:
        if goal.status != GoalStatus.completed:
            set_goal_status(db, goal, GoalStatus.completed, actor_id, "Numeric target reached")
            return
    if goal.status == GoalStatus.not_started and (has_work or any_moved):
        set_goal_status(db, goal, GoalStatus.in_progress, actor_id, "Work recorded")
