"""SQLAlchemy models.

Enum-like columns are stored as plain strings (validated by the StrEnums below)
so the schema stays portable between SQLite (local dev) and PostgreSQL.
"""

from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.employee, index=True)
    department: Mapped[str | None] = mapped_column(String(120))
    job_title: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # {"daily_reminder": true, "deadlines": true, "blockers": true, "reports": true}
    notification_prefs: Mapped[dict] = mapped_column(JSON, default=dict)


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    department: Mapped[str | None] = mapped_column(String(120))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)

    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id])
    members: Mapped[list["TeamMember"]] = relationship(back_populates="team", cascade="all, delete-orphan")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class WeeklyGoal(TimestampMixin, Base):
    __tablename__ = "weekly_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    project: Mapped[str | None] = mapped_column(String(120), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    week_end: Mapped[date] = mapped_column(Date)
    expected_outcome: Mapped[str | None] = mapped_column(Text)
    success_criteria: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default=Priority.medium)
    start_date: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    original_deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=GoalStatus.not_started, index=True)
    target_type: Mapped[str] = mapped_column(String(20), default=TargetType.tasks)
    target_value: Mapped[float | None] = mapped_column(Float)
    current_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(40))
    dependencies: Mapped[str | None] = mapped_column(Text)
    blockers: Mapped[str | None] = mapped_column(Text)
    carried_from_goal_id: Mapped[int | None] = mapped_column(ForeignKey("weekly_goals.id"))
    carry_forward_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    team: Mapped[Team | None] = relationship()
    tasks: Mapped[list["Task"]] = relationship(back_populates="goal", order_by="Task.id")

    @property
    def code(self) -> str:
        return f"G-{self.id}"


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("weekly_goals.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    project: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.not_started, index=True)
    priority: Mapped[str] = mapped_column(String(20), default=Priority.medium)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    due_date: Mapped[date | None] = mapped_column(Date)
    is_unplanned: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    carried_from_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    goal: Mapped[WeeklyGoal | None] = relationship(back_populates="tasks")
    owner: Mapped[User] = relationship(foreign_keys=[owner_id])

    @property
    def code(self) -> str:
        return f"T-{self.id}"


class TaskStatusHistory(Base):
    __tablename__ = "task_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    work_log_item_id: Mapped[int | None] = mapped_column(ForeignKey("work_log_items.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoalStatusHistory(Base):
    __tablename__ = "goal_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("weekly_goals.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyWorkLog(TimestampMixin, Base):
    """One submitted update. The original text is never modified."""

    __tablename__ = "daily_work_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    input_method: Mapped[str] = mapped_column(String(20))  # paste | chat
    raw_text: Mapped[str] = mapped_column(Text)
    raw_text_hash: Mapped[str] = mapped_column(String(64), index=True)
    chat_messages: Mapped[list] = mapped_column(JSON, default=list)
    parse_mode: Mapped[str] = mapped_column(String(20), default="ai")  # ai | fallback
    parsed_draft: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=LogStatus.draft, index=True)
    total_hours: Mapped[float | None] = mapped_column(Float)
    blockers: Mapped[list] = mapped_column(JSON, default=list)
    next_steps: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    employee: Mapped[User] = relationship()
    items: Mapped[list["WorkLogItem"]] = relationship(back_populates="work_log", order_by="WorkLogItem.id")


class WorkLogItem(TimestampMixin, Base):
    __tablename__ = "work_log_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_log_id: Mapped[int] = mapped_column(ForeignKey("daily_work_logs.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("weekly_goals.id"), index=True)
    is_unplanned: Mapped[bool] = mapped_column(Boolean, default=False)
    project: Mapped[str | None] = mapped_column(String(120))
    task_title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=ItemStatus.in_progress)
    kind: Mapped[str] = mapped_column(String(20), default=ItemKind.activity)
    evidence: Mapped[str | None] = mapped_column(Text)
    hours: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    match_method: Mapped[str | None] = mapped_column(String(20))

    work_log: Mapped[DailyWorkLog] = relationship(back_populates="items")
    task: Mapped[Task | None] = relationship()
    goal: Mapped[WeeklyGoal | None] = relationship()


class WeeklyReport(TimestampMixin, Base):
    __tablename__ = "weekly_reports"
    __table_args__ = (UniqueConstraint("report_type", "employee_id", "team_id", "week_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_type: Mapped[str] = mapped_column(String(20))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    week_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=ReportStatus.draft, index=True)
    generation_mode: Mapped[str] = mapped_column(String(20), default="ai")
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_warnings: Mapped[list] = mapped_column(JSON, default=list)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)

    employee: Mapped[User | None] = relationship(foreign_keys=[employee_id])
    team: Mapped[Team | None] = relationship()
    reviews: Mapped[list["ReportReview"]] = relationship(back_populates="report", order_by="ReportReview.id")


class ReportReview(Base):
    __tablename__ = "report_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("weekly_reports.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))  # generate | edit | submit | approve | return
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[WeeklyReport] = relationship(back_populates="reviews")
    reviewer: Mapped[User] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(255))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TimeOff(Base):
    """Leave for one employee, or an organization holiday when user_id is null."""

    __tablename__ = "time_off"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrgSettings(TimestampMixin, Base):
    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_name: Mapped[str] = mapped_column(String(120), default="My Organization")
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Kolkata")
    # 0 = Monday ... 6 = Sunday
    working_days: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])
    daily_reminder_time: Mapped[str] = mapped_column(String(5), default="18:00")
    report_generation_day: Mapped[int] = mapped_column(Integer, default=4)  # Friday
    report_generation_time: Mapped[str] = mapped_column(String(5), default="19:00")
    min_daily_hours: Mapped[float | None] = mapped_column(Float, default=None)
    max_daily_hours: Mapped[float | None] = mapped_column(Float, default=12)
    managers_can_assign_goals: Mapped[bool] = mapped_column(Boolean, default=True)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_generate_reports: Mapped[bool] = mapped_column(Boolean, default=True)
