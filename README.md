# TeamTrack AI

Weekly goals, AI-assisted daily work updates and automatic weekly achievement reports.

Admins and managers assign weekly goals. Employees paste their daily status (for example, from ChatGPT) or chat with the in-app assistant. The AI turns the text into structured work items linked to their goals, and the employee reviews them before saving. At the end of the week, individual and team reports are drafted from the stored records. Managers then review, edit, approve and export them.

```
backend/    FastAPI + SQLAlchemy + Alembic + Claude API   (Python 3.11+)
frontend/   React + TypeScript + Vite + Tailwind + TanStack Query
docs/       reference-app feature study (Asana, ClickUp, Weekdone, Zoho People)
```

## Quick start (local)

Requirements: Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
# 1. Backend
cd backend
cp .env.example .env              # optional; add ANTHROPIC_API_KEY to enable AI
uv sync
uv run alembic upgrade head       # create the database (SQLite by default)
uv run python -m app.seed         # demo data (use --reset to recreate)
uv run uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                       # http://localhost:5173 (proxies /api to :8000)
```

API docs (Swagger): http://localhost:8000/docs

### Demo accounts (password `Password123!`)

| Role | Email | Notes |
|---|---|---|
| Admin | admin@teamtrack.local | Everything: people, teams, settings, all reports |
| Manager | priya@teamtrack.local | Manages *AI Products* (Arjun, Neha, Rahul) |
| Manager | vikram@teamtrack.local | Manages *Partnerships & Communications* (Ananya, Karan, Sara) |
| Employee | arjun@teamtrack.local, neha@…, rahul@…, ananya@…, karan@…, sara@… | |

Other data options (stop the backend first):

| Command | Result |
|---|---|
| `uv run python -m app.seed --reset` | Full demo with two weeks of history |
| `uv run python -m app.seed --starter` | Clean slate: 1 team, 3 employees, this week's goals, every task *Not started*, no updates. Good for testing status changes live. |
| `uv run python -m app.seed --empty` | Deletes everything except one admin login |

The full demo (`--reset`) covers last week and the current week. Last week has unfinished goals waiting in **End-of-week review**, and there are blockers, missing updates and number-based goals.

## Enabling AI

The backend reads `.env` from the project root and from `backend/` (the `backend/` file wins). With `LLM_PROVIDER=auto` it uses Groq when `GROQ_API_KEY` is set, otherwise Claude when Anthropic credentials are set, otherwise the basic parser. Restart the backend after changing `.env`. The sidebar shows **AI assistant on** when AI is active.

**Groq** (current setup):

```env
GROQ_API_KEY=gsk_...
MODEL=qwen/qwen3.8-27b
```

Groq requests use strict JSON-schema output. Empty-string fields are treated as null, any `<think>` reasoning text is removed, and every response is validated with Pydantic. Errors, invalid JSON and truncated replies fall back to the basic parser, and the user sees a warning.

**Claude**: set `ANTHROPIC_API_KEY` instead (or `LLM_PROVIDER=anthropic` to use an `ant auth login` profile).

- **Model:** `claude-opus-5-5`, configurable with `LLM_MODEL`. Parsing runs at `low` effort and reports at `medium`.
- **Structured output:** responses are constrained to a JSON schema, then validated again with Pydantic. Invalid, refused or failed responses fall back to the rule-based parser, and the user sees a warning.
- **Refusal fallbacks:** server-side fallbacks are on by default. A declined request is re-run on a fallback model. Turn this off with `LLM_USE_SERVER_FALLBACKS=false`.

Without a key, everything still works. Daily updates use a conservative rule-based parser, labelled as such, and every item must be confirmed. Reports contain record data only.

## How it works

| Module | What it does |
|---|---|
| Weekly goals | Goals have an owner, team, project, expected outcome, success criteria, priority, deadline, dependencies and blockers. Progress is measured by tasks/milestones (weighted), a numeric target, or done/not done. You can assign one goal to many people at once. Goals show as a list, board or calendar. |
| Daily update | **Paste** a report or use the **AI chat**. The parser extracts work items, hours, blockers, next steps and date, then links each item to a goal or task. Linking tries, in order: an explicit `G-12`/`T-40` reference, a title match, the LLM's suggestion (only for the employee's own records), and otherwise records it as *additional work*. Uncertain items are highlighted and must be confirmed. Nothing is written until **Save update**. |
| Progress | Rule-based, not inferred. Task status changes only when the employee confirms an item as completed or blocked. A goal completes automatically only when all of its tasks are done or its numeric target is reached. "Worked on it" never counts as done. Health (on track / at risk / off track) compares progress with the working days elapsed. |
| End-of-week review | Unfinished goals stay open until a manager chooses *carry forward*, *complete*, *defer* or *cancel*, with a reason. Carrying forward creates a linked goal for next week with the unfinished tasks. The original deadline and history are kept. |
| Reports | Facts are built from confirmed records only. The AI writes the narrative sections, and every statement must cite record ids (`I-14`, `G-3`…). Statements with unknown ids are dropped. Numbers that don't appear in the cited records, and claims that a goal is complete when it isn't, are flagged for the reviewer. Workflow: **Draft → Submitted → Approved or Returned (comment required)**. Approved reports export to PDF, Excel or Markdown. |
| Dashboards | Employee home (goals, progress, update streak, report status). Team dashboard with summary cards, team overview, goal tracking, missing-update monitor and blockers. Analytics: completion trend, update rate, recurring blockers, overdue deliverables and workload. |
| Automation | A background job runs every 15 minutes (`app/services/automation.py`). It sends daily reminders after the configured time on working days, deadline-tomorrow and overdue alerts, and drafts weekly reports on the report day with a reminder to review goals. Every notification has a dedupe key, so nothing is sent twice. Users can switch notification categories off. |
| Missing updates | Counts only configured working days, minus organization holidays, the person's leave and days before they joined. Today counts only once it is reported. It's shown as a data gap, never as a performance score. |

### Roles and data isolation

Permissions are enforced in the backend (`app/deps.py`):

- **Employees** see only their own data.
- **Managers** see themselves and members of teams they manage. They can assign goals if the setting allows, and review their team's reports, but not their own.
- **Admins** see everything.

Drafts are private to their author. Model output can only link work to the employee's own goals and tasks, and it never approves anything.

### Data model

`users`, `teams`, `team_members`, `weekly_goals`, `tasks`, `daily_work_logs` (original text kept unchanged, plus the AI draft and the confirmed version), `work_log_items`, `task_status_history`, `goal_status_history`, `weekly_reports`, `report_reviews`, `notifications`, `audit_logs`, `time_off`, `org_settings`. The migration is in `backend/alembic/versions/`.

## Tests

```bash
cd backend && uv run pytest
```

42 tests cover:

- auth and role permissions, and data isolation
- goal assignment rules
- paste parsing, confirmation and duplicate prevention
- multi-day work on one task
- linking to another employee's records (rejected)
- mocked-LLM workflows: valid output, bad JSON, refusals, and errors falling back to the basic parser
- report claim validation
- the review and approval workflow, and exports
- missing-update calendar rules
- reminder de-duplication and preferences

All LLM tests use a fake provider, so they make no network calls.

Frontend: `cd frontend && npm run build` (type-checks and builds) and `npm run lint`.

## Deploying (Railway or any Docker host)

The root `Dockerfile` builds the React app and serves it from the FastAPI backend, so one service hosts both the website (`/`) and the API (`/api`). On start it runs `alembic upgrade head`, then listens on `$PORT`. `railway.json` tells Railway to use the Dockerfile, with `/api/health` as the health check.

1. In Railway, create a project from the GitHub repo. It detects `railway.json` and builds the Dockerfile.
2. Add a **PostgreSQL** database to the project. SQLite inside a container is wiped on every redeploy.
3. Set these variables on the app service:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway reference; `postgres://` URLs are converted automatically) |
| `JWT_SECRET` | a long random string |
| `GROQ_API_KEY` / `MODEL` | your Groq key and model |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_NAME` | the first admin login, created only while the database has no users |

4. Deploy and open the generated domain. Log in as the admin, then add people and teams under **People & teams**.

Reaching `{"detail":"Not Found"}` at `/` means the website build isn't being served, usually because the service was built from the `backend` folder instead of the repo root with the Dockerfile.

## Deploying on Vercel (two projects from the same repo)

Vercel runs the backend as a serverless function. It can't store files (so no SQLite) and can't run a background timer (so reminders use a Cron Job).

**1. Backend project.** Import the repo, set **Root Directory = `backend`**. Vercel detects FastAPI in `app/main.py`. Each build runs `alembic upgrade head` (`[tool.vercel.scripts]` in `pyproject.toml`), and `backend/vercel.json` adds a daily cron at 14:00 UTC (19:30 IST). Add a Postgres database (Storage → Neon, or Supabase) and set:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Postgres connection string (`postgres://` is converted automatically) |
| `JWT_SECRET` | long random string |
| `GROQ_API_KEY`, `MODEL` | Groq key and model |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | first admin login, created only while the database is empty |
| `CRON_SECRET` | random string; Vercel sends it to `/api/cron/automation` |
| `CORS_ORIGINS` | the frontend URL, e.g. `https://teamtrack.vercel.app` |

