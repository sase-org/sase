"""SAVEALL proof of async auto-refresh and Textual bead-warmup lifetimes.

The 10-second tick, incomplete-load merge, deferred live-hint apply, and
bead-warmup follow-up/apply seams must release obsolete payloads after the
visitor, row-ownership, and failed-snapshot fixes. This module exercises those
seams with a persistent AcePage (or a real Textual timer host), stubs only
storage/VCS mutations, and counts cyclic garbage while the owner stays alive.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from textual.app import App

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._loading_bead_warmup import (
    AgentBeadWarmupMixin,
    _AgentBeadWarmupCandidates,
    _AgentBeadWarmupResults,
)
from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult
from sase.ace.tui.actions.agents._roster_generation import bump_roster_generation
from sase.ace.tui.app import AceApp
from sase.ace.tui.models._agent_clan_waves import (
    ClanWaveSlot,
    ClanWaveSummary,
    _ClanWaveMemberView,
    _ClanWaveState,
    _ClanWaveView,
)
from sase.ace.tui.models._loaders._done_common import lazy_done_instruction_bundle_files
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bead import _BEAD_DISPLAY_CACHE
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.ace.tui.util.textual_cycle_guards import install_textual_cycle_guards
from sase.bead.model import Issue
from sase.core.agent_scan_wire_markers import (
    FinalizerStatusInstanceWire,
    FinalizerStatusRunnerWire,
    FinalizerStatusSummaryWire,
)
from tests.ace.tui._gc_cycles import (
    AGENT_TYPE,
    CycleGarbage,
    measure_cycle_garbage_async,
)
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent,
    make_monitor_member,
    make_plan_root,
)

_AGENT_COUNT = 100
_SASE_PREFIX = "sase."
_STARTED = datetime(2026, 9, 1, 12, 0, 0)

_PAYLOAD_TYPES = (
    AGENT_TYPE,
    "sase.ace.tui.models._agent_clan_waves.ClanWaveSlot",
    "sase.ace.tui.models._agent_clan_waves.ClanWaveSummary",
    "sase.ace.tui.models._agent_clan_waves._ClanWaveView",
    "sase.ace.tui.models._agent_clan_waves._ClanWaveMemberView",
    "sase.ace.tui.models._loaders._done_common._LazyInstructionBundleFiles",
    "sase.core.agent_scan_wire_markers.FinalizerStatusSummaryWire",
)


def _complete_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
        running_claims_scanned=True,
    )


def _incomplete_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        complete_visible_inbox=True,
    )


def _attach_payloads(root: Agent, member: Agent) -> None:
    identity = member.raw_suffix or "refresh-member"
    root.clan_waves = ClanWaveSummary(
        layered=True,
        numbered_wave_count=1,
        has_seal=False,
        waves=(
            _ClanWaveView(
                number=1,
                kind="number",
                member_identities=(identity,),
                ghost_names=(),
                state=_ClanWaveState.IN_FLIGHT,
                predecessor_identities=(),
            ),
        ),
        members=(
            _ClanWaveMemberView(
                identity=identity,
                relative_label=".code",
                wave_index=0,
                predecessors=(),
                ghost_predecessors=(),
                external_wait_count=0,
            ),
        ),
        unresolved_identities=(),
    )
    member.clan_wave_slot = ClanWaveSlot(
        wave_index=0,
        label_kind="number",
        number=1,
        rank=0,
        open=True,
    )
    member.finalizer_status = FinalizerStatusSummaryWire(
        phase="finalize",
        status="done",
        runner=FinalizerStatusRunnerWire(pid=1234, identity="test-runner"),
        instances=[
            FinalizerStatusInstanceWire(
                id="builtin@commit",
                status="done",
                attempt=1,
                max_attempts=1,
            )
        ],
        instance_count=1,
    )
    member.instruction_bundle_files = lazy_done_instruction_bundle_files(
        "/tmp/unopened-refresh-bundle"
    )


def _session_group(generation: int, index: int) -> list[Agent]:
    """Build one fresh session graph (root, coder, monitor, extra)."""

    prefix = f"r{generation:02d}-{index:02d}"
    start = _STARTED + timedelta(minutes=generation * 100 + index)
    root = make_plan_root(name=f"{prefix}--plan")
    root.start_time = start
    root.status = "RUNNING"
    root.workspace_dir = f"/tmp/ws/{prefix}"
    coder = make_agent(
        f"{prefix}--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
        status="RUNNING",
    )
    coder.start_time = start + timedelta(seconds=1)
    coder.workspace_dir = root.workspace_dir
    coder.agent_name = f"sase-r{generation}.{index}"
    monitor = make_monitor_member(
        f"{prefix}--mon",
        root=root,
        monitor_id=f"m-{prefix}",
        monitor_state="running",
    )
    monitor.start_time = start + timedelta(seconds=2)
    extra = make_agent(
        f"{prefix}--extra",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=3,
        status="DONE",
        stop_offset=4,
    )
    extra.start_time = start + timedelta(seconds=3)
    root.runtime_children = [coder]
    root.followup_agents = [monitor, extra]
    coder.followup_agents = [monitor]
    monitor.runtime_children = []
    if index % 3 == 0:
        _attach_payloads(root, coder)
    return [root, coder, monitor, extra]


def _roster(generation: int, *, count: int = _AGENT_COUNT) -> list[Agent]:
    rows: list[Agent] = []
    index = 0
    while len(rows) < count:
        rows.extend(_session_group(generation, index))
        index += 1
    return rows[:count]


def _disk_result(agents: list[Agent], state: AgentLoadState) -> tuple[Any, None]:
    return (
        _AgentDiskLoadResult(
            all_agents=list(agents),
            dismissed_from_loader=[],
            load_state=state,
        ),
        None,
    )


def _sase_garbage(report: CycleGarbage) -> dict[str, int]:
    return {
        name: count
        for name, count in report.by_type.items()
        if name.startswith(_SASE_PREFIX) and count
    }


def _payload_counts(report: CycleGarbage) -> dict[str, int]:
    return {name: report.count(name) for name in _PAYLOAD_TYPES}


def _live_pump_tasks(app: object) -> set[asyncio.Task[Any]]:
    tasks: set[asyncio.Task[Any]] = set()
    for attr in tuple(getattr(app, "_pump_free_task_registry_attrs", ())):
        registry = getattr(app, attr, None)
        if isinstance(registry, set):
            tasks.update(task for task in registry if not task.done())
    return tasks


async def _await_pump_free(app: object, *, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tasks = _live_pump_tasks(app)
        if not tasks:
            await asyncio.sleep(0)
            if not _live_pump_tasks(app):
                return
            continue
        await asyncio.wait(tasks, timeout=0.25)
    leftover = _live_pump_tasks(app)
    assert not leftover, f"pump-free tasks still running: {leftover!r}"


def _unfinished_startup_workers(app: object) -> tuple[Any, ...]:
    """One-shot prompt-inventory workers started on owner mount."""
    workers = getattr(app, "workers", ())
    pending: list[Any] = []
    for worker in workers:
        if getattr(worker, "is_finished", True):
            continue
        group = str(getattr(worker, "group", "") or "")
        name = str(getattr(worker, "name", "") or "")
        if group.startswith("prompt-") or name.startswith("prompt-"):
            pending.append(worker)
    return tuple(pending)


async def _await_startup_workers(page: AcePage, *, timeout: float = 8.0) -> None:
    """Drain one-shot owner workers that exist before SAVEALL sampling.

    Prompt mount starts a ``prompt-finalizers`` thread worker when AceApp
    exposes no ``finalizer_inventory``. If that worker finishes inside the
    measured window, its ``FinalizerInventoryWorkerResult`` is counted as
    per-refresh garbage. Wait it out (and any other already-running one-shot
    worker) so app teardown cycles are not mistaken for producer residue.
    """
    app = page.app
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = _unfinished_startup_workers(app)
        if not pending:
            await page.pause()
            if not _unfinished_startup_workers(app):
                return
            continue
        waits = []
        for worker in pending:
            wait = getattr(worker, "wait", None)
            if callable(wait):
                waits.append(wait())
        if waits:
            await asyncio.gather(*waits, return_exceptions=True)
        await page.pause()
    leftover = _unfinished_startup_workers(app)
    names = [getattr(worker, "name", worker) for worker in leftover]
    assert not leftover, f"startup workers still running: {names!r}"


class _DummyWatcher:
    """Satisfy ``_watcher_active`` without a real inotify handle."""

    def stop(self) -> None:
        return None


def _arm_auto_refresh(app: AceApp) -> None:
    app._startup_deferred_loads_released = True
    app._fs_watcher = _DummyWatcher()
    app._prompt_input_active = lambda: False  # type: ignore[method-assign]
    app._dirty_agents = True
    app._dirty_axe = False
    app._dirty_patches = False
    app._dirty_notifications = False
    app._last_full_sanity_refresh = 0.0
    app._last_agents_load_mono = 0.0
    app._auto_refresh_scheduled = False
    app._auto_refresh_running = False
    app._auto_refresh_pending = False
    app._auto_refresh_deferred = False
    app._agents_loading = False
    app._hint_mode_active = False
    app.hide_non_run_agents = False
    app.current_tab = "agents"


async def _run_auto_refresh_tick(page: AcePage) -> None:
    app = page.app
    _arm_auto_refresh(app)
    app._on_auto_refresh()
    await _await_pump_free(app)
    await page.pause()
    await _await_pump_free(app)


def _stub_refresh_side_effects(app: AceApp, monkeypatch: pytest.MonkeyPatch) -> None:
    app._probe_surface_tokens = lambda: None  # type: ignore[method-assign]
    app._should_seed_agent_search_query = lambda: False  # type: ignore[method-assign]
    app._external_dismissal_merge_result = lambda _snapshot: None  # type: ignore[method-assign]
    app._schedule_monitor_reconcile = lambda **_kwargs: None  # type: ignore[method-assign]
    app._agent_search_query = ""

    async def _skip_notifications() -> bool:
        return False

    async def _skip_axe(**_kwargs: object) -> bool:
        return False

    async def _skip_patches(*_args: object, **_kwargs: object) -> None:
        return None

    app._poll_agent_completions = _skip_notifications  # type: ignore[method-assign]
    app._run_axe_status_refresh = _skip_axe  # type: ignore[method-assign]
    app._load_axe_status_async = _skip_axe  # type: ignore[method-assign]
    app._run_patches_async_refresh = _skip_patches  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.project_display_names.refresh_project_display_snapshot",
        lambda: False,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._loading_live_hints.classify_live_file_change_hint",
        lambda _agent: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async.compute_linked_delta_groups",
        lambda _agent: (),
    )
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: Issue(id=candidate_id, title="", description=""),
    )


@pytest.mark.asyncio
async def test_auto_refresh_merge_live_hints_and_warmup_release_obsolete_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_textual_cycle_guards()
    loads: list[tuple[list[Agent], AgentLoadState]] = []
    merged_sentinel_seen = False
    generation = 0

    def fake_disk(_snapshot: object, **_kwargs: object) -> tuple[Any, None]:
        agents, state = loads.pop(0)
        return _disk_result(agents, state)

    async with AcePage(
        query="!!!",
        size=(200, 50),
        initial_tab="agents",
    ) as page:
        app = page.app
        _stub_refresh_side_effects(app, monkeypatch)
        await _await_startup_workers(page)
        with patch(
            "sase.ace.tui.actions.agents._loading_disk_full.disk_load_with_optional_current_project",
            side_effect=fake_disk,
        ):

            async def produce() -> None:
                nonlocal generation, merged_sentinel_seen
                generation += 1
                complete = _roster(generation)
                sentinel = complete[-1]
                incomplete = complete[:-10]
                replacement = _roster(generation + 50)
                loads.extend(
                    (
                        (complete, _complete_state()),
                        (incomplete, _incomplete_state()),
                        (replacement, _complete_state()),
                    )
                )
                await _run_auto_refresh_tick(page)
                assert len(app._agents_with_children) >= _AGENT_COUNT
                assert app._agents, "auto-refresh tick did not publish visible rows"
                selected_index = min(1, len(app._agents) - 1)
                app.current_idx = selected_index
                selected_identity = app._agents[selected_index].identity
                await _run_auto_refresh_tick(page)
                merged_identities = {row.identity for row in app._agents_with_children}
                if sentinel.identity in merged_identities:
                    merged_sentinel_seen = True
                assert app._agents, "incomplete-load tick cleared the visible roster"
                assert 0 <= app.current_idx < len(app._agents)
                assert app._agents[app.current_idx].identity == selected_identity
                await _run_auto_refresh_tick(page)
                _BEAD_DISPLAY_CACHE.clear()

            await produce()
            report = await measure_cycle_garbage_async(produce, repeat=3, warmup=1)

    assert merged_sentinel_seen is True
    assert _payload_counts(report) == dict.fromkeys(_PAYLOAD_TYPES, 0)
    assert report.function_count("visit") == 0
    assert report.function_count("emit") == 0
    assert report.function_count("walk_turns") == 0
    assert _sase_garbage(report) == {}
    assert loads == []


class _WarmupTimerApp(AgentBeadWarmupMixin, App[None]):
    """Real Textual timer host for bead-warmup follow-up/apply seams."""

    def __init__(self) -> None:
        super().__init__()
        self._agents_first_load_done = True
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scan_running = False
        self._bead_warmup_scan_pending = False
        self._bead_warmup_scan_source = "unknown"
        self._bead_warmup_scheduled_candidates: _AgentBeadWarmupCandidates | None = None
        self._bead_warmup_async_tasks: set[asyncio.Task[None]] = set()
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_roster_generation = 0
        self.current_tab = "agents"
        self.current_idx = 0
        self._nav_gate = NavigationGate(window_s=0.25)
        self._patched: list[Agent] = []
        self.apply_calls = 0

    def _prompt_input_active(self) -> bool:
        return False

    def _surfaced_bead_warmup_agents(self) -> list[Agent]:
        return list(self._agents)

    def _try_patch_agent_row(self, agent: Agent, **_kwargs: object) -> bool:
        self._patched.append(agent)
        return True

    def _apply_bead_warmup_results(self, results: _AgentBeadWarmupResults) -> None:
        self.apply_calls += 1
        super()._apply_bead_warmup_results(results)

    def install_roster(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._agents_with_children = agents
        bump_roster_generation(self)
        self.current_idx = 0


def _warmup_agents(generation: int, *, count: int = 12) -> list[Agent]:
    return [
        make_agent(
            f"sase-w{generation}.{index}",
            role="code",
            start_offset=index,
            status="RUNNING",
        )
        for index in range(count)
    ]


async def _drain_warmup(
    app: _WarmupTimerApp, pilot: Any, *, delay: float = 0.05
) -> None:
    await _await_pump_free(app)
    await pilot.pause(delay)
    await _await_pump_free(app)


@pytest.mark.asyncio
async def test_bead_warmup_real_timer_followup_apply_and_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferred apply, pending follow-up, nav deferral, and failure retry."""

    worker_calls = 0
    fail_once = {"value": True}

    def warmup(candidates: _AgentBeadWarmupCandidates) -> _AgentBeadWarmupResults:
        nonlocal worker_calls
        worker_calls += 1
        if fail_once["value"] and candidates.force_stranded_projects:
            fail_once["value"] = False
            raise RuntimeError("warmup-timer-failure")
        return _AgentBeadWarmupResults(
            {agent.identity: True for agent in candidates.bead_display_agents},
            set(),
        )

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._loading_bead_warmup._warm_agent_bead_caches",
        warmup,
    )
    app = _WarmupTimerApp()
    async with app.run_test() as pilot:
        agents = _warmup_agents(1)
        app.install_roster(agents)

        app._nav_gate.record()
        app._schedule_bead_confirmation_warmup(source="apply")
        assert app._bead_warmup_scan_scheduled is True
        await _drain_warmup(app, pilot, delay=0.35)
        assert worker_calls >= 1
        assert app.apply_calls >= 1

        worker_calls_after_nav = worker_calls
        app.install_roster(_warmup_agents(2))
        app._bead_warmup_scan_pending = True
        app._bead_warmup_scan_scheduled = True
        app._bead_warmup_scheduled_candidates = _AgentBeadWarmupCandidates(
            bead_display_agents=tuple(app._agents),
            roster_generation=0,
        )
        await app._run_bead_confirmation_warmup()
        await _drain_warmup(app, pilot, delay=0.1)
        assert worker_calls > worker_calls_after_nav

        started = threading.Event()
        release = threading.Event()

        def blocked(
            candidates: _AgentBeadWarmupCandidates,
        ) -> _AgentBeadWarmupResults:
            started.set()
            release.wait(timeout=2.0)
            return _AgentBeadWarmupResults(
                {agent.identity: True for agent in candidates.bead_display_agents},
                set(),
            )

        monkeypatch.setattr(
            "sase.ace.tui.actions.agents._loading_bead_warmup._warm_agent_bead_caches",
            blocked,
        )
        apply_before = app.apply_calls
        app.install_roster(_warmup_agents(3))
        app._schedule_bead_confirmation_warmup(source="apply")
        assert await asyncio.to_thread(started.wait, 1.0) is True
        app._nav_gate.record()
        release.set()
        await _drain_warmup(app, pilot, delay=0.35)
        assert app.apply_calls > apply_before

        monkeypatch.setattr(
            "sase.ace.tui.actions.agents._loading_bead_warmup._warm_agent_bead_caches",
            warmup,
        )
        fail_calls = worker_calls
        app._bead_warmup_forced_projects = {"proj"}
        app._bead_warmup_forced_immediate_projects = {"proj"}
        app._bead_warmup_scan_scheduled = True
        app._bead_warmup_scheduled_candidates = _AgentBeadWarmupCandidates(
            force_stranded_projects=("proj",),
            force_stranded_immediate=True,
            roster_generation=app._agents_roster_generation,
        )
        await app._run_bead_confirmation_warmup()
        await _drain_warmup(app, pilot, delay=1.1)
        assert worker_calls > fail_calls
        assert app._bead_warmup_scan_running is False


@pytest.mark.asyncio
async def test_bead_warmup_timer_apply_releases_obsolete_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: Issue(id=candidate_id, title="", description=""),
    )
    app = _WarmupTimerApp()
    generation = 0
    async with app.run_test() as pilot:

        async def produce() -> None:
            nonlocal generation
            generation += 1
            _BEAD_DISPLAY_CACHE.clear()
            app.install_roster(_warmup_agents(generation))
            app._schedule_bead_confirmation_warmup(source="apply")
            await _drain_warmup(app, pilot, delay=0.1)

        await produce()
        report = await measure_cycle_garbage_async(produce, repeat=3, warmup=1)

    assert report.count(AGENT_TYPE) == 0
    assert report.function_count("visit") == 0
    assert _sase_garbage(report) == {}
