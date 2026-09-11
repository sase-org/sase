"""Real monitor lifecycle acceptance for weighted runner-slot capacity.

Drives the production ``start_monitor``/``launch_followup_agent`` paths --
not hand-authored monitor records -- through real ``wait_for_runner_slot``
contention against the shared ``_RunnerSlotFakeyHarness`` (see
``test_runner_slots_e2e.py``). Gate-shell capacity acceptance lives in the
sibling ``test_gate_capacity_e2e.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import sys
import time

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.axe.run_agent_markers import write_agent_meta
import sase.monitor.followup as monitor_followup_module
from sase.monitor.followup import launch_followup_agent
from sase.monitor.start import StartMonitorRequest, start_monitor

from tests.fakey._runner_slot_harness import (
    _WAIT_TIMEOUT,
    _Agent,
    _RunnerSlotFakeyHarness,
)
from tests.monitor._fixtures import (
    patch_project_records,
    wait_for_done,
    wait_for_path,
    write_project_file,
)

_MONITOR_PROJECT = "fakey-slots"


def _blocking_monitor_command(started: Path, release: Path) -> str:
    """Return a shell command that signals *started* then blocks on *release*."""
    code = (
        "import pathlib, sys, time\n"
        f"pathlib.Path({str(started)!r}).write_text('1')\n"
        f"deadline = time.monotonic() + {_WAIT_TIMEOUT}\n"
        f"while not pathlib.Path({str(release)!r}).exists():\n"
        "    if time.monotonic() > deadline:\n"
        "        sys.exit(1)\n"
        "    time.sleep(0.01)\n"
    )
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def test_weight_two_land_family_retains_one_owner_through_real_monitor_and_next_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real monitor start, real supervision, and a real ``--next`` handoff
    all persist the same lineage owner and weight.

    Replaces the former hand-authored monitor simulation (bare live pid,
    default weight 1.0) with the production ``start_monitor`` and
    ``launch_followup_agent`` entry points, asserting against the persisted
    ``runner_claim_owner_key`` a weight-2 competitor must respect throughout.
    """
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    write_project_file(_MONITOR_PROJECT, workspace_dir=str(harness.workspace))

    starter = harness.create_agent(
        0,
        name="land--0",
        agent_family="land",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    # `%i(@, family=...)` resolution (exercised below by the real ``--next``
    # handoff) matches on `workflow_name`, the durable family key -- not on
    # `agent_family` alone -- so a real starter must carry both.
    starter.meta["workflow_name"] = "land"
    write_agent_meta(str(starter.artifacts_dir), starter.meta)
    harness.start(starter)
    harness.wait_started(starter)
    starter_owner_key = harness.agent_meta(starter).get("runner_claim_owner_key")
    assert isinstance(starter_owner_key, str) and starter_owner_key

    competitor = harness.create_agent(
        1, name="competitor", queue_weight=2.0, queue_weight_explicit=True
    )
    harness.start(competitor)
    harness.wait_parked(competitor)

    patch_project_records(monkeypatch, [str(starter.artifacts_dir)])
    monitor_started = harness.root / "signals" / "monitor.started"
    monitor_release = harness.root / "signals" / "monitor.release"
    record = start_monitor(
        StartMonitorRequest(
            command=_blocking_monitor_command(monitor_started, monitor_release),
            reason="weight-2 land family acceptance",
            timeout_seconds=30.0,
            cwd=str(harness.workspace),
            project_name=_MONITOR_PROJECT,
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="land",
            inherit_lane_workspace_claim=False,
        )
    )
    wait_for_path(monitor_started)

    monitor_meta = json.loads(
        (Path(record.artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert monitor_meta["runner_claim_owner_key"] == starter_owner_key
    assert monitor_meta["queue_weight"] == 2.0
    assert monitor_meta["queue_weight_explicit"] is True

    # Production kills the starter's runner group as part of a real handoff;
    # release its fakey process so only the monitor represents live lineage.
    harness.release_agent(starter)
    harness.join(starter)
    time.sleep(0.05)  # sase-test-wait: delayed runner admission window
    harness.assert_parked_not_started(competitor)

    # A finished monitor with no successor yet holds nothing -- that gap is
    # real (the successor is a separate, later admission), so the first
    # competitor must stop polling before it opens rather than racing it.
    harness.kill_parked(competitor)

    monitor_release.parent.mkdir(parents=True, exist_ok=True)
    monitor_release.touch()
    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"

    from sase.monitor.output import OutputCapture

    handoff_meta = json.loads(
        (Path(record.artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    handoff_meta["monitor_next_action"] = "Report that the land family finished."

    successor_holder: dict[str, _Agent] = {}

    def fake_spawn(**kwargs: object) -> AgentLaunchResult:
        extra_env = kwargs["extra_env"]
        assert isinstance(extra_env, dict)
        plan = json.loads(extra_env["SASE_AGENT_FAMILY_ATTACH"])
        successor = harness.create_agent(
            2,
            name=plan["agent_name"],
            parent_timestamp=Path(record.artifacts_dir).name,
            agent_family="land",
            queue_weight=2.0,
            queue_weight_explicit=True,
        )
        successor_holder["agent"] = successor
        harness.start(successor)
        harness.wait_started(successor)
        return AgentLaunchResult(
            pid=os.getpid(),
            workspace_num=0,
            workspace_dir=str(harness.workspace),
            output_path=str(harness.root / "monitor-successor.log"),
            agent_name=plan["agent_name"],
        )

    monkeypatch.setattr(monitor_followup_module, "spawn_agent_subprocess", fake_spawn)
    result = launch_followup_agent(
        record.artifacts_dir,
        handoff_meta,
        monitor_state=str(done["monitor_state"]),
        exit_code=done.get("monitor_exit_code"),  # type: ignore[arg-type]
        elapsed_seconds=float(done.get("monitor_elapsed_seconds") or 0.0),
        capture=OutputCapture(),
        project_name=_MONITOR_PROJECT,
        settle_timeout_seconds=5.0,
    )
    assert result.launched is True

    successor = successor_holder["agent"]
    successor_meta = harness.agent_meta(successor)
    assert successor_meta["runner_claim_owner_key"] == starter_owner_key
    assert successor_meta["queue_weight"] == 2.0
    assert successor_meta["queue_weight_explicit"] is True

    # A second competitor, introduced only once the successor is confirmed
    # live, proves the successor -- not the finished monitor -- now holds
    # the family's one 2.0 claim.
    late_competitor = harness.create_agent(
        3, name="late-competitor", queue_weight=2.0, queue_weight_explicit=True
    )
    harness.start(late_competitor)
    harness.wait_parked(late_competitor)

    harness.release_agent(successor)
    harness.join(successor)
    harness.wait_started(late_competitor)
    harness.release_agent(late_competitor)
    harness.join(late_competitor)


def test_independently_weighted_parallel_member_and_its_serial_successor_keep_own_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parallel member sharing a land family's display name keeps its own
    claim, and its own serial successor reuses that claim -- never the land
    family's -- through real ``wait_for_runner_slot`` contention.
    """
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=3)

    land_root = harness.create_agent(
        0,
        name="land2--0",
        agent_family="land2",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    harness.start(land_root)
    harness.wait_started(land_root)
    land_owner_key = harness.agent_meta(land_root).get("runner_claim_owner_key")
    assert isinstance(land_owner_key, str) and land_owner_key

    parallel_member = harness.create_agent(
        1,
        name="land2--p0",
        agent_family="land2",
        agent_family_parallel=True,
        queue_weight=1.0,
        queue_weight_explicit=True,
    )
    harness.start(parallel_member)
    harness.wait_started(parallel_member)
    parallel_owner_key = harness.agent_meta(parallel_member).get(
        "runner_claim_owner_key"
    )
    assert isinstance(parallel_owner_key, str) and parallel_owner_key
    assert parallel_owner_key != land_owner_key

    # Admitted while its predecessor is still live -- the serial-overlap
    # dedup rule that keeps this one lineage at one claim, not two, matches
    # the shape production retry/pipe handoffs use. The successor carries no
    # `agent_family_parallel` marker of its own; it continues the parallel
    # member's specific lineage (via `parent_timestamp`), not the land
    # family's active one.
    parallel_successor = harness.create_agent(
        3,
        name="land2--p1",
        parent_timestamp=parallel_member.artifacts_dir.name,
        agent_family="land2",
        queue_weight=1.0,
        queue_weight_explicit=False,
    )
    harness.start(parallel_successor)
    harness.wait_started(parallel_successor)
    successor_owner_key = harness.agent_meta(parallel_successor).get(
        "runner_claim_owner_key"
    )
    assert successor_owner_key == parallel_owner_key
    assert successor_owner_key != land_owner_key
    assert harness.agent_meta(land_root)["runner_claim_owner_key"] == land_owner_key

    harness.release_agent(parallel_member)
    harness.join(parallel_member)

    # Only introduced now (rather than racing the successor's admission):
    # capacity is fully committed (2.0 + 1.0 == cap), so this unrelated
    # contender stays parked -- the two lineages were never merged nor
    # double-counted.
    extra = harness.create_agent(2, name="extra", queue_weight=0.5)
    harness.start(extra)
    harness.wait_parked(extra)

    harness.release_agent(parallel_successor)
    harness.join(parallel_successor)
    harness.wait_started(extra)
    harness.release_agent(extra)
    harness.join(extra)
    harness.release_agent(land_root)
    harness.join(land_root)
