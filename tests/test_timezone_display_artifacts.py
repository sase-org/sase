"""Configured-timezone regressions for artifacts and generated Markdown."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
from pathlib import Path

import pytest
from rich.console import Console

from sase.ace.tui.widgets._artifact_ref_completion_menu import age_label
from sase.ace.tui.widgets.artifacts.beads_detail import (
    bead_preview_markdown,
    bead_properties_header,
)
from sase.ace.tui.widgets.artifacts.files_detail import build_file_detail
from sase.ace.tui.widgets.artifacts.files_rendering import file_row_text
from sase.ace.tui.widgets.artifacts.plans_rendering import archive_text
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.rendering_commits import render_agent_commits
from sase.artifact_cli.listing import handle_list
from sase.bead.model import Issue, IssueType, Resolution, Status
from sase.bead_pages.associations import BeadCommitAssociation
from sase.bead_pages.rendering_identity import _render_instant
from sase.bead_pages.rendering_tables import render_commits
from sase.core.artifact_file_explicit import write_artifact_file_index_unlocked
from sase.core.artifact_file_helpers import file_created_at
from sase.core.artifact_file_query_facade import query_artifact_files
from sase.core.artifact_file_types import ArtifactFile
from sase.plan_search.model import Plan, PlanSearchMatch
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests.ace.tui._artifacts_files_helpers import logical_file


def _artifact_file(created_at: str = "2026-07-25T01:30:00Z") -> ArtifactFile:
    return ArtifactFile(
        id="explicit:0123456789abcdef01234567",
        label="Timezone report",
        kind="markdown",
        path="/tmp/timezone-report.md",
        created_at=created_at,
        project="alpha",
        agent_name="alpha.agent",
        size_bytes=1024,
    )


def _projects() -> ProjectRefDisplaySnapshot:
    return ProjectRefDisplaySnapshot(ProjectDisplaySnapshot({"alpha": "Alpha"}))


def test_files_rows_use_configured_timezone(
    tz_divergence: None,
) -> None:
    row = _artifact_file()
    logical = logical_file(row)

    rendered = file_row_text(logical, view_mode="markdown", projects=_projects())
    assert "21:30" in rendered.plain
    assert "01:30" not in rendered.plain


def test_files_detail_uses_configured_timezone(tz_divergence: None) -> None:
    rendered = build_file_detail(
        _artifact_file(),
        None,
        view_mode="markdown",
        projects=_projects(),
    )

    assert "Created: 2026-07-24 21:30" in rendered.plain


def test_bead_detail_and_markdown_use_configured_timezone(
    tz_divergence: None,
) -> None:
    issue = Issue(
        id="alpha-1",
        title="Timezone display",
        status=Status.CLOSED,
        issue_type=IssueType.TASK,
        resolution=Resolution.DONE,
        created_at="2026-07-25T01:30:00Z",
        updated_at="2026-07-25T02:45:00Z",
        closed_at="2026-07-25T03:15:00Z",
    )
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                None,
                project="alpha",
                project_name="Alpha",
            )
        )
    properties = capture.get()
    markdown = bead_preview_markdown(issue, None, project="alpha")

    assert "2026-07-24 21:30:00" in properties
    assert "2026-07-24 22:45:00" in properties
    assert "2026-07-24 23:15:00" in properties
    assert "- Created: 2026-07-24 21:30:00" in markdown
    assert "- Updated: 2026-07-24 22:45:00" in markdown
    assert "- Closed: 2026-07-24 23:15:00" in markdown


def test_plan_archive_date_uses_configured_timezone_and_preserves_fallback(
    tz_divergence: None,
) -> None:
    def match(created_at: str) -> PlanSearchMatch:
        return PlanSearchMatch(
            plan=Plan(
                source="repo",
                kind="epic",
                path="/tmp/timezone.md",
                relpath="202607/timezone.md",
                name="timezone",
                title="Timezone",
                status="done",
                created_at=created_at,
                prompt_link="",
                summary="",
                body="",
            ),
            matched_fields=[],
            score=0,
        )

    assert "07-24" in archive_text(match("2026-07-25T01:30:00Z")).plain
    assert "not-a-dat" in archive_text(match("not-a-date-value")).plain


def test_artifact_ref_age_date_uses_configured_timezone(
    tz_divergence: None,
) -> None:
    assert age_label("2026-07-03T01:30:00Z") == "2026-07-02"


def test_artifact_list_uses_configured_timezone(
    tz_divergence: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.listing.load_project_ref_display_snapshot",
        _projects,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.listing.query_artifact_files",
        lambda **_kwargs: [_artifact_file()],
    )
    args = argparse.Namespace(
        agent=None,
        explicit=False,
        json=False,
        kind=None,
        limit=50,
        project=None,
        query=None,
        since=None,
        unused=False,
    )

    assert handle_list(args) == 0
    output = capsys.readouterr().out
    assert "2026-07-24 21:30" in output
    assert "2026-07-25 01:30" not in output


def test_file_created_at_mints_configured_timezone_offset(
    tz_divergence: None,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "late-local-day.txt"
    artifact.write_text("artifact", encoding="utf-8")
    timestamp = datetime(2026, 7, 4, 1, 30, tzinfo=UTC).timestamp()
    os.utime(artifact, (timestamp, timestamp))

    created_at = file_created_at(artifact)

    assert created_at == "2026-07-03T21:30:00-04:00"


def test_since_filter_uses_created_at_embedded_offset_calendar_date(
    tz_divergence: None,
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.jsonl"
    artifact = ArtifactFile(
        id="default:111111111111111111111111",
        label="late-local-day",
        kind="file",
        path=str(tmp_path / "late-local-day.txt"),
        created_at="2026-07-03T21:30:00-04:00",
    )
    write_artifact_file_index_unlocked(index, [artifact])

    assert query_artifact_files(index, since="2026-07-03") == [artifact]
    assert query_artifact_files(index, since="2026-07-04") == []


def test_generated_commit_tables_use_labeled_configured_timezone(
    tz_divergence: None,
) -> None:
    epoch = int(datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp())
    agent_lines = render_agent_commits(
        (CommitRecord("a" * 40, "subject", epoch),),
        commit_url_base=None,
        commit_repo_name="sase",
    )
    bead_lines = render_commits(
        Issue("sase-tz", "Timezone"),
        (
            BeadCommitAssociation(
                "aaaaaaa",
                None,
                "sase-tz",
                "subject",
                epoch,
                (epoch, "aaaaaaa", "sase-tz"),
                "a" * 40,
            ),
        ),
    )

    for lines in (agent_lines, bead_lines):
        rendered = "\n".join(lines)
        assert "Committed (UTC)" not in rendered
        assert "2026-07-03 06:24:49 EDT" in rendered


def test_bead_page_instants_use_labeled_configured_timezone(
    tz_divergence: None,
) -> None:
    assert _render_instant("2026-07-03T10:24:49Z") == ("2026-07-03 06:24:49 EDT")
    assert _render_instant("not|an-instant") == r"not\|an-instant"
