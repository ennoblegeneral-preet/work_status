"""Connects parsed work items to existing goals and tasks.

Order of preference:
1. explicit code in the text (G-12 / T-40)
2. exact or near-exact title match against the employee's tasks
3. the LLM's semantic suggestion (validated against the allowed set)
4. otherwise unmatched -> recorded as additional/unplanned work

Ids are only ever accepted from the employee's own goals/tasks, so model output
cannot link work to someone else's records.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models import Task, WeeklyGoal

CODE_RE = re.compile(r"\b([GT])-(\d+)\b", re.I)
STOP = {"the", "a", "an", "to", "of", "for", "and", "in", "on", "with", "on", "at", "by", "from", "my", "our"}
TITLE_MATCH = 0.82
CONFIRM_BELOW = 0.75


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split())


IRREGULAR = {"built": "build", "wrote": "write", "written": "write", "ran": "run", "sent": "send", "made": "make",
             "did": "do", "done": "do", "began": "begin", "met": "meet", "fixes": "fix"}


def _stem(t: str) -> str:
    if t in IRREGULAR:
        return IRREGULAR[t]
    for suffix, min_len in (("ing", 6), ("ed", 5), ("es", 5), ("s", 4)):
        if t.endswith(suffix) and len(t) >= min_len:
            return t[: -len(suffix)]
    return t


def _tokens(s: str) -> set[str]:
    return {_stem(t) for t in _norm(s).split() if t not in STOP and len(t) > 1}


def similarity(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return seq
    jac = len(ta & tb) / len(ta | tb)
    smaller = min(len(ta), len(tb))
    coverage = len(ta & tb) / smaller
    # one title fully containing the other ("Build CSV export" in "Started building CSV export")
    cov_score = 0.9 * coverage if smaller >= 2 else 0.6 * coverage
    return max(seq, jac, cov_score)


@dataclass
class MatchResult:
    goal_id: int | None
    task_id: int | None
    create_task: bool
    is_unplanned: bool
    confidence: float
    method: str
    note: str | None
    requires_confirmation: bool


class Matcher:
    def __init__(self, goals: list[WeeklyGoal], extra_tasks: list[Task]):
        self.goals = {g.id: g for g in goals}
        self.tasks: dict[int, Task] = {t.id: t for g in goals for t in g.tasks}
        self.tasks.update({t.id: t for t in extra_tasks})

    def _ref_id(self, ref: str | None, prefix: str) -> int | None:
        if not ref:
            return None
        m = CODE_RE.search(ref)
        if m and m.group(1).upper() == prefix:
            return int(m.group(2))
        return None

    def _best_task_by_title(self, title: str, goal_id: int | None = None) -> tuple[Task | None, float]:
        best, score = None, 0.0
        for t in self.tasks.values():
            if goal_id is not None and t.goal_id != goal_id:
                continue
            s = similarity(title, t.title)
            if s > score:
                best, score = t, s
        return best, score

    def _for_task(self, task: Task, confidence: float, method: str, note: str | None = None) -> MatchResult:
        return MatchResult(
            goal_id=task.goal_id,
            task_id=task.id,
            create_task=False,
            is_unplanned=task.goal_id is None,
            confidence=confidence,
            method=method,
            note=note,
            requires_confirmation=confidence < CONFIRM_BELOW,
        )

    def _for_goal(self, goal: WeeklyGoal, title: str, confidence: float, method: str) -> MatchResult:
        task, score = self._best_task_by_title(title, goal.id)
        if task and score >= 0.6:
            return self._for_task(task, min(confidence, max(score, 0.6)), method, f"Linked to existing task {task.code}")
        return MatchResult(
            goal_id=goal.id,
            task_id=None,
            create_task=True,
            is_unplanned=False,
            confidence=confidence,
            method=method,
            note=f"New task will be added under {goal.code}",
            requires_confirmation=confidence < CONFIRM_BELOW,
        )

    def match(
        self, title: str, text_blob: str, llm_goal_ref: str | None, llm_task_ref: str | None, llm_confidence: float
    ) -> MatchResult:
        # 1. explicit references typed by the employee
        for m in CODE_RE.finditer(text_blob or ""):
            kind, num = m.group(1).upper(), int(m.group(2))
            if kind == "T" and num in self.tasks:
                return self._for_task(self.tasks[num], 1.0, "explicit")
            if kind == "G" and num in self.goals:
                return self._for_goal(self.goals[num], title, 1.0, "explicit")

        # 2. title match
        task, score = self._best_task_by_title(title)
        if task and score >= TITLE_MATCH:
            return self._for_task(task, round(min(0.97, score), 2), "title")

        # 3. semantic suggestion from the LLM, only if it points at an allowed record
        tid = self._ref_id(llm_task_ref, "T")
        if tid in self.tasks:
            return self._for_task(self.tasks[tid], round(llm_confidence, 2), "semantic")
        gid = self._ref_id(llm_goal_ref, "G")
        if gid in self.goals:
            return self._for_goal(self.goals[gid], title, round(llm_confidence, 2), "semantic")

        # 4. weaker title match -> suggest, but ask
        if task and score >= 0.55:
            r = self._for_task(task, round(score, 2), "title", f"Possible match: {task.code} {task.title}")
            r.requires_confirmation = True
            return r

        return MatchResult(
            goal_id=None,
            task_id=None,
            create_task=True,
            is_unplanned=True,
            confidence=0.0,
            method="none",
            note="No matching goal - will be recorded as additional work",
            requires_confirmation=True,
        )
