"""Regression tests for the ``timezone_display_consistency`` plan.

These pin the *display* half of timezone handling: every user-facing timestamp
(TUI panes, CLI tables, generated Markdown) must resolve through the
configured timezone via :func:`sase.core.time.parse_local` /
:func:`sase.core.time.format_local`, never through the host system clock or a
raw UTC instant. The ``tz_divergence`` fixture (see ``tests/conftest.py``)
forces configured tz (``America/New_York``) != system tz (``UTC``) so both bug
classes are visible.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest
from rich.console import Console

from sase.ace.tui.widgets._artifact_ref_completion_menu import age_label
from sase.ace.tui.widgets.artifacts.beads_detail import (
    bead_preview_markdown,
    bead_properties_header,
)
from sase.ace.tui.widgets.artifacts.files_detail import build_file_detail
from sase.ace.tui.widgets.artifacts.files_rendering import (
    file_group_label,
    file_row_text,
)
from sase.ace.tui.widgets.artifacts.plans_rendering import archive_text
from sase.artifact_cli.listing import handle_list
from sase.bead.model import Issue, IssueType, Resolution, Status
from sase.core.artifact_file_types import ArtifactFile
from sase.core.time import format_local, parse_local
from sase.plan_search.model import Plan, PlanSearchMatch
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)


# --- parse_local / format_local: aware-UTC input --------------------------


def test_parse_local_converts_aware_utc_z_suffix(tz_divergence: None) -> None:
    parsed = parse_local("2026-07-03T10:24:49Z")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_converts_aware_utc_offset_suffix(tz_divergence: None) -> None:
    parsed = parse_local("2026-07-03T10:24:49+00:00")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_converts_non_utc_offset(tz_divergence: None) -> None:
    # 2026-07-03T14:24:49+04:00 is the same instant as 10:24:49 UTC.
    parsed = parse_local("2026-07-03T14:24:49+04:00")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


# --- parse_local: naive input is already configured-tz wall time ---------


def test_parse_local_naive_iso_is_unchanged_wall_clock(tz_divergence: None) -> None:
    parsed = parse_local("2026-07-03T06:24:49")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_naive_datetime_is_unchanged_wall_clock(
    tz_divergence: None,
) -> None:
    parsed = parse_local(datetime(2026, 7, 3, 6, 24, 49))
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_aware_datetime_converts(tz_divergence: None) -> None:
    parsed = parse_local(datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC))
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


# --- parse_local: epoch input ---------------------------------------------


def test_parse_local_epoch_int_lands_on_configured_wall_clock(
    tz_divergence: None,
) -> None:
    epoch = int(datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp())
    parsed = parse_local(epoch)
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


def test_parse_local_epoch_float_lands_on_configured_wall_clock(
    tz_divergence: None,
) -> None:
    epoch = datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp()
    parsed = parse_local(epoch)
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (6, 24, 49)


# --- parse_local: unparseable / empty inputs ------------------------------


def test_parse_local_none_returns_none(tz_divergence: None) -> None:
    assert parse_local(None) is None


def test_parse_local_empty_string_returns_none(tz_divergence: None) -> None:
    assert parse_local("") is None


def test_parse_local_whitespace_string_returns_none(tz_divergence: None) -> None:
    assert parse_local("   ") is None


def test_parse_local_garbage_string_returns_none(tz_divergence: None) -> None:
    assert parse_local("not-a-timestamp") is None


# --- format_local ----------------------------------------------------------


def test_format_local_formats_in_configured_tz(tz_divergence: None) -> None:
    assert format_local("2026-07-03T10:24:49Z") == "2026-07-03 06:24:49"


def test_format_local_honors_custom_fmt(tz_divergence: None) -> None:
    assert format_local("2026-07-03T10:24:49Z", "%H:%M") == "06:24"


def test_format_local_honors_custom_default(tz_divergence: None) -> None:
    assert format_local(None, default="N/A") == "N/A"
    assert format_local("garbage", default="N/A") == "N/A"


def test_format_local_default_placeholder_for_unparseable(tz_divergence: None) -> None:
    assert format_local(None) == "—"


# --- Artifacts tab and artifact CLI ---------------------------------------


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


def test_files_rows_and_groups_use_configured_timezone(
    tz_divergence: None,
) -> None:
    row = _artifact_file()
    today = datetime(2026, 7, 24, 23, 0)

    assert file_group_label(row, today=today) == "Today"
    rendered = file_row_text(row, view_mode="markdown", projects=_projects())
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
