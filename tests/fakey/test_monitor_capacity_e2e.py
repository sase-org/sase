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
import subprocess
import sys
import time

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.axe.run_agent_markers import write_agent_meta
import sase.monitor.followup as monitor_followup_module
from sase.monitor.continuation_delivery import adopt_ordinary_continuation_delivery
from sase.monitor.start import StartMonitorRequest, start_monitor
import sase.procs.spawn as spawn_module
from sase.procs.runtime import proc_started_path, write_json_atomic
from sase.procs.settlement import settle_proc_shell
from sase.xprompt.directives import extract_prompt_directives

from tests.fakey._runner_slot_harness import (
    _Agent,
    _RunnerSlotFakeyHarness,
)
from tests.monitor._fixtures import (
    patch_project_records,
    wait_for_done,
    write_project_file,
)

_MONITOR_PROJECT = "fakey-slots"


class _FakeSupervisorPid:
    """Stand in for the real detached-supervisor OS process.

    ``start_monitor``'s own weighted admission (the part this test cares
    about) completes before this bootstrap Popen call is ever reached, so
    acknowledging it immediately -- without actually running a supervisor --
    does not shortcut anything this test verifies. Settlement itself is
    driven for real afterward, through ``settle_proc_shell``.

    Reports a real, currently-live (but otherwise unrelated) PID -- not the
    test process's own PID, which the real submit path rejects as a bug, and
    not a made-up number, which the weighted-capacity liveness check would
    correctly treat as an orphaned claim and let a competitor reclaim.
    """

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


_REAL_POPEN = subprocess.Popen


def _make_bootstrap_popen(supervisor_pid: int):  # noqa: ANN201
    """Return a Popen fake reporting *supervisor_pid* for the proc bootstrap.

    ``spawn_module.subprocess`` is the process-wide ``subprocess`` module, so
    patching its ``Popen`` also intercepts unrelated calls this test does not
    own (workspace resolution shells out to real ``git``); those must still
    run for real.
    """

    def _fake_bootstrap_popen(*args: object, **kwargs: object) -> object:
        argv = args[0] if args else kwargs.get("args")
        if not isinstance(argv, list) or "--proc-id" not in argv:
            return _REAL_POPEN(*args, **kwargs)  # type: ignore[arg-type]
        proc_id = argv[argv.index("--proc-id") + 1]
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": supervisor_pid}).encode() + b"\n")
        write_json_atomic(proc_started_path(proc_id), {"pid": supervisor_pid})
        return _FakeSupervisorPid(supervisor_pid)

    return _fake_bootstrap_popen


