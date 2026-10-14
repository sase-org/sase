"""Source-stage modal flow tests for the New Project wizard."""

from __future__ import annotations

from types import SimpleNamespace

from textual import events
from textual.widgets import Input, OptionList, Static

from sase import workspace_provider
from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_source import NewProjectSource
from sase.ace.tui.modals.new_project_source_model import create_source_row
from sase.project_onboarding import CandidateInputs, Preferences
from tests.ace.tui.modals._new_project_source_helpers import (
    ModalApp,
    inputs,
    parsed,
    provider,
)


def _patch_list_basics(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            parsed(workflow_type, text) if text == "sase-org/new" else None
        ),
    )
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: object()
    )


def _stub_provider_hooks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Keep installed provider plugins out of the modal's off-thread discovery.

    A real plugin can answer ``describe_repo_creation`` with a form, which pins
    a Create row that takes the highlight from the row under test.
    """
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    monkeypatch.setattr(workspace_provider, "probe_repo", lambda _wt, _ref: None)


async def _wait_for_create_row(modal: NewProjectModal, pilot) -> None:  # type: ignore[no-untyped-def]
    from sase.ace.testing.wait import wait_for

    source = modal.query_one(NewProjectSource)
    await wait_for(pilot, lambda: source.create_row is not None)


async def test_filter_and_enter_advance_the_modal_without_an_entry_point(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _stub_provider_hooks(monkeypatch)
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            parsed(workflow_type, text) if text == "sase-org/new" else None
        ),
    )
    metadata = (provider("gh", "GitHub"),)
    modal = NewProjectModal(
        provider_metadata=metadata,
        candidate_inputs={"gh": inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        filter_input = modal.query_one("#new-project-filter", Input)
        source = modal.query_one(NewProjectSource)
        filter_input.focus()
        await pilot.press("s", "a", "s", "e", "-", "o", "r", "g", "/", "n", "e", "w")
        await wait_for(
            pilot,
            lambda: (
                source._filter_text == "sase-org/new"
                and "sase-org/new"
                in modal.query_one("#new-project-source-detail", Static).render().plain
            ),
        )
        assert modal.query_one("#new-project-filter", Input).value == "sase-org/new"
        assert (
            "sase-org/new"
            in modal.query_one("#new-project-source-detail", Static).render().plain
        )

        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: (
                modal._state.stage == "configure"
                and modal.query_one("#new-project-stepper", Static)
                .render()
                .plain.startswith("✓ Source")
            ),
        )


async def test_filter_discards_pending_probe_for_previous_highlight(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from sase.ace.tui.util.debounce import DetailPanelDebouncer

    _stub_provider_hooks(monkeypatch)
    scheduled: list[object] = []
    monkeypatch.setattr(
        DetailPanelDebouncer,
        "schedule",
        lambda _self, callback: scheduled.append(callback),
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
        assert source._detail_debouncer is not None
        source._detail_debouncer.cancel()
        scheduled.clear()
        previous = source._highlighted_row()
        assert previous is not None
        source._select_detail(previous)
        assert scheduled
        stale_probe = scheduled[-1]
        started: list[str] = []
        monkeypatch.setattr(
            source,
            "_start_probe",
            lambda ref, _key: started.append(ref),
        )

        modal.query_one("#new-project-filter", Input).value = "no-such-repo"
        await wait_for(pilot, lambda: source._highlighted_row() is None)
        stale_probe()  # type: ignore[operator]

        assert started == []


async def test_tab_selection_persists_last_provider_off_thread(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    import json

    _stub_provider_hooks(monkeypatch)
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    metadata = (
        provider("gh", "GitHub"),
        provider("git", "Git (bare)"),
    )
    modal = NewProjectModal(provider_metadata=metadata, preferences=Preferences())
    modal._provided_inputs.update(
        {
            "gh": inputs(),
            "git": CandidateInputs("git", "Git (bare)", ""),
        }
    )
    app = ModalApp()
    preferences_path = tmp_path / "project_onboarding" / "preferences.json"
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal.select_provider("git")
        await wait_for(
            pilot,
            lambda: (
                preferences_path.is_file()
                and json.loads(preferences_path.read_text())["last_provider"] == "git"
            ),
        )

    payload = json.loads(preferences_path.read_text())
    assert payload["last_provider"] == "git"


async def test_discovery_pins_create_row_and_n_opens_create(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_list_basics(monkeypatch)
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _wait_for_create_row(modal, pilot)
        source = modal.query_one(NewProjectSource)
        assert source.create_row is not None
        assert "Create a new GitHub repository" in source.create_row.display
        source.focus_list()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert modal._state.stage == "create-configure"
        assert modal._state.wizard_mode == "create"


async def test_n_in_filter_stays_text(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_list_basics(monkeypatch)
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _wait_for_create_row(modal, pilot)
        modal.query_one("#new-project-filter", Input).focus()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == "n"
        assert modal._state.stage == "source"


async def test_loading_row_cannot_be_chosen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
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
        source.set_inputs(inputs(), pending_owners=frozenset({"sase-org"}))
        await pilot.pause()
        options = source.query_one(OptionList)
        fetching = next(row for row in source._rows.values() if row.is_loading)
        fetching_index = next(
            index
            for index in range(options.option_count)
            if str(options.get_option_at_index(index).id or "") == fetching.row_id
        )
        assert options.get_option_at_index(fetching_index).disabled
        # Even a highlight resting on a loading row must not advance the wizard.
        monkeypatch.setattr(source, "_highlighted_row", lambda: fetching)
        source.choose_highlighted()
        await pilot.pause()
        assert modal._state.stage == "source"
        assert modal._state.selected is None
        source._row_selected(
            SimpleNamespace(option=SimpleNamespace(id=fetching.row_id))
        )
        await pilot.pause()
        assert modal._state.stage == "source"
        assert modal._state.selected is None


async def test_bracketed_paste_focuses_filter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            parsed(workflow_type, text) if text == "sase-org/new" else None
        ),
    )
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
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
        assert app.screen.focused is modal.query_one(
            "#new-project-source-list", OptionList
        )
        modal.post_message(events.Paste("sase-org/new"))
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == "sase-org/new"
        assert app.screen.focused is modal.query_one("#new-project-filter", Input)


async def test_provider_selection_write_preserves_owner_prefs(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    import json

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    prefs_dir = tmp_path / "project_onboarding"
    prefs_dir.mkdir(parents=True)
    (prefs_dir / "preferences.json").write_text(
        json.dumps({"last_provider": "gh", "last_owner": {"gh": "sase-org"}})
    )
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={"gh": inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    await modal._save_provider_preference("git")
    payload = json.loads((prefs_dir / "preferences.json").read_text())
    assert payload["last_provider"] == "git"
    assert payload["last_owner"] == {"gh": "sase-org"}


async def test_no_owners_card_shows_with_create_row(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(provider("gh", "GitHub"),),
        candidate_inputs={
            "gh": CandidateInputs(workflow_type="gh", display="GitHub", account="")
        },
        preferences=Preferences(last_provider="gh"),
    )
    app = ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        source = modal.query_one(NewProjectSource)
        source.set_create_row(create_source_row("GitHub", "gh"))
        await pilot.pause()
        assert source.create_row is not None
        detail = modal.query_one("#new-project-source-detail", Static).render().plain
        assert "No GitHub owners yet" in detail
        assert "github_orgs" in detail
