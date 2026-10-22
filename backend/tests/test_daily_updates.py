from datetime import timedelta

from sqlalchemy import func, select

from app.models import Task, WorkLogItem
from tests.conftest import auth, create_goal

PASTE = (
    "Fixed the scoring error in the Scoring Agent, added a new guardrail to the Interviewer Agent, "
    "tested phone detection, and reviewed the code. Total time spent: 7.5 hours."
)


def parse(client, user, text, **kw):
    r = client.post("/api/daily-updates/parse", json={"text": text, **kw}, headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def confirm(client, user, d):
    return client.post(f"/api/daily-updates/{d['log_id']}/confirm", json={"draft": d["draft"]}, headers=auth(user))


def test_paste_parse_preview_does_not_save_work(client, org, db):
    d = parse(client, org.e1, PASTE)
    titles = [i["task_title"] for i in d["draft"]["items"]]
    assert titles == [
        "Fixed the scoring error in the Scoring Agent",
        "Added a new guardrail to the Interviewer Agent",
        "Tested phone detection",
        "Reviewed the code",
    ]
    assert d["draft"]["total_hours"] == 7.5
    assert d["parse_mode"] == "fallback"
    assert all(i["requires_confirmation"] for i in d["draft"]["items"])  # fallback: always confirm
    assert any("rule-based" in w for w in d["draft"]["warnings"])
    assert db.scalar(select(func.count(WorkLogItem.id))) == 0  # nothing saved before confirmation
    assert d["raw_text"] == PASTE


def test_confirm_saves_items_preserves_original_and_hours(client, org, db):
    d = parse(client, org.e1, PASTE)
    r = confirm(client, org.e1, d)
    assert r.status_code == 200, r.text
    log = r.json()
    assert log["raw_text"] == PASTE
    assert log["total_hours"] == 7.5
    assert len(log["items"]) == 4
    assert all(i["is_unplanned"] for i in log["items"])  # no goals assigned -> additional work
    # confirming twice is rejected
    assert confirm(client, org.e1, d).status_code == 409
    # the same text cannot be submitted again
    assert client.post("/api/daily-updates/parse", json={"text": PASTE}, headers=auth(org.e1)).status_code == 409


def test_missing_hours_are_stored_as_unknown(client, org):
    d = parse(client, org.e1, "Reviewed the onboarding docs and updated the FAQ page.")
    log = confirm(client, org.e1, d).json()
    assert log["total_hours"] is None
    assert all(i["hours"] is None for i in log["items"])


def test_title_match_links_to_existing_task_and_updates_progress(client, org):
    goal = create_goal(client, org.m1, org.e1, org.week_start)
    d = parse(client, org.e1, "Built CSV export and deployed it. 6 hours")
    item = d["draft"]["items"][0]
    task_id = goal["tasks"][0]["id"]
    assert item["task_id"] == task_id and item["goal_id"] == goal["id"]
    assert item["match_method"] == "title"
    confirm(client, org.e1, d)
    g = client.get(f"/api/goals/{goal['id']}", headers=auth(org.e1)).json()
    assert g["tasks"][0]["status"] == "completed"
    assert g["progress"] == 50.0
    assert g["status"] == "in_progress"  # not completed: one task still open


def test_explicit_task_reference_wins(client, org):
    goal = create_goal(client, org.m1, org.e1, org.week_start)
    tid = goal["tasks"][1]["id"]
    d = parse(client, org.e1, f"Worked on T-{tid} today, half the cases written")
    item = d["draft"]["items"][0]
    assert item["task_id"] == tid and item["match_method"] == "explicit" and item["confidence"] == 1.0


def test_multi_day_work_stays_on_one_task(client, org, db):
    # three consecutive days inside one week, none in the future
    ws = org.week_start if org.today >= org.week_start + timedelta(days=2) else org.week_start - timedelta(days=7)
    goal = create_goal(client, org.m1, org.e1, ws, tasks=("Build CSV export",))
    days = [ws, ws + timedelta(days=1), ws + timedelta(days=2)]
    texts = ["Started building CSV export", "Continued building the CSV export", "Finished CSV export and deployed"]
    for day, text in zip(days, texts):
        d = parse(client, org.e1, text, report_date=day.isoformat())
        assert d["draft"]["items"][0]["task_id"] == goal["tasks"][0]["id"], text
        assert confirm(client, org.e1, d).status_code == 200

    tasks = db.scalars(select(Task).where(Task.owner_id == org.e1.id)).all()
    assert len(tasks) == 1  # no duplicates created
    items = db.scalars(select(WorkLogItem).where(WorkLogItem.task_id == tasks[0].id).order_by(WorkLogItem.report_date)).all()
    assert [i.report_date for i in items] == days
    assert [i.status for i in items] == ["in_progress", "in_progress", "completed"]
    g = client.get(f"/api/goals/{goal['id']}", headers=auth(org.e1)).json()
    assert g["status"] == "completed" and g["progress"] == 100  # defined rule: all tasks completed
    hist = client.get(f"/api/goals/{goal['id']}/history", headers=auth(org.e1)).json()
    assert [h["to_status"] for h in hist["task_status"]] == ["in_progress", "completed"]


def test_unplanned_work_is_reused_across_days(client, org, db):
    d1 = parse(client, org.e1, "Investigated flaky login test", report_date=(org.today - timedelta(days=1)).isoformat())
    confirm(client, org.e1, d1)
    d2 = parse(client, org.e1, "Investigated flaky login test, root cause found")
    first_task = db.scalar(select(Task.id).where(Task.owner_id == org.e1.id))
    assert d2["draft"]["items"][0]["task_id"] == first_task
    confirm(client, org.e1, d2)
    assert db.scalar(select(func.count(Task.id)).where(Task.owner_id == org.e1.id)) == 1


def test_cannot_link_other_employees_goal(client, org):
    other = create_goal(client, org.m1, org.e2, org.week_start)
    d = parse(client, org.e1, "Did some work")
    d["draft"]["items"][0]["goal_id"] = other["id"]
    r = confirm(client, org.e1, d)
    assert r.status_code == 400
    d["draft"]["items"][0]["goal_id"] = None
    d["draft"]["items"][0]["task_id"] = other["tasks"][0]["id"]
    assert confirm(client, org.e1, d).status_code == 400


def test_drafts_are_private(client, org):
    d = parse(client, org.e1, "Wrote the release notes")
    for user in (org.e2, org.m1, org.admin):
        assert client.get(f"/api/daily-updates/{d['log_id']}/draft", headers=auth(user)).status_code == 404
        assert confirm(client, user, d).status_code == 404


def test_future_date_rejected_and_blank_draft_rejected(client, org):
    future = (org.today + timedelta(days=2)).isoformat()
    r = client.post("/api/daily-updates/parse", json={"text": "Wrote docs", "report_date": future}, headers=auth(org.e1))
    assert r.status_code == 400
    d = parse(client, org.e1, "Wrote docs for the API")
    d["draft"]["items"] = []
    assert confirm(client, org.e1, d).status_code == 400


def test_duplicate_item_same_day_flagged(client, org):
    confirm(client, org.e1, parse(client, org.e1, "Updated the donor dashboard charts"))
    d = parse(client, org.e1, "Updated the donor dashboard charts.\nAlso answered support tickets")
    first = d["draft"]["items"][0]
    assert first["duplicate_of_item_id"] is not None and first["requires_confirmation"]
    assert d["other_updates_today"] == 1


def test_blockers_and_next_steps_notify_manager(client, org):
    text = "Worked on the import pipeline.\nBlockers:\n- Waiting for client sample file\nTomorrow:\n- Start validation rules"
    d = parse(client, org.e1, text)
    assert d["draft"]["blockers"] == ["Waiting for client sample file"]
    assert d["draft"]["next_steps"] == ["Start validation rules"]
    confirm(client, org.e1, d)
    notes = client.get("/api/notifications", headers=auth(org.m1)).json()
    assert any(n["type"] == "blocker" for n in notes)
    assert client.get("/api/notifications", headers=auth(org.m2)).json() == []


def test_edit_item_after_confirm_is_audited(client, org):
    log = confirm(client, org.e1, parse(client, org.e1, "Prepared the board deck")).json()
    item = log["items"][0]
    r = client.patch(f"/api/work-log-items/{item['id']}", json={"hours": 2, "status": "completed"}, headers=auth(org.e1))
    assert r.status_code == 200 and r.json()["hours"] == 2
    assert client.patch(f"/api/work-log-items/{item['id']}", json={"hours": 3}, headers=auth(org.m1)).status_code == 403
    hist = client.get(f"/api/work-logs/{log['id']}/history", headers=auth(org.e1)).json()
    edit = [h for h in hist if h["action"] == "edit_work_log_item"][0]
    assert edit["before"]["hours"] is None and edit["after"]["hours"] == 2


def test_work_log_visibility(client, org):
    confirm(client, org.e1, parse(client, org.e1, "Wrote unit tests for billing"))
    confirm(client, org.e3, parse(client, org.e3, "Called three CSR partners"))
    assert client.get("/api/work-logs", headers=auth(org.e2)).json()["total"] == 0
    assert client.get("/api/work-logs", headers=auth(org.m1)).json()["total"] == 1
    assert client.get("/api/work-logs", headers=auth(org.admin)).json()["total"] == 2
    assert client.get(f"/api/work-logs?employee_id={org.e3.id}", headers=auth(org.m1)).status_code == 404
