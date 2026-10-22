"""Data models, stored in MongoDB (one collection per class; see app/db.py).

Enum-like fields are stored as plain strings, validated by the StrEnums below.
Every record has an integer id, so codes like G-12 / T-40 stay stable.
"""

from datetime import date, datetime, timezone
from enum import StrEnum

from app.db import BelongsTo, Doc, HasMany, factory


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(StrEnum):
    admin = "admin"
    manager = "manager"
    employee = "employee"


class GoalStatus(StrEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    blocked = "blocked"
    completed = "completed"
    deferred = "deferred"
    cancelled = "cancelled"


class TargetType(StrEnum):
    tasks = "tasks"  # progress = completed task weight / total task weight
    number = "number"  # progress = current_value / target_value
    boolean = "boolean"  # progress = 100 only when the goal is marked completed


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TaskStatus(StrEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    blocked = "blocked"
    completed = "completed"
    cancelled = "cancelled"


class ItemStatus(StrEnum):
    """Status of a single reported work item, as stated by the employee."""

    in_progress = "in_progress"
    completed = "completed"
    blocked = "blocked"


class ItemKind(StrEnum):
    activity = "activity"  # work performed ("worked on", "tested", "reviewed")
    outcome = "outcome"  # an achieved deliverable ("deployed", "fixed", "shipped")


class LogStatus(StrEnum):
    draft = "draft"
    confirmed = "confirmed"
    discarded = "discarded"


class ReportType(StrEnum):
    employee = "employee"
    team = "team"


class ReportStatus(StrEnum):
    draft = "draft"
    submitted = "submitted"
    returned = "returned"
    approved = "approved"


class TimestampMixin:
    __onupdate__ = ("updated_at",)

    created_at: datetime = factory(utcnow)
    updated_at: datetime = factory(utcnow)


class User(TimestampMixin, Doc):
    __collection__ = "users"

    email: str = None  # stored lowercase, unique
    full_name: str = None
    password_hash: str = None
    role: str = Role.employee
    department: str | None = None
    job_title: str | None = None
    is_active: bool = True
    # {"daily_reminder": true, "deadlines": true, "blockers": true, "reports": true}
    notification_prefs: dict = factory(dict)


class Team(TimestampMixin, Doc):
    __collection__ = "teams"

    name: str = None  # unique
    department: str | None = None
    manager_id: int | None = None

    manager = BelongsTo("User", "manager_id")
    members = HasMany("TeamMember", "team_id", delete_orphan=True)


class TeamMember(Doc):
    __collection__ = "team_members"  # unique (team_id, user_id)

    team_id: int = None
    user_id: int = None
    created_at: datetime = factory(utcnow)

    team = BelongsTo("Team", "team_id")
    user = BelongsTo("User", "user_id")


class WeeklyGoal(TimestampMixin, Doc):
    __collection__ = "weekly_goals"

    title: str = None
    description: str | None = None
    owner_id: int = None
    team_id: int | None = None
    project: str | None = None
    week_start: date = None
    week_end: date = None
    expected_outcome: str | None = None
    success_criteria: str | None = None
    priority: str = Priority.medium
    start_date: date | None = None
    deadline: date | None = None
    original_deadline: date | None = None
    status: str = GoalStatus.not_started
    target_type: str = TargetType.tasks
    target_value: float | None = None
    current_value: float | None = None
    unit: str | None = None
    dependencies: str | None = None
    blockers: str | None = None
    carried_from_goal_id: int | None = None
    carry_forward_reason: str | None = None
    reviewed_at: datetime | None = None
    created_by_id: int | None = None

    owner = BelongsTo("User", "owner_id")
    team = BelongsTo("Team", "team_id")
    tasks = HasMany("Task", "goal_id")

    @property
    def code(self) -> str:
        return f"G-{self.id}"


class Task(TimestampMixin, Doc):
    __collection__ = "tasks"

    goal_id: int | None = None
    owner_id: int = None
    title: str = None
    description: str | None = None
    project: str | None = None
    status: str = TaskStatus.not_started
    priority: str = Priority.medium
    weight: int = 1
    due_date: date | None = None
    is_unplanned: bool = False
    completed_at: datetime | None = None
    carried_from_task_id: int | None = None
    created_by_id: int | None = None

    goal = BelongsTo("WeeklyGoal", "goal_id")
    owner = BelongsTo("User", "owner_id")

    @property
    def code(self) -> str:
        return f"T-{self.id}"


class TaskStatusHistory(Doc):
    __collection__ = "task_status_history"

    task_id: int = None
    from_status: str | None = None
    to_status: str = None
    changed_by_id: int | None = None
    work_log_item_id: int | None = None
    reason: str | None = None
    created_at: datetime = factory(utcnow)


class GoalStatusHistory(Doc):
    __collection__ = "goal_status_history"

    goal_id: int = None
    from_status: str | None = None
    to_status: str = None
    changed_by_id: int | None = None
    reason: str | None = None
    created_at: datetime = factory(utcnow)


class DailyWorkLog(TimestampMixin, Doc):
    """One submitted update. The original text is never modified."""

    __collection__ = "daily_work_logs"

    employee_id: int = None
    report_date: date = None
    input_method: str = None  # paste | chat
    raw_text: str = None
    raw_text_hash: str = None
    chat_messages: list = factory(list)
    parse_mode: str = "ai"  # ai | fallback
    parsed_draft: dict = factory(dict)
    status: str = LogStatus.draft
    total_hours: float | None = None
    blockers: list = factory(list)
    next_steps: list = factory(list)
    confirmed_at: datetime | None = None

    employee = BelongsTo("User", "employee_id")
    items = HasMany("WorkLogItem", "work_log_id")


class WorkLogItem(TimestampMixin, Doc):
    __collection__ = "work_log_items"

    work_log_id: int = None
    employee_id: int = None
    report_date: date = None
    task_id: int | None = None
    goal_id: int | None = None
    is_unplanned: bool = False
    project: str | None = None
    task_title: str = None
    description: str | None = None
    status: str = ItemStatus.in_progress
    kind: str = ItemKind.activity
    evidence: str | None = None
    hours: float | None = None
    confidence: float | None = None
    match_method: str | None = None

    work_log = BelongsTo("DailyWorkLog", "work_log_id")
    task = BelongsTo("Task", "task_id")
    goal = BelongsTo("WeeklyGoal", "goal_id")


class WeeklyReport(TimestampMixin, Doc):
    __collection__ = "weekly_reports"  # unique (report_type, employee_id, team_id, week_start)

    report_type: str = None
    employee_id: int | None = None
    team_id: int | None = None
    week_start: date = None
    week_end: date = None
    status: str = ReportStatus.draft
    generation_mode: str = "ai"
    facts: dict = factory(dict)
    ai_summary: dict = factory(dict)
    validation_warnings: list = factory(list)
    content_markdown: str = ""
    edited_by_human: bool = False
    generated_by_id: int | None = None
    approved_by_id: int | None = None
    approved_at: datetime | None = None
    version: int = 1

    employee = BelongsTo("User", "employee_id")
    team = BelongsTo("Team", "team_id")
    reviews = HasMany("ReportReview", "report_id")


class ReportReview(Doc):
    __collection__ = "report_reviews"

    report_id: int = None
    reviewer_id: int = None
    action: str = None  # generate | edit | submit | approve | return
    comment: str | None = None
    created_at: datetime = factory(utcnow)

    report = BelongsTo("WeeklyReport", "report_id")
    reviewer = BelongsTo("User", "reviewer_id")


class Notification(Doc):
    __collection__ = "notifications"
    __ignore_duplicates__ = True  # dedupe_key is unique: a concurrent duplicate is simply not stored

    user_id: int = None
    type: str = None
    title: str = None
    body: str | None = None
    link: str | None = None
    dedupe_key: str = None
    read_at: datetime | None = None
    created_at: datetime = factory(utcnow)


class AuditLog(Doc):
    __collection__ = "audit_logs"

    actor_id: int | None = None
    action: str = None
    entity_type: str = None
    entity_id: int | None = None
    before: dict | None = None
    after: dict | None = None
    created_at: datetime = factory(utcnow)


class TimeOff(Doc):
    """Leave for one employee, or an organization holiday when user_id is null."""

    __collection__ = "time_off"

    user_id: int | None = None
    day: date = None
    reason: str | None = None
    created_at: datetime = factory(utcnow)


class OrgSettings(TimestampMixin, Doc):
    """Single document with id 1."""

    __collection__ = "org_settings"
    __ignore_duplicates__ = True  # two first requests may both create the defaults

    org_name: str = "My Organization"
    timezone: str = "Asia/Kolkata"
    # 0 = Monday ... 6 = Sunday
    working_days: list = factory(lambda: [0, 1, 2, 3, 4])
    daily_reminder_time: str = "18:00"
    report_generation_day: int = 4  # Friday
    report_generation_time: str = "19:00"
    min_daily_hours: float | None = None
    max_daily_hours: float | None = 12
    managers_can_assign_goals: bool = True
    reminders_enabled: bool = True
    auto_generate_reports: bool = True
