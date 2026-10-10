"""Coverage for the `%tab` launch path, storage, query, and completion."""

from __future__ import annotations

import pytest

from sase.macro._exceptions import DirectiveError
from sase.macro.directives import extract_prompt_directives


def test_tab_absent_leaves_defaults() -> None:
    cleaned, directives = extract_prompt_directives("do work")
    assert directives.agent_tab is None
    assert directives.agent_tab_explicit_default is False
    assert cleaned == "do work"


def test_tab_valid_stores_canonical_name() -> None:
    cleaned, directives = extract_prompt_directives("%tab:sase do work")
    assert directives.agent_tab == "sase"
    assert directives.agent_tab_explicit_default is False
    assert "%tab" not in cleaned


def test_tab_uppercase_canonicalizes() -> None:
    _, directives = extract_prompt_directives("%tab:Sase do work")
    assert directives.agent_tab == "sase"


def test_tab_parenthesized_form() -> None:
    _, directives = extract_prompt_directives("%tab(blog) do work")
    assert directives.agent_tab == "blog"


def test_tab_main_is_explicit_default() -> None:
    _, directives = extract_prompt_directives("%tab:main do work")
    assert directives.agent_tab is None
    assert directives.agent_tab_explicit_default is True


@pytest.mark.parametrize("prompt", ["%tab:local do", "%tab(local) do"])
def test_tab_local_is_reserved(prompt: str) -> None:
    with pytest.raises(DirectiveError, match="machine tabs are derived"):
        extract_prompt_directives(prompt)


@pytest.mark.parametrize("prompt", ["%tab:all do", "%tab(all) do"])
def test_tab_all_is_layout_level(prompt: str) -> None:
    with pytest.raises(DirectiveError, match="there is no 'all' tab"):
        extract_prompt_directives(prompt)


def test_tab_empty_is_error() -> None:
    with pytest.raises(DirectiveError, match="must not be empty"):
        extract_prompt_directives("%tab do work")


def test_tab_duplicate_fails_even_when_values_match() -> None:
    with pytest.raises(DirectiveError, match="Duplicate directive '%tab'"):
        extract_prompt_directives("%tab:a %tab:a do work")


def test_tab_plus_is_rejected() -> None:
    with pytest.raises(DirectiveError, match="does not support '\\+'"):
        extract_prompt_directives("%tab+ do work")


def test_tab_keywords_rejected() -> None:
    with pytest.raises(DirectiveError, match="Unsupported keyword on %tab"):
        extract_prompt_directives("%tab(foo=bar) do work")


def test_tab_multiple_positional_rejected() -> None:
    with pytest.raises(DirectiveError, match="exactly one tab name"):
        extract_prompt_directives("%tab(a, b) do work")


def test_tab_missing_paren_is_error() -> None:
    with pytest.raises(DirectiveError, match="missing closing '\\)'"):
        extract_prompt_directives("%tab(apollo do work")


def test_tab_inside_fence_is_ignored() -> None:
    prompt = "```\n%tab:sase\n```"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives.agent_tab is None


def test_tab_plus_dispatch_is_accepted() -> None:
    _, directives = extract_prompt_directives("%tab:apollo %dispatch:zeus do work")
    assert directives.agent_tab == "apollo"
    assert directives.dispatch == "zeus"


def test_tab_plus_proc_is_rejected() -> None:
    with pytest.raises(DirectiveError, match="stand-alone %proc"):
        extract_prompt_directives('%tab:sase %proc("echo hi")')


def test_tab_query_legacy_dialect() -> None:
    from sase.ace.agent_query.evaluator import _match_tab
    from sase.ace.agent_query.types import PropertyMatch

    class _Agent:
        def __init__(self, tab: str | None) -> None:
            self.agent_tab = tab

    assert _match_tab(PropertyMatch(key="tab", value="main"), _Agent(None)) is True
    assert _match_tab(PropertyMatch(key="tab", value="main"), _Agent("blog")) is False
    assert _match_tab(PropertyMatch(key="tab", value="blog"), _Agent("blog")) is True
    assert _match_tab(PropertyMatch(key="tab", value="BLOG"), _Agent("blog")) is True
    assert _match_tab(PropertyMatch(key="tab", value="other"), _Agent("blog")) is False


def test_tab_live_query_projection() -> None:
    from sase.ace.tui.models.agent_live_query import _tab_values

    class _Agent:
        def __init__(self, tab: str | None) -> None:
            self.agent_tab = tab

    assert _tab_values(_Agent("blog")) == ("blog",)
    assert _tab_values(_Agent(None)) == ("main",)


def test_agent_tab_wire_round_trip() -> None:
    from sase.core.agent_launch_wire_conversion import agent_launch_wire_to_json_dict
    from sase.core.agent_launch_wire_from_dict import launch_plan_from_dict
    from sase.core.agent_launch_wire_records import AgentUnitWire

    unit = AgentUnitWire(prompt="hi", agent_tab="sase")
    payload = agent_launch_wire_to_json_dict(unit)
    assert payload["agent_tab"] == "sase"
    plan = launch_plan_from_dict(
        {
            "schema_version": 2,
            "launch_kind": "test",
            "selected_project": None,
            "content_digest": "x",
            "approval_preview": [],
            "diagnostics": [],
            "units": [
                {
                    "logical_id": "unit-1",
                    "source_order": 0,
                    "waits": [],
                    "payload": {**payload, "kind": "agent"},
                }
            ],
        }
    )
    assert isinstance(plan.units[0].payload, AgentUnitWire)
    assert plan.units[0].payload.agent_tab == "sase"


def test_agent_tab_canonicalizer_messages() -> None:
    from sase.core.agent_tab import canonicalize_agent_tab

    assert canonicalize_agent_tab("Sase") == "sase"
    assert canonicalize_agent_tab("main") is None
    with pytest.raises(ValueError, match="machine tabs are derived"):
        canonicalize_agent_tab("local")
    with pytest.raises(ValueError, match="there is no 'all' tab"):
        canonicalize_agent_tab("all")
