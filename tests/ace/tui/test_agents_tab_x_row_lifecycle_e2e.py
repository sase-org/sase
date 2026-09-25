"""End-to-end ``x`` on live single rows: backoff kill, DONE dismiss, exit, restart.

Drives the mounted Agents tab through the same harness as the clan-race
module (on-disk fixture agents with real process trees, the real ``x`` and
confirmation flow, the real tombstone and row-publication path, and the
durable cleanup payload run through ``apply_cleanup_payload_for_result``).
Where the clan module races loads against a clan kill, this module covers
the remaining acceptance cases from ``plan:202609/x_kill_removal_reliability``:

* a live retry-backoff (RETRYING) runner offers kill confirmation, disappears,
  has its complete process tree terminated, and stays hidden after refresh;
* a live FAILED row is dismissed with its same-identity live twin, whose
  process tree the durable safety net terminates;
* a live DONE finalizing runner is dismissed and stays hidden without
  receiving a signal;
* pressing ``x`` on a running agent and immediately exiting the app still
  leaves a durable payload that verifies every fixture process dead;
* a fresh app instance against the same on-disk state shows none of the
  removed rows.
"""

from __future__ import annotations

import asyncio
import json

from sase.ace.dismissed_agents import load_dismissed_agents
from sase.ace.tui import AceApp
from sase.core.agent_artifact_index_lifecycle import default_agent_artifact_index_path
from sase.core.agent_artifact_index_lifecycle_common import (
    default_agent_artifact_projects_root,
)
from sase.core.agent_scan_facade import rebuild_agent_artifact_index
from sase.ops.commands._agent_cleanup import apply_cleanup_payload_for_result
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests.ace.tui._agents_x_pilot_helpers import (
    AgentIdentity,
    FixtureAgent,
    XEnv,
    assert_rows_absent,
    disk_rows,
    refresh_fleet,
    reload_agents,
    wait_for_processes_dead,
    x_env as x_env,
)


def _write_done(agent: FixtureAgent, outcome: str) -> None:
    agent.artifacts_dir.joinpath("done.json").write_text(
        json.dumps({"outcome": outcome, "cl_name": "~"}), encoding="utf-8"
    )


