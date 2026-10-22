"""AI workflow with a mocked LLM provider (deterministic, no network)."""

from app.ai.provider import LLMError, set_provider
from app.ai.types import Claim, LLMEmployeeNarrative, LLMParsedUpdate, LLMWorkItem
from tests.conftest import auth, create_goal


class FakeProvider:
    mode = "ai"

    def __init__(self, parsed=None, narrative=None, error=None):
        self.parsed, self.narrative, self.error = parsed, narrative, error
        self.contexts = []

    def parse_update(self, ctx):
        self.contexts.append(ctx)
        if self.error:
            raise self.error
        return self.parsed(ctx) if callable(self.parsed) else self.parsed

    def employee_narrative(self, facts):
        if self.error:
            raise self.error
        return self.narrative(facts) if callable(self.narrative) else self.narrative

    def team_narrative(self, facts):
        return None


def item(title, **kw):
    base = dict(task_title=title, description=None, project=None, goal_ref=None, task_ref=None, status="in_progress",
                kind="activity", evidence=title, hours=None, confidence=0.0)
    return LLMWorkItem(**{**base, **kw})


def parse(client, user, text="Worked on things today"):
    r = client.post("/api/daily-updates/parse", json={"text": text}, headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def test_llm_context_contains_only_own_goals(client, org):
    mine = create_goal(client, org.m1, org.e1, org.week_start, title="My goal")
    create_goal(client, org.m1, org.e2, org.week_start, title="Someone else's goal")
    fake = FakeProvider(parsed=LLMParsedUpdate(work_items=[item("x")]))
    set_provider(fake)
    parse(client, org.e1)
    ctx = fake.contexts[0]
    assert [g["code"] for g in ctx.goals] == [f"G-{mine['id']}"]
    assert ctx.employee_name == "Employee One"


def test_semantic_match_validated_against_allowed_goals(client, org):
    mine = create_goal(client, org.m1, org.e1, org.week_start, title="Improve search", tasks=("Add fallback query",))
    other = create_goal(client, org.m1, org.e2, org.week_start, title="Foreign goal")
    parsed = LLMParsedUpdate(
        work_items=[
            item("Wrote retry logic for the agent", task_ref=f"T-{mine['tasks'][0]['id']}", confidence=0.9),
            item("Something unrelated", goal_ref=f"G-{other['id']}", confidence=0.95),  # not allowed -> ignored
            item("Tweaked search ranking", goal_ref=f"G-{mine['id']}", confidence=0.5),
        ]
    )
    set_provider(FakeProvider(parsed=parsed))
    d = parse(client, org.e1)
    a, b, c = d["draft"]["items"]
    assert a["task_id"] == mine["tasks"][0]["id"] and a["match_method"] == "semantic" and not a["requires_confirmation"]
    assert b["goal_id"] is None and b["is_unplanned"] and b["requires_confirmation"]
    assert c["goal_id"] == mine["id"] and c["create_task"] and c["requires_confirmation"]  # low confidence
    assert d["parse_mode"] == "ai"
    assert d["draft"]["needs_confirmation"]


def test_llm_error_falls_back_to_rule_parser(client, org):
    set_provider(FakeProvider(error=LLMError("The AI service is rate limited")))
    d = parse(client, org.e1, "Fixed the login bug and wrote tests. 5 hours")
    assert d["parse_mode"] == "fallback"
    assert any("rate limited" in w for w in d["draft"]["warnings"])
    assert len(d["draft"]["items"]) == 2 and d["draft"]["total_hours"] == 5


def test_invalid_llm_payload_is_rejected_by_schema():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LLMParsedUpdate.model_validate({"work_items": [{"task_title": ""}]})
    # implausible numbers are dropped, never kept
    p = LLMParsedUpdate.model_validate({"total_hours": 90, "work_items": [{"task_title": "x", "hours": -3, "confidence": 4}]})
    assert p.total_hours is None and p.work_items[0].hours is None and p.work_items[0].confidence == 1.0


def test_anthropic_provider_handles_bad_json(monkeypatch):
    from types import SimpleNamespace

    import pytest

    from app.ai import provider as prov

    p = prov.AnthropicProvider.__new__(prov.AnthropicProvider)
    import anthropic

    p._anthropic = anthropic
    p.model, p.use_fallbacks, p.parse_effort, p.report_effort = "m", False, "low", "medium"

    def fake_create(**kw):
        assert kw["output_config"]["format"]["type"] == "json_schema"
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="{not json")])

    p.client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    with pytest.raises(LLMError):
        p._structured("s", "u", {}, "t", "low", 100)

    p.client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(stop_reason="refusal", content=[])))
    with pytest.raises(LLMError):
        p._structured("s", "u", {}, "t", "low", 100)


