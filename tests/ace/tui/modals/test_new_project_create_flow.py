"""Create-stage modal behavior tests."""

from __future__ import annotations

import pytest

from sase.ace.testing.wait import wait_for
from ._new_project_create_helpers import enter_create_stage, make_modal


async def test_current_project_context_defaults_provider_and_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.new_project_source import NewProjectSource
    from sase.project_onboarding import OwnerResult, Preferences
    from tests.ace.tui.modals._new_project_source_helpers import inputs as source_inputs

    inputs = source_inputs(
        account="sase-org",
        owners=[OwnerResult(name="sase-org"), OwnerResult(name="bbugyi200")],
    )
    app, modal, _probes, _describes = make_modal(
        monkeypatch,
        current_workflow_type="gh",
        current_project_owner="bbugyi200",
        candidate_inputs={"gh": inputs},
        preferences=Preferences(last_owner={"gh": "missing"}),
    )

    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        source = modal.query_one(NewProjectSource)
        await wait_for(pilot, lambda: source.create_row is not None)

        assert modal._state.workflow_type == "gh"
        assert source.create_row is not None
        modal._enter_create_from_source(source.create_row)
        await wait_for(pilot, lambda: modal._state.stage == "create-configure")

        assert modal._state.stage == "create-configure"
        assert "bbugyi200" in modal._create_drafts


async def test_typing_starts_no_sync_probe_and_settles_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, probe_calls, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal.enter_create_configure(
            workflow_type="gh",
            owners=["sase-org"],
            account="",
        )
        # The default name's probe is stale by the time the name field is ready,
        # but finish it before isolating calls for the typed name.
        await wait_for(pilot, lambda: probe_calls == ["sase-org/forge"])
        # Source detail probes are out of scope; isolate create-flow probes.
        probe_calls.clear()
        name = modal.query_one("#new-project-create-name", Input)
        # No awaits while typing: delivery is queued, so the debounce cannot
        # fire mid-word and the settled probe below is the only one.
        for character in ("n", "e", "w"):
            name.insert_text_at_cursor(character)
        assert probe_calls == []
        await wait_for(
            pilot,
            lambda: (
                probe_calls == ["sase-org/new"]
                and modal._create_availability.status == "available"
            ),
        )
        assert probe_calls == ["sase-org/new"]
        assert modal._create_availability.status == "available"


async def test_project_name_follows_until_explicitly_edited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, _, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        name = modal.query_one("#new-project-create-name", Input)
        project = modal.query_one("#new-project-create-project-name", Input)
        name.value = "alpha"
        await pilot.pause(0.6)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.project.name == "alpha"
        assert project.value == "alpha"
        project.value = "custom"
        await pilot.pause(0.6)
        assert modal._state.create_draft.project_name_edited
        name.value = "beta"
        await pilot.pause(0.6)
        assert modal._state.create_draft.project.name == "custom"
        assert project.value == "custom"


async def test_owner_switch_preserves_per_owner_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, _, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == "sase-org"
        assert modal._state.create_draft.visibility == "public"
        modal.query_one("#new-project-create-name", Input).value = "alpha"
        await pilot.pause(0.6)
        modal._on_create_owner_selected("bbugyi200")
        await pilot.pause(0.6)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == "bbugyi200"
        assert modal._state.create_draft.raw_name == ""
        modal._on_create_owner_selected("sase-org")
        await pilot.pause(0.6)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.raw_name == "alpha"


async def test_taken_name_offers_explicit_add_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Button, Input

    app, modal, _, _ = make_modal(monkeypatch, probe_status="found")
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "taken"
        await pilot.pause(0.6)
        assert modal._create_availability.status == "taken"
        add_instead = modal.query_one("#new-project-create-add-instead", Button)
        assert add_instead.display
        assert modal.query_one("#new-project-create-review", Button).disabled
        name = modal.query_one("#new-project-create-name", Input)
        name.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert modal._state.wizard_mode == "add"
        assert modal._state.draft is not None
        assert modal._state.draft.name == "taken"


async def test_enter_with_available_name_creates_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, _, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "fresh"
        await pilot.pause(0.6)
        assert modal._create_availability.status == "available"
        name = modal.query_one("#new-project-create-name", Input)
        name.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert modal._state.stage == "create-configure"
        assert modal.create_review_intent() is None


async def test_probe_failure_never_becomes_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Button, Input, Static

    app, modal, _, _ = make_modal(
        monkeypatch, probe_status=RuntimeError("permission denied")
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "new"
        await pilot.pause(0.6)
        assert modal._create_availability.status == "unavailable"
        assert "permission denied" in modal._create_availability.reason
        assert modal.query_one("#new-project-create-review", Button).disabled
        availability = modal.query_one("#new-project-create-availability", Static)
        assert "permission denied" in availability.render().plain


async def test_missing_form_leaves_no_confirmable_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Button, Input, Static

    app, modal, _, _ = make_modal(monkeypatch, form=None)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "new"
        await pilot.pause(0.6)
        assert modal._create_form_status == "unavailable"
        assert modal.query_one("#new-project-create-review", Button).disabled
        status = modal.query_one("#new-project-create-status", Static)
        assert "unavailable" in status.render().plain


async def test_name_collision_blocks_review_but_occupied_checkout_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Button, Input

    app, modal, _, _ = make_modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "brandnew"
        modal.query_one(
            "#new-project-create-project-name", Input
        ).value = "existing-project"
        await pilot.pause(0.8)
        assert modal.query_one("#new-project-create-review", Button).disabled
        assert "existing-project" in (modal._create_identity_reason() or "")
