"""Pydantic request/response models for the REST API."""

from datetime import date, datetime
import re
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.models import GoalStatus, ItemKind, ItemStatus, Priority, Role, TargetType, TaskStatus

T = TypeVar("T")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 255 or not _EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address")
    return v


# Accepts internal/company domains (e.g. name@corp.local) that strict validators reject.
Email = Annotated[str, AfterValidator(_email)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------- auth / users


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=200)


class UserBrief(ORM):
    id: int
    full_name: str
    email: str
    role: Role
    department: str | None = None


class UserOut(UserBrief):
    job_title: str | None = None
    is_active: bool
    notification_prefs: dict = {}
    team_ids: list[int] = []
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    email: Email
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=200)
    role: Role = Role.employee
    department: str | None = Field(default=None, max_length=120)
    job_title: str | None = Field(default=None, max_length=120)
    team_ids: list[int] = []


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: Role | None = None
    department: str | None = Field(default=None, max_length=120)
    job_title: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    team_ids: list[int] | None = None


class PreferencesUpdate(BaseModel):
    notification_prefs: dict[str, bool]


# ---------------------------------------------------------------- teams


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    manager_id: int | None = None
    member_ids: list[int] = []


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    department: str | None = None
    manager_id: int | None = None
    member_ids: list[int] | None = None


class TeamOut(ORM):
    id: int
    name: str
    department: str | None
    manager_id: int | None
    manager: UserBrief | None = None
    members: list[UserBrief] = []


# ---------------------------------------------------------------- goals / tasks


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    weight: int = Field(default=1, ge=1, le=100)
    due_date: date | None = None
    priority: Priority = Priority.medium


class TaskCreate(TaskIn):
    goal_id: int | None = None
    owner_id: int | None = None  # defaults to goal owner / current user
    project: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    weight: int | None = Field(default=None, ge=1, le=100)
    due_date: date | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    reason: str | None = Field(default=None, max_length=2000)


class TaskOut(ORM):
    id: int
    code: str
    goal_id: int | None
    owner_id: int
    title: str
    description: str | None
    project: str | None
    status: TaskStatus
    priority: Priority
    weight: int
    due_date: date | None
    is_unplanned: bool
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GoalBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project: str | None = Field(default=None, max_length=120)
    expected_outcome: str | None = None
    success_criteria: str | None = None
    priority: Priority = Priority.medium
    start_date: date | None = None
    deadline: date | None = None
    target_type: TargetType = TargetType.tasks
    target_value: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=40)
    dependencies: str | None = None


class GoalCreate(GoalBase):
    owner_id: int
    team_id: int | None = None
    week_start: date  # any date in the week; normalized to Monday
    tasks: list[TaskIn] = []


class GoalBulkCreate(BaseModel):
    goals: list[GoalCreate] = Field(min_length=1, max_length=200)


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    project: str | None = None
    expected_outcome: str | None = None
    success_criteria: str | None = None
    priority: Priority | None = None
    start_date: date | None = None
    deadline: date | None = None
    target_value: float | None = Field(default=None, gt=0)
    current_value: float | None = Field(default=None, ge=0)
    unit: str | None = None
    dependencies: str | None = None
    blockers: str | None = None
    status: GoalStatus | None = None
    reason: str | None = Field(default=None, max_length=2000)


class GoalOut(ORM):
    id: int
    code: str
    title: str
    description: str | None
    owner_id: int
    owner: UserBrief
    team_id: int | None
    project: str | None
    week_start: date
    week_end: date
    expected_outcome: str | None
    success_criteria: str | None
    priority: Priority
    start_date: date | None
    deadline: date | None
    original_deadline: date | None
    status: GoalStatus
    target_type: TargetType
    target_value: float | None
    current_value: float | None
    unit: str | None
    dependencies: str | None
    blockers: str | None
    carried_from_goal_id: int | None
    carry_forward_reason: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tasks: list[TaskOut] = []
    progress: float = 0
    health: str = "not_started"
    last_activity: date | None = None


class GoalReviewDecision(BaseModel):
    action: Literal["carry_forward", "complete", "defer", "cancel"]
    reason: str = Field(min_length=3, max_length=2000)
    new_deadline: date | None = None


class StatusHistoryOut(ORM):
    id: int
    from_status: str | None
    to_status: str
    changed_by_id: int | None
    reason: str | None
    created_at: datetime


# ---------------------------------------------------------------- daily updates


class ParseRequest(BaseModel):
    text: str = Field(min_length=3, max_length=20000)
    report_date: date | None = None
    input_method: Literal["paste", "chat"] = "paste"


class ChatMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class DraftItem(BaseModel):
    task_title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    project: str | None = Field(default=None, max_length=120)
    goal_id: int | None = None
    task_id: int | None = None
    create_task: bool = False
    is_unplanned: bool = False
    status: ItemStatus = ItemStatus.in_progress
    kind: ItemKind = ItemKind.activity
    evidence: str | None = Field(default=None, max_length=4000)
    hours: float | None = Field(default=None, ge=0, le=24)
    confidence: float | None = Field(default=None, ge=0, le=1)
    match_method: str | None = None
    match_note: str | None = None
    requires_confirmation: bool = False
    duplicate_of_item_id: int | None = None


