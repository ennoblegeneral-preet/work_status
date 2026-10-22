from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.models import GoalStatus, Notification, OrgSettings, TargetType, Task, TimeOff, WeeklyGoal
from app.services.automation import run_automation
from app.services.missing import missing_for_user
from app.services.progress import goal_health, goal_progress
from tests.conftest import auth, create_goal


def _goal(**kw):
    g = WeeklyGoal(title="g", owner_id=1, week_start=date(2026, 10, 19), week_end=date(2026, 10, 25), status=GoalStatus.in_progress,
                   target_type=TargetType.tasks, **kw)
    return g


def test_progress_rules():
    g = _goal()
    g.tasks = [Task(title="a", status="completed", weight=3, owner_id=1), Task(title="b", status="in_progress", weight=1, owner_id=1),
               Task(title="c", status="cancelled", weight=5, owner_id=1)]
    assert goal_progress(g) == 75.0  # cancelled tasks excluded, weights respected
    g.tasks = []
    assert goal_progress(g) == 0.0  # working on a goal without tasks never implies progress
    n = _goal(target_value=4, current_value=1)
    n.target_type = TargetType.number
    assert goal_progress(n) == 25.0
    b = _goal()
    b.target_type = TargetType.boolean
    assert goal_progress(b) == 0.0
    b.status = GoalStatus.completed
    assert goal_progress(b) == 100.0


def test_health():
    wd = [0, 1, 2, 3, 4]
    g = _goal(deadline=date(2026, 10, 23))
    g.tasks = [Task(title="a", status="not_started", weight=1, owner_id=1)]
    assert goal_health(g, date(2026, 10, 19), wd) == "on_track"
    assert goal_health(g, date(2026, 10, 22), wd) == "off_track"
    g.tasks[0].status = "completed"
    g.tasks.append(Task(title="b", status="not_started", weight=1, owner_id=1))
    assert goal_health(g, date(2026, 10, 22), wd) == "at_risk"
    assert goal_health(g, date(2026, 10, 26), wd) == "off_track"


def test_goal_completion_requires_reason_when_tasks_open(client, org):
    g = create_goal(client, org.m1, org.e1, org.week_start)
    r = client.patch(f"/api/goals/{g['id']}", json={"status": "completed"}, headers=auth(org.e1))
    assert r.status_code == 422
    r = client.patch(f"/api/goals/{g['id']}", json={"status": "completed", "reason": "Delivered via another approach"}, headers=auth(org.e1))
    assert r.status_code == 200 and r.json()["progress"] == 100
    assert client.patch(f"/api/goals/{g['id']}", json={"status": "cancelled"}, headers=auth(org.e1)).status_code == 403
    assert client.patch(f"/api/goals/{g['id']}", json={"title": "Renamed"}, headers=auth(org.e1)).status_code == 403


def test_carry_forward_preserves_history(client, org, db):
    prev = org.week_start - timedelta(days=7)
    g = create_goal(client, org.m1, org.e1, prev, deadline=(prev + timedelta(days=4)).isoformat())
    t0 = g["tasks"][0]["id"]
    client.patch(f"/api/tasks/{t0}", json={"status": "completed"}, headers=auth(org.e1))
    review = client.get(f"/api/goals/review?week_start={prev}", headers=auth(org.m1)).json()
    assert [x["id"] for x in review] == [g["id"]]
    assert client.post(f"/api/goals/{g['id']}/review", json={"action": "carry_forward", "reason": "x"}, headers=auth(org.e1)).status_code == 403
    r = client.post(f"/api/goals/{g['id']}/review", json={"action": "carry_forward", "reason": "Client feedback delayed"}, headers=auth(org.m1))
    new = r.json()
    assert new["week_start"] == org.week_start.isoformat()
    assert new["carried_from_goal_id"] == g["id"]
    assert new["original_deadline"] == (prev + timedelta(days=4)).isoformat()
    assert [t["title"] for t in new["tasks"]] == ["Write export tests"]  # completed task not copied
    old = client.get(f"/api/goals/{g['id']}", headers=auth(org.m1)).json()
    assert old["status"] == "deferred" and old["tasks"][0]["status"] == "completed"
    assert client.get(f"/api/goals/review?week_start={prev}", headers=auth(org.m1)).json() == []
    assert client.post(f"/api/goals/{g['id']}/review", json={"action": "carry_forward", "reason": "again"}, headers=auth(org.m1)).status_code == 409


def test_missing_updates_respect_schedule_leave_and_holidays(db, org):
    # A fixed past week: Mon 2026-10-05 .. Sun 2026-10-11
    ws = date(2026, 10, 5)
    db.add(TimeOff(user_id=None, day=date(2026, 10, 7), reason="Holiday"))
    db.add(TimeOff(user_id=org.e1.id, day=date(2026, 10, 8), reason="Leave"))
    db.commit()
    res = missing_for_user(db, org.e1, ws, ws + timedelta(days=6))
    assert res["expected_days"] == 3  # Mon, Tue, Fri
    assert res["missing_dates"] == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 9)]
    s = db.get(OrgSettings, 1)
    s.working_days = [0, 1, 2, 3, 4, 5]
    db.commit()
    assert missing_for_user(db, org.e1, ws, ws + timedelta(days=6))["expected_days"] == 4


def test_reminders_are_not_duplicated_and_respect_preferences(db, org, client):
    s = db.get(OrgSettings, 1) or OrgSettings(id=1)
    db.merge(s)
    db.commit()
    s = db.get(OrgSettings, 1)
    s.working_days = [0, 1, 2, 3, 4, 5, 6]
    s.daily_reminder_time = "17:00"
    s.report_generation_day = 6 if datetime.now().weekday() != 6 else 5
    db.commit()
    client.patch("/api/auth/me/preferences", json={"notification_prefs": {"daily_reminder": False}}, headers=auth(org.e2))
    now = datetime.combine(org.today, datetime.min.time()).replace(hour=18)
    first = run_automation(db, now)
    second = run_automation(db, now)
    assert first["reminders"] == 4  # m1, m2, e1, e3 (e2 opted out; admins excluded)
    assert second["reminders"] == 0
    users = {n.user_id for n in db.scalars(select(Notification).where(Notification.type == "daily_reminder"))}
    assert org.e2.id not in users and org.admin.id not in users
    early = run_automation(db, now.replace(hour=9))
    assert early["reminders"] == 0