Visiting the backend URL itself shows `{"detail":"Not Found"}`; that's expected. Check `/api/health` instead.

**2. Frontend project.** Import the same repo again, set **Root Directory = `frontend`** (Vite is detected). Set `VITE_API_URL` to the backend URL, e.g. `https://teamtrack-api.vercel.app`, then deploy. `frontend/vercel.json` makes page refreshes on routes like `/goals` load the app. Open this project's URL to use the app.

Set environment variables before deploying, or redeploy after changing them. `VITE_API_URL` is built into the frontend.

## Production notes

- Set a strong `JWT_SECRET` and a PostgreSQL `DATABASE_URL`, run `alembic upgrade head`, and serve `frontend/dist` behind the same origin, or set `CORS_ORIGINS`.
- The rate limiter and scheduler run in-process. Run a single API instance, or move them to Redis and a separate worker before scaling out.
- Notifications are in-app only. Email and Zoho Cliq delivery aren't built yet; `app/services/notifications.py:notify` is the place to add them.
- Use your database's backups (for example `pg_dump`). Retention and deletion policies aren't automated yet.

## Not built yet (next phases)

- Email / Zoho Cliq delivery for reminders, and a Cliq bot for replying with updates
- GitHub and project-management integrations (Phase 5)
- Manager comments on individual work items
- Multi-organization tenancy
- Automated data-retention policies
