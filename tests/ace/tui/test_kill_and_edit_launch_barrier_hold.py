"""The relaunch cleanup barrier gates the launch, not the mount."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow import _relaunch_barrier
from sase.ace.tui.actions.agent_workflow._types import (
    RelaunchOperation,
    begin_prompt_session,
)
from sase.ace.tui.widgets import PromptInputBar
from tests.ace.tui._kill_and_edit_launch_barrier_helpers import (
    LaunchBarrierApp,
    PromptLifecycleApp,
    RealBarLaunchApp,
    barriers,
    done_agent,
    home_prompt_context,
    launch_procs,
    prompt_bar_ready,
    submit_launch,
    waiting_notified,
)


async def test_launch_held_while_barrier_pending_then_replays_once_settled(
    tmp_path: Path,
) -> None:
    """Direct regression test for 1b2381366: order, not mount, is protected."""
    agent = done_agent(tmp_path, "feature", "20260801190500", "%id:foo\nDo work")
    app = LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        assert app._prompt_context is not None

        cleanup_task = app.tracked_procs[-1]
        prompt = "%id:!foo\nDo work edited"
        submit_launch(app, prompt)

        # No launch proc submitted while the barrier is pending.
        assert launch_procs(app) == []
        assert waiting_notified(app)

        cleanup_task["proc_callable"]()
        await wait_for(pilot, lambda: bool(launch_procs(app)))

        launched = launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == prompt
        assert barriers(app) == []


async def test_submit_resolved_launch_without_pending_barrier_submits_immediately() -> (
    None
):
    app = LaunchBarrierApp([])

    async with app.run_test(size=(100, 35)):
        app._prompt_context = home_prompt_context()
        submit_launch(app, "%id:!foo\nDo work")

        launched = launch_procs(app)
        assert len(launched) == 1
        assert not waiting_notified(app)


async def test_kill_last_launch_during_hold_drops_parked_launch(
    tmp_path: Path,
) -> None:
    """``,X`` is the only way to cancel a held launch: the bar is already gone."""
    agent = done_agent(tmp_path, "feature", "20260801190600", "%id:foo\nDo work")
    app = RealBarLaunchApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))
        await wait_for(pilot, lambda: prompt_bar_ready(app))

        cleanup_task = app.tracked_procs[-1]
        submit_launch(app, "%id:!foo\nDo work edited")
        assert launch_procs(app) == []
        await pilot.pause()
        assert not app.query(PromptInputBar)

        # The held launch is cancelled with ``,X``, which hands the prompt
        # back in a bar rather than leaving a parked waiter behind.
        app._kill_and_edit_last_launch()
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        assert app.query_one(PromptInputBar).all_prompt_texts() == [
            "%id:!foo\nDo work edited"
        ]

        cleanup_task["proc_callable"]()
        await pilot.pause()

        assert barriers(app) == []
        assert launch_procs(app) == []


async def test_cancelled_hold_drops_old_submit_and_new_prompt_launches() -> None:
    app = PromptLifecycleApp()
    operation = RelaunchOperation("old kill-and-edit")

    async with app.run_test(size=(100, 35)) as pilot:
        barrier = _relaunch_barrier.open_relaunch_cleanup_barrier(
            app,
            "old cleanup",
            operation=operation,
        )
        begin_prompt_session(
            app,
            home_prompt_context("old"),
            relaunch_operation=operation,
        )

        submit_launch(app, "%id:!old\nold edited")
        assert launch_procs(app) == []

        # ``,X`` cancels the held launch and restores its prompt into a bar;
        # cancelling that bar leaves the old edit in prompt history only.
        app._kill_and_edit_last_launch()
        await wait_for(pilot, lambda: prompt_bar_ready(app))
        app.on_prompt_input_bar_cancelled(
            PromptInputBar.Cancelled(
                "%id:!old\nold edited",
                "prompt",
                record_segments=False,
            )
        )
        assert app._prompt_context is None
        assert app.saved_cancelled == ["%id:!old\nold edited"]

        begin_prompt_session(app, home_prompt_context("new"))
        submit_launch(app, "%id:new\nnew")

        launched = launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == "%id:new\nnew"

        _relaunch_barrier.settle_relaunch_cleanup_barrier(app, barrier)

        launched = launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == "%id:new\nnew"


def test_repeated_whole_bar_submit_while_held_replays_once() -> None:
    app = PromptLifecycleApp()
    operation = RelaunchOperation("duplicate submit cleanup")

    barrier = _relaunch_barrier.open_relaunch_cleanup_barrier(
        app,
        "duplicate cleanup",
        operation=operation,
    )
    begin_prompt_session(
        app,
        home_prompt_context("duplicate"),
        relaunch_operation=operation,
    )

    prompt = "%id:!dup\none edited"
    submit_launch(app, prompt)
    submit_launch(app, prompt)

    assert launch_procs(app) == []

    _relaunch_barrier.settle_relaunch_cleanup_barrier(app, barrier)

    launched = launch_procs(app)
    assert len(launched) == 1
    assert launched[0]["request"]["prompt"] == prompt


async def test_barrier_timeout_releases_held_launch_with_warning(
    tmp_path: Path,
) -> None:
    agent = done_agent(tmp_path, "feature", "20260801190700", "%id:foo\nDo work")
    app = LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))
        await wait_for(pilot, lambda: prompt_bar_ready(app))

        prompt = "%id:!foo\nDo work edited"
        submit_launch(app, prompt)
        assert launch_procs(app) == []

        # The cleanup proc's callable never runs (a hung supervisor);
        # simulate the timer firing directly rather than sleeping in real
        # time for ``RELAUNCH_CLEANUP_BARRIER_TIMEOUT_SECONDS``.
        barrier = barriers(app)[0]
        _relaunch_barrier._settle_on_timeout(app, barrier)

        assert barriers(app) == []
        launched = launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == prompt
        assert any(
            "did not settle in time" in message and severity == "warning"
            for message, severity in app.notifications
        )


async def test_two_overlapping_barriers_replay_parked_launch_once(
    tmp_path: Path,
) -> None:
    """Two overlapping ``,x`` cleanups; only the second settling drains the launch.

    Each kill-and-edit still mounts its own prompt bar in production; that
    mounting is already covered by the single-agent tests above, so here the
    mount itself is stubbed out to isolate the barrier bookkeeping (two open
    barriers, one shared parked launch) from unrelated Textual widget-ID
    plumbing.
    """
    first = done_agent(tmp_path, "one", "20260801190800", "%id:one\nFirst")
    second = done_agent(tmp_path, "two", "20260801190900", "%id:two\nSecond")
    app = LaunchBarrierApp([first, second], selected=first)
    app._edit_and_relaunch_agent = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: len(app.tracked_procs) == 1)

        app.selected = second
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: len(app.tracked_procs) == 2)

        assert len(barriers(app)) == 2

        operation: Any = barriers(app)[1].operation
        begin_prompt_session(
            app,
            home_prompt_context(),
            relaunch_operation=operation,
        )
        prompt = "%id:!two\nSecond edited"
        submit_launch(app, prompt)
        assert launch_procs(app) == []

        app.tracked_procs[0]["proc_callable"]()
        assert len(barriers(app)) == 1
        assert launch_procs(app) == []

        app.tracked_procs[1]["proc_callable"]()
        await wait_for(pilot, lambda: bool(launch_procs(app)))

        launched = launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == prompt
        assert barriers(app) == []
