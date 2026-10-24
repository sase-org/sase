"""A pure-wait monitor releases capacity and its follow-up re-enters admission."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.axe.run_agent_markers import write_agent_meta
import sase.monitor.followup as monitor_followup_module
from sase.monitor.continuation_delivery import adopt_ordinary_continuation_delivery
from sase.monitor.start import StartMonitorRequest, start_monitor
import sase.procs.spawn as spawn_module
from sase.procs.settlement import settle_named_proc
from sase.macro.directives import extract_prompt_directives

from tests.fakey._monitor_capacity_helpers import make_bootstrap_popen
from tests.fakey._runner_slot_harness import _Agent, _RunnerSlotFakeyHarness
from tests.monitor._fixtures import (
    patch_project_records,
    wait_for_done,
    write_project_file,
)

_MONITOR_PROJECT = "fakey-slots"


def test_zero_weight_wait_monitor_followup_reenters_full_host_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The monitor is free, but its weight-2 successor waits for real capacity."""
    import tests.fakey._runner_slot_harness as harness_module

    monkeypatch.setattr(harness_module, "_WAIT_TIMEOUT", 5.0)
    # Follow-up dispatch has a bounded 60-second starter-settle window; keep
    # the already-admitted filler alive through that production wait.
    monkeypatch.setattr(harness_module, "_FAKEY_RELEASE_TIMEOUT", 90.0)
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    for name in ("SASE_AGENT", "SASE_AGENT_NAME"):
        monkeypatch.delenv(name, raising=False)
    write_project_file(_MONITOR_PROJECT, workspace_dir=str(harness.workspace))

    starter = harness.create_agent(
        0,
        name="wait--0",
        agent_session="wait",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    starter.meta["workflow_name"] = "wait"
    starter.meta["continuation_node_id"] = "agent-turn:wait--0:sentinel"
    write_agent_meta(str(starter.artifacts_dir), starter.meta)
    harness.start(starter)
    harness.wait_started(starter)

    patch_project_records(monkeypatch, [str(starter.artifacts_dir)])
    dummy_supervisor = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    monkeypatch.setattr(
        spawn_module.subprocess, "Popen", make_bootstrap_popen(dummy_supervisor.pid)
    )

    filler: _Agent | None = None
    successor: _Agent | None = None
    competitor: _Agent | None = None
    try:
        record = start_monitor(
            StartMonitorRequest(
                command="true",
                reason="zero-weight pure wait capacity acceptance",
                timeout_seconds=30.0,
                cwd=str(harness.workspace),
                project_name=_MONITOR_PROJECT,
                start_status="WAITING",
                stop_status="WAITED",
                lane="wait",
                inherit_lane_workspace_claim=False,
                next_action="Report that the external wait finished.",
                queue_weight_override=0.0,
            )
        )
        monitor_meta = json.loads(
            (Path(record.artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert monitor_meta["queue_weight"] == 0.0
        assert monitor_meta["queue_weight_explicit"] is True
        assert monitor_meta["monitor_queue_weight_overridden"] is True
        assert monitor_meta["monitor_inherited_queue_weight"] == 2.0

        harness.release_agent(starter)
        harness.join(starter)

        filler = harness.create_agent(
            1,
            name="filler",
            queue_weight=2.0,
            queue_weight_explicit=True,
        )
        harness.start(filler)
        harness.wait_started(filler)

        saved: dict[str, object] = {}

        def fake_spawn(**kwargs: object) -> AgentLaunchResult:
            nonlocal successor
            prompt = kwargs["prompt"]
            assert isinstance(prompt, str)
            _cleaned, directives = extract_prompt_directives(prompt)
            assert directives.queue_weight == 2.0
            assert directives.queue_weight_explicit is True

            extra_env = kwargs["extra_env"]
            assert isinstance(extra_env, dict)
            plan = json.loads(extra_env["SASE_AGENT_SESSION_ATTACH"])
            successor = harness.create_agent(
                2,
                name=plan["agent_name"],
                parent_timestamp=Path(record.artifacts_dir).name,
                agent_session="wait",
                queue_weight=directives.queue_weight or 1.0,
                queue_weight_explicit=directives.queue_weight_explicit,
                wait_priority=directives.wait_priority,
                wait_runners=directives.queue_capacity,
            )
            harness.start(successor)
            harness.wait_parked(successor)
            saved["env"] = dict(extra_env)
            saved["agent_name"] = plan["agent_name"]
            return AgentLaunchResult(
                pid=os.getpid(),
                workspace_num=0,
                workspace_dir=str(harness.workspace),
                output_path=str(harness.root / "monitor-successor.log"),
                agent_name=plan["agent_name"],
            )

        monkeypatch.setattr(
            monitor_followup_module, "spawn_agent_subprocess", fake_spawn
        )
        settle_named_proc(
            record.monitor_id,
            supervisor_id="test-supervisor",
            status="success",
            message="completed",
            termination_reason="success",
            exit_code=0,
        )
        assert wait_for_done(record.artifacts_dir)["monitor_state"] == "completed"
        assert successor is not None
        harness.assert_parked_not_started(successor)

        harness.release_agent(filler)
        harness.join(filler)
        harness.wait_started(successor)
        adopted = adopt_ordinary_continuation_delivery(
            env=saved["env"], agent_name=str(saved["agent_name"])
        )
        assert adopted is not None
        assert adopted["disposition"] == "acknowledged"

        successor_meta = harness.agent_meta(successor)
        assert successor_meta["queue_weight"] == 2.0
        assert successor_meta["queue_weight_explicit"] is True

        competitor = harness.create_agent(
            3,
            name="late-competitor",
            queue_weight=2.0,
            queue_weight_explicit=True,
        )
        harness.start(competitor)
        harness.wait_parked(competitor)
        harness.release_agent(successor)
        harness.join(successor)
        harness.wait_started(competitor)
        harness.release_agent(competitor)
        harness.join(competitor)
    finally:
        for agent in (starter, filler, successor, competitor):
            if (
                agent is not None
                and agent.thread is not None
                and agent.thread.is_alive()
            ):
                harness.release_agent(agent)
        dummy_supervisor.kill()
        dummy_supervisor.wait()
