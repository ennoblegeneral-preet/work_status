"""Load realistic demo data: 1 admin, 2 managers, 6 employees, 2 teams,
goals for last week and this week, and daily updates confirmed through the real
workflow (so task/goal status history is produced the same way as in the app).

Usage:  uv run python -m app.seed            (refuses if users exist)
        uv run python -m app.seed --reset    (wipe everything, load the full demo with history)
        uv run python -m app.seed --starter  (wipe everything, fresh week of goals, nothing logged)
        uv run python -m app.seed --empty    (wipe everything, keep only an admin login)
"""

import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import (
    DailyWorkLog,
    GoalStatus,
    LogStatus,
    Role,
    Task,
    Team,
    TeamMember,
    User,
    WeeklyGoal,
)
from app.schemas import Draft, DraftItem
from app.security import hash_password
from app.services.daily_updates import confirm
from app.utils import get_org_settings, org_today, text_hash, week_bounds

PASSWORD = "Password123!"


def _user(db, email, name, role, dept, title):
    u = User(
        email=email, full_name=name, password_hash=hash_password(PASSWORD), role=role, department=dept, job_title=title,
        created_at=datetime.now(timezone.utc) - timedelta(days=90),
    )
    db.add(u)
    db.flush()
    return u


def _goal(db, owner, team, ws, title, project, outcome, criteria, tasks, priority="medium", deadline_offset=4, creator=None, **kw):
    g = WeeklyGoal(
        title=title, owner_id=owner.id, team_id=team.id, project=project, week_start=ws, week_end=ws + timedelta(days=6),
        expected_outcome=outcome, success_criteria=criteria, priority=priority, start_date=ws,
        deadline=ws + timedelta(days=deadline_offset), original_deadline=ws + timedelta(days=deadline_offset),
        created_by_id=creator.id if creator else None, **kw,
    )
    db.add(g)
    db.flush()
    for t in tasks:
        db.add(Task(goal_id=g.id, owner_id=owner.id, title=t, project=project, created_by_id=g.created_by_id))
    db.flush()
    db.refresh(g)
    return g


def _t(goal, idx):
    return goal.tasks[idx]


