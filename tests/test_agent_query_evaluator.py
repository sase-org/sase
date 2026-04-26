"""Tests for the agent query evaluator (Phase 2)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from sase.ace.agent_query import (
    AndExpr,
    DurationCompare,
    NotExpr,
    OrExpr,
    PropertyMatch,
    StringMatch,
    evaluate_agent_query,
    parse_agent_query,
)
from sase.ace.tui.models.agent import Agent, AgentType


# --- Fixtures ----------------------------------------------------------------


_NOW = datetime(2026, 4, 26, 12, 0, 0)


def _make_agent(**overrides: Any) -> Agent:
    """Build an :class:`Agent` with minimal required fields, overridden by kwargs.

    The model has many optional fields; we set only what tests touch and
    rely on the dataclass defaults for everything else.
    """
    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "my_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "RUNNING",
        "start_time": _NOW - timedelta(hours=1),
    }
    defaults.update(overrides)
    return Agent(**defaults)


def _eval(query: str, agent: Agent, *, now: datetime = _NOW) -> bool:
    """Parse + evaluate, no content cache."""
    return evaluate_agent_query(parse_agent_query(query), agent, now=now)


# --- Bare-word + text: substring matches -------------------------------------


def test_bare_word_matches_metadata_substring() -> None:
    agent = _make_agent(cl_name="frontend_login_fix")
    assert _eval("login", agent)


def test_bare_word_is_case_insensitive() -> None:
    agent = _make_agent(cl_name="LoginFix")
    assert _eval("login", agent)


def test_bare_word_no_match_returns_false() -> None:
    agent = _make_agent(cl_name="something_else")
    assert not _eval("login", agent)


def test_text_property_alias_for_bare_word() -> None:
    agent = _make_agent(cl_name="zzz", agent_name="database migration v2")
    assert _eval('text:"database migration"', agent)


def test_case_sensitive_string_match_against_metadata() -> None:
    agent = _make_agent(status="FAILED")
    assert _eval('c"FAILED"', agent)
    # Lowercase variant must not match the all-caps status field.
    assert not _eval('c"failed"', agent)


# --- status / cl / project / name / model / provider (substring) -------------


def test_status_substring_hits_failed_retried() -> None:
    agent = _make_agent(status="FAILED (RETRIED)")
    assert _eval("status:failed", agent)


def test_status_substring_no_match() -> None:
    agent = _make_agent(status="DONE")
    assert not _eval("status:failed", agent)


def test_cl_substring() -> None:
    agent = _make_agent(cl_name="bar_feature")
    assert _eval("cl:bar", agent)
    assert not _eval("cl:foo", agent)


def test_project_uses_basename_not_full_path() -> None:
    agent = _make_agent(project_file="/tmp/projects/foo/foo.gp")
    assert _eval("project:foo", agent)
    # The leading "tmp" is in the path but not in the basename, so no match.
    assert not _eval("project:tmp", agent)


def test_name_matches_agent_name_first() -> None:
    agent = _make_agent(agent_name="my_agent_name", cl_name="cl_abc")
    assert _eval("name:my_agent", agent)


def test_name_falls_back_to_display_name() -> None:
    # No agent_name set; display_name derives from cl_name for non-workflow.
    agent = _make_agent(agent_name=None, cl_name="display_via_cl")
    assert _eval("name:display_via_cl", agent)


def test_model_substring() -> None:
    agent = _make_agent(model="claude-opus-4-7")
    assert _eval("model:opus", agent)
    assert not _eval("model:sonnet", agent)


def test_provider_substring() -> None:
    agent = _make_agent(llm_provider="claude")
    assert _eval("provider:claude", agent)


def test_substring_property_no_field_value_is_false() -> None:
    agent = _make_agent(model=None)
    assert not _eval("model:opus", agent)


# --- type / source / needs (enums) -------------------------------------------


def test_type_workflow() -> None:
    agent = _make_agent(agent_type=AgentType.WORKFLOW)
    assert _eval("type:workflow", agent)
    assert not _eval("type:run", agent)


def test_type_run_aliases_running() -> None:
    agent = _make_agent(agent_type=AgentType.RUNNING)
    assert _eval("type:run", agent)
    assert _eval("type:running", agent)


def test_source_axe_when_workflow_set() -> None:
    agent = _make_agent(workflow="crs")
    assert _eval("source:axe", agent)
    assert not _eval("source:manual", agent)


def test_source_axe_when_step_type_set() -> None:
    agent = _make_agent(step_type="agent")
    assert _eval("source:axe", agent)


def test_source_manual_default() -> None:
    agent = _make_agent()
    assert _eval("source:manual", agent)
    assert not _eval("source:axe", agent)


def test_needs_input_matches_question_status() -> None:
    agent = _make_agent(status="QUESTION")
    assert _eval("needs:input", agent)


def test_needs_input_matches_waiting_input() -> None:
    agent = _make_agent(status="WAITING INPUT")
    assert _eval("needs:input", agent)


def test_needs_input_matches_plan_approved() -> None:
    agent = _make_agent(status="PLAN APPROVED")
    assert _eval("needs:input", agent)


def test_needs_input_no_match_for_running() -> None:
    agent = _make_agent(status="RUNNING")
    assert not _eval("needs:input", agent)


# --- tag / pinned / hidden / attention (bool / exact) ------------------------


def test_tag_exact_match() -> None:
    agent = _make_agent(tag="reviewed")
    assert _eval("tag:reviewed", agent)
    # Substring must NOT match (exact-match semantics).
    assert not _eval("tag:revi", agent)


def test_tag_match_is_case_insensitive() -> None:
    agent = _make_agent(tag="Reviewed")
    assert _eval("tag:reviewed", agent)


def test_bare_tag_matches_any_tag() -> None:
    agent = _make_agent(tag="anything")
    assert _eval("tag:", agent)


def test_bare_tag_no_match_when_untagged() -> None:
    agent = _make_agent(tag=None)
    assert not _eval("tag:", agent)


def test_pinned_true() -> None:
    agent = _make_agent(tag="pinned")
    assert _eval("pinned:true", agent)
    assert not _eval("pinned:false", agent)


def test_pinned_false() -> None:
    agent = _make_agent(tag=None)
    assert _eval("pinned:false", agent)
    assert not _eval("pinned:true", agent)


def test_hidden_true() -> None:
    agent = _make_agent(hidden=True)
    assert _eval("hidden:true", agent)
    assert not _eval("hidden:false", agent)


def test_hidden_false_default() -> None:
    agent = _make_agent()
    assert _eval("hidden:false", agent)


def test_attention_true_for_question() -> None:
    agent = _make_agent(status="QUESTION")
    assert _eval("attention:true", agent)


def test_attention_false_for_running() -> None:
    agent = _make_agent(status="RUNNING")
    assert _eval("attention:false", agent)


# --- age comparisons ---------------------------------------------------------


def test_age_greater_than_hours() -> None:
    agent = _make_agent(start_time=_NOW - timedelta(hours=3))
    assert _eval("age>2h", agent)
    assert not _eval("age>4h", agent)


def test_age_less_than_minutes() -> None:
    agent = _make_agent(start_time=_NOW - timedelta(minutes=15))
    assert _eval("age<30m", agent)
    assert not _eval("age<10m", agent)


def test_age_gte_days() -> None:
    agent = _make_agent(start_time=_NOW - timedelta(days=1))
    assert _eval("age>=1d", agent)
    assert _eval("age>=86400s", agent)


def test_age_lte_seconds() -> None:
    agent = _make_agent(start_time=_NOW - timedelta(seconds=10))
    assert _eval("age<=15s", agent)
    assert not _eval("age<=5s", agent)


def test_age_equality() -> None:
    agent = _make_agent(start_time=_NOW - timedelta(hours=2))
    expr = DurationCompare(key="age", op="=", seconds=7200)
    assert evaluate_agent_query(expr, agent, now=_NOW)


def test_age_colon_aliases_gte() -> None:
    agent = _make_agent(start_time=_NOW - timedelta(hours=3))
    assert _eval("age:2h", agent)
    # Also: less-than-N old ⇒ age:Nh false.
    assert not _eval("age:4h", agent)


def test_age_missing_start_time_always_false() -> None:
    agent = _make_agent(start_time=None)
    assert not _eval("age>1s", agent)
    assert not _eval("age<10d", agent)
    assert not _eval("age:0s", agent)


# --- Boolean composition -----------------------------------------------------


def test_and_composition() -> None:
    agent = _make_agent(status="FAILED", project_file="/tmp/x/foo/foo.gp")
    assert _eval("status:failed AND project:foo", agent)
    assert not _eval("status:failed AND project:bar", agent)


def test_or_composition() -> None:
    agent = _make_agent(status="DONE")
    assert _eval("status:failed OR status:done", agent)


def test_not_composition() -> None:
    agent = _make_agent(project_file="/tmp/x/foo/foo.gp", cl_name="cl_zzz")
    assert _eval("NOT (project:foo OR cl:bar)", agent) is False
    agent2 = _make_agent(project_file="/tmp/x/baz/baz.gp", cl_name="cl_zzz")
    assert _eval("NOT (project:foo OR cl:bar)", agent2) is True


def test_juxtaposition_is_and() -> None:
    agent = _make_agent(status="FAILED", agent_name="foo_a")
    assert _eval("status:failed name:foo", agent)
    assert not _eval("status:failed name:zzz", agent)


def test_attention_and_failed_combination() -> None:
    agent = _make_agent(status="QUESTION")
    assert _eval("attention:true AND NOT status:failed", agent)


# --- Bare-word + property combination ----------------------------------------


def test_bare_word_plus_property() -> None:
    agent = _make_agent(
        cl_name="db_migration",
        agent_name="database migration v2",
        status="FAILED",
    )
    assert _eval('"database migration" status:failed', agent)


# --- Content-cache integration (bare-word + text:) ---------------------------


class _FakeContentCache:
    """Minimal stand-in for AgentContentSearchCache (returns lower text)."""

    def __init__(self, text_per_agent: dict[int, str]) -> None:
        self._text = text_per_agent

    def get_haystack(self, agent: Any) -> str:
        return self._text.get(id(agent), "").lower()


def test_bare_word_searches_content_cache() -> None:
    agent = _make_agent(cl_name="zz", agent_name="zz")
    cache = _FakeContentCache({id(agent): "Some long REPLY about MIGRATIONS"})
    expr = parse_agent_query("migrations")
    assert evaluate_agent_query(expr, agent, now=_NOW, content_cache=cache)
    expr_miss = parse_agent_query("nonexistent")
    assert not evaluate_agent_query(expr_miss, agent, now=_NOW, content_cache=cache)


def test_text_property_searches_content_cache() -> None:
    agent = _make_agent(cl_name="zz", agent_name="zz")
    cache = _FakeContentCache({id(agent): "Reply text mentioning FastAPI here"})
    assert evaluate_agent_query(
        parse_agent_query("text:fastapi"), agent, now=_NOW, content_cache=cache
    )


def test_no_cache_falls_back_to_metadata_only() -> None:
    agent = _make_agent(agent_name="metadata_only_agent")
    # No cache supplied.
    assert _eval("metadata", agent)
    assert not _eval("nonexistent", agent)


# --- Direct AST construction (parser-independent paths) ----------------------


def test_direct_ast_property_match() -> None:
    agent = _make_agent(status="DONE")
    assert evaluate_agent_query(
        PropertyMatch(key="status", value="done"), agent, now=_NOW
    )


def test_direct_ast_string_match() -> None:
    agent = _make_agent(cl_name="hello_world")
    assert evaluate_agent_query(
        StringMatch(value="HELLO", case_sensitive=False), agent, now=_NOW
    )


def test_direct_ast_and_or_not() -> None:
    agent = _make_agent(status="FAILED", project_file="/x/foo/foo.gp")
    expr = AndExpr(
        operands=[
            PropertyMatch(key="status", value="failed"),
            NotExpr(operand=PropertyMatch(key="project", value="bar")),
            OrExpr(
                operands=[
                    PropertyMatch(key="cl", value="my_cl"),
                    PropertyMatch(key="cl", value="other"),
                ]
            ),
        ]
    )
    assert evaluate_agent_query(expr, agent, now=_NOW)


# --- Edge cases --------------------------------------------------------------


@pytest.mark.parametrize(
    "field,query",
    [
        ("model", "model:opus"),
        ("llm_provider", "provider:claude"),
        ("agent_name", "name:foo"),
    ],
)
def test_substring_property_with_unset_field_is_false(field: str, query: str) -> None:
    agent = _make_agent(**{field: None})
    assert not _eval(query, agent)
