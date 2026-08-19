"""Filter behavior for the Artifacts Stitches pane."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.modals.inventory_project_picker import InventoryProjectChoice
from sase.ace.tui.widgets.artifacts import CommitsPane, CommitsTimeline
from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.vcs_log.filter_query import parse_commit_filter_query, to_query_string
from tests.ace.tui._commits_pane_helpers import _result, _result_with_sidecar


async def test_custom_default_query_controls_first_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result_with_sidecar()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "stitches": {
                        "default_query": (
                            "project:alpha repo:plans sidecar:true limit:5"
                        )
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        bar = pane.query_one(CommitFilterBar)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        assert bar.display is True
        assert editor.text == (
            "project:alpha repo:plans sidecar:true merges:hide limit:5"
        )
        await page.wait_for(lambda _state: bool(calls) and pane.result is not None)

        assert calls[0]["project_scope"] == "alpha"
        assert calls[0]["all_projects"] is False
        assert calls[0]["repo_filters"] == ("plans",)
        assert calls[0]["include_sidecars"] is True
        assert calls[0]["limit"] == 5


async def test_ace_query_project_overrides_config_and_cwd_before_first_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "stitches": {"default_query": "project:configured sidecar:false"}
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: ("/tmp/cwd-project.sase", 1, "cwd-project"),
    )
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or _result(),
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(
        query="project:ace-query",
        initial_tab="patches",
    ) as page:
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        editor = pane.query_one(
            "#commit-filter-input",
            SingleLineVimTextArea,
        )
        assert editor.text == "project:ace-query sidecar:false merges:hide"
        await page.wait_for(lambda _state: bool(calls))

        assert calls[0]["project_scope"] == "ace-query"
        assert calls[0]["all_projects"] is False


async def test_inferred_project_scopes_stitches_after_async_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    choices = _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice("cwd-project", "cwd-project", "enabled"),
            InventoryProjectChoice("other", "Other", "enabled"),
        ),
        enabled_projects=("cwd-project", "other"),
        display_names={"cwd-project": "cwd-project", "other": "Other"},
        current_project="cwd-project",
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {"stitches": {"default_query": "sidecar:false since:24h"}}
            }
        },
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or _result(),
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        editor = pane.query_one(
            "#commit-filter-input",
            SingleLineVimTextArea,
        )
        await page.wait_for(lambda _state: pane.filters.project == "cwd-project")
        assert editor.text == (
            "project:cwd-project sidecar:false merges:hide since:24h"
        )
        await page.wait_for(
            lambda _state: any(call["project_scope"] == "cwd-project" for call in calls)
        )

        assert calls[-1]["project_scope"] == "cwd-project"
        assert calls[-1]["all_projects"] is False


async def test_absent_project_token_collects_all_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    startup_load_calls = 0

    def load_startup_projection() -> ProjectRefDisplaySnapshot:
        nonlocal startup_load_calls
        startup_load_calls += 1
        return ProjectRefDisplaySnapshot()

    monkeypatch.setattr(
        "sase.project_display_names.load_project_ref_display_snapshot",
        load_startup_projection,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {"artifacts": {"stitches": {"default_query": "sidecar:false"}}}
        },
    )
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or _result(),
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        assert pane.filters.project is None
        await page.wait_for(lambda _state: bool(calls))

        assert calls[0]["project_scope"] is None
        assert calls[0]["all_projects"] is True
        assert startup_load_calls == 0


async def test_commits_filter_bar_rejects_invalid_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches", notifications=True) as page:
        await page.press("1")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        bar = pane.query_one(CommitFilterBar)

        await page.press("slash", "ctrl+u", "r", "e", "p", "o")
        await page.wait_for(lambda _state: pane.filters.text == ("repo",))
        await page.press("colon", "enter")
        await page.wait_for(
            lambda _state: (
                bar.query_one("#commit-filter-status", Static).has_class("error")
                and pane.filters.text == ()
            )
        )

        assert bar.display is True
        assert bar.query_one("#commit-filter-status", Static).has_class("error")
        assert pane.filters.text == ()


async def test_committed_project_key_alias_and_unknown_ref_canonicalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_key = "gh_acme__widgets"
    project_label = "widgets"
    project_file = "/tmp/widgets.sase"
    project_ref_display = ProjectRefDisplaySnapshot(
        ProjectDisplaySnapshot({project_key: project_label}),
        {"docs": project_key},
    )
    choices = _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key=project_key,
                display_name=project_label,
                state="enabled",
            ),
        ),
        enabled_projects=(project_key,),
        display_names={project_key: project_label},
        project_files={project_key: project_file},
        project_ref_display=project_ref_display,
    )
    result = _result()
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: choices,
    )
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        bar = pane.query_one(CommitFilterBar)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is choices
        )

        for project_ref, expected_project in (
            (project_key, project_label),
            ("docs", project_label),
            ("unknown", "unknown"),
        ):
            query = (
                f"project:{project_ref} repo:plans author:Ada sidecar:false limit:5 fix"
            )
            await page.press("slash")
            editor.load_text(query)
            editor.cursor_position = len(query)
            await page.press("enter")
            await page.wait_for(
                lambda _state, expected_project=expected_project: (
                    pane.filters.project == expected_project
                    and page.app.focused
                    is pane.query_one("#stitches-timeline", CommitsTimeline)
                )
            )

            expected_values = replace(
                parse_commit_filter_query(query),
                project=expected_project,
            )
            assert editor.text == to_query_string(expected_values)
            assert pane.filters == expected_values


async def test_commits_negative_repo_reconciles_before_collection_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        await page.press("1")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        bar = pane.query_one(CommitFilterBar)
        status = bar.query_one("#commit-filter-status", Static)
        await page.press("slash")
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        query = "-repo:sase-core-foundation"
        editor.load_text(query)
        editor.cursor_position = len(query)

        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and [repo.name for repo in pane.result.repos]
                == ["alpha-platform-repository"]
                and calls[-1].get("exclude_repo_filters") == ("sase-core-foundation",)
                and "exact" in status.content.plain
            )
        )
        assert calls[-1]["limit"] == 0
        assert [entry.commit.short_id for entry in pane.result.commits] == ["aaaaaaa"]
        assert "exact" in status.content.plain

        await page.press("enter")
        await page.wait_for(
            lambda _state: (
                page.app.focused
                is pane.query_one("#stitches-timeline", CommitsTimeline)
            )
        )
        assert bar.display is True
        assert pane.filters.excluded_repos == ("sase-core-foundation",)
        assert editor.text == f"{query} sidecar:true merges:hide"
        assert query not in pane._build_info().plain

        await page.press("slash")
        editor.load_text("-author:Grace")
        editor.cursor_position = len(editor.text)
        await page.wait_for(
            lambda _state: (
                pane.filters.excluded_authors == ("Grace",) and calls[-1]["limit"] == 0
            )
        )
        await page.press("escape")
        await page.wait_for(
            lambda _state: (
                page.app.focused
                is pane.query_one("#stitches-timeline", CommitsTimeline)
            )
        )
        assert pane.filters.excluded_repos == ("sase-core-foundation",)


async def test_clicking_idle_bar_opens_the_filter_session() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("stitches"))
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        bar = pane.query_one(CommitFilterBar)
        assert not pane._filter_session_open

        await page.click("#commit-filter-bar")
        await page.pause()

        assert pane._filter_session_open
        assert bar._editing  # type: ignore[attr-defined]
