"""Agents-tab regressions for restarting one exact family member."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from threading import Event
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import wait_for
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


def _prompt_bar_ready(app: _FamilyRelaunchApp) -> bool:
    for bar in app.query(PromptInputBar):
        if bar.query("#frontmatter-raw"):
            return True
    return False


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

    with patch(
        "sase.ace.tui.actions.agents._fork_scope.resolve_vcs_tag",
        return_value="#gh:feature ",
    ):
        async with app.run_test(size=(110, 40)) as pilot:
            app._kill_and_edit_agent()
            await wait_for(pilot, lambda: _prompt_bar_ready(app))

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
        await wait_for(
            pilot,
            lambda: isinstance(app.screen, ConfirmKillModal),
        )
        assert isinstance(app.screen, ConfirmKillModal)
        assert app.screen.agent_description == (
            "Sase agent:\n  sase-8u.4.2 @sase-8u.4.2--code\nType: run\nPID: 12345"
        )

        await pilot.press("n")
        await wait_for(
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

    with patch(
        "sase.ace.tui.actions.agents._fork_scope.resolve_vcs_tag",
        return_value="#gh:feature ",
    ):
        async with app.run_test(size=(100, 35)) as pilot:
            app._kill_and_edit_agent()
            await wait_for(
                pilot,
                lambda: isinstance(app.screen, ConfirmKillModal),
            )
            assert isinstance(app.screen, ConfirmKillModal)

            await pilot.press("y")
            await wait_for(pilot, lambda: _prompt_bar_ready(app))

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
            await wait_for(pilot, lambda: bool(app.notifications))

            assert app.dismissed == []
            assert app.killed == []
            assert not app.query(PromptInputBar)
            assert app.notifications == [
                (
                    "Selected agent is no longer available; nothing killed",
                    "warning",
                )
            ]


_EPIC_ROOT_PROMPT = (
    "#gh:gh_sase-org__sase\n"
    "%id(sase-pw.1, bead=sase-pw.1)\n"
    "%clan(sase-pw, tribe=epic, summary_script=sase_clan_summary_epic)\n"
    "%model:@medium\n"
    "%auto\n"
    "#bd/work_phase_bead:sase-pw.1"
)


def _write_prompt(directory: Path, prompt: str) -> Path:
    directory.mkdir()
    (directory / "raw_xprompt.md").write_text(prompt, encoding="utf-8")
    return directory


def _epic_family_root(tmp_path: Path) -> Agent:
    artifacts = _write_prompt(tmp_path / "epic-root", _EPIC_ROOT_PROMPT)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/projects/project/project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 23, 12, 0, 0),
        raw_suffix="20260723120000",
        artifacts_dir=str(artifacts),
        agent_name="sase-pw.1--plan",
        agent_family="sase-pw.1",
        agent_family_role="root",
        plan_chain_root=True,
        role_suffix="--plan",
        agent_clan="sase-pw",
        phase_bead_id="sase-pw.1",
    )


def _plain_plan_root(tmp_path: Path) -> Agent:
    artifacts = _write_prompt(
        tmp_path / "plain-root",
        "#gh:gh_sase-org__sase #plan",
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/projects/project/project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 23, 12, 0, 0),
        raw_suffix="20260723120100",
        artifacts_dir=str(artifacts),
        agent_name="06d--plan",
        agent_family="06d",
        agent_family_role="root",
        plan_chain_root=True,
        role_suffix="--plan",
    )


def _self_attaching_family_row(tmp_path: Path) -> Agent:
    artifacts = _write_prompt(tmp_path / "self-attach", "Do work")
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/projects/project/project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 23, 12, 0, 0),
        raw_suffix="20260723120200",
        artifacts_dir=str(artifacts),
        agent_name="sase-pw.1",
        agent_family="sase-pw.1",
        role_suffix="--code",
        phase_bead_id="sase-pw.1",
    )


def _clan_container_row() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/projects/project/project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 23, 12, 0, 0),
        raw_suffix="20260723120300",
        agent_name="sase-pw.1",
        agent_clan="sase-pw",
        is_clan_container=True,
    )


async def test_family_root_relaunch_keeps_clan_and_not_self_family(
    tmp_path: Path,
) -> None:
    root = _epic_family_root(tmp_path)
    app = _FamilyRelaunchApp([root], root)

    async with app.run_test(size=(110, 40)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        seeded = app.query_one(PromptInputBar).all_prompt_texts()[0]
        assert seeded.startswith("%id(!1, clan=sase-pw, bead=sase-pw.1)")
        assert "%clan" not in seeded
        assert "family=" not in seeded

    assert app.dismissed == [root]
    assert app.killed == []
    assert app.notifications == []


async def test_plain_plan_root_relaunch_keeps_prompt(
    tmp_path: Path,
) -> None:
    root = _plain_plan_root(tmp_path)
    app = _FamilyRelaunchApp([root], root)

    async with app.run_test(size=(110, 40)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        seeded = app.query_one(PromptInputBar).all_prompt_texts()[0]
        assert seeded == "#gh:gh_sase-org__sase #plan"
        assert "family=" not in seeded

    assert app.dismissed == [root]
    assert app.killed == []


async def test_self_attaching_family_rewrite_notifies_and_kills_nothing(
    tmp_path: Path,
) -> None:
    row = _self_attaching_family_row(tmp_path)
    app = _FamilyRelaunchApp([row], row)

    async with app.run_test(size=(110, 40)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.notifications))

        assert app.killed == []
        assert app.dismissed == []
        assert not app.query(PromptInputBar)
        assert len(app.notifications) == 1
        message, severity = app.notifications[0]
        assert severity == "error"
        assert "sase-pw.1" in message
        assert "family=" in message


async def test_clan_container_focused_relaunch_warns_and_kills_nothing() -> None:
    container = _clan_container_row()
    app = _FamilyRelaunchApp([container], container)

    async with app.run_test(size=(110, 40)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.notifications))

        assert app.killed == []
        assert app.dismissed == []
        assert not app.query(PromptInputBar)
        assert app.notifications == [
            (
                "'sase-pw' is a clan container; mark its members and use "
                ",x on the marked set instead.",
                "warning",
            )
        ]
