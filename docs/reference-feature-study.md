# Reference Feature Study: TeamTrack AI

This study looks at Asana, ClickUp, Weekdone and Zoho People to find feature and workflow ideas. It does not copy their branding, code or wording.
Researched: 2026-10-22.

## Sources and how they were retrieved

| Page | Result |
|---|---|
| Asana Goals (asana.com/features/goals-reporting/goals) | Loaded with WebFetch |
| ClickUp Goals (clickup.com/features/goals) | Loaded with WebFetch |
| ClickUp Intro to tasks (help.clickup.com, article 10552031987735) | **FAILED: HTTP 403** (bot protection). The fallback help article "Intro to Goals" also returned 403. |
| Weekdone product (weekdone.com/product) | Loaded with WebFetch |
| Weekdone getting started (weekdone.com/gettingstarted) | Loaded with WebFetch |
| Zoho People timesheet marketing page | Loaded with WebFetch |
| Zoho People timesheet service overview (help.zoho.com) | Loaded, but the page has little detail: roles only, no status values or fields |

**REA MCP tools:** REA's web tools (`inspect_web_page`, `capture_web_screenshot`, `observe_web_session`) do not open URLs themselves. They need a local Chrome DevTools (CDP) endpoint with a page already open, and no such browser was running. Because of that, all pages were fetched with WebFetch.

Items marked **[bg]** come from general product knowledge and could not be confirmed on a page that loaded. Check them before relying on them.

---

## 1. Asana Goals

**Goal hierarchy and ownership**
- Goal kinds: Objective, Key Result, and Individual goal.
- Goals "ladder up" from individual to team to company. Sub-goals split a goal into smaller pieces.
- Each goal has one owner. Visibility is either public to the whole organization or shared with chosen members. Enterprise plans add finer-grained permissions.
- Time periods: quarter, half-year, annual, or a custom range.

**Linking goals to work**
- A goal can be linked to projects, portfolios and tasks.
- When linked work is completed, the goal's progress updates automatically.

**Progress calculation** (progress source)
- Manual: the owner enters the current value.
- Automatic: rolled up from sub-goals, projects or tasks.
- External: pulled from an integration, for example Salesforce.
- **[bg]** Metric units are percentage, number and currency. Each metric has a start value, a current value and a target value.

**Statuses**
- **On track / At risk / Off track.** **[bg]** Some goals can also be marked Achieved, Partial, Missed or Dropped when they close.
- **[bg]** Status updates are posted as separate entries, each with a status colour, a summary and the current progress. They appear in a timeline on the goal.

**UI/UX patterns**
- A goal page shows a header with owner, time period and status pill. Below that sit a progress bar, the list of sub-goals and linked work, and the history of status updates.
- Dashboards show live charts of goal progress across the organization. Viewers can be given comment-only access, and teams can save their own filtered views.
- **[bg]** A "strategy map" shows the goal tree as a graph.

---

## 2. ClickUp Goals and Tasks

**Goal hierarchy and ownership**
- Goal Folders group related goals, for example sprint cycles, OKRs or **weekly employee scorecards**. Each folder shows a roll-up percentage across the goals inside it.
- A goal can have **multiple owners**, with separate view and edit permissions.
- Goals have a deadline or due date.

**Targets** (a goal has one or more targets, and progress is calculated from them)
- **Task target:** progress comes from the share of linked tasks that are closed. Tasks can come from several teams, or from a whole sprint list.
- **Number target:** a start value and a target value, with a unit.
- **True/False target:** done or not done.
- **[bg]** **Currency target:** the same as a number target but in a currency.
- The page's example of a custom target is "Create 5 posts in a week", which counts discrete units.
- **[bg]** Goal % is the average of its targets' progress. A task target counts closed tasks out of total tasks.

**Tasks** (help page failed to load, so everything here is **[bg]**)
- Fields: name, description, assignees (more than one allowed), watchers, status, priority, start date, due date, time estimate, time tracked, tags, custom fields, subtasks, checklists, dependencies (waiting on / blocking), relationships, attachments, comments, and an activity log.
- Priorities: **Urgent / High / Normal / Low**.
- Statuses are grouped as **Not started → Active → Done → Closed**. The defaults are "To Do", "In Progress" and "Complete", and each list can define its own.
- Task view layout: the main area shows the title, fields and description. A right-hand panel shows activity and comments.

