"""Create-stage async result and cancellation tests."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase import workspace_provider
from sase.ace.testing.wait import wait_for
from sase.workspace_provider._hookspec import (
    RepoCreationField,
    RepoCreationForm,
)
from ._new_project_create_helpers import (
    enter_create_stage,
    make_modal,
    parsed,
    probe,
    repo_form,
)


class _BareGitApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("host")


async def test_late_form_completion_keeps_current_owner_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from textual.widgets import Input

    gates: dict[str, threading.Event] = {}
    describe_calls: list[str] = []

    def _gated_describe(workflow_type: str, namespace: str) -> RepoCreationForm | None:
        from dataclasses import replace as _replace

        gate = gates.setdefault(namespace, threading.Event())
        describe_calls.append(namespace)
        assert gate.wait(timeout=10)
        return _replace(repo_form(), namespace=namespace)

    app, modal, _, _ = make_modal(monkeypatch)
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parsed)
    monkeypatch.setattr(workspace_provider, "describe_repo_creation", _gated_describe)
    monkeypatch.setattr(
        workspace_provider, "probe_repo", lambda workflow_type, ref: probe("not_found")
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        # Source-level create-support discovery describes the account namespace
        # on mount; drain it so the assertions below cover the create flow.
        await wait_for(pilot, lambda: "bbugyi200" in describe_calls)
        describe_calls.clear()
        modal.enter_create_configure(
            workflow_type="gh",
            owners=["sase-org", "bbugyi200"],
            account="bbugyi200",
        )
        await wait_for(pilot, lambda: describe_calls == ["sase-org"])
        assert describe_calls == ["sase-org"]
        name = modal.query_one("#new-project-create-name", Input)
        name.value = "alpha"
        await wait_for(
            pilot,
            lambda: (
                modal._state.create_draft is not None
                and modal._state.create_draft.owner == "sase-org"
                and modal._state.create_draft.raw_name == "alpha"
            ),
        )
        modal._on_create_owner_selected("bbugyi200")
        await wait_for(pilot, lambda: describe_calls == ["sase-org", "bbugyi200"])
        assert describe_calls == ["sase-org", "bbugyi200"]

        name.value = "beta"
        await wait_for(
            pilot,
            lambda: (
                modal._state.create_draft is not None
                and modal._state.create_draft.owner == "bbugyi200"
                and modal._state.create_draft.raw_name == "beta"
            ),
        )
        gates["bbugyi200"].set()
        await wait_for(
            pilot,
            lambda: (
                modal._create_form is not None
                and modal._create_form.namespace == "bbugyi200"
                and modal._state.create_draft is not None
                and modal._state.create_draft.owner == "bbugyi200"
                and modal._state.create_draft.raw_name == "beta"
            ),
        )
        gates["sase-org"].set()
        await wait_for(
            pilot,
            lambda: (
                not any(
                    task.get_name() == "new-project-create-form:gh:sase-org"
                    for task in getattr(modal, "_new_project_create_tasks", ())
                )
            ),
        )
        assert modal._create_form is not None
        assert modal._create_form.namespace == "bbugyi200"
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == "bbugyi200"
        assert modal._state.create_draft.raw_name == "beta"
        assert name.value == "beta"


async def test_stale_probe_and_preview_results_are_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, _, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "settled"
        await wait_for(
            pilot,
            lambda: (
                modal._create_availability.status == "available"
                and modal._create_plan_current()
            ),
        )
        settled_plan = dict(modal._create_plan)
        assert settled_plan
        draft = modal._state.create_draft
        assert draft is not None
        stale_generation = modal._create_generation - 1
        await modal._run_create_check(
            generation=stale_generation,
            workflow_type="gh",
            owner="sase-org",
            identity=modal._create_identity,
            draft=draft,
            cached_probe=probe("found"),
            provider_display="GitHub",
            storage_policy="",
        )
        await pilot.pause()
        assert modal._create_availability.status == "available"
        assert modal._create_plan == settled_plan


async def test_back_cancels_pending_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    from sase.ace.tui.modals.new_project_create import NewProjectCreateConfigure

    app, modal, probe_calls, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        widget = modal.query_one(NewProjectCreateConfigure)
        modal.query_one("#new-project-create-name", Input).value = "typed"
        # No awaits here: the debounce cannot fire without loop iterations,
        # so cancellation below deterministically wins the race.
        generation = modal._create_generation
        modal.action_cancel()
        assert modal._state.stage == "create-configure"
        modal.action_cancel()
        assert widget._check_timer is None
        await pilot.pause()
        assert modal._state.stage == "source"
        assert modal._state.wizard_mode == "add"
        assert modal._create_generation > generation
        assert "sase-org/typed" not in probe_calls
        modal.enter_create_configure(
            workflow_type="gh",
            owners=["sase-org"],
            account="",
        )
        await wait_for(pilot, lambda: "sase-org/typed" in probe_calls)


async def test_unmount_cancels_pending_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.ace.tui.modals.new_project_create import NewProjectCreateConfigure

    app, modal, _, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        widget = modal.query_one(NewProjectCreateConfigure)
        widget.request_check()
        assert widget._check_timer is not None
        widget.on_unmount()
        assert widget._check_timer is None
        assert widget._check_due is False


async def test_paste_in_create_stage_leaves_source_filter_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace as _NS

    from textual.widgets import Input

    app, modal, _, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        source_filter = modal.query_one("#new-project-filter", Input)
        before = source_filter.value
        event = _NS(stop=lambda: None, prevent_default=lambda: None, text="pasted")
        modal._paste_anywhere(event)  # type: ignore[arg-type]
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == before


async def test_bare_git_entry_supports_empty_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.workspace_provider import WorkflowMetadata

    bare_form = RepoCreationForm(
        workflow_type="git",
        namespace="",
        fields=(
            RepoCreationField(
                name="bare_dir", label="Bare repository path", kind="line"
            ),
        ),
        can_create=True,
    )
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parsed)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda *args: bare_form
    )
    monkeypatch.setattr(
        workspace_provider, "probe_repo", lambda workflow_type, ref: probe("not_found")
    )
    from sase.ace.tui.modals.new_project_modal import NewProjectModal
    from sase.project_onboarding import Preferences

    modal = NewProjectModal(
        provider_metadata=(
            WorkflowMetadata(
                workflow_type="git",
                ref_pattern=r"^$",
                display_name="Bare git",
                pre_allocated_env_prefix="",
            ),
        ),
        candidate_inputs={},
        preferences=Preferences(),
    )
    app = _BareGitApp()
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal.enter_create_configure(workflow_type="git", owners=[])
        await wait_for(pilot, lambda: modal._create_form_status == "ready")
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == ""
        assert modal._state.create_draft.visibility == ""
        assert modal._create_form_status == "ready"
        assert not modal.query_one("#new-project-create-visibility-row").display
