"""Tests for unknown waited-for agent markers in the metadata header."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from rich.text import Text

from sase.ace.tui.agent_completion import (
    _collect_known_agent_names,
    known_agent_names_for_app,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _waiting_line(text: Text) -> str:
    return next(
        line for line in text.plain.splitlines() if line.startswith("Waiting for: ")
    )


def _styles_covering(text: Text, substring: str) -> set[str]:
    start = text.plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


def test_unknown_waited_for_agent_gets_warning_marker() -> None:
    agent = make_agent(status="WAITING", waiting_for=["ghost_deploy"])

    header, _ = build_header_text(
        agent,
        cheap=True,
        known_agent_names=frozenset({"coder"}),
    )

    assert _waiting_line(header) == "Waiting for: ghost_deploy ▲"
    assert "bold #FFAF5F" in _styles_covering(header, "▲")


def test_all_known_waited_for_agents_keep_existing_duration_format() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder", "deploy"],
        wait_duration=300,
    )

    header, _ = build_header_text(
        agent,
        cheap=True,
        known_agent_names=frozenset({"coder", "deploy"}),
    )

    assert "▲" not in header.plain
    assert _waiting_line(header) == "Waiting for: coder, deploy + 5m"


def test_all_known_waited_for_agents_keep_existing_until_countdown_format() -> None:
    wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder"],
        wait_until=wait_until,
    )

    header, _ = build_header_text(
        agent,
        cheap=True,
        known_agent_names=frozenset({"coder"}),
    )

    line = _waiting_line(header)
    assert "▲" not in line
    assert line.startswith("Waiting for: coder + until ")
    assert line.endswith(" left)")


def test_mixed_waited_for_agents_mark_only_unknown_names() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder", "ghost_deploy", "reviewer"],
    )

    header, _ = build_header_text(
        agent,
        cheap=True,
        known_agent_names=frozenset({"coder", "reviewer"}),
    )

    assert _waiting_line(header) == "Waiting for: coder, ghost_deploy ▲, reviewer"
    assert header.plain.count("▲") == 1
    assert header.plain.index("ghost_deploy ▲") < header.plain.index(", reviewer")


def test_missing_known_agent_set_renders_no_warning_marker() -> None:
    agent = make_agent(status="WAITING", waiting_for=["ghost_deploy"])

    header, _ = build_header_text(agent, cheap=True, known_agent_names=None)

    assert "▲" not in header.plain
    assert _waiting_line(header) == "Waiting for: ghost_deploy"


def test_collect_known_agent_names_includes_family_and_raw_names() -> None:
    root = make_agent(
        agent_name="research.plan",
        agent_family="research",
        agent_family_role="root",
        plan_chain_root=True,
    )
    specific = make_agent(agent_name="research.code")
    blank = make_agent(agent_name="   ")

    names = _collect_known_agent_names([root, specific, blank])

    assert names == frozenset({"research", "research.plan", "research.code"})


def test_known_agent_names_for_app_uses_full_agent_set_and_falls_back() -> None:
    folded_child = make_agent(agent_name="root.child", parent_timestamp="root")
    fallback_agent = make_agent(agent_name="fallback")

    assert known_agent_names_for_app(None) is None
    assert known_agent_names_for_app(
        SimpleNamespace(_agents_with_children=[folded_child])
    ) == frozenset({"root.child"})
    assert known_agent_names_for_app(
        SimpleNamespace(_agents_with_children=[], _agents=[fallback_agent])
    ) == frozenset({"fallback"})
