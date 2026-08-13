"""In-memory filters and inline query interactions for Artifacts Files."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone, UTC

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import files_pane
from sase.ace.tui.widgets.artifacts.file_filter_bar import FileFilterBar
from sase.ace.tui.widgets.artifacts.files_filtering import (
    FilesFilterQueryError,
    filter_files_snapshot,
    parse_files_filter_query,
)
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.core.time import get_timezone
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests.ace.tui._artifacts_files_helpers import (
    artifact_file,
    logical_file,
    snapshot,
)
from tests.ace.tui._artifacts_plans_helpers import _choices


def test_filter_tokens_match_file_fields_and_date_bounds() -> None:
    explicit = artifact_file(
        "render",
        kind="image",
        path="/stored/render.png",
        source_path="/workspace/teaser-source.png",
        project="bob",
        agent_name="bob.render--code",
        workflow="render",
        explicit=True,
        created_at="2026-07-15T12:00:00+00:00",
    )
    default = artifact_file(
        "notes",
        kind="markdown",
        path="/stored/notes.md",
        source_path="/workspace/notes.md",
        created_at="2026-06-15T12:00:00+00:00",
    )
    model = snapshot((explicit, default), project=None)
    values = parse_files_filter_query(
        "kind:image project:bob agent:bob.render--code workflow:render "
        "origin:created since:2026-07 until:202607 teaser-source",
        now=datetime(2026, 7, 29, tzinfo=UTC),
    )
    matched = filter_files_snapshot(model, values)

    assert matched is not None and matched.rows == (model.rows[0],)
    assert matched.view_mode_counts == model.view_mode_counts
    assert matched.origin_counts == model.origin_counts


def test_repeatable_kind_is_or_while_free_text_terms_are_anded() -> None:
    image = artifact_file(
        "image",
        kind="image",
        path="/stored/build-result.png",
    )
    pdf = artifact_file(
        "pdf",
        kind="pdf",
        path="/stored/build-result.pdf",
    )
    other = artifact_file("other", path="/stored/other.txt")
    filtered = filter_files_snapshot(
        snapshot((image, pdf, other)),
        parse_files_filter_query("kind:image kind:pdf build result"),
    )

    assert filtered is not None and filtered.rows == snapshot((image, pdf)).rows


def test_free_text_filter_matches_vcs_relative_path() -> None:
    row = replace(
        artifact_file("tracked"),
        path=None,
        sha256="a" * 64,
        vcs_repo="sase",
        vcs_sha="b" * 40,
        vcs_relpath="docs/build-result.png",
    )

    filtered = filter_files_snapshot(
        snapshot((row,)),
        parse_files_filter_query("build-result.png"),
    )

    assert filtered is not None and filtered.rows == snapshot((row,)).rows


def test_project_filter_accepts_display_name_without_rendering_storage_key() -> None:
    row = artifact_file("named", project="gh_sase-org__sase")
    projects = ProjectRefDisplaySnapshot(
        ProjectDisplaySnapshot({"gh_sase-org__sase": "sase"})
    )
    filtered = filter_files_snapshot(
        snapshot((row,), project=None),
        parse_files_filter_query("project:sase"),
        projects,
    )

    assert filtered is not None and filtered.rows == snapshot((row,), project=None).rows


@pytest.mark.parametrize(
    "query",
    [
        "kind:video",
        "origin:manual",
        "unknown:value",
        "-kind:image",
        "since:tomorrow",
        "since:2026-08 until:202607",
    ],
)
def test_invalid_file_filter_tokens_are_rejected(query: str) -> None:
    with pytest.raises(FilesFilterQueryError):
        parse_files_filter_query(
            query,
            now=datetime(2026, 7, 29, tzinfo=UTC),
        )


def test_relative_month_bound_uses_calendar_months() -> None:
    tz = get_timezone()
    values = parse_files_filter_query(
        "since:1m",
        now=datetime(2026, 3, 31, 12, 30, tzinfo=tz),
    )
    assert values.since == int(datetime(2026, 2, 28, 12, 30, tzinfo=tz).timestamp())


async def test_filter_bar_kind_cycle_selection_and_empty_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        artifact_file(
            "image-one",
            kind="image",
            path="/stored/image-one.png",
            explicit=True,
        ),
        artifact_file(
            "image-two",
            kind="image",
            path="/stored/image-two.png",
            created_at="2026-07-23T13:10:00-04:00",
        ),
        artifact_file(
            "notes",
            kind="markdown",
            path="/stored/notes.md",
            created_at="2026-07-22T13:10:00-04:00",
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: snapshot(rows, project=project),
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)
        assert pane.select_entry_target(("file", logical_file(rows[1]).logical_id))

        await page.press("/")
        bar = pane.query_one(FileFilterBar)
        await page.wait_for(lambda _state: bar.display)
        bar.set_query("kind:image")
        bar.post_message(FileFilterBar.QueryChanged("kind:image"))
        await page.wait_for(lambda _state: len(pane.entry_targets()) == 2)
        assert pane.selected_entry is not None
        assert pane.selected_entry.id == rows[1].id
        assert {"Alpha", "alpha.1--code", "code"} <= {
            value for values in bar._completion_sources.values() for value in values
        }
        await page.press("enter")
        await page.wait_for(lambda _state: not bar.display)
        assert pane.filters.kinds == ("image",)
        assert "filtered 2/3" in pane.query_one("#files-info", Static).content.plain

        await page.press("s")
        assert pane.filters.kinds == ("markdown",)
        assert pane.selected_entry is not None
        assert pane.selected_entry.id == rows[2].id
        await page.press("s")
        assert pane.filters.kinds == ()

        pane.filters = replace(pane.filters, text=("missing",))
        pane._refresh_options()
        empty = pane.query_one("#files-empty", Static)
        assert "No artifact files match the active filters." in str(empty.content)
        assert "Press f to edit or clear them." in str(empty.content)
