from fastapi import APIRouter, Depends, HTTPException, status
from app.db import Session, get_db
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


def _load(db: Session, teams: list[Team]) -> list[Team]:
    db.preload(teams, "members", "manager")
    db.preload([m for t in teams for m in t.members], "user")
    return teams


def _validate(db: Session, manager_id: int | None, member_ids: list[int] | None) -> None:
    if manager_id is not None:
        m = db.get(User, manager_id)
        if m is None or m.role not in (Role.manager, Role.admin):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Team manager must be a user with the manager or admin role")
    if member_ids:
        found = set(db.get_many(User, member_ids))
        if found != set(member_ids):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown user id(s): {sorted(set(member_ids) - found)}")


@router.get("", response_model=list[TeamOut])
def list_teams(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f: dict = {}
    if user.role != Role.admin:
        my_teams = [m.team_id for m in db.find(TeamMember, {"user_id": user.id})]
        f = {"$or": [{"manager_id": user.id}, {"id": {"$in": my_teams}}]} if user.role == Role.manager else {"id": {"$in": my_teams}}
    return [team_out(t) for t in _load(db, db.find(Team, f, sort=[("name", 1)]))]


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "Not found")
    if user.role != Role.admin and t.manager_id != user.id and user.id not in {m.user_id for m in t.members}:
        raise HTTPException(404, "Not found")
    return team_out(t)


@router.post("", response_model=TeamOut, status_code=201)
def create_team(data: TeamCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.exists(Team, {"name": data.name}):
        raise HTTPException(status.HTTP_409_CONFLICT, "A team with this name already exists")
    _validate(db, data.manager_id, data.member_ids)
    t = Team(name=data.name, department=data.department, manager_id=data.manager_id)
    db.add(t)
    for uid in sorted(set(data.member_ids)):
        db.add(TeamMember(team_id=t.id, user_id=uid))
    audit(db, actor.id, "create_team", "team", t.id, after=data.model_dump())
    db.commit()
    return team_out(t)


@router.patch("/{team_id}", response_model=TeamOut)
def update_team(team_id: int, data: TeamUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "Not found")
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != t.name and db.exists(Team, {"name": changes["name"]}):
        raise HTTPException(status.HTTP_409_CONFLICT, "A team with this name already exists")
    _validate(db, changes.get("manager_id"), changes.get("member_ids"))
    before = {"name": t.name, "manager_id": t.manager_id, "member_ids": [m.user_id for m in t.members]}
    for f in ("name", "department", "manager_id"):
        if f in changes:
            setattr(t, f, changes[f])
    if data.member_ids is not None:
        keep = set(data.member_ids)
        t.members = [m for m in t.members if m.user_id in keep]  # removed members are deleted
        have = {m.user_id for m in t.members}
        for uid in sorted(keep - have):
            db.add(TeamMember(team_id=t.id, user_id=uid))
    audit(db, actor.id, "update_team", "team", t.id, before=before, after=changes)
    db.commit()
    return team_out(t)


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: int, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import WeeklyGoal, WeeklyReport

    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "Not found")
    if db.exists(WeeklyGoal, {"team_id": team_id}) or db.exists(WeeklyReport, {"team_id": team_id}):
        raise HTTPException(status.HTTP_409_CONFLICT, "This team has goals or reports; remove members instead of deleting it")
    audit(db, actor.id, "delete_team", "team", t.id, before={"name": t.name})
    for m in t.members:
        db.delete(m)
    db.delete(t)
    db.commit()
