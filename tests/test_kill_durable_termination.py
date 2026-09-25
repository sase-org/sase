"""The durable persist-cleanup stage terminates processes before releasing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents import AgentsMixin, _kill_termination
from sase.ace.tui.actions.agents._kill_persistence import BulkKillItem
from sase.ace.tui.actions.agents._kill_transactions import (
    persist_bulk_kill_transaction,
    persist_single_kill_transaction,
    single_kill_targets,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.process_tree import process_is_running
from sase.agent.user_kill import AgentTerminationResult
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    AgentCleanupArtifactDeleteIntentWire,
    AgentCleanupIdentityWire,
    AgentCleanupKillItemWire,
    AgentCleanupPlanWire,
    AgentCleanupSideEffectsWire,
    AgentCleanupWorkspaceReleaseIntentWire,
)

from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin
from tests._agent_process_tree_helpers import (
    assert_dead,
    launch_runner,
    no_registry,
    reap as reap,
    scratch_key as scratch_key,
    write_meta,
)

_KILLING = "sase.ace.tui.actions.agents._killing"


def _agent(
    tmp_path: Path,
    pid: int | None,
    *,
    suffix: str = "20260501010101",
    status: str = "RUNNING",
    workflow: str | None = None,
    cl_name: str = "feature_one",
    **kwargs: Any,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=None,
        workflow=workflow,
        pid=pid,
        raw_suffix=suffix,
        artifacts_dir=str(tmp_path / f"artifacts-{suffix}"),
        **kwargs,
    )


def _wire_identity(agent: Agent) -> AgentCleanupIdentityWire:
    return AgentCleanupIdentityWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
    )


class _Events:
    """Record the order of every durable-stage effect."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[Any] = []
        self.dead: set[int] = set()
        self.survivors: set[int] = set()
        self.live_verified: set[int] = set()
        monkeypatch.setattr(
            "sase.ace.dismissed_agents.add_dismissed_agents", self._save
        )
        monkeypatch.setattr(
            f"{_KILLING}.sync_dismissed_agent_artifact_index", self._sync
        )
        monkeypatch.setattr(
            f"{_KILLING}.dismiss_notifications_for_agents", self._notify
        )
        monkeypatch.setattr(f"{_KILLING}.persist_kill_side_effects", self._effects)
        monkeypatch.setattr(
            f"{_KILLING}.persist_bulk_kill_side_effects", self._bulk_effects
        )
        monkeypatch.setattr(
            "sase.agent.user_kill.terminate_agent_processes", self._terminate
        )
        monkeypatch.setattr(
            _kill_termination,
            "live_verified_agent_pid",
            lambda pid, artifacts_dir=None: pid in self.live_verified,
        )

    def _save(self, added: Any) -> set[Any]:
        self.events.append("save")
        return set(added)

    def _sync(self, snapshot: object) -> None:
        self.events.append("sync")

    def _notify(self, agents: list[Agent]) -> None:
        self.events.append(("notify", sorted(a.pid or 0 for a in agents)))

    def _effects(self, *args: Any, **kwargs: Any) -> bool:
        self.events.append(("effects", args, kwargs))
        return False

    def _bulk_effects(self, *args: Any, **kwargs: Any) -> None:
        self.events.append(("bulk_effects", args, kwargs))

    def _terminate(self, pid: int, **kwargs: Any) -> AgentTerminationResult:
        self.events.append(("terminate", pid))
        if pid in self.survivors:
            return AgentTerminationResult(
                False, "survivors", pid, pid, error="still alive", survivors=(pid + 1,)
            )
        self.dead.add(pid)
        return AgentTerminationResult(True, "killed", pid, pid)

    def names(self) -> list[Any]:
        return [e if isinstance(e, str) else e[0] for e in self.events]

    def terminated(self) -> list[int]:
        return sorted(e[1] for e in self.events if e[0] == "terminate")


