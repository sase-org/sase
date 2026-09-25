"""Mounted Agents-tab harness for end-to-end ``x`` kill/dismiss regressions.

The component tests for ``x`` each cover one boundary: a fake app for the
tombstone filters, a real process tree for termination, a fake Agents mixin for
the modal flow. This harness joins them. It mounts the real ``AceApp`` on the
Agents tab, loads agents from on-disk artifacts through the real loader, and
gives each agent a real fixture process tree (``_agent_process_tree_helpers``).

Three seams are deliberately controllable, and everything else is production
code:

* :class:`DurableCleanupRecorder` intercepts only the durable submit boundary of
  ``sase agent persist-cleanup``. The TUI builds and submits the real payload;
  the test decides when it runs. It then executes on a worker thread through
  ``apply_cleanup_payload_for_result`` (the function the CLI runs) and hands the
  completion back to the app on the UI thread, so the real tombstone, refresh,
  and row-publication code still sees a normal completion.
* :class:`LoadGate` parks one agents load after its worker prep and before its
  apply, which is the window where a load holds a roster prepared before ``x``.
* :func:`reload_agents` and :func:`refresh_fleet` drive the app's real load and
  fleet-refresh schedulers (including a forced complete-history load) and wait
  for their observable end.

Fixture agents are home-mode ``ace-run`` agents: a ``running.json`` marker whose
pid is a live fixture runner. The real loader turns them into live RUNNING rows
(``runner_is_live``), and the fixture runner ignores SIGTERM by default so it
outlives the TUI's immediate signal exactly as a real runner with a soft
handler does, until the durable stage escalates.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.process_tree import process_is_running
from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.paths import sase_projects_dir
from sase.core.process_identity import process_identity_token
from sase.ops.commands._agent_cleanup import apply_cleanup_payload_for_result
from sase.ops.names import AGENT_CLEANUP

from tests._agent_process_tree_helpers import launch_runner, wait_until_gone
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT

AgentIdentity = tuple[AgentType, str, str | None]

# The durable stage's grace before SIGKILL. The production default (6s) outlasts
# the ``sase tool run`` wrapper's own escalation; a real fixture process tree
# only needs enough time to prove the SIGTERM-ignoring processes get escalated.
TEST_TERMINATION_GRACE_SECONDS = 1.0

HOME_PROJECT = "home"
HOME_CL_NAME = "~"


@dataclass
class FixtureAgent:
    """One on-disk agent whose runner is a real fixture process tree."""

    name: str
    timestamp: str
    artifacts_dir: Path
    runner: subprocess.Popen[bytes]
    pids: dict[str, int]

    @property
    def identity(self) -> AgentIdentity:
        return (AgentType.RUNNING, HOME_CL_NAME, self.timestamp)

    @property
    def runner_pid(self) -> int:
        return self.runner.pid

    def alive(self) -> dict[str, int]:
        """Return the fixture processes (runner and children) still running."""
        return {name: pid for name, pid in self.pids.items() if process_is_running(pid)}


def write_home_agent_artifacts(
    *,
    name: str,
    timestamp: str,
    pid: int,
    scratch_key: str,
    clan: str | None = None,
    clan_generation: str | None = None,
) -> Path:
    """Write the on-disk artifacts of a live home-mode ``ace-run`` agent."""
    projects = sase_projects_dir()
    home = projects / HOME_PROJECT
    home.mkdir(parents=True, exist_ok=True)
    (home / f"{HOME_PROJECT}.sase").touch()
    artifacts_dir = canonical_agent_artifact_path(
        HOME_PROJECT, "ace-run", timestamp, projects_root=projects
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "running.json").write_text(
        json.dumps({"pid": pid, "cl_name": HOME_CL_NAME}), encoding="utf-8"
    )
    meta: dict[str, object] = {
        "name": name,
        "pid": pid,
        "process_identity": process_identity_token(pid),
        "launch_scratch_key": scratch_key,
    }
    if clan is not None:
        meta["agent_clan"] = clan
        meta["agent_clan_generation"] = clan_generation
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return artifacts_dir


@dataclass
class PendingCleanup:
    """A ``sase agent persist-cleanup`` submission the TUI made and the test holds."""

    request: dict[str, Any]
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None
    on_settled: Callable[[], None] | None


@dataclass
class CleanupOutcome:
    success: bool
    message: str
    payload: dict[str, Any]


@dataclass
class DurableCleanupRecorder:
    """Hold durable cleanup submissions, then run each one out of the event loop."""

    pending: list[PendingCleanup] = field(default_factory=list)
    outcomes: list[CleanupOutcome] = field(default_factory=list)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original: Any = AceApp._submit_durable_proc
        recorder = self

        def submit_durable_proc(
            app: AceApp,
            argv: Any,
            *,
            operation: str = "",
            request: Any = None,
            on_complete: Any = None,
            on_settled: Any = None,
            **kwargs: Any,
        ) -> Any:
            if operation != AGENT_CLEANUP:
                return original(
                    app,
                    argv,
                    operation=operation,
                    request=request,
                    on_complete=on_complete,
                    on_settled=on_settled,
                    **kwargs,
                )
            recorder.pending.append(
                PendingCleanup(dict(request or {}), on_complete, on_settled)
            )
            # A real submission registers a proc, and the proc observer's next
            # snapshot replaces the projection (bumping its generation) while
            # any in-flight load is still waiting to apply. Reproduce that move
            # deterministically instead of leaving it to observer timing.
            app._replace_proc_projection(app._proc_projection)
            return object()

        monkeypatch.setattr(
            AceApp, "_submit_durable_proc", submit_durable_proc, raising=False
        )

    async def run_pending(self) -> list[CleanupOutcome]:
        """Run every held payload through the CLI's apply function, in order.

        The payload takes the same JSON round trip as the real request sidecar,
        and the process termination, disk writes, and index updates run on a
        worker thread. The completion and settle callbacks then run here, on the
        app's loop, exactly as the tracked-proc adapter delivers them.
        """
        ran: list[CleanupOutcome] = []
        while self.pending:
            job = self.pending.pop(0)
            request = json.loads(json.dumps(job.request))
            success, message, payload = await asyncio.to_thread(
                apply_cleanup_payload_for_result, request
            )
            outcome = CleanupOutcome(success, message, dict(payload))
            ran.append(outcome)
            self.outcomes.append(outcome)
            try:
                if job.on_complete is not None:
                    job.on_complete(
                        TrackedProcCompletion(
                            proc_info=None,  # type: ignore[arg-type]
                            success=success,
                            message=message,
                            output="",
                            payload=dict(payload),
                            error=None if success else message,
                        )
                    )
            finally:
                if job.on_settled is not None:
                    job.on_settled()
        return ran


class LoadGate:
    """Park one agents load after its worker prep and before its apply.

    ``prepared_identities`` records the roster the parked load prepared, so a
    test can prove the load really held the rows it must not resurrect.
    """

    def __init__(self) -> None:
        self._entered: asyncio.Event | None = None
        self._release: asyncio.Event | None = None
        self._armed = False
        self.prepared_identities: set[AgentIdentity] = set()

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original: Any = AceApp._prepare_agent_content_search_index_async
        gate = self

        async def gated(app: AceApp, agents: Any, *args: Any, **kwargs: Any) -> Any:
            result = await original(app, agents, *args, **kwargs)
            if gate._armed:
                assert gate._entered is not None and gate._release is not None
                gate._armed = False
                gate.prepared_identities = {agent.identity for agent in agents}
                gate._entered.set()
                await gate._release.wait()
            return result

        monkeypatch.setattr(AceApp, "_prepare_agent_content_search_index_async", gated)

    def arm(self) -> None:
        """Hold the next load that reaches its apply seam."""
        self._entered = asyncio.Event()
        self._release = asyncio.Event()
        self._armed = True

    @property
    def is_holding(self) -> bool:
        return self._entered is not None and self._entered.is_set()

    def release(self) -> None:
        assert self._release is not None, "arm() the gate before releasing it"
        self._release.set()


@dataclass
class XEnv:
    """Fixture bundle for one mounted-Agents-tab ``x`` scenario."""

    tmp_path: Path
    reap_pids: list[int]
    cleanup: DurableCleanupRecorder
    gate: LoadGate
    agents: list[FixtureAgent] = field(default_factory=list)

    def launch_agent(
        self,
        name: str,
        timestamp: str,
        *,
        clan: str | None = None,
        clan_generation: str | None = None,
        runner_ignores_term: bool = True,
    ) -> FixtureAgent:
        """Start a real process tree and write the on-disk agent that owns it."""
        scratch_key = f"xe2e-{uuid.uuid4().hex}"
        workdir = self.tmp_path / f"runner-{name}"
        workdir.mkdir()
        runner, pids = launch_runner(
            workdir,
            scratch_key,
            self.reap_pids,
            runner_ignores_term=runner_ignores_term,
        )
        artifacts_dir = write_home_agent_artifacts(
            name=name,
            timestamp=timestamp,
            pid=runner.pid,
            scratch_key=scratch_key,
            clan=clan,
            clan_generation=clan_generation,
        )
        agent = FixtureAgent(name, timestamp, artifacts_dir, runner, pids)
        self.agents.append(agent)
        return agent

    def open_page(self) -> AcePage:
        """Return an un-entered ``AcePage`` on the Agents tab."""
        return AcePage(initial_tab="agents")


@pytest.fixture
def x_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[XEnv]:
    """Install the durable-cleanup recorder, load gate, and short kill grace.

    Owns the fixture pids too: whatever a scenario leaves alive, a failing one
    included, is SIGKILLed and reaped at teardown.
    """
    from sase.agent import user_kill

    # The suite-wide guard already confines signalling to the test's children;
    # this wraps it so the durable stage escalates after a short grace.
    confined = user_kill.terminate_agent_processes

    def short_grace(pid: int, **kwargs: Any) -> Any:
        kwargs.setdefault("grace_seconds", TEST_TERMINATION_GRACE_SECONDS)
        return confined(pid, **kwargs)

    monkeypatch.setattr(user_kill, "terminate_agent_processes", short_grace)

    recorder = DurableCleanupRecorder()
    recorder.install(monkeypatch)
    gate = LoadGate()
    gate.install(monkeypatch)
    env = XEnv(tmp_path, [], recorder, gate)
    yield env
    for pid in env.reap_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    for agent in env.agents:
        agent.runner.wait(timeout=10)


def rosters(app: AceApp) -> dict[str, list[Agent]]:
    """Return every roster a row can be published from, by name.

    ``_agents_local_with_children`` is the base a fleet reprojection rebuilds
    ``_agents`` from, so a removed row surviving there comes back on the next
    refresh even while the visible list looks clean.
    """
    return {
        "visible": list(app._agents),
        "with_children": list(app._agents_with_children),
        "local_with_children": list(app._agents_local_with_children),
    }


def roster_identities(app: AceApp) -> dict[str, set[AgentIdentity]]:
    return {
        name: {agent.identity for agent in agents}
        for name, agents in rosters(app).items()
    }


def assert_rows_absent(
    app: AceApp, identities: set[AgentIdentity], *, stage: str
) -> None:
    """Assert none of *identities* is published by any roster."""
    leaked = {
        roster: present & identities
        for roster, present in roster_identities(app).items()
        if present & identities
    }
    assert leaked == {}, f"removed rows resurfaced after {stage}: {leaked}"


def assert_clan_absent(app: AceApp, clan: str, *, stage: str) -> None:
    """Assert no clan container (or member) of *clan* survives in any roster."""
    leaked = {
        roster: [a.identity for a in agents if a.agent_clan == clan]
        for roster, agents in rosters(app).items()
        if any(a.agent_clan == clan for a in agents)
    }
    assert leaked == {}, f"clan {clan!r} resurfaced after {stage}: {leaked}"


@dataclass
class ScheduledLoad:
    """A real scheduled agents load and the observable end of its apply.

    ``rosters_at_apply`` is captured by the load's own completion callback,
    which runs right after the apply and before any follow-up work the apply
    scheduled (a fleet refresh, say) can run. A row published there was on
    screen even if a later refresh took it away again.
    """

    page: AcePage
    applied: bool = False
    rosters_at_apply: dict[str, set[AgentIdentity]] = field(default_factory=dict)

    async def wait_applied(self) -> None:
        app = self.page.app
        await self.page.wait_for(
            lambda _state: self.applied and not app._agents_loading,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )

    def assert_absent_at_apply(self, identities: set[AgentIdentity]) -> None:
        """Assert the apply itself never published any of *identities*."""
        assert self.applied, "the load has not applied yet"
        leaked = {
            roster: present & identities
            for roster, present in self.rosters_at_apply.items()
            if present & identities
        }
        assert leaked == {}, f"the load's apply published removed rows: {leaked}"


def schedule_agents_load(
    page: AcePage,
    *,
    full_history: bool = False,
    source: str = "x_e2e_load",
) -> ScheduledLoad:
    """Schedule one real agents load through the app's refresh coalescer."""
    load = ScheduledLoad(page)

    def on_applied() -> None:
        load.rosters_at_apply = roster_identities(page.app)
        load.applied = True

    page.app._schedule_agents_async_refresh(
        source=source,
        full_history=full_history,
        full_history_reason="x_e2e_forced_complete_history" if full_history else None,
        on_complete=on_applied,
    )
    return load


