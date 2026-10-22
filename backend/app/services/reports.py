"""Weekly report generation.

1. Facts are built deterministically from stored, confirmed records.
2. The LLM writes only narrative sections, and every claim must cite record refs.
3. Claims are validated against the facts; unsupported ones are dropped and flagged.
4. The Markdown is assembled in code, marking AI text separately from record data.
The result is saved as a draft for human review; nothing here approves anything.
"""

import json
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from app.ai.provider import LLMError, get_provider
from app.ai.types import Claim
from app.db import Session
from app.models import (
    DailyWorkLog,
    GoalStatus,
    LogStatus,
    ReportReview,
    ReportStatus,
    ReportType,
    Team,
    TeamMember,
    User,
    WeeklyGoal,
    WeeklyReport,
)
from app.services.goals import employee_week_goals
from app.services.missing import missing_for_user
from app.services.progress import goal_health, goal_progress
from app.utils import get_org_settings, org_today, week_bounds

LABEL = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "completed": "Completed",
    "deferred": "Deferred",
    "cancelled": "Cancelled",
    "on_track": "On track",
    "at_risk": "At risk",
    "off_track": "Off track",
}


def _d(d: date) -> str:
    return d.strftime("%a %d %b %Y")


def _lbl(s: str | None) -> str:
    return LABEL.get(s or "", s or "-")


def _esc(s: str | None) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


# ---------------------------------------------------------------- facts


def _goal_fact(g: WeeklyGoal, today: date, working_days: list[int]) -> dict:
    p = goal_progress(g)
    return {
        "ref": g.code,
        "owner": g.owner.full_name if g.owner else None,
        "owner_ref": f"E-{g.owner_id}",
        "title": g.title,
        "project": g.project,
        "expected_outcome": g.expected_outcome,
        "success_criteria": g.success_criteria,
        "status": g.status,
        "progress_percent": p,
        "health": goal_health(g, today, working_days, p),
        "deadline": g.deadline.isoformat() if g.deadline else None,
        "original_deadline": g.original_deadline.isoformat() if g.original_deadline else None,
        "carried_from": f"G-{g.carried_from_goal_id}" if g.carried_from_goal_id else None,
        "carry_forward_reason": g.carry_forward_reason,
        "target": (
            {"type": g.target_type, "target": g.target_value, "current": g.current_value, "unit": g.unit}
            if g.target_type == "number"
            else {"type": g.target_type}
        ),
        "dependencies": g.dependencies,
        "blockers": g.blockers,
        "tasks": [{"ref": t.code, "title": t.title, "status": t.status, "weight": t.weight} for t in g.tasks],
    }


def _week_logs(db: Session, employee_id: int, ws: date, we: date) -> list[DailyWorkLog]:
    logs = db.find(
        DailyWorkLog,
        {"employee_id": employee_id, "report_date": {"$gte": ws, "$lte": we}, "status": LogStatus.confirmed},
        sort=[("report_date", 1), ("id", 1)],
    )
    db.preload(logs, "items")
    return logs