def _log(db, emp, day, text, items, hours=None, blockers=(), next_steps=()):
    """items: (title, status, kind, goal|None, task|None, hours|None, evidence)"""
    log = DailyWorkLog(
        employee_id=emp.id, report_date=day, input_method="paste", raw_text=text, raw_text_hash=text_hash(text),
        parse_mode="seed", parsed_draft={}, status=LogStatus.draft,
    )
    db.add(log)
    db.flush()
    draft = Draft(
        report_date=day,
        items=[
            DraftItem(
                task_title=title, status=st, kind=kind, goal_id=g.id if g else None, task_id=t.id if t else None,
                create_task=g is None, is_unplanned=g is None, hours=h, evidence=ev,
                project=(g.project if g else None), confidence=1.0 if g else 0.0, match_method="explicit" if g else "none",
            )
            for title, st, kind, g, t, h, ev in items
        ],
        total_hours=hours,
        blockers=list(blockers),
        next_steps=list(next_steps),
    )
    confirm(db, log, emp, draft)
    log.confirmed_at = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=13)


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.scalar(select(User.id)):
            print("Users already exist - run with --reset to recreate demo data.")
            return
        s = get_org_settings(db)
        s.org_name = "Ennoble Demo Org"
        today = org_today(db)
        ws, _ = week_bounds(today)
        lw = ws - timedelta(days=7)

        admin = _user(db, "admin@teamtrack.local", "Asha Kapoor", Role.admin, "Leadership", "Operations Director")
        priya = _user(db, "priya@teamtrack.local", "Priya Sharma", Role.manager, "Technology", "Engineering Manager")
        vikram = _user(db, "vikram@teamtrack.local", "Vikram Rao", Role.manager, "Partnerships", "Partnerships Lead")
        arjun = _user(db, "arjun@teamtrack.local", "Arjun Mehta", Role.employee, "Technology", "AI Engineer")
        neha = _user(db, "neha@teamtrack.local", "Neha Gupta", Role.employee, "Technology", "Full-stack Developer")
        rahul = _user(db, "rahul@teamtrack.local", "Rahul Verma", Role.employee, "Technology", "Backend Developer")
        ananya = _user(db, "ananya@teamtrack.local", "Ananya Iyer", Role.employee, "Partnerships", "Partnerships Associate")
        karan = _user(db, "karan@teamtrack.local", "Karan Singh", Role.employee, "Partnerships", "Communications Executive")
        sara = _user(db, "sara@teamtrack.local", "Sara Khan", Role.employee, "Partnerships", "Program Coordinator")

        ai_team = Team(name="AI Products", department="Technology", manager_id=priya.id)
        ops_team = Team(name="Partnerships & Communications", department="Partnerships", manager_id=vikram.id)
        db.add_all([ai_team, ops_team])
        db.flush()
        for u in (arjun, neha, rahul):
            db.add(TeamMember(team_id=ai_team.id, user_id=u.id))
        for u in (ananya, karan, sara):
            db.add(TeamMember(team_id=ops_team.id, user_id=u.id))
        db.flush()

        # ---------------- last week
        lw_days = [lw + timedelta(days=i) for i in range(5)]
        a1 = _goal(db, arjun, ai_team, lw, "Stabilise Scoring Agent", "Interview AI", "Scores match rubric on the test set",
                   "No scoring errors on 50 sample interviews", ["Fix rubric weighting bug", "Add regression tests for scoring"], "high", creator=priya)
        a2 = _goal(db, arjun, ai_team, lw, "Interviewer Agent guardrails", "Interview AI", "Agent refuses off-topic prompts",
                   "Guardrail test suite passes", ["Draft guardrail policy", "Implement guardrail checks", "Run red-team prompts"], creator=priya)
        n1 = _goal(db, neha, ai_team, lw, "Donor IQ search improvements", "Donor IQ", "Faster, more relevant donor search",
                   "Search returns results under 2s", ["Add search filters UI", "Optimise search query"], "high", creator=priya)
        r1 = _goal(db, rahul, ai_team, lw, "Donor IQ data import pipeline", "Donor IQ", "CSV donor import working end to end",
                   "Import 10k rows without errors", ["Build CSV parser", "Validate and deduplicate rows", "Import progress UI"], creator=priya)
        an1 = _goal(db, ananya, ops_team, lw, "CSR partner outreach", "Partnerships", "Meetings booked with new CSR partners",
                    "5 meetings booked", [], target_type="number", target_value=5, current_value=0, unit="meetings", creator=vikram)
        k1 = _goal(db, karan, ops_team, lw, "Monthly newsletter", "Communications", "October newsletter sent",
                   "Sent to full mailing list", ["Collect stories", "Design newsletter", "Send newsletter"], creator=vikram)
        s1 = _goal(db, sara, ops_team, lw, "Volunteer onboarding kit", "Programs", "Onboarding kit ready for volunteers",
                   "Kit approved by program lead", ["Write onboarding guide", "Prepare training slides"], creator=vikram)

        _log(db, arjun, lw_days[0], "Fixed the rubric weighting bug in the Scoring Agent and started regression tests. 7 hours.",
             [("Fix rubric weighting bug", "completed", "outcome", a1, _t(a1, 0), None, "Fixed the rubric weighting bug"),
              ("Regression tests for scoring", "in_progress", "activity", a1, _t(a1, 1), None, "started regression tests")], 7)
        _log(db, arjun, lw_days[1], "Finished scoring regression tests (42 cases). Drafted guardrail policy. 8h",
             [("Regression tests for scoring", "completed", "outcome", a1, _t(a1, 1), None, "Finished scoring regression tests"),
              ("Draft guardrail policy", "completed", "outcome", a2, _t(a2, 0), None, "Drafted guardrail policy")], 8)
        _log(db, arjun, lw_days[2], "Implemented guardrail checks in the Interviewer Agent. Waiting for red-team prompt set from QA.",
             [("Implement guardrail checks", "completed", "outcome", a2, _t(a2, 1), None, "Implemented guardrail checks")],
             None, ["Waiting for red-team prompt set from QA"], ["Run red-team prompts once received"])
        _log(db, arjun, lw_days[3], "Ran partial red-team prompts, 3 failures logged. Reviewed PRs for Neha. 7.5 hours total.",
             [("Run red-team prompts", "in_progress", "activity", a2, _t(a2, 2), None, "Ran partial red-team prompts"),
              ("Code review for Donor IQ search", "completed", "activity", None, None, 1.5, "Reviewed PRs for Neha")], 7.5)

        _log(db, neha, lw_days[0], "Built the search filters UI for Donor IQ. 6h",
             [("Add search filters UI", "completed", "outcome", n1, _t(n1, 0), 6, "Built the search filters UI")], 6)
        _log(db, neha, lw_days[1], "Profiling search query, found missing index on donors table.",
             [("Optimise search query", "in_progress", "activity", n1, _t(n1, 1), None, "Profiling search query")])
        _log(db, neha, lw_days[3], "Added index and rewrote search query, results now 1.4s. Deployed to staging. 7 hours",
             [("Optimise search query", "completed", "outcome", n1, _t(n1, 1), None, "rewrote search query, results now 1.4s")], 7)

        _log(db, rahul, lw_days[0], "Built CSV parser for donor import. 8h",
             [("Build CSV parser", "completed", "outcome", r1, _t(r1, 0), 8, "Built CSV parser")], 8)
        _log(db, rahul, lw_days[2], "Working on validation and dedup rules for imported rows. Blocked on sample data from the client.",
             [("Validate and deduplicate rows", "blocked", "activity", r1, _t(r1, 1), None, "Working on validation and dedup rules")],
             None, ["Need sample donor data from the client"])
        _log(db, rahul, lw_days[4], "Dedup logic done using test data, still waiting for real client sample.",
             [("Validate and deduplicate rows", "in_progress", "activity", r1, _t(r1, 1), None, "Dedup logic done using test data")],
             None, ["Still waiting for client sample data"])

        an1.current_value = 3
        _log(db, ananya, lw_days[1], "Booked 2 CSR meetings (Tata Trust follow-up, HDFC CSR). 6 hours",
             [("CSR partner meetings", "in_progress", "outcome", an1, None, None, "Booked 2 CSR meetings")], 6)
        _log(db, ananya, lw_days[3], "Booked 1 more CSR meeting and prepared the partnership deck.",
             [("CSR partner meetings", "in_progress", "outcome", an1, None, None, "Booked 1 more CSR meeting"),
              ("Partnership deck", "completed", "outcome", None, None, None, "prepared the partnership deck")])
        _log(db, karan, lw_days[0], "Collected 4 stories for the newsletter.",
             [("Collect stories", "completed", "outcome", k1, _t(k1, 0), None, "Collected 4 stories")], 5)
        _log(db, karan, lw_days[2], "Designed newsletter in Mailchimp and sent it to the full list. 7h",
             [("Design newsletter", "completed", "outcome", k1, _t(k1, 1), None, "Designed newsletter"),
              ("Send newsletter", "completed", "outcome", k1, _t(k1, 2), None, "sent it to the full list")], 7)
        _log(db, sara, lw_days[1], "Wrote volunteer onboarding guide draft.",
             [("Write onboarding guide", "completed", "outcome", s1, _t(s1, 0), None, "Wrote volunteer onboarding guide draft")], 6)

        # ---------------- this week
        tw_days = [ws + timedelta(days=i) for i in range(5) if ws + timedelta(days=i) < today]
        a3 = _goal(db, arjun, ai_team, ws, "Phone detection for proctoring", "Interview AI", "Detect phone use during interviews",
                   "90% detection on labelled clips", ["Collect labelled clips", "Train detection model", "Integrate with interview flow"],
                   "high", creator=priya)
        a4 = _goal(db, arjun, ai_team, ws, "Close red-team findings", "Interview AI", "All red-team failures fixed",
                   "0 open red-team failures", ["Fix prompt-injection failure", "Fix off-topic failure", "Re-run red-team suite"], creator=priya)
        n2 = _goal(db, neha, ai_team, ws, "Donor IQ fallback search", "Donor IQ", "Search falls back when the AI agent fails",
                   "Fallback query used on agent errors", ["Add fallback query", "Error monitoring for search agent"], "high", creator=priya)
        r2 = _goal(db, rahul, ai_team, ws, "Finish donor import", "Donor IQ", "Client data imported",
                   "Client sample imported with 0 errors", ["Import client sample", "Import progress UI"], creator=priya,
                   dependencies="Client must share the donor sample file")
        an2 = _goal(db, ananya, ops_team, ws, "CSR proposal submissions", "Partnerships", "Proposals submitted to booked partners",
                    "2 proposals submitted", [], target_type="number", target_value=2, current_value=0, unit="proposals", creator=vikram)
        k2 = _goal(db, karan, ops_team, ws, "Annual report design brief", "Communications", "Brief shared with design agency",
                   "Brief approved by Vikram", ["Draft brief", "Collect photos"], creator=vikram)
        s2 = _goal(db, sara, ops_team, ws, "Volunteer training session", "Programs", "First training held",
                   "Session held with 10+ volunteers", ["Book venue", "Send invites", "Run session"], creator=vikram)

        if len(tw_days) >= 1:
            d = tw_days[0]
            _log(db, arjun, d, "Collected 120 labelled clips for phone detection and fixed the prompt-injection red-team failure. 8 hours",
                 [("Collect labelled clips", "completed", "outcome", a3, _t(a3, 0), None, "Collected 120 labelled clips"),
                  ("Fix prompt-injection failure", "completed", "outcome", a4, _t(a4, 0), None, "fixed the prompt-injection red-team failure")], 8)
            _log(db, neha, d, "Added fallback query to the search agent and deployed to staging. 6h",
                 [("Add fallback query", "completed", "outcome", n2, _t(n2, 0), None, "Added fallback query to the search agent")], 6)
            _log(db, rahul, d, "Still no client sample. Built the import progress UI meanwhile.",
                 [("Import progress UI", "completed", "outcome", r2, _t(r2, 1), None, "Built the import progress UI")],
                 None, ["Client donor sample still not received - needs escalation"])
            _log(db, ananya, d, "Drafted CSR proposal for HDFC.",
                 [("HDFC CSR proposal", "in_progress", "activity", an2, None, None, "Drafted CSR proposal for HDFC")], 5)
            _log(db, karan, d, "Drafted the annual report design brief.",
                 [("Draft brief", "completed", "outcome", k2, _t(k2, 0), None, "Drafted the annual report design brief")], 6)
            _log(db, sara, d, "Booked the community hall for Saturday training.",
                 [("Book venue", "completed", "outcome", s2, _t(s2, 0), None, "Booked the community hall")], 4)
        if len(tw_days) >= 2:
            d = tw_days[1]
            _log(db, arjun, d, "Started training the phone detection model, first run 78% accuracy.",
                 [("Train detection model", "in_progress", "activity", a3, _t(a3, 1), None, "first run 78% accuracy")], 7)
            _log(db, neha, d, "Set up error monitoring for search agent errors (Sentry alerts).",
                 [("Error monitoring for search agent", "in_progress", "activity", n2, _t(n2, 1), None, "Set up error monitoring")], 7)
            _log(db, ananya, d, "Submitted HDFC CSR proposal. Started Tata Trust proposal. 7 hours",
                 [("HDFC CSR proposal", "completed", "outcome", an2, None, None, "Submitted HDFC CSR proposal"),
                  ("Tata Trust proposal", "in_progress", "activity", an2, None, None, "Started Tata Trust proposal")], 7)
            an2.current_value = 1
            _log(db, sara, d, "Sent invites to 25 volunteers for the training session.",
                 [("Send invites", "completed", "outcome", s2, _t(s2, 1), None, "Sent invites to 25 volunteers")], 5,
                 next_steps=["Confirm attendance by Friday"])
        if len(tw_days) >= 3:
            d = tw_days[2]
            _log(db, arjun, d, "Tuned the detection model, now 86%. Paired with Neha on search agent retries. 8h",
                 [("Train detection model", "in_progress", "activity", a3, _t(a3, 1), None, "Tuned the detection model, now 86%"),
                  ("Pairing on search agent retries", "completed", "activity", None, None, 1, "Paired with Neha")], 8,
                 next_steps=["Push model above 90% with more clips"])
            _log(db, neha, d, "Error monitoring live in staging. Waiting on DevOps for production alert channel.",
                 [("Error monitoring for search agent", "blocked", "activity", n2, _t(n2, 1), None, "Waiting on DevOps")], 6,
                 ["Waiting on DevOps for production alert channel"])
            _log(db, karan, d, "Collected 30 photos from field teams for the annual report.",
                 [("Collect photos", "completed", "outcome", k2, _t(k2, 1), None, "Collected 30 photos")], 5)
        for g in db.scalars(select(WeeklyGoal)):
            if g.status == GoalStatus.not_started and g.week_start == lw:
                g.status = GoalStatus.in_progress
        db.commit()
        print(f"Seeded demo data. Log in as admin@teamtrack.local / {PASSWORD} (see README for other accounts).")
    finally:
        db.close()


