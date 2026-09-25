"""End-to-end ``x`` on an Agents-tab clan racing loads and fleet reprojection.

Drives the mounted Agents tab: on-disk fixture agents with real process trees, a
real ``x`` and confirmation through the pilot, the real tombstone and row
publication path, and the durable cleanup payload run through
``apply_cleanup_payload_for_result``. The component suites cover each boundary
alone; this proves they hold together when an in-flight load, a fleet
reprojection, and a forced complete-history reload all land after the keypress.
"""

from __future__ import annotations

import asyncio

from sase.ace.dismissed_agents import load_dismissed_agents
from sase.ace.tui.models.agent import AgentType
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests.ace.tui._agents_x_pilot_helpers import (
    AgentIdentity,
    FixtureAgent,
    XEnv,
    assert_clan_absent,
    assert_rows_absent,
    disk_rows,
    refresh_fleet,
    reload_agents,
    schedule_agents_load,
    wait_for_processes_dead,
    x_env as x_env,
)

CLAN = "racers"
CLAN_GENERATION = "20260924090000"
CLAN_CONTAINER: AgentIdentity = (AgentType.RUNNING, f"clan:{CLAN}", CLAN_GENERATION)


def _launch_clan(env: XEnv, *, runner_ignores_term: bool) -> list[FixtureAgent]:
    return [
        env.launch_agent(
            f"{CLAN}.{index}",
            f"2026092410000{index}",
            clan=CLAN,
            clan_generation=CLAN_GENERATION,
            runner_ignores_term=runner_ignores_term,
        )
        for index in range(2)
    ]


async def test_clan_x_stays_removed_through_racing_load_fleet_refresh_and_reload(
    x_env: XEnv,
) -> None:
    members = _launch_clan(x_env, runner_ignores_term=True)
    member_ids = {member.identity for member in members}
    removed = member_ids | {CLAN_CONTAINER}

    async with x_env.open_page() as page:
        app = page.app
        await reload_agents(page)
        await page.wait_for(
            lambda _state: CLAN_CONTAINER in {a.identity for a in app._agents},
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        assert member_ids <= {a.identity for a in app._agents_with_children}
        selected = app._get_selected_agent()
        assert selected is not None and selected.identity == CLAN_CONTAINER

        # A load that already read disk and prepared its roster, but has not
        # applied it, holds every member as a live row.
        x_env.gate.arm()
        racing_load = schedule_agents_load(page, source="x_e2e_racing_load")
        await page.wait_for(
            lambda _state: x_env.gate.is_holding, timeout=LOAD_TOLERANT_TIMEOUT
        )
        assert member_ids <= x_env.gate.prepared_identities

        await page.press("x")
        await page.expect_modal("ConfirmKillAllModal")
        await page.press("y")
        await page.press("y")
        await page.expect_no_modal()

        # The TUI stage signalled every runner's group and removed the rows.
        # The SIGTERM-ignoring runners are still alive, so only the session
        # tombstone (not a dead pid) keeps a later load from rebuilding them.
        await wait_for_processes_dead(*(m.pids["same_group"] for m in members))
        assert all(m.runner.poll() is None for m in members)
        assert len(x_env.cleanup.pending) == 1
        assert x_env.cleanup.pending[0].request["transaction"] == "bulk_kill"
        assert_rows_absent(app, removed, stage="x confirmation")
        assert_clan_absent(app, CLAN, stage="x confirmation")

        # The parked load now applies the roster it prepared before the kill.
        x_env.gate.release()
        await racing_load.wait_applied()
        racing_load.assert_absent_at_apply(removed)
        assert_rows_absent(app, removed, stage="the racing load applying")
        assert_clan_absent(app, CLAN, stage="the racing load applying")

        # Fleet refreshes reproject the visible list from the local roster; the
        # forced one skips the unchanged-signature shortcut and rebuilds it.
        await refresh_fleet(page, source="x_e2e_fleet_refresh")
        assert_rows_absent(app, removed, stage="a fleet refresh")
        await refresh_fleet(page, source="remote_attention")
        assert_rows_absent(app, removed, stage="a forced fleet reprojection")
        assert_clan_absent(app, CLAN, stage="a forced fleet reprojection")

        # The runners are alive and their markers are still on disk, so a
        # forced complete-history load really does rebuild them as live rows.
        assert member_ids <= await disk_rows(full_history=True)
        await reload_agents(page, full_history=True, source="x_e2e_forced_history")
        assert_rows_absent(app, removed, stage="a complete-history reload")
        assert_clan_absent(app, CLAN, stage="a complete-history reload")
        await page.expect_screen_not_contains(CLAN)

        # The durable stage kills and verifies every process of every member,
        # including the children that left the runner's process group.
        (outcome,) = await x_env.cleanup.run_pending()
        assert outcome.success, outcome.message
        for member in members:
            await wait_for_processes_dead(*member.pids.values())
            assert member.alive() == {}
        assert member_ids <= await asyncio.to_thread(load_dismissed_agents)

        await refresh_fleet(page, source="remote_attention")
        assert_rows_absent(app, removed, stage="the durable stage")
        assert_clan_absent(app, CLAN, stage="the durable stage")
        await reload_agents(page, full_history=True, source="x_e2e_history_after_kill")
        assert_rows_absent(app, removed, stage="a post-durable reload")
        assert_clan_absent(app, CLAN, stage="a post-durable reload")
        await page.expect_screen_not_contains(CLAN)


async def test_clan_x_durable_stage_kills_orphans_of_runners_that_already_exited(
    x_env: XEnv,
) -> None:
    """The immediate SIGTERM ends the runners; the durable stage still sweeps.

    Their own-group, ``setsid``, and SIGTERM-ignoring children survive the
    runner's death, reparented to init, and only the durable stage can find them
    (by session and launch scratch key) and verify them dead.
    """
    members = _launch_clan(x_env, runner_ignores_term=False)
    orphan_names = {"own_group", "setsid", "ignores_term"}

    async with x_env.open_page() as page:
        app = page.app
        await reload_agents(page)
        await page.wait_for(
            lambda _state: CLAN_CONTAINER in {a.identity for a in app._agents},
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        await page.press("x")
        await page.expect_modal("ConfirmKillAllModal")
        await page.press("y")
        await page.press("y")
        await page.expect_no_modal()

        for member in members:
            await wait_for_processes_dead(member.runner_pid)
            assert set(member.alive()) == orphan_names

        (outcome,) = await x_env.cleanup.run_pending()
        assert outcome.success, outcome.message
        for member in members:
            await wait_for_processes_dead(*member.pids.values())
            assert member.alive() == {}

        await reload_agents(page, full_history=True, source="x_e2e_history_after_kill")
        assert_clan_absent(app, CLAN, stage="a post-durable reload")
        assert_rows_absent(
            app,
            {m.identity for m in members} | {CLAN_CONTAINER},
            stage="a post-durable reload",
        )
