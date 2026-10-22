"""Rule-based parser used when no LLM is configured or the LLM call fails.

It is intentionally conservative: it splits the text into work items, extracts
explicitly stated hours/dates/blockers/next steps, and leaves goal matching to the
deterministic matcher. Every item it produces must be confirmed by the employee.
"""

import re
from datetime import date

from app.ai.provider import ParseContext
from app.ai.types import LLMParsedUpdate, LLMWorkItem

OUTCOME_WORDS = (
    "fixed", "completed", "complete", "done", "deployed", "finished", "resolved", "merged",
    "shipped", "released", "delivered", "sent", "submitted", "published", "closed", "launched",
)
BLOCKER_WORDS = ("blocked", "blocker", "waiting for", "waiting on", "stuck", "dependency on", "unable to", "couldn't", "could not")
NEXT_WORDS = ("tomorrow", "next step", "next steps", "will ", "plan to", "planning to", "going to", "to do next")
VERB_HINT = re.compile(
    r"^(?:i\s+)?(?:\w+ed|\w+ing|built|wrote|made|sent|met|did|ran|set up|began|fixed|added|tested|reviewed|"
    r"created|updated|implemented|deployed|prepared|called|completed|started|worked)\b",
    re.I,
)
FOLLOW_UP_RE = re.compile(r"^\w+(?:\s+(?:it|them|this|that|the changes?|the fix|everything))?$", re.I)
HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", re.I)
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DMY_DATE_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦]|\d+[.)]|[a-z][.)])\s+", re.I)
HEADER_RE = re.compile(r"^\s*[#*_ ]*([A-Za-z][A-Za-z /&'-]{1,40})[*_ ]*:\s*$")


def _clean(s: str) -> str:
    s = BULLET_RE.sub("", s).strip()
    s = re.sub(r"^[*_#]+|[*_]+$", "", s).strip()
    return s


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if p.strip()]


def _split_actions(sentence: str) -> list[str]:
    """'Fixed X, added Y, and tested Z.' -> ['Fixed X', 'added Y', 'tested Z']."""
    sentence = sentence.rstrip(".!; ")
    chunks: list[str] = []
    for piece in re.split(r"\s*(?:,|;)\s*(?:and\s+)?", sentence):
        parts = re.split(r"\s+and\s+", piece)
        cur = parts[0]
        for nxt in parts[1:]:
            if VERB_HINT.match(nxt):
                chunks.append(cur)
                cur = nxt
            else:
                cur = f"{cur} and {nxt}"
        chunks.append(cur)
    out: list[str] = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue
        if out and FOLLOW_UP_RE.match(c):
            out[-1] = f"{out[-1]} and {c}"  # "...and deployed it" continues the same piece of work
        elif out and not VERB_HINT.match(c):
            out[-1] = f"{out[-1]}, {c}"
        else:
            out.append(c)
    return out


def _title(chunk: str) -> str:
    t = re.sub(r"^(?:today\s+)?i\s+(?:have\s+)?", "", chunk.strip(), flags=re.I)
    t = t[:1].upper() + t[1:]
    return t if len(t) <= 90 else t[:87].rstrip() + "..."


def _has(text: str, words) -> bool:
    low = f" {text.lower()} "
    return any(w in low for w in words)


def parse_text(ctx: ParseContext) -> LLMParsedUpdate:
    text = ctx.text
    user_chat = [m["content"] for m in ctx.chat if m.get("role") == "user"]
    if user_chat:
        text = text + "\n" + "\n".join(user_chat)

    report_date = None
    if m := ISO_DATE_RE.search(text):
        report_date = m.group(1)
    elif m := DMY_DATE_RE.search(text):
        try:
            report_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            report_date = None

    known_projects = {g["project"] for g in ctx.goals if g.get("project")}
    project = next((p for p in sorted(known_projects, key=len, reverse=True) if p.lower() in text.lower()), None)

    items: list[LLMWorkItem] = []
    blockers: list[str] = []
    next_steps: list[str] = []
    hours_mentions: list[float] = []
    total_hours = None
    section = "work"

    lines = [ln for ln in text.splitlines() if ln.strip()]
    for line in lines:
        if h := HEADER_RE.match(line):
            name = h.group(1).lower()
            if any(k in name for k in ("block", "issue", "challenge", "problem", "risk")):
                section = "blockers"
            elif any(k in name for k in ("next", "tomorrow", "plan")):
                section = "next"
            elif any(k in name for k in ("date", "name", "employee")):
                continue
            else:
                section = "work"
            continue
        line = _clean(line)
        if not line or re.match(r"^(date|name|employee|reporting date)\s*[:\-]", line, re.I):
            continue
        for sentence in _split_sentences(line):
            hours = [float(x) for x in HOURS_RE.findall(sentence)]
            is_total = bool(re.search(r"\btotal\b|\boverall\b|\bin all\b", sentence, re.I))
            hours_only = bool(hours) and len(re.sub(r"[^\w\s]", "", HOURS_RE.sub("", sentence)).split()) <= 3
            if hours and (is_total or hours_only):
                total_hours = hours[0]
                continue
            hours_mentions.extend(hours)

            if section == "blockers" or _has(sentence, BLOCKER_WORDS):
                blockers.append(sentence.rstrip("."))
                pure_blocker = re.match(r"^(?:i\s+am\s+|i'm\s+|still\s+)?(?:waiting|blocked|stuck|need|needs|unable|couldn't|could not)\b", sentence, re.I)
                if section == "blockers" or pure_blocker:
                    continue  # a statement of a blocker, not a piece of work
            if section == "next" or (_has(sentence, NEXT_WORDS) and not _has(sentence, OUTCOME_WORDS)):
                next_steps.append(sentence.rstrip("."))
                continue

            for chunk in _split_actions(sentence):
                ctx_match = re.match(r"^(?:i\s+)?(?:worked|working|was working) on (.+?)(?: today)?$", chunk, re.I)
                if ctx_match and ctx_match.group(1).strip().lower() in {p.lower() for p in known_projects}:
                    continue  # "worked on <project> today" is context, not a work item
                outcome = _has(chunk, OUTCOME_WORDS)
                blocked = _has(chunk, BLOCKER_WORDS)
                chunk_hours = [float(x) for x in HOURS_RE.findall(chunk)]
                items.append(
                    LLMWorkItem(
                        task_title=_title(re.sub(r"\(\s*\)", "", HOURS_RE.sub("", chunk)).strip(" ,-(") or chunk),
                        description=None,
                        project=project,
                        goal_ref=None,
                        task_ref=None,
                        status="blocked" if blocked else ("completed" if outcome else "in_progress"),
                        kind="outcome" if outcome else "activity",
                        evidence=chunk,
                        hours=chunk_hours[0] if len(chunk_hours) == 1 else None,
                        confidence=0.0,
                    )
                )

    if total_hours is None and len(items) == 1 and items[0].hours is None and len(hours_mentions) == 1:
        # A single-item update with one stated duration: that duration is the item's.
        items[0].hours = hours_mentions[0]

    return LLMParsedUpdate(
        report_date=report_date,
        project=project,
        work_items=items[:50],
        total_hours=total_hours,
        blockers=blockers,
        next_steps=next_steps,
        clarification_question=None,
    )


class FallbackProvider:
    mode = "fallback"

    def parse_update(self, ctx: ParseContext) -> LLMParsedUpdate:
        return parse_text(ctx)

    def employee_narrative(self, facts: dict):
        return None

    def team_narrative(self, facts: dict):
        return None
