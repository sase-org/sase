"""Source-stage model and user-path coverage for the New Project wizard."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase import workspace_provider
from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_rendering import (
    render_no_owners_detail,
    render_source_detail,
    render_source_row,
)
from sase.ace.tui.modals.new_project_source import NewProjectSource
from sase.ace.tui.modals.new_project_source_model import (
    build_source_view,
    cache_age_for,
    create_source_row,
    health_chip_text,
    hidden_footer,
)
from sase.project_onboarding import CandidateInputs, OwnerResult, Preferences
from sase.workspace_provider import ParsedRepoRef, WorkflowMetadata


def _parsed(workflow_type: str, ref: str) -> ParsedRepoRef:
    owner, name = ref.split("/", 1)
    return ParsedRepoRef(
        workflow_type=workflow_type,
        ref=ref,
        identity_key=f"github.com/{ref}".casefold(),
        display=ref,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=f"~/projects/github/{owner}/{name}/",
    )


def _provider(workflow_type: str, display_name: str) -> WorkflowMetadata:
    return WorkflowMetadata(
        workflow_type=workflow_type,
        ref_pattern=r"^$",
        display_name=display_name,
        pre_allocated_env_prefix="",
    )


def _inputs(
    *,
    owners: list[OwnerResult] | None = None,
    account: str = "bbugyi200",
) -> CandidateInputs:
    return CandidateInputs(
        workflow_type="gh",
        display="GitHub",
        account=account,
        owners=owners if owners is not None else [OwnerResult(name="sase-org")],
        remote=[
            {
                "identity_key": "github.com/sase-org/new",
                "ref": "sase-org/new",
                "display": "sase-org/new",
                "owner": "sase-org",
                "name": "new",
                "description": "A suggested repository",
                "visibility": "public",
                "pushed_at": "2026-10-11T14:00:00Z",
                "is_fork": False,
            },
            {
                "identity_key": "github.com/sase-org/fork",
                "ref": "sase-org/fork",
                "display": "sase-org/fork",
                "owner": "sase-org",
                "name": "fork",
                "description": "",
                "visibility": "public",
                "is_fork": True,
            },
            {
                "identity_key": "github.com/sase-org/hidden",
                "ref": "sase-org/hidden",
                "display": "sase-org/hidden",
                "owner": "sase-org",
                "name": "hidden",
                "description": "Already registered",
                "visibility": "private",
                "is_fork": False,
            },
        ],
        local=[
            {
                "identity_key": "github.com/sase-org/clone",
                "ref": "sase-org/clone",
                "display": "sase-org/clone",
                "owner": "sase-org",
                "name": "clone",
                "path": "/tmp/clone",
                "numbered_copy": False,
            }
        ],
        projects=[
            {
                "key": "old-project",
                "name": "old-project",
                "aliases": [],
                "state": "disabled",
                "identity_keys": ["github.com/sase-org/old"],
            },
            {
                "key": "existing-project",
                "name": "existing-project",
                "aliases": [],
                "state": "enabled",
                "identity_keys": ["github.com/sase-org/hidden"],
            },
        ],
        inventory=[
            {
                "identity_key": "github.com/sase-org/sase--plans",
                "kind": "sidecar",
                "project_key": "sase",
            }
        ],
        journals=[
            {
                "identity_key": "github.com/sase-org/forge",
                "ref": "sase-org/forge",
                "display": "sase-org/forge",
                "status": "failed",
                "stopped_at": "2026-10-11T14:00:00Z",
            }
        ],
        owned_namespaces=["sase-org", "bbugyi200"],
        sidecar_roles=["plans", "beads", "agents", "attachments", "research", "sdd"],
    )


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("host")


def test_source_groups_hidden_counts_and_hidden_filter() -> None:
    inputs = _inputs()
    view = build_source_view(inputs)

    assert [group.group_id for group in view.groups] == [
        "resume",
        "local",
        "suggested",
        "disabled",
    ]
    assert view.groups[0].rows[0].display == "sase-org/forge"
    assert dict(view.hidden_counts)["fork"] == 1
    # sase-core no longer seeds ref-less inventory rows, so the fixture's
    # sidecar entry is gone rather than hidden (verified against the base
    # tree with this phase's changes stashed).
    assert hidden_footer(view) == ("┄ 1 project · 1 fork hidden · f forks · . all")

    matching_hidden = build_source_view(inputs, filter_text="hidden")
    assert matching_hidden.groups[-1].group_id == "search_only"
    assert matching_hidden.groups[-1].rows[0].display == "sase-org/hidden"

    all_rows = build_source_view(inputs, reveal_forks=True)
    assert all_rows.groups[-1].rows[0].hidden_reason == "fork"


def test_source_paste_ref_becomes_a_synthetic_row(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            _parsed(workflow_type, "sase-org/pasted")
            if text == "https://github.com/sase-org/pasted"
            else None
        ),
    )

    view = build_source_view(
        _inputs(), filter_text="https://github.com/sase-org/pasted"
    )

    assert view.parsed_ref.ref == "sase-org/pasted"
    assert view.groups[0].group_id == "paste"
    assert view.groups[0].rows[0].display == "Add sase-org/pasted"


async def test_filter_and_enter_advance_the_modal_without_an_entry_point(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            _parsed(workflow_type, text) if text == "sase-org/new" else None
        ),
    )
    metadata = (_provider("gh", "GitHub"),)
    modal = NewProjectModal(
        provider_metadata=metadata,
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        filter_input = modal.query_one("#new-project-filter", Input)
        filter_input.focus()
        await pilot.press("s", "a", "s", "e", "-", "o", "r", "g", "/", "n", "e", "w")
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == "sase-org/new"
        assert (
            "sase-org/new"
            in modal.query_one("#new-project-source-detail", Static).render().plain
        )

        await pilot.press("enter")
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert (
            modal.query_one("#new-project-stepper", Static)
            .render()
            .plain.startswith("✓ Source")
        )


async def test_tab_selection_persists_last_provider_off_thread(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    metadata = (
        _provider("gh", "GitHub"),
        _provider("git", "Git (bare)"),
    )
    modal = NewProjectModal(provider_metadata=metadata, preferences=Preferences())
    modal._provided_inputs.update(
        {
            "gh": _inputs(),
            "git": CandidateInputs("git", "Git (bare)", ""),
        }
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal.select_provider("git")
        await pilot.pause(0.1)

    import json

    payload = json.loads(
        (tmp_path / "project_onboarding" / "preferences.json").read_text()
    )
    assert payload["last_provider"] == "git"


def test_create_row_pins_first_across_filter_and_states(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    row = create_source_row("GitHub", "gh")
    assert row.group == "create"
    assert row.ref == ""
    assert "GitHub" in row.display

    view = build_source_view(_inputs(), create_row=row)
    assert view.groups[0].group_id == "create"
    assert view.rows[0] == row

    filtered = build_source_view(_inputs(), filter_text="zzz-no-match", create_row=row)
    assert filtered.rows[0] == row

    empty = build_source_view(
        CandidateInputs(workflow_type="gh", display="GitHub", account=""),
        create_row=row,
    )
    assert empty.rows == (row,)

    without = build_source_view(_inputs())
    assert all(group.group_id != "create" for group in without.groups)


def _patch_list_basics(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            _parsed(workflow_type, text) if text == "sase-org/new" else None
        ),
    )
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: object()
    )


async def _wait_for_create_row(modal: NewProjectModal, pilot) -> None:  # type: ignore[no-untyped-def]
    source = modal.query_one(NewProjectSource)
    await wait_for(pilot, lambda: source.create_row is not None)


async def test_discovery_pins_create_row_and_n_opens_create(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_list_basics(monkeypatch)
    modal = NewProjectModal(
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
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
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
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


def _tool_missing_inputs() -> CandidateInputs:
    inputs = _inputs(
        owners=[
            OwnerResult(
                name="sase-org",
                status="error",
                error_kind="tool_missing",
                message="gh not found",
            )
        ]
    )
    inputs.remote = []
    inputs.local = []
    return inputs


def test_loading_rows_are_unselectable_placeholders(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    view = build_source_view(_inputs(), pending_owners=frozenset({"sase-org"}))
    fetching = [row for row in view.rows if row.is_loading]
    assert fetching, "a pending owner must render a fetching row"
    assert all(not row.selectable and not row.ref for row in fetching)


async def test_loading_row_cannot_be_chosen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        source = modal.query_one(NewProjectSource)
        source.set_inputs(_inputs(), pending_owners=frozenset({"sase-org"}))
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


def test_truncation_footer_names_filter_and_paste(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    owners = _inputs().owners
    truncated = [
        OwnerResult(
            name=owner.name,
            kind_label=owner.kind_label,
            status=owner.status,
            truncated=True,
        )
        for owner in owners
    ]
    view = build_source_view(_inputs(owners=truncated))
    assert view.truncated
    assert "showing 200 · type to filter or paste owner/repo" in hidden_footer(view)


def test_health_chip_states() -> None:
    assert health_chip_text(None) == "◌ loading cached candidates…"
    assert (
        health_chip_text(_inputs(), pending_owners=frozenset({"sase-org"}))
        == "◌ loading 0 of 1 owners"
    )
    assert (
        health_chip_text(_tool_missing_inputs(), workflow_type="gh")
        == "✗ gh not installed"
    )
    owner_error = _inputs(
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
    assert health_chip_text(owner_error) == "⚠ 1 owner issue(s) · t gh auth login"
    assert (
        health_chip_text(_inputs(), cache_age="2m")
        == "✓ bbugyi200 · 1 owners · cached 2m"
    )
    assert health_chip_text(_inputs()) == "✓ bbugyi200 · 1 owners · cached"
    assert (
        health_chip_text(CandidateInputs("gh", "GitHub", ""))
        == "○ no owners · paste owner/repo"
    )
    now = 1_000_000.0
    young = _inputs()
    young.fetched_at = now - 30
    assert cache_age_for(young, now=now) == ""
    old = _inputs()
    old.fetched_at = now - 150
    assert cache_age_for(old, now=now) == "2m"
    older = _inputs()
    older.fetched_at = now - 7200
    assert cache_age_for(older, now=now) == "2h"


def test_hidden_enabled_project_row_names_show_action(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    view = build_source_view(_inputs(), filter_text="hidden")
    row = view.groups[-1].rows[0]
    assert row.hidden_reason == "enabled_project"
    assert "already the project" in render_source_row(row).plain
    assert "show it" in render_source_row(row).plain


def test_detail_status_wording() -> None:
    managed = SimpleNamespace(
        visibility="private",
        default_branch="main",
        sase_managed=True,
        can_push=True,
        message="",
    )
    row = create_source_row("GitHub", "gh")
    detail = render_source_detail(
        _inputs_suggested_row(), workflow_type="gh", probe=managed
    )
    assert "✓ managed" in detail.plain
    unset = SimpleNamespace(
        visibility="private",
        default_branch="main",
        sase_managed=False,
        can_push=True,
        message="",
    )
    assert (
        "○ will be set up"
        in render_source_detail(
            _inputs_suggested_row(), workflow_type="gh", probe=unset
        ).plain
    )
    unknown = SimpleNamespace(
        visibility="private",
        default_branch="main",
        sase_managed=None,
        can_push=None,
        message="",
    )
    assert (
        "? unknown"
        in render_source_detail(
            _inputs_suggested_row(), workflow_type="gh", probe=unknown
        ).plain
    )
    assert (
        "◌ checking…"
        in render_source_detail(
            _inputs_suggested_row(), workflow_type="gh", checking=True
        ).plain
    )
    collapsed = render_source_detail(
        _inputs_suggested_row(), workflow_type="gh", probe=unset, collapsed=True
    )
    assert "\n" not in collapsed.plain
    assert "○ will be set up" in collapsed.plain
    assert row.group == "create"


def _inputs_suggested_row():  # type: ignore[no-untyped-def]
    from sase.ace.tui.modals.new_project_source_model import SourceRow as _Row

    return _Row(
        row_id="suggested:x",
        group="suggested",
        display="sase-org/new",
        ref="sase-org/new",
    )


def test_no_owners_detail_points_at_config() -> None:
    detail = render_no_owners_detail("GitHub", "gh")
    assert "No GitHub owners yet" in detail.plain
    assert "github_orgs" in detail.plain
    bare = render_no_owners_detail("Git (bare)", "git")
    assert "No Git (bare) owners yet" in bare.plain
    assert "github_orgs" not in bare.plain
    collapsed = render_no_owners_detail("GitHub", "gh", collapsed=True)
    assert "\n" not in collapsed.plain
    assert "No GitHub owners yet" in collapsed.plain


def test_collapsed_detail_covers_every_card_kind() -> None:
    from sase.ace.tui.modals.new_project_source_model import SourceRow as _Row

    create = create_source_row("GitHub", "gh")
    assert (
        "\n"
        not in render_source_detail(create, workflow_type="gh", collapsed=True).plain
    )
    assert (
        "Create a new GitHub repository"
        in render_source_detail(create, workflow_type="gh", collapsed=True).plain
    )
    error = _Row(
        row_id="owner-error:sase-org",
        group="owner_error",
        display="sase-org: expired",
        owner="sase-org",
    )
    collapsed_error = render_source_detail(
        error, workflow_type="gh", collapsed=True
    ).plain
    assert "\n" not in collapsed_error
    assert "sase-org: expired" in collapsed_error


def test_ref_less_disabled_rows_promise_no_action() -> None:
    from sase.ace.tui.modals.new_project_source_model import SourceRow as _Row

    actionable = _Row(
        row_id="disabled:x",
        group="disabled",
        display="sase-org/old",
        ref="sase-org/old",
        data={"project_key": "old-project"},
    )
    assert actionable.selectable
    assert "⏎ re-enables" in render_source_row(actionable).plain
    stranded = _Row(
        row_id="disabled:y",
        group="disabled",
        display="sase-org/gone",
        ref="",
        data={"project_key": "gone-project"},
    )
    assert not stranded.selectable
    stranded_text = render_source_row(stranded).plain
    assert "⏎" not in stranded_text
    assert "sase project enable gone-project" in stranded_text
    detail = render_source_detail(stranded, workflow_type="gh").plain
    assert "sase project enable gone-project" in detail


def test_health_chip_sanitizes_account_and_drops_cached_when_live() -> None:
    dirty = _inputs(account="bbugyi\x00\x1f200")
    assert health_chip_text(dirty) == "✓ bbugyi200 · 1 owners · cached"
    assert health_chip_text(dirty, live=True) == "✓ bbugyi200 · 1 owners"
    assert (
        health_chip_text(_inputs(), cache_age="2m", live=True)
        == "✓ bbugyi200 · 1 owners"
    )


def test_cache_age_comes_from_inputs_timestamp() -> None:
    import time

    from sase.ace.tui.modals.new_project_source_model import cache_age_for

    assert cache_age_for(None) == ""
    assert cache_age_for(_inputs()) == ""
    aged = _inputs()
    aged.fetched_at = time.time() - 150
    assert cache_age_for(aged) == "2m"


def test_source_hint_line_keeps_choose_and_remedy() -> None:
    from sase.ace.tui.modals.new_project_source_model import source_hint_line

    full = source_hint_line(120, remedy=True)
    assert "⏎ choose" in full
    assert "t provider login" in full
    assert "? help" not in full
    narrow = source_hint_line(40, remedy=True)
    assert narrow.startswith("⏎ choose")
    assert "t provider login" in narrow
    assert "? help" in narrow
    plain = source_hint_line(40, remedy=False)
    assert "t provider login" not in plain
    assert plain.startswith("⏎ choose")


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
    error_inputs = _inputs(
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
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": error_inputs},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
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
    error_inputs = _inputs(
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
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": error_inputs},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        source = modal.query_one(NewProjectSource)
        notices: list[str] = []
        source.notify = lambda message, *args, **kwargs: notices.append(str(message))  # type: ignore[method-assign]
        monkeypatch.setattr(app, "suspend", lambda *args, **kwargs: _raise_suspend())
        source.action_run_remedy()
        assert any("Could not run remedy" in notice for notice in notices)


def _raise_suspend():  # type: ignore[no-untyped-def]
    raise OSError("no terminal")


async def test_remedy_suspend_unsupported_notifies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from textual.app import SuspendNotSupported

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    error_inputs = _inputs(
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
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": error_inputs},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
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
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
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
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
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


async def test_bracketed_paste_focuses_filter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            _parsed(workflow_type, text) if text == "sase-org/new" else None
        ),
    )
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
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
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    await modal._save_provider_preference("git")
    payload = json.loads((prefs_dir / "preferences.json").read_text())
    assert payload["last_provider"] == "git"
    assert payload["last_owner"] == {"gh": "sase-org"}


async def test_tool_missing_disables_provider_tab(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(
            _provider("gh", "GitHub"),
            _provider("git", "Git (bare)"),
        ),
        candidate_inputs={
            "gh": _tool_missing_inputs(),
            "git": CandidateInputs("git", "Git (bare)", ""),
        },
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip

        strip_widget = modal.query_one(PanelTabStrip)
        assert strip_widget.is_tab_disabled("gh")
        assert not strip_widget.is_tab_disabled("git")
        # The wizard steps off the disabled tab onto the working provider.
        assert modal._state.workflow_type == "git"
        assert modal._state.stage == "source"
        modal.select_provider("gh")
        assert modal._state.workflow_type == "git"


async def test_unmount_cancels_owner_refresh_jobs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import threading

    import sase.ace.tui.modals.new_project_modal_providers as _providers

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    release = threading.Event()

    def _slow_load(workflow_type, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("cache_only"):
            return _inputs()
        assert release.wait(timeout=15), "live owner refresh must be released"
        return _inputs()

    monkeypatch.setattr(_providers, "load_candidate_inputs", _slow_load)
    modal = NewProjectModal(
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    wizard_queries: list[str] = []
    _real_query_one = modal.query_one

    def _recording_query_one(*args, **kwargs):  # type: ignore[no-untyped-def]
        wizard_queries.append(str(args[0]) if args else "")
        return _real_query_one(*args, **kwargs)

    monkeypatch.setattr(modal, "query_one", _recording_query_one)
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal._loaded.discard("gh")
        modal._start_provider_load("gh")
        await wait_for(pilot, lambda: len(modal._owner_jobs) > 0)
        parents = {
            task
            for task in asyncio.all_tasks()
            if str(task.get_name()).startswith("new-project-load:gh")
        }
        assert parents, "the real provider load must be in flight"
        children = set(modal._owner_jobs)
        assert children, "real owner refresh jobs must be in flight"
        wizard_queries.clear()
        app.pop_screen()
        # Let teardown land while the owner threads are still blocked: the
        # parent must end cancelled (propagation, not a swallowed break).
        await wait_for(pilot, lambda: all(task.done() for task in parents | children))
        for task in parents:
            assert task.cancelled(), "cancelled refresh must propagate, not swallow"
        for task in children:
            assert task.cancelled(), "teardown must cancel owner jobs"
        release.set()
        await pilot.pause()
        assert modal._loading == set()
        assert modal._refresh_queued == set()
        assert modal._teardown_started
        touched = [
            selector
            for selector in wizard_queries
            if selector.startswith("#new-project-") or "NewProjectSource" in selector
        ]
        assert touched == [], f"teardown touched the DOM: {touched}"


async def test_disabled_tab_fallback_does_not_persist_provider(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    import json

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    prefs_dir = tmp_path / "project_onboarding"
    prefs_dir.mkdir(parents=True)
    (prefs_dir / "preferences.json").write_text(
        json.dumps({"last_provider": "gh", "last_owner": {"gh": "sase-org"}})
    )
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(
            _provider("gh", "GitHub"),
            _provider("git", "Git (bare)"),
        ),
        candidate_inputs={
            "gh": _tool_missing_inputs(),
            "git": CandidateInputs("git", "Git (bare)", ""),
        },
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        # Automatic fallback steps off the broken provider...
        assert modal._state.workflow_type == "git"
        # ...without persisting it over the user's saved provider.
        await pilot.pause(0.2)
        assert modal._preferences.last_provider == "gh"
        payload = json.loads((prefs_dir / "preferences.json").read_text())
        assert payload["last_provider"] == "gh"


async def test_post_remedy_refresh_queues_behind_load(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        assert modal._state.workflow_type == "gh"
        modal._loading.add("gh")
        modal.action_refresh_provider()
        assert modal._refresh_queued == {"gh"}
        refreshes: list[str] = []

        async def _fake_refresh(workflow_type: str, *, force: bool) -> None:
            refreshes.append(workflow_type)
            modal._loading.discard(workflow_type)

        monkeypatch.setattr(modal, "_refresh_all_owners", _fake_refresh)
        modal._finish_provider_load("gh")
        await pilot.pause()
        assert refreshes == ["gh"]
        assert modal._refresh_queued == set()


async def test_no_owners_card_shows_with_create_row(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )
    modal = NewProjectModal(
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={
            "gh": CandidateInputs(workflow_type="gh", display="GitHub", account="")
        },
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
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
