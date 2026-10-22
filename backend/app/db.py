"""MongoDB persistence: a small unit-of-work layer over pymongo.

Models are plain Python classes (see app/models.py). A `Session` keeps an identity
map of the documents it has loaded or added, and writes nothing until `commit()`.
That keeps the request semantics the routers rely on: an exception before commit
leaves the database untouched.

- Ids are integers from a `counters` collection, so record codes (G-12, T-40) and
  URLs stay short. An id is assigned as soon as an object is added.
- Queries see the session's own pending changes: when a collection has unsaved
  changes, results are re-filtered and sorted in memory (only the operators used
  in this code base are supported: equality, $in, $nin, $ne, $gt, $gte, $lt,
  $lte, $regex, $or, $and).
- Dates are stored as midnight datetimes, datetimes as UTC with millisecond
  precision, and JSON fields round-trip through json (dict keys become strings),
  matching what the SQL JSON columns did.
"""

from __future__ import annotations

import inspect
import json
import re
import threading
import types
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, ClassVar, TypeVar, Union, get_args, get_origin

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import get_settings

T = TypeVar("T", bound="Doc")


class IntegrityError(Exception):
    """A unique index rejected a write."""


# ---------------------------------------------------------------- fields

PLAIN, DATE, DATETIME, JSON = "plain", "date", "datetime", "json"


class factory:  # noqa: N801 - reads like a keyword in model definitions
    """Default produced by calling `fn` for each new object (for mutable defaults)."""

    def __init__(self, fn):
        self.fn = fn


def _kind(tp) -> str:
    args = get_args(tp) if get_origin(tp) in (Union, types.UnionType) else (tp,)
    args = [a for a in args if a is not type(None)]
    t = args[0] if args else None
    t = get_origin(t) or t
    if t is datetime:
        return DATETIME
    if t is date:
        return DATE
    if t in (dict, list):
        return JSON
    return PLAIN


