"""Publish surfaces for the Memory panel."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

import pytest
from textual.widgets import Input

from sase.ace.testing import wait_for
from sase.ace.tui.modals import memory_panel_write as write_mod
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.memory_panel import MemoryPanel
from sase.ace.tui.modals.memory_panel_add import MemoryNoteFormModal
from sase.ace.tui.modals.memory_panel_publish import (
    MemoryPublishModal,
    memory_publish_argv,
    memory_publish_cwd,
    memory_publish_subject,
)
from sase.memory.mutation import MemoryMutationOutcome
from tests.ace.tui.modals.memory_panel_actions_test_helpers import (
    MemoryPanelActionsApp,
    fill_form,
    install_write_fakes,
    mutation_outcome,
)
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load,
    memory_note,
    panel_static_text,
    scope_ref,
    scope_snapshot,
)


def test_publish_argv_for_both_branches() -> None:
    assert memory_publish_argv(commit=True, subject="Add memory note beta") == [
        "sase",
        "memory",
        "init",
        "--message",
        "Add memory note beta",
    ]
    assert memory_publish_argv(commit=False, subject="ignored") == [
        "sase",
        "memory",
        "init",
        "--no-commit",
    ]


def test_publish_cwd_uses_home_for_home_scope() -> None:
    project = scope_ref("sase", "sase", content_root="/tmp/project")
    home = scope_ref(
        "home",
        "Home (chezmoi)",
        kind="home",
        content_root="/tmp/chezmoi",
    )
    assert memory_publish_cwd(project) == Path("/tmp/project")
    assert memory_publish_cwd(home) == Path.home()


def test_publish_subject_prefills_from_write_kind() -> None:
    assert memory_publish_subject("sase", kind="add", stem="beta") == (
        "Add memory note beta"
    )
    assert memory_publish_subject("sase") == "Publish memory notes for sase"


async def test_publish_runs_init_and_clears_unpublished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase", content_root="/tmp/project")
    snapshots = {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[tuple[list[str], str]] = []

    def fake_create(**_kwargs: Any) -> MemoryMutationOutcome:
        snapshots[ref.key] = scope_snapshot(
            ref, (memory_note("alpha"), memory_note("beta", description="New."))
        )
        return mutation_outcome("beta")

    def fake_run(
        argv: Any, *, cwd: Any = None, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        recorded.append((list(argv), str(cwd)))
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    install_write_fakes(monkeypatch, snapshots, create=fake_create)
    monkeypatch.setattr(write_mod, "run_noninteractive", fake_run)

    panel = MemoryPanel()
    app = MemoryPanelActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("a")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await fill_form(app, stem="beta", description="New.")
        form.action_submit()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        await pilot.press("escape")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryPublishModal))
        assert "UNPUBLISHED" in panel_static_text(panel, "memory-panel-header")
        publish = app.screen
        assert isinstance(publish, MemoryPublishModal)
        assert publish.query_one("#memory-publish-subject", Input).value == (
            "Add memory note beta"
        )
        publish.action_publish_commit()
        await wait_for(pilot, lambda: "memory-publish" in app.session_calls)
        await wait_for(pilot, lambda: "sase" not in panel._unpublished_scopes)
        assert "UNPUBLISHED" not in panel_static_text(panel, "memory-panel-header")

    assert recorded == [
        (
            ["sase", "memory", "init", "--message", "Add memory note beta"],
            "/tmp/project",
        )
    ]


async def test_publish_only_and_home_scope_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref(
        "home",
        "Home (chezmoi)",
        kind="home",
        content_root="/tmp/chezmoi",
    )
    snapshots = {"home": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[tuple[list[str], str]] = []

    def fake_run(
        argv: Any, *, cwd: Any = None, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        recorded.append((list(argv), str(cwd)))
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    monkeypatch.setattr(write_mod, "run_noninteractive", fake_run)

    panel = MemoryPanel()
    app = MemoryPanelActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._mark_scope_unpublished()
        await wait_for(
            pilot,
            lambda: "UNPUBLISHED" in panel_static_text(panel, "memory-panel-header"),
        )
        await pilot.press("I")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryPublishModal))
        app.screen.action_publish_only()
        await wait_for(pilot, lambda: "memory-publish" in app.session_calls)
        await wait_for(pilot, lambda: "home" not in panel._unpublished_scopes)

    assert recorded == [(["sase", "memory", "init", "--no-commit"], str(Path.home()))]


async def test_publish_failure_keeps_unpublished_and_surfaces_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)

    def fake_run(
        argv: Any, *, cwd: Any = None, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            list(argv), 1, "", "fold failed\ncommit subject required\n"
        )

    monkeypatch.setattr(write_mod, "run_noninteractive", fake_run)

    panel = MemoryPanel()
    app = MemoryPanelActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._mark_scope_unpublished()
        await pilot.press("I")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryPublishModal))
        app.screen.action_publish_only()
        await wait_for(
            pilot,
            lambda: any(
                "commit subject required" in msg for msg, _sev in app.notifications
            ),
        )
        assert "UNPUBLISHED" in panel_static_text(panel, "memory-panel-header")

    assert "sase" in panel._unpublished_scopes
    assert any(sev == "error" for _msg, sev in app.notifications)
