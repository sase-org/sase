"""Tests for the provider teardown reaper's tree walk, exclusions, and sweep."""

from __future__ import annotations

import signal
import subprocess
from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import _subprocess_reap as reap
from sase.llm_provider._subprocess_reap import (
    TeardownStall,
    _ancestor_pids,
    _DescendantSweepPlan,
    _parse_process_table,
    _plan_descendant_sweep,
    _ProcessEntry,
    _select_reapable_descendants,
    _SweepTarget,
    terminate_process_tree,
)


def _table(*rows: tuple[int, int, str]) -> list[_ProcessEntry]:
    return [_ProcessEntry(pid, ppid, argv) for pid, ppid, argv in rows]


def _selected_pids(
    root: int,
    table: list[_ProcessEntry],
    *,
    protected: set[int] | None = None,
    current_pid: int = 999_999,
) -> set[int]:
    selected = _select_reapable_descendants(
        root, table, protected_pids=protected or set(), current_pid=current_pid
    )
    return {entry.pid for entry in selected}


def test_parse_process_table_skips_malformed_rows() -> None:
    text = (
        "  100     1 /bin/sh -c python3 /tmp/listen.py 2>&1 | head -n 30\n"
        "\n"
        "  bogus   1 not-a-pid\n"
        "  200   100\n"
        "  300\n"
    )

    assert _parse_process_table(text) == [
        _ProcessEntry(100, 1, "/bin/sh -c python3 /tmp/listen.py 2>&1 | head -n 30"),
        _ProcessEntry(200, 100, ""),
    ]


def test_walk_selects_transitive_descendants_only() -> None:
    table = _table(
        (100, 1, "provider"),
        (200, 100, "child"),
        (300, 200, "grandchild"),
        (500, 1, "unrelated"),
        (600, 500, "unrelated child"),
    )

    assert _selected_pids(100, table) == {200, 300}


def test_walk_reaches_a_descendant_in_a_different_session() -> None:
    """The incident shape: a leaked shell that made itself a session leader.

    The table carries no session data on purpose. The walk follows ``ppid``
    alone, so a session or process-group boundary between the provider and
    the leaked ``sh`` (which a ``killpg`` would not cross) changes nothing.
    """
    table = _table(
        (100, 1, "muse exec --json"),
        (200, 100, "/bin/sh -c python3 /tmp/muse_usage_listen_a.py 2>&1 | head"),
        (300, 200, "python3 /tmp/muse_usage_listen_a.py"),
        (400, 300, "muse serve"),
    )

    assert _selected_pids(100, table) == {200, 300, 400}


def test_walk_never_selects_a_registered_monitor_or_what_it_spawned() -> None:
    table = _table(
        (100, 1, "muse exec --json"),
        (200, 100, "sase monitor supervisor"),
        (210, 200, "long-running monitored command"),
        (220, 210, "its helper"),
        (300, 100, "/bin/sh leaked"),
        (310, 300, "python3 leaked.py"),
    )

    selected = _selected_pids(100, table, protected={200})

    assert selected == {300, 310}
    assert selected.isdisjoint({200, 210, 220})


def test_walk_never_selects_the_current_process_or_its_ancestors() -> None:
    table = _table(
        (100, 1, "provider"),
        (150, 100, "intermediate runner ancestor"),
        (160, 150, "this process"),
        (170, 160, "this process's own child"),
        (300, 100, "leaked"),
    )

    assert _selected_pids(100, table, current_pid=160) == {300}


def test_walk_survives_a_ppid_cycle() -> None:
    table = _table((100, 1, "provider"), (200, 300, "a"), (300, 200, "b"))

    assert _selected_pids(100, table) == set()
    assert _ancestor_pids(200, {200: 300, 300: 200}) == {200, 300}
    assert _ancestor_pids(1, {1: 1}) == {1}


