"""Configured-timezone regressions for CLI and diagnostic rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO

from rich.console import Console

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


def _render_plain(renderable: object, *, width: int = 200) -> str:
    output = StringIO()
    Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=width,
    ).print(renderable)
    return output.getvalue()


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
