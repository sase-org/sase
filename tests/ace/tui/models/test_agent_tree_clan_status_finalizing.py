"""Finalizing, retrying, and render-key clan status tests.

Lone finalizing-member presentation, finalizer settling, the retrying
countdown mirror, and render-key invalidation.
"""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from tests.ace.tui.models._agent_tree_clan_status_helpers import (
    format_member,
    make_base_agent,
    make_clan_member,
    style_at,
)

__all__ = [
    "test_clan_finalizing_member_plus_failed_has_no_pointer",
    "test_clan_finalizing_settles_back_to_running_then_clears",
    "test_clan_render_key_invalidates_when_member_finalizer_changes",
    "test_clan_retrying_countdown_matches_member",
    "test_clan_row_shows_finalizing_for_lone_running_member_declaring",
    "test_clan_row_shows_finalizing_for_lone_running_member_executing",
    "test_clan_row_shows_finalizing_for_lone_running_session_member",
    "test_clan_two_running_members_one_finalizing_stays_running",
]


def _finalizing_member(
    suffix: str = "gem",
    *,
    status: str = "RUNNING",
    phase: str = "declaring",
    running_instance: bool = False,
) -> Agent:
    from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping

    row = make_clan_member(f"research.{suffix}", suffix, status=status)
    instances: list[dict[str, object]] = []
    if running_instance or phase == "executing":
        instances = [
            {
                "id": "commit",
                "status": "running",
                "attempt": 1,
                "max_attempts": 1,
                "op": "stitch main",
                "step": "just fix",
                "started_at": 1727440001.0,
            }
        ]
    row.finalizer_status = finalizer_status_from_mapping(
        {
            "schema_version": 1,
            "phase": phase,
            "run_id": "abc123",
            "started_at": 1727440000.0,
            "updated_at": 1727440012.5,
            "instance_count": len(instances),
            "instances": instances,
        }
    )
    return row


def _screenshot_members(member: Agent) -> list[Agent]:
    return [
        *(
            make_clan_member(f"research.done-{index}", f"done-{index}", status="DONE")
            for index in range(4)
        ),
        *(
            make_clan_member(
                f"research.waiting-{index}", f"waiting-{index}", status="WAITING"
            )
            for index in range(2)
        ),
        member,
    ]


def test_clan_row_shows_finalizing_for_lone_running_member_declaring() -> None:
    member = _finalizing_member(phase="declaring")
    container, *_ = project_clan_tree(_screenshot_members(member))

    assert container.status == "RUNNING"
    assert container.status_display_source is member
    container_text = format_member(container)
    member_text = format_member(member, 1)
    assert container_text.plain.startswith("tmp (FINALIZING)")
    assert "[R1 W2 D4]" in container_text.plain
    assert style_at(container_text, container_text.plain.index("FINALIZING")) == (
        style_at(member_text, member_text.plain.index("FINALIZING"))
    )


def test_clan_row_shows_finalizing_for_lone_running_member_executing() -> None:
    member = _finalizing_member(phase="executing", running_instance=True)
    container, *_ = project_clan_tree(_screenshot_members(member))

    assert container.status == "RUNNING"
    assert container.status_display_source is member
    container_text = format_member(container)
    assert container_text.plain.startswith("tmp (FINALIZING)")
    assert "[R1 W2 D4]" in container_text.plain


