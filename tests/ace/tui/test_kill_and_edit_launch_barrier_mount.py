"""Focused and marked ``,x`` kill-and-edit mounts the prompt immediately."""

from __future__ import annotations

from pathlib import Path

from sase.ace.testing import wait_for
from sase.ace.tui.modals import ConfirmKillAllModal, ConfirmKillModal
from sase.ace.tui.widgets import PromptInputBar
from tests.ace.tui._kill_and_edit_launch_barrier_helpers import (
    LaunchBarrierApp,
    barriers,
    done_agent,
    done_agent_without_raw_suffix,
    prompt_bar_ready,
    running_agent,
)


async def test_focused_dismiss_kill_and_edit_mounts_prompt_bar_immediately(
    tmp_path: Path,
) -> None:
    agent = done_agent(tmp_path, "feature", "20260801190000", "%id:foo\nDo work")
    app = LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))

        # The optimistic in-memory removal already ran, and the prompt bar
        # is ready without waiting for the durable persistence proc.
        assert app._agents_with_children == []
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        bar = app.query_one(PromptInputBar)
        assert len(bar.all_prompt_texts()) == 1

        # The barrier is still open: settling it releases nothing (there's
        # no pending launch), but it must clear on settlement.
        assert barriers(app)

        task = app.tracked_procs[-1]
        assert task["proc_type"] == "dismiss"
        task["proc_callable"]()

        assert app._dismiss_persistence_inflight == set()
        assert barriers(app) == []


async def test_focused_dismiss_kill_and_edit_rejected_submission_mounts_and_settles(
    tmp_path: Path,
) -> None:
    """A collision that rejects the proc submission cannot strand the prompt."""
    agent = done_agent(tmp_path, "feature", "20260801190050", "%id:foo\nDo work")
    app = LaunchBarrierApp([agent], selected=agent)
    # Simulate an already-in-flight dismiss persistence proc for this
    # identity so ``_submit_dismiss_persistence_task`` rejects submission
    # instead of queuing a new tracked proc.
    app._dismiss_persistence_inflight.add(agent.identity)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: prompt_bar_ready(app))

        # No proc was ever submitted, yet the prepared prompt still mounted
        # via the immediate on_settled() fallback, and no barrier is left
        # pending.
        assert app.tracked_procs == []
        assert len(app.query_one(PromptInputBar).all_prompt_texts()) == 1
        assert barriers(app) == []


async def test_focused_kill_and_edit_mounts_prompt_bar_immediately(
    tmp_path: Path,
) -> None:
    agent = running_agent(tmp_path, "feature", "20260801190100", "%id:foo\nDo work")
    app = LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmKillModal))

        await pilot.press("y")
        await wait_for(pilot, lambda: bool(app.tracked_procs))

        assert app._agents_with_children == []
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        assert len(app.query_one(PromptInputBar).all_prompt_texts()) == 1
        assert barriers(app)

        task = app.tracked_procs[-1]
        assert task["proc_type"] == "kill"
        task["proc_callable"]()

        assert app._kill_persistence_inflight == set()
        assert barriers(app) == []


async def test_focused_kill_and_edit_cancel_mounts_nothing_and_leaves_no_barrier(
    tmp_path: Path,
) -> None:
    agent = running_agent(tmp_path, "feature", "20260801190200", "%id:foo\nDo work")
    app = LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmKillModal))

        await pilot.press("n")
        await wait_for(pilot, lambda: not isinstance(app.screen, ConfirmKillModal))

        assert app._agents_with_children == [agent]
        assert app.tracked_procs == []
        assert not app.query(PromptInputBar)
        assert not barriers(app)


async def test_focused_dismiss_kill_and_edit_missing_raw_suffix_mounts_nothing(
    tmp_path: Path,
) -> None:
    agent = done_agent_without_raw_suffix(tmp_path, "feature", "%id:foo\nDo work")
    app = LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(
            pilot,
            lambda: any(
                "Cannot dismiss agent" in message for message, _ in app.notifications
            ),
        )

        assert app._agents_with_children == [agent]
        assert app.tracked_procs == []
        assert not app.query(PromptInputBar)
        assert not barriers(app)


async def test_marked_bulk_kill_and_edit_mounts_prompt_stack_immediately(
    tmp_path: Path,
) -> None:
    killed = running_agent(tmp_path, "live", "20260801190300", "%id:live\nFirst")
    dismissed = done_agent(tmp_path, "done", "20260801190400", "%id:done\nSecond")
    app = LaunchBarrierApp([killed, dismissed])
    app._marked_agents = {killed.identity, dismissed.identity}
    app._marked_agent_order = [killed.identity, dismissed.identity]

    async with app.run_test(size=(100, 35)) as pilot:
        app._bulk_kill_marked_agents_and_edit()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmKillAllModal))

        # ConfirmKillAllModal needs an extra settle tick before its key
        # binding takes effect once freshly mounted; matches the double
        # ``pilot.press("y")`` pattern used elsewhere for this modal.
        await pilot.press("y")
        await pilot.pause()
        if isinstance(app.screen, ConfirmKillAllModal):
            await pilot.press("y")
        await wait_for(pilot, lambda: bool(app.tracked_procs))

        # One combined bulk proc handles both the killed and dismissed rows.
        assert app._agents_with_children == []
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        bar = app.query_one(PromptInputBar)
        assert bar.all_prompt_texts() == ["%id:!live\nFirst", "%id:!done\nSecond"]
        assert barriers(app)

        task = app.tracked_procs[-1]
        task["proc_callable"]()

        assert barriers(app) == []
