"""Configured alias and slug redirect tests for ``sase repo open``."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.repo_handler import handle_repo_command
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from tests.main.repo_handler_helpers import (
    project_context,
    project_record,
    repo_record,
    set_git_origin,
)


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


def test_repo_open_registered_project_alias_redirects_to_linked_by_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    linked = repo_record(tmp_path, name="sase-core", kind="linked")
    registered_project = replace(
        project_record("upstream-core", Path(linked.path)),
        aliases=["core-alias"],
    )
    opened_projects: list[str] = []
    audit_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((linked,)),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [registered_project],
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        lambda ctx, *_args, **_kwargs: (
            opened_projects.append(ctx.project_name) or linked.path
        ),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.clone_external_repo",
        lambda *_args, **_kwargs: pytest.fail("external clone must not run"),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler._record_repo_open",
        lambda **kwargs: audit_calls.append(kwargs),
    )
    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "core-alias",
            "--project",
            "demo",
            "--reason",
            "inspect upstream",
            "--workspace",
            "0",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    output = capsys.readouterr()
    assert exc_info.value.code == 0
    assert output.out == f"{linked.path}\n"
    assert "matches linked repo 'sase-core'" in output.err
    assert "registered project's primary checkout is that linked repo" in output.err
    assert opened_projects == ["sase-core"]
    assert audit_calls == [
        {
            "host_ctx": host_ctx,
            "repo_name": "sase-core",
            "repo_kind": "linked",
            "workspace_num": 0,
            "path": linked.path,
            "reason": "inspect upstream",
        }
    ]


def test_repo_open_registered_project_alias_redirects_to_linked_by_remote_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    primary = replace(
        repo_record(tmp_path, name="demo", kind="primary"),
        path=host_ctx.primary_workspace_dir,
        clones=(RepoCloneRecord(12, host_ctx.primary_workspace_dir, True),),
    )
    workspace_core = tmp_path / "workspace-12-core"
    workspace_core.mkdir()
    linked = repo_record(
        tmp_path,
        name="sase-core",
        kind="linked",
        clones=(RepoCloneRecord(12, str(workspace_core), True),),
    )
    set_git_origin(workspace_core, "git@github.com:sase-org/sase-core.git")
    source = tmp_path / "other-primary"
    source.mkdir()
    set_git_origin(source, "https://github.com/SASE-Org/SASE-Core.git")
    registered_project = project_record("upstream-core", source)
    audit_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((primary, linked)),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [registered_project],
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        lambda *_args, **_kwargs: str(workspace_core),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.clone_external_repo",
        lambda *_args, **_kwargs: pytest.fail("external clone must not run"),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler._record_repo_open",
        lambda **kwargs: audit_calls.append(kwargs),
    )
    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "upstream-core",
            "--project",
            "demo",
            "--reason",
            "inspect upstream",
            "--workspace",
            "12",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    output = capsys.readouterr()
    assert exc_info.value.code == 0
    assert output.out == f"{workspace_core}\n"
    assert "same supported remote identity" in output.err
    assert audit_calls == [
        {
            "host_ctx": host_ctx,
            "repo_name": "sase-core",
            "repo_kind": "linked",
            "workspace_num": 12,
            "path": str(workspace_core),
            "reason": "inspect upstream",
        }
    ]


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
