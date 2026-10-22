import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.config import get_settings
from app.routers import auth_users, daily_updates, dashboard, goals, misc, reports, teams
from app.services.automation import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("teamtrack")


def bootstrap_admin() -> None:
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD when the database has no users."""
    s = get_settings()
    if not (s.admin_email and s.admin_password):
        return
    from app.db import SessionLocal
    from app.models import Role, User
    from app.security import hash_password
    from app.utils import get_org_settings

    db = SessionLocal()
    try:
        if db.scalar(select(User.id).limit(1)) is not None:
            return
        get_org_settings(db)
        db.add(
            User(
                email=s.admin_email.strip().lower(),
                full_name=s.admin_name,
                password_hash=hash_password(s.admin_password),
                role=Role.admin,
            )
        )
        db.commit()
        log.info("Created initial admin account %s", s.admin_email)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap_admin()
    start_scheduler()
    yield
    stop_scheduler()


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built React app; unknown non-API paths return index.html (client-side routing)."""
    index = dist / "index.html"
    if not index.is_file():
        log.info("Frontend build not found at %s - serving the API only", dist)
        return
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="TeamTrack AI API",
        version="0.1.0",
        description="Weekly goals, AI-assisted daily work updates and weekly achievement reports.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    for r in (auth_users, teams, goals, daily_updates, reports, dashboard, misc):
        app.include_router(r.router, prefix="/api")

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    mount_frontend(app, Path(s.frontend_dist))  # registered last so API routes win
    return app


app = create_app()
