"""Configured-repository opening tests for ``sase repo``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.linked_repos import opened_linked_repo_records
from sase.main.parser import create_parser
from sase.main.repo_handler import (
    _match_repo_record,
    _repo_target_context,
    _resolve_open_workspace_num,
    handle_repo_command,
)
from sase.main.repo_open_external import ExternalRepoOpenError, open_external_repo
from sase.main.workspace_handler import handle_workspace_command
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from sase.repo_open_log import read_repo_open_events
from sase.workspace_provider.marker import CheckoutMarker
from sase.workspace_provider.store import WorkspaceStore
from tests.main.repo_handler_helpers import project_context, repo_record


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
    host_ctx = project_context(tmp_path)
    primary = repo_record(tmp_path, name="demo", kind="primary")
    linked = repo_record(tmp_path, name="demo", kind="linked")

    resolved = _match_repo_record(
        "demo",
        host_ctx=host_ctx,
        inventory=RepoInventory((primary, linked)),
    )

    assert resolved is linked


def test_repo_name_resolution_accepts_sidecar_slug(tmp_path: Path) -> None:
    host_ctx = project_context(tmp_path)
    sidecar = repo_record(
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
    host_ctx = project_context(tmp_path)
    sidecar = repo_record(
        tmp_path,
        name="research",
        slug="shared-research",
        kind="sidecar",
    )
    opened_names: list[str] = []

    def prepare_checkout(ctx: ProjectContext, *_args: object, **_kwargs: object) -> str:
        opened_names.append(ctx.project_name)
        return sidecar.path

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
        prepare_checkout,
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


def test_repo_open_hidden_agents_stays_machine_scoped_for_numbered_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    stable = tmp_path / "state" / "projects" / "demo" / "repos" / "agents"
    stable.mkdir(parents=True)
    agents = RepoRecord(
        name="agents",
        kind="sidecar",
        project="demo",
        project_key="demo",
        path=str(stable),
        exists=True,
        auto_clone=False,
        description="Hidden agent data.",
        source="test",
        env_name=None,
        slug="demo--agents",
        remote_url="git@example.test:acme/demo--agents.git",
        clones=(
            RepoCloneRecord(0, str(stable), True),
            RepoCloneRecord(12, str(stable), True),
        ),
    )
    materialize_calls: list[dict[str, object]] = []
    audit_calls: list[dict[str, object]] = []

    def materialize(**kwargs: object) -> str:
        materialize_calls.append(kwargs)
        return str(stable)

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((agents,)),
    )
    monkeypatch.setattr("sase.main.repo_handler.load_merged_config", lambda: {})
    monkeypatch.setattr(
        "sase.linked_repos.materialize_linked_repo_workspace",
        materialize,
    )
    monkeypatch.setattr(
        "sase.sdd.files.ensure_bare_git_sdd_initialized", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "sase.axe.runner_workspace.prepare_workspace",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.linked_repos.record_opened_linked_repo",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler._record_repo_open",
        lambda **kwargs: audit_calls.append(kwargs),
    )
    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "demo--agents",
            "--project",
            "demo",
            "--reason",
            "inspect agent archive",
            "--workspace",
            "12",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    assert materialize_calls
    assert {call["workspace_dir"] for call in materialize_calls} == {str(stable)}
    assert audit_calls == [
        {
            "host_ctx": host_ctx,
            "repo_name": "agents",
            "repo_kind": "sidecar",
            "workspace_num": 12,
            "path": str(stable),
            "reason": "inspect agent archive",
        }
    ]
    assert capsys.readouterr().out == f"{stable}\n"


def test_unknown_repo_lists_valid_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = project_context(tmp_path)
    inventory = RepoInventory(
        (
            repo_record(tmp_path, name="demo", kind="primary"),
            repo_record(tmp_path, name="core", kind="linked"),
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
    host_ctx = project_context(tmp_path)
    external = repo_record(tmp_path, name="gh:acme/widget", kind="external")

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
    host_ctx = project_context(tmp_path)
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
    host_ctx = project_context(tmp_path)
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
            "sase.axe.runner_workspace.prepare_workspace",
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


def test_repo_target_context_uses_durable_workspace_zero_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = project_context(tmp_path)
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
