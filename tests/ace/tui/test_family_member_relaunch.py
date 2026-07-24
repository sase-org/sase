"""Agents-tab regressions for restarting one exact family member."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import json
from pathlib import Path
from threading import Event
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widgets import Static

from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals import ConfirmKillModal
from sase.ace.tui.widgets import PromptInputBar


class _FamilyRelaunchApp(EntryRelaunchMixin, App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, agents: list[Agent], selected: Agent) -> None:
        super().__init__()
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self.selected = selected
        self._prompt_context = None
        self._last_custom_agent_selection = None
        self.notifications: list[tuple[str, str]] = []
        self.dismissed: list[Agent] = []
        self.killed: list[Agent] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="host")

    def notify(self, message: str, *, severity: str = "information", **_kwargs) -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        return self.selected if self.selected in self._agents_with_children else None

    def _unmount_prompt_bar(self) -> str:
        return ""

    def _remove(self, agent: Agent) -> None:
        self._agents = [row for row in self._agents if row.identity != agent.identity]
        self._agents_with_children = [
            row for row in self._agents_with_children if row.identity != agent.identity
        ]

    def _dismiss_done_agent(self, agent: Agent) -> None:
        self.dismissed.append(agent)
        self._remove(agent)

    def _do_kill_agent(self, agent: Agent) -> None:
        self.killed.append(agent)
        self._remove(agent)


async def _wait_until(
    pilot: Pilot[None],
    predicate: Callable[[], bool],
    *,
    timeout: float = 5.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("family relaunch test condition timed out")
        await pilot.pause()


def _family_rows(tmp_path: Path, *, running_child: bool = False) -> tuple[Agent, Agent]:
    parent_dir = tmp_path / "parent"
    child_dir = tmp_path / "child"
    parent_dir.mkdir()
    child_dir.mkdir()
    (parent_dir / "raw_xprompt.md").write_text(
        "#gh:project #propose\nPlan the change",
        encoding="utf-8",
    )
    (parent_dir / "embedded_workflows.json").write_text(
        json.dumps(
            [
                {"name": "gh", "tags": ["vcs"], "args": {"ref": "project"}},
                {"name": "propose", "tags": ["rollover"], "args": {}},
            ]
        ),
        encoding="utf-8",
    )
    (child_dir / "workflow-gh-main_prompt.md").write_text(
        "Implement the approved plan body.",
        encoding="utf-8",
    )

    common = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "feature",
        "project_file": "/tmp/projects/project/project.sase",
        "start_time": datetime(2026, 7, 23, 12, 0, 0),
        "agent_family": "sase-8u.4.2",
        "agent_family_parallel": False,
    }
    parent = Agent(
        **common,
        status="DONE",
        raw_suffix="20260723120000",
        artifacts_dir=str(parent_dir),
        agent_name="sase-8u.4.2--plan",
        role_suffix="--plan",
        phase_bead_id="sase-8u.4.2",
    )
    child = Agent(
        **common,
        status="RUNNING" if running_child else "DONE",
        pid=12345 if running_child else None,
        raw_suffix="20260723120100",
        artifacts_dir=str(child_dir),
        parent_timestamp=parent.raw_suffix,
        step_name="gh-main",
        agent_name="sase-8u.4.2--code",
        role_suffix="--code",
        phase_bead_id="sase-8u.4.2",
        model="gpt-5.6-sol",
        llm_provider="codex",
        reasoning_effort="xhigh",
    )
    return parent, child


async def test_completed_family_member_relaunch_dismisses_only_selected_child(
    tmp_path: Path,
) -> None:
    parent, child = _family_rows(tmp_path)
    app = _FamilyRelaunchApp([parent, child], child)

    with (
        patch(
            "sase.ace.last_agent_selection.save_last_agent_selection_if_launchable",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.actions.agents._fork_scope.resolve_vcs_tag",
            return_value="#gh:feature ",
        ),
    ):
        async with app.run_test(size=(110, 40)) as pilot:
            app._kill_and_edit_agent()
            await _wait_until(pilot, lambda: bool(app.query(PromptInputBar)))

            bar = app.query_one(PromptInputBar)
            assert bar.all_prompt_texts() == [
                "%id(!code, family=sase-8u.4.2, bead=sase-8u.4.2)\n"
                "%model:codex/gpt-5.6-sol@xhigh\n"
                "#gh:feature\n"
                "Implement the approved plan body.\n"
                "#propose\n"
            ]

    assert app.dismissed == [child]
    assert app.killed == []
    assert app._agents_with_children == [parent]


async def test_running_family_member_relaunch_cancel_is_non_destructive(
    tmp_path: Path,
) -> None:
    parent, child = _family_rows(tmp_path, running_child=True)
    app = _FamilyRelaunchApp([parent, child], child)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await _wait_until(
            pilot,
            lambda: isinstance(app.screen, ConfirmKillModal),
        )
        assert isinstance(app.screen, ConfirmKillModal)

        await pilot.press("n")
        await _wait_until(
            pilot,
            lambda: not isinstance(app.screen, ConfirmKillModal),
        )

        assert app.killed == []
        assert app.dismissed == []
        assert app._agents_with_children == [parent, child]
        assert not app.query(PromptInputBar)


async def test_running_family_member_relaunch_confirmation_kills_only_child(
    tmp_path: Path,
) -> None:
    parent, child = _family_rows(tmp_path, running_child=True)
    app = _FamilyRelaunchApp([parent, child], child)

    with (
        patch(
            "sase.ace.tui.actions.agents._fork_scope.resolve_vcs_tag",
            return_value="#gh:feature ",
        ),
        patch(
            "sase.ace.last_agent_selection.save_last_agent_selection_if_launchable",
            return_value=False,
        ),
    ):
        async with app.run_test(size=(100, 35)) as pilot:
            app._kill_and_edit_agent()
            await _wait_until(
                pilot,
                lambda: isinstance(app.screen, ConfirmKillModal),
            )
            assert isinstance(app.screen, ConfirmKillModal)

            await pilot.press("y")
            await _wait_until(pilot, lambda: bool(app.query(PromptInputBar)))

            assert app.killed == [child]
            assert app.dismissed == []
            assert app._agents_with_children == [parent]
            assert (
                app.query_one(PromptInputBar)
                .all_prompt_texts()[0]
                .startswith("%id(!code, family=sase-8u.4.2")
            )


async def test_family_member_relaunch_aborts_when_row_goes_stale(
    tmp_path: Path,
) -> None:
    parent, child = _family_rows(tmp_path)
    app = _FamilyRelaunchApp([parent, child], child)
    started = Event()
    release = Event()

    def delayed_prompt(*_args) -> str:
        started.set()
        release.wait(timeout=2)
        return "%id(!code, family=sase-8u.4.2)\nDo work"

    with patch(
        "sase.ace.tui.actions.agent_workflow._entry_relaunch."
        "prepare_kill_edit_agent_prompt",
        side_effect=delayed_prompt,
    ):
        async with app.run_test(size=(100, 35)) as pilot:
            app._kill_and_edit_agent()
            await pilot.pause(0.05)
            assert started.is_set()

            app._remove(child)
            release.set()
            await _wait_until(pilot, lambda: bool(app.notifications))

            assert app.dismissed == []
            assert app.killed == []
            assert not app.query(PromptInputBar)
            assert app.notifications == [
                (
                    "Selected agent is no longer available; nothing killed",
                    "warning",
                )
            ]