def employee_facts(db: Session, employee: User, week_start: date) -> dict:
    ws, we = week_bounds(week_start)
    s = get_org_settings(db)
    today = org_today(db)
    goals = employee_week_goals(db, employee.id, ws)
    logs = _week_logs(db, employee.id, ws, we)

    items, blockers, next_steps = [], [], []
    hours_by_day: dict[date, float | None] = {}
    for log in logs:
        for it in log.items:
            items.append(
                {
                    "ref": f"I-{it.id}",
                    "date": it.report_date.isoformat(),
                    "project": it.project,
                    "goal": f"G-{it.goal_id}" if it.goal_id else None,
                    "task": f"T-{it.task_id}" if it.task_id else None,
                    "title": it.task_title,
                    "description": it.description,
                    "status": it.status,
                    "kind": it.kind,
                    "hours": it.hours,
                    "unplanned": it.goal_id is None,
                }
            )
        for n, b in enumerate(log.blockers or []):
            blockers.append({"ref": f"B-{log.id}-{n}", "date": log.report_date.isoformat(), "text": b})
        for n, ns in enumerate(log.next_steps or []):
            next_steps.append({"ref": f"N-{log.id}-{n}", "date": log.report_date.isoformat(), "text": ns})
        if log.total_hours is not None:
            hours_by_day[log.report_date] = (hours_by_day.get(log.report_date) or 0) + log.total_hours
        else:
            hours_by_day.setdefault(log.report_date, None)

    cov = missing_for_user(db, employee, ws, we, include_today=today > we)
    carried_next = db.find(WeeklyGoal, {"carried_from_goal_id": {"$in": [g.id for g in goals]}, "owner_id": employee.id})
    known_hours = [h for h in hours_by_day.values() if h is not None]
    return {
        "employee": {
            "ref": f"E-{employee.id}",
            "name": employee.full_name,
            "department": employee.department,
            "job_title": employee.job_title,
        },
        "period": {"start": ws.isoformat(), "end": we.isoformat()},
        "goals": [_goal_fact(g, today, s.working_days) for g in goals],
        "work_items": items,
        "blockers": blockers,
        "next_steps": next_steps,
        "carried_forward_next_week": [
            {"ref": g.code, "from": f"G-{g.carried_from_goal_id}", "title": g.title, "reason": g.carry_forward_reason}
            for g in carried_next
        ],
        "time": {
            "total_reported_hours": round(sum(known_hours), 2) if known_hours else None,
            "days_with_hours": len(known_hours),
            "days_with_updates": len(hours_by_day),
        },
        "reporting": {
            "expected_days": cov["expected_days"],
            "reported_days": cov["reported_days"],
            "missing_dates": [d.isoformat() for d in cov["missing_dates"]],
        },
    }


def team_members(db: Session, team: Team) -> list[User]:
    ids = [m.user_id for m in db.find(TeamMember, {"team_id": team.id})]
    return db.find(User, {"id": {"$in": ids}, "is_active": True}, sort=[("full_name", 1), ("id", 1)])


def team_facts(db: Session, team: Team, week_start: date) -> dict:
    ws, we = week_bounds(week_start)
    members = []
    goals, items, blockers, next_steps, carried = [], [], [], [], []
    for u in team_members(db, team):
        f = employee_facts(db, u, ws)
        goals += f["goals"]
        items += [dict(i, owner_ref=f"E-{u.id}") for i in f["work_items"]]
        blockers += [dict(b, owner_ref=f"E-{u.id}") for b in f["blockers"]]
        next_steps += [dict(n, owner_ref=f"E-{u.id}") for n in f["next_steps"]]
        carried += [dict(c, owner_ref=f"E-{u.id}") for c in f["carried_forward_next_week"]]
        st = [g["status"] for g in f["goals"]]
        members.append(
            {
                "ref": f"E-{u.id}",
                "name": u.full_name,
                "job_title": u.job_title,
                "goals_total": len(st),
                "goals_completed": st.count("completed"),
                "goals_in_progress": st.count("in_progress"),
                "goals_blocked": st.count("blocked"),
                "time": f["time"],
                "reporting": f["reporting"],
            }
        )
    next_week = db.find(
        WeeklyGoal,
        {"owner_id": {"$in": [int(m["ref"][2:]) for m in members]}, "week_start": ws + timedelta(days=7)},
    )
    return {
        "team": {"name": team.name, "department": team.department, "manager": team.manager.full_name if team.manager else None},
        "period": {"start": ws.isoformat(), "end": we.isoformat()},
        "members": members,
        "goals": goals,
        "work_items": items,
        "blockers": blockers,
        "next_steps": next_steps,
        "carried_forward_next_week": carried,
        "next_week_goals": [{"ref": g.code, "owner_ref": f"E-{g.owner_id}", "title": g.title} for g in next_week],
    }


# ---------------------------------------------------------------- validation


def _ref_index(facts: dict) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    if "employee" in facts:
        idx[facts["employee"]["ref"]] = facts["employee"]
    for key in ("members", "goals", "work_items", "blockers", "next_steps", "carried_forward_next_week", "next_week_goals"):
        for row in facts.get(key, []):
            idx[row["ref"]] = row
            if key == "goals":
                for t in row.get("tasks", []):
                    idx[t["ref"]] = t
    return idx


NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
COMPLETION_RE = re.compile(r"\b(completed|finished|achieved|delivered|done)\b", re.I)


