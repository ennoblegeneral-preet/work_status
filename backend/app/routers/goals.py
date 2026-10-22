from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.db import Session, get_db
from app.deps import can_manage_employee, ensure_can_view_employee, get_current_user, require_manager_or_admin, visible_employee_ids
from app.models import (
    GoalStatus,
    GoalStatusHistory,
    Role,
    Task,
    TaskStatus,
    TaskStatusHistory,
    TeamMember,
    User,
    WeeklyGoal,
    WorkLogItem,
)
from app.schemas import (
    GoalBulkCreate,
    GoalCreate,
    GoalOut,
    GoalReviewDecision,
    GoalUpdate,
    Page,
    StatusHistoryOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    WorkLogItemOut,
)
from app.services.goals import change_task_status, find_goals, goal_out, review_goal, unfinished_goals
from app.services.notifications import notify
from app.services.progress import set_goal_status, sync_goal_status_from_work
from app.utils import audit, get_org_settings, org_today, snapshot, week_bounds

router = APIRouter(tags=["goals & tasks"])

GOAL_FIELDS = [
    "title", "description", "project", "expected_outcome", "success_criteria", "priority", "start_date",
    "deadline", "target_value", "current_value", "unit", "dependencies", "blockers", "status",
]
OWNER_EDITABLE = {"current_value", "blockers", "status", "reason"}
OWNER_STATUSES = {GoalStatus.in_progress, GoalStatus.blocked, GoalStatus.completed}


