import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.db import Session
from app.models import AuditLog, OrgSettings


def week_bounds(d: date) -> tuple[date, date]:
    """Monday..Sunday week containing d."""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def text_hash(text: str) -> str:
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_org_settings(db: Session) -> OrgSettings:
    s = db.get(OrgSettings, 1)
    if s is None:
        s = db.add(OrgSettings(id=1))
    return s


def org_now(db: Session) -> datetime:
    tz = get_org_settings(db).timezone
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        return datetime.now()


def org_today(db: Session) -> date:
    return org_now(db).date()


def audit(
    db: Session,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=_jsonable(before),
            after=_jsonable(after),
        )
    )


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def snapshot(obj, fields: list[str]) -> dict:
    return {f: getattr(obj, f) for f in fields}
