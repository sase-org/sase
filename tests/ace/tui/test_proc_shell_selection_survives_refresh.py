"""Agents-tab proc-shell selection restoration across loader refreshes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui._proc_observer_models import (
    ObservedProc,
    ProcProjection,
    compose_proc_projection,
)
from sase.ace.tui.actions._proc_action_completion import ProcCompletionActionsMixin
from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    compute_apply_loaded_agents,
)
from sase.ace.tui.models._agent_loader_artifacts import AgentLoadState
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_proc_shells import proc_shell_agents_from_observed
from sase.procs import PROC_LIFECYCLE_PROC_SHELL, XPROMPT_PROC_ORIGIN

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


_NOW = datetime(2026, 8, 23, 12, 0, 0)


class ProcShellFakeApp(ProcCompletionActionsMixin, FakeAgentApp):
    """Headless app with the production proc-shell roster reconcile."""

    def __init__(self) -> None:
        super().__init__()
        self._proc_projection = ProcProjection()
        self._dismissed_proc_shells: set[str] = set()
        self._session_completion_callbacks: dict[
            str, tuple[Callable[..., Any], Any]
        ] = {}
        self._proc_completion_callbacks: dict[str, Any] = {}

    def _session_overlay_rows(self) -> tuple[ObservedProc, ...]:
        rows: list[ObservedProc] = []
        for recorded in self._session_completion_callbacks.values():
            if not isinstance(recorded, tuple) or len(recorded) != 2:
                continue
            _callback, row = recorded
            if isinstance(row, ObservedProc):
                rows.append(row)
        return tuple(rows)

    def _effective_proc_projection(self) -> ProcProjection:
        return compose_proc_projection(
            self._proc_projection,
            self._session_overlay_rows(),
        )

    def _update_proc_indicator(self) -> None:
        pass

    def _invalidate_agent_panel_cache(self) -> None:
        pass


def _tier1_index_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=True,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )


def _observed_proc(
    proc_id: str = "0123456789abcdef",
    *,
    project: str = "sase",
    status: str = "running",
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type="proc",
        cl_name=project,
        project_file=f"/tmp/projects/{project}/{project}.sase",
        status=status,
        message=status,
        started_at=_NOW,
        display_name="background job",
        command=["python", "-m", "sase", "demo"],
        origin=XPROMPT_PROC_ORIGIN,
        lifecycle=PROC_LIFECYCLE_PROC_SHELL,
        project=project,
        shell_name="background-job",
    )


def _seed_roster_with_proc_shell(
    app: ProcShellFakeApp,
    disk_agents: list[Agent],
    row: ObservedProc,
) -> Agent:
    app._agents = list(disk_agents)
    app._agents_with_children = list(disk_agents)
    app._proc_projection = ProcProjection(rows=(row,), active_count=1)
    app._sync_proc_shell_agents_from_projection()
    proc_shell = next(agent for agent in app._agents if agent.is_proc_shell)
    return proc_shell


def _apply_disk_refresh(
    app: ProcShellFakeApp,
    disk_agents: list[Agent],
    *,
    on_agents_tab: bool,
    selected_identity: tuple[AgentType, str, str | None] | None,
) -> None:
    prep = compute_apply_loaded_agents(
        all_agents=list(disk_agents),
        dismissed_from_loader=[],
        dismissed_snapshot=set(),
        hide_non_run_agents=False,
    )
    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=on_agents_tab,
        selected_identity=selected_identity,
        load_state=_tier1_index_state(),
        persist_dismissed_changes=False,
    )


def test_focused_proc_shell_keeps_selection_across_loader_apply() -> None:
    alpha = _make_agent(cl_name="alpha", raw_suffix="alpha")
    beta = _make_agent(cl_name="beta", raw_suffix="beta")
    app = ProcShellFakeApp()
    proc_shell = _seed_roster_with_proc_shell(app, [alpha, beta], _observed_proc())
    proc_identity = proc_shell.identity
    app.current_tab = "agents"
    app.current_idx = app._agents.index(proc_shell)

    _apply_disk_refresh(
        app,
        [alpha, beta],
        on_agents_tab=True,
        selected_identity=proc_identity,
    )

    assert app._agents[app.current_idx].identity == proc_identity


def test_loader_apply_keeps_proc_shell_rows_in_roster_before_finalize() -> None:
    alpha = _make_agent(cl_name="alpha", raw_suffix="alpha")
    beta = _make_agent(cl_name="beta", raw_suffix="beta")
    app = ProcShellFakeApp()
    proc_shell = _seed_roster_with_proc_shell(app, [alpha, beta], _observed_proc())
    proc_identity = proc_shell.identity
    app.current_tab = "agents"
    app.current_idx = app._agents.index(proc_shell)
    rosters_at_finalize: list[
        tuple[
            list[tuple[AgentType, str, str | None]],
            list[tuple[AgentType, str, str | None]],
        ]
    ] = []
    original_finalize = app._finalize_agent_list

    def _recording_finalize(*args: Any, **kwargs: Any) -> None:
        rosters_at_finalize.append(
            (
                [agent.identity for agent in app._agents_with_children],
                [agent.identity for agent in app._agents],
            )
        )
        original_finalize(*args, **kwargs)

    app._finalize_agent_list = _recording_finalize  # type: ignore[method-assign]

    _apply_disk_refresh(
        app,
        [alpha, beta],
        on_agents_tab=True,
        selected_identity=proc_identity,
    )

    assert proc_identity in rosters_at_finalize[0][0]
    assert proc_identity in rosters_at_finalize[0][1]


def test_unchanged_proc_projection_runs_one_finalize_pass() -> None:
    alpha = _make_agent(cl_name="alpha", raw_suffix="alpha")
    beta = _make_agent(cl_name="beta", raw_suffix="beta")
    app = ProcShellFakeApp()
    proc_shell = _seed_roster_with_proc_shell(app, [alpha, beta], _observed_proc())
    app.current_tab = "agents"
    app.current_idx = app._agents.index(proc_shell)
    calls = 0
    original_finalize = app._finalize_agent_list

    def _counting_finalize(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        original_finalize(*args, **kwargs)

    app._finalize_agent_list = _counting_finalize  # type: ignore[method-assign]

    _apply_disk_refresh(
        app,
        [alpha, beta],
        on_agents_tab=True,
        selected_identity=proc_shell.identity,
    )

    assert calls == 1


def test_off_tab_refresh_preserves_saved_proc_shell_selection() -> None:
    alpha = _make_agent(cl_name="alpha", raw_suffix="alpha")
    beta = _make_agent(cl_name="beta", raw_suffix="beta")
    app = ProcShellFakeApp()
    proc_shell = _seed_roster_with_proc_shell(app, [alpha, beta], _observed_proc())
    proc_identity = proc_shell.identity
    app.current_tab = "patches"
    app._agents_last_idx = app._agents.index(proc_shell)
    app._agents_last_identity = proc_identity

    _apply_disk_refresh(
        app,
        [alpha, beta],
        on_agents_tab=False,
        selected_identity=proc_identity,
    )

    assert app._agents_last_identity == proc_identity
    assert app._agents[app._agents_last_idx].identity == proc_identity


def test_settled_proc_removed_from_projection_leaves_roster() -> None:
    alpha = _make_agent(cl_name="alpha", raw_suffix="alpha")
    beta = _make_agent(cl_name="beta", raw_suffix="beta")
    app = ProcShellFakeApp()
    proc_shell = _seed_roster_with_proc_shell(app, [alpha, beta], _observed_proc())
    app.current_tab = "agents"
    app.current_idx = app._agents.index(proc_shell)
    app._proc_projection = ProcProjection()

    _apply_disk_refresh(
        app,
        [alpha, beta],
        on_agents_tab=True,
        selected_identity=proc_shell.identity,
    )

    assert all(not agent.is_proc_shell for agent in app._agents)
    assert all(not agent.is_proc_shell for agent in app._agents_with_children)


def test_observed_proc_identity_is_stable_when_durable_row_replaces_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_proc_shells.project_display_name_for",
        lambda project: project,
    )
    overlay = _observed_proc(proc_id="proc-stable", project="gh_sase-org__sase")
    durable = replace(
        overlay,
        status="running",
        store_backed=True,
        durable_proc_id=overlay.proc_id,
    )
    overlay_identity = proc_shell_agents_from_observed([overlay])[0].identity

    projection = compose_proc_projection(
        ProcProjection(rows=(durable,)),
        session_rows=(overlay,),
    )

    assert projection.rows == (durable,)
    assert (
        proc_shell_agents_from_observed(projection.rows)[0].identity == overlay_identity
    )


def test_dismissed_terminal_proc_shell_does_not_return_on_projection_sync() -> None:
    from sase.ace.tui.actions.agents._proc_shell_dismiss import ProcShellDismissMixin

    class _App(ProcShellDismissMixin, ProcShellFakeApp):
        pass

    alpha = _make_agent(cl_name="alpha", raw_suffix="alpha")
    beta = _make_agent(cl_name="beta", raw_suffix="beta")
    app = _App()
    row = _observed_proc(status="success")
    proc_shell = _seed_roster_with_proc_shell(app, [alpha, beta], row)
    proc_identity = proc_shell.identity
    finalize_calls = 0
    original_finalize = app._finalize_agent_list

    def _counting_finalize(*args: Any, **kwargs: Any) -> None:
        nonlocal finalize_calls
        finalize_calls += 1
        original_finalize(*args, **kwargs)

    app._finalize_agent_list = _counting_finalize  # type: ignore[method-assign]
    app._dismiss_proc_shell_rows([proc_shell])
    finalize_calls = 0
    app._sync_proc_shell_agents_from_projection()

    assert finalize_calls == 0
    assert all(agent.identity != proc_identity for agent in app._agents)
    assert all(agent.identity != proc_identity for agent in app._agents_with_children)
    assert proc_shell.proc_id in app._dismissed_proc_shells

    _apply_disk_refresh(
        app,
        [alpha, beta],
        on_agents_tab=True,
        selected_identity=alpha.identity,
    )

    assert all(agent.identity != proc_identity for agent in app._agents)
    assert all(agent.identity != proc_identity for agent in app._agents_with_children)
