"""Parser and handler tests for ``sase repo``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest
from rich.console import Console

from sase.main.parser import create_parser, default_list_delegation_notice
from sase.main.repo_handler import (
    _match_repo_record,
    _repo_panel,
    _repo_target_context,
    _resolve_open_workspace_num,
    handle_repo_command,
)
from sase.main.repo_open_external import ExternalRepoOpenError, open_external_repo
from sase.main.workspace_handler import handle_workspace_command
from sase.main.workspace_handler_context import ProjectContext
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.repo_open_log import read_repo_open_events
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from sase.linked_repos import (
    opened_external_repo_records,
    opened_linked_repo_records,
)
from sase.workspace_provider import ExternalRepoCloneResult
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

    resolved = _match_repo_record(
        "demo",
        host_ctx=host_ctx,
        inventory=RepoInventory((primary, linked)),
    )

    assert resolved is linked


def test_repo_name_resolution_accepts_sidecar_slug(tmp_path: Path) -> None:
    host_ctx = _project_context(tmp_path)
    sidecar = _repo_record(
        tmp_path,
        name="research",
        slug="shared-research",
        kind="sidecar",
    )

    resolved = _match_repo_record(
        "shared-research",
        host_ctx=host_ctx,
        inventory=RepoInventory((sidecar,)),
    )

    assert resolved is sidecar


def test_repo_open_accepts_sidecar_slug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = _project_context(tmp_path)
    sidecar = _repo_record(
        tmp_path,
        name="research",
        slug="shared-research",
        kind="sidecar",
    )
    opened_names: list[str] = []
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((sidecar,)),
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        lambda ctx, *_args, **_kwargs: (
            opened_names.append(ctx.project_name) or sidecar.path
        ),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler._record_repo_open", lambda **_kwargs: None
    )
    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "shared-research",
            "--project",
            "demo",
            "--reason",
            "inspect reports",
            "--workspace",
            "0",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert opened_names == ["research"]
    assert capsys.readouterr().out == f"{sidecar.path}\n"


def test_unknown_repo_lists_valid_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = _project_context(tmp_path)
    inventory = RepoInventory(
        (
            _repo_record(tmp_path, name="demo", kind="primary"),
            _repo_record(tmp_path, name="core", kind="linked"),
        )
    )

    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    with pytest.raises(ExternalRepoOpenError) as exc_info:
        open_external_repo(
            "missing",
            host_ctx=host_ctx,
            workspace_num=0,
            inventory=inventory,
            reason="test",
            resolve_checkout=lambda *_args, **_kwargs: host_ctx.primary_workspace_dir,
        )

    assert "Valid repos: core, demo" in str(exc_info.value)
    assert "gh:owner/repo" in str(exc_info.value)


def test_materialized_external_is_not_a_tier_one_cleaning_target(
    tmp_path: Path,
) -> None:
    host_ctx = _project_context(tmp_path)
    external = _repo_record(tmp_path, name="gh:acme/widget", kind="external")

    assert (
        _match_repo_record(
            "gh:acme/widget",
            host_ctx=host_ctx,
            inventory=RepoInventory((external,)),
        )
        is None
    )


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

    def prepare_workspace_with_progress(*_args: object, **_kwargs: object) -> bool:
        print("Cleaning workspace...")
        return True

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
        patch(
            "sase.axe.runner_utils.prepare_workspace",
            side_effect=prepare_workspace_with_progress,
        ),
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
    assert new_output.out == f"{checkout}\n"
    assert "Cleaning workspace..." in new_output.err
    assert legacy_exit.value.code == 0
    assert legacy_output.out == f"{checkout}\n"
    assert "Cleaning workspace..." in legacy_output.err
    assert "deprecated" in legacy_output.err

    events = read_repo_open_events(project="demo")
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


def test_repo_open_registered_project_clones_locally_and_reopens_without_cleaning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_HOME", str(state))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-two")

    host_ctx = _project_context(tmp_path)
    source = tmp_path / "other-primary"
    _init_git_repo(source)
    project_record = _project_record("other", source)
    inventory = RepoInventory((_repo_record(tmp_path, name="demo", kind="primary"),))
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: host_ctx.primary_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: inventory,
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [project_record],
    )

    args = create_parser().parse_args(
        ["repo", "open", "other", "-p", "demo", "-r", "port fix", "-w", "0"]
    )
    with pytest.raises(SystemExit) as first_exit:
        handle_repo_command(args)

    assert first_exit.value.code == 0
    first = capsys.readouterr()
    expected = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "projects"
        / "other"
    )
    assert first.out == f"{expected}\n"
    assert (expected / ".git").is_dir()
    exclude = expected / ".git" / "info" / "exclude"
    exclude_lines = exclude.read_text(encoding="utf-8").splitlines()
    assert exclude_lines.count(".sase/") == 1
    assert exclude_lines.count("/sase/repos/") == 1

    dirty = expected / "keep-me.txt"
    dirty.write_text("agent work\n", encoding="utf-8")
    with pytest.raises(SystemExit) as second_exit:
        handle_repo_command(args)

    assert second_exit.value.code == 0
    assert capsys.readouterr().out == f"{expected}\n"
    assert dirty.read_text(encoding="utf-8") == "agent work\n"
    exclude_lines = exclude.read_text(encoding="utf-8").splitlines()
    assert exclude_lines.count(".sase/") == 1
    assert exclude_lines.count("/sase/repos/") == 1
    marker = opened_external_repo_records(artifacts)["other"]
    assert marker["workspace_dir"] == str(expected)
    assert marker["reason"] == "port fix"
    events = read_repo_open_events(project="demo")
    assert [event.repo_kind for event in events] == ["external", "external"]
    assert [event.repo for event in events] == ["other", "other"]


def test_repo_open_provider_ref_is_atomic_audited_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_HOME", str(state))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-two")
    host_ctx = _project_context(tmp_path)
    clone_calls: list[tuple[str, str, str]] = []

    def clone(scheme: str, ref: str, dest_dir: str) -> ExternalRepoCloneResult:
        clone_calls.append((scheme, ref, dest_dir))
        _init_git_repo(Path(dest_dir))
        return ExternalRepoCloneResult(
            canonical_name="gh:acme/widget",
            dest_dir=dest_dir,
            default_branch="main",
        )

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: host_ctx.primary_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.get_external_repo_schemes", lambda: {"gh"}
    )
    monkeypatch.setattr("sase.main.repo_open_external.clone_external_repo", clone)

    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "acme/widget",
            "-p",
            "demo",
            "-r",
            "inspect upstream",
            "-w",
            "0",
        ]
    )
    with pytest.raises(SystemExit) as first_exit:
        handle_repo_command(args)

    assert first_exit.value.code == 0
    expected = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "gh"
        / "acme"
        / "widget"
    )
    assert capsys.readouterr().out == f"{expected}\n"
    assert len(clone_calls) == 1
    assert clone_calls[0][:2] == ("gh", "acme/widget")
    assert Path(clone_calls[0][2]).parent == expected.parent
    assert Path(clone_calls[0][2]) != expected

    dirty = expected / "keep-me.txt"
    dirty.write_text("agent work\n", encoding="utf-8")
    with pytest.raises(SystemExit) as second_exit:
        handle_repo_command(args)

    assert second_exit.value.code == 0
    assert capsys.readouterr().out == f"{expected}\n"
    assert len(clone_calls) == 1
    assert dirty.is_file()
    marker = opened_external_repo_records(artifacts)["gh:acme/widget"]
    assert marker["ref"] == "gh:acme/widget"
    assert marker["reason"] == "inspect upstream"
    assert [event.repo for event in read_repo_open_events(project="demo")] == [
        "gh:acme/widget",
        "gh:acme/widget",
    ]


def test_repo_target_context_uses_durable_workspace_zero_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = _project_context(tmp_path)
    durable = tmp_path / "linked-primary"
    scoped = Path(host_ctx.primary_workspace_dir) / "sase" / "repos" / "linked" / "core"
    durable.mkdir()
    scoped.mkdir(parents=True)
    record = RepoRecord(
        name="core",
        kind="linked",
        project="demo",
        project_key="demo",
        path=str(scoped),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name="CORE",
        clones=(
            RepoCloneRecord(0, str(durable), True),
            RepoCloneRecord(10, str(scoped), True),
        ),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.load_merged_config",
        lambda: {"workspace": {"root": "adjacent"}},
    )

    target_ctx = _repo_target_context(host_ctx, record)

    assert target_ctx.primary_workspace_dir == str(durable)
    assert target_ctx.store.primary_workspace_dir == str(durable)
    assert (
        target_ctx.linked_host_primary_workspace_dir == host_ctx.primary_workspace_dir
    )


def test_repo_open_provider_failure_removes_staging_and_records_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_HOME", str(state))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    host_ctx = _project_context(tmp_path)

    def fail_clone(_scheme: str, _ref: str, dest_dir: str) -> ExternalRepoCloneResult:
        partial = Path(dest_dir)
        partial.mkdir(parents=True)
        (partial / "partial").write_text("nope", encoding="utf-8")
        raise RuntimeError("GitHub clone failed; run 'gh auth login'")

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: host_ctx.primary_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.get_external_repo_schemes", lambda: {"gh"}
    )
    monkeypatch.setattr("sase.main.repo_open_external.clone_external_repo", fail_clone)
    args = create_parser().parse_args(
        ["repo", "open", "gh:acme/widget", "-r", "inspect", "-w", "0"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "gh auth login" in output.err
    external_root = Path(host_ctx.primary_workspace_dir) / "sase" / "repos" / "external"
    assert not (external_root / "gh" / "acme" / "widget").exists()
    assert not list(external_root.rglob("*.clone-tmp-*"))
    assert opened_external_repo_records(artifacts) == {}
    assert read_repo_open_events(project="demo") == ()


def test_repo_open_missing_provider_lists_registered_schemes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = _project_context(tmp_path)
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: host_ctx.primary_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.get_external_repo_schemes", lambda: {"gl"}
    )
    args = create_parser().parse_args(
        ["repo", "open", "gh:acme/widget", "-r", "inspect", "-w", "0"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "Install or upgrade sase-github" in output.err
    assert "Registered external schemes: gl" in output.err


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
    slug: str | None = None,
    clones: tuple[RepoCloneRecord, ...] = (),
) -> RepoRecord:
    path = tmp_path / f"{kind}-{name}"
    path.mkdir(parents=True, exist_ok=True)
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
        slug=slug,
        clones=clones,
    )


def _project_record(name: str, workspace_dir: Path) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=3,
        project_name=name,
        project_dir=str(workspace_dir.parent / f"project-{name}"),
        project_file=str(workspace_dir.parent / f"project-{name}" / f"{name}.sase"),
        archive_file=None,
        workspace_dir=str(workspace_dir),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=None,
        is_project=True,
        vcs_kind="git",
    )


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)
