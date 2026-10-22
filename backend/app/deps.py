"""Authentication and authorization dependencies.

All data-visibility rules live here so every router enforces them the same way:
- admin: everyone
- manager: themselves + members of teams they manage
- employee: themselves only
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Role, Team, TeamMember, User
from app.security import decode_access_token, rate_limiter

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_access_token(creds.credentials)
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_roles(*roles: Role):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return user

    return checker


require_admin = require_roles(Role.admin)
require_manager_or_admin = require_roles(Role.admin, Role.manager)


def ai_rate_limit(request: Request, user: User = Depends(get_current_user)) -> None:
    rate_limiter.check(f"ai:{user.id}", get_settings().rate_limit_ai_per_minute)


def managed_team_ids(db: Session, user: User) -> list[int]:
    return list(db.scalars(select(Team.id).where(Team.manager_id == user.id)))


def visible_employee_ids(db: Session, user: User) -> set[int] | None:
    """Employee ids the user may see. None means unrestricted (admin)."""
    if user.role == Role.admin:
        return None
    ids = {user.id}
    if user.role == Role.manager:
        team_ids = managed_team_ids(db, user)
        if team_ids:
            ids.update(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id.in_(team_ids))))
    return ids


def can_view_employee(db: Session, user: User, employee_id: int) -> bool:
    ids = visible_employee_ids(db, user)
    return ids is None or employee_id in ids


def ensure_can_view_employee(db: Session, user: User, employee_id: int) -> None:
    if not can_view_employee(db, user, employee_id):
        # 404 rather than 403 so we don't leak which records exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def can_manage_employee(db: Session, user: User, employee_id: int) -> bool:
    """Manage = assign goals, review reports. Managers only for their team members."""
    if user.role == Role.admin:
        return True
    if user.role == Role.manager:
        return employee_id != user.id and can_view_employee(db, user, employee_id)
    return False


def ensure_can_manage_employee(db: Session, user: User, employee_id: int) -> None:
    if not can_manage_employee(db, user, employee_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot manage this employee")


def can_view_team(db: Session, user: User, team_id: int) -> bool:
    if user.role == Role.admin:
        return True
    team = db.get(Team, team_id)
    if team is None:
        return False
    if user.role == Role.manager and team.manager_id == user.id:
        return True
    return False
