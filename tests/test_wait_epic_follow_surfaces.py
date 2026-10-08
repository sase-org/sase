"""Surfaces phase: follow toggle, authored beads, CLI, rows, and Jinja."""

from __future__ import annotations

import json

from sase.ace.tui.modals.wait_modal_types import WaitModalResult
from sase.ace.tui.actions.agents._wait_helpers import (
    authored_result_beads,
    prompt_wait_spec,
)
from sase.core.wait_epic_follow_view import (
    authored_wait_beads,
    describe_epic_follow,
    epic_follow_views,
    follow_epics_mode,
    follow_toggle_disabled_reason,
    follow_toggle_label,
    is_follow_plan_row,
    resolve_epic_follow_agents,
)


def test_follow_epics_mode_tristate() -> None:
    assert follow_epics_mode([], []) == "off"
    assert follow_epics_mode(["a"], []) == "off"
    assert follow_epics_mode(["a"], ["a"]) == "on"
    assert follow_epics_mode(["a", "b"], ["a"]) == "mixed"
    assert follow_epics_mode(["a", "b"], ["a", "b"]) == "on"


def test_resolve_epic_follow_agents_modes() -> None:
    assert resolve_epic_follow_agents(["a", "b"], "on", []) == ("a", "b")
    assert resolve_epic_follow_agents(["a", "b"], "off", ["a"]) == ()
    assert resolve_epic_follow_agents(["a", "b"], "mixed", ["a"]) == ("a",)
    assert resolve_epic_follow_agents(["a", "c"], "mixed", ["a", "b"]) == ("a",)


def test_plan_rows_never_follow_and_disable_toggle() -> None:
    assert is_follow_plan_row("planner--plan")
    assert is_follow_plan_row("planner.plan")
    assert not is_follow_plan_row("planner")
    reason = follow_toggle_disabled_reason(["planner--plan"])
    assert reason is not None and "never follow" in reason
    assert follow_toggle_disabled_reason(["planner"]) is None
    assert follow_toggle_disabled_reason(["planner", "planner--plan"]) is None
    assert "never follow" in follow_toggle_label("off", disabled_reason=reason)
    assert "↪" in follow_toggle_label("on")
    assert follow_toggle_label("mixed") == "Follow epics: mixed"
    assert follow_toggle_label("off") == "Follow epics: off"


def test_authored_wait_beads_filters_derived() -> None:
    source = {
        "wait_for_beads": ["sase-1.1", "sase-1.2"],
        "wait_epic_follows": [
            {
                "target": "planner",
                "state": "following",
                "epic_ids": ["sase-1.2"],
                "added_bead_ids": ["sase-1.2"],
            }
        ],
    }
    assert authored_wait_beads(source) == ["sase-1.1"]
    views = epic_follow_views(source)
    assert views[0].target == "planner"
    assert "sase-1.2" in describe_epic_follow(views[0])


def test_prompt_wait_spec_splits_follow_and_drops_derived() -> None:
    from sase.macro.directive_edit import set_prompt_wait_and_queue

    class _Agent:
        wait_epic_follows = [
            {
                "target": "planner",
                "state": "following",
                "epic_ids": ["sase-9.1"],
                "added_bead_ids": ["sase-9.1"],
            }
        ]

    result = WaitModalResult(
        agents=["planner", "coder"],
        time_token=None,
        beads=["sase-9.1", "sase-1.1"],
        follow_mode="on",
        epic_follow_agents=("planner",),
    )
    assert authored_result_beads(result, _Agent()) == ("sase-1.1",)
    spec = prompt_wait_spec(result, _Agent())
    assert spec is not None
    assert spec.epic_follow_agents == ("planner",)
    assert spec.beads == ("sase-1.1",)
    rendered = set_prompt_wait_and_queue("do work", spec)
    assert "%wait(planner)" in rendered
    assert "%wait(coder, for_epic=false)" in rendered
    assert "for_epic=true" not in rendered
    assert "sase-9.1" not in rendered
    assert "sase-1.1" in rendered


