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
from io import StringIO
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
from sase.ace.tui.widgets.artifacts.files_rendering import (
    file_group_label,
    file_row_text,
)
from sase.ace.tui.widgets.artifacts.plans_rendering import archive_text
from sase.artifact_cli.listing import handle_list
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.rendering_commits import render_agent_commits
from sase.bead.model import Issue, IssueType, Resolution, Status
from sase.bead_pages.associations import BeadCommitAssociation
from sase.bead_pages.rendering_identity import _render_instant
from sase.bead_pages.rendering_tables import render_commits
from sase.core.artifact_file_explicit import write_artifact_file_index_unlocked
from sase.core.artifact_file_helpers import file_created_at
from sase.core.artifact_file_query_facade import query_artifact_files
from sase.core.artifact_file_types import ArtifactFile
from sase.core.time import format_local, parse_local
from sase.main.task_render import task_detail, task_show_json
from sase.memory.cli_log import (
    _events_panel as memory_events_panel,
    _proposal_events_panel,
)
from sase.memory.proposals import MemoryProposalEvent
from sase.memory.read_log import MemoryReadEvent
from sase.memory.review_tui._render import format_time_or_age
from sase.notification_gates.debug import iso_from_unix as debug_iso_from_unix
from sase.notification_gates.debug_rendering import iso_from_unix
from sase.plan_search.model import Plan, PlanSearchMatch
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from sase.repo_open_cli_log import _event_panel as repo_event_panel
from sase.repo_open_log import RepoOpenEvent
from sase.skills.cli_log import _event_panel as skill_event_panel
from sase.skills.use_log import SkillUseEvent
from sase.tasks import BackgroundTask
from sase.telemetry.render import (
    format_recording_started,
    render_bar_chart,
    render_sparkline,
    render_stat_tile,
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


# --- artifact-file calendar dates -----------------------------------------


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


# --- CLI tables ------------------------------------------------------------


def test_task_detail_uses_configured_timezone_but_json_stays_raw(
    tz_divergence: None,
) -> None:
    task = BackgroundTask(
        task_id="task-1",
        label="Timezone task",
        kind="command",
        status="success",
        command=["true"],
        cwd="/tmp",
        origin="cli",
        created_at="2026-07-03T10:24:49Z",
        started_at="2026-07-03T10:25:49Z",
        finished_at="2026-07-03T10:26:49Z",
        log_path="/tmp/task.log",
    )

    rendered = _render_plain(task_detail(task))

    assert "2026-07-03 06:24:49" in rendered
    assert "2026-07-03 06:25:49" in rendered
    assert "2026-07-03 06:26:49" in rendered
    assert task_show_json(task, log="")["task"]["created_at"] == task.created_at


def test_repo_log_detail_uses_configured_timezone(tz_divergence: None) -> None:
    event = RepoOpenEvent(
        schema_version=1,
        id="open-1",
        timestamp="2026-07-03T10:24:49Z",
        project="sase",
        repo="sase",
        repo_kind="primary",
        workspace_num=1,
        path="/tmp/sase",
        agent_name="agent",
        agent_source="test",
        artifacts_dir=None,
        reason="test",
        cwd="/tmp",
    )

    assert "2026-07-03 06:24:49" in _render_plain(repo_event_panel(event))


def test_memory_log_tables_use_configured_timezone(tz_divergence: None) -> None:
    read_event = MemoryReadEvent(
        schema_version=1,
        id="read-1",
        timestamp="2026-07-03T10:24:49Z",
        project="sase",
        cwd="/tmp",
        canonical_path="example.md",
        resolved_path="/tmp/example.md",
        agent_name="agent",
        agent_source="test",
        artifacts_dir=None,
        reason="test",
        byte_count=1,
        frontmatter_stripped=False,
    )
    proposal_event = MemoryProposalEvent(
        schema_version=1,
        event_type="proposed",
        proposal_id="proposal-1",
        timestamp="2026-07-03T10:24:49Z",
        project="sase",
        cwd="/tmp",
        title="Proposal",
        target_path="example.md",
        author_name="agent",
        author_source="test",
        artifacts_dir=None,
        body_path="/tmp/body.md",
        body_sha256="a" * 64,
        body_byte_count=1,
        evidence=(),
        warnings=(),
    )

    assert "2026-07-03 06:24:49" in _render_plain(memory_events_panel((read_event,)))
    assert "2026-07-03 06:24:49" in _render_plain(
        _proposal_events_panel((proposal_event,))
    )


def test_skill_log_detail_uses_configured_timezone(tz_divergence: None) -> None:
    event = SkillUseEvent(
        schema_version=1,
        id="use-1",
        timestamp="2026-07-03T10:24:49Z",
        project="sase",
        cwd="/tmp",
        skill_name="example",
        agent_name="agent",
        agent_source="test",
        artifacts_dir=None,
        reason="test",
        runtime="codex",
    )

    assert "2026-07-03 06:24:49" in _render_plain(skill_event_panel(event))


# --- Generated Markdown ---------------------------------------------------


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


# --- Other display sites --------------------------------------------------


def test_memory_review_absolute_date_uses_configured_timezone(
    tz_divergence: None,
) -> None:
    assert format_time_or_age("2026-01-02T03:00:00Z") == "2026-01-01"


def test_notification_debug_unix_timestamps_use_configured_timezone(
    tz_divergence: None,
) -> None:
    epoch = datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp()
    expected = "2026-07-03T06:24:49-04:00"

    assert debug_iso_from_unix(epoch) == expected
    assert iso_from_unix(epoch) == expected


def test_telemetry_defaults_use_configured_timezone(tz_divergence: None) -> None:
    epoch = datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp()
    expected = "2026-07-03 06:24 EDT"

    assert expected in format_recording_started(epoch)
    assert expected in _render_plain(
        render_bar_chart(
            title="Empty bars",
            width=100,
            height=6,
            recording_started_at=epoch,
        )
    )
    assert expected in _render_plain(
        render_stat_tile(
            None,
            caption="Empty tile",
            width=100,
            height=6,
            recording_started_at=epoch,
        )
    )
    assert (
        expected
        in render_sparkline(
            [],
            width=100,
            recording_started_at=epoch,
        ).plain
    )


def _render_plain(renderable: object, *, width: int = 200) -> str:
    output = StringIO()
    Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=width,
    ).print(renderable)
    return output.getvalue()
