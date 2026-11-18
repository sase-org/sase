"""Ordinary chop launches persist progress at each spawn boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.axe import chop_batch_store
from sase.axe.chop_proposal_launch import launch_chop_proposals
from sase.axe.chop_proposal_planning import plan_chop_proposals
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_policy import ChopPreflight

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _result(name: str, pid: int) -> SimpleNamespace:
    return SimpleNamespace(
        pid=pid,
        agent_name=name,
        timestamp="260823_120000",
        workspace_num=2,
        workspace_dir="/tmp/workspace",
        project_name="sase",
        workflow_name="ace(run)-260823_120000",
        cl_name="sase",
        artifacts_dir=f"/tmp/artifacts/{name}",
    )


def _record(name: str, pid: int, env: dict[str, str]) -> SimpleNamespace:
    request = SimpleNamespace(
        name_reservation=SimpleNamespace(agent_name=name),
        extra_env=env,
    )
    return SimpleNamespace(
        slot=SimpleNamespace(slot_index=0),
        request=request,
        result=_result(name, pid),
    )


def test_standalone_batch_is_persisted_before_each_spawn_and_acknowledged(
    temp_state_dir: Path,
) -> None:
    proposals = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "refresh",
                    "prompt": "Review stale docs.",
                    "workspace": "git:sase",
                    "agent_name": "refresh-docs",
                },
                {
                    "id": "fix",
                    "prompt": "Fix the docs issue.",
                    "workspace": "git:sase",
                    "agent_name": "fix-docs",
                },
            ]
        },
        run_id="ordinary-run",
    )
    calls: list[str] = []

    def fake_launch(
        _prompt: str,
        *,
        extra_env: dict[str, str],
        before_agent_spawn: object,
        on_agent_launch_recorded: object,
        **_kwargs: object,
    ) -> SimpleNamespace:
        index = int(extra_env["SASE_CHOP_PROPOSAL_INDEX"])
        proposal_id = extra_env["SASE_CHOP_PROPOSAL_ID"]
        name = "refresh-docs" if index == 0 else "fix-docs"
        assert proposal_id == ("refresh" if index == 0 else "fix")
        batch = chop_batch_store.load_chop_batch("docs", "docs", "ordinary-run")
        assert batch["members"][index]["status"] == "pending"

        request = SimpleNamespace(
            name_reservation=SimpleNamespace(agent_name=name),
            extra_env={**extra_env, "SASE_AGENT_PLANNED_NAME": name},
        )
        before_agent_spawn(0, 0, request, None)  # type: ignore[operator]
        batch = chop_batch_store.load_chop_batch("docs", "docs", "ordinary-run")
        assert batch["members"][index]["status"] == "dispatching"
        calls.append(name)

        record = SimpleNamespace(
            slot=SimpleNamespace(slot_index=0),
            request=request,
            result=_result(name, 500 + index),
        )
        on_agent_launch_recorded(0, 0, record, None)  # type: ignore[operator]
        assert (
            chop_batch_store.load_chop_batch("docs", "docs", "ordinary-run")["members"][
                index
            ]["status"]
            == "launched"
        )
        return record.result

    launches = launch_chop_proposals(
        lumberjack_name="docs",
        chop_name="docs",
        run_id="ordinary-run",
        proposals=proposals,
        launch_agent_from_cwd_fn=fake_launch,
        launch_plans=plan_chop_proposals(proposals),
        run_started_at=datetime.fromisoformat("2026-11-17T12:00:00-05:00"),
        preflight=ChopPreflight(
            outcome="fire",
            reason="trigger matched",
            decision={"checkpoint_key": "git:sase", "cursor": "abc"},
        ),
    )

    batch = chop_batch_store.load_chop_batch("docs", "docs", "ordinary-run")
    assert calls == ["refresh-docs", "fix-docs"]
    assert batch["status"] == "complete"
    assert [member["status"] for member in batch["members"]] == [
        "launched",
        "launched",
    ]
    assert batch["run"]["run_started_at"] == "2026-11-17T12:00:00-05:00"
    assert batch["run"]["checkpoint_scope"] == "git:sase"
    assert [launch["agent_name"] for launch in launches] == calls


def test_clan_callbacks_map_source_segments_and_keep_paused_suffix_pending(
    temp_state_dir: Path,
) -> None:
    parsed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "first",
                    "prompt": "Review the first issue.",
                    "workspace": "git:sase",
                    "agent_name": "first",
                    "clan": "chop-batch-callback-test",
                },
                {
                    "id": "second",
                    "prompt": "Review the second issue.",
                    "workspace": "git:sase",
                    "agent_name": "second",
                    "clan": "chop-batch-callback-test",
                },
            ]
        },
        run_id="clan-run",
    )
    parsed = [
        replace(proposal, index=source_index)
        for proposal, source_index in zip(parsed, (7, 12), strict=True)
    ]
    plans = plan_chop_proposals(parsed)

    def fake_clan_launch(
        _query: str,
        *,
        segment_extra_env: list[dict[str, str]],
        on_agent_plan_prepared: object,
        before_agent_spawn: object,
        on_agent_launch_recorded: object,
        on_launch_paused: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        results: list[SimpleNamespace] = []
        for segment_index, plan in enumerate(plans):
            membership = SimpleNamespace(
                clan_name=plan.clan,
                generation="clan-generation-1",
            )
            on_agent_plan_prepared(  # type: ignore[operator]
                segment_index,
                0,
                plan.agent_name,
                membership,
            )
        # Deliberately report the second source segment first. The journal
        # callback must use the segment identity, not zip result order.
        for segment_index in (1, 0):
            env = segment_extra_env[segment_index]
            name = f"{plans[segment_index].clan}.{plans[segment_index].member_id}"
            request = SimpleNamespace(
                name_reservation=SimpleNamespace(agent_name=name),
                extra_env={**env, "SASE_AGENT_PLANNED_NAME": name},
            )
            membership = SimpleNamespace(
                clan_name=plans[segment_index].clan,
                generation="clan-generation-1",
            )
            before_agent_spawn(
                segment_index,
                0,
                request,
                membership,  # type: ignore[operator]
            )
            record = SimpleNamespace(
                slot=SimpleNamespace(slot_index=0),
                request=request,
                result=_result(name, 600 + segment_index),
            )
            on_agent_launch_recorded(
                segment_index,
                0,
                record,
                membership,  # type: ignore[operator]
            )
            results.append(record.result)
            if segment_index == 1:
                on_launch_paused()  # type: ignore[operator]
                break
        return results

    launches = launch_chop_proposals(
        lumberjack_name="docs",
        chop_name="docs",
        run_id="clan-run",
        proposals=parsed,
        launch_agent_from_cwd_fn=None,
        launch_agents_from_cwd_fn=fake_clan_launch,
        launch_plans=plans,
        run_started_at=datetime.fromisoformat("2026-11-17T12:00:00-05:00"),
        preflight=ChopPreflight(outcome="fire", reason="trigger matched"),
    )

    batch = chop_batch_store.load_chop_batch("docs", "docs", "clan-run")
    assert launches.paused is True
    assert batch["status"] == "paused"
    assert [member["source_index"] for member in batch["members"]] == [7, 12]
    assert [member["status"] for member in batch["members"]] == [
        "pending",
        "launched",
    ]
    assert [member["clan_generation"] for member in batch["members"]] == [
        "clan-generation-1",
        "clan-generation-1",
    ]
    assert batch["clan_generation"] == "clan-generation-1"
    assert launches[0]["index"] == 12
