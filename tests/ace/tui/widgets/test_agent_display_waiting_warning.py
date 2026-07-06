"""Tests for waited-for agent status badges in the metadata header."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from rich.text import Text

from sase.ace.tui.agent_completion import (
    _collect_agent_status_buckets,
    agent_status_buckets_for_app,
    wait_dependencies_satisfied,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _waiting_line(text: Text) -> str:
    return next(line for line in text.plain.splitlines() if line.startswith("Wait: "))


def _styles_covering(text: Text, substring: str) -> set[str]:
    start = text.plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


@pytest.mark.parametrize(
    ("bucket", "glyph", "style"),
    [
        ("Done", "✓", "bold #5FD75F"),
        ("Running", "▶", "bold #FFD700"),
        ("Failed", "✗", "bold #FF5F5F"),
        ("Waiting", "⏳", "bold #AF87FF"),
        ("Starting", "◐", "bold #87D7FF"),
        ("Stopped", "▲", "bold #8787AF"),
    ],
)
def test_known_waited_for_agent_gets_status_badge(
    bucket: str,
    glyph: str,
    style: str,
) -> None:
    agent = make_agent(status="WAITING", waiting_for=["dep"])

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"dep": bucket},
    )

    assert _waiting_line(header) == f"Wait: dep {glyph}"
    assert style in _styles_covering(header, glyph)


def test_unknown_waited_for_agent_gets_unknown_badge() -> None:
    agent = make_agent(status="WAITING", waiting_for=["ghost_deploy"])

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"coder": "Running"},
    )

    assert _waiting_line(header) == "Wait: ghost_deploy ?"
    assert "bold #FFAF5F" in _styles_covering(header, "?")


def test_mixed_waited_for_agents_badge_each_name_independently() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder", "ghost_deploy", "reviewer"],
    )

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"coder": "Done", "reviewer": "Failed"},
    )

    assert _waiting_line(header) == "Wait: coder ✓, ghost_deploy ?, reviewer ✗"
    assert header.plain.index("coder ✓") < header.plain.index(", ghost_deploy ?")
    assert header.plain.index("ghost_deploy ?") < header.plain.index(", reviewer ✗")


def test_missing_agent_status_bucket_map_renders_no_badges() -> None:
    agent = make_agent(status="WAITING", waiting_for=["ghost_deploy"])

    header, _ = build_header_text(agent, cheap=True, agent_status_buckets=None)

    assert "?" not in _waiting_line(header)
    assert _waiting_line(header) == "Wait: ghost_deploy"


def test_waited_for_status_badges_keep_duration_format() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder", "deploy"],
        wait_duration=300,
    )

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"coder": "Done", "deploy": "Running"},
    )

    assert _waiting_line(header) == "Wait: coder ✓, deploy ▶ + 5m"


def test_waited_for_status_badges_keep_until_countdown_format() -> None:
    wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder"],
        wait_until=wait_until,
    )

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"coder": "Done"},
    )

    line = _waiting_line(header)
    assert line.startswith("Wait: coder ✓ + until ")
    assert line.endswith(" left)")


def test_collect_agent_status_buckets_includes_family_and_raw_names() -> None:
    root = make_agent(
        agent_name="research.plan",
        agent_family="research",
        agent_family_role="root",
        plan_chain_root=True,
        status="WAITING",
    )
    specific = make_agent(agent_name="research.code", status="DONE")
    blank = make_agent(agent_name="   ")

    buckets = _collect_agent_status_buckets([root, specific, blank])

    assert buckets == {
        "research": "Waiting",
        "research.plan": "Waiting",
        "research.code": "Done",
    }


def test_collect_agent_status_buckets_applies_family_precedence() -> None:
    def family_agent(agent_name: str, status: str):
        return make_agent(
            agent_name=agent_name,
            agent_family="foo",
            agent_family_role="root",
            plan_chain_root=True,
            status=status,
        )

    assert (
        _collect_agent_status_buckets(
            [family_agent("foo.1", "FAILED"), family_agent("foo.2", "DONE")]
        )["foo"]
        == "Done"
    )
    assert (
        _collect_agent_status_buckets(
            [family_agent("foo.1", "FAILED"), family_agent("foo.2", "RUNNING")]
        )["foo"]
        == "Running"
    )
    assert (
        _collect_agent_status_buckets(
            [family_agent("foo.1", "FAILED"), family_agent("foo.2", "PLAN")]
        )["foo"]
        == "Stopped"
    )
    assert (
        _collect_agent_status_buckets(
            [family_agent("foo.1", "WAITING"), family_agent("foo.2", "STARTING")]
        )["foo"]
        == "Starting"
    )
    assert (
        _collect_agent_status_buckets(
            [family_agent("foo.1", "FAILED"), family_agent("foo.2", "FAILED")]
        )["foo"]
        == "Failed"
    )


def test_agent_status_buckets_for_app_uses_full_agent_set_and_falls_back() -> None:
    folded_child = make_agent(agent_name="root.child", parent_timestamp="root")
    fallback_agent = make_agent(agent_name="fallback", status="DONE")

    assert agent_status_buckets_for_app(None) is None
    assert agent_status_buckets_for_app(
        SimpleNamespace(_agents_with_children=[folded_child])
    ) == {"root.child": "Running"}
    assert agent_status_buckets_for_app(
        SimpleNamespace(_agents_with_children=[], _agents=[fallback_agent])
    ) == {"fallback": "Done"}


def test_wait_dependencies_satisfied_accepts_empty_wait_list() -> None:
    agent = make_agent(status="WAITING", waiting_for=[])

    assert wait_dependencies_satisfied(agent, None) is True


def test_wait_dependencies_satisfied_requires_all_deps_done() -> None:
    agent = make_agent(status="WAITING", waiting_for=["coder", "reviewer"])

    assert (
        wait_dependencies_satisfied(
            agent,
            {"coder": "Done", "reviewer": "Done"},
        )
        is True
    )
    assert (
        wait_dependencies_satisfied(
            agent,
            {"coder": "Done", "reviewer": "Running"},
        )
        is False
    )
    assert wait_dependencies_satisfied(agent, {"coder": "Done"}) is False
    assert wait_dependencies_satisfied(agent, None) is False


def test_wait_dependencies_satisfied_uses_wait_display_source() -> None:
    root = make_agent(status="WAITING")
    child = make_agent(status="WAITING", cl_name="child", waiting_for=["coder"])
    root.wait_display_source = child

    assert wait_dependencies_satisfied(root, {"coder": "Done"}) is True
    assert wait_dependencies_satisfied(root, {"coder": "Running"}) is False