def test_chat_turn_updates_draft_and_keeps_original_text(client, org):
    calls = {"n": 0}

    def parsed(ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMParsedUpdate(work_items=[item("Fixed search bug")], clarification_question="Which project was this for?")
        assert ctx.chat[-1] == {"role": "user", "content": "Donor IQ, and it took 3 hours"}
        return LLMParsedUpdate(project="Donor IQ", total_hours=3, work_items=[item("Fixed search bug", project="Donor IQ", status="completed", kind="outcome")])

    set_provider(FakeProvider(parsed=parsed))
    r = client.post("/api/daily-updates/parse", json={"text": "fixed search bug", "input_method": "chat"}, headers=auth(org.e1))
    d = r.json()
    assert d["chat_messages"] == [{"role": "assistant", "content": "Which project was this for?"}]
    r = client.post(f"/api/daily-updates/{d['log_id']}/chat", json={"message": "Donor IQ, and it took 3 hours"}, headers=auth(org.e1))
    d2 = r.json()
    assert d2["raw_text"] == "fixed search bug"
    assert d2["draft"]["total_hours"] == 3 and d2["draft"]["items"][0]["status"] == "completed"
    assert len(d2["chat_messages"]) == 3


def test_report_claims_without_valid_refs_are_dropped(client, org, db):
    goal = create_goal(client, org.m1, org.e1, org.week_start, tasks=("Build CSV export",))
    set_provider(FakeProvider(parsed=LLMParsedUpdate(work_items=[item("Built CSV export", task_ref=f"T-{goal['tasks'][0]['id']}", confidence=0.95, status="in_progress")])))
    d = parse(client, org.e1)
    client.post(f"/api/daily-updates/{d['log_id']}/confirm", json={"draft": d["draft"]}, headers=auth(org.e1))

    def narrative(facts):
        iref = facts["work_items"][0]["ref"]
        return LLMEmployeeNarrative(
            key_achievements=[
                Claim(text="Progressed the CSV export", refs=[iref]),
                Claim(text="Shipped a new billing system", refs=["I-9999"]),
                Claim(text="Completed the goal", refs=[f"G-{goal['id']}"]),
            ],
            overall_status=[Claim(text="Steady week", refs=[])],
        )

    set_provider(FakeProvider(narrative=narrative))
    r = client.post("/api/reports/generate", json={"week_start": org.week_start.isoformat(), "employee_id": org.e1.id}, headers=auth(org.m1))
    rep = r.json()
    assert rep["generation_mode"] == "ai"
    md = rep["content_markdown"]
    assert "Progressed the CSV export" in md
    assert "billing system" not in md and "Steady week" not in md
    warnings = " ".join(rep["validation_warnings"])
    assert "I-9999" in warnings and "no supporting record" in warnings
    assert "suggests" in warnings  # goal claimed complete while status is in_progress


def _fake_groq(content, finish_reason="stop"):
    from types import SimpleNamespace

    from app.ai import provider as prov

    p = prov.GroqProvider.__new__(prov.GroqProvider)
    import groq

    p._groq, p.model, p.max_tokens = groq, "m", 8000
    calls = []

    def create(**kw):
        calls.append(kw)
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)])

    p.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return p, calls


def test_groq_provider_strict_schema_and_blank_fields():
    import json
    from datetime import date

    from app.ai.provider import ParseContext

    payload = {
        "report_date": "", "project": "", "total_hours": 5, "blockers": [""], "next_steps": [], "clarification_question": "",
        "work_items": [{"task_title": "Fixed login bug", "description": "", "project": "", "goal_ref": "", "task_ref": "",
                        "status": "completed", "kind": "outcome", "evidence": "Fixed login bug", "hours": None, "confidence": 0.9}],
    }
    p, calls = _fake_groq("<think>reasoning</think>" + json.dumps(payload))
    out = p.parse_update(ParseContext(employee_name="x", report_date=date.today(), today=date.today(), text="Fixed login bug"))
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert out.report_date is None and out.clarification_question is None and out.blockers == []
    assert out.work_items[0].goal_ref is None and out.work_items[0].status == "completed"


def test_groq_provider_errors_become_llm_errors():
    import pytest

    p, _ = _fake_groq("not json")
    with pytest.raises(LLMError):
        p._structured("s", "u", {}, "t", "low", 100)
    p, _ = _fake_groq('{"a": 1', finish_reason="length")
    with pytest.raises(LLMError):
        p._structured("s", "u", {}, "t", "low", 100)


def test_auto_provider_prefers_groq(monkeypatch):
    from app.ai import provider as prov
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "auto")
    monkeypatch.setattr(s, "groq_api_key", "test-key")
    assert type(prov._build_provider()).__name__ == "GroqProvider"
    monkeypatch.setattr(s, "groq_api_key", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(s, "anthropic_api_key", None)
    assert type(prov._build_provider()).__name__ == "FallbackProvider"