def test_single_kill_publishes_then_terminates_then_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = _agent(tmp_path, 111)
    recorder = _Events(monkeypatch)

    persist_single_kill_transaction(
        agent, "running", [agent], {agent.identity}, None, [agent]
    )

    assert recorder.names() == ["save", "sync", "notify", "terminate", "effects"]
    assert recorder.events[3] == ("terminate", 111)


def test_single_kill_terminates_every_planned_target_but_not_monitors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _agent(tmp_path, 111, suffix="root")
    member = _agent(tmp_path, 222, suffix="member", cl_name="feature_two")
    monitor = _agent(tmp_path, 333, suffix="monitor", cl_name="feature_three")
    plan = AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        kill_items=tuple(
            AgentCleanupKillItemWire(
                identity=_wire_identity(target), kind=kind, pid=target.pid
            )
            for target, kind in ((member, "running"), (monitor, "monitor"))
        ),
    )
    recorder = _Events(monkeypatch)

    persist_single_kill_transaction(
        root, "running", [root, member, monitor], {root.identity}, plan, [root]
    )

    assert recorder.terminated() == [111, 222]


def test_survivor_keeps_its_workspace_claim_and_the_error_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = _agent(tmp_path, 111)
    recorder = _Events(monkeypatch)
    recorder.survivors = {111}

    with pytest.raises(_kill_termination.AgentSurvivorsError) as excinfo:
        persist_single_kill_transaction(
            agent, "running", [agent], {agent.identity}, None, [agent]
        )

    assert "112" in str(excinfo.value)
    # The dismissal was published and the notifications dismissed, but no
    # workspace release or artifact deletion ran for the survivor.
    assert recorder.names() == ["save", "sync", "notify", "terminate"]


def test_survivor_among_planned_targets_only_withholds_that_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _agent(tmp_path, 111, suffix="root")
    stuck = _agent(tmp_path, 222, suffix="stuck", cl_name="feature_two")
    plan = AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        kill_items=(
            AgentCleanupKillItemWire(
                identity=_wire_identity(stuck), kind="running", pid=222
            ),
        ),
        side_effects=AgentCleanupSideEffectsWire(
            artifact_delete_paths=(
                AgentCleanupArtifactDeleteIntentWire(_wire_identity(root), "/root"),
                AgentCleanupArtifactDeleteIntentWire(_wire_identity(stuck), "/stuck"),
            ),
            workspace_release_requests=(
                AgentCleanupWorkspaceReleaseIntentWire(
                    _wire_identity(root), "/tmp/test.sase", workspace=1
                ),
                AgentCleanupWorkspaceReleaseIntentWire(
                    _wire_identity(stuck), "/tmp/test.sase", workspace=2
                ),
            ),
        ),
    )
    recorder = _Events(monkeypatch)
    recorder.survivors = {222}

    with pytest.raises(_kill_termination.AgentSurvivorsError):
        persist_single_kill_transaction(
            root, "running", [root, stuck], {root.identity}, plan, [root]
        )

    effects = next(e for e in recorder.events if e[0] == "effects")
    persisted = effects[1][3].side_effects
    assert [i.artifacts_dir for i in persisted.artifact_delete_paths] == ["/root"]
    assert [i.workspace for i in persisted.workspace_release_requests] == [1]