def _mark_running(agent: FixtureAgent) -> None:
    """Record an execution-loop start so the row renders as RUNNING.

    Home-mode rows load as STARTING until ``agent_meta.json`` carries
    ``run_started_at``. STARTING rows are never rendered on the Agents tab,
    so a fixture the pilot must select needs the promotion a real runner
    records when its execution loop starts.
    """
    from datetime import UTC, datetime

    meta_path = agent.artifacts_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.setdefault(
        "run_started_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _write_retry_backoff(agent: FixtureAgent) -> None:
    agent.artifacts_dir.joinpath("retry_state.json").write_text(
        json.dumps(
            {
                "status": "retrying",
                "retry_count": 1,
                "max_retries": 3,
                "next_retry_at_epoch": 9999999999.0,
                "wait_seconds": 60,
                "fallback_model": None,
                "using_fallback": False,
                "last_error_snippet": "provider timeout",
            }
        ),
        encoding="utf-8",
    )


async def _select_row(page, app: AceApp, *, status: str, suffix: str) -> None:
    """Focus the first visible row matching *status* and *suffix*.

    Selection reads the panel-rendered roster, which can lag the raw agent
    list, so keep asserting the focused identity until ``x`` would act on it.
    """
    await page.wait_for(
        lambda _state: any(
            a.status == status and a.raw_suffix == suffix for a in app._agents
        ),
        timeout=LOAD_TOLERANT_TIMEOUT,
    )
    wanted = (status, suffix)

    def focused(_state: object) -> bool:
        for index, agent in enumerate(app._agents):
            if (agent.status, agent.raw_suffix or "") == wanted:
                app.current_idx = index
        selected = app._get_selected_agent()
        return (
            selected is not None
            and (selected.status, selected.raw_suffix or "") == wanted
        )

    await page.wait_for(focused, timeout=LOAD_TOLERANT_TIMEOUT)
    selected = app._get_selected_agent()
    assert selected is not None
    assert (selected.status, selected.raw_suffix or "") == wanted


async def _ensure_artifact_index() -> None:
    """Build the SQLite artifact index production maintains at startup.

    The durable dismiss transaction fails closed when the index file is
    absent. The pilot's fast startup skips index maintenance, so build it
    from the fixture tree explicitly, off the event loop.
    """
    await asyncio.to_thread(
        rebuild_agent_artifact_index,
        default_agent_artifact_index_path(),
        default_agent_artifact_projects_root(),
    )


async def _wait_row_absent(
    page, app: AceApp, identities: set[AgentIdentity], *, stage: str
) -> None:
    """Wait until no roster publishes *identities*, then assert it holds."""

    def absent(_state: object) -> bool:
        try:
            assert_rows_absent(app, identities, stage=stage)
        except AssertionError:
            return False
        return True

    await page.wait_for(absent, timeout=LOAD_TOLERANT_TIMEOUT)
    assert_rows_absent(app, identities, stage=stage)


async def test_retry_backoff_row_offers_kill_and_tree_dies_and_stays_hidden(
    x_env: XEnv,
) -> None:
    agent = x_env.launch_agent("row.retry", "20260924141001", runner_ignores_term=True)
    _write_retry_backoff(agent)
    identity = agent.identity

    async with x_env.open_page() as page:
        app = page.app
        await reload_agents(page)
        await page.wait_for(
            lambda _state: (
                identity in {a.identity for a in app._agents}
                and any(
                    a.identity == identity and a.runner_is_live and a.pid is not None
                    for a in app._agents
                )
            ),
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        row = next(a for a in app._agents if a.identity == identity)
        assert row.status == "RETRYING"
        assert row.pid == agent.runner_pid

        # The row is still on disk with a live runner, so only the session
        # tombstone (not a dead pid) can keep it hidden after the kill.
        assert identity in await disk_rows(full_history=True)

        await _select_row(page, app, status="RETRYING", suffix=agent.timestamp)
        await page.press("x")
        await page.expect_modal("ConfirmKillModal")
        await page.press("y")
        await page.expect_no_modal()

        # The TUI stage signalled the runner's group: the plain same-group
        # child is dead while the SIGTERM-ignoring runner survives it.
        await wait_for_processes_dead(agent.pids["same_group"])
        assert agent.runner.poll() is None
        assert len(x_env.cleanup.pending) == 1
        assert "kill" in x_env.cleanup.pending[0].request["transaction"]
        await _wait_row_absent(page, app, {identity}, stage="x confirmation")

        (outcome,) = await x_env.cleanup.run_pending()
        assert outcome.success, outcome.message
        await wait_for_processes_dead(*agent.pids.values())
        assert agent.alive() == {}
        assert identity in await asyncio.to_thread(load_dismissed_agents)

        await refresh_fleet(page, source="remote_attention")
        await _wait_row_absent(
            page, app, {identity}, stage="a forced fleet reprojection"
        )
        await reload_agents(page, full_history=True, source="x_e2e_history_after_kill")
        await _wait_row_absent(page, app, {identity}, stage="a complete-history reload")


async def test_failed_row_dismiss_terminates_live_runner_and_stays_hidden(
    x_env: XEnv,
) -> None:
    agent = x_env.launch_agent("row.failed", "20260924142001", runner_ignores_term=True)
    _write_done(agent, "failed")
    identity = agent.identity
    await _ensure_artifact_index()

    async with x_env.open_page() as page:
        app = page.app
        await reload_agents(page)
        await page.wait_for(
            lambda _state: (
                {a.status for a in app._agents if a.identity == identity}
                == {"FAILED", "STARTING"}
            ),
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        # Both same-identity twins are really on disk with a live runner.
        assert identity in await disk_rows(full_history=True)
        assert agent.runner.poll() is None

        # The pid-less FAILED row dismisses without a kill modal, and the
        # same-identity live twin goes with it.
        await _select_row(page, app, status="FAILED", suffix=agent.timestamp)
        await page.press("x")
        await page.expect_no_modal()
        await _wait_row_absent(page, app, {identity}, stage="x dismissal")

        # The TUI stage sends no signal: the runner is still alive, so only
        # the durable safety net can terminate the retry-backoff tree.
        assert agent.runner.poll() is None
        assert len(x_env.cleanup.pending) == 1
        assert "kill" not in x_env.cleanup.pending[0].request["transaction"]

        (outcome,) = await x_env.cleanup.run_pending()
        assert outcome.success, outcome.message
        await wait_for_processes_dead(*agent.pids.values())
        assert agent.alive() == {}
        assert identity in await asyncio.to_thread(load_dismissed_agents)

        await refresh_fleet(page, source="remote_attention")
        await _wait_row_absent(
            page, app, {identity}, stage="a forced fleet reprojection"
        )
        await reload_agents(page, full_history=True, source="x_e2e_history_after_kill")
        await _wait_row_absent(page, app, {identity}, stage="a complete-history reload")


async def test_done_row_dismissed_without_signal_and_stays_hidden(
    x_env: XEnv,
) -> None:
    agent = x_env.launch_agent("row.done", "20260924143001", runner_ignores_term=False)
    _write_done(agent, "completed")
    identity = agent.identity
    await _ensure_artifact_index()

    async with x_env.open_page() as page:
        app = page.app
        await reload_agents(page)
        await page.wait_for(
            lambda _state: (
                {a.status for a in app._agents if a.identity == identity}
                == {"DONE", "STARTING"}
            ),
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        assert identity in await disk_rows(full_history=True)

        await _select_row(page, app, status="DONE", suffix=agent.timestamp)
        await page.press("x")
        await page.expect_no_modal()
        await _wait_row_absent(page, app, {identity}, stage="x dismissal")

        # This runner dies on SIGTERM, so a live runner proves no stage
        # signalled it: DONE runners run host-owned finalizers.
        assert agent.runner.poll() is None
        assert len(x_env.cleanup.pending) == 1

        (outcome,) = await x_env.cleanup.run_pending()
        assert outcome.success, outcome.message
        assert agent.runner.poll() is None
        assert agent.alive() != {}
        assert identity in await asyncio.to_thread(load_dismissed_agents)

        await refresh_fleet(page, source="remote_attention")
        await _wait_row_absent(
            page, app, {identity}, stage="a forced fleet reprojection"
        )
        await reload_agents(page, full_history=True, source="x_e2e_history_after_kill")
        await _wait_row_absent(page, app, {identity}, stage="a complete-history reload")


async def test_x_then_immediate_exit_durable_payload_still_verifies_death(
    x_env: XEnv,
) -> None:
    agent = x_env.launch_agent("row.exit", "20260924144001", runner_ignores_term=True)
    _mark_running(agent)
    identity = agent.identity

    async with x_env.open_page() as page:
        app = page.app
        await reload_agents(page)
        await _select_row(page, app, status="RUNNING", suffix=agent.timestamp)
        await page.press("x")
        await page.expect_modal("ConfirmKillModal")
        await page.press("y")
        await page.expect_no_modal()
        await _wait_row_absent(page, app, {identity}, stage="x confirmation")
        assert len(x_env.cleanup.pending) == 1
        request = json.loads(json.dumps(x_env.cleanup.pending[0].request))
        # The app exits immediately: the held payload never runs in-session.
        assert agent.runner.poll() is None

    # The orphaned durable proc runs out of process after the TUI is gone.
    # Apply its payload exactly as the CLI would, with no app callbacks.
    success, message, _payload = await asyncio.to_thread(
        apply_cleanup_payload_for_result, request
    )
    assert success, message
    await wait_for_processes_dead(*agent.pids.values())
    assert agent.alive() == {}
    assert identity in await asyncio.to_thread(load_dismissed_agents)


async def test_fresh_app_instance_hides_removed_rows(x_env: XEnv) -> None:
    killed = x_env.launch_agent(
        "row.restart-kill", "20260924145001", runner_ignores_term=True
    )
    _write_retry_backoff(killed)
    dismissed = x_env.launch_agent(
        "row.restart-dismiss", "20260924145002", runner_ignores_term=False
    )
    _write_done(dismissed, "completed")
    removed = {killed.identity, dismissed.identity}
    await _ensure_artifact_index()

    async with x_env.open_page() as page:
        app = page.app
        await reload_agents(page)
        await _select_row(page, app, status="RETRYING", suffix=killed.timestamp)
        await page.press("x")
        await page.expect_modal("ConfirmKillModal")
        await page.press("y")
        await page.expect_no_modal()
        await _select_row(page, app, status="DONE", suffix=dismissed.timestamp)
        await page.press("x")
        await page.expect_no_modal()
        await _wait_row_absent(page, app, removed, stage="x removals")
        assert len(x_env.cleanup.pending) == 2
        for _outcome in await x_env.cleanup.run_pending():
            assert _outcome.success, _outcome.message
        await wait_for_processes_dead(*killed.pids.values())
        assert killed.alive() == {}

    # A fresh app instance has no session tombstones: only the durable
    # dismissed index persisted to disk can keep the rows hidden.
    async with x_env.open_page() as page:
        app = page.app
        assert app._explicit_removals == set()
        await reload_agents(page, full_history=True, source="x_e2e_restart_history")
        await _wait_row_absent(page, app, removed, stage="a restart reload")
        await refresh_fleet(page, source="remote_attention")
        await _wait_row_absent(page, app, removed, stage="a post-restart reprojection")