def validate_claims(section: str, claims: list[Claim], idx: dict[str, dict], warnings: list[str]) -> list[Claim]:
    kept: list[Claim] = []
    for c in claims:
        refs = [r.strip() for r in c.refs if r.strip() in idx]
        bad = [r for r in c.refs if r.strip() not in idx]
        if bad:
            warnings.append(f"{section}: removed unknown references {', '.join(bad)}.")
        if not refs:
            warnings.append(f"{section}: dropped a statement with no supporting record: \"{c.text[:120]}\"")
            continue
        source = json.dumps([idx[r] for r in refs], default=str)
        for n in NUM_RE.findall(c.text):
            if n not in source and not re.search(rf"[GTIBNE]-{re.escape(n)}\b", c.text):
                warnings.append(f"{section}: the number {n} in \"{c.text[:100]}\" does not appear in the cited records.")
                break
        for r in refs:
            fact = idx[r]
            if r.startswith("G-") and COMPLETION_RE.search(c.text) and fact.get("status") != GoalStatus.completed:
                warnings.append(
                    f"{section}: \"{c.text[:100]}\" suggests {r} is complete, but its recorded status is {_lbl(fact.get('status'))}."
                )
        kept.append(Claim(text=c.text.strip(), refs=refs))
    return kept


# ---------------------------------------------------------------- markdown


AI_TAG = "_AI summary, drafted from the cited records:_"
REC_TAG = "_From employee updates and goal records:_"


def _claims_md(claims: list[dict]) -> list[str]:
    return [f"- {c['text']} `[{', '.join(c['refs'])}]`" for c in claims]


def _hours_line(t: dict) -> str:
    if not t["days_with_hours"]:
        return "No hours were reported this week."
    total = t["total_reported_hours"]
    if t["days_with_hours"] < t["days_with_updates"]:
        missing = t["days_with_updates"] - t["days_with_hours"]
        return (
            f"{total} hours reported on {t['days_with_hours']} of {t['days_with_updates']} updated days. "
            f"Hours are missing for {missing} day(s), so this total is incomplete."
        )
    return f"{total} hours reported across {t['days_with_hours']} day(s)."


def _coverage_line(r: dict) -> str:
    line = f"Daily updates submitted on {r['reported_days']} of {r['expected_days']} expected working day(s)."
    if r["missing_dates"]:
        line += " No update recorded for: " + ", ".join(_d(date.fromisoformat(d)) for d in r["missing_dates"]) + "."
    return line


def _goal_result(g: dict, items: list[dict]) -> str:
    parts = []
    tasks = [t for t in g["tasks"] if t["status"] != "cancelled"]
    if g["target"]["type"] == "number":
        tgt = g["target"]
        parts.append(f"{tgt.get('current') or 0} / {tgt.get('target')} {tgt.get('unit') or ''}".strip())
    elif tasks:
        done = sum(1 for t in tasks if t["status"] == "completed")
        parts.append(f"{done} of {len(tasks)} tasks completed")
    outcomes = [i["title"] for i in items if i["goal"] == g["ref"] and (i["kind"] == "outcome" or i["status"] == "completed")]
    if outcomes:
        parts.append("Delivered: " + "; ".join(outcomes[:3]))
    elif not any(i["goal"] == g["ref"] for i in items):
        parts.append("No work recorded")
    return ". ".join(parts)