def test_cli_list_json_exports_follow_state() -> None:
    from sase.agents.cli_list import _agent_to_json
    from sase.integrations._agent_list_entry_models import (
        AgentListEntry,
        AgentRetryInfo,
        AgentWaitInfo,
    )

    entry = AgentListEntry(
        name="waiter",
        project="sase",
        pid=123,
        model="m",
        provider="p",
        provider_badge=None,
        workspace_num=1,
        duration="1m",
        duration_seconds=60,
        started_at=None,
        finished_at=None,
        prompt="p",
        status="WAITING",
        status_bucket="Waiting",
        status_glyph="",
        approve=False,
        artifacts_dir="/tmp/x",
        wait=AgentWaitInfo(
            wait_for=("planner",),
            wait_for_beads=("sase-9.1",),
            wait_for_epics_of=("planner",),
            epic_follows=(
                {
                    "target": "planner",
                    "state": "following",
                    "epic_ids": ["sase-9.1"],
                    "added_bead_ids": ["sase-9.1"],
                    "members": [],
                    "since": 0.0,
                    "reason": None,
                    "detail": None,
                    "resume_command": None,
                    "skipped_epic_ids": [],
                },
            ),
        ),
        retry=AgentRetryInfo(),
    )
    payload = _agent_to_json(entry)
    assert payload["wait_for_epics_of"] == ["planner"]
    assert payload["epic_follows"][0]["target"] == "planner"
    assert payload["epic_follows"][0]["state"] == "following"


def test_wait_live_row_uses_shared_follow_phrasing() -> None:
    from sase.agents._wait_live_rows import _why_column
    from sase.agent.wait_watch import WaitState
    from sase.core.agent_scan_wire import (
        AgentArtifactRecordWire,
        AgentMetaWire,
        WaitingMarkerWire,
    )
    from sase.core.agent_scan_wire_markers import WaitEpicFollowEntryWire

    record = AgentArtifactRecordWire(
        project_name="sase",
        project_dir="/tmp/sase/projects/sase",
        project_file="/tmp/sase/projects/sase/sase.gp",
        workflow_dir_name="ace-run",
        artifact_dir="/tmp/sase/projects/sase/artifacts/ace-run/20260823120001",
        timestamp="20260823120001",
        agent_meta=AgentMetaWire(name="waiter", wait_for=["planner"]),
        done=None,
        waiting=WaitingMarkerWire(
            waiting_for=["planner"],
            wait_for_epics_of=["planner"],
            wait_epic_follows=[
                WaitEpicFollowEntryWire(
                    target="planner",
                    state="following",
                    epic_ids=["sase-9.1"],
                    added_bead_ids=["sase-9.1"],
                )
            ],
        ),
        pending_question=None,
        plan_path=None,
        raw_prompt_snippet=None,
        has_done_marker=False,
    )
    text = _why_column(WaitState.WAITING, record, queue=None, error=None, reason=None)
    assert "waits on planner" in text
    assert "↪" in text
    assert "sase-9.1" in text


def test_jinja_synthesizes_created_epics_from_target_meta(tmp_path) -> None:
    import sase.agent.output_variable_context as ctx

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "planner",
                "created_epics": [{"bead_id": "sase-9.1"}],
            }
        )
    )

    resolved = (str(target_dir), "planner", None)
    with (
        __import__("unittest.mock", fromlist=["patch"]).patch.object(
            ctx, "_resolve_waited_agent", return_value=resolved
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch.object(
            ctx, "_resolve_submitted_plan_wait", return_value=None
        ),
    ):
        built = ctx.build_agent_output_variable_context(
            upstreams_json=None, wait_names=["planner"]
        )
    agents = built["agents"]
    assert agents["planner"]["created_epic"] == "sase-9.1"
    assert list(agents["planner"]["created_epics"]) == ["sase-9.1"]


def test_jinja_prefers_waiter_following_entry(tmp_path) -> None:
    import sase.agent.output_variable_context as ctx

    target_dir = tmp_path / "target2"
    target_dir.mkdir()
    (target_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "planner",
                "created_epics": [{"bead_id": "sase-9.9"}],
            }
        )
    )
    resolved = (str(target_dir), "planner", None)
    with (
        __import__("unittest.mock", fromlist=["patch"]).patch.object(
            ctx, "_resolve_waited_agent", return_value=resolved
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch.object(
            ctx, "_resolve_submitted_plan_wait", return_value=None
        ),
    ):
        built = ctx.build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["planner"],
            waiter_follows={"planner": ["sase-9.1", "sase-9.2"]},
        )
    agents = built["agents"]
    assert agents["planner"]["created_epic"] == "sase-9.1"
    assert list(agents["planner"]["created_epics"]) == ["sase-9.1", "sase-9.2"]