**UI/UX patterns**
- The goal list has one row per goal with a progress bar, percentage, owner avatars and due date. Rows are grouped by folder.
- The goal detail page lists each target with its own small progress bar and current/target value. Values can be edited inline.

---

## 3. Weekdone (weekly check-ins and OKRs)

**Goal hierarchy**
- Levels: company, department, team and personal.
- Annual and quarterly Objectives with Key Results. KPIs are tracked as numbers. Projects and initiatives can run for several weeks.
- Goal types: "moonshot" (stretch) and "roofshot" (realistic).
- Goals are shown as a tree in which progress is coloured automatically (for example green, yellow or red by %).

**Weekly check-in using PPP (Plans, Progress, Problems)**
- Each person keeps a weekly page with three item lists:
  - **Plans:** what they will do this week or next.
  - **Progress (Done):** what they completed. A plan can be marked done.
  - **Problems:** blockers.
- Each weekly item can be **linked to an Objective/KR**.
- **[bg]** Unfinished plans carry over to the next week.
- Admins can customize the weekly planning form and set the weekly schedule (which day reports are due).
- Each week the person also gives a **job satisfaction rating** (a one-click 5-point pulse score). Pulse questions can be customized.

**Manager feedback and reminders**
- Managers can add comments and likes on items, OKRs and status updates. There is also public kudos and recognition, following the CFR model (Conversations, Feedback, Recognition).
- There is a private **1:1 space** for each manager–employee pair, which holds performance notes.
- Notifications and reminders prompt people to submit their weekly report.

**Reporting**
- **Automated weekly email reports** go to teams and the company. Quarterly and annual reports are also available.
- A dashboard shows OKR, KPI and weekly progress. It has a hierarchy view, a tree view and a **Person view** for each employee.
- Custom reports can be exported. A TV-dashboard slideshow is available.
- A social newsfeed shows recent updates.

**UI/UX patterns**
- The weekly page has three columns or sections (Plans / Progress / Problems). Each has quick "Add 1 Plan" / "Add 1 Done" inputs, and items carry an objective tag.
- The team view lists one card per member's weekly PPP. Comments and likes sit on each item.

---

## 4. Zoho People Timesheets

**Entities**
- Client → Project → Job (a task that can be assigned) → Time log → Timesheet (time logs gathered for one period).
- Jobs are either **billable** or **non-billable**.

**Logging time**
- Time can be logged manually by day, week or month, or with a built-in **timer**.
- Managers can schedule jobs for a day or week and repeat them at set intervals.
- Paid and unpaid **breaks** are tracked, and **overtime** is calculated automatically.
- **[bg]** Time log fields: date, project, job, hours (or from/to time), billable status, description, and attachment.

**Timesheet workflow**
- Timesheets cover a daily, weekly, semi-monthly or monthly period.
- A scheduler creates timesheets automatically and sends them to the right manager.
- Workflow: Employee **submits** the timesheet, then the Manager **approves or rejects** it.
- **[bg]** Statuses: Draft (not submitted), Pending/Waiting for approval, Approved, Rejected (with a reason, after which the employee can resubmit).
- **[bg]** Admin rules: whether future dates can be logged, minimum and maximum hours per day, whether past logs can be edited, and whether a description is mandatory.

**Roles** (from the docs page)
- Employee: submits time logs and timesheets.
- Manager: everything an employee can do, plus approving timesheets and scheduling jobs.
- Admin: everything a manager can do, plus settings, permissions, policies and generating bills.

**Reporting**
- A project dashboard shows jobs completed and in progress, **estimated vs logged hours**, project members and **billable hours**.
- Other reports: scheduled vs logged hours, and time planned vs time spent.
- Billing links to invoicing and accounting tools. A mobile app lets people log time, view schedules and check approval status.

---

## 5. Adopt in TeamTrack AI

Priorities: **P0** = needed for the MVP, **P1** = next release, **P2** = later.

### Weekly Goals
- **P0** Goal fields: title, description, owner (the employee), assigned-by (the admin), week (ISO week, Monday to Sunday), target type, target value, current value, unit, status, priority, and an optional link to a parent goal.
- **P0** Four target types, adapted from ClickUp:
  - **Number:** start, target and unit. Progress = (current − start) / (target − start).
  - **Yes/No:** progress is 0% or 100%.
  - **Task-based:** progress = done work items / total work items.
  - **Manual %:** the owner enters a percentage.