def employee_markdown(facts: dict, ai: dict | None, mode: str) -> str:
    e, p = facts["employee"], facts["period"]
    items = facts["work_items"]
    L = [
        "# Weekly Work Status Report",
        "",
        f"**Employee:** {e['name']}  ",
        f"**Department:** {e.get('department') or '-'}  ",
        f"**Reporting Period:** {_d(date.fromisoformat(p['start']))} – {_d(date.fromisoformat(p['end']))}",
        "",
        "> " + (
            "Sections marked *AI summary* were drafted by AI and cite record ids in brackets. Everything else is taken directly from stored records."
            if ai
            else "This report was assembled from stored records only (no AI summary)."
        ),
        "",
        "### 1. Weekly Goals",
        "",
    ]
    if facts["goals"]:
        L += ["| Goal | Expected outcome | Actual result | Status | Progress |", "|---|---|---|---|---|"]
        for g in facts["goals"]:
            L.append(
                f"| {g['ref']} {_esc(g['title'])} | {_esc(g['expected_outcome']) or '-'} | {_esc(_goal_result(g, items))} | "
                f"{_lbl(g['status'])} | {g['progress_percent']:.0f}% |"
            )
    else:
        L.append("No goals were assigned for this week.")

    L += ["", "### 2. Key Achievements", ""]
    if ai and ai.get("key_achievements"):
        L += [AI_TAG, *_claims_md(ai["key_achievements"])]
    else:
        outs = [i for i in items if i["kind"] == "outcome" or i["status"] == "completed"]
        L += [REC_TAG, *[f"- {i['title']} `[{i['ref']}]`" for i in outs]] if outs else ["No completed deliverables were recorded."]

    L += ["", "### 3. Work Completed", ""]
    done = [i for i in items if i["status"] == "completed" or i["kind"] == "outcome"]
    if done:
        L.append(REC_TAG)
        by_proj: dict[str, list[dict]] = {}
        for i in done:
            by_proj.setdefault(i["project"] or "General", []).append(i)
        for proj, rows in by_proj.items():
            L.append(f"\n**{proj}**")
            L += [f"- {date.fromisoformat(i['date']).strftime('%a')}: {i['title']}" + (f" ({i['goal']})" if i["goal"] else "") + f" `[{i['ref']}]`" for i in rows]
    else:
        L.append("No completed work was recorded.")

    L += ["", "### 4. In-Progress Work", ""]
    open_tasks = [
        (g, t) for g in facts["goals"] for t in g["tasks"] if t["status"] in ("in_progress", "blocked", "not_started")
        and g["status"] not in ("cancelled",)
    ]
    if open_tasks:
        L.append(REC_TAG)
        L += [f"- {t['ref']} {t['title']} ({g['ref']}) - {_lbl(t['status'])}" for g, t in open_tasks]
    wip_unplanned = [i for i in items if i["unplanned"] and i["status"] == "in_progress"]
    L += [f"- {i['title']} (additional work) - In progress `[{i['ref']}]`" for i in wip_unplanned]
    if ai and ai.get("in_progress_summary"):
        L += ["", AI_TAG, *_claims_md(ai["in_progress_summary"])]
    if not open_tasks and not wip_unplanned and not (ai and ai.get("in_progress_summary")):
        L.append("No unfinished work recorded.")

    L += ["", "### 5. Blockers and Challenges", ""]
    blocked_items = [i for i in items if i["status"] == "blocked"]
    if facts["blockers"] or blocked_items:
        L.append(REC_TAG)
        L += [f"- {date.fromisoformat(b['date']).strftime('%a')}: {b['text']} `[{b['ref']}]`" for b in facts["blockers"]]
        L += [f"- Blocked: {i['title']} `[{i['ref']}]`" for i in blocked_items]
    else:
        L.append("No blockers were reported.")
    if ai and ai.get("blockers_summary"):
        L += ["", AI_TAG, *_claims_md(ai["blockers_summary"])]

    L += ["", "### 6. Additional Work", ""]
    unplanned = [i for i in items if i["unplanned"]]
    if unplanned:
        L.append(REC_TAG)
        L += [f"- {i['title']} - {_lbl(i['status'])} `[{i['ref']}]`" for i in unplanned]
    else:
        L.append("No unplanned work was recorded.")

    L += ["", "### 7. Next Week's Priorities", ""]
    if facts["carried_forward_next_week"]:
        L.append("**Carried forward (confirmed in goal review):**")
        L += [f"- {c['ref']} {c['title']} (from {c['from']}): {c['reason'] or ''}" for c in facts["carried_forward_next_week"]]
    if facts["next_steps"]:
        L.append("**Next steps recorded in daily updates:**")
        L += [f"- {n['text']} `[{n['ref']}]`" for n in facts["next_steps"][-8:]]
    if ai and ai.get("next_week_priorities"):
        L += ["", AI_TAG, *_claims_md(ai["next_week_priorities"])]
    if not facts["carried_forward_next_week"] and not facts["next_steps"] and not (ai and ai.get("next_week_priorities")):
        L.append("No next steps were recorded.")

    L += ["", "### 8. Time Summary", "", _hours_line(facts["time"]), "", _coverage_line(facts["reporting"])]

    L += ["", "### 9. Overall Status", ""]
    st = [g["status"] for g in facts["goals"]]
    L.append(
        f"{REC_TAG} {st.count('completed')} of {len(st)} goal(s) completed, {st.count('in_progress')} in progress, "
        f"{st.count('blocked')} blocked, {st.count('not_started')} not started."
    )
    if ai and ai.get("overall_status"):
        L += ["", AI_TAG, *_claims_md(ai["overall_status"])]
    return "\n".join(L) + "\n"


