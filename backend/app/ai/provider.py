"""LLM provider interface.

Business logic never talks to the SDK directly: it calls `get_provider()` and
receives validated Pydantic objects, or an `LLMError` it can recover from.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from pydantic import ValidationError

from app.ai import prompts
from app.ai.types import (
    EMPLOYEE_NARRATIVE_SCHEMA,
    PARSE_SCHEMA,
    TEAM_NARRATIVE_SCHEMA,
    LLMEmployeeNarrative,
    LLMParsedUpdate,
    LLMTeamNarrative,
)
from app.config import get_settings

log = logging.getLogger("teamtrack.ai")


class LLMError(Exception):
    """Any failure to get a valid structured answer from the model."""


@dataclass
class ParseContext:
    employee_name: str
    report_date: date
    today: date
    text: str
    input_method: str = "paste"
    goals: list[dict] = field(default_factory=list)
    extra_tasks: list[dict] = field(default_factory=list)
    chat: list[dict] = field(default_factory=list)
    current_items: list[dict] = field(default_factory=list)


class LLMProvider(Protocol):
    mode: str  # "ai" or "fallback"

    def parse_update(self, ctx: ParseContext) -> LLMParsedUpdate: ...

    def employee_narrative(self, facts: dict) -> LLMEmployeeNarrative | None: ...

    def team_narrative(self, facts: dict) -> LLMTeamNarrative | None: ...


def _parse_user_message(ctx: ParseContext) -> str:
    context = {
        "employee": ctx.employee_name,
        "default_report_date": ctx.report_date.isoformat(),
        "today": ctx.today.isoformat(),
        "weekly_goals": ctx.goals,
        "other_open_tasks": ctx.extra_tasks,
    }
    parts = [
        "Goals and tasks assigned to this employee for the week (match work items against these codes):",
        "<context>",
        json.dumps(context, ensure_ascii=False, indent=1),
        "</context>",
        "",
        "<employee_update>",
        ctx.text,
        "</employee_update>",
    ]
    if ctx.chat:
        parts += ["", "Follow-up chat with the employee (oldest first):", "<chat>"]
        parts += [f"{m['role']}: {m['content']}" for m in ctx.chat]
        parts.append("</chat>")
    if ctx.current_items:
        parts += [
            "",
            "Work items extracted so far (update them using the chat):",
            "<current_items>",
            json.dumps(ctx.current_items, ensure_ascii=False),
            "</current_items>",
        ]
    parts.append("\nReturn the structured daily update.")
    return "\n".join(parts)


def _blank_to_none(value):
    """Strict JSON mode on some providers emits "" for optional fields; treat it as null."""
    if isinstance(value, dict):
        return {k: (None if v == "" and k != "task_title" else _blank_to_none(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_blank_to_none(v) for v in value if v != ""]
    return value


class _StructuredProvider:
    """Shared prompt building and validation. Subclasses implement `_structured`."""

    mode = "ai"
    parse_effort = "low"
    report_effort = "medium"

    def _structured(self, system: str, user: str, schema: dict, name: str, effort: str, max_tokens: int) -> dict:
        raise NotImplementedError

    def parse_update(self, ctx: ParseContext) -> LLMParsedUpdate:
        data = self._structured(
            prompts.PARSE_SYSTEM, _parse_user_message(ctx), PARSE_SCHEMA, "daily_update", self.parse_effort, 8000
        )
        try:
            return LLMParsedUpdate.model_validate(_blank_to_none(data))
        except ValidationError as exc:
            raise LLMError("The AI response did not match the expected format") from exc

    def employee_narrative(self, facts: dict) -> LLMEmployeeNarrative:
        user = "Weekly records for one employee:\n<records>\n" + json.dumps(facts, ensure_ascii=False, default=str) + "\n</records>"
        data = self._structured(prompts.REPORT_SYSTEM, user, EMPLOYEE_NARRATIVE_SCHEMA, "employee_report", self.report_effort, 16000)
        try:
            return LLMEmployeeNarrative.model_validate(_blank_to_none(data))
        except ValidationError as exc:
            raise LLMError("The AI report did not match the expected format") from exc

    def team_narrative(self, facts: dict) -> LLMTeamNarrative:
        user = "Weekly records for a team:\n<records>\n" + json.dumps(facts, ensure_ascii=False, default=str) + "\n</records>"
        data = self._structured(prompts.REPORT_SYSTEM, user, TEAM_NARRATIVE_SCHEMA, "team_report", self.report_effort, 16000)
        try:
            return LLMTeamNarrative.model_validate(_blank_to_none(data))
        except ValidationError as exc:
            raise LLMError("The AI report did not match the expected format") from exc


class AnthropicProvider(_StructuredProvider):
    def __init__(self) -> None:
        import anthropic

        s = get_settings()
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=s.anthropic_api_key) if s.anthropic_api_key else anthropic.Anthropic()
        self.model = s.llm_model
        self.use_fallbacks = s.llm_use_server_fallbacks
        self.parse_effort = s.llm_parse_effort
        self.report_effort = s.llm_report_effort

    def _structured(self, system: str, user: str, schema: dict, name: str, effort: str, max_tokens: int) -> dict:
        a = self._anthropic
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if self.use_fallbacks:
                # On a safety decline the API re-runs the request on a fallback model.
                resp = self.client.beta.messages.create(
                    **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            else:
                resp = self.client.messages.create(**kwargs)
        except a.RateLimitError as exc:
            raise LLMError("The AI service is rate limited, please retry shortly") from exc
        except a.AuthenticationError as exc:
            raise LLMError("The AI service credentials are invalid") from exc
        except a.APIStatusError as exc:
            log.warning("LLM API error %s request_id=%s", exc.status_code, getattr(exc, "request_id", None))
            raise LLMError(f"The AI service returned an error ({exc.status_code})") from exc
        except a.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service") from exc

        if resp.stop_reason == "refusal":
            raise LLMError("The AI service declined this request")
        if resp.stop_reason == "max_tokens":
            raise LLMError("The AI response was cut off")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            raise LLMError("The AI service returned no content")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("The AI service returned invalid JSON") from exc


class GroqProvider(_StructuredProvider):
    """Groq's OpenAI-compatible chat API with strict JSON-schema output."""

    def __init__(self) -> None:
        import groq

        s = get_settings()
        self._groq = groq
        self.client = groq.Groq(api_key=s.groq_api_key, max_retries=2, timeout=120)
        self.model = s.groq_model
        self.max_tokens = s.groq_max_tokens

    def _structured(self, system: str, user: str, schema: dict, name: str, effort: str, max_tokens: int) -> dict:
        g = self._groq
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
                temperature=0.2,
                max_completion_tokens=min(max_tokens, self.max_tokens),
            )
        except g.RateLimitError as exc:
            raise LLMError("The AI service is rate limited, please retry shortly") from exc
        except g.AuthenticationError as exc:
            raise LLMError("The AI service credentials are invalid") from exc
        except g.APIStatusError as exc:
            log.warning("Groq API error %s: %s", exc.status_code, str(exc)[:300])
            raise LLMError(f"The AI service returned an error ({exc.status_code})") from exc
        except g.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service") from exc

        choice = resp.choices[0] if resp.choices else None
        if choice is None or not choice.message.content:
            raise LLMError("The AI service returned no content")
        if choice.finish_reason == "length":
            raise LLMError("The AI response was cut off")
        # Reasoning models may prepend their thinking; keep only the JSON.
        text = re.sub(r"^\s*<think>.*?</think>\s*", "", choice.message.content, flags=re.S)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("The AI service returned invalid JSON") from exc


_provider: LLMProvider | None = None


def _anthropic_credentials_present() -> bool:
    s = get_settings()
    return bool(
        s.anthropic_api_key
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_PROFILE")
    )


def _build_provider() -> LLMProvider:
    from app.ai.fallback import FallbackProvider

    s = get_settings()
    choice = s.llm_provider
    if choice == "auto":
        choice = "groq" if s.groq_api_key else ("anthropic" if _anthropic_credentials_present() else "fallback")
    try:
        if choice == "groq":
            if not s.groq_api_key:
                raise ValueError("GROQ_API_KEY is not set")
            return GroqProvider()
        if choice == "anthropic":
            return AnthropicProvider()
    except Exception as exc:  # misconfigured SDK/credentials
        log.warning("AI provider unavailable, using fallback parser: %s", exc)
    return FallbackProvider()


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = _build_provider()
        log.info("LLM provider: %s", type(_provider).__name__)
    return _provider


def set_provider(provider: LLMProvider | None) -> None:
    """Override the provider (tests) or reset it (None)."""
    global _provider
    _provider = provider