def test_dismissed_live_non_terminal_rows_get_the_safety_net(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _agent(tmp_path, None, suffix="root")
    retrying = _agent(tmp_path, 222, suffix="retry", status="FAILED", cl_name="r")
    done = _agent(tmp_path, 333, suffix="done", status="DONE", cl_name="d")
    gone = _agent(tmp_path, 444, suffix="gone", status="FAILED", cl_name="g")
    recorder = _Events(monkeypatch)
    recorder.live_verified = {222, 333}  # 444's runner is not provably alive

    persist_bulk_kill_transaction(
        [], [root, retrying, done, gone], {root.identity}, [], None, None
    )

    # DONE is success-terminal (its runner is finishing host-owned work) and
    # 444 has no live verified runner: only the retrying FAILED row is killed.
    assert recorder.terminated() == [222]


def test_bulk_kill_persists_the_verified_and_reports_the_survivors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok = _agent(tmp_path, 111, suffix="ok")
    stuck = _agent(tmp_path, 222, suffix="stuck", cl_name="feature_two")
    ok_item = BulkKillItem(agent=ok, kind="running", identities={ok.identity})
    stuck_item = BulkKillItem(agent=stuck, kind="running", identities={stuck.identity})
    monitor = _agent(tmp_path, 333, suffix="mon", cl_name="feature_three")
    monitor_item = BulkKillItem(
        agent=monitor, kind="monitor", identities={monitor.identity}
    )
    recorder = _Events(monkeypatch)
    recorder.survivors = {222}

    with pytest.raises(_kill_termination.AgentSurvivorsError) as excinfo:
        persist_bulk_kill_transaction(
            [ok_item, stuck_item, monitor_item],
            [],
            {ok.identity, stuck.identity},
            [ok, stuck, monitor],
            None,
            None,
        )

    assert recorder.names()[:4] == ["save", "sync", "notify", "terminate"]
    assert recorder.terminated() == [111, 222]
    args, kwargs = next(e[1:] for e in recorder.events if e[0] == "bulk_effects")
    assert args[0] == [ok_item, monitor_item]
    assert kwargs == {"publish_dismissal": False}
    assert "223" in str(excinfo.value)
    # The dismissal was saved exactly once, before any process was signalled.
    assert recorder.names().count("save") == 1


def test_single_kill_targets_resolve_the_plan_and_clan_members(
    tmp_path: Path,
) -> None:
    root = _agent(tmp_path, 111, suffix="root")
    member = _agent(tmp_path, 222, suffix="member", cl_name="feature_two")
    plan = AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        kill_items=(
            AgentCleanupKillItemWire(
                identity=_wire_identity(root), kind="workflow", pid=111
            ),
            AgentCleanupKillItemWire(
                identity=_wire_identity(member), kind="hook", pid=222
            ),
        ),
    )

    assert single_kill_targets(root, "running", plan, [root, member]) == [
        (root, "workflow"),
        (member, "hook"),
    ]
    assert single_kill_targets(root, "running", None, [root, member]) == [
        (root, "running")
    ]


def test_withhold_also_covers_workflow_step_rows(tmp_path: Path) -> None:
    parent = _agent(tmp_path, 111, suffix="parent", workflow="wf")
    step = _agent(
        tmp_path,
        None,
        suffix="step",
        cl_name="step",
        parent_workflow="wf",
        parent_timestamp="parent",
    )
    other = _agent(tmp_path, 222, suffix="other", cl_name="other")
    plan = AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        side_effects=AgentCleanupSideEffectsWire(
            artifact_delete_paths=tuple(
                AgentCleanupArtifactDeleteIntentWire(_wire_identity(a), f"/{a.cl_name}")
                for a in (parent, step, other)
            ),
        ),
    )

    filtered = _kill_termination.withhold_agent_side_effects(
        plan, [parent], [parent, step, other]
    )

    assert [i.artifacts_dir for i in filtered.side_effects.artifact_delete_paths] == [
        "/other"
    ]
    assert _kill_termination.withhold_agent_side_effects(plan, [], [parent]) is plan
    assert _kill_termination.withhold_agent_side_effects(None, [parent], []) is None


def test_durable_transaction_releases_only_after_the_process_tree_is_dead(
    tmp_path: Path,
    scratch_key: str,
    reap: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts-real"
    write_meta(artifacts, proc.pid, launch_scratch_key=scratch_key)
    agent = _agent(tmp_path, proc.pid, suffix="real")
    agent.artifacts_dir = str(artifacts)
    seen_alive_at_release: list[dict[str, bool]] = []

    def effects(*args: Any, **kwargs: Any) -> bool:
        seen_alive_at_release.append(
            {name: process_is_running(pid) for name, pid in pids.items()}
        )
        return False

    monkeypatch.setattr("sase.agent.user_kill.read_process_registry", no_registry)
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.add_dismissed_agents", lambda _s: set()
    )
    monkeypatch.setattr(f"{_KILLING}.persist_kill_side_effects", effects)
    monkeypatch.setattr(f"{_KILLING}.dismiss_notifications_for_agents", lambda _a: None)
    real_terminate = _kill_termination.user_kill.terminate_agent_processes
    monkeypatch.setattr(
        _kill_termination.user_kill,
        "terminate_agent_processes",
        lambda pid, **kwargs: real_terminate(pid, grace_seconds=0.3, **kwargs),
    )

    persist_single_kill_transaction(
        agent, "running", [agent], {agent.identity}, None, [agent]
    )

    assert seen_alive_at_release == [dict.fromkeys(pids, False)]
    assert_dead(pids)


