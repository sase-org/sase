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
    create_source_row,
    format_cache_age,
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
    assert format_cache_age(30) == ""
    assert format_cache_age(150) == "2m"
    assert format_cache_age(7200) == "2h"


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
    detail = render_no_owners_detail("GitHub")
    assert "No GitHub owners yet" in detail.plain
    assert "github_orgs" in detail.plain


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


async def test_filter_typing_and_highlight_spawn_no_subprocess(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """Perf guard: filter/highlight stay in memory plus the pure parse."""
    parses: list[str] = []
    probes: list[tuple[str, str]] = []

    def _parse(workflow_type: str, text: str):  # type: ignore[no-untyped-def]
        parses.append(text)
        return None

    def _probe(workflow_type: str, ref: str):  # type: ignore[no-untyped-def]
        probes.append((workflow_type, ref))
        raise AssertionError("probe must stay debounced off the hot path")

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", _parse)
    monkeypatch.setattr(workspace_provider, "probe_repo", _probe)
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_source.subprocess.run",
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
        source = modal.query_one(NewProjectSource)
        source.focus_filter()
        await pilot.pause()
        await pilot.press(*"sase")
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == "sase"
        assert parses, "the pure parse hook may run on the hot path"
        assert probes == []
        modal.query_one("#new-project-filter", Input).value = ""
        await pilot.pause()
        assert probes == []
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
        modal.post_message(events.Paste("sase-org/new"))
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == "sase-org/new"


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
        never_set = asyncio.Event()
        job = asyncio.create_task(never_set.wait())
        modal._owner_jobs.add(job)
        app.pop_screen()
        await pilot.pause()
        assert job.cancelled() or job.done()
