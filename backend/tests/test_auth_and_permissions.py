from app.models import Role
from tests.conftest import auth, create_goal


def test_login_success_and_failure(client, org):
    r = client.post("/api/auth/login", json={"email": "e1@x.io", "password": "Password123!"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "e1@x.io"
    assert me.json()["team_ids"] == [org.t1.id]

    assert client.post("/api/auth/login", json={"email": "e1@x.io", "password": "wrong"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_deactivated_user_cannot_log_in_or_use_token(client, org, db):
    headers = auth(org.e1)
    r = client.patch(f"/api/users/{org.e1.id}", json={"is_active": False}, headers=auth(org.admin))
    assert r.status_code == 200
    assert client.post("/api/auth/login", json={"email": "e1@x.io", "password": "Password123!"}).status_code == 403
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_only_admin_manages_users_and_teams(client, org):
    payload = {"email": "new@x.io", "full_name": "New Person", "password": "Password123!"}
    assert client.post("/api/users", json=payload, headers=auth(org.e1)).status_code == 403
    assert client.post("/api/users", json=payload, headers=auth(org.m1)).status_code == 403
    r = client.post("/api/users", json={**payload, "team_ids": [org.t1.id]}, headers=auth(org.admin))
    assert r.status_code == 201
    assert r.json()["team_ids"] == [org.t1.id]
    assert client.post("/api/users", json=payload, headers=auth(org.admin)).status_code == 409
    assert client.post("/api/teams", json={"name": "X"}, headers=auth(org.m1)).status_code == 403


def test_admin_cannot_demote_self(client, org):
    r = client.patch(f"/api/users/{org.admin.id}", json={"role": Role.employee}, headers=auth(org.admin))
    assert r.status_code == 400


def test_user_visibility(client, org):
    ids = lambda r: {u["id"] for u in r.json()["items"]}  # noqa: E731
    assert ids(client.get("/api/users", headers=auth(org.e1))) == {org.e1.id}
    assert ids(client.get("/api/users", headers=auth(org.m1))) == {org.m1.id, org.e1.id, org.e2.id}
    assert len(ids(client.get("/api/users", headers=auth(org.admin)))) == 6
    assert client.get(f"/api/users/{org.e3.id}", headers=auth(org.m1)).status_code == 404


def test_goal_data_isolation(client, org):
    g1 = create_goal(client, org.m1, org.e1, org.week_start)
    g3 = create_goal(client, org.m2, org.e3, org.week_start, title="Other team goal")

    assert client.get(f"/api/goals/{g1['id']}", headers=auth(org.e2)).status_code == 404
    assert client.get(f"/api/goals/{g3['id']}", headers=auth(org.m1)).status_code == 404
    assert client.get(f"/api/goals/{g3['id']}", headers=auth(org.admin)).status_code == 200

    listed = client.get("/api/goals", headers=auth(org.e1)).json()["items"]
    assert [g["id"] for g in listed] == [g1["id"]]
    listed_m1 = {g["id"] for g in client.get("/api/goals", headers=auth(org.m1)).json()["items"]}
    assert listed_m1 == {g1["id"]}


def test_manager_can_only_assign_to_own_team(client, org):
    payload = {"title": "X", "owner_id": org.e3.id, "week_start": org.week_start.isoformat()}
    assert client.post("/api/goals", json=payload, headers=auth(org.m1)).status_code == 403
    assert client.post("/api/goals", json=payload, headers=auth(org.e1)).status_code == 403
    assert client.post("/api/goals", json={**payload, "owner_id": org.e1.id}, headers=auth(org.m1)).status_code == 201


def test_managers_can_be_prevented_from_assigning(client, org):
    assert client.patch("/api/settings", json={"managers_can_assign_goals": False}, headers=auth(org.admin)).status_code == 200
    payload = {"title": "X", "owner_id": org.e1.id, "week_start": org.week_start.isoformat()}
    assert client.post("/api/goals", json=payload, headers=auth(org.m1)).status_code == 403


def test_validation_errors(client, org):
    r = client.post("/api/goals", json={"owner_id": org.e1.id}, headers=auth(org.admin))
    assert r.status_code == 422
    r = client.post("/api/daily-updates/parse", json={"text": ""}, headers=auth(org.e1))
    assert r.status_code == 422
    r = client.patch("/api/settings", json={"working_days": [9]}, headers=auth(org.admin))
    assert r.status_code == 422
    r = client.post("/api/goals", json={"title": "N", "owner_id": org.e1.id, "week_start": org.week_start.isoformat(),
                                       "target_type": "number"}, headers=auth(org.admin))
    assert r.status_code == 422
