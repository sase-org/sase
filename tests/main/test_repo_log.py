"""Tests for ``sase repo log`` rendering, filtering, and lookup."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.main.parser import create_parser
from sase.main.repo_handler import handle_repo_command
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_open_cli_log import (
    _render_repo_open_log_summary,
    handle_repo_log_command,
)
from sase.repo_inventory import RepoKind
from sase.repo_open_log import RepoOpenEvent
from sase.workspace_provider.store import WorkspaceStore


def test_repo_log_summary_renders_grouped_open_stats() -> None:
    events = (
        _event(
            open_id="open-a",
            repo="core",
            repo_kind="linked",
            agent="agent-a",
            timestamp="2026-07-13T12:00:00+00:00",
            reason="Need core context",
        ),
        _event(
            open_id="open-b",
            repo="core",
            repo_kind="linked",
            agent="agent-b",
            timestamp="2026-07-13T12:01:00+00:00",
            reason="Need updated core context",
        ),
        _event(
            open_id="open-c",
            repo="demo--plans",
            repo_kind="sidecar",
            agent="agent-a",
            timestamp="2026-07-13T12:02:00+00:00",
            reason="Read the plan",
        ),
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )

    _render_repo_open_log_summary(events, console=console, project_name="demo")

    text = output.getvalue()
    assert "SASE Repo Open Log" in text
    assert "Open events" in text
    assert "Repos (2)" in text
    assert "core" in text
    assert "demo--plans" in text
    assert "agent-b" in text
    assert "Need updated core context" in text
    assert "Repo Open Events" not in text


def test_repo_log_filtered_view_renders_agents_and_events() -> None:
    events = (
        _event(
            open_id="open-a",
            repo="core",
            repo_kind="linked",
            agent="agent-a",
            workspace=12,
            reason="Need\ncore context",
        ),
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )

    _render_repo_open_log_summary(
        events,
        console=console,
        project_name="demo",
        repo_filter="core",
        agent_filter="agent-a",
        workspace_filter=12,
    )

    text = output.getvalue()
    assert "repo=core, agent=agent-a, workspace=12" in text
    assert "Agents (1)" in text
    assert "Repo Open Events (1)" in text
    assert "open-a" in text
    assert "#12" in text
    assert "Need core context" in text


def test_repo_log_summary_renders_empty_states() -> None:
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=120,
    )

    _render_repo_open_log_summary(
        (),
        console=console,
        project_name="demo",
        repo_filter="missing",
    )

    text = output.getvalue()
    assert "repo=missing" in text
    assert "No repository open events match the current filters." in text
    assert "No agents match the current filters." in text
    assert "No individual repository open events match" in text


def test_repo_log_summary_renders_external_kind() -> None:
    event = _event(
        open_id="external-open",
        repo="gh:acme/widget",
        repo_kind="external",
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        width=180,
    )

    _render_repo_open_log_summary((event,), console=console, project_name="demo")

    rendered = output.getvalue()
    assert "gh:acme/widget" in rendered
    assert "external" in rendered
    assert "255;175;0" in rendered


def test_repo_log_json_filters_and_summarizes_through_repo_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx = _project_context(tmp_path, project_name="demo-key")
    events = (
        _event(
            open_id="open-a",
            repo="core",
            repo_kind="linked",
            agent="agent-a",
            workspace=12,
            reason="First",
        ),
        _event(
            open_id="open-b",
            repo="core",
            repo_kind="linked",
            agent="agent-b",
            workspace=12,
            timestamp="2026-07-13T12:01:00+00:00",
            reason="Second",
        ),
        _event(
            open_id="open-c",
            repo="demo--plans",
            repo_kind="sidecar",
            agent="agent-b",
            workspace=10,
            reason="Third",
        ),
    )
    requested_projects: list[str | None] = []
    requested_log_projects: list[str] = []
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda project: requested_projects.append(project) or ctx,
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _project: "demo",
    )
    monkeypatch.setattr(
        "sase.repo_open_cli_log.read_repo_open_events",
        lambda **kwargs: requested_log_projects.append(kwargs["project"]) or events,
    )
    args = create_parser().parse_args(
        [
            "repo",
            "log",
            "--project",
            "demo",
            "--repo",
            "core",
            "--agent",
            "agent-b",
            "--workspace",
            "12",
            "--json",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert requested_projects == ["demo"]
    assert requested_log_projects == ["demo-key"]
    assert json.loads(capsys.readouterr().out) == {
        "filters": {"agent": "agent-b", "repo": "core", "workspace": 12},
        "project": "demo",
        "summary": [
            {
                "distinct_agent_count": 1,
                "last_agent": "agent-b",
                "last_opened_at": "2026-07-13T12:01:00+00:00",
                "last_reason": "Second",
                "open_count": 1,
                "repo": "core",
                "repo_kind": "linked",
            }
        ],
        "total_agents": 1,
        "total_open_events": 1,
        "total_repos": 1,
    }


@pytest.mark.parametrize(
    ("arguments", "expected_summary"),
    [
        (["--repo", "core"], [("core", 2)]),
        (["--agent", "agent-a"], [("core", 1), ("demo--plans", 1)]),
        (["--workspace", "12"], [("core", 2)]),
        (
            ["--repo", "core", "--agent", "agent-b", "--workspace", "12"],
            [("core", 1)],
        ),
    ],
)
def test_repo_log_filters_compose(
    arguments: list[str],
    expected_summary: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = (
        _event(open_id="open-a", repo="core", agent="agent-a", workspace=12),
        _event(open_id="open-b", repo="core", agent="agent-b", workspace=12),
        _event(
            open_id="open-c",
            repo="demo--plans",
            repo_kind="sidecar",
            agent="agent-a",
            workspace=10,
        ),
    )
    monkeypatch.setattr(
        "sase.repo_open_cli_log.read_repo_open_events",
        lambda **_kwargs: events,
    )
    args = create_parser().parse_args(["repo", "log", *arguments, "--json"])

    assert handle_repo_log_command(args, project_name="demo") == 0

    payload = json.loads(capsys.readouterr().out)
    assert [
        (summary["repo"], summary["open_count"]) for summary in payload["summary"]
    ] == expected_summary
    assert payload["total_open_events"] == sum(
        open_count for _, open_count in expected_summary
    )


def test_repo_log_id_prefix_json_outputs_raw_event(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event = _event(
        open_id="abc123def456",
        repo="core",
        agent="agent-a",
        workspace=12,
        reason="Need core context",
    )
    monkeypatch.setattr(
        "sase.repo_open_cli_log.read_repo_open_events",
        lambda **_kwargs: (event,),
    )
    args = create_parser().parse_args(["repo", "log", "--id", "abc123", "--json"])

    assert handle_repo_log_command(args, project_name="demo") == 0

    assert json.loads(capsys.readouterr().out) == {
        "agent_name": "agent-a",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": None,
        "cwd": "/tmp/demo",
        "id": "abc123def456",
        "path": "/tmp/demo/core",
        "project": "demo",
        "reason": "Need core context",
        "repo": "core",
        "repo_kind": "linked",
        "schema_version": 1,
        "timestamp": "2026-07-13T12:00:00+00:00",
        "workspace_num": 12,
    }


def test_repo_log_id_drilldown_renders_full_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _event(open_id="abc123def456", reason="Need core context")
    monkeypatch.setattr(
        "sase.repo_open_cli_log.read_repo_open_events",
        lambda **_kwargs: (event,),
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )
    args = create_parser().parse_args(["repo", "log", "--id", "abc123"])

    assert handle_repo_log_command(args, project_name="demo", console=console) == 0

    text = output.getvalue()
    assert "Repo Open Event abc123def456" in text
    assert "Timestamp" in text
    assert "Repo" in text
    assert "Kind" in text
    assert "Workspace" in text
    assert "Path" in text
    assert "Agent source" in text
    assert "Need core context" in text
    assert "/tmp/demo" in text
    assert "Artifacts dir" in text
    assert "none" in text


def test_repo_log_ambiguous_and_unknown_ids_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = (
        _event(open_id="abc111"),
        _event(open_id="abc222"),
    )
    monkeypatch.setattr(
        "sase.repo_open_cli_log.read_repo_open_events",
        lambda **_kwargs: events,
    )

    ambiguous = create_parser().parse_args(["repo", "log", "--id", "abc"])
    assert handle_repo_log_command(ambiguous, project_name="demo") == 1
    assert "prefix is ambiguous" in capsys.readouterr().err

    unknown = create_parser().parse_args(["repo", "log", "--id", "missing"])
    assert handle_repo_log_command(unknown, project_name="demo") == 1
    assert "unknown repository open id: missing" in capsys.readouterr().err


def test_repo_log_rejects_negative_workspace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["repo", "log", "--workspace", "-1"])

    assert handle_repo_log_command(args, project_name="demo") == 2
    assert "workspace number must be >= 0" in capsys.readouterr().err


def _event(
    *,
    open_id: str,
    repo: str = "core",
    repo_kind: RepoKind = "linked",
    agent: str = "agent-a",
    workspace: int = 12,
    timestamp: str = "2026-07-13T12:00:00+00:00",
    reason: str = "Open the repo",
) -> RepoOpenEvent:
    return RepoOpenEvent(
        schema_version=1,
        id=open_id,
        timestamp=timestamp,
        project="demo",
        repo=repo,
        repo_kind=repo_kind,
        workspace_num=workspace,
        path=f"/tmp/demo/{repo}",
        agent_name=agent,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        reason=reason,
        cwd="/tmp/demo",
    )


def _project_context(
    tmp_path: Path,
    *,
    project_name: str = "demo",
) -> ProjectContext:
    primary = tmp_path / "demo"
    primary.mkdir()
    return ProjectContext(
        project_name=project_name,
        project_file=str(tmp_path / "demo.sase"),
        primary_workspace_dir=str(primary),
        store=WorkspaceStore(str(primary)),
    )
