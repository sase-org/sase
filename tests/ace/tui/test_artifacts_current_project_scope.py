"""Current-project seeding for the shared Artifacts scope."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import (
    _ArtifactsProjectChoices,
    _collect_artifacts_project_choices,
    _resolve_artifacts_scope_seed,
)
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

        state["choices"] = second
        page.app._artifacts_project_choices = None
        page.app._ensure_artifacts_project_choices()
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is second
        )

        assert page.app.artifacts_project_scope == "alpha"
        assert page.app._artifacts_scope_was_picked is False
        assert page.app.query_one(CommitsPane).filters.project == "Alpha"


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
