"""Shapes the LLM must return, as Pydantic models (for validation) and as
JSON schemas (for the API's structured-output constraint).

Numeric ranges are enforced by Pydantic after the call, because the structured
output schema subset does not support numeric bounds.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _nullable(t: str) -> dict:
    return {"anyOf": [{"type": t}, {"type": "null"}]}


# ---------------------------------------------------------------- daily update parsing


class LLMWorkItem(BaseModel):
    task_title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project: str | None = None
    goal_ref: str | None = None
    task_ref: str | None = None
    status: Literal["in_progress", "completed", "blocked"] = "in_progress"
    kind: Literal["activity", "outcome"] = "activity"
    evidence: str | None = None
    hours: float | None = None
    confidence: float = 0.0

    @field_validator("hours")
    @classmethod
    def _hours(cls, v):
        if v is not None and (v < 0 or v > 24):
            return None  # never keep an implausible number
        return v

    @field_validator("confidence")
    @classmethod
    def _conf(cls, v):
        return max(0.0, min(1.0, v))


class LLMParsedUpdate(BaseModel):
    report_date: str | None = None
    project: str | None = None
    work_items: list[LLMWorkItem] = Field(default_factory=list, max_length=50)
    total_hours: float | None = None
    blockers: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    clarification_question: str | None = None

    @field_validator("total_hours")
    @classmethod
    def _hours(cls, v):
        if v is not None and (v < 0 or v > 24):
            return None
        return v


PARSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "report_date": _nullable("string"),
        "project": _nullable("string"),
        "work_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task_title": {"type": "string"},
                    "description": _nullable("string"),
                    "project": _nullable("string"),
                    "goal_ref": _nullable("string"),
                    "task_ref": _nullable("string"),
                    "status": {"type": "string", "enum": ["in_progress", "completed", "blocked"]},
                    "kind": {"type": "string", "enum": ["activity", "outcome"]},
                    "evidence": _nullable("string"),
                    "hours": _nullable("number"),
                    "confidence": {"type": "number"},
                },
                "required": [
                    "task_title",
                    "description",
                    "project",
                    "goal_ref",
                    "task_ref",
                    "status",
                    "kind",
                    "evidence",
                    "hours",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
        "total_hours": _nullable("number"),
        "blockers": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "clarification_question": _nullable("string"),
    },
    "required": [
        "report_date",
        "project",
        "work_items",
        "total_hours",
        "blockers",
        "next_steps",
        "clarification_question",
    ],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- weekly report narrative


class Claim(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    refs: list[str] = Field(default_factory=list)


class LLMEmployeeNarrative(BaseModel):
    key_achievements: list[Claim] = Field(default_factory=list)
    in_progress_summary: list[Claim] = Field(default_factory=list)
    blockers_summary: list[Claim] = Field(default_factory=list)
    next_week_priorities: list[Claim] = Field(default_factory=list)
    overall_status: list[Claim] = Field(default_factory=list)


class LLMTeamNarrative(BaseModel):
    overview: list[Claim] = Field(default_factory=list)
    major_milestones: list[Claim] = Field(default_factory=list)
    decisions_needed: list[Claim] = Field(default_factory=list)
    cross_team_dependencies: list[Claim] = Field(default_factory=list)
    next_week_priorities: list[Claim] = Field(default_factory=list)


_CLAIMS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "refs": {"type": "array", "items": {"type": "string"}}},
        "required": ["text", "refs"],
        "additionalProperties": False,
    },
}


def _claims_schema(keys: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {k: _CLAIMS for k in keys},
        "required": keys,
        "additionalProperties": False,
    }


EMPLOYEE_NARRATIVE_SCHEMA = _claims_schema(list(LLMEmployeeNarrative.model_fields))
TEAM_NARRATIVE_SCHEMA = _claims_schema(list(LLMTeamNarrative.model_fields))
