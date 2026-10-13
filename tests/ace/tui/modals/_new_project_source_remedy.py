"""Remedy and hot-path tests for the New Project source stage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from textual.widgets import Input, OptionList, Static

from sase import workspace_provider
from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_source import NewProjectSource
from sase.project_onboarding import OwnerResult, Preferences
from tests.ace.tui.modals._new_project_source_helpers import (
    ModalApp,
    inputs,
    provider,
)


def _raise_suspend():  # type: ignore[no-untyped-def]
    raise OSError("no terminal")


async def test_remedy_falls_back_to_provider_level(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    recorded: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_source.subprocess.run",
        lambda argv, **kwargs: recorded.append(tuple(argv)),
    )
    error_inputs = inputs(
        owners=[
            OwnerResult(
                name="sase-org",
                status="error",
                error_kind="auth",
                message="expired",
                remedy_argv=["gh", "auth", "login"],
            )
        ]
    )
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": error_inputs},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        from contextlib import nullcontext

        monkeypatch.setattr(app, "suspend", lambda *args, **kwargs: nullcontext())
        app.push_screen(modal)
        await pilot.pause()
        source = modal.query_one(NewProjectSource)
        # Move the highlight off the owner-error row so the provider-level
        # fallback (not the row path) supplies the remedy.
        options = source.query_one(OptionList)
        fallback_index = None
        for index in range(options.option_count):
            row = source._rows.get(str(options.get_option_at_index(index).id or ""))
            if row is not None and not row.is_error:
                fallback_index = index
                break
        assert fallback_index is not None
        options.highlighted = fallback_index
        await pilot.pause()
        highlighted = source.selected_row()
        assert highlighted is not None and not highlighted.is_error
        # Highlight is not on the error row, but the chip advertises t.
        assert source._remedy_argv() == ("gh", "auth", "login")
        source.action_run_remedy()
        assert recorded == [("gh", "auth", "login")]


async def test_remedy_suspend_failure_notifies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    error_inputs = inputs(
        owners=[
            OwnerResult(
                name="sase-org",
                status="error",
                error_kind="auth",
                message="expired",
                remedy_argv=["gh", "auth", "login"],
            )
        ]
    )
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": error_inputs},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        source = modal.query_one(NewProjectSource)
        notices: list[str] = []
        source.notify = lambda message, *args, **kwargs: notices.append(str(message))  # type: ignore[method-assign]
        monkeypatch.setattr(app, "suspend", lambda *args, **kwargs: _raise_suspend())
        source.action_run_remedy()
        assert any("Could not run remedy" in notice for notice in notices)


async def test_remedy_suspend_unsupported_notifies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from textual.app import SuspendNotSupported

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    error_inputs = inputs(
        owners=[
            OwnerResult(
                name="sase-org",
                status="error",
                error_kind="auth",
                message="expired",
                remedy_argv=["gh", "auth", "login"],
            )
        ]
    )
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": error_inputs},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        source = modal.query_one(NewProjectSource)
        notices: list[str] = []
        source.notify = lambda message, *args, **kwargs: notices.append(str(message))  # type: ignore[method-assign]

        def _raise_unsupported(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise SuspendNotSupported("suspend is not supported")

        monkeypatch.setattr(app, "suspend", _raise_unsupported)
        source.action_run_remedy()
        assert any("Could not run remedy" in notice for notice in notices)


async def test_filter_typing_and_highlight_spawn_no_subprocess(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """Perf guard: filter/highlight stay in memory plus the pure parse."""
    import subprocess as _subprocess

    parses: list[str] = []
    probes: list[tuple[str, str]] = []
    hook_calls: list[str] = []

    def _parse(workflow_type: str, text: str):  # type: ignore[no-untyped-def]
        parses.append(text)
        return None

    def _probe(workflow_type: str, ref: str):  # type: ignore[no-untyped-def]
        probes.append((workflow_type, ref))
        raise AssertionError("probe must stay debounced off the hot path")

    def _forbidden_hook(name: str):  # type: ignore[no-untyped-def]
        def _hook(*args, **kwargs):  # type: ignore[no-untyped-def]
            hook_calls.append(name)
            raise AssertionError(f"{name} must stay off the hot path")

        return _hook

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", _parse)
    monkeypatch.setattr(workspace_provider, "probe_repo", _probe)
    monkeypatch.setattr(
        workspace_provider,
        "list_repo_candidates",
        _forbidden_hook("list_repo_candidates"),
    )
    monkeypatch.setattr(
        workspace_provider,
        "list_local_repo_candidates",
        _forbidden_hook("list_local_repo_candidates"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_source.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("no subprocess on the hot path")
        ),
    )
    monkeypatch.setattr(
        _subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("no subprocess on the hot path")
        ),
    )
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    from sase.ace.tui.util.debounce import DetailPanelDebouncer

    scheduled: list[Any] = []
    monkeypatch.setattr(
        DetailPanelDebouncer, "schedule", lambda self, cb: scheduled.append(cb)
    )
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        # Mount may legitimately describe the creation form; after settle,
        # typing and highlight must not invoke any provider hook but parse.
        monkeypatch.setattr(
            workspace_provider,
            "describe_repo_creation",
            _forbidden_hook("describe_repo_creation"),
        )
        hook_calls.clear()
        source = modal.query_one(NewProjectSource)
        source.focus_filter()
        await pilot.pause()
        await pilot.press(*"sase")
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == "sase"
        assert parses, "the pure parse hook may run on the hot path"
        assert probes == []
        assert hook_calls == []
        modal.query_one("#new-project-filter", Input).value = ""
        await pilot.pause()
        assert probes == []
        assert hook_calls == []
        first = source.selected_row()
        source.focus_list()
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        moved = source.selected_row()
        assert moved is not None and moved is not first
        # The highlight paints immediately; the probe stays debounced.
        assert (
            moved.display
            in modal.query_one("#new-project-source-detail", Static).render().plain
        )
        assert probes == []
        assert hook_calls == []
        assert scheduled, "highlight must schedule the debounced probe"


async def test_highlight_paints_before_debounced_probe_runs(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    monkeypatch.setattr(
        workspace_provider,
        "probe_repo",
        lambda workflow_type, ref: SimpleNamespace(
            visibility="public",
            default_branch="main",
            sase_managed=True,
            can_push=True,
            message="",
        ),
    )
    from sase.ace.tui.util.debounce import DetailPanelDebouncer

    scheduled: list[Any] = []
    monkeypatch.setattr(
        DetailPanelDebouncer, "schedule", lambda self, cb: scheduled.append(cb)
    )
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        source = modal.query_one(NewProjectSource)
        source.focus_list()
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        moved = source.selected_row()
        assert moved is not None
        detail_before = modal.query_one("#new-project-source-detail", Static)
        assert moved.display in detail_before.render().plain
        assert "✓ managed" not in detail_before.render().plain
        for callback in list(scheduled):
            callback()
        await wait_for(
            pilot,
            lambda: (
                "✓ managed"
                in modal.query_one("#new-project-source-detail", Static).render().plain
            ),
        )
