"""Parser and handler tests for ``sase repo``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.parser import create_parser, default_list_delegation_notice
from sase.main.repo_handler import (
    _resolve_open_workspace_num,
    _resolve_repo_record,
    handle_repo_command,
)
from sase.main.workspace_handler import handle_workspace_command
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_open_log import read_repo_open_events, repo_open_log_path
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from sase.linked_repos import opened_linked_repo_records
from sase.workspace_provider.marker import CheckoutMarker
from sase.workspace_provider.store import WorkspaceStore


def test_repo_parser_defaults_to_list() -> None:
    args = create_parser().parse_args(["repo"])
    assert args.command == "repo"
    assert args.repo_subcommand == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase repo'; delegating to 'sase repo list'."
    )


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
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda project: requested_projects.append(project) or ctx,
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


def test_repo_open_parser_requires_reason_and_accepts_context_options() -> None:
    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "core",
            "--project",
            "demo",
            "--reason",
            "fix bindings",
            "--workspace",
            "12",
        ]
    )

    assert args.repo_subcommand == "open"
    assert args.repo == "core"
    assert args.project == "demo"
    assert args.reason == "fix bindings"
    assert args.workspace == 12

    with pytest.raises(SystemExit):
        create_parser().parse_args(["repo", "open", "core"])


def test_repo_name_resolution_prefers_linked_over_primary_alias(
    tmp_path: Path,
) -> None:
    host_ctx = _project_context(tmp_path)
    primary = _repo_record(tmp_path, name="demo", kind="primary")
    linked = _repo_record(tmp_path, name="demo", kind="linked")

    resolved = _resolve_repo_record(
        "demo",
        host_ctx=host_ctx,
        inventory=RepoInventory((primary, linked)),
    )

    assert resolved is linked


def test_unknown_repo_lists_valid_candidates(
    tmp_path: Path,
) -> None:
    host_ctx = _project_context(tmp_path)
    inventory = RepoInventory(
        (
            _repo_record(tmp_path, name="demo", kind="primary"),
            _repo_record(tmp_path, name="core", kind="linked"),
        )
    )

    with pytest.raises(ValueError, match="Valid repos: core, demo"):
        _resolve_repo_record("missing", host_ctx=host_ctx, inventory=inventory)


def test_workspace_inference_uses_matching_checkout_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = _project_context(tmp_path)
    marker = CheckoutMarker(
        project_name="demo",
        project_key="demo",
        workspace_num=12,
        primary_workspace_dir=host_ctx.primary_workspace_dir,
        registry_path=str(tmp_path / "registry.json"),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )

    assert _resolve_open_workspace_num(host_ctx, None, cwd=tmp_path) == 12


def test_workspace_inference_treats_primary_checkout_as_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = _project_context(tmp_path)
    cwd = Path(host_ctx.primary_workspace_dir) / "src"
    cwd.mkdir()
    monkeypatch.setattr(
        "sase.main.repo_handler.find_marker_from_cwd",
        lambda _cwd: None,
    )

    assert _resolve_open_workspace_num(host_ctx, None, cwd=cwd) == 0


def test_repo_open_and_legacy_alias_share_audit_and_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-one")

    host_primary = tmp_path / "demo"
    linked_primary = tmp_path / "core"
    host_primary.mkdir()
    linked_primary.mkdir()
    project_dir = home / ".sase" / "projects" / "demo"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "demo.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {host_primary}\n",
        encoding="utf-8",
    )
    host_ctx = ProjectContext(
        project_name="demo",
        project_file=str(project_file),
        primary_workspace_dir=str(host_primary),
        store=WorkspaceStore(str(host_primary)),
    )
    linked_ctx = ProjectContext(
        project_name="core",
        project_file=str(home / ".sase" / "projects" / "core" / "core.sase"),
        primary_workspace_dir=str(linked_primary),
        store=WorkspaceStore(str(linked_primary)),
        is_sibling=True,
        is_configured_linked_repo=True,
        linked_host_primary_workspace_dir=str(host_primary),
    )
    linked = RepoRecord(
        name="core",
        kind="linked",
        project="demo",
        project_key="demo",
        path=str(linked_primary),
        exists=True,
        auto_clone=False,
        description=None,
        source="linked_repos config",
        env_name="CORE",
    )
    checkout = str(tmp_path / "demo_12" / "sase" / "repos" / "linked" / "core")

    def resolve_context(project: str | None) -> ProjectContext:
        return linked_ctx if project == "core" else host_ctx

    with (
        patch(
            "sase.main.workspace_handler._resolve_project_context",
            side_effect=resolve_context,
        ),
        patch(
            "sase.main.repo_handler.collect_repo_inventory",
            return_value=RepoInventory((linked,)),
        ),
        patch("sase.main.repo_handler.load_merged_config", return_value={}),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.main.workspace_handler._resolve_checkout_path",
            return_value=checkout,
        ),
        patch("sase.axe.runner_utils.prepare_workspace", return_value=True),
    ):
        new_args = create_parser().parse_args(
            ["repo", "open", "core", "-p", "demo", "-r", "same reason", "-w", "12"]
        )
        with pytest.raises(SystemExit) as new_exit:
            handle_repo_command(new_args)
        new_output = capsys.readouterr()

        legacy_args = create_parser().parse_args(
            ["workspace", "open", "-p", "core", "-r", "same reason", "12"]
        )
        with pytest.raises(SystemExit) as legacy_exit:
            handle_workspace_command(legacy_args)
        legacy_output = capsys.readouterr()

    assert new_exit.value.code == 0
    assert new_output.out.strip() == checkout
    assert new_output.err == ""
    assert legacy_exit.value.code == 0
    assert legacy_output.out.strip() == checkout
    assert "deprecated" in legacy_output.err

    events = read_repo_open_events(log_path=repo_open_log_path("demo"))
    assert len(events) == 2
    comparable = [
        (
            event.project,
            event.repo,
            event.repo_kind,
            event.workspace_num,
            event.path,
            event.agent_name,
            event.reason,
        )
        for event in events
    ]
    assert comparable[0] == comparable[1]
    marker = opened_linked_repo_records(tmp_path / "artifacts")["core"]
    assert marker["workspace_dir"] == checkout
    assert marker["reason"] == "same reason"


def _project_context(tmp_path: Path) -> ProjectContext:
    primary = tmp_path / "demo"
    primary.mkdir(exist_ok=True)
    return ProjectContext(
        project_name="demo",
        project_file=str(tmp_path / "demo.sase"),
        primary_workspace_dir=str(primary),
        store=WorkspaceStore(str(primary)),
    )


def _repo_record(
    tmp_path: Path,
    *,
    name: str,
    kind: str,
    clones: tuple[RepoCloneRecord, ...] = (),
) -> RepoRecord:
    path = tmp_path / f"{kind}-{name}"
    path.mkdir(exist_ok=True)
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project="demo",
        project_key="demo",
        path=str(path),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        clones=clones,
    )
