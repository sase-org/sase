"""Current-project seeding for the shared Artifacts scope."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.ace.config import get_ace_page_size
from sase.ace.query.limit_token import ensure_limit
from sase.ace.query.project_scope import has_project_scope
from sase.ace.saved_queries import load_last_query
from sase.ace.testing import AcePage, make_patch
from sase.ace.tui.actions.artifacts import (
    _ArtifactsProjectChoices,
    _collect_artifacts_project_choices,
    _resolve_artifacts_scope_seed,
)
from sase.ace.tui.app import AceApp
from sase.ace.tui.modals.inventory_project_picker import (
    InventoryProjectChoice,
    InventoryProjectPicker,
)
from sase.ace.tui.widgets import (
    ArtifactPlaceholderPane,
    ArtifactsBeadsPane,
    ArtifactsDocumentsPane,
    ArtifactsFilesPane,
    CommitsPane,
)
from sase.current_project import CurrentProject
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from sase.vcs_log.models import VcsLogResult
import sase.ace.tui.widgets.artifacts.commits as commits_module
from tests._project_display_case import ProjectDisplayCase


def _capped(query: str) -> str:
    return ensure_limit(query, get_ace_page_size())


@pytest.fixture(autouse=True)
def _stub_commits_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **_kwargs: VcsLogResult((), (), ()),
    )


def _two_enabled_choices(
    current_project: str | None = "alpha",
) -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice("alpha", "Alpha", "enabled"),
            InventoryProjectChoice("beta", "Beta", "enabled"),
        ),
        enabled_projects=("alpha", "beta"),
        display_names={"alpha": "Alpha", "beta": "Beta"},
        current_project=current_project,
    )


def _needle_patches() -> list:
    alpha = make_patch(
        name="needle_alpha",
        description="needle",
        file_path="/tmp/alpha/alpha.sase",
    )
    alpha.project_display_name = "Alpha"
    beta = make_patch(
        name="needle_beta",
        description="needle",
        file_path="/tmp/beta/beta.sase",
    )
    beta.project_display_name = "Beta"
    return [alpha, beta]


def _capture_notify(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    seen: list[str] = []
    original = AceApp.notify

    def _notify(self: AceApp, message: str, **kwargs: Any) -> None:
        seen.append(message)
        original(self, message, **kwargs)

    monkeypatch.setattr(AceApp, "notify", _notify)
    return seen


async def _wait_for_choices(
    page: AcePage,
    choices: _ArtifactsProjectChoices,
) -> None:
    await page.wait_for(lambda _state: page.app._artifacts_project_choices is choices)


async def _pick_inventory_row(page: AcePage, highlighted: int) -> None:
    await page.press("p")
    await page.expect_modal("InventoryProjectPicker")
    picker = page.app.screen
    assert isinstance(picker, InventoryProjectPicker)
    picker.query_one("#inventory-project-picker-list").highlighted = highlighted
    picker.action_select_highlighted()
    await page.expect_no_modal()


def _sole_enabled_choices(
    current_project: str | None = None,
) -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice("alpha", "Alpha", "enabled"),
            InventoryProjectChoice("beta", "Beta", "disabled"),
        ),
        enabled_projects=("alpha",),
        display_names={"alpha": "Alpha", "beta": "Beta"},
        current_project=current_project,
    )


@pytest.mark.parametrize(
    ("choices", "seed_filters", "expected"),
    [
        (_two_enabled_choices("alpha"), True, "alpha"),
        (_two_enabled_choices("alpha"), False, None),
        (_two_enabled_choices(None), True, None),
        (_two_enabled_choices("missing"), True, None),
        (_sole_enabled_choices("beta"), True, "alpha"),
        (_sole_enabled_choices("alpha"), False, "alpha"),
        (_sole_enabled_choices(None), False, "alpha"),
    ],
)
def test_artifacts_scope_seed_precedence_table(
    choices: _ArtifactsProjectChoices,
    seed_filters: bool,
    expected: str | None,
) -> None:
    assert _resolve_artifacts_scope_seed(choices, seed_filters=seed_filters) == expected


def test_artifacts_scope_seed_normalizes_display_name_to_key() -> None:
    case = ProjectDisplayCase()
    choices = _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(case.project_key, case.project_label, "enabled"),
            InventoryProjectChoice("other", "Other", "enabled"),
        ),
        enabled_projects=(case.project_key, "other"),
        display_names={case.project_key: case.project_label, "other": "Other"},
        project_ref_display=ProjectRefDisplaySnapshot(
            ProjectDisplaySnapshot({case.project_key: case.project_label}),
        ),
        current_project=case.project_label,
    )

    assert _resolve_artifacts_scope_seed(choices, seed_filters=True) == case.project_key


def test_collect_prefers_resolved_current_project(
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    record = project_display_case.project_record()
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.current_project.resolve_current_project",
        lambda: CurrentProject(
            project_key=project_display_case.project_key,
            display_name=project_display_case.project_label,
            origin="project",
            origin_ref=project_display_case.project_key,
            workflow_type="gh",
        ),
    )
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("cwd fallback must not run when MRU resolves")
        ),
    )

    choices = _collect_artifacts_project_choices()

    assert choices.current_project == project_display_case.project_key
    assert choices.enabled_projects == (project_display_case.project_key,)


def test_collect_falls_back_to_cwd_when_mru_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    record = project_display_case.project_record()
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.current_project.resolve_current_project",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: (
            record.project_file,
            1,
            project_display_case.project_key,
        ),
    )

    choices = _collect_artifacts_project_choices()

    assert choices.current_project == project_display_case.project_key


async def test_seeded_scope_reaches_stitches_beads_files_and_plans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is choices
        )
        await page.wait_for(lambda _state: page.app.artifacts_project_scope == "alpha")

        assert page.app.artifacts_project_scope == "alpha"
        assert page.app._artifacts_scope_was_picked is False
        for pane in page.app.query(ArtifactPlaceholderPane):
            assert pane.project_scope == "alpha"
        commits = page.app.query_one(CommitsPane)
        assert commits.project_scope == "Alpha"
        assert commits.filters.project == "Alpha"
        assert page.app.query_one(ArtifactsBeadsPane).project_scope == "alpha"
        assert page.app.query_one(ArtifactsFilesPane).project_scope == "alpha"
        for pane in page.app.query(ArtifactsDocumentsPane):
            assert pane.project_scope == "alpha"
        assert page.app.query_string == _capped('"feature"') + " AND project:Alpha"
        assert "project:alpha" not in page.app.query_string


async def test_seed_filters_false_keeps_today_s_unscoped_multi_project_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"ace": {"current_project": {"seed_filters": False}}},
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is choices
        )

        assert page.app._current_project_settings.seed_filters is False
        assert page.app.artifacts_project_scope is None
        assert page.app.query_one(CommitsPane).filters.project is None
        assert page.app.query_string == _capped('"feature"')


async def test_explicit_query_term_wins_over_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )

    async with AcePage(query="project:beta", initial_tab="patches") as page:
        assert page.app.artifacts_project_scope == "beta"
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is choices
        )
        assert page.app.artifacts_project_scope == "beta"
        assert page.app.query_one(CommitsPane).filters.project == "beta"
        assert page.app.query_string == _capped("project:beta")


async def test_mid_session_current_project_change_does_not_re_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _two_enabled_choices("alpha")
    second = _two_enabled_choices("beta")
    state = {"choices": first}
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: state["choices"],
    )

    async with AcePage(initial_tab="patches") as page:
        await page.wait_for(lambda _state: page.app.artifacts_project_scope == "alpha")
        page.app.query_string = '"edited"'
        page.app.parsed_query = page.app._parse_patch_query('"edited"')

        state["choices"] = second
        page.app._artifacts_project_choices = None
        page.app._ensure_artifacts_project_choices()
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is second
        )

        assert page.app.artifacts_project_scope == "alpha"
        assert page.app._artifacts_scope_was_picked is False
        assert page.app.query_one(CommitsPane).filters.project == "Alpha"
        assert page.app.query_string == '"edited"'


async def test_picked_all_projects_is_not_reseeded_after_inventory_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _two_enabled_choices("alpha")
    second = replace(first)
    state = {"choices": first}
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: state["choices"],
    )

    async with AcePage(initial_tab="patches") as page:
        await page.wait_for(lambda _state: page.app.artifacts_project_scope == "alpha")
        await page.press("p")
        await page.expect_modal("InventoryProjectPicker")
        picker = page.app.screen
        assert isinstance(picker, InventoryProjectPicker)
        picker.query_one("#inventory-project-picker-list").highlighted = 0
        picker.action_select_highlighted()
        await page.expect_no_modal()
        await page.wait_for(lambda _state: page.app.artifacts_project_scope is None)
        assert page.app._artifacts_scope_was_picked is True

        state["choices"] = second
        page.app._artifacts_project_choices = None
        page.app._ensure_artifacts_project_choices()
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is second
        )

        assert page.app.artifacts_project_scope is None
        assert page.app.query_one(CommitsPane).filters.project is None
        assert not has_project_scope(page.app.query_string)


async def test_first_open_seeds_patches_query_with_display_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )

    async with AcePage(
        query='"needle"',
        patches=_needle_patches(),
        initial_tab="patches",
    ) as page:
        await _wait_for_choices(page, choices)
        await page.wait_for(
            lambda _state: (
                page.app.query_string == _capped('"needle"') + " AND project:Alpha"
            )
        )

        assert page.app.artifacts_project_scope == "alpha"
        assert page.app.query_string == _capped('"needle"') + " AND project:Alpha"
        assert [patch.name for patch in page.app.patches] == ["needle_alpha"]


async def test_not_project_term_is_not_inverted_by_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )
    query = "NOT project:beta"

    async with AcePage(query=query, initial_tab="patches") as page:
        await _wait_for_choices(page, choices)
        await page.wait_for(
            lambda _state: page.app._patch_query_scope_seed_attempted is True
        )

        assert page.app.query_string == _capped(query)
        assert "NOT project:Alpha" not in page.app.query_string


async def test_nested_project_term_is_left_byte_identical_without_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )
    seen = _capture_notify(monkeypatch)
    query = '(project:beta OR "x")'

    async with AcePage(query=query, initial_tab="patches") as page:
        await _wait_for_choices(page, choices)
        await page.wait_for(
            lambda _state: page.app._patch_query_scope_seed_attempted is True
        )

        assert page.app.query_string == _capped(query)
        assert not any("grouped expression" in message for message in seen)


async def test_startup_save_persists_pre_seed_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    last_query = tmp_path / "last_query.txt"
    monkeypatch.setattr("sase.ace.saved_queries._LAST_QUERY_FILE", last_query)
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )
    starting = '"needle"'

    async with AcePage(query=starting, initial_tab="patches") as page:
        await _wait_for_choices(page, choices)
        await page.wait_for(
            lambda _state: (
                page.app.query_string == _capped('"needle"') + " AND project:Alpha"
            )
        )
        page.app._save_startup_query()

        persisted = last_query.read_text()
        assert persisted == _capped(starting)
        assert load_last_query() == _capped(starting)
        assert "project:" not in persisted

    async with AcePage(query=starting, initial_tab="patches") as page:
        await _wait_for_choices(page, choices)
        await page.wait_for(
            lambda _state: (
                page.app.query_string == _capped('"needle"') + " AND project:Alpha"
            )
        )
        assert page.app.query_string == _capped('"needle"') + " AND project:Alpha"


async def test_user_commit_after_seed_persists_committed_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    last_query = tmp_path / "last_query.txt"
    monkeypatch.setattr("sase.ace.saved_queries._LAST_QUERY_FILE", last_query)
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )

    async with AcePage(query='"needle"', initial_tab="patches") as page:
        await _wait_for_choices(page, choices)
        await page.wait_for(
            lambda _state: (
                page.app.query_string == _capped('"needle"') + " AND project:Alpha"
            )
        )
        seeded = page.app.query_string
        assert page.app._patch_query_scope_seed_baseline is not None

        page.app._commit_patch_query(seeded)
        assert page.app._patch_query_scope_seed_baseline is None
        assert last_query.read_text() == page.app.canonical_query_string
        assert "project:Alpha" in last_query.read_text()

        page.app._save_current_query()
        assert last_query.read_text() == page.app.canonical_query_string
        assert last_query.read_text() != '"needle"'


async def test_cross_pane_pick_rewrites_patches_query_without_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )
    seen = _capture_notify(monkeypatch)

    async with AcePage(query='"needle"', initial_tab="patches") as page:
        await _wait_for_choices(page, choices)
        await page.wait_for(
            lambda _state: (
                page.app.query_string == _capped('"needle"') + " AND project:Alpha"
            )
        )
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")
        seen.clear()

        await _pick_inventory_row(page, 2)
        await page.wait_for(lambda _state: page.app.artifacts_project_scope == "beta")

        assert page.app.query_string == _capped('"needle"') + " AND project:Beta"
        assert page.app.artifacts_project_scope == "beta"
        assert "Query updated" not in seen


async def test_live_filter_session_suppresses_seed_and_consumes_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )

    async with AcePage(query='"needle"', initial_tab="agents") as page:
        parsed = page.app._parse_patch_query('"needle"')
        page.app._live_patch_query = ('"needle"', parsed)
        page.app._ensure_artifacts_project_choices()
        await _wait_for_choices(page, choices)
        await page.wait_for(
            lambda _state: page.app._patch_query_scope_seed_attempted is True
        )

        assert page.app.query_string == _capped('"needle"')
        assert page.app._patch_query_scope_seed_attempted is True

        page.app._live_patch_query = None
        page.app._artifacts_project_choices = None
        page.app._ensure_artifacts_project_choices()
        await _wait_for_choices(page, choices)

        assert page.app.query_string == _capped('"needle"')


async def test_patches_pane_sync_triggers_project_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = _two_enabled_choices("alpha")
    calls = {"n": 0}

    def _collect() -> _ArtifactsProjectChoices:
        calls["n"] += 1
        return choices

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _collect,
    )

    async with AcePage(query='"needle"', initial_tab="agents") as page:
        assert calls["n"] == 0
        page.app.current_artifacts_subtab = "patches"
        page.app.current_tab = "artifacts"
        await _wait_for_choices(page, choices)

        assert calls["n"] >= 1
        assert page.app.current_artifacts_pane_key == "patches"
