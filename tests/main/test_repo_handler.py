"""Parser and handler tests for ``sase repo``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.main.parser import create_parser, default_list_delegation_notice
from sase.main.repo_handler import _repo_panel, handle_repo_command
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from sase.workspace_provider.marker import CheckoutMarker
from tests.main.repo_handler_helpers import (
    project_context as _project_context,
    repo_record as _repo_record,
)


def test_repo_parser_defaults_to_list() -> None:
    args = create_parser().parse_args(["repo"])
    assert args.command == "repo"
    assert args.repo_subcommand == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase repo'; delegating to 'sase repo list'."
    )


def test_repo_init_parser_exposes_scoped_controls() -> None:
    args = create_parser().parse_args(
        ["repo", "init", "--check", "--diff", "--no-commit"]
    )

    assert args.command == "repo"
    assert args.repo_subcommand == "init"
    assert args.check is True
    assert args.diff is True
    assert args.no_commit is True


def test_repo_list_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx = _project_context(tmp_path)
    record = RepoRecord(
        name="demo",
        kind="primary",
        project="demo",
        project_key="demo",
        path=ctx.primary_workspace_dir,
        exists=True,
        auto_clone=False,
        description=None,
        source="ProjectSpec",
        env_name=None,
        clones=(RepoCloneRecord(0, ctx.primary_workspace_dir, True),),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((record,)),
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: ctx,
    )
    args = create_parser().parse_args(["repo", "list", "--json", "--workspace", "0"])

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repos"][0]["kind"] == "primary"
    assert payload["repos"][0]["path"] == ctx.primary_workspace_dir
    assert payload["repos"][0]["clones"] == [
        {
            "exists": True,
            "path": ctx.primary_workspace_dir,
            "workspace_num": 0,
        }
    ]


def test_repo_list_defaults_to_cwd_project_and_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx = _project_context(tmp_path)
    workspace_12 = tmp_path / "demo_12"
    record = _repo_record(
        tmp_path,
        name="core",
        kind="linked",
        clones=(
            RepoCloneRecord(0, str(tmp_path / "linked-core"), True),
            RepoCloneRecord(12, str(workspace_12 / "core"), False),
        ),
    )
    marker = CheckoutMarker(
        project_name="demo",
        project_key="demo",
        workspace_num=12,
        primary_workspace_dir=ctx.primary_workspace_dir,
        registry_path=str(tmp_path / "registry.json"),
    )
    requested_projects: list[str | None] = []

    def resolve_project(project: str | None) -> ProjectContext:
        requested_projects.append(project)
        return ctx

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        resolve_project,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.find_marker_from_cwd",
        lambda _cwd: (str(workspace_12), marker),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **kwargs: RepoInventory((record,)),
    )
    args = create_parser().parse_args(["repo", "list", "--json"])

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert requested_projects == [None]
    assert payload["project"] == "demo"
    assert payload["workspace_num"] == 12
    assert payload["repos"][0]["path"] == str(workspace_12 / "core")
    assert payload["repos"][0]["exists"] is False


def test_repo_list_human_renders_clone_counts_and_selected_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx = _project_context(tmp_path)
    record = _repo_record(
        tmp_path,
        name="core",
        kind="linked",
        clones=(
            RepoCloneRecord(0, str(tmp_path / "linked-core"), True),
            RepoCloneRecord(12, str(tmp_path / "demo_12" / "core"), False),
        ),
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((record,)),
    )
    args = create_parser().parse_args(
        ["repo", "list", "--project", "demo", "--workspace", "12"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Repos · demo · workspace #12" in output
    assert "WORKSPACES" in output
    assert "1/2" in output
    assert "✗" in output


def test_repo_list_human_renders_external_row_with_amber_kind(tmp_path: Path) -> None:
    clone = tmp_path / "sase" / "repos" / "external" / "gh" / "acme" / "widget"
    clone.mkdir(parents=True)
    record = RepoRecord(
        name="gh:acme/widget",
        kind="external",
        project="demo",
        project_key="demo",
        path=str(clone),
        exists=True,
        auto_clone=False,
        description=None,
        source="opened external",
        env_name=None,
        clones=(RepoCloneRecord(10, str(clone), True),),
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        width=180,
    )

    console.print(_repo_panel((record,), project="demo", workspace_num=10))

    rendered = output.getvalue()
    assert "gh:acme/widget" in rendered
    assert "external" in rendered
    assert "255;175;0" in rendered


def test_repo_list_all_includes_disabled_projects_at_primary_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = RepoRecord(
        name="old-demo",
        kind="primary",
        project="old-demo",
        project_key="old-demo",
        path=str(tmp_path / "old-demo"),
        exists=False,
        auto_clone=False,
        description=None,
        source="ProjectSpec",
        env_name=None,
        clones=(RepoCloneRecord(0, str(tmp_path / "old-demo"), False),),
    )
    calls: list[dict[str, object]] = []

    def collect(**kwargs: object) -> RepoInventory:
        calls.append(kwargs)
        return RepoInventory((record,))

    monkeypatch.setattr("sase.main.repo_handler.collect_repo_inventory", collect)
    args = create_parser().parse_args(["repo", "list", "--all", "--json"])

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert calls == [{"include_disabled": True}]
    assert payload["all_projects"] is True
    assert payload["repos"][0]["project"] == "old-demo"


def test_repo_list_rejects_all_with_project(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["repo", "list", "--all", "--project", "demo"])

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 2
    assert "--all cannot be combined with --project" in capsys.readouterr().err