class Draft(BaseModel):
    report_date: date
    project: str | None = None
    items: list[DraftItem] = Field(default=[], max_length=50)
    total_hours: float | None = Field(default=None, ge=0, le=24)
    blockers: list[str] = Field(default=[], max_length=30)
    next_steps: list[str] = Field(default=[], max_length=30)
    needs_confirmation: bool = False
    clarification_question: str | None = None
    warnings: list[str] = []

    @field_validator("blockers", "next_steps")
    @classmethod
    def _strip_empty(cls, v: list[str]) -> list[str]:
        return [s.strip()[:1000] for s in v if s and s.strip()]


class ConfirmIn(BaseModel):
    draft: Draft


class WorkLogItemOut(ORM):
    id: int
    report_date: date
    task_id: int | None
    goal_id: int | None
    is_unplanned: bool
    project: str | None
    task_title: str
    description: str | None
    status: ItemStatus
    kind: ItemKind
    evidence: str | None
    hours: float | None
    confidence: float | None
    match_method: str | None


class WorkLogItemUpdate(BaseModel):
    task_title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    project: str | None = None
    status: ItemStatus | None = None
    kind: ItemKind | None = None
    hours: float | None = Field(default=None, ge=0, le=24)
    goal_id: int | None = None
    task_id: int | None = None


class DailyLogOut(ORM):
    id: int
    employee_id: int
    employee: UserBrief
    report_date: date
    input_method: str
    raw_text: str
    chat_messages: list = []
    parse_mode: str
    status: str
    total_hours: float | None
    blockers: list = []
    next_steps: list = []
    confirmed_at: datetime | None
    created_at: datetime
    items: list[WorkLogItemOut] = []


class DraftOut(BaseModel):
    log_id: int
    status: str
    parse_mode: str
    raw_text: str
    chat_messages: list
    draft: Draft
    other_updates_today: int = 0
    goals: list[dict] = []  # lightweight goal/task options for the editor


# ---------------------------------------------------------------- reports


class GenerateReportIn(BaseModel):
    week_start: date
    employee_id: int | None = None
    team_id: int | None = None


class ReportEditIn(BaseModel):
    content_markdown: str = Field(min_length=1, max_length=200000)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewActionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=4000)


class ReportReviewOut(ORM):
    id: int
    reviewer_id: int
    reviewer: UserBrief
    action: str
    comment: str | None
    created_at: datetime


class ReportOut(ORM):
    id: int
    report_type: str
    employee_id: int | None
    employee: UserBrief | None = None
    team_id: int | None
    team_name: str | None = None
    week_start: date
    week_end: date
    status: str
    generation_mode: str
    content_markdown: str
    validation_warnings: list
    edited_by_human: bool
    approved_by_id: int | None
    approved_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    reviews: list[ReportReviewOut] = []


class ReportListItem(ORM):
    id: int
    report_type: str
    employee_id: int | None
    employee: UserBrief | None = None
    team_id: int | None
    team_name: str | None = None
    week_start: date
    status: str
    generation_mode: str
    updated_at: datetime


# ---------------------------------------------------------------- settings / misc


class OrgSettingsOut(ORM):
    org_name: str
    timezone: str
    working_days: list[int]
    daily_reminder_time: str
    report_generation_day: int
    report_generation_time: str
    min_daily_hours: float | None
    max_daily_hours: float | None
    managers_can_assign_goals: bool
    reminders_enabled: bool
    auto_generate_reports: bool
    ai_mode: str = "fallback"


class OrgSettingsUpdate(BaseModel):
    org_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = None
    working_days: list[int] | None = None
    daily_reminder_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    report_generation_day: int | None = Field(default=None, ge=0, le=6)
    report_generation_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    min_daily_hours: float | None = Field(default=None, ge=0, le=24)
    max_daily_hours: float | None = Field(default=None, ge=0, le=24)
    managers_can_assign_goals: bool | None = None
    reminders_enabled: bool | None = None
    auto_generate_reports: bool | None = None

    @field_validator("working_days")
    @classmethod
    def _days(cls, v):
        if v is not None and (not v or any(d < 0 or d > 6 for d in v)):
            raise ValueError("working_days must contain values 0 (Mon) .. 6 (Sun)")
        return sorted(set(v)) if v is not None else v


class TimeOffIn(BaseModel):
    user_id: int | None = None  # null = organization holiday (admin only)
    start: date
    end: date | None = None
    reason: str | None = Field(default=None, max_length=255)


class TimeOffOut(ORM):
    id: int
    user_id: int | None
    day: date
    reason: str | None


class NotificationOut(ORM):
    id: int
    type: str
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class AuditLogOut(ORM):
    id: int
    actor_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    before: dict | None
    after: dict | None
    created_at: datetime
