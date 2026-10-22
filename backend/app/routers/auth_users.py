from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
import re

from app.config import get_settings
from app.db import Session, get_db
from app.deps import ensure_can_view_employee, get_current_user, require_admin, visible_employee_ids
from app.models import Role, Team, TeamMember, User
from app.schemas import LoginIn, Page, PreferencesUpdate, TokenOut, UserCreate, UserOut, UserUpdate
from app.security import create_access_token, hash_password, rate_limiter, verify_password
from app.services.notifications import PREF_LABELS
from app.utils import audit

router = APIRouter(tags=["auth & users"])


def user_out(db: Session, u: User) -> UserOut:
    out = UserOut.model_validate(u)
    out.team_ids = [m.team_id for m in db.find(TeamMember, {"user_id": u.id})]
    return out


def _set_teams(db: Session, user: User, team_ids: list[int]) -> None:
    valid = set(db.get_many(Team, team_ids))
    missing = set(team_ids) - valid
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown team id(s): {sorted(missing)}")
    have = set()
    for m in db.find(TeamMember, {"user_id": user.id}):
        if m.team_id in valid:
            have.add(m.team_id)
        else:
            db.delete(m)
    for tid in sorted(valid - have):
        db.add(TeamMember(team_id=tid, user_id=user.id))


@router.post("/auth/login", response_model=TokenOut)
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"login:{ip}:{data.email.lower()}", get_settings().rate_limit_login_per_minute)
    user = db.first(User, {"email": data.email.strip().lower()})
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
    f: dict = {}
    conditions: list[dict] = []
    ids = visible_employee_ids(db, user)
    if ids is not None:
        conditions.append({"id": {"$in": sorted(ids)}})
    if role:
        f["role"] = role
    if active is not None:
        f["is_active"] = active
    if team_id:
        conditions.append({"id": {"$in": [m.user_id for m in db.find(TeamMember, {"team_id": team_id})]}})
    if q:
        pattern = re.escape(q.strip())
        f["$or"] = [{"full_name": {"$regex": pattern, "$options": "i"}}, {"email": {"$regex": pattern, "$options": "i"}}]
    if conditions:
        f["$and"] = conditions
    total = db.count(User, f)
    rows = db.find(User, f, sort=[("full_name", 1), ("id", 1)], skip=(page - 1) * page_size, limit=page_size)
    return Page(items=[user_out(db, u) for u in rows], total=total, page=page, page_size=page_size)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.exists(User, {"email": data.email.strip().lower()}):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    u = User(
        email=data.email.strip().lower(),
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
        department=data.department,
        job_title=data.job_title,
    )
    db.add(u)
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