def team_markdown(facts: dict, ai: dict | None, mode: str) -> str:
    t, p = facts["team"], facts["period"]
    names = {m["ref"]: m["name"] for m in facts["members"]}
    goals = facts["goals"]
    st = [g["status"] for g in goals]
    L = [
        f"# Team Weekly Report: {t['name']}",
        "",
        f"**Manager:** {t.get('manager') or '-'}  ",
        f"**Reporting Period:** {_d(date.fromisoformat(p['start']))} – {_d(date.fromisoformat(p['end']))}  ",
        f"**Team members:** {len(facts['members'])}",
        "",
        "> " + (
            "Sections marked *AI summary* were drafted by AI and cite record ids in brackets. Everything else is taken directly from stored records."
            if ai
            else "This report was assembled from stored records only (no AI summary)."
        ),
        "",
        "### 1. Overall Team Goals and Outcomes",
        "",
        f"{REC_TAG} {len(goals)} goal(s): {st.count('completed')} completed, {st.count('in_progress')} in progress, "
        f"{st.count('blocked')} blocked, {st.count('not_started')} not started, {st.count('deferred')} deferred.",
    ]
    if ai and ai.get("overview"):
        L += ["", AI_TAG, *_claims_md(ai["overview"])]
    if goals:
        L += ["", "| Owner | Goal | Status | Progress | Health |", "|---|---|---|---|---|"]
        L += [
            f"| {names.get(g['owner_ref'], g['owner'])} | {g['ref']} {_esc(g['title'])} | {_lbl(g['status'])} | {g['progress_percent']:.0f}% | {_lbl(g['health'])} |"
            for g in goals
        ]

    L += ["", "### 2. Employee-wise Achievements", ""]
    for m in facts["members"]:
        outs = [i for i in facts["work_items"] if i["owner_ref"] == m["ref"] and (i["kind"] == "outcome" or i["status"] == "completed")]
        L.append(f"**{m['name']}** - {m['goals_completed']}/{m['goals_total']} goals completed")
        L += [f"- {i['title']} `[{i['ref']}]`" for i in outs] or ["- No completed deliverables recorded."]
        L.append("")

    L += ["### 3. Completed and Pending Deliverables", ""]
    comp = [g for g in goals if g["status"] == "completed"]
    pend = [g for g in goals if g["status"] in ("not_started", "in_progress", "blocked")]
    L.append("**Completed:**")
    L += [f"- {g['ref']} {g['title']} ({names.get(g['owner_ref'], '')})" for g in comp] or ["- None"]
    L.append("\n**Pending:**")
    L += [f"- {g['ref']} {g['title']} ({names.get(g['owner_ref'], '')}) - {g['progress_percent']:.0f}%, {_lbl(g['health'])}" for g in pend] or ["- None"]

    L += ["", "### 4. Major Milestones", ""]
    if ai and ai.get("major_milestones"):
        L += [AI_TAG, *_claims_md(ai["major_milestones"])]
    else:
        L += [f"- {g['ref']} {g['title']} completed" for g in comp] or ["No milestones recorded."]

    L += ["", "### 5. Cross-team Dependencies", ""]
    deps = [g for g in goals if g.get("dependencies")]
    L += [f"- {g['ref']} {g['title']}: {g['dependencies']}" for g in deps] or ["No dependencies recorded."]
    if ai and ai.get("cross_team_dependencies"):
        L += ["", AI_TAG, *_claims_md(ai["cross_team_dependencies"])]

    L += ["", "### 6. Blockers Requiring Management Decisions", ""]
    if facts["blockers"]:
        L.append(REC_TAG)
        L += [f"- {names.get(b['owner_ref'], '')}, {date.fromisoformat(b['date']).strftime('%a')}: {b['text']} `[{b['ref']}]`" for b in facts["blockers"]]
    else:
        L.append("No blockers were reported.")
    if ai and ai.get("decisions_needed"):
        L += ["", AI_TAG, *_claims_md(ai["decisions_needed"])]

    L += ["", "### 7. Work Carried Forward", ""]
    L += [f"- {c['ref']} {c['title']} ({names.get(c['owner_ref'], '')}), from {c['from']}: {c['reason'] or ''}" for c in facts["carried_forward_next_week"]] or [
        "Nothing has been carried forward yet (unfinished goals may still be awaiting review)."
    ]

    L += ["", "### 8. Priorities for the Coming Week", ""]
    if facts["next_week_goals"]:
        L.append(f"{len(facts['next_week_goals'])} goal(s) already assigned for next week:")
        L += [f"- {g['ref']} {g['title']} ({names.get(g['owner_ref'], '')})" for g in facts["next_week_goals"]]
    if ai and ai.get("next_week_priorities"):
        L += ["", AI_TAG, *_claims_md(ai["next_week_priorities"])]
    if not facts["next_week_goals"] and not (ai and ai.get("next_week_priorities")):
        L.append("No priorities recorded yet.")

    L += ["", "### 9. Missing or Incomplete Reporting Data", ""]
    gaps = []
    for m in facts["members"]:
        r, tm = m["reporting"], m["time"]
        if r["missing_dates"]:
            gaps.append(f"- {m['name']}: no update on " + ", ".join(date.fromisoformat(d).strftime("%a %d %b") for d in r["missing_dates"]))
        if tm["days_with_updates"] and tm["days_with_hours"] < tm["days_with_updates"]:
            gaps.append(f"- {m['name']}: hours missing for {tm['days_with_updates'] - tm['days_with_hours']} updated day(s)")
    L += gaps or ["All expected updates were submitted."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- generation


def _find_report(db: Session, rtype: str, week_start: date, employee_id: int | None, team_id: int | None) -> WeeklyReport | None:
    return db.first(
        WeeklyReport,
        {"report_type": rtype, "week_start": week_start, "employee_id": employee_id or None, "team_id": team_id or None},
    )


def generate(
    db: Session,
    actor: User | None,
    week_start: date,
    employee: User | None = None,
    team: Team | None = None,
) -> WeeklyReport:
    ws, we = week_bounds(week_start)
    rtype = ReportType.employee if employee else ReportType.team
    report = _find_report(db, rtype, ws, employee.id if employee else None, team.id if team else None)
    if report and report.status == ReportStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "This report is already approved and cannot be regenerated")
    if report and report.status == ReportStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "This report is awaiting review. Return it before regenerating.")

    facts = employee_facts(db, employee, ws) if employee else team_facts(db, team, ws)
    provider = get_provider()
    warnings: list[str] = []
    ai_dict = None
    mode = provider.mode
    try:
        narrative = provider.employee_narrative(facts) if employee else provider.team_narrative(facts)
    except LLMError as exc:
        narrative = None
        mode = "fallback"
        warnings.append(f"AI summary unavailable ({exc}). The report contains record data only.")
    if narrative is not None:
        idx = _ref_index(facts)
        ai_dict = {}
        for section, claims in narrative:
            ai_dict[section] = [c.model_dump() for c in validate_claims(section.replace("_", " ").capitalize(), claims, idx, warnings)]
    elif mode == "fallback" and not warnings:
        warnings.append("AI is not configured. The report contains record data only.")

    md = employee_markdown(facts, ai_dict, mode) if employee else team_markdown(facts, ai_dict, mode)
    if report is None:
        report = WeeklyReport(
            report_type=rtype,
            employee_id=employee.id if employee else None,
            team_id=team.id if team else None,
            week_start=ws,
            week_end=we,
            version=1,
        )
        db.add(report)
    else:
        report.version += 1
    report.status = ReportStatus.draft
    report.generation_mode = "ai" if ai_dict is not None else "fallback"
    report.facts = json.loads(json.dumps(facts, default=str))
    report.ai_summary = ai_dict or {}
    report.validation_warnings = warnings
    report.content_markdown = md
    report.edited_by_human = False
    report.generated_by_id = actor.id if actor else None
    report.approved_by_id = None
    report.approved_at = None
    if actor:
        db.add(ReportReview(report_id=report.id, reviewer_id=actor.id, action="generate", comment=f"Version {report.version}"))
    return report


def mark_approved(report: WeeklyReport, actor: User) -> None:
    report.status = ReportStatus.approved
    report.approved_by_id = actor.id
    report.approved_at = datetime.now(timezone.utc)
