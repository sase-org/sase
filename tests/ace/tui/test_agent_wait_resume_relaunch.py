"""Tests for Agents-tab wait relaunch flows.

Covers ``_apply_wait``'s time-replacement relaunch path and
``_apply_wait_running``, which both kill and relaunch the underlying agent
process with an updated wait directive.
"""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals import WaitModalResult
from tests.ace.tui._agent_wait_resume_helpers import (
    FakeWaitResumeApp,
    make_waiting_agent,
)


def test_apply_wait_with_time_relaunches_with_replacement_directive(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%w:old #t:5m do the thing",
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        agent_name="old.w0",
        wait_duration=300.0,
        waiting_for=["old"],
    )
    app = FakeWaitResumeApp()
    app.selected_agent = agent

    app._apply_wait(
        str(tmp_path),
        agent,
        WaitModalResult(agents=["new"], time_token="10m"),
    )

    assert len(app.pushed_screens) == 1
    modal, callback = app.pushed_screens[0]
    assert "waiting for new, then 10m" in modal.agent_description  # type: ignore[attr-defined]
    assert "Sase agent:\n  old.w0" in modal.agent_description  # type: ignore[attr-defined]
    assert callable(callback)
    callback(True)

    assert app.killed_agents == [agent]
    assert app.launch_prompts == ["%wait(new, time=10m)\n%id:!old.w0\ndo the thing"]
    assert "%w:old" not in app.launch_prompts[0]
    assert "#t:5m" not in app.launch_prompts[0]


def test_apply_wait_running_relaunches_with_canonical_wait_and_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw_xprompt.md").write_text("%id:kept do the thing", encoding="utf-8")
    agent = make_waiting_agent(
        status="RUNNING",
        artifacts_dir=str(tmp_path),
        agent_name="kept",
    )
    app = FakeWaitResumeApp()
    app.selected_agent = agent

    app._apply_wait_running(agent, WaitModalResult(agents=["dep"], time_token=None))

    assert len(app.pushed_screens) == 1
    modal, callback = app.pushed_screens[0]
    assert "Sase agent:\n  kept" in modal.agent_description  # type: ignore[attr-defined]
    assert callable(callback)
    callback(True)

    assert app.killed_agents == [agent]
    assert app.launch_prompts == ["%wait(dep)\n%id:!kept do the thing"]


def test_apply_wait_running_holds_launch_until_cleanup_settles(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw_xprompt.md").write_text("Do the work", encoding="utf-8")
    agent = make_waiting_agent(
        status="RUNNING",
        artifacts_dir=str(tmp_path),
        agent_name="old.w0",
    )
    app = FakeWaitResumeApp()
    app.auto_settle_kill = False
    app.selected_agent = agent

    app._apply_wait_running(agent, WaitModalResult(agents=["dep"], time_token=None))

    assert len(app.pushed_screens) == 1
    _modal, callback = app.pushed_screens[0]
    callback(True)

    assert app.killed_agents == [agent]
    assert app.launch_prompts == []
    assert len(app.kill_settlers) == 1

    app.kill_settlers[0]()

    assert app.launch_prompts == ["%wait(dep)\n%id:!old.w0\nDo the work"]


def test_apply_wait_running_run_now_is_noop() -> None:
    agent = make_waiting_agent(status="RUNNING")
    app = FakeWaitResumeApp()

    app._apply_wait_running(
        agent,
        WaitModalResult(agents=[], time_token=None, run_now=True),
    )

    assert app.notifications == [("Agent is already running", "warning")]
    assert app.pushed_screens == []