class _App(TrackedProcRecorderMixin, AgentsMixin):
    """The slice of the TUI the kill-persistence submitters touch."""

    def __init__(self) -> None:
        self._init_tracked_task_recorder()
        self._kill_persistence_inflight: set[Any] = set()
        self._dismiss_persistence_inflight: set[Any] = set()
        self._dismissed_agents: set[Any] = set()
        self._agents_with_children: list[Agent] = []
        self.notifications: list[tuple[str, str]] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self.notifications.append((msg, severity))


def _kill_item(agent: Agent, kind: str = "running") -> BulkKillItem:
    return BulkKillItem(
        agent=agent,
        kind=kind,  # type: ignore[arg-type]
        identities={agent.identity},
    )


def test_bulk_kill_guard_drops_only_the_in_flight_rows(tmp_path: Path) -> None:
    first = _agent(tmp_path, 111, suffix="first")
    second = _agent(tmp_path, 222, suffix="second", cl_name="feature_two")
    app = _App()
    app._kill_persistence_inflight = {first.identity}
    settled: list[str] = []

    app._submit_bulk_kill_persistence_proc(  # type: ignore[attr-defined]
        [_kill_item(first), _kill_item(second)],
        [],
        {first.identity, second.identity},
        [first, second],
        on_settled=lambda: settled.append("settled"),
    )

    assert len(app.tracked_procs) == 1
    assert app._kill_persistence_inflight == {first.identity, second.identity}
    assert settled == []


def test_bulk_kill_guard_settles_at_once_when_everything_is_in_flight(
    tmp_path: Path,
) -> None:
    first = _agent(tmp_path, 111, suffix="first")
    app = _App()
    app._kill_persistence_inflight = {first.identity}
    settled: list[str] = []

    app._submit_bulk_kill_persistence_proc(  # type: ignore[attr-defined]
        [_kill_item(first)],
        [],
        {first.identity},
        [first],
        on_settled=lambda: settled.append("settled"),
    )

    assert app.tracked_procs == []
    assert settled == ["settled"]


def test_bulk_dismiss_guard_drops_only_the_in_flight_rows(tmp_path: Path) -> None:
    first = _agent(tmp_path, 111, suffix="first", status="DONE")
    second = _agent(tmp_path, 222, suffix="second", status="DONE", cl_name="two")
    app = _App()
    app._dismiss_persistence_inflight = {first.identity}

    app._submit_bulk_dismiss_persistence_task(  # type: ignore[attr-defined]
        [first, second], [first, second], None, {first.identity, second.identity}
    )

    assert len(app.tracked_procs) == 1
    assert app._dismiss_persistence_inflight == {first.identity, second.identity}


def test_rejected_cleanup_proc_falls_back_to_background_escalation(
    tmp_path: Path,
) -> None:
    first = _agent(tmp_path, 111, suffix="first")
    monitor = _agent(tmp_path, 222, suffix="mon", cl_name="feature_two")
    silent = _agent(tmp_path, None, suffix="silent", cl_name="feature_three")
    app = _App()
    app._submit_cleanup_proc = lambda **_kwargs: False  # type: ignore[method-assign]

    with patch(f"{_KILLING}.escalate_user_kill_in_background") as escalate:
        app._submit_bulk_kill_persistence_proc(  # type: ignore[attr-defined]
            [
                _kill_item(first),
                _kill_item(monitor, "monitor"),
                _kill_item(silent),
            ],
            [],
            {first.identity},
            [first, monitor, silent],
        )

    assert [call.args[0] for call in escalate.call_args_list] == [111]
    assert app._kill_persistence_inflight == set()


