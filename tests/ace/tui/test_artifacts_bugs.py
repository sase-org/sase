"""Pilot coverage for the Artifacts Bugs pane."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import threading
from typing import Any

import pluggy
import pytest

from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui.artifacts_bugs import BugSnapshot, _BugScope
from sase.ace.tui.modals import IssueEditModal, IssueEditResult
from sase.ace.tui.widgets import ArtifactsBugsPane, PromptInputBar
from sase.ace.tui.widgets.artifacts import BugLinkList
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bug_links import BugLinks
from sase.vcs_provider import IssueWire
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.testing import FakeIssueProvider
from textual.widgets import Input, Static, TextArea


def _provider(*plugins: object) -> VCSPluginManager:
    manager = pluggy.PluginManager("sase_vcs")
    manager.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        manager.register(plugin)
    return VCSPluginManager(manager)


def _issue(number: int = 42, *, state: str = "open") -> IssueWire:
    return IssueWire(
        number=number,
        title=f"Issue {number}",
        state=state,  # type: ignore[arg-type]
        body=f"## Reproduction\n\nBody for issue {number}.",
        labels=("bug", "priority:high"),
        assignees=("octocat",),
        author="reporter",
        updated_at="2026-07-15T10:00:00Z",
        url=f"https://example.test/issues/{number}",
        comment_count=2,
    )


def _snapshot(
    issues: tuple[IssueWire, ...],
    *,
    state_filter: str = "open",
    links: tuple[tuple[int, BugLinks], ...] = (),
    supported: bool = True,
) -> BugSnapshot:
    return BugSnapshot(
        project_key="alpha",
        display_name="Alpha",
        project_file="/state/alpha/alpha.sase",
        cwd="/repos/alpha",
        state_filter=state_filter,  # type: ignore[arg-type]
        issues=issues,
        links=links,
        supported=supported,
    )


async def _open_bugs(page: AcePage) -> ArtifactsBugsPane:
    page.app._set_artifacts_project_scope("alpha", picked=True)
    page.app.current_artifacts_subtab = "bugs"
    await page.expect_state("artifacts_subtab", "bugs")
    return page.query_one_widget("#artifacts-bugs-pane", ArtifactsBugsPane)


async def test_bugs_load_lazily_navigate_filter_and_jump_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked_pr = make_changespec(name="linked_pr")
    linked_pr.bug = "42"
    other_pr = make_changespec(name="other_pr")
    epic = Issue(
        id="sase-42",
        title="Linked epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        changespec_name="linked_pr",
        changespec_bug_id="42",
    )
    calls: list[str] = []

    def collect(_project: str, state: str, _changespecs: object) -> BugSnapshot:
        calls.append(state)
        if state == "closed":
            return _snapshot((_issue(7, state="closed"),), state_filter="closed")
        return _snapshot(
            (_issue(42), _issue(41)),
            state_filter=state,
            links=((42, BugLinks("42", (epic,), (linked_pr,))),),
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot", collect
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type", lambda _path: "gh"
    )

    async with AcePage(changespecs=[other_pr, linked_pr]) as page:
        await page.pause()
        page.app.changespecs = [other_pr, linked_pr]
        assert calls == []
        pane = await _open_bugs(page)
        await page.wait_for(lambda _state: pane.selected_issue == _issue(42))
        assert calls == ["open"]
        assert pane.selected_issue is not None
        assert "Reproduction" in pane.selected_issue.body
        assert pane._link_targets == [("epic", "sase-42"), ("pr", "linked_pr")]

        await page.press("j")
        await page.wait_for(
            lambda _state: (
                pane.selected_issue is not None and pane.selected_issue.number == 41
            )
        )
        await page.press("k")

        await page.press("a")
        await page.wait_for(lambda _state: bool(page.app.query("#prompt-input-bar")))
        bar = page.query_one_widget("#prompt-input-bar", PromptInputBar)
        assert "external bug #42" in bar.current_prompt_text()
        assert "bug_id: 42" in bar.current_prompt_text()
        page.app._unmount_prompt_bar()

        await page.press("l")
        assert isinstance(page.app.focused, BugLinkList)
        await page.press("j")
        assert page.query_one_widget("#bugs-links", BugLinkList).highlighted == 1
        await page.press("enter")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("selected.name", "linked_pr")

        page.app.current_artifacts_subtab = "bugs"
        await page.expect_state("artifacts_subtab", "bugs")
        await page.press("l")
        page.query_one_widget("#bugs-links", BugLinkList).highlighted = 0
        await page.press("enter")
        await page.expect_state("artifacts_subtab", "beads")
        assert page.app.artifacts_plan_target_bead_id == "sase-42"

        page.app.current_artifacts_subtab = "bugs"
        await page.expect_state("artifacts_subtab", "bugs")
        await page.press("f")
        await page.wait_for(
            lambda _state: (
                pane.selected_issue is not None and pane.selected_issue.number == 7
            )
        )
        assert calls[-1] == "closed"


async def test_bugs_automatic_load_is_pump_free_and_coalesces_bursts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[bool] = []

    def collect(_project: str, _state: str, _changespecs: object) -> BugSnapshot:
        call_number = len(calls) + 1
        calls.append(call_number > 1)
        if call_number == 1:
            started.set()
            assert release.wait(timeout=5.0)
        return _snapshot((_issue(call_number),))

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot", collect
    )

    try:
        async with AcePage() as page:
            pane = await _open_bugs(page)
            await page.wait_for(lambda _state: started.is_set())
            assert any(
                task.get_name() == "sase-artifacts-bugs-auto-load"
                for task in page.app._pump_free_async_tasks
            )

            pump_advanced: list[bool] = []
            page.app.call_later(lambda: pump_advanced.append(True))
            await page.wait_for(lambda _state: bool(pump_advanced))

            pane.schedule_load()
            pane.schedule_load(force=True)
            pane.schedule_load()
            assert pane._pending_load is True
            assert pane._pending_force is True

            release.set()
            await page.wait_for(
                lambda _state: (
                    len(calls) == 2
                    and not pane._loading
                    and pane.selected_issue == _issue(2)
                )
            )
            await asyncio.sleep(0)
            assert len(calls) == 2
            assert pane._pending_load is False
            assert pane._pending_force is False
    finally:
        release.set()


async def test_bugs_automatic_load_spawn_failure_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def fail_spawn(
        _owner: object,
        coro: Coroutine[Any, Any, object],
        *,
        name: str,
        registry_attr: str,
    ) -> None:
        nonlocal attempts
        del name, registry_attr
        attempts += 1
        coro.close()

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.spawn_pump_free_task",
        fail_spawn,
    )

    async with AcePage() as page:
        pane = await _open_bugs(page)
        await page.pause()
        assert attempts >= 1
        assert pane._loading is False

        previous_attempts = attempts
        pane.schedule_load(force=True)
        assert attempts == previous_attempts + 1
        assert pane._loading is False


async def test_bug_create_and_state_toggle_are_tracked_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _issue(1)
    plugin = FakeIssueProvider([original])
    provider = _provider(plugin)
    scope = _BugScope(
        project_key="alpha",
        display_name="Alpha",
        project_file="/state/alpha/alpha.sase",
        cwd="/repos/alpha",
        provider=provider,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_a, **_kw: _snapshot((original,)),
    )
    monkeypatch.setattr(
        "sase.ace.tui.artifacts_bugs._resolve_bug_scope", lambda _project: scope
    )

    async with AcePage() as page:
        pane = await _open_bugs(page)
        await page.wait_for(lambda _state: pane.selected_issue == original)

        await page.press("c")
        await page.expect_modal("IssueEditModal")
        modal = page.app.screen
        assert isinstance(modal, IssueEditModal)
        modal.query_one("#issue-edit-title-input", Input).value = "Created in TUI"
        await page.press("enter")
        body = modal.query_one("#issue-edit-body", TextArea)
        assert page.app.focused is body
        body.text = "Markdown body"
        modal.query_one("#issue-edit-labels", Input).value = "bug"
        modal.action_save()
        await page.wait_for(
            lambda _state: (
                any(issue.number == 2 for issue in pane.issues)
                and page.app._task_queue.running_count == 0
            )
        )
        created = next(issue for issue in pane.issues if issue.number == 2)
        assert created.title == "Created in TUI"

        page.app._submit_bug_edit(
            created,
            IssueEditResult("Edited in TUI", "Updated markdown", ("bug", "fixed")),
        )
        await page.wait_for(
            lambda _state: (
                any(issue.title == "Edited in TUI" for issue in pane.issues)
                and page.app._task_queue.running_count == 0
            )
        )
        created = next(issue for issue in pane.issues if issue.number == 2)

        page.app._submit_bug_state_toggle(created, "closed")
        await page.wait_for(
            lambda _state: (
                all(issue.number != 2 for issue in pane.issues)
                and page.app._task_queue.running_count == 0
            )
        )
        assert (
            next(issue for issue in plugin.issues if issue.number == 2).state
            == "closed"
        )


async def test_bugs_capability_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_a, **_kw: _snapshot((), supported=False),
    )

    async with AcePage() as page:
        pane = await _open_bugs(page)
        await page.wait_for(lambda _state: pane.snapshot.supported is False)
        message = page.query_one_widget("#bugs-list-message", Static)
        assert "tracker-capable provider" in message.render().plain
