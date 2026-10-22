from tests.conftest import auth, create_goal


def _log(client, user, text):
    d = client.post("/api/daily-updates/parse", json={"text": text}, headers=auth(user)).json()
    r = client.post(f"/api/daily-updates/{d['log_id']}/confirm", json={"draft": d["draft"]}, headers=auth(user))
    assert r.status_code == 200, r.text


def _generate(client, actor, org, **target):
    return client.post("/api/reports/generate", json={"week_start": org.week_start.isoformat(), **target}, headers=auth(actor))


def test_employee_report_from_records(client, org):
    create_goal(client, org.m1, org.e1, org.week_start, tasks=("Build CSV export", "Write export tests"))
    _log(client, org.e1, "Built CSV export and deployed it. Also helped support with a refund query. 6 hours\nBlockers:\n- Waiting for QA environment")
    r = _generate(client, org.m1, org, employee_id=org.e1.id)
    assert r.status_code == 200, r.text
    rep = r.json()
    md = rep["content_markdown"]
    assert rep["status"] == "draft" and rep["generation_mode"] == "fallback"
    for heading in ("1. Weekly Goals", "2. Key Achievements", "3. Work Completed", "4. In-Progress Work", "5. Blockers and Challenges",
                    "6. Additional Work", "7. Next Week's Priorities", "8. Time Summary", "9. Overall Status"):
        assert heading in md
    assert "1 of 2 tasks completed" in md
    assert "Waiting for QA environment" in md
    assert "6.0 hours reported" in md
    assert "no AI summary" in md


def test_employee_can_generate_only_own_report(client, org):
    assert _generate(client, org.e1, org, employee_id=org.e1.id).status_code == 200
    assert _generate(client, org.e1, org, employee_id=org.e2.id).status_code == 404
    assert _generate(client, org.m2, org, employee_id=org.e1.id).status_code == 404
    assert _generate(client, org.m1, org, employee_id=org.e1.id, team_id=org.t1.id).status_code == 422


def test_review_workflow(client, org):
    rep = _generate(client, org.e1, org, employee_id=org.e1.id).json()
    rid = rep["id"]
    # employee edits own draft, then submits
    r = client.put(f"/api/reports/{rid}/content", json={"content_markdown": rep["content_markdown"] + "\nExtra note"}, headers=auth(org.e1))
    assert r.status_code == 200 and r.json()["edited_by_human"]
    assert client.post(f"/api/reports/{rid}/approve", json={}, headers=auth(org.e1)).status_code == 403  # no self-approval
    assert client.post(f"/api/reports/{rid}/submit", json={}, headers=auth(org.e1)).json()["status"] == "submitted"
    assert any(n["type"] == "report_review" for n in client.get("/api/notifications", headers=auth(org.m1)).json())
    # cannot regenerate while under review; return needs a comment
    assert _generate(client, org.m1, org, employee_id=org.e1.id).status_code == 409
    assert client.post(f"/api/reports/{rid}/return", json={}, headers=auth(org.m1)).status_code == 422
    r = client.post(f"/api/reports/{rid}/return", json={"comment": "Add hours for Tuesday"}, headers=auth(org.m1))
    assert r.json()["status"] == "returned"
    assert client.post(f"/api/reports/{rid}/submit", json={}, headers=auth(org.e1)).json()["status"] == "submitted"
    assert client.post(f"/api/reports/{rid}/approve", json={}, headers=auth(org.m2)).status_code == 404  # other team's manager
    r = client.post(f"/api/reports/{rid}/approve", json={"comment": "Thanks"}, headers=auth(org.m1))
    assert r.json()["status"] == "approved" and r.json()["approved_by_id"] == org.m1.id
    assert [x["action"] for x in r.json()["reviews"]] == ["generate", "edit", "submit", "return", "submit", "approve"]
    # approved reports are locked
    assert client.put(f"/api/reports/{rid}/content", json={"content_markdown": "x"}, headers=auth(org.m1)).status_code == 409
    assert _generate(client, org.m1, org, employee_id=org.e1.id).status_code == 409


def test_exports_only_for_approved(client, org):
    create_goal(client, org.m1, org.e1, org.week_start)
    _log(client, org.e1, "Built CSV export – handled “edge cases” → done")
    rid = _generate(client, org.m1, org, employee_id=org.e1.id).json()["id"]
    assert client.get(f"/api/reports/{rid}/export?format=pdf", headers=auth(org.m1)).status_code == 409
    client.post(f"/api/reports/{rid}/approve", json={}, headers=auth(org.m1))
    pdf = client.get(f"/api/reports/{rid}/export?format=pdf", headers=auth(org.m1))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    xlsx = client.get(f"/api/reports/{rid}/export?format=xlsx", headers=auth(org.e1))
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    md = client.get(f"/api/reports/{rid}/export?format=md", headers=auth(org.e1))
    assert md.text.startswith("# Weekly Work Status Report")
    assert "attachment" in md.headers["content-disposition"]
    assert client.get(f"/api/reports/{rid}/export?format=pdf", headers=auth(org.e2)).status_code == 404


def test_team_report(client, org):
    create_goal(client, org.m1, org.e1, org.week_start, title="Ship export", dependencies="Needs design team sign-off")
    create_goal(client, org.m1, org.e2, org.week_start, title="Fix login", tasks=("Fix login bug",))
    _log(client, org.e2, "Fixed login bug and deployed")
    assert _generate(client, org.m2, org, team_id=org.t1.id).status_code == 404
    r = _generate(client, org.m1, org, team_id=org.t1.id)
    assert r.status_code == 200
    md = r.json()["content_markdown"]
    assert "Team Weekly Report: Team 1" in md
    assert "Employee Two** - 1/1 goals completed" in md
    assert "Needs design team sign-off" in md
    assert "9. Missing or Incomplete Reporting Data" in md
    rid = r.json()["id"]
    assert client.post(f"/api/reports/{rid}/submit", json={}, headers=auth(org.m1)).status_code == 400
    assert client.post(f"/api/reports/{rid}/approve", json={}, headers=auth(org.m1)).json()["status"] == "approved"
    assert client.get(f"/api/reports/{rid}", headers=auth(org.e1)).status_code == 404  # team report is for managers


def test_dashboards(client, org):
    create_goal(client, org.m1, org.e1, org.week_start)
    _log(client, org.e1, "Built CSV export")
    me = client.get("/api/dashboard/me", headers=auth(org.e1)).json()
    assert me["submitted_today"] and me["summary"]["goals"] == 1
    ov = client.get("/api/dashboard/overview", headers=auth(org.m1)).json()
    assert ov["cards"]["total_employees"] == 2 and ov["cards"]["active_goals"] == 1
    assert {r["name"] for r in ov["team_overview"]} == {"Employee One", "Employee Two"}
    assert client.get("/api/dashboard/overview", headers=auth(org.e1)).status_code == 403
    assert client.get(f"/api/dashboard/overview?team_id={org.t2.id}", headers=auth(org.m1)).status_code == 404
    an = client.get("/api/dashboard/analytics?weeks=4", headers=auth(org.admin)).json()
    assert len(an["weeks"]) == 4 and {w["name"] for w in an["workload"]} >= {"Employee One"}