def test_plan_carries_argv_and_identity_for_each_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reap, "process_identity_token", lambda pid: f"boot:{pid}")
    table = _table((100, 1, "provider"), (200, 100, "python3 /tmp/listen.py"))

    plan = _plan_descendant_sweep(
        100, read_table=lambda: table, read_registry=lambda: frozenset()
    )

    assert plan.skipped_reason is None
    assert plan.targets == [
        _SweepTarget(200, 100, "python3 /tmp/listen.py", "boot:200")
    ]


def test_plan_consults_the_registry_for_protected_pids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reap, "process_identity_token", lambda pid: f"boot:{pid}")
    table = _table(
        (100, 1, "provider"), (200, 100, "registered monitor"), (300, 100, "leak")
    )

    plan = _plan_descendant_sweep(
        100, read_table=lambda: table, read_registry=lambda: frozenset({200})
    )

    assert [target.pid for target in plan.targets] == [300]


def test_plan_selects_nothing_when_the_registry_is_unreadable() -> None:
    table = _table((100, 1, "provider"), (200, 100, "could be a monitor"))

    plan = _plan_descendant_sweep(
        100, read_table=lambda: table, read_registry=lambda: None
    )

    assert plan.targets == []
    assert plan.skipped_reason == "live agent registry unavailable"


def test_plan_selects_nothing_without_a_process_table() -> None:
    plan = _plan_descendant_sweep(
        100, read_table=lambda: [], read_registry=lambda: frozenset()
    )

    assert plan.targets == []
    assert plan.skipped_reason == "process table unavailable"


def test_plan_drops_targets_without_identity_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reap, "process_identity_token", lambda pid: "")
    table = _table((100, 1, "provider"), (200, 100, "leak"))

    plan = _plan_descendant_sweep(
        100, read_table=lambda: table, read_registry=lambda: frozenset()
    )

    assert plan.targets == []


class _FakeProcess:
    """Popen stand-in whose ``wait`` can be told to time out."""

    pid = 100

    def __init__(self, *, ignores_sigterm: bool = False) -> None:
        self.ignores_sigterm = ignores_sigterm
        self.returncode: int | None = None
        self.events: list[str] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.events.append("terminate")
        if not self.ignores_sigterm:
            self.returncode = -signal.SIGTERM

    def kill(self) -> None:
        self.events.append("kill")
        self.returncode = -signal.SIGKILL

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout or 0)
        return self.returncode


def _terminate(
    process: _FakeProcess,
    plan: _DescendantSweepPlan | None = None,
    *,
    timeout: float = 1.0,
    plan_sweep: Callable[[int], _DescendantSweepPlan] | None = None,
) -> TeardownStall:
    """Run ``terminate_process_tree`` over *process* and return the stall it filled."""
    stall = TeardownStall(
        runtime="fake", provider_pid=process.pid, declared_at="", grace_seconds=0.0
    )
    terminate_process_tree(
        cast("subprocess.Popen[str]", process),
        stall,
        timeout=timeout,
        plan_sweep=plan_sweep or (lambda _pid: plan or _DescendantSweepPlan()),
    )
    return stall


def _reaped_pids(stall: TeardownStall) -> list[object]:
    return [item["pid"] for item in stall.descendants]


