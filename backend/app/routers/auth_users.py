from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import ensure_can_view_employee, get_current_user, require_admin, visible_employee_ids
from app.models import Role, Team, TeamMember, User
from app.schemas import LoginIn, Page, PreferencesUpdate, TokenOut, UserCreate, UserOut, UserUpdate
from app.security import create_access_token, hash_password, rate_limiter, verify_password
from app.services.notifications import PREF_LABELS
from app.utils import audit

router = APIRouter(tags=["auth & users"])


def user_out(db: Session, u: User) -> UserOut:
    out = UserOut.model_validate(u)
    out.team_ids = list(db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == u.id)))
    return out


def _set_teams(db: Session, user: User, team_ids: list[int]) -> None:
    valid = set(db.scalars(select(Team.id).where(Team.id.in_(team_ids or [-1]))))
    missing = set(team_ids) - valid
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown team id(s): {sorted(missing)}")
    db.query(TeamMember).filter(TeamMember.user_id == user.id, TeamMember.team_id.not_in(valid or {-1})).delete(
        synchronize_session=False
    )
    have = set(db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == user.id)))
    for tid in valid - have:
        db.add(TeamMember(team_id=tid, user_id=user.id))


@router.post("/auth/login", response_model=TokenOut)
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"login:{ip}:{data.email.lower()}", get_settings().rate_limit_login_per_minute)
    user = db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is deactivated")
    return TokenOut(access_token=create_access_token(user.id, user.role), user=user_out(db, user))


@router.post("/auth/logout", status_code=204)
def logout(_: User = Depends(get_current_user)):
    # Tokens are stateless; the client discards its token.
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_out(db, user)


@router.get("/auth/me/preference-options")
def preference_options(user: User = Depends(get_current_user)):
    prefs = user.notification_prefs or {}
    return [{"key": k, "label": v, "enabled": prefs.get(k, True)} for k, v in PREF_LABELS.items()]


@router.patch("/auth/me/preferences", response_model=UserOut)
def update_preferences(data: PreferencesUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    unknown = set(data.notification_prefs) - set(PREF_LABELS)
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown preference(s): {sorted(unknown)}")
    user.notification_prefs = {**(user.notification_prefs or {}), **data.notification_prefs}
    db.commit()
    return user_out(db, user)


@router.get("/users", response_model=Page[UserOut])
def list_users(
    role: Role | None = None,
    team_id: int | None = None,
    q: str | None = None,
    active: bool | None = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page, page_size = max(1, page), min(max(1, page_size), 200)
    stmt = select(User)
    ids = visible_employee_ids(db, user)
    if ids is not None:
        stmt = stmt.where(User.id.in_(ids))
    if role:
        stmt = stmt.where(User.role == role)
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    if team_id:
        stmt = stmt.join(TeamMember, TeamMember.user_id == User.id).where(TeamMember.team_id == team_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.full_name).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[user_out(db, u) for u in rows], total=total, page=page, page_size=page_size)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User.id).where(func.lower(User.email) == data.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    u = User(
        email=data.email.lower(),
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
        department=data.department,
        job_title=data.job_title,
    )
    db.add(u)
    db.flush()
    _set_teams(db, u, data.team_ids)
    audit(db, actor.id, "create_user", "user", u.id, after={"email": u.email, "role": u.role})
    db.commit()
    return user_out(db, u)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_can_view_employee(db, user, user_id)
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Not found")
    return user_out(db, u)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Not found")
    if u.id == actor.id and (data.is_active is False or (data.role and data.role != Role.admin)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate or demote your own account")
    before = {"full_name": u.full_name, "role": u.role, "is_active": u.is_active, "department": u.department}
    for f in ("full_name", "role", "department", "job_title", "is_active"):
        v = getattr(data, f)
        if v is not None:
            setattr(u, f, v)
    if data.password:
        u.password_hash = hash_password(data.password)
    if data.team_ids is not None:
        _set_teams(db, u, data.team_ids)
    audit(db, actor.id, "update_user", "user", u.id, before=before,
          after={"full_name": u.full_name, "role": u.role, "is_active": u.is_active, "department": u.department})
    db.commit()
    return user_out(db, u)
