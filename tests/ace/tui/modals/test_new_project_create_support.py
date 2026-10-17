"""Create support discovery across the New Project bootstrap path."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from textual.widgets import Input, OptionList

from sase import workspace_provider
from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_source import NewProjectSource
from sase.project_onboarding import CandidateInputs, Preferences
from sase.workspace_provider._hookspec import RepoCreationForm
from tests.ace.tui.modals._new_project_create_helpers import repo_form
from tests.ace.tui.modals._new_project_source_helpers import (
    ModalApp,
    inputs,
    parsed,
    provider,
)


def _describe_calls(
    monkeypatch: pytest.MonkeyPatch,
    *,
    calls: list[str],
    result: RepoCreationForm | None = None,
) -> None:
    def describe(_workflow_type: str, namespace: str) -> RepoCreationForm | None:
        calls.append(namespace)
        if namespace == "":
            return None
        return replace(result or repo_form(), namespace=namespace)

    monkeypatch.setattr(workspace_provider, "describe_repo_creation", describe)


async def test_bootstrap_discovers_namespace_and_pins_create_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    _describe_calls(monkeypatch, calls=calls)
    monkeypatch.setattr(
        workspace_provider,
        "get_all_workflow_metadata",
        lambda: (provider("gh", "GitHub"),),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_modal_providers.load_preferences",
        lambda: Preferences(last_provider="gh"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_modal_providers.load_candidate_inputs",
        lambda *_args, **_kwargs: inputs(),
    )
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parsed)
    monkeypatch.setattr(workspace_provider, "probe_repo", lambda *_args: None)
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    modal = NewProjectModal()
    app = ModalApp()

    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await wait_for(
            pilot, lambda: modal.query_one(NewProjectSource).create_row is not None
        )
        assert "" not in calls
        assert "bbugyi200" in calls
        modal.query_one("#new-project-source-list", OptionList).focus()
        await pilot.press("n")
        await wait_for(pilot, lambda: modal._state.stage == "create-configure")


async def test_cached_result_for_old_namespace_is_not_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _describe_calls(monkeypatch, calls=calls)
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs(account="", owners=[])},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await wait_for(
            pilot, lambda: modal._create_support.get("gh") == ("", "unsupported")
        )
        modal._inputs["gh"] = inputs()
        modal._maybe_discover_create_support("gh")
        await wait_for(
            pilot, lambda: modal.query_one(NewProjectSource).create_row is not None
        )
        assert calls == ["", "bbugyi200"]


async def test_namespace_change_during_discovery_triggers_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def describe(_workflow_type: str, namespace: str) -> RepoCreationForm | None:
        calls.append(namespace)
        if namespace == "":
            started.set()
            assert release.wait(timeout=10)
            return None
        return replace(repo_form(), namespace=namespace)

    monkeypatch.setattr(workspace_provider, "describe_repo_creation", describe)
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs(account="", owners=[])},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await wait_for(pilot, started.is_set)
        modal._inputs["gh"] = inputs()
        release.set()
        await wait_for(
            pilot, lambda: modal.query_one(NewProjectSource).create_row is not None
        )
        assert calls == ["", "bbugyi200"]


async def test_failed_provider_load_skips_synthetic_error_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _describe_calls(monkeypatch, calls=calls)
    monkeypatch.setattr(
        workspace_provider,
        "get_all_workflow_metadata",
        lambda: (provider("gh", "GitHub"),),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_modal_providers.load_preferences",
        lambda: Preferences(last_provider="gh"),
    )

    def fail_load(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_modal_providers.load_candidate_inputs",
        fail_load,
    )
    modal = NewProjectModal()
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await wait_for(
            pilot,
            lambda: bool(
                modal._inputs.get("gh")
                and modal._inputs["gh"].owners
                and modal._inputs["gh"].owners[0].name == "provider"
            ),
        )
        await pilot.pause(0.1)
        assert "provider" not in calls


async def test_unavailable_create_notifies_only_from_list_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _describe_calls(monkeypatch, calls=calls, result=None)
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs(account="", owners=[])},
        preferences=Preferences(last_provider="gh"),
    )
    notices: list[tuple[str, str]] = []
    modal.notify = lambda message, **kwargs: notices.append(  # type: ignore[method-assign]
        (message, kwargs.get("severity", "information"))
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await wait_for(
            pilot, lambda: modal._create_support.get("gh") == ("", "unsupported")
        )
        modal.query_one("#new-project-source-list", OptionList).focus()
        await pilot.press("n")
        await wait_for(pilot, lambda: bool(notices))
        assert modal._state.stage == "source"
        assert "press R to retry" in notices[-1][0]
        assert notices[-1][1] == "warning"

        modal.query_one("#new-project-filter", Input).focus()
        await pilot.press("n")
        assert len(notices) == 1
        assert modal.query_one("#new-project-filter", Input).value == "n"