def _fake_process_table(
    monkeypatch: pytest.MonkeyPatch,
    alive: dict[int, str],
    *,
    ignoring_sigterm: frozenset[int] = frozenset(),
) -> list[tuple[int, int]]:
    """Fake identity lookups and ``os.kill`` over an in-memory *alive* table."""
    kills: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        if pid not in alive:
            raise ProcessLookupError(pid)
        kills.append((pid, sig))
        if sig == signal.SIGKILL or (
            sig == signal.SIGTERM and pid not in ignoring_sigterm
        ):
            del alive[pid]

    monkeypatch.setattr(reap.os, "kill", fake_kill)
    monkeypatch.setattr(reap, "process_identity_token", lambda pid: alive.get(pid, ""))
    monkeypatch.setattr(reap, "_SWEEP_TERM_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(reap, "_SWEEP_POLL_SECONDS", 0.005)
    return kills


def test_terminate_snapshots_descendants_before_signalling_the_provider() -> None:
    process = _FakeProcess()
    order: list[str] = []

    def plan_sweep(pid: int) -> _DescendantSweepPlan:
        order.append(f"plan:{pid}:{list(process.events)}")
        return _DescendantSweepPlan()

    _terminate(process, plan_sweep=plan_sweep)

    # The plan ran while the provider was still untouched: once it dies its
    # children reparent to init and the ppid walk would find nothing.
    assert order == ["plan:100:[]"]
    assert process.events == ["terminate"]


def test_terminate_escalates_to_sigkill_when_sigterm_is_ignored() -> None:
    process = _FakeProcess(ignores_sigterm=True)

    _terminate(process, timeout=0.01)

    assert process.events == ["terminate", "kill"]
    assert process.returncode == -signal.SIGKILL


def test_terminate_leaves_an_already_exited_provider_alone() -> None:
    process = _FakeProcess()
    process.returncode = 0

    _terminate(process)

    assert process.events == []


def test_terminate_records_why_the_sweep_was_skipped() -> None:
    plan = _DescendantSweepPlan(skipped_reason="live agent registry unavailable")

    stall = _terminate(_FakeProcess(), plan)

    assert stall.descendants == []
    assert stall.sweep_skipped_reason == "live agent registry unavailable"


def test_sweep_terms_then_kills_survivors_and_reports_the_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alive = {200: "id200", 300: "id300", 400: "id400"}
    kills = _fake_process_table(monkeypatch, alive, ignoring_sigterm=frozenset({400}))
    plan = _DescendantSweepPlan(
        targets=[
            _SweepTarget(200, 100, "sh -c leak", "id200"),
            _SweepTarget(300, 200, "python3 leak.py", "id300"),
            _SweepTarget(400, 300, "muse serve", "id400"),
        ]
    )

    stall = _terminate(_FakeProcess(), plan)

    assert alive == {}
    assert _reaped_pids(stall) == [200, 300, 400]
    assert stall.descendants[0] == {"pid": 200, "ppid": 100, "argv": "sh -c leak"}
    assert (400, signal.SIGKILL) in kills
    assert (200, signal.SIGKILL) not in kills


def test_sweep_skips_a_pid_that_now_belongs_to_a_different_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recycled pid has a new start time, so the snapshot identity is stale."""
    alive = {200: "recycled-identity", 300: "id300"}
    kills = _fake_process_table(monkeypatch, alive)
    plan = _DescendantSweepPlan(
        targets=[
            _SweepTarget(200, 100, "long gone", "id200"),
            _SweepTarget(300, 100, "leak", "id300"),
        ]
    )

    stall = _terminate(_FakeProcess(), plan)

    assert [pid for pid, _sig in kills] == [300]
    assert _reaped_pids(stall) == [300]
    assert 200 in alive


def test_sweep_ignores_targets_that_already_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kills = _fake_process_table(monkeypatch, {})
    plan = _DescendantSweepPlan(targets=[_SweepTarget(200, 100, "gone", "id200")])

    stall = _terminate(_FakeProcess(), plan)

    assert kills == []
    assert stall.descendants == []


def test_registered_live_pids_is_none_when_the_registry_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**_kwargs: object) -> list[object]:
        raise RuntimeError("index unavailable")

    monkeypatch.setattr("sase.agent.running_listing.list_running_agents", boom)

    assert reap._registered_live_pids() is None


def test_registered_live_pids_unions_agents_and_procs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.running_listing.list_running_agents",
        lambda **_kwargs: [MagicMock(pid=11), MagicMock(pid=None), MagicMock(pid=12)],
    )
    monkeypatch.setattr(
        "sase.procs.store.read_procs",
        lambda **_kwargs: [MagicMock(pid=21), MagicMock(pid=None)],
    )

    assert reap._registered_live_pids() == frozenset({11, 12, 21})