async def reload_agents(
    page: AcePage,
    *,
    full_history: bool = False,
    source: str = "x_e2e_reload",
) -> None:
    """Run one real scheduled agents load and wait for it to apply."""
    await schedule_agents_load(
        page, full_history=full_history, source=source
    ).wait_applied()


async def refresh_fleet(page: AcePage, *, source: str = "fleet_refresh") -> None:
    """Run one real fleet refresh, which reprojects ``_agents`` from local rows.

    With no federation configured it still ends in the same
    ``_reproject_agents_from_current_mode`` a remote refresh reaches. The sources
    ``remote_attention`` and ``remote_mutation`` force a full rebuild instead of
    the unchanged-signature shortcut.
    """
    app = page.app
    app._schedule_agents_fleet_refresh(source=source, force=True)
    await page.wait_for(
        lambda _state: not app._agents_fleet_loading,
        timeout=LOAD_TOLERANT_TIMEOUT,
    )


async def disk_rows(*, full_history: bool = True) -> set[AgentIdentity]:
    """Return the identities the real loader builds from disk with no dismissals.

    Proves a scenario has teeth: the rows the UI must keep hidden really are
    still on disk (and their runners really are alive), so only the session
    tombstone or the durable dismissal, not an empty disk, hides them.
    """
    from sase.ace.tui.actions.agents._loading_helpers import (
        load_agents_from_disk_with_state,
    )

    result = await asyncio.to_thread(
        load_agents_from_disk_with_state, set(), full_history=full_history
    )
    return {agent.identity for agent in result.all_agents}


async def wait_for_processes_dead(
    *pids: int, timeout: float = LOAD_TOLERANT_TIMEOUT
) -> None:
    """Wait for the kernel to report every pid dead, off the event loop."""
    await asyncio.to_thread(wait_until_gone, *pids, timeout=timeout)


__all__ = [
    "HOME_CL_NAME",
    "TEST_TERMINATION_GRACE_SECONDS",
    "AgentIdentity",
    "CleanupOutcome",
    "DurableCleanupRecorder",
    "FixtureAgent",
    "LoadGate",
    "PendingCleanup",
    "ScheduledLoad",
    "XEnv",
    "assert_clan_absent",
    "assert_rows_absent",
    "disk_rows",
    "refresh_fleet",
    "reload_agents",
    "roster_identities",
    "rosters",
    "schedule_agents_load",
    "wait_for_processes_dead",
    "write_home_agent_artifacts",
    "x_env",
]
