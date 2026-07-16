"""Tests for human-readable plan inventory rendering."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from sase.main import plan_inventory as plan_inventory_module
from sase.main.plan_inventory import (
    build_plan_inventory,
    plan_inventory_to_json,
    render_plan_inventory,
)
from tests._plan_inventory_helpers import (
    append_plan_notification as _append_plan_notification,
    archived_plan as _archived_plan,
    live_agent as _live_agent,
    response_dir as _response_dir,
    write_agent_meta as _write_agent_meta,
)


def test_render_plan_inventory_empty_state_is_intentional() -> None:
    inventory = build_plan_inventory()
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    render_plan_inventory(inventory, console=console)

    output = buffer.getvalue()
    assert "Plan Pipeline" in output
    assert "Proposed" in output
    assert "Approved" in output
    assert "Rejected" in output
    assert "No pending plan proposals." in output
    assert "No approved plans found." in output
    assert "No inferred rejected plans." in output


def test_render_plan_inventory_non_empty_output_uses_stable_columns(
    tmp_path: Path,
) -> None:
    plan = _archived_plan("proposed.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "proposed")
    _append_plan_notification(
        "12345678-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
    )
    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(_live_agent(),),
    ):
        inventory = build_plan_inventory()
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    render_plan_inventory(inventory, console=console)

    output = buffer.getvalue()
    assert "ID" in output
    assert "Age" in output
    assert "Agent/Project" in output
    assert "Model" in output
    assert "Plan" in output
    assert "Plan path" not in output
    assert "12345678" in output
    assert "planner / demo-project" in output
    assert output.index("Proposed") < output.index("proposed.md")


def test_render_plan_inventory_uses_project_display_names_only_in_dashboard(
    tmp_path: Path,
) -> None:
    proposed_plan = _archived_plan("proposed-display.md", minutes_ago=5)
    explicit_plan = _archived_plan("approved-explicit-display.md", minutes_ago=4)
    fallback_plan = _archived_plan("approved-fallback-display.md", minutes_ago=3)
    response_dir = _response_dir(tmp_path, "proposed-display")
    _append_plan_notification(
        "12345678-plan-notification",
        proposed_plan,
        response_dir,
        minutes_ago=5,
        project_dir="/work/gh_sase-org__sase",
    )
    _write_agent_meta(
        "artifact-container",
        "workflow-plan",
        "20260613130000",
        {
            "plan_approved": True,
            "plan_path": str(explicit_plan),
            "name": "explicit-agent",
            "project": "gh_bobs-org__bob-cli",
        },
        minutes_ago=2,
    )
    _write_agent_meta(
        "gh_sase-org__sase",
        "workflow-plan",
        "20260613140000",
        {
            "plan_approved": True,
            "plan_path": str(fallback_plan),
            "name": "fallback-agent",
        },
        minutes_ago=1,
    )
    display_names = {
        "gh_sase-org__sase": "sase",
        "gh_bobs-org__bob-cli": "bob-cli",
    }

    with (
        patch(
            "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
            return_value=(_live_agent(),),
        ),
        patch.object(
            plan_inventory_module,
            "project_display_name_for",
            side_effect=lambda key: display_names.get(key, key),
        ),
    ):
        inventory = build_plan_inventory()
        payload = plan_inventory_to_json(inventory)
        buffer = io.StringIO()
        render_plan_inventory(
            inventory,
            console=Console(
                file=buffer,
                force_terminal=False,
                color_system=None,
                width=160,
            ),
        )

    output = buffer.getvalue()
    assert "planner / sase" in output
    assert "explicit-agent / bob-cli" in output
    assert "fallback-agent / sase" in output
    assert "gh_sase-org__sase" not in output
    assert "gh_bobs-org__bob-cli" not in output
    assert payload["proposed"][0]["project"] == "gh_sase-org__sase"
    assert {row["agent"]: row["project"] for row in payload["approved"]} == {
        "explicit-agent": "gh_bobs-org__bob-cli",
        "fallback-agent": "gh_sase-org__sase",
    }


def test_agent_project_display_name_fallback_and_sentinels() -> None:
    display_names = {"gh_sase-org__sase": "sase"}

    with patch.object(
        plan_inventory_module,
        "project_display_name_for",
        side_effect=lambda key: display_names.get(key, key),
    ) as display_name_for:
        assert plan_inventory_module._agent_project(
            "planner", "gh_unknown__legacy"
        ) == ("planner / gh_unknown__legacy")
        assert plan_inventory_module._agent_project("-", "gh_sase-org__sase") == "sase"
        assert plan_inventory_module._agent_project("planner", "-") == "planner"
        assert plan_inventory_module._agent_project("-", "-") == "-"

    assert [call.args[0] for call in display_name_for.call_args_list] == [
        "gh_unknown__legacy",
        "gh_sase-org__sase",
    ]


def test_render_plan_inventory_filters_panels_and_consolidates_filters() -> None:
    inventory = build_plan_inventory(
        limit=25,
        statuses=("approved",),
        tiers=("epic",),
    )
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    render_plan_inventory(inventory, console=console)

    output = buffer.getvalue()
    assert "Approved (0)" in output
    assert "Proposed (0)" not in output
    assert "Rejected (0)" not in output
    assert "No pending plan proposals." not in output
    assert "No inferred rejected plans." not in output
    assert "Filters: status=approved · tier=epic: 0 · limit=25" in output
    assert "Tier filter:" not in output


def test_render_plan_inventory_titles_paths_and_rejected_note_at_multiple_widths(
    tmp_path: Path,
) -> None:
    proposed = _archived_plan("p.md", minutes_ago=3, title="Atlas")
    approved = _archived_plan("a.md", minutes_ago=2, title="Beacon")
    rejected = _archived_plan("r.md", minutes_ago=1, title="Cipher")
    _append_plan_notification(
        "87654321-plan-notification",
        proposed,
        _response_dir(tmp_path, "p"),
        minutes_ago=3,
    )
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613150000",
        {
            "plan_approved": True,
            "plan_path": str(approved),
            "name": "approver",
        },
        minutes_ago=1,
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(_live_agent(),),
    ):
        inventory = build_plan_inventory()

    assert rejected.name == "r.md"
    for width in (100, 180):
        buffer = io.StringIO()
        render_plan_inventory(
            inventory,
            console=Console(
                file=buffer,
                force_terminal=False,
                color_system=None,
                width=width,
            ),
        )

        output = buffer.getvalue()
        assert "87654321" in output
        for title, filename in (
            ("Atlas", "p.md"),
            ("Beacon", "a.md"),
            ("Cipher", "r.md"),
        ):
            assert title in output
            assert filename in output
            assert output.index(title) < output.index(filename)
        assert output.count("inferred from archived proposal") == 1
        assert "Note" not in output


def test_render_plan_inventory_uses_subdued_unavailable_title() -> None:
    from sase.main.plan_inventory_render import _plan_cell

    cell = _plan_cell(None, "~/.sase/plans/legacy.md")

    assert cell.plain == "title unavailable\n~/.sase/plans/legacy.md"
    assert str(cell.spans[0].style) == "dim italic"