def test_clan_row_shows_finalizing_for_lone_running_session_member() -> None:
    root = make_clan_member("research.session", "session", status="RUNNING")
    root.agent_session = "session"
    root.agent_session_role = "root"
    turn = make_base_agent(
        "research.session--code",
        "session-code",
        status="RUNNING",
        parent_timestamp=root.raw_suffix,
        clan=None,
        generation=None,
    )
    from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping

    turn.finalizer_status = finalizer_status_from_mapping(
        {
            "schema_version": 1,
            "phase": "executing",
            "run_id": "abc123",
            "started_at": 1727440000.0,
            "updated_at": 1727440012.5,
            "instance_count": 1,
            "instances": [
                {
                    "id": "commit",
                    "status": "running",
                    "attempt": 1,
                    "max_attempts": 1,
                    "op": "stitch main",
                    "step": "just fix",
                    "started_at": 1727440001.0,
                }
            ],
        }
    )
    root.followup_agents = [turn]
    root.runtime_children = [turn]
    members = [
        root,
        turn,
        make_clan_member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status_display_source is root
    assert format_member(container).plain.startswith("tmp (FINALIZING")


def test_clan_two_running_members_one_finalizing_stays_running() -> None:
    member = _finalizing_member()
    members = [
        member,
        make_clan_member("research.plain", "plain", status="RUNNING"),
        make_clan_member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RUNNING"
    assert container.status_display_source is None
    assert format_member(container).plain.startswith("tmp (RUNNING")


def test_clan_finalizing_member_plus_failed_has_no_pointer() -> None:
    member = _finalizing_member()
    members = [
        member,
        make_clan_member("research.failed", "failed", status="FAILED"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "FAILED"
    assert container.status_display_source is None
    assert format_member(container).plain.startswith("tmp (FAILED")


def test_clan_finalizing_settles_back_to_running_then_clears() -> None:
    from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping

    member = _finalizing_member()
    done_one = make_clan_member("research.one", "one", status="DONE")
    done_two = make_clan_member("research.two", "two", status="DONE")
    container, *members = project_clan_tree([done_one, done_two, member])
    assert format_member(container).plain.startswith("tmp (FINALIZING)")

    member.finalizer_status = finalizer_status_from_mapping(
        {
            "schema_version": 1,
            "phase": "settled",
            "status": "success",
            "run_id": "abc123",
            "started_at": 1727440000.0,
            "updated_at": 1727440020.0,
            "instance_count": 1,
            "instances": [
                {
                    "id": "commit",
                    "status": "success",
                    "attempt": 1,
                    "max_attempts": 1,
                    "started_at": 1727440001.0,
                    "finished_at": 1727440019.0,
                }
            ],
        }
    )
    assert format_member(container).plain.startswith("tmp (RUNNING")

    member.status = "DONE"
    reprojection, *_ = project_clan_tree([container, *members])
    assert reprojection.status_display_source is None


def test_clan_retrying_countdown_matches_member() -> None:
    import time

    member = make_clan_member("research.retry", "retry", status="RETRYING")
    member.retry_next_at_epoch = time.time() + 30
    members = [
        member,
        make_clan_member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RETRYING"
    assert container.status_display_source is member
    member_text = format_member(member, 1).plain
    container_text = format_member(container).plain
    assert "RETRYING (" in member_text
    assert "RETRYING (" in container_text
    import re

    assert re.search(r"RETRYING \(\d+s\)", member_text)
    assert re.search(r"RETRYING \(\d+s\)", container_text)


def test_clan_render_key_invalidates_when_member_finalizer_changes() -> None:
    from sase.ace.tui.widgets._agent_list_render_cache import agent_render_key
    from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping

    member = make_clan_member("research.gem", "gem", status="RUNNING")
    container, *_ = project_clan_tree(
        [member, make_clan_member("research.done", "done", status="DONE")]
    )
    before = agent_render_key(
        container,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
    )
    member.finalizer_status = finalizer_status_from_mapping(
        {
            "schema_version": 1,
            "phase": "executing",
            "run_id": "abc123",
            "started_at": 1727440000.0,
            "updated_at": 1727440012.5,
            "instance_count": 1,
            "instances": [
                {
                    "id": "commit",
                    "status": "running",
                    "attempt": 1,
                    "max_attempts": 1,
                    "started_at": 1727440001.0,
                }
            ],
        }
    )
    after = agent_render_key(
        container,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
    )
    assert before != after
