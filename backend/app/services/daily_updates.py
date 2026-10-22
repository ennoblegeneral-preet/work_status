"""Daily work update workflow: parse -> (chat) -> review -> confirm.

Nothing is written to work-log items, tasks or goals until the employee confirms.
The original text is stored untouched on the log; the AI draft and the confirmed
version are both kept for traceability.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.fallback import parse_text
from app.ai.provider import LLMError, ParseContext, get_provider
from app.models import (
    DailyWorkLog,
    ItemStatus,
    LogStatus,
    Task,
    TaskStatus,
    User,
    WeeklyGoal,
    WorkLogItem,
)
from app.schemas import Draft, DraftItem, DraftOut, ParseRequest, WorkLogItemUpdate
from app.services.goals import employee_week_goals
from app.services.matching import Matcher, similarity
from app.services.notifications import managers_of, notify
from app.services.progress import set_task_status, sync_goal_status_from_work
from app.utils import audit, get_org_settings, org_today, text_hash

FALLBACK_NOTE = "AI is not configured, so a basic rule-based parser was used. Please check every item before saving."


# ---------------------------------------------------------------- context


def _open_extra_tasks(db: Session, employee_id: int) -> list[Task]:
    """Open tasks not attached to a goal (previously recorded additional work)."""
    return list(
        db.scalars(
            select(Task).where(
                Task.owner_id == employee_id,
                Task.goal_id.is_(None),
                Task.status.not_in([TaskStatus.completed, TaskStatus.cancelled]),
            )
        )
    )


def goal_options(goals: list[WeeklyGoal], extra: list[Task]) -> list[dict]:
    opts = [
        {
            "id": g.id,
            "code": g.code,
            "title": g.title,
            "project": g.project,
            "status": g.status,
            "tasks": [{"id": t.id, "code": t.code, "title": t.title, "status": t.status} for t in g.tasks],
        }
        for g in goals
    ]
    if extra:
        opts.append(
            {
                "id": None,
                "code": None,
                "title": "Additional work (no goal)",
                "project": None,
                "status": None,
                "tasks": [{"id": t.id, "code": t.code, "title": t.title, "status": t.status} for t in extra],
            }
        )
    return opts


def _context(db: Session, employee: User, report_date: date, text: str, chat: list, current: list) -> tuple:
    goals = employee_week_goals(db, employee.id, report_date, include_closed=False)
    extra = _open_extra_tasks(db, employee.id)
    ctx = ParseContext(
        employee_name=employee.full_name,
        report_date=report_date,
        today=org_today(db),
        text=text,
        goals=[
            {
                "code": g.code,
                "title": g.title,
                "project": g.project,
                "expected_outcome": g.expected_outcome,
                "status": g.status,
                "tasks": [{"code": t.code, "title": t.title, "status": t.status} for t in g.tasks],
            }
            for g in goals
        ],
        extra_tasks=[{"code": t.code, "title": t.title, "status": t.status} for t in extra],
        chat=chat,
        current_items=current,
    )
    return ctx, goals, extra


# ---------------------------------------------------------------- parsing


def _resolve_date(requested: date | None, parsed: str | None, today: date, warnings: list[str]) -> date:
    chosen = requested or today
    if parsed:
        try:
            pd = date.fromisoformat(parsed)
        except ValueError:
            pd = None
        if pd and pd != chosen:
            if requested is None and today - timedelta(days=30) <= pd <= today:
                warnings.append(f"Your update mentions {pd.isoformat()}, so that date was used. Change it if needed.")
                chosen = pd
            else:
                warnings.append(f"Your update mentions {parsed}, but the report date is {chosen.isoformat()}.")
    return chosen


def run_parse(
    db: Session,
    employee: User,
    text: str,
    requested_date: date | None,
    chat: list | None = None,
    current_items: list | None = None,
) -> tuple[Draft, str]:
    today = org_today(db)
    base_date = requested_date or today
    ctx, goals, extra = _context(db, employee, base_date, text, chat or [], current_items or [])
    provider = get_provider()
    warnings: list[str] = []
    try:
        parsed = provider.parse_update(ctx)
        mode = provider.mode
        if mode == "fallback":
            warnings.append(FALLBACK_NOTE)
    except LLMError as exc:
        parsed = parse_text(ctx)
        mode = "fallback"
        warnings.append(f"AI parsing was unavailable ({exc}). A basic parser was used; please check every item.")

    report_date = _resolve_date(requested_date, parsed.report_date, today, warnings)
    if report_date != base_date:
        # Goals of a different week apply; rebuild the matcher for that week.
        ctx, goals, extra = _context(db, employee, report_date, text, chat or [], current_items or [])

    matcher = Matcher(goals, extra)
    existing = list(
        db.scalars(
            select(WorkLogItem)
            .join(DailyWorkLog)
            .where(
                WorkLogItem.employee_id == employee.id,
                WorkLogItem.report_date == report_date,
                DailyWorkLog.status == LogStatus.confirmed,
            )
        )
    )
    goal_by_id = {g.id: g for g in goals}
    items: list[DraftItem] = []
    for it in parsed.work_items:
        blob = " ".join(filter(None, [it.task_title, it.evidence, it.description]))
        m = matcher.match(it.task_title, blob, it.goal_ref, it.task_ref, it.confidence)
        goal = goal_by_id.get(m.goal_id) if m.goal_id else None
        dup = next(
            (e for e in existing if similarity(e.task_title, it.task_title) >= 0.9 or (
                it.evidence and e.evidence and similarity(e.evidence, it.evidence) >= 0.9)),
            None,
        )
        note = m.note
        if dup:
            note = f"Looks like a duplicate of work already saved for this date ({dup.task_title})"
        items.append(
            DraftItem(
                task_title=it.task_title[:255],
                description=it.description,
                project=it.project or parsed.project or (goal.project if goal else None),
                goal_id=m.goal_id,
                task_id=m.task_id,
                create_task=m.create_task,
                is_unplanned=m.is_unplanned,
                status=it.status,
                kind=it.kind,
                evidence=it.evidence,
                hours=it.hours,
                confidence=m.confidence,
                match_method=m.method,
                match_note=note,
                requires_confirmation=m.requires_confirmation or mode == "fallback" or dup is not None,
                duplicate_of_item_id=dup.id if dup else None,
            )
        )

    if not items:
        warnings.append("No work items were found in this update. Add details or enter items manually.")
    s = get_org_settings(db)
    if parsed.total_hours is not None:
        if s.max_daily_hours and parsed.total_hours > s.max_daily_hours:
            warnings.append(f"Reported {parsed.total_hours}h is above the daily maximum of {s.max_daily_hours}h.")
        if s.min_daily_hours and parsed.total_hours < s.min_daily_hours:
            warnings.append(f"Reported {parsed.total_hours}h is below the expected minimum of {s.min_daily_hours}h.")

    draft = Draft(
        report_date=report_date,
        project=parsed.project,
        items=items,
        total_hours=parsed.total_hours,
        blockers=parsed.blockers,
        next_steps=parsed.next_steps,
        clarification_question=parsed.clarification_question,
        needs_confirmation=any(i.requires_confirmation for i in items) or bool(parsed.clarification_question),
        warnings=warnings,
    )
    return draft, mode


def _assistant_reply(draft: Draft) -> str:
    if draft.clarification_question:
        return draft.clarification_question
    n = len(draft.items)
    if not n:
        return "I couldn't find any work items yet. What did you work on?"
    unsure = sum(1 for i in draft.items if i.requires_confirmation)
    msg = f"I found {n} work item{'s' if n != 1 else ''}."
    if unsure:
        msg += f" Please check the {unsure} highlighted item{'s' if unsure != 1 else ''}."
    return msg + " Review them on the right and save when ready, or tell me what to change."


def _confirmed_today(db: Session, employee_id: int, report_date: date, exclude_id: int | None = None) -> int:
    q = select(DailyWorkLog.id).where(
        DailyWorkLog.employee_id == employee_id,
        DailyWorkLog.report_date == report_date,
        DailyWorkLog.status == LogStatus.confirmed,
    )
    if exclude_id:
        q = q.where(DailyWorkLog.id != exclude_id)
    return len(list(db.scalars(q)))


def draft_out(db: Session, log: DailyWorkLog) -> DraftOut:
    current = Draft.model_validate(log.parsed_draft.get("current") or {"report_date": log.report_date})
    goals = employee_week_goals(db, log.employee_id, current.report_date, include_closed=False)
    extra = _open_extra_tasks(db, log.employee_id)
    return DraftOut(
        log_id=log.id,
        status=log.status,
        parse_mode=log.parse_mode,
        raw_text=log.raw_text,
        chat_messages=log.chat_messages or [],
        draft=current,
        other_updates_today=_confirmed_today(db, log.employee_id, current.report_date, log.id),
        goals=goal_options(goals, extra),
    )


def create_draft(db: Session, employee: User, req: ParseRequest) -> DailyWorkLog:
    today = org_today(db)
    if req.report_date and req.report_date > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The report date cannot be in the future")
    h = text_hash(req.text)
    dup = db.scalar(
        select(DailyWorkLog).where(
            DailyWorkLog.employee_id == employee.id,
            DailyWorkLog.raw_text_hash == h,
            DailyWorkLog.status == LogStatus.confirmed,
        )
    )
    if dup:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This exact update was already saved for {dup.report_date.isoformat()}.",
        )
    draft, mode = run_parse(db, employee, req.text, req.report_date)
    chat = [{"role": "assistant", "content": _assistant_reply(draft)}] if req.input_method == "chat" else []
    log = DailyWorkLog(
        employee_id=employee.id,
        report_date=draft.report_date,
        input_method=req.input_method,
        raw_text=req.text,
        raw_text_hash=h,
        chat_messages=chat,
        parse_mode=mode,
        parsed_draft={"ai_original": draft.model_dump(mode="json"), "current": draft.model_dump(mode="json")},
        status=LogStatus.draft,
    )
    db.add(log)
    db.flush()
    audit(db, employee.id, "create_draft", "daily_work_log", log.id)
    return log


def chat_turn(db: Session, log: DailyWorkLog, employee: User, message: str) -> DailyWorkLog:
    if log.status != LogStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "This update has already been saved")
    chat = list(log.chat_messages or []) + [{"role": "user", "content": message}]
    current = (log.parsed_draft.get("current") or {}).get("items", [])
    slim = [
        {k: i.get(k) for k in ("task_title", "status", "kind", "hours", "project", "evidence")}
        | {"goal_ref": f"G-{i['goal_id']}" if i.get("goal_id") else None,
           "task_ref": f"T-{i['task_id']}" if i.get("task_id") else None}
        for i in current
    ]
    report_date = date.fromisoformat((log.parsed_draft.get("current") or {}).get("report_date") or log.report_date.isoformat())
    draft, mode = run_parse(db, employee, log.raw_text, report_date, chat=chat, current_items=slim)
    chat.append({"role": "assistant", "content": _assistant_reply(draft)})
    log.chat_messages = chat
    log.parse_mode = mode
    log.report_date = draft.report_date
    log.parsed_draft = {**log.parsed_draft, "current": draft.model_dump(mode="json")}
    return log


def save_draft_edits(db: Session, log: DailyWorkLog, draft: Draft) -> DailyWorkLog:
    if log.status != LogStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "This update has already been saved")
    log.parsed_draft = {**log.parsed_draft, "current": draft.model_dump(mode="json")}
    log.report_date = draft.report_date
    return log


# ---------------------------------------------------------------- confirmation


def _validate_links(db: Session, employee_id: int, goal_id: int | None, task_id: int | None) -> tuple:
    goal = task = None
    if task_id is not None:
        task = db.get(Task, task_id)
        if task is None or task.owner_id != employee_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Task T-{task_id} is not one of your tasks")
        if task.goal_id:
            goal_id = task.goal_id
    if goal_id is not None:
        goal = db.get(WeeklyGoal, goal_id)
        if goal is None or goal.owner_id != employee_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Goal G-{goal_id} is not one of your goals")
    return goal, task


def _find_or_create_task(db: Session, employee: User, item: DraftItem, goal: WeeklyGoal | None) -> Task:
    if goal is not None:
        candidates = list(goal.tasks)
    else:
        candidates = _open_extra_tasks(db, employee.id)
    for t in candidates:
        if similarity(t.title, item.task_title) >= 0.82:
            return t
    task = Task(
        goal_id=goal.id if goal else None,
        owner_id=employee.id,
        title=item.task_title,
        description=item.description,
        project=item.project or (goal.project if goal else None),
        status=TaskStatus.not_started,
        is_unplanned=goal is None,
        created_by_id=employee.id,
    )
    db.add(task)
    db.flush()
    return task


def apply_item_to_task(db: Session, task: Task, item_status: str, actor_id: int, item_id: int) -> None:
    """Employee-confirmed item status drives the task status, never backwards from completed."""
    if item_status == ItemStatus.completed:
        set_task_status(db, task, TaskStatus.completed, actor_id, "Reported completed in daily update", item_id)
    elif item_status == ItemStatus.blocked:
        if task.status != TaskStatus.completed:
            set_task_status(db, task, TaskStatus.blocked, actor_id, "Reported blocked in daily update", item_id)
    elif task.status in (TaskStatus.not_started, TaskStatus.blocked):
        set_task_status(db, task, TaskStatus.in_progress, actor_id, "Work reported in daily update", item_id)


def confirm(db: Session, log: DailyWorkLog, employee: User, draft: Draft) -> DailyWorkLog:
    if log.status != LogStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "This update has already been saved or discarded")
    if draft.report_date > org_today(db):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The report date cannot be in the future")
    if not draft.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add at least one work item before saving")
    same = db.scalar(
        select(DailyWorkLog.id).where(
            DailyWorkLog.employee_id == employee.id,
            DailyWorkLog.raw_text_hash == log.raw_text_hash,
            DailyWorkLog.status == LogStatus.confirmed,
        )
    )
    if same:
        raise HTTPException(status.HTTP_409_CONFLICT, "This exact update was already saved")

    touched_goals: dict[int, WeeklyGoal] = {}
    for item in draft.items:
        goal, task = _validate_links(db, employee.id, item.goal_id, item.task_id)
        if task is None and (item.create_task or goal is not None):
            task = _find_or_create_task(db, employee, item, goal)
        wli = WorkLogItem(
            work_log_id=log.id,
            employee_id=employee.id,
            report_date=draft.report_date,
            task_id=task.id if task else None,
            goal_id=goal.id if goal else None,
            is_unplanned=goal is None,
            project=item.project or (goal.project if goal else None),
            task_title=item.task_title,
            description=item.description,
            status=item.status,
            kind=item.kind,
            evidence=item.evidence,
            hours=item.hours,
            confidence=item.confidence,
            match_method=item.match_method if (item.goal_id or item.task_id) else "none",
        )
        db.add(wli)
        db.flush()
        if task is not None:
            apply_item_to_task(db, task, item.status, employee.id, wli.id)
        if goal is not None:
            touched_goals[goal.id] = goal

    item_hours = [i.hours for i in draft.items]
    if draft.total_hours is not None:
        total = draft.total_hours
    elif item_hours and all(h is not None for h in item_hours):
        total = round(sum(item_hours), 2)
    else:
        total = None  # unknown - never estimated

    log.report_date = draft.report_date
    log.status = LogStatus.confirmed
    log.confirmed_at = datetime.now(timezone.utc)
    log.total_hours = total
    log.blockers = draft.blockers
    log.next_steps = draft.next_steps
    log.parsed_draft = {**log.parsed_draft, "confirmed": draft.model_dump(mode="json")}

    for g in touched_goals.values():
        sync_goal_status_from_work(db, g, employee.id)

    blocked_items = [i.task_title for i in draft.items if i.status == ItemStatus.blocked]
    if draft.blockers or blocked_items:
        body = "; ".join(draft.blockers + blocked_items)[:500]
        for m in managers_of(db, employee.id):
            notify(
                db, m, "blocker", f"{employee.full_name} reported a blocker",
                f"blocker:{log.id}:{m.id}", body, f"/team/history?employee={employee.id}",
            )
    audit(db, employee.id, "confirm_daily_log", "daily_work_log", log.id, after=draft.model_dump(mode="json"))
    return log


def update_item(db: Session, item: WorkLogItem, data: WorkLogItemUpdate, actor: User) -> WorkLogItem:
    before = {
        f: getattr(item, f)
        for f in ("task_title", "description", "project", "status", "kind", "hours", "goal_id", "task_id")
    }
    changes = data.model_dump(exclude_unset=True)
    if "goal_id" in changes or "task_id" in changes:
        goal, task = _validate_links(
            db, item.employee_id, changes.get("goal_id", item.goal_id), changes.get("task_id", item.task_id)
        )
        item.goal_id = goal.id if goal else None
        item.task_id = task.id if task else None
        item.is_unplanned = goal is None
        item.match_method = "manual"
    for f in ("task_title", "description", "project", "status", "kind", "hours"):
        if f in changes:
            setattr(item, f, changes[f])
    db.flush()
    if item.task is not None and ("status" in changes or "task_id" in changes):
        apply_item_to_task(db, item.task, item.status, actor.id, item.id)
    goal_ids = {before["goal_id"], item.goal_id} - {None}
    for gid in goal_ids:
        g = db.get(WeeklyGoal, gid)
        if g:
            sync_goal_status_from_work(db, g, actor.id)
    after = {f: getattr(item, f) for f in before}
    audit(db, actor.id, "edit_work_log_item", "work_log_item", item.id, before=before, after=after)
    return item
