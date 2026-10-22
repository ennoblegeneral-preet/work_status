from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import Role, Team, TeamMember, User
from app.schemas import TeamCreate, TeamOut, TeamUpdate, UserBrief
from app.utils import audit

router = APIRouter(prefix="/teams", tags=["teams"])


def team_out(t: Team) -> TeamOut:
    return TeamOut(
        id=t.id,
        name=t.name,
        department=t.department,
        manager_id=t.manager_id,
        manager=UserBrief.model_validate(t.manager) if t.manager else None,
        members=[UserBrief.model_validate(m.user) for m in t.members if m.user.is_active],
    )


def _q():
    return select(Team).options(selectinload(Team.members).selectinload(TeamMember.user), selectinload(Team.manager))


def _validate(db: Session, manager_id: int | None, member_ids: list[int] | None) -> None:
    if manager_id is not None:
        m = db.get(User, manager_id)
        if m is None or m.role not in (Role.manager, Role.admin):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Team manager must be a user with the manager or admin role")
    if member_ids:
        found = set(db.scalars(select(User.id).where(User.id.in_(member_ids))))
        if found != set(member_ids):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown user id(s): {sorted(set(member_ids) - found)}")


@router.get("", response_model=list[TeamOut])
def list_teams(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = _q().order_by(Team.name)
    if user.role == Role.manager:
        q = q.where(
            (Team.manager_id == user.id) | Team.id.in_(select(TeamMember.team_id).where(TeamMember.user_id == user.id))
        )
    elif user.role == Role.employee:
        q = q.where(Team.id.in_(select(TeamMember.team_id).where(TeamMember.user_id == user.id)))
    return [team_out(t) for t in db.scalars(q)]


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.scalar(_q().where(Team.id == team_id))
    if t is None:
        raise HTTPException(404, "Not found")
    if user.role != Role.admin and t.manager_id != user.id and user.id not in {m.user_id for m in t.members}:
        raise HTTPException(404, "Not found")
    return team_out(t)


@router.post("", response_model=TeamOut, status_code=201)
def create_team(data: TeamCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(Team.id).where(Team.name == data.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A team with this name already exists")
    _validate(db, data.manager_id, data.member_ids)
    t = Team(name=data.name, department=data.department, manager_id=data.manager_id)
    db.add(t)
    db.flush()
    for uid in set(data.member_ids):
        db.add(TeamMember(team_id=t.id, user_id=uid))
    audit(db, actor.id, "create_team", "team", t.id, after=data.model_dump())
    db.commit()
    return team_out(db.scalar(_q().where(Team.id == t.id)))


@router.patch("/{team_id}", response_model=TeamOut)
def update_team(team_id: int, data: TeamUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.scalar(_q().where(Team.id == team_id))
    if t is None:
        raise HTTPException(404, "Not found")
    changes = data.model_dump(exclude_unset=True)
    _validate(db, changes.get("manager_id"), changes.get("member_ids"))
    before = {"name": t.name, "manager_id": t.manager_id, "member_ids": [m.user_id for m in t.members]}
    for f in ("name", "department", "manager_id"):
        if f in changes:
            setattr(t, f, changes[f])
    if data.member_ids is not None:
        keep = set(data.member_ids)
        t.members = [m for m in t.members if m.user_id in keep]
        have = {m.user_id for m in t.members}
        for uid in keep - have:
            t.members.append(TeamMember(team_id=t.id, user_id=uid))
    audit(db, actor.id, "update_team", "team", t.id, before=before, after=changes)
    db.commit()
    db.expire_all()
    return team_out(db.scalar(_q().where(Team.id == team_id)))


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: int, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import WeeklyGoal, WeeklyReport

    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "Not found")
    if db.scalar(select(WeeklyGoal.id).where(WeeklyGoal.team_id == team_id)) or db.scalar(
        select(WeeklyReport.id).where(WeeklyReport.team_id == team_id)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "This team has goals or reports; remove members instead of deleting it")
    audit(db, actor.id, "delete_team", "team", t.id, before={"name": t.name})
    db.delete(t)
    db.commit()
