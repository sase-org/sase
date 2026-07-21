"""Tests for waited-for agent status badges in the metadata header."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from rich.text import Text

from sase.ace.tui.agent_completion import (
    _collect_agent_status_buckets,
    _collect_agent_wait_status_maps,
    agent_status_buckets_for_app,
    agent_wait_status_maps_for_app,
    missing_wait_dependency_names,
    wait_dependencies_satisfied,
)
from sase.ace.tui.models.agent import Agent
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


def _clan_rows(
    clan_name: str,
    generation: str,
    member_statuses: list[tuple[str, str]],
) -> list[Agent]:
    members = [
        make_agent(
            cl_name=f"{clan_name}-{generation}-{suffix}",
            agent_name=f"{clan_name}.{suffix}",
            raw_suffix=f"{generation}-{index}",
            start_time=datetime(2024, 1, 1, 14, 23, 45) + timedelta(seconds=index),
            status=status,
            agent_clan=clan_name,
            agent_clan_generation=generation,
        )
        for index, (suffix, status) in enumerate(member_statuses)
    ]
    container = make_agent(
        cl_name=clan_name,
        agent_name=None,
        raw_suffix=generation,
        agent_clan=clan_name,
        agent_clan_generation=generation,
        is_clan_container=True,
    )
    container.runtime_children.extend(members)
    return [container, *members]


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


def test_bead_waits_render_as_named_read_only_conditions() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder"],
        waiting_for_beads=["sase-87.2", "sase-87.3"],
    )

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"coder": "Done"},
    )

    assert _waiting_line(header) == ("Wait: coder ✓ + beads: sase-87.2, sase-87.3")


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


def test_clan_wait_expands_ordered_member_statuses() -> None:
    agent = make_agent(status="WAITING", waiting_for=["sase-7g"])

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"sase-7g": "Running"},
        clan_wait_member_statuses={
            "sase-7g": (
                (".f0", "Done"),
                (".f1", "Done"),
                (".w0", "Running"),
                (".w1", "Waiting"),
            )
        },
    )

    assert _waiting_line(header) == (
        "Wait: sase-7g (all clan members · 2/4 done: .f0 ✓ · .f1 ✓ · .w0 ▶ · .w1 ⏳)"
    )
    assert header.plain.index(".f0 ✓") < header.plain.index(".f1 ✓")
    assert header.plain.index(".f1 ✓") < header.plain.index(".w0 ▶")
    assert header.plain.index(".w0 ▶") < header.plain.index(".w1 ⏳")


def test_clan_wait_expansion_keeps_plain_dependency_and_duration() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["sase-7g", "reviewer"],
        wait_duration=300,
    )

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"sase-7g": "Running", "reviewer": "Done"},
        clan_wait_member_statuses={
            "sase-7g": ((".code", "Running"), (".test", "Done"))
        },
    )

    assert _waiting_line(header) == (
        "Wait: sase-7g (all clan members · 1/2 done: "
        ".code ▶ · .test ✓), reviewer ✓ + 5m"
    )


def test_unknown_clan_wait_keeps_unknown_badge() -> None:
    agent = make_agent(status="WAITING", waiting_for=["archived-clan"])

    header, _ = build_header_text(
        agent,
        cheap=True,
        agent_status_buckets={"visible-clan": "Done"},
        clan_wait_member_statuses={"visible-clan": ((".member", "Done"),)},
    )

    assert _waiting_line(header) == "Wait: archived-clan ?"


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


@pytest.mark.parametrize(
    ("statuses", "expected_bucket"),
    [
        (["DONE", "DONE"], "Done"),
        (["RUNNING", "DONE"], "Running"),
        (["RUNNING", "FAILED"], "Failed"),
        (["WAITING", "DONE"], "Waiting"),
    ],
)
def test_collect_agent_status_buckets_aggregates_clan_members(
    statuses: list[str],
    expected_bucket: str,
) -> None:
    rows = _clan_rows(
        "sase-7g",
        "20260719120000",
        [(f"member-{index}", status) for index, status in enumerate(statuses)],
    )

    buckets, clan_members = _collect_agent_wait_status_maps(rows)

    assert buckets["sase-7g"] == expected_bucket
    expected_member_buckets = {
        "DONE": "Done",
        "RUNNING": "Running",
        "FAILED": "Failed",
        "WAITING": "Waiting",
    }
    assert clan_members["sase-7g"] == tuple(
        (f".member-{index}", expected_member_buckets[status])
        for index, status in enumerate(statuses)
    )


def test_collect_agent_status_buckets_uses_newest_clan_generation() -> None:
    older = _clan_rows(
        "sase-7g",
        "20260719110000",
        [("old", "FAILED")],
    )
    newest = _clan_rows(
        "sase-7g",
        "20260719120000",
        [("new-0", "DONE"), ("new-1", "DONE")],
    )

    buckets, clan_members = _collect_agent_wait_status_maps([*older, *newest])

    assert buckets["sase-7g"] == "Done"
    assert clan_members["sase-7g"] == ((".new-0", "Done"), (".new-1", "Done"))


def test_real_agent_and_family_names_win_clan_name_collisions() -> None:
    agent_collision = make_agent(
        agent_name="legacy-agent",
        status="WAITING",
    )
    family_collision = make_agent(
        agent_name="legacy-family.plan",
        agent_family="legacy-family",
        agent_family_role="root",
        plan_chain_root=True,
        status="FAILED",
    )
    clans = [
        *_clan_rows("legacy-agent", "20260719120000", [("done", "DONE")]),
        *_clan_rows("legacy-family", "20260719120000", [("done", "DONE")]),
    ]

    buckets, clan_members = _collect_agent_wait_status_maps(
        [agent_collision, family_collision, *clans]
    )

    assert buckets["legacy-agent"] == "Waiting"
    assert buckets["legacy-family"] == "Failed"
    assert "legacy-agent" not in clan_members
    assert "legacy-family" not in clan_members


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


def test_agent_wait_status_maps_for_app_uses_one_clan_snapshot() -> None:
    rows = _clan_rows(
        "sase-7g",
        "20260719120000",
        [("plan", "DONE"), ("code", "RUNNING")],
    )

    status_maps = agent_wait_status_maps_for_app(
        SimpleNamespace(_agents_with_children=rows)
    )

    assert status_maps is not None
    buckets, clan_members = status_maps
    assert buckets["sase-7g"] == "Running"
    assert clan_members["sase-7g"] == ((".plan", "Done"), (".code", "Running"))


def test_wait_dependencies_satisfied_accepts_empty_wait_list() -> None:
    agent = make_agent(status="WAITING", waiting_for=[])

    assert wait_dependencies_satisfied(agent, None) is True


def test_wait_dependencies_satisfied_keeps_bead_waits_pending() -> None:
    agent = make_agent(status="WAITING", waiting_for_beads=["sase-87.2"])

    assert wait_dependencies_satisfied(agent, None) is False


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


def test_wait_dependencies_satisfied_uses_clan_aggregate() -> None:
    agent = make_agent(status="WAITING", waiting_for=["sase-7g"])
    done_buckets = _collect_agent_status_buckets(
        _clan_rows(
            "sase-7g",
            "20260719120000",
            [("plan", "DONE"), ("code", "DONE")],
        )
    )
    active_buckets = _collect_agent_status_buckets(
        _clan_rows(
            "sase-7g",
            "20260719120000",
            [("plan", "DONE"), ("code", "RUNNING")],
        )
    )

    assert wait_dependencies_satisfied(agent, done_buckets) is True
    assert wait_dependencies_satisfied(agent, active_buckets) is False


def test_missing_wait_dependency_names_returns_ordered_partial_list() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder", "ghost_deploy", "reviewer"],
    )

    assert missing_wait_dependency_names(
        agent,
        {"coder": "Running", "reviewer": "Failed"},
    ) == ("ghost_deploy",)


def test_missing_wait_dependency_names_treats_every_known_status_as_existing() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["running", "waiting", "failed", "stopped", "starting"],
    )

    assert (
        missing_wait_dependency_names(
            agent,
            {
                "running": "Running",
                "waiting": "Waiting",
                "failed": "Failed",
                "stopped": "Stopped",
                "starting": "Starting",
            },
        )
        == ()
    )


def test_missing_wait_dependency_names_keeps_missing_target_when_another_is_done() -> (
    None
):
    agent = make_agent(
        status="WAITING",
        waiting_for=["done_target", "missing_target"],
    )

    assert missing_wait_dependency_names(agent, {"done_target": "Done"}) == (
        "missing_target",
    )


def test_missing_wait_dependency_names_preserves_multiple_missing_names() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["first_missing", "known", "second_missing"],
    )

    assert missing_wait_dependency_names(agent, {"known": "Done"}) == (
        "first_missing",
        "second_missing",
    )


def test_missing_wait_dependency_names_preserves_unavailable_snapshot() -> None:
    agent = make_agent(status="WAITING", waiting_for=["ghost_deploy"])

    assert missing_wait_dependency_names(agent, None) is None


def test_missing_wait_dependency_names_uses_wait_display_source() -> None:
    root = make_agent(status="WAITING")
    child = make_agent(
        status="WAITING",
        cl_name="child",
        waiting_for=["known", "missing"],
    )
    root.wait_display_source = child

    assert missing_wait_dependency_names(root, {"known": "Done"}) == ("missing",)


def test_missing_wait_dependency_names_recognizes_clan_aggregate() -> None:
    agent = make_agent(status="WAITING", waiting_for=["sase-7g"])
    buckets = _collect_agent_status_buckets(
        _clan_rows(
            "sase-7g",
            "20260719120000",
            [("plan", "DONE"), ("code", "RUNNING")],
        )
    )

    assert missing_wait_dependency_names(agent, buckets) == ()
