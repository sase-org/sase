"""Source view-model unit tests for the New Project wizard."""

from __future__ import annotations

from types import SimpleNamespace

from sase import workspace_provider
from sase.ace.tui.modals.new_project_rendering import (
    render_no_owners_detail,
    render_source_detail,
    render_source_row,
)
from sase.ace.tui.modals.new_project_source_model import (
    build_source_view,
    cache_age_for,
    create_source_row,
    health_chip_text,
    hidden_footer,
)
from sase.project_onboarding import CandidateInputs, OwnerResult
from tests.ace.tui.modals._new_project_source_helpers import (
    inputs,
    parsed,
    tool_missing_inputs,
)


def test_source_groups_hidden_counts_and_hidden_filter() -> None:
    candidate = inputs()
    view = build_source_view(candidate)

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

    matching_hidden = build_source_view(candidate, filter_text="hidden")
    assert matching_hidden.groups[-1].group_id == "search_only"
    assert matching_hidden.groups[-1].rows[0].display == "sase-org/hidden"

    all_rows = build_source_view(candidate, reveal_forks=True)
    assert all_rows.groups[-1].rows[0].hidden_reason == "fork"


def test_source_paste_ref_becomes_a_synthetic_row(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            parsed(workflow_type, "sase-org/pasted")
            if text == "https://github.com/sase-org/pasted"
            else None
        ),
    )

    view = build_source_view(inputs(), filter_text="https://github.com/sase-org/pasted")

    assert view.parsed_ref.ref == "sase-org/pasted"
    assert view.groups[0].group_id == "paste"
    assert view.groups[0].rows[0].display == "Add sase-org/pasted"


def test_create_row_pins_first_across_filter_and_states(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    row = create_source_row("GitHub", "gh")
    assert row.group == "create"
    assert row.ref == ""
    assert "GitHub" in row.display

    view = build_source_view(inputs(), create_row=row)
    assert view.groups[0].group_id == "create"
    assert view.rows[0] == row

    filtered = build_source_view(inputs(), filter_text="zzz-no-match", create_row=row)
    assert filtered.rows[0] == row

    empty = build_source_view(
        CandidateInputs(workflow_type="gh", display="GitHub", account=""),
        create_row=row,
    )
    assert empty.rows == (row,)

    without = build_source_view(inputs())
    assert all(group.group_id != "create" for group in without.groups)


def test_loading_rows_are_unselectable_placeholders(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    view = build_source_view(inputs(), pending_owners=frozenset({"sase-org"}))
    fetching = [row for row in view.rows if row.is_loading]
    assert fetching, "a pending owner must render a fetching row"
    assert all(not row.selectable and not row.ref for row in fetching)


def test_truncation_footer_names_filter_and_paste(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    owners = inputs().owners
    truncated = [
        OwnerResult(
            name=owner.name,
            kind_label=owner.kind_label,
            status=owner.status,
            truncated=True,
        )
        for owner in owners
    ]
    view = build_source_view(inputs(owners=truncated))
    assert view.truncated
    assert "showing 200 · type to filter or paste owner/repo" in hidden_footer(view)


def test_health_chip_states() -> None:
    assert health_chip_text(None) == "◌ loading cached candidates…"
    assert (
        health_chip_text(inputs(), pending_owners=frozenset({"sase-org"}))
        == "◌ loading 0 of 1 owners"
    )
    assert (
        health_chip_text(tool_missing_inputs(), workflow_type="gh")
        == "✗ gh not installed"
    )
    owner_error = inputs(
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
        health_chip_text(inputs(), cache_age="2m")
        == "✓ bbugyi200 · 1 owners · cached 2m"
    )
    assert health_chip_text(inputs()) == "✓ bbugyi200 · 1 owners · cached"
    assert (
        health_chip_text(CandidateInputs("gh", "GitHub", ""))
        == "○ no owners · paste owner/repo"
    )
    now = 1_000_000.0
    young = inputs()
    young.fetched_at = now - 30
    assert cache_age_for(young, now=now) == ""
    old = inputs()
    old.fetched_at = now - 150
    assert cache_age_for(old, now=now) == "2m"
    older = inputs()
    older.fetched_at = now - 7200
    assert cache_age_for(older, now=now) == "2h"


def test_hidden_enabled_project_row_names_show_action(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", lambda *args: None)
    view = build_source_view(inputs(), filter_text="hidden")
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
    dirty = inputs(account="bbugyi\x00\x1f200")
    assert health_chip_text(dirty) == "✓ bbugyi200 · 1 owners · cached"
    assert health_chip_text(dirty, live=True) == "✓ bbugyi200 · 1 owners"
    assert (
        health_chip_text(inputs(), cache_age="2m", live=True)
        == "✓ bbugyi200 · 1 owners"
    )


def test_cache_age_comes_from_inputs_timestamp() -> None:
    import time

    from sase.ace.tui.modals.new_project_source_model import cache_age_for

    assert cache_age_for(None) == ""
    assert cache_age_for(inputs()) == ""
    aged = inputs()
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
