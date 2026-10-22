from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Notification, Role, Team, TeamMember, User

# notification type -> preference key (users can switch categories off)
PREF_KEYS = {
    "daily_reminder": "daily_reminder",
    "deadline": "deadlines",
    "overdue": "deadlines",
    "blocker": "blockers",
    "report_ready": "reports",
    "report_review": "reports",
    "report_status": "reports",
    "goal_review": "reports",
    "goal_assigned": "goals",
}

PREF_LABELS = {
    "daily_reminder": "Daily update reminders",
    "deadlines": "Upcoming and overdue deadlines",
    "blockers": "Blockers reported by my team",
    "reports": "Weekly reports and reviews",
    "goals": "New goals assigned to me",
}


def wants(user: User, ntype: str) -> bool:
    key = PREF_KEYS.get(ntype)
    return True if key is None else (user.notification_prefs or {}).get(key, True)


def notify(
    db: Session, user: User, ntype: str, title: str, dedupe_key: str, body: str | None = None, link: str | None = None
) -> bool:
    """Create a notification once per dedupe_key. Returns True if created."""
    if not user.is_active or not wants(user, ntype):
        return False
    if db.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key)):
        return False
    try:
        with db.begin_nested():
            db.add(Notification(user_id=user.id, type=ntype, title=title, body=body, link=link, dedupe_key=dedupe_key))
    except IntegrityError:
        return False
    return True


def managers_of(db: Session, employee_id: int) -> list[User]:
    """Managers of the employee's teams; admins when the employee has no manager."""
    q = (
        select(User)
        .join(Team, Team.manager_id == User.id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == employee_id, User.is_active.is_(True), User.id != employee_id)
    )
    managers = list(dict.fromkeys(db.scalars(q)))
    if not managers:
        managers = list(db.scalars(select(User).where(User.role == Role.admin, User.is_active.is_(True))))
    return managers