- **P0** Statuses, from Asana: **On track / At risk / Off track**. The AI suggests one based on progress compared with how far through the week it is (expected progress, e.g. 60% by Wednesday). The employee or manager can override it. When the week closes, the goal is marked **Achieved / Partial / Missed / Dropped**.
- **P1** Two-level hierarchy: a team or company objective (monthly or quarterly) above the weekly goals that roll up into it, using Weekdone's company/team/personal levels. Automatic roll-up of progress from child goals.
- **P1** Unfinished goals can be "carried over" to the next week in one action, and the history is kept.
- **P2** Goal templates and recurring weekly goals (for example "5 client calls/week").

### Tasks & Progress
- **P0** Work-item fields: title, description, goal_id (nullable, which means "unplanned work"), status (**Todo / In progress / Done / Blocked**), priority (**Urgent / High / Normal / Low**), estimated hours, actual hours, source (manual / ai_parsed / chat), confidence score, and date.
- **P0** Goal progress is recalculated automatically whenever a linked work item changes (a task-target roll-up).
- **P1** Dependencies and blockers. A Blocked item automatically creates a "Problem" entry in the daily or weekly update.
- **P1** Activity log on every goal and item, recording who changed what. This also serves as the audit trail for AI edits.

### Daily Work Update
- **P0** Use Weekdone's PPP structure for the AI parser's output. Each pasted or chatted update is split into **Done (Progress)**, **Plans (next)** and **Problems/Blockers**. Each item is matched to a goal with a confidence score. Unmatched items appear as "Unplanned".
- **P0** Review-before-save screen. Parsed items are shown in three sections, each with a goal dropdown, estimated hours and status, all editable inline. The employee confirms before saving. Items the AI is less sure about are highlighted.
- **P1** Plans from yesterday appear today as checkboxes for "did you finish this?", following Weekdone's plans→done flow.
- **P1** An optional daily mood or satisfaction score (1–5), from Weekdone's pulse.

### Weekly Reports & Review
- **P0** The AI generates a weekly report for each employee, with these sections:
  - goals and their final status
  - % achieved
  - work items grouped by goal
  - unplanned work
  - problems/blockers
  - hours (planned vs logged)
  - plans for next week
- **P0** Approval workflow with these states: **Draft → Submitted → Approved / Changes requested (Rejected)**. "Changes requested" requires a manager comment, and the employee can then resubmit. This follows Zoho's timesheet approval flow.
- **P0** Managers can comment on individual items or goals, inspired by Weekdone's feedback. **P1** "Like"/kudos on individual items.
- **P1** A team weekly digest shows one card per member, with team roll-up statistics. **P1** It is sent automatically by email, as in Weekdone's weekly email report.
- **P2** A private 1:1 notes space for each manager–employee pair. Export to PDF/CSV.

### Timesheet / Hours
- **P0** Hours are logged on each work item, either entered manually or estimated by the AI from the update text and confirmed by the employee. A daily total is shown, with warnings below a minimum or above a maximum (admin setting).
- **P1** Billable / non-billable flag on each item or project. Optional client/project fields, following Zoho's Client → Project → Job model.
- **P1** A weekly timesheet view as a grid (days × goals/projects). It is submitted together with the weekly report, using the same approval states.
- **P2** Timer, overtime calculation, and rules for future or past logging.

### Notifications
- **P0** A daily reminder to submit the update at a time the admin sets. A manager alert when an update is missed.
- **P0** Notifications for: goal assigned, report submitted (to the manager), report approved or changes requested (to the employee), and new comment.
- **P1** A weekly-report-due reminder on the day the admin chooses. An alert when a goal changes to At risk or Off track. A Monday notification that the week's goals have been assigned.
- **P2** Email digests (weekly team summary) and Slack/Teams delivery.

### Dashboard
- **P0** Employee dashboard: this week's goals as progress bars with status pills and the % of the week elapsed, today's update status, and hours this week.
- **P0** Manager or admin dashboard: team grid with one row per employee showing goals, average %, and update streak or missed days, plus the queue of reports waiting for approval.
- **P1** Goal-status distribution (on track / at risk / off track), planned vs actual hours, and a trend of unplanned work as a % of total.
- **P2** A goal tree view (Weekdone/Asana style), a person view with history across weeks, and a TV/slideshow mode.
