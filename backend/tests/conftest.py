import os

os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["LLM_PROVIDER"] = "fallback"
os.environ["MONGODB_URI"] = "mongomock://"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256"

from datetime import datetime, timedelta, timezone  # noqa: E402

import mongomock  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai.provider import set_provider  # noqa: E402
from app.db import Session, ensure_indexes, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, Team, TeamMember, User  # noqa: E402
from app.security import create_access_token, hash_password, rate_limiter  # noqa: E402
from app.utils import org_today, week_bounds  # noqa: E402


@pytest.fixture
def db():
    database = mongomock.MongoClient()["teamtrack_test"]  # fresh in-memory MongoDB per test
    ensure_indexes(database)
    session = Session(database)

    def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    set_provider(None)
    rate_limiter.reset()
    yield session
    session.close()
    app.dependency_overrides.clear()
    set_provider(None)


@pytest.fixture
def client(db):
    return TestClient(app)


def make_user(db, email, role=Role.employee, name=None, password="Password123!"):
    u = User(
        email=email,
        full_name=name or email.split("@")[0].title(),
        password_hash=hash_password(password),
        role=role,
        created_at=datetime.now(timezone.utc) - timedelta(days=60),
    )
    return db.add(u)


def auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


class Org:
    pass


@pytest.fixture
def org(db):
    o = Org()
    o.admin = make_user(db, "admin@x.io", Role.admin, "Admin")
    o.m1 = make_user(db, "m1@x.io", Role.manager, "Manager One")
    o.m2 = make_user(db, "m2@x.io", Role.manager, "Manager Two")
    o.e1 = make_user(db, "e1@x.io", name="Employee One")
    o.e2 = make_user(db, "e2@x.io", name="Employee Two")
    o.e3 = make_user(db, "e3@x.io", name="Employee Three")
    o.t1 = Team(name="Team 1", manager_id=o.m1.id)
    o.t2 = Team(name="Team 2", manager_id=o.m2.id)
    db.add_all([o.t1, o.t2])
    db.add_all(
        [
            TeamMember(team_id=o.t1.id, user_id=o.e1.id),
            TeamMember(team_id=o.t1.id, user_id=o.e2.id),
            TeamMember(team_id=o.t2.id, user_id=o.e3.id),
        ]
    )
    db.commit()
    o.today = org_today(db)
    o.week_start = week_bounds(o.today)[0]
    return o


def create_goal(client, actor, owner, week_start, title="Ship export feature", tasks=("Build CSV export", "Write export tests"), **extra):
    payload = {
        "title": title,
        "owner_id": owner.id,
        "week_start": week_start.isoformat(),
        "project": extra.pop("project", "Donor IQ"),
        "expected_outcome": "Users can export data",
        "tasks": [{"title": t} for t in tasks],
        **extra,
    }
    r = client.post("/api/goals", json=payload, headers=auth(actor))
    assert r.status_code == 201, r.text
    return r.json()