def _wipe() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed_empty() -> None:
    """Delete all data and keep only one admin login."""
    _wipe()
    db = SessionLocal()
    try:
        get_org_settings(db)
        _user(db, "admin@teamtrack.local", "Asha Kapoor", Role.admin, "Leadership", "Operations Director")
        db.commit()
        print(f"All data cleared. Log in as admin@teamtrack.local / {PASSWORD} to add people, teams and goals.")
    finally:
        db.close()


def seed_starter() -> None:
    """Delete all data, then create one team with this week's goals and tasks.

    Every task starts as 'Not started' and nothing has been logged, so you can
    submit daily updates as an employee and watch task and goal status change.
    Accounts are created today, so earlier days don't count as missing updates.
    """
    _wipe()
    db = SessionLocal()
    try:
        s = get_org_settings(db)
        s.org_name = "Ennoble Demo Org"
        ws, _ = week_bounds(org_today(db))
        now = datetime.now(timezone.utc)

        def user(email, name, role, title):
            u = _user(db, email, name, role, "Technology", title)
            u.created_at = now
            return u

        admin = user("admin@teamtrack.local", "Asha Kapoor", Role.admin, "Operations Director")
        priya = user("priya@teamtrack.local", "Priya Sharma", Role.manager, "Engineering Manager")
        arjun = user("arjun@teamtrack.local", "Arjun Mehta", Role.employee, "AI Engineer")
        neha = user("neha@teamtrack.local", "Neha Gupta", Role.employee, "Full-stack Developer")
        rahul = user("rahul@teamtrack.local", "Rahul Verma", Role.employee, "Backend Developer")
        team = Team(name="AI Products", department="Technology", manager_id=priya.id)
        db.add(team)
        db.flush()
        for u in (arjun, neha, rahul):
            db.add(TeamMember(team_id=team.id, user_id=u.id))
        db.flush()

        _goal(db, arjun, team, ws, "Phone detection for proctoring", "Interview AI", "Detect phone use during interviews",
              "90% detection on labelled clips", ["Collect labelled clips", "Train detection model", "Integrate with interview flow"],
              "high", creator=priya)
        _goal(db, arjun, team, ws, "Scoring Agent fixes", "Interview AI", "Scores match the rubric",
              "No scoring errors on the test set", ["Fix scoring error", "Add regression tests for scoring"], creator=priya)
        _goal(db, neha, team, ws, "Donor IQ fallback search", "Donor IQ", "Search falls back when the AI agent fails",
              "Fallback query used on agent errors", ["Add fallback query", "Error monitoring for search agent", "Deploy to production"],
              "high", creator=priya)
        _goal(db, neha, team, ws, "Donor list improvements", "Donor IQ", "Faster, easier donor list",
              "Pagination and filters live", ["Fix donor list pagination", "Add search filters"], creator=priya)
        _goal(db, rahul, team, ws, "Donor CSV import", "Donor IQ", "Client donor data imported",
              "10k rows imported without errors", ["Build CSV parser", "Validate and deduplicate rows", "Import progress UI"],
              creator=priya)
        _goal(db, rahul, team, ws, "Client onboarding calls", "Donor IQ", "Pilot clients onboarded",
              "3 onboarding calls done", [], target_type="number", target_value=3, current_value=0, unit="calls", creator=priya)
        db.commit()
        print("Starter data ready: 1 team, 3 employees, 6 goals for this week, all tasks Not started, no updates yet.")
        print(f"Employees: arjun@ / neha@ / rahul@teamtrack.local  Manager: priya@  Admin: admin@  (password {PASSWORD})")
    finally:
        db.close()


if __name__ == "__main__":
    if "--empty" in sys.argv:
        seed_empty()
    elif "--starter" in sys.argv:
        seed_starter()
    else:
        seed(reset="--reset" in sys.argv)