def _ensure_can_assign(db: Session, actor: User, owner_id: int) -> None:
    owner = db.get(User, owner_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Goal owner not found or inactive")
    if actor.role == Role.admin:
        return
    if actor.role == Role.manager and get_org_settings(db).managers_can_assign_goals and can_manage_employee(db, actor, owner_id):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot assign goals to this employee")


def _create_goal(db: Session, actor: User, data: GoalCreate) -> WeeklyGoal:
    _ensure_can_assign(db, actor, data.owner_id)
    ws, we = week_bounds(data.week_start)
    membership = db.first(TeamMember, {"user_id": data.owner_id})
    team_id = data.team_id or (membership.team_id if membership else None)
    if data.target_type == "number" and not data.target_value:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A numeric goal needs a target value")
    if data.deadline and data.start_date and data.deadline < data.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Deadline cannot be before the start date")
    g = WeeklyGoal(
        **data.model_dump(exclude={"tasks", "week_start", "team_id"}),
        team_id=team_id,
        week_start=ws,
        week_end=we,
        original_deadline=data.deadline,
        status=GoalStatus.not_started,
        created_by_id=actor.id,
    )
    if g.target_type == "number":
        g.current_value = 0
    db.add(g)
    for t in data.tasks:
        db.add(Task(goal_id=g.id, owner_id=g.owner_id, project=g.project, created_by_id=actor.id, **t.model_dump()))
    audit(db, actor.id, "create_goal", "weekly_goal", g.id, after=data.model_dump(mode="json"))
    notify(db, g.owner, "goal_assigned", f"New goal: {g.title}", f"goal_assigned:{g.id}",
           f"Week of {ws.strftime('%d %b')}", f"/goals/{g.id}")
    return g


def _get_goal(db: Session, user: User, goal_id: int) -> WeeklyGoal:
    g = db.get(WeeklyGoal, goal_id)
    if g is None:
        raise HTTPException(404, "Not found")
    ensure_can_view_employee(db, user, g.owner_id)
    return g


@router.get("/goals", response_model=Page[GoalOut])
def list_goals(
    week_start: date | None = None,
    owner_id: int | None = None,
    team_id: int | None = None,
    status_: GoalStatus | None = Query(None, alias="status"),
    project: str | None = None,
    page: int = 1,
    page_size: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page, page_size = max(1, page), min(max(1, page_size), 300)
    f: dict = {}
    ids = visible_employee_ids(db, user)
    if ids is not None:
        f["owner_id"] = {"$in": sorted(ids)}
    if week_start:
        f["week_start"] = week_bounds(week_start)[0]
    if owner_id:
        f["$and"] = [{"owner_id": owner_id}]
    if team_id:
        f["team_id"] = team_id
    if status_:
        f["status"] = status_
    if project:
        f["project"] = project
    total = db.count(WeeklyGoal, f)
    rows = find_goals(
        db, f, sort=[("week_start", -1), ("owner_id", 1), ("id", 1)], skip=(page - 1) * page_size, limit=page_size
    )
    today, wd = org_today(db), get_org_settings(db).working_days
    return Page(items=[goal_out(db, g, today, wd) for g in rows], total=total, page=page, page_size=page_size)


@router.post("/goals", response_model=GoalOut, status_code=201)
def create_goal(data: GoalCreate, actor: User = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    g = _create_goal(db, actor, data)
    db.commit()
    return goal_out(db, g)


@router.post("/goals/bulk", response_model=list[GoalOut], status_code=201)
def bulk_create_goals(data: GoalBulkCreate, actor: User = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    created = [_create_goal(db, actor, g) for g in data.goals]  # all-or-nothing
    db.commit()
    return [goal_out(db, g) for g in created]


@router.get("/goals/review", response_model=list[GoalOut])
def goals_to_review(
    week_start: date | None = None, user: User = Depends(require_manager_or_admin), db: Session = Depends(get_db)
):
    ws = week_bounds(week_start or org_today(db))[0]
    ids = visible_employee_ids(db, user)
    if ids is not None:
        ids = {i for i in ids if i != user.id}
    return [goal_out(db, g) for g in unfinished_goals(db, ws, ids)]


@router.get("/goals/{goal_id}", response_model=GoalOut)
def get_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return goal_out(db, _get_goal(db, user, goal_id))


@router.patch("/goals/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, data: GoalUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = _get_goal(db, user, goal_id)
    changes = data.model_dump(exclude_unset=True)
    is_manager = can_manage_employee(db, user, g.owner_id)
    if not is_manager:
        if g.owner_id != user.id or set(changes) - OWNER_EDITABLE:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only update status, progress value and blockers of your own goals")
        if "status" in changes and changes["status"] not in OWNER_STATUSES:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can defer or cancel a goal")
    before = snapshot(g, GOAL_FIELDS)
    new_status = changes.pop("status", None)
    reason = changes.pop("reason", None)
    if "deadline" in changes and g.original_deadline is None:
        g.original_deadline = g.deadline
    for k, v in changes.items():
        setattr(g, k, v)
    if new_status:
        if new_status == GoalStatus.completed and g.target_type == "tasks":
            open_tasks = [t for t in g.tasks if t.status not in (TaskStatus.completed, TaskStatus.cancelled)]
            if open_tasks and not reason:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"{len(open_tasks)} task(s) are still open. Give a reason to mark this goal completed anyway.",
                )
        set_goal_status(db, g, new_status, user.id, reason)
    elif "current_value" in changes:
        sync_goal_status_from_work(db, g, user.id)
    audit(db, user.id, "update_goal", "weekly_goal", g.id, before=before, after=snapshot(g, GOAL_FIELDS))
    db.commit()
    return goal_out(db, _get_goal(db, user, goal_id))


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, user: User = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    g = _get_goal(db, user, goal_id)
    if not can_manage_employee(db, user, g.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot manage this employee")
    if db.exists(WorkLogItem, {"goal_id": g.id}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Work has been logged against this goal. Cancel it instead.")
    audit(db, user.id, "delete_goal", "weekly_goal", g.id, before=snapshot(g, GOAL_FIELDS))
    for t in g.tasks:
        db.delete(t)
    db.delete(g)
    db.commit()


@router.post("/goals/{goal_id}/review", response_model=GoalOut | None)
def review(goal_id: int, data: GoalReviewDecision, user: User = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    g = _get_goal(db, user, goal_id)
    if not can_manage_employee(db, user, g.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot manage this employee")
    new_goal = review_goal(db, g, data, user.id)
    db.commit()
    return goal_out(db, new_goal) if new_goal else None


@router.get("/goals/{goal_id}/history")
def goal_history(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = _get_goal(db, user, goal_id)
    goal_hist = db.find(GoalStatusHistory, {"goal_id": g.id})
    task_hist = db.find(TaskStatusHistory, {"task_id": {"$in": [t.id for t in g.tasks]}})
    items = db.find(WorkLogItem, {"goal_id": g.id}, sort=[("report_date", 1), ("id", 1)])
    return {
        "goal_status": [StatusHistoryOut.model_validate(h) for h in goal_hist],
        "task_status": [StatusHistoryOut.model_validate(h).model_dump() | {"task_id": h.task_id} for h in task_hist],
        "work_items": [WorkLogItemOut.model_validate(i) for i in items],
    }


# ---------------------------------------------------------------- tasks


def _get_task(db: Session, user: User, task_id: int) -> Task:
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "Not found")
    ensure_can_view_employee(db, user, t.owner_id)
    return t


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goal = None
    if data.goal_id:
        goal = _get_goal(db, user, data.goal_id)
        owner_id = goal.owner_id
    else:
        owner_id = data.owner_id or user.id
    if owner_id != user.id and not can_manage_employee(db, user, owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot add tasks for this employee")
    t = Task(
        goal_id=goal.id if goal else None,
        owner_id=owner_id,
        title=data.title,
        description=data.description,
        project=data.project or (goal.project if goal else None),
        weight=data.weight,
        due_date=data.due_date,
        priority=data.priority,
        is_unplanned=goal is None,
        created_by_id=user.id,
    )
    db.add(t)
    if goal is not None and goal.status == GoalStatus.completed:
        sync_goal_status_from_work(db, goal, user.id)
    audit(db, user.id, "create_task", "task", t.id, after=data.model_dump(mode="json"))
    db.commit()
    return t


@router.get("/tasks/{task_id}")
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _get_task(db, user, task_id)
    hist = db.find(TaskStatusHistory, {"task_id": t.id})
    items = db.find(WorkLogItem, {"task_id": t.id}, sort=[("report_date", 1), ("id", 1)])
    return {
        "task": TaskOut.model_validate(t),
        "goal": {"id": t.goal.id, "code": t.goal.code, "title": t.goal.title} if t.goal else None,
        "history": [StatusHistoryOut.model_validate(h) for h in hist],
        "work_items": [WorkLogItemOut.model_validate(i) for i in items],
    }


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, data: TaskUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _get_task(db, user, task_id)
    if t.owner_id != user.id and not can_manage_employee(db, user, t.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot edit this task")
    fields = ["title", "description", "weight", "due_date", "priority", "status"]
    before = snapshot(t, fields)
    changes = data.model_dump(exclude_unset=True)
    new_status = changes.pop("status", None)
    reason = changes.pop("reason", None)
    for k, v in changes.items():
        setattr(t, k, v)
    if new_status:
        change_task_status(db, t, new_status, user.id, reason)
    elif "weight" in changes and t.goal:
        sync_goal_status_from_work(db, t.goal, user.id)
    audit(db, user.id, "update_task", "task", t.id, before=before, after=snapshot(t, fields))
    db.commit()
    return t


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _get_task(db, user, task_id)
    if t.owner_id != user.id and not can_manage_employee(db, user, t.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot delete this task")
    if db.exists(WorkLogItem, {"task_id": t.id}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Work has been logged on this task. Cancel it instead.")
    goal = t.goal
    audit(db, user.id, "delete_task", "task", t.id, before=snapshot(t, ["title", "goal_id", "status"]))
    db.delete(t)
    if goal:
        sync_goal_status_from_work(db, goal, user.id)
    db.commit()