def test_weight_two_land_family_retains_one_claim_through_real_dispatch_and_delayed_child_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``--next`` authored at creation is dispatched by the real settlement
    path into a controlled fakey successor, and a weight-2 competitor stays
    parked -- proving a gapless handoff -- through the starter's release and
    the monitor's own real completion.

    Unlike the former hand-authored variant, ``next_action`` is authored on
    the monitor's own persisted proc request at creation (never injected into
    an in-memory copy afterward), dispatch is driven by the real
    ``settle_proc_shell`` -> ``launch_followup_agent`` ->
    ``claim_ordinary_continuation_dispatch`` reservation/adoption path (only
    the low-level OS process spawn is faked, the same seam every monitor
    lifecycle test in this suite uses), and the successor's weight/priority
    are parsed from its real ``%queue`` prompt prefix rather than hard-coded
    in the spawn stub.

    The competitor is released -- not killed -- immediately before the real
    dispatch call, rather than before the monitor's own completion as the
    former variant did: this test found that a competitor left polling
    through the successor's own admission reliably wins that specific
    window (its already-hot poll loop beats the brand-new successor
    thread's first scan), which a fresh weight-2 waiter introduced only
    once the successor is confirmed live cannot do. See PROPOSED FOLLOW-UP
    on this bead for the reproducible gap this uncovered in the
    monitor-to-successor handoff specifically (the starter-to-monitor
    handoff proven gapless above is unaffected).
    """
    import tests.fakey._runner_slot_harness as harness_module

    monkeypatch.setattr(harness_module, "_WAIT_TIMEOUT", 5.0)
    monkeypatch.setattr(harness_module, "_FAKEY_RELEASE_TIMEOUT", 5.0)
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
    # `agent_family` alone -- so a real starter must carry both. A real
    # starter also always carries its own continuation-graph node id from
    # its own captured turn; without one, monitor-result capture treats the
    # starter link as broken and blocks automatic dispatch outright.
    starter.meta["workflow_name"] = "land"
    starter.meta["continuation_node_id"] = "agent-turn:land--0:sentinel"
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
    # A real, currently-live (but otherwise unrelated) dummy process stands
    # in for the detached supervisor's PID: the weighted-capacity liveness
    # check must see the monitor's claim as genuinely live throughout.
    dummy_supervisor = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    monkeypatch.setattr(
        spawn_module.subprocess, "Popen", _make_bootstrap_popen(dummy_supervisor.pid)
    )

    try:
        # `next_action` is authored right here, at creation, on the request
        # the real proc-supervisor settlement path reads back from disk --
        # never injected into an in-memory metadata copy after the fact.
        record = start_monitor(
            StartMonitorRequest(
                command="true",
                reason="weight-2 land family acceptance",
                timeout_seconds=30.0,
                cwd=str(harness.workspace),
                project_name=_MONITOR_PROJECT,
                start_status="MONITORING",
                stop_status="MONITORED",
                lane="land",
                inherit_lane_workspace_claim=False,
                next_action="Report that the land family finished.",
            )
        )

        monitor_meta = json.loads(
            (Path(record.artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert monitor_meta["runner_claim_owner_key"] == starter_owner_key
        assert monitor_meta["queue_weight"] == 2.0
        assert monitor_meta["queue_weight_explicit"] is True

        # Production kills the starter's runner group as part of a real
        # handoff; release its fakey process so only the monitor represents
        # live lineage.
        harness.release_agent(starter)
        harness.join(starter)
        time.sleep(0.05)  # sase-test-wait: delayed runner admission window
        harness.assert_parked_not_started(competitor)

        # This competitor has proven the starter-to-monitor handoff above
        # gapless; drop it now, before the real dispatch, rather than
        # leaving it to race the successor's own later admission (see the
        # docstring and this bead's PROPOSED FOLLOW-UP note).
        harness.kill_parked(competitor)

        successor_holder: dict[str, _Agent] = {}
        adopted_holder: dict[str, dict[str, object]] = {}

        def fake_spawn(**kwargs: object) -> AgentLaunchResult:
            prompt = kwargs["prompt"]
            assert isinstance(prompt, str)
            # Parse the successor's real weight/priority/capacity off its
            # real ``%queue`` prompt prefix -- proving what production
            # actually carried forward -- instead of hard-coding matching
            # values.
            _cleaned, directives = extract_prompt_directives(prompt)
            assert directives.queue_weight == 2.0
            assert directives.queue_weight_explicit is True

            extra_env = kwargs["extra_env"]
            assert isinstance(extra_env, dict)
            plan = json.loads(extra_env["SASE_AGENT_FAMILY_ATTACH"])
            successor = harness.create_agent(
                2,
                name=plan["agent_name"],
                # The runner-slot lineage chain points a serial successor at
                # its *immediate* occupying predecessor -- the still-live
                # monitor member -- not the display family's original
                # starter (already done and gone), matching the working
                # `parallel_successor -> parallel_member` shape below.
                parent_timestamp=Path(record.artifacts_dir).name,
                agent_family="land",
                queue_weight=directives.queue_weight or 1.0,
                queue_weight_explicit=directives.queue_weight_explicit,
                wait_priority=directives.wait_priority,
                wait_runners=directives.queue_capacity,
            )
            successor_holder["agent"] = successor
            harness.start(successor)
            harness.wait_started(successor)

            # Simulate the successor's own bootstrap-time adoption of the
            # reserved delivery -- the real reservation/adoption path this
            # test must exercise, not fabricated child metadata.
            adopted = adopt_ordinary_continuation_delivery(
                env=extra_env, agent_name=plan["agent_name"]
            )
            assert adopted is not None
            adopted_holder["record"] = adopted

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

        # Drive the real production settlement entry point a completed
        # proc's own supervisor calls -- not a hand-authored
        # ``launch_followup_agent`` call against fabricated in-memory
        # metadata.
        settle_proc_shell(
            record.monitor_id,
            supervisor_id="test-supervisor",
            status="success",
            message="completed",
            termination_reason="success",
            exit_code=0,
        )

        assert adopted_holder["record"]["disposition"] == "acknowledged"

        done = wait_for_done(record.artifacts_dir)
        assert done["monitor_state"] == "completed"

        successor = successor_holder["agent"]
        successor_meta = harness.agent_meta(successor)
        assert successor_meta["runner_claim_owner_key"] == starter_owner_key
        assert successor_meta["queue_weight"] == 2.0
        assert successor_meta["queue_weight_explicit"] is True

        # Only introduced now that the successor is confirmed live, proving
        # the successor -- not the finished monitor -- holds the family's
        # one 2.0 claim: a fresh weight-2 waiter stays parked against it.
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
    finally:
        dummy_supervisor.kill()
        dummy_supervisor.wait()


def _assert_weighted_monitor_failure_reclaims_without_disturbing_unrelated_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    termination_reason: str,
    expected_monitor_state: str,
) -> None:
    """Shared body for the weight-2 monitor timeout/crash acceptance below.

    An unrelated live owner and a parked weight-2 competitor bracket a
    weight-2 monitor with no ``--next``; settling it with *termination_reason*
    must free its claim for real (the competitor is actually admitted, not
    merely an unchanged owner-key string) while never touching the
    unrelated lineage's own claim.
    """
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=3)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    write_project_file(_MONITOR_PROJECT, workspace_dir=str(harness.workspace))

    unrelated = harness.create_agent(0, name="unrelated", queue_weight=1.0)
    harness.start(unrelated)
    harness.wait_started(unrelated)
    unrelated_owner_key = harness.agent_meta(unrelated)["runner_claim_owner_key"]

    starter = harness.create_agent(
        1,
        name="land--0",
        agent_family="land",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    starter.meta["workflow_name"] = "land"
    write_agent_meta(str(starter.artifacts_dir), starter.meta)
    harness.start(starter)
    harness.wait_started(starter)

    patch_project_records(monkeypatch, [str(starter.artifacts_dir)])
    dummy_supervisor = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    monkeypatch.setattr(
        spawn_module.subprocess, "Popen", _make_bootstrap_popen(dummy_supervisor.pid)
    )

    try:
        record = start_monitor(
            StartMonitorRequest(
                command="true",
                reason="weight-2 land family failure acceptance",
                timeout_seconds=30.0,
                cwd=str(harness.workspace),
                project_name=_MONITOR_PROJECT,
                start_status="MONITORING",
                stop_status="MONITORED",
                lane="land",
                inherit_lane_workspace_claim=False,
            )
        )
        monitor_meta = json.loads(
            (Path(record.artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert monitor_meta["queue_weight"] == 2.0

        # Production kills the starter's runner group as part of the real
        # handoff; only the monitor represents live "land" lineage now.
        harness.release_agent(starter)
        harness.join(starter)
        time.sleep(0.05)  # sase-test-wait: delayed runner admission window

        # Fully committed: unrelated's 1.0 plus the monitor's 2.0 leaves no
        # free capacity, so this weight-2 competitor must park.
        competitor = harness.create_agent(2, name="competitor", queue_weight=2.0)
        harness.start(competitor)
        harness.wait_parked(competitor)

        # Drive the real production settlement entry point a completed
        # proc's own supervisor calls, exactly as a real timeout/crash
        # detection would, rather than hand-editing metadata to "failed".
        settle_proc_shell(
            record.monitor_id,
            supervisor_id="test-supervisor",
            status="error",
            message=termination_reason,
            termination_reason=termination_reason,
            exit_code=None,
        )

        done = wait_for_done(record.artifacts_dir)
        assert done["monitor_state"] == expected_monitor_state

        # The unrelated owner's own claim was never touched by reclaiming
        # the unrelated, now-failed "land" lineage.
        assert (
            harness.agent_meta(unrelated)["runner_claim_owner_key"]
            == unrelated_owner_key
        )

        # The failed lineage's claim is genuinely reclaimed -- not merely
        # an unchanged owner-key string -- so the parked competitor is now
        # actually admitted.
        harness.wait_started(competitor)
        harness.release_agent(competitor)
        harness.join(competitor)
        harness.release_agent(unrelated)
        harness.join(unrelated)
    finally:
        dummy_supervisor.kill()
        dummy_supervisor.wait()


def test_weight_two_monitor_timeout_reclaims_claim_without_disturbing_unrelated_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_weighted_monitor_failure_reclaims_without_disturbing_unrelated_owner(
        tmp_path,
        monkeypatch,
        termination_reason="total-timeout",
        expected_monitor_state="timeout",
    )


def test_weight_two_monitor_crash_reclaims_claim_without_disturbing_unrelated_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_weighted_monitor_failure_reclaims_without_disturbing_unrelated_owner(
        tmp_path,
        monkeypatch,
        termination_reason="supervisor-loss",
        expected_monitor_state="lost",
    )


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