def _enc(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind == JSON:
        return json.loads(json.dumps(v, default=str))
    return _enc_scalar(v)


def _enc_scalar(v: Any) -> Any:
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v.replace(microsecond=v.microsecond // 1000 * 1000)  # BSON keeps milliseconds
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return v


def _dec(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind == DATE and isinstance(v, datetime):
        return v.date()
    if kind == DATETIME and isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
    return v


# ---------------------------------------------------------------- relationships

_registry: dict[str, type[Doc]] = {}


class BelongsTo:
    """Many-to-one: `goal.owner` loads `User` by `goal.owner_id`."""

    def __init__(self, target: str, fk: str):
        self.target, self.fk = target, fk

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        fk = getattr(obj, self.fk)
        if fk is None:
            return None
        if obj._db is None:
            rel = obj.__dict__.get("_rel_" + self.name)
            return rel if rel is not None and rel.id == fk else None
        return obj._db.get(_registry[self.target], fk)

    def __set__(self, obj, value):
        setattr(obj, self.fk, value.id if value is not None else None)
        obj.__dict__["_rel_" + self.name] = value


class HasMany:
    """One-to-many ordered by id: `goal.tasks` = tasks whose goal_id is the goal's id."""

    def __init__(self, target: str, fk: str, delete_orphan: bool = False):
        self.target, self.fk, self.delete_orphan = target, fk, delete_orphan

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        if obj._db is None:
            return obj.__dict__.setdefault("_rel_" + self.name, [])
        return obj._db._children(obj, self)

    def __set__(self, obj, value):
        value = list(value)
        db = obj._db
        if db is None:
            obj.__dict__["_rel_" + self.name] = value
            return
        keep = {id(v) for v in value}
        for child in db._children(obj, self):
            if id(child) not in keep:
                if self.delete_orphan:
                    db.delete(child)
                else:
                    setattr(child, self.fk, None)
        for child in value:
            setattr(child, self.fk, obj.id)
            if child._db is None:
                db.add(child)


# ---------------------------------------------------------------- documents


class Doc:
    __collection__: ClassVar[str]
    __fields__: ClassVar[dict[str, str]] = {}
    __defaults__: ClassVar[dict[str, Any]] = {}
    __onupdate__: ClassVar[tuple[str, ...]] = ()
    __ignore_duplicates__: ClassVar[bool] = False  # unique-index clashes on insert are skipped

    id: int | None = None

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        fields: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        for klass in reversed(cls.__mro__):
            if klass is object:
                continue
            for name, tp in inspect.get_annotations(klass, eval_str=True).items():
                if name.startswith("_") or get_origin(tp) is ClassVar:
                    continue
                fields[name] = _kind(tp)
                if name in klass.__dict__:
                    defaults[name] = klass.__dict__[name]
        cls.__fields__ = fields
        cls.__defaults__ = defaults
        cls._has_many = [v for k in reversed(cls.__mro__) for v in k.__dict__.values() if isinstance(v, HasMany)]
        _registry[cls.__name__] = cls

    def __init__(self, **kw):
        self._db: Session | None = None
        for name in self.__fields__:
            if name in kw:
                value = kw.pop(name)
            else:
                d = self.__defaults__.get(name)
                value = d.fn() if isinstance(d, factory) else d
            object.__setattr__(self, name, value)
        for name, value in kw.items():
            if not isinstance(getattr(type(self), name, None), (BelongsTo, HasMany)):
                raise TypeError(f"{type(self).__name__} has no field {name!r}")
            setattr(self, name, value)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id}>"

    def _encode(self) -> dict:
        doc = {"_id": self.id}
        for name, kind in self.__fields__.items():
            if name != "id":
                doc[name] = _enc(kind, getattr(self, name))
        return doc

    @classmethod
    def _decode(cls, doc: dict) -> Doc:
        obj = cls.__new__(cls)
        obj._db = None
        for name, kind in cls.__fields__.items():
            if name == "id":
                value = doc.get("_id")
            elif name in doc:
                value = _dec(kind, doc[name])
            else:
                d = cls.__defaults__.get(name)
                value = d.fn() if isinstance(d, factory) else d
            object.__setattr__(obj, name, value)
        return obj


# ---------------------------------------------------------------- query helpers


def _field(name: str) -> str:
    return "_id" if name == "id" else name


def _enc_filter(f: dict) -> dict:
    out = {}
    for k, v in f.items():
        if k in ("$or", "$and"):
            out[k] = [_enc_filter(x) for x in v]
        elif isinstance(v, dict) and v and all(op.startswith("$") for op in v):
            out[_field(k)] = {
                op: ([_enc_scalar(x) for x in arg] if op in ("$in", "$nin") else arg if op in ("$regex", "$options") else _enc_scalar(arg))
                for op, arg in v.items()
            }
        else:
            out[_field(k)] = _enc_scalar(v)
    return out


def _cmp_ok(val, arg) -> bool:
    return val is not None and arg is not None and type(val) is not bool and (
        isinstance(val, (int, float)) == isinstance(arg, (int, float))
    )


def _matches(doc: dict, f: dict) -> bool:
    for key, cond in f.items():
        if key == "$or":
            if not any(_matches(doc, x) for x in cond):
                return False
            continue
        if key == "$and":
            if not all(_matches(doc, x) for x in cond):
                return False
            continue
        val = doc.get(key)
        if isinstance(cond, dict) and cond and all(op.startswith("$") for op in cond):
            for op, arg in cond.items():
                if op == "$in" and val not in arg:
                    return False
                if op == "$nin" and val in arg:
                    return False
                if op == "$ne" and val == arg:
                    return False
                if op in ("$gt", "$gte", "$lt", "$lte"):
                    if not _cmp_ok(val, arg):
                        return False
                    if (op == "$gt" and not val > arg) or (op == "$gte" and not val >= arg) or (
                        op == "$lt" and not val < arg) or (op == "$lte" and not val <= arg):
                        return False
                if op == "$regex":
                    flags = re.I if "i" in cond.get("$options", "") else 0
                    if not isinstance(val, str) or not re.search(arg, val, flags):
                        return False
        elif val != cond:
            return False
    return True


def _sort_key(v):
    return (0, 0) if v is None else (1, v)


def _sort_docs(pairs: list[tuple[dict, Doc]], sort: list[tuple[str, int]]) -> list[Doc]:
    for name, direction in reversed(sort):
        pairs.sort(key=lambda p, n=_field(name): _sort_key(p[0].get(n)), reverse=direction < 0)
    return [o for _, o in pairs]


# ---------------------------------------------------------------- session


class Session:
    def __init__(self, database):
        self.database = database
        self._objs: dict[type, dict[int, Doc]] = {}
        self._snap: dict[int, dict] = {}  # id(obj) -> encoded state as last read/written
        self._new: list[Doc] = []
        self._deleted: list[Doc] = []
        self._loaded_rel: set[tuple] = set()

    # ---- plumbing

    def _coll(self, cls: type[Doc]):
        return self.database[cls.__collection__]

    def _next_id(self, cls: type[Doc]) -> int:
        row = self.database["counters"].find_one_and_update(
            {"_id": cls.__collection__}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER
        )
        return int(row["seq"])

    def _load(self, cls: type[T], doc: dict) -> T:
        bucket = self._objs.setdefault(cls, {})
        obj = bucket.get(doc["_id"])
        if obj is None:
            obj = cls._decode(doc)
            obj._db = self
            bucket[obj.id] = obj
            self._snap[id(obj)] = obj._encode()
        return obj

    def _live(self, cls: type[T]) -> list[T]:
        dead = {id(o) for o in self._deleted}
        return [o for o in self._objs.get(cls, {}).values() if id(o) not in dead]

    def _is_dirty(self, obj: Doc) -> bool:
        snap = self._snap.get(id(obj))
        return snap is None or snap != obj._encode()

    def _has_changes(self, cls: type[Doc]) -> bool:
        if any(type(o) is cls for o in self._new) or any(type(o) is cls for o in self._deleted):
            return True
        return any(self._is_dirty(o) for o in self._objs.get(cls, {}).values())

    def _children(self, parent: Doc, rel: HasMany) -> list:
        child_cls = _registry[rel.target]
        key = (type(parent), parent.id, rel.name)
        if key not in self._loaded_rel:
            if parent not in self._new:
                for d in self._coll(child_cls).find({rel.fk: parent.id}):
                    self._load(child_cls, d)
            self._loaded_rel.add(key)
        return sorted((o for o in self._live(child_cls) if getattr(o, rel.fk) == parent.id), key=lambda o: o.id)

    # ---- reads

    def get(self, cls: type[T], obj_id: int | None) -> T | None:
        if obj_id is None:
            return None
        obj = self._objs.get(cls, {}).get(int(obj_id))
        if obj is not None:
            return None if obj in self._deleted else obj
        doc = self._coll(cls).find_one({"_id": int(obj_id)})
        return self._load(cls, doc) if doc else None

    def get_many(self, cls: type[T], ids: Iterable[int]) -> dict[int, T]:
        ids = {int(i) for i in ids if i is not None}
        have = self._objs.get(cls, {})
        missing = [i for i in ids if i not in have]
        if missing:
            for d in self._coll(cls).find({"_id": {"$in": missing}}):
                self._load(cls, d)
        return {i: o for i in ids if (o := self.get(cls, i)) is not None}

    def find(
        self,
        cls: type[T],
        filter: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int | None = None,
    ) -> list[T]:
        f = _enc_filter(filter or {})
        sort = sort or [("id", 1)]
        if not self._has_changes(cls):
            cur = self._coll(cls).find(f).sort([(_field(n), d) for n, d in sort])
            if skip:
                cur = cur.skip(skip)
            if limit:
                cur = cur.limit(limit)
            return [self._load(cls, d) for d in cur]
        for d in self._coll(cls).find(f):
            self._load(cls, d)
        pairs = [(enc, o) for o in self._live(cls) if _matches(enc := o._encode(), f)]
        rows = _sort_docs(pairs, sort)
        return rows[skip: skip + limit if limit else None]

    def first(self, cls: type[T], filter: dict | None = None, sort: list[tuple[str, int]] | None = None) -> T | None:
        rows = self.find(cls, filter, sort, limit=1)
        return rows[0] if rows else None

    def exists(self, cls: type[Doc], filter: dict) -> bool:
        return self.first(cls, filter) is not None

    def count(self, cls: type[Doc], filter: dict | None = None) -> int:
        if not self._has_changes(cls):
            return self._coll(cls).count_documents(_enc_filter(filter or {}))
        return len(self.find(cls, filter))

    def preload(self, objs: Iterable[Doc], *rels: str) -> None:
        """Batch-load relationships for many objects (one query per relationship)."""
        objs = list(objs)
        for name in rels:
            for cls in {type(o) for o in objs}:
                group = [o for o in objs if type(o) is cls]
                rel = getattr(cls, name)
                if isinstance(rel, BelongsTo):
                    self.get_many(_registry[rel.target], (getattr(o, rel.fk) for o in group))
                elif isinstance(rel, HasMany):
                    todo = [o for o in group if (cls, o.id, name) not in self._loaded_rel and o not in self._new]
                    if todo:
                        child_cls = _registry[rel.target]
                        for d in self._coll(child_cls).find({rel.fk: {"$in": [o.id for o in todo]}}):
                            self._load(child_cls, d)
                    self._loaded_rel.update((cls, o.id, name) for o in group)

    # ---- writes (buffered until commit)

    def add(self, obj: Doc) -> Doc:
        if obj._db is self:
            return obj
        if obj._db is not None:
            raise ValueError(f"{obj!r} belongs to another session")
        cls = type(obj)
        if obj.id is None:
            obj.id = self._next_id(cls)
        bucket = self._objs.setdefault(cls, {})
        if obj.id in bucket:
            raise IntegrityError(f"{cls.__name__} {obj.id} already exists")
        bucket[obj.id] = obj
        obj._db = self
        self._new.append(obj)
        for rel in cls._has_many:
            for child in obj.__dict__.pop("_rel_" + rel.name, []):
                setattr(child, rel.fk, obj.id)
                self.add(child)
        return obj

    def add_all(self, objs: Iterable[Doc]) -> None:
        for o in objs:
            self.add(o)

    def delete(self, obj: Doc) -> None:
        if obj in self._new:
            self._new.remove(obj)
            self._objs[type(obj)].pop(obj.id, None)
            obj._db = None
        elif obj._db is self and obj not in self._deleted:
            self._deleted.append(obj)

    def flush(self) -> None:
        """Kept for readability at call sites: ids exist from add() and queries see pending changes."""

    def commit(self) -> None:
        for obj in list(self._new):
            enc = obj._encode()
            try:
                self._coll(type(obj)).insert_one(enc)
            except DuplicateKeyError as exc:
                if not obj.__ignore_duplicates__:
                    raise IntegrityError(str(exc)) from exc
                self._new.remove(obj)
                self._objs[type(obj)].pop(obj.id, None)
                obj._db = None
                continue
            self._new.remove(obj)
            self._snap[id(obj)] = enc
        for bucket in self._objs.values():
            for obj in bucket.values():
                snap = self._snap.get(id(obj))
                if snap is None or obj in self._deleted:
                    continue
                enc = obj._encode()
                changed = {k: v for k, v in enc.items() if snap.get(k) != v}
                if not changed:
                    continue
                for f in obj.__onupdate__:
                    if f not in changed:
                        setattr(obj, f, datetime.now(timezone.utc))
                enc = obj._encode()
                changed = {k: v for k, v in enc.items() if snap.get(k) != v}
                try:
                    self._coll(type(obj)).update_one({"_id": obj.id}, {"$set": changed})
                except DuplicateKeyError as exc:
                    raise IntegrityError(str(exc)) from exc
                self._snap[id(obj)] = enc
        for obj in self._deleted:
            self._coll(type(obj)).delete_one({"_id": obj.id})
            self._objs.get(type(obj), {}).pop(obj.id, None)
            self._snap.pop(id(obj), None)
            obj._db = None
        self._deleted.clear()

    def refresh(self, obj: Doc) -> None:
        """Reload a saved object from the database, dropping unsaved changes to it."""
        doc = self._coll(type(obj)).find_one({"_id": obj.id})
        if doc is None:
            return
        fresh = type(obj)._decode(doc)
        for name in obj.__fields__:
            object.__setattr__(obj, name, getattr(fresh, name))
        self._snap[id(obj)] = obj._encode()

    def rollback(self) -> None:
        for bucket in self._objs.values():
            for obj in bucket.values():
                obj._db = None
        self._objs.clear()
        self._snap.clear()
        self._new.clear()
        self._deleted.clear()
        self._loaded_rel.clear()

    def close(self) -> None:
        self.rollback()


# ---------------------------------------------------------------- connection

_client = None
_database = None
_lock = threading.Lock()


def _make_client(uri: str):
    if uri.startswith("mongomock://"):
        import mongomock

        return mongomock.MongoClient()
    from pymongo import MongoClient

    return MongoClient(uri, serverSelectionTimeoutMS=10000, appname="teamtrack", tz_aware=False)


def get_database():
    """The process-wide database handle (the client is reused across requests and warm serverless calls)."""
    global _client, _database
    if _database is None:
        with _lock:
            if _database is None:
                s = get_settings()
                client = _make_client(s.mongodb_uri)
                if s.mongodb_db:
                    db = client[s.mongodb_db]
                else:
                    try:
                        db = client.get_default_database(default="teamtrack")
                    except Exception:
                        db = client["teamtrack"]
                ensure_indexes(db)
                _client, _database = client, db
    return _database


def SessionLocal() -> Session:  # noqa: N802 - kept from the SQL version for call sites
    return Session(get_database())


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


INDEXES: dict[str, list[tuple[list[tuple[str, int]], dict]]] = {
    "users": [([("email", 1)], {"unique": True}), ([("role", 1)], {})],
    "teams": [([("name", 1)], {"unique": True}), ([("manager_id", 1)], {})],
    "team_members": [([("team_id", 1), ("user_id", 1)], {"unique": True}), ([("user_id", 1)], {})],
    "weekly_goals": [
        ([("owner_id", 1), ("week_start", 1)], {}),
        ([("week_start", 1), ("status", 1)], {}),
        ([("team_id", 1)], {}),
        ([("carried_from_goal_id", 1)], {}),
        ([("deadline", 1)], {}),
    ],
    "tasks": [([("goal_id", 1)], {}), ([("owner_id", 1), ("status", 1)], {}), ([("due_date", 1)], {})],
    "task_status_history": [([("task_id", 1)], {})],
    "goal_status_history": [([("goal_id", 1)], {})],
    "daily_work_logs": [
        ([("employee_id", 1), ("report_date", 1)], {}),
        ([("employee_id", 1), ("raw_text_hash", 1)], {}),
        ([("status", 1), ("report_date", 1)], {}),
    ],
    "work_log_items": [
        ([("work_log_id", 1)], {}),
        ([("goal_id", 1)], {}),
        ([("task_id", 1)], {}),
        ([("employee_id", 1), ("report_date", 1)], {}),
    ],
    "weekly_reports": [
        ([("report_type", 1), ("employee_id", 1), ("team_id", 1), ("week_start", 1)], {"unique": True}),
        ([("week_start", 1)], {}),
    ],
    "report_reviews": [([("report_id", 1)], {})],
    "notifications": [([("dedupe_key", 1)], {"unique": True}), ([("user_id", 1), ("read_at", 1)], {})],
    "audit_logs": [([("entity_type", 1), ("entity_id", 1)], {}), ([("actor_id", 1)], {})],
    "time_off": [([("day", 1), ("user_id", 1)], {})],
}


def ensure_indexes(database) -> None:
    from pymongo import IndexModel

    for coll, specs in INDEXES.items():  # one round trip per collection; existing indexes are a no-op
        database[coll].create_indexes([IndexModel(keys, **opts) for keys, opts in specs])


def drop_all(database) -> None:
    for name in [*INDEXES, "org_settings", "counters"]:
        database[name].drop()
    ensure_indexes(database)