def test_rejected_single_kill_proc_falls_back_to_background_escalation(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path, 111)
    app = _App()
    app._submit_cleanup_proc = lambda **_kwargs: False  # type: ignore[method-assign]

    with patch(f"{_KILLING}.escalate_user_kill_in_background") as escalate:
        app._submit_kill_persistence_proc(  # type: ignore[attr-defined]
            agent, "running", [agent], {agent.identity}
        )

    assert [call.args[0] for call in escalate.call_args_list] == [111]


def test_immediate_stage_only_sends_sigterm(tmp_path: Path) -> None:
    agent = _agent(tmp_path, 111)
    app = _App()

    with patch(
        f"{_KILLING}.request_user_kill",
        return_value=SimpleNamespace(success=True, status="killed", error=None),
    ) as request_kill:
        assert app._kill_agent_process_group(agent) is True  # type: ignore[attr-defined]

    assert request_kill.call_args.kwargs["wait"] is False
    assert request_kill.call_args.kwargs["background"] is False


def _dismiss_patches(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Patch the dismissal transaction's persistence to record its order."""
    from sase.ace.tui.actions.agents import _dismissing

    effects: list[Any] = []
    monkeypatch.setattr(
        _dismissing, "persist_cleanup_side_effect_intents", lambda *a, **k: False
    )
    monkeypatch.setattr(
        _dismissing,
        "persist_dismiss_side_effects",
        lambda agent, *a, **k: effects.append(("single", agent.pid)),
    )
    monkeypatch.setattr(
        _dismissing,
        "persist_bulk_dismiss_side_effects",
        lambda agents, *a, **k: effects.append(("bulk", [a.pid for a in agents])),
    )
    monkeypatch.setattr(
        _dismissing, "dismiss_notifications_for_agents", lambda _a: None
    )
    monkeypatch.setattr(
        _dismissing, "sync_dismissed_agent_artifact_index", lambda *a, **k: True
    )
    return effects


def test_single_dismiss_terminates_a_live_failed_row_before_releasing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui.actions.agents._dismissing import (
        persist_single_dismiss_transaction,
    )

    retrying = _agent(tmp_path, 222, status="FAILED")
    recorder = _Events(monkeypatch)
    recorder.live_verified = {222}
    effects = _dismiss_patches(monkeypatch)

    persist_single_dismiss_transaction(retrying, {retrying.identity}, [retrying])

    assert recorder.terminated() == [222]
    assert effects == [("single", 222)]


def test_single_dismiss_leaves_a_success_terminal_row_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui.actions.agents._dismissing import (
        persist_single_dismiss_transaction,
    )

    finishing = _agent(tmp_path, 222, status="DONE")
    recorder = _Events(monkeypatch)
    recorder.live_verified = {222}
    effects = _dismiss_patches(monkeypatch)

    persist_single_dismiss_transaction(finishing, {finishing.identity}, [finishing])

    assert recorder.terminated() == []
    assert effects == [("single", 222)]


def test_bulk_dismiss_survivor_keeps_artifacts_and_reports_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui.actions.agents._dismissing import (
        persist_bulk_dismiss_transaction,
    )

    stuck = _agent(tmp_path, 222, status="FAILED")
    done = _agent(tmp_path, 333, suffix="done", status="DONE", cl_name="done")
    recorder = _Events(monkeypatch)
    recorder.live_verified = {222}
    recorder.survivors = {222}
    effects = _dismiss_patches(monkeypatch)

    with pytest.raises(_kill_termination.AgentSurvivorsError):
        persist_bulk_dismiss_transaction(
            [stuck, done], {stuck.identity, done.identity}, [stuck, done]
        )

    assert effects == [("bulk", [333])]
